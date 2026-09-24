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


class EngineStopped(BaseException):
    """ผู้ใช้กด Stop - ทุก request ถัดไปของทุกเธรดโยนตัวนี้ ให้ไอดีที่ค้างอยู่วางมือทันที

    BaseException ไม่ใช่ Exception โดยตั้งใจ: flows มี `except Exception` ที่ retry แล้วสุดท้าย
    ตอบ FAIL -> ไฟล์จะไปลง "login failed" ทั้งที่ไอดีไม่ได้เสีย แค่ถูกสั่งหยุด ตัวนี้ต้องทะลุขึ้นไป
    ถึง EnginePool ซึ่งคืนไฟล์เข้า input/ ให้ทำต่อรอบหน้า
    """


class _GaugedQuota:
    """โควตา mint ของ lane ที่นับเธรดที่ยืนรอเข้า gauge เดียวกับถัง req/s

    ให้ autoscaler เห็นว่าโหมด GenID ชนเพดาน 2 mint/นาที/IP อยู่ ไม่ใช่เธรดน้อยเกิน
    """

    def __init__(self, quota, lane) -> None:
        self._quota = quota
        self._lane = lane

    def acquire(self) -> None:
        self._lane._check_stop()
        self._lane._wait_begin()
        try:
            self._quota.acquire()
        finally:
            self._lane._wait_end()
        self._lane._check_stop()   # รอโควตาได้ถึงนาที - ห้าม mint ต่อถ้าระหว่างนั้นถูกสั่งหยุด

    def __getattr__(self, name):
        return getattr(self._quota, name)


class ProxyLane:
    def __init__(self, name: str, parts, rps: float, threads: int,
                 clock=None, sleep=None) -> None:
        self.name = name
        self.parts = parts
        self.rps = float(rps)
        # เป้าจำนวนเธรดของ lane นี้ - โหมดตั้งเองคงที่ โหมด auto ให้ engine.autoscale ขยับ
        self.threads = threads
        self.running = 0          # เธรด worker ที่ยังอยู่บน lane นี้จริงตอนนี้ (pool นับ)
        self.alive = True
        self.stopping = False     # stop() ตั้ง (EnginePool.request_stop) - request ถัดไปโยน EngineStopped
        self._stop_evt = threading.Event()
        kw = {}
        if clock is not None:
            kw["clock"] = clock
        if sleep is not None:
            kw["sleep"] = sleep
        self.bucket = ratelimit.TokenBucket(rate=rps, **kw)
        # C6 (final review): the guest-mint quota (game-api allows 2 mints/IP/~60s) used to
        # be ratelimit.quota_for("linegame-auth", ...) - ONE quota cached on the name alone
        # for the WHOLE PROCESS, so every lane shared a single 2-per-minute budget instead
        # of getting its own (a regression from the old fleet's 2 per process = 2 per
        # proxy). Each lane now owns an in-memory quota exactly like it owns its own
        # TokenBucket (spec sec 7/14.3: "ผูกกับ lane ไม่ใช่ทั้งโปรแกรม" - 50 proxy must mint
        # 100 accounts/minute, not 2 for the whole fleet). Consumed by
        # tools/new_account.py's _do() via rangers_api.current_lane().auth_quota.
        limit, window = ratelimit.parse_quota_spec(ratelimit.AUTH_QUOTA)
        self._lock = threading.Lock()
        self.auth_quota = _GaugedQuota(ratelimit.InMemoryQuota(limit, window, **kw), self)
        self._fails = 0
        # ตัวนับให้ autoscaler: เธรดที่ยืนรอถัง/โควตาอยู่ตอนนี้, request ที่ได้โทเคนแล้ว (สะสม),
        # คำตอบ 429/503 ที่เซิร์ฟเวอร์ตีกลับ (สะสม)
        self._waiting = 0
        self._sent = 0
        self._limited = 0

    def _wait_begin(self) -> None:
        with self._lock:
            self._waiting += 1

    def _wait_end(self) -> None:
        with self._lock:
            self._waiting -= 1

    def stop(self) -> None:
        self.stopping = True
        self._stop_evt.set()

    def _check_stop(self) -> None:
        if self.stopping:
            raise EngineStopped()

    def nap(self, seconds: float) -> None:
        """time.sleep ที่ตื่นทันทีเมื่อกด Stop แล้วโยน EngineStopped - ให้ flows ใช้รอ retry
        (5-15 วิ) ไอดีที่กำลังรออยู่จะได้คืน input/ ทันที ไม่ต้องรอหลับจนครบ"""
        self._check_stop()
        self._stop_evt.wait(seconds)
        self._check_stop()

    def acquire(self) -> None:
        """ทุก request ของทุกโหมดผ่านตรงนี้ (rangers_api และ new_account) จึงเป็นจุดเดียวที่
        ตัดไอดีที่ค้างอยู่ได้ทันทีเมื่อกด Stop - เช็คทั้งก่อนและหลังรอถัง"""
        self._check_stop()
        self._wait_begin()
        try:
            self.bucket.acquire()
        finally:
            self._wait_end()
        self._check_stop()
        with self._lock:
            self._sent += 1

    def note_limited(self) -> None:
        """เซิร์ฟเวอร์ตอบ 429/503 (nginx ต่อ IP) - สัญญาณให้ autoscaler ถอยเธรด"""
        with self._lock:
            self._limited += 1

    def counters(self) -> tuple[int, int, int]:
        """(เธรดที่รอถัง/โควตาอยู่ตอนนี้, request สะสม, 429/503 สะสม)"""
        with self._lock:
            return self._waiting, self._sent, self._limited

    def enter(self) -> None:
        with self._lock:
            self.running += 1

    def leave(self) -> None:
        with self._lock:
            self.running -= 1

    def retire_one(self) -> bool:
        """เธรดเกินเป้า -> คืน True และหักตัวเองออกจาก running ทันที (ในล็อก)

        หักในล็อกเดียวกับที่เช็ค ไม่งั้นเธรดสิบตัวที่เช็คพร้อมกันตอนเกินเป้าหนึ่งตัวจะออกไปทั้งสิบ
        """
        with self._lock:
            if self.running > self.threads:
                self.running -= 1
                return True
            return False

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
