"""ปรับจำนวนเธรดของแต่ละ lane เองระหว่างรัน - เป้าคือบัญชี/นาทีสูงสุด ไม่ต้องให้ผู้ใช้เดาเลขเอง

เลขที่ดีที่สุดเปลี่ยนตามโหมด: Login อิ่มที่ ~128 เธรดต่อ IP (ถัง 80 req/s, ~26 request ต่อบัญชี),
GenID อิ่มที่ไม่กี่เธรดเพราะโควตา mint 2 ครั้ง/นาที/IP, Stage/Quest ยิงถี่กว่าต่อเธรดจึงอิ่มเร็วกว่า
Login - เลขเดียวในช่องตั้งค่าจึงผิดเสมอสำหรับบางโหมด (threadcount ตัวเดียวใช้ร่วมทุกโหมด)

สัญญาณสามตัว วัดต่อ lane ทุก WINDOW วินาที:
- req/s ที่ lane ส่งออกจริง: บัญชีในโหมดเดียวกันยิง request ชุดเดิม req/s จึงแปรตามบัญชี/นาที
  แต่วัดได้ในไม่กี่วินาที - นับบัญชีที่เสร็จใช้ไม่ได้กับ Stage ที่ใช้ ~9 นาทีต่อใบ
- สัดส่วนเธรดที่ยืนรอถัง req/s หรือโควตา mint ของ lane: รอเยอะ = ชนเพดานของ IP แล้ว
  เพิ่มเธรดได้แค่คิวยาวขึ้น -> ตัดเหลือพอให้ถังเต็มพอดี
- 429/503 จากเซิร์ฟเวอร์: IP นี้โดนตีกลับ -> ถอย

นอกนั้นเพิ่มทีละ 50% แล้วเช็คว่าคุ้มไหม: req/s ต้องขึ้นอย่างน้อย MIN_GAIN ของสัดส่วนเธรดที่เพิ่ม
ไม่งั้นแปลว่าคอขวดอยู่ที่อื่น (CPU/GIL ของเครื่อง, เซิร์ฟเวอร์ช้า) -> กลับไปเลขเดิม รอ PROBE_AFTER
แล้วลองใหม่ เพราะสภาพเน็ตและเซิร์ฟเวอร์เปลี่ยนได้ระหว่างรันยาว ๆ

ตัวนี้ขยับแค่ lane.threads (เป้า) - pool เป็นคนสปอว์นเธรดเพิ่ม และเธรดที่เกินเป้าออกเองหลังจบบัญชี
ที่ถืออยู่ (ไม่มีการฆ่าเธรดกลางบัญชี)
"""
from __future__ import annotations

import math

WINDOW = 10.0          # วินาทีต่อการตัดสินใจหนึ่งครั้ง
START = 32             # เธรดต่อ lane ตอนเริ่ม สำหรับโหมดที่ไม่มีใน START_BY_MODE (Stage/Quest)
# จุดเริ่มต่อโหมด (ผู้ใช้กำหนด 2026-09-24): GenID ติดโควตา mint 2 ครั้ง/นาที/IP ตั้งแต่เธรดแรก
# เริ่มเยอะก็แค่ยืนรอโควตา ส่วน Login อิ่มที่ ~128 ต่อ IP เริ่ม 32 ถึงจุดนั้นในสี่รอบ (~40 วิ)
# Level3 อยู่กลุ่มเดียวกับ Login ใน GUI (_isLoginMode) และ relogin จากไฟล์เหมือนกัน
START_BY_MODE = {
    "ranger_api_GenID": 2,
}
LANE_MAX = 256         # เพดานต่อ lane: IP เดียวอิ่มที่ ~128 ในโหมด Login (วัด 2026-09-23)
GROW = 1.5
BLOCKED_TRIM = 0.35    # เธรดรอถัง/โควตาเกินสัดส่วนนี้ = เกินจุดอิ่ม ตัดลง
BLOCKED_FULL = 0.10    # ระหว่าง FULL กับ TRIM = อิ่มพอดี ค้างไว้
HEADROOM = 1.25        # ตอนตัด เผื่อเธรดทำงานไว้เกินที่ถังต้องการ 25% ให้ถังไม่ว่าง
MIN_GAIN = 0.2         # req/s ต้องขึ้น >= 20% ของสัดส่วนเธรดที่เพิ่ม (เพิ่ม 50% -> ต้องได้ >= 10%)
PROBE_AFTER = 60.0     # หลังถอย รอเท่านี้ก่อนลองเพิ่มอีก
LIMITED_MIN = 3        # 429/503 อย่างน้อยกี่ครั้งในหนึ่งรอบถึงนับว่าโดนตีกลับจริง
LIMITED_FRAC = 0.02    # และต้องเกินสัดส่วนนี้ของ request ในรอบนั้น
BACKOFF = 0.75


def start_for(mode: str) -> int:
    """จำนวนเธรดต่อ lane ตอนเริ่มของโหมดนี้ - autoscaler ขยับต่อจากเลขนี้"""
    return START_BY_MODE.get(mode, START)


class _LaneState:
    def __init__(self, lane, now: float) -> None:
        self.lane = lane
        self.state = "grow"
        self.hold_until = 0.0
        self.trial = None      # (เป้าก่อนเพิ่ม, req/s ก่อนเพิ่ม, เธรดเฉลี่ยก่อนเพิ่ม)
        self.reset(now)

    def reset(self, now: float) -> None:
        _waiting, self.sent0, self.limited0 = self.lane.counters()
        self.t0 = now
        self.wait_sum = 0.0
        self.run_sum = 0.0
        self.samples = 0


class AutoScaler:
    def __init__(self, lanes, lane_max: int = LANE_MAX, total_max: int = 4096,
                 now: float = 0.0, window: float | None = None,
                 probe_after: float | None = None) -> None:
        self.lane_max = max(1, int(lane_max))
        self.total_max = max(1, int(total_max))
        self.window = WINDOW if window is None else window
        self.probe_after = PROBE_AFTER if probe_after is None else probe_after
        self._states = [_LaneState(lane, now) for lane in lanes]
        self._last = now

    def tick(self, now: float) -> bool:
        """เรียกทุกรอบของ supervisor: เก็บตัวอย่าง gauge และตัดสินใจเมื่อครบ window

        คืน True เมื่อเป้าของ lane ไหนเปลี่ยน
        """
        for st in self._states:
            waiting, _sent, _limited = st.lane.counters()
            st.wait_sum += waiting
            st.run_sum += st.lane.running
            st.samples += 1
        if now - self._last < self.window:
            return False
        self._last = now
        changed = False
        for st in self._states:
            changed |= self._decide(st, now)
        return changed

    def _cap(self, st) -> int:
        others = sum(x.lane.threads for x in self._states if x is not st and x.lane.alive)
        return max(1, min(self.lane_max, self.total_max - others))

    def _decide(self, st, now: float) -> bool:
        lane = st.lane
        _waiting, sent, limited = lane.counters()
        dt = max(1e-6, now - st.t0)
        sent_n = sent - st.sent0
        limited_n = limited - st.limited0
        rate = sent_n / dt
        run_avg = st.run_sum / st.samples if st.samples else float(lane.running)
        blocked = st.wait_sum / st.run_sum if st.run_sum > 0 else 0.0
        st.reset(now)
        if not lane.alive:
            st.trial = None            # lane ตาย: pool ไม่สปอว์นให้อยู่แล้ว ผลที่วัดตอนนี้ไม่มีความหมาย
            return False

        old = lane.threads
        new = old
        if limited_n >= LIMITED_MIN and limited_n > LIMITED_FRAC * max(1, sent_n):
            new = max(1, int(min(old, run_avg) * BACKOFF))
            st.state, st.trial, st.hold_until = "backoff", None, now + self.probe_after
        elif blocked >= BLOCKED_TRIM:
            # เธรดที่ทำงานจริง (ไม่ได้ยืนรอ) คือจำนวนที่ถังรับไหว เก็บไว้เท่านั้นบวกเผื่อ
            want = math.ceil(run_avg * (1.0 - blocked) * HEADROOM) + 1
            new = max(1, min(old, want))
            st.state, st.trial = "full", None
        elif blocked >= BLOCKED_FULL:
            st.state, st.trial = "full", None
        else:
            if st.trial is not None:
                prev_target, prev_rate, prev_run = st.trial
                st.trial = None
                expected = run_avg / prev_run - 1.0 if prev_run > 0 else 0.0
                if prev_rate > 0:
                    gained = rate / prev_rate - 1.0
                else:
                    gained = 1.0 if rate > 0 else 0.0
                if expected > 0 and gained < MIN_GAIN * expected:
                    new = prev_target
                    st.state, st.hold_until = "plateau", now + self.probe_after
            # โตเฉพาะตอนเธรดครบเป้าจริง: ถ้าคิวใกล้หมดหรือ pool หยุดสปอว์นแล้ว เพิ่มเป้าก็ไม่มีเธรดมาเติม
            if new == old and now >= st.hold_until and run_avg >= 0.9 * old:
                grown = min(self._cap(st), max(old + 1, math.ceil(old * GROW)))
                if grown > old:
                    new = grown
                    st.state, st.trial = "grow", (old, rate, run_avg)
                else:
                    st.state = "max"
        lane.threads = new
        return new != old

    def summary(self) -> str:
        """สถานะที่ lane ส่วนใหญ่อยู่ - GUI แปลเป็นข้อความสั้น ๆ ข้างจำนวนเธรด"""
        counts: dict[str, int] = {}
        for st in self._states:
            if st.lane.alive:
                counts[st.state] = counts.get(st.state, 0) + 1
        return max(counts, key=counts.get) if counts else ""
