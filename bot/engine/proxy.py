"""1 proxy = 1 IP = 1 งบ request = กลุ่มเธรดของตัวเอง

เพดานของเกมคือ ~100 req/s ต่อ IP การเพิ่มเธรดบน IP เดิมจึงไม่ได้งานเพิ่ม ได้แค่คิวที่ยาวขึ้น
สิ่งที่เพิ่มงานได้จริงมีอย่างเดียวคือเพิ่ม IP โครงนี้จึงผูกงบกับ lane ไม่ใช่กับทั้งโปรแกรม
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))
import ratelimit  # noqa: E402

# connect ไม่ติดกี่ครั้งติดกันถึงถือว่า proxy ตาย หนึ่งครั้งคือสายหลุดธรรมดา ซึ่งเกิดได้
# ตลอดเวลาบนเน็ตที่ปกติดี ถอด lane เพราะเรื่องนั้นคือการตัดกำลังตัวเองฟรี ๆ
LANE_DEATH = 3


class ProxyLane:
    def __init__(self, name: str, parts, rps: float, threads: int,
                 clock=None, sleep=None) -> None:
        self.name = name
        self.parts = parts
        self.threads = threads
        self.alive = True
        kw = {}
        if clock is not None:
            kw["clock"] = clock
        if sleep is not None:
            kw["sleep"] = sleep
        self.bucket = ratelimit.TokenBucket(rate=rps, **kw)
        self._lock = threading.Lock()
        self._fails = 0

    def acquire(self) -> None:
        self.bucket.acquire()

    def note_ok(self) -> None:
        with self._lock:
            self._fails = 0

    def note_fail(self) -> bool:
        """คืน True เฉพาะครั้งที่ทำให้ lane ตาย ผู้เรียกจะได้รายงานครั้งเดียว ไม่ใช่ทุกครั้ง"""
        with self._lock:
            self._fails += 1
            if self._fails >= LANE_DEATH and self.alive:
                self.alive = False
                return True
            return False

    def revive(self) -> None:
        with self._lock:
            self._fails = 0
            self.alive = True


class ProxyPool:
    def __init__(self, proxies, rps: float, threads_per: int,
                 max_threads: int = 4096, clock=None, sleep=None) -> None:
        entries = [p.strip() for p in (proxies or []) if p and p.strip()]
        self.lanes: list[ProxyLane] = []
        if not entries:
            self.lanes.append(ProxyLane("direct", None, rps, threads_per, clock, sleep))
        else:
            for entry in entries:
                # proxy_parts โยน ValueError เมื่อรูปแบบผิด ปล่อยให้ขึ้นไปถึงผู้เรียก:
                # ยอมรับเงียบ ๆ แปลว่า engine สตาร์ทแล้ววิ่งผ่าน IP ของเครื่องตัวเองแทน
                parts = ratelimit.proxy_parts(entry)
                host, port = parts[0], parts[1]
                self.lanes.append(
                    ProxyLane("%s:%s" % (host, port), parts, rps, threads_per, clock, sleep))

        wanted = sum(x.threads for x in self.lanes)
        self.capped = 0
        if wanted > max_threads:
            # หารเฉลี่ยลงมา อย่างน้อย lane ละ 1 เธรด แล้วบันทึกส่วนต่างไว้ให้ผู้เรียกบอกผู้ใช้
            per = max(1, max_threads // len(self.lanes))
            for lane in self.lanes:
                lane.threads = per
            self.capped = wanted - sum(x.threads for x in self.lanes)

    def alive_lanes(self) -> list[ProxyLane]:
        return [x for x in self.lanes if x.alive]

    def total_threads(self) -> int:
        return sum(x.threads for x in self.lanes)
