"""ปรับจำนวนเธรด *และ* งบ req/s ของแต่ละ lane เองระหว่างรัน - เป้าคือบัญชี/นาทีสูงสุด

เลขที่ดีที่สุดเปลี่ยนตามโหมด: GenID อิ่มที่ไม่กี่เธรดเพราะโควตา mint 2 ครั้ง/นาที/IP, Login ยิง
~19 request ต่อบัญชี, Stage/Quest ยิงถี่กว่าต่อเธรด - เลขเดียวในช่องตั้งค่าจึงผิดเสมอสำหรับบางโหมด

สองคันโยก:
1. งบ req/s ต่อ IP (ถังโทเคนของ lane) - เดิมตายตัวที่ apirps (80) รันจริง 2026-09-25 โหมด Login
   ค้างที่ 108 เธรด ~250 บัญชี/นาทีตลอด 14 นาที เพราะชนถังของเราเอง ไม่ใช่ของเซิร์ฟเวอร์ (วัด
   2026-09-22: nginx ตอบ 429 แค่ 0.4% ที่ 106 req/s, 2% ที่ 140) ตอนนี้ขยายงบทีละ 15% ตราบที่เธรด
   ยืนรอถังและ 429/503 ไม่เกิน 0.5% หดลง 20% เมื่อเกิน 2% แล้วพัก RPS_HOLD วิ (AIMD)
2. จำนวนเธรด - เพิ่มทีละ 50% ตราบที่ req/s ที่ใช้ได้จริงยังขึ้นตาม (ขึ้นไม่ถึง MIN_GAIN ของสัดส่วนที่
   เพิ่ม = คอขวดอยู่ที่อื่น เช่น CPU/GIL หรือเซิร์ฟเวอร์ช้า -> กลับเลขเดิม รอ PROBE_AFTER แล้วลองใหม่)
   ตัดลงเมื่อเธรดยืนรอมากเกินที่งบจะขยายได้แล้ว (โควตา mint หรืองบชนเพดาน) ถอย 25% เมื่อต่อไม่ติดซ้ำ

ทั้งสองคันโยกจำ "เพดานที่เคยชน" (ตอนโดนตีกลับหรือเพิ่มแล้วไม่คุ้ม) ก้าวใหญ่ใช้แค่ตอนยังห่างเพดาน
พอก้าวใหญ่จะข้ามมันก็เปลี่ยนเป็นก้าวเล็ก (เธรด x1.1, งบ x1.03) และเมื่อผ่านเพดานไปได้โดยไม่มีปัญหา
เพดานเลื่อนตามขึ้นไป (ยังก้าวเล็กต่อ ~2.6 เท่า/นาทีสำหรับเธรด ตามสภาพที่เปลี่ยนได้ทัน) - แบบ
slow start / congestion avoidance ของ TCP รันจริง 2026-09-25 หลังเซิร์ฟเวอร์ช้าลงตอน 02:13 เธรดแกว่ง
156 -> 119 -> 96 -> 135 -> 89 -> 141 ทุกนาที เพราะหลังถอยแล้วโตกลับ x1.5 ชนขอบเดิมซ้ำ ไอดี/นาทีตกจาก
~250 เหลือ ~190

สัญญาณวัดต่อ lane ทุก WINDOW วินาที (ProxyLane.signals()): req/s ที่ส่งจริง (บัญชีในโหมดเดียวกัน
ยิง request ชุดเดิม req/s จึงแปรตามบัญชี/นาที แต่วัดได้ในไม่กี่วินาที ไม่ต้องรอ Stage ที่ใช้ ~9 นาทีต่อใบ),
สัดส่วนเธรดที่ยืนรอถัง/รอโควตา, 429/503 และการต่อไม่ติด

ตัวนี้ขยับแค่ lane.threads (เป้า) กับ lane.rps - pool เป็นคนสปอว์นเธรดเพิ่ม และเธรดที่เกินเป้าออกเอง
หลังจบบัญชีที่ถืออยู่ (ไม่มีการฆ่าเธรดกลางบัญชี)
"""
from __future__ import annotations

import math

WINDOW = 5.0           # วินาทีต่อการตัดสินใจหนึ่งครั้ง - ~400 request ต่อรอบที่ 80 req/s พอให้สัดส่วนไม่แกว่ง
START = 32             # เธรดต่อ lane ตอนเริ่ม สำหรับโหมดที่ไม่มีใน START_BY_MODE
# จุดเริ่มต่อโหมด (ผู้ใช้กำหนด 2026-09-24): GenID ติดโควตา mint 2 ครั้ง/นาที/IP ตั้งแต่เธรดแรก
# เริ่มเยอะก็แค่ยืนรอโควตา
START_BY_MODE = {
    "ranger_api_GenID": 2,
}
LANE_MAX = 512         # เพดานต่อ lane: งบ req/s ที่ขยายได้ถึง ~150 ต้องใช้เธรดเกิน 256 ในโหมด Login
GROW = 1.5
GROW_NEAR = 1.1        # ก้าวเมื่อก้าวใหญ่จะข้ามเพดานเธรดที่เคยชน
BLOCKED_TRIM = 0.35    # เธรดรอถัง/โควตาเกินสัดส่วนนี้ (และขยายงบไม่ได้แล้ว) = เกินจุดอิ่ม ตัดลง
BLOCKED_FULL = 0.10    # รอเกินนี้ = งบ req/s คือคอขวด -> ขยายงบ (ถ้าเซิร์ฟเวอร์ยังไม่ตีกลับ)
HEADROOM = 1.25        # ตอนตัด เผื่อเธรดทำงานไว้เกินที่ถังต้องการ 25% ให้ถังไม่ว่าง
MIN_GAIN = 0.2         # req/s ต้องขึ้น >= 20% ของสัดส่วนเธรดที่เพิ่ม (เพิ่ม 50% -> ต้องได้ >= 10%)
PROBE_AFTER = 60.0     # หลังถอย รอเท่านี้ก่อนลองเพิ่มอีก
LIMITED_MIN = 3        # 429/503 หรือต่อไม่ติด อย่างน้อยกี่ครั้งในหนึ่งรอบถึงนับว่าเป็นสัญญาณจริง
LIMITED_FRAC = 0.02    # และต้องเกินสัดส่วนนี้ของ request ในรอบนั้น
BACKOFF = 0.75
RPS_RAISE = 1.15       # ขยายงบ req/s ทีละ 15% ...
RPS_RAISE_NEAR = 1.03  # ... แต่แค่ 3% เมื่อ 15% จะข้ามงบที่เคยโดน 429
RPS_RAISE_FRAC = 0.005 # ... เฉพาะตอน 429/503 ไม่เกิน 0.5% ของ request ในรอบ
RPS_CUT = 0.8          # 429/503 เกิน LIMITED_FRAC ครั้งแรก -> หดงบ 20%
RPS_CUT_NEAR = 0.9     # ครั้งถัดไป (รู้ขอบแล้ว กำลังเลียบขอบอยู่) หดแค่ 10% - จำลอง: ใช้ขอบได้เฉลี่ย 89% -> 97%
RPS_HOLD = 20.0        # หลังหดงบ ห้ามขยายอีกนานเท่านี้ - กันแกว่งขึ้นลงทุกรอบที่ขอบของเซิร์ฟเวอร์
RPS_MIN = 10.0
RPS_MAX = 400.0        # ปรับได้ด้วย [settings] apirpsmax (ใส่เท่ากับ apirps = งบคงที่แบบเดิม)


def start_for(mode: str) -> int:
    """จำนวนเธรดต่อ lane ตอนเริ่มของโหมดนี้ - autoscaler ขยับต่อจากเลขนี้"""
    return START_BY_MODE.get(mode, START)


class _LaneState:
    def __init__(self, lane, now: float) -> None:
        self.lane = lane
        self.state = "grow"
        self.hold_until = 0.0
        self.rps_hold_until = 0.0
        self.trial = None      # (เป้าก่อนเพิ่ม, req/s ก่อนเพิ่ม, เธรดเฉลี่ยก่อนเพิ่ม)
        self.ceiling = None    # จำนวนเธรดที่เคยชนขอบ (ต่อไม่ติด/เพิ่มแล้วไม่คุ้ม) - None = ยังไม่รู้
        self.rps_ceiling = None  # งบ req/s ที่เคยโดน 429 - None = ยังไม่รู้
        self.reset(now)

    def reset(self, now: float) -> None:
        sig = self.lane.signals()
        self.sent0, self.limited0, self.neterr0 = sig["sent"], sig["limited"], sig["neterr"]
        self.t0 = now
        self.wait_bucket_sum = 0.0
        self.wait_quota_sum = 0.0
        self.run_sum = 0.0
        self.samples = 0


class AutoScaler:
    def __init__(self, lanes, lane_max: int = LANE_MAX, total_max: int = 4096,
                 now: float = 0.0, window: float | None = None,
                 probe_after: float | None = None, rps_max: float | None = None,
                 rps_min: float | None = None) -> None:
        self.lane_max = max(1, int(lane_max))
        self.total_max = max(1, int(total_max))
        self.window = WINDOW if window is None else window
        self.probe_after = PROBE_AFTER if probe_after is None else probe_after
        self.rps_max = RPS_MAX if rps_max is None else float(rps_max)
        self.rps_min = RPS_MIN if rps_min is None else float(rps_min)
        self._states = [_LaneState(lane, now) for lane in lanes]
        self._last = now

    def tick(self, now: float) -> bool:
        """เรียกทุกรอบของ supervisor: เก็บตัวอย่าง gauge และตัดสินใจเมื่อครบ window

        คืน True เมื่อเป้าเธรดหรืองบ req/s ของ lane ไหนเปลี่ยน
        """
        for st in self._states:
            sig = st.lane.signals()
            st.wait_bucket_sum += sig["wait_bucket"]
            st.wait_quota_sum += sig["wait_quota"]
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

    def _trim(self, run_avg: float, blocked: float, old: int) -> int:
        # เธรดที่ทำงานจริง (ไม่ได้ยืนรอ) คือจำนวนที่ถัง/โควตารับไหว เก็บไว้เท่านั้นบวกเผื่อ
        want = math.ceil(run_avg * (1.0 - blocked) * HEADROOM) + 1
        return max(1, min(old, want))

    def _decide(self, st, now: float) -> bool:
        lane = st.lane
        sig = lane.signals()
        dt = max(1e-6, now - st.t0)
        sent_n = sig["sent"] - st.sent0
        limited_n = sig["limited"] - st.limited0
        neterr_n = sig["neterr"] - st.neterr0
        useful = max(0, sent_n - limited_n) / dt     # request ที่ถูกตีกลับไม่ใช่งานที่เดินหน้า
        run_avg = st.run_sum / st.samples if st.samples else float(lane.running)
        blocked_bucket = st.wait_bucket_sum / st.run_sum if st.run_sum > 0 else 0.0
        blocked_quota = st.wait_quota_sum / st.run_sum if st.run_sum > 0 else 0.0
        blocked = blocked_bucket + blocked_quota
        st.reset(now)
        if not lane.alive:
            st.trial = None            # lane ตาย: pool ไม่สปอว์นให้อยู่แล้ว ผลที่วัดตอนนี้ไม่มีความหมาย
            return False

        old, old_rps = lane.threads, lane.rps
        new = old
        budgeted = lane.rps > 0         # apirps = 0 คือปิดถัง - ไม่มีงบให้ขยับ เหลือแต่คันโยกเธรด
        denominator = max(1, sent_n)
        pushback = limited_n >= LIMITED_MIN and limited_n > LIMITED_FRAC * denominator
        neterr = neterr_n >= LIMITED_MIN and neterr_n > LIMITED_FRAC * denominator
        can_raise = (budgeted and lane.rps < self.rps_max and now >= st.rps_hold_until
                     and limited_n <= RPS_RAISE_FRAC * denominator)

        if pushback and budgeted:
            # เซิร์ฟเวอร์ตีกลับ = เกินเพดานต่อ IP ของมัน หดงบ ส่วนเธรดปล่อยให้กฎ "ยืนรอถัง" ข้างล่างตัดเอง
            # ในรอบถัดไป - หดทั้งสองพร้อมกันคือถอยสองเท่าจากสัญญาณเดียว
            cut = RPS_CUT_NEAR if st.rps_ceiling is not None else RPS_CUT
            st.rps_ceiling = lane.rps
            lane.set_rps(max(self.rps_min, lane.rps * cut))
            st.state, st.trial, st.rps_hold_until = "cut", None, now + RPS_HOLD
        elif pushback or neterr:
            # ต่อไม่ติด/หลุดซ้ำ (หรือ 429 ตอนไม่มีถังให้หด) - ต้นเหตุคือจำนวนเธรด/การเชื่อมต่อ
            st.ceiling = max(1, int(min(old, run_avg)))
            new = max(1, int(min(old, run_avg) * BACKOFF))
            st.state, st.trial, st.hold_until = "backoff", None, now + self.probe_after
        elif blocked_quota >= BLOCKED_TRIM:
            # ยืนรอโควตา mint (GenID) - ขยายงบ req/s ไม่ช่วย ตัดเธรดที่เกินลง
            new = self._trim(run_avg, blocked, old)
            st.state, st.trial = "full", None
        elif blocked_bucket >= BLOCKED_FULL and can_raise:
            # ถังของเราเองคือคอขวด และเซิร์ฟเวอร์ยังรับได้ - ขยายงบ เธรดที่ยืนรออยู่จะได้ทำงานทันที
            near = st.rps_ceiling is not None and lane.rps * RPS_RAISE > st.rps_ceiling
            lane.set_rps(min(self.rps_max, lane.rps * (RPS_RAISE_NEAR if near else RPS_RAISE)))
            if st.rps_ceiling is not None and lane.rps > st.rps_ceiling:
                st.rps_ceiling = lane.rps   # ผ่านจุดที่เคยโดน 429 ได้ - เพดานเลื่อนตาม ยังก้าวเล็กต่อ
            st.state, st.trial = "raise", None
        elif blocked >= BLOCKED_TRIM:
            new = self._trim(run_avg, blocked, old)
            st.state, st.trial = "full", None
        elif blocked >= BLOCKED_FULL:
            st.state, st.trial = "full", None
        else:
            if st.trial is not None:
                prev_target, prev_rate, prev_run = st.trial
                st.trial = None
                expected = run_avg / prev_run - 1.0 if prev_run > 0 else 0.0
                if prev_rate > 0:
                    gained = useful / prev_rate - 1.0
                else:
                    gained = 1.0 if useful > 0 else 0.0
                if expected > 0 and gained < MIN_GAIN * expected:
                    st.ceiling = old            # เลขที่เพิ่มแล้วไม่คุ้ม - รอบหน้าเข้าหามันด้วยก้าวเล็ก
                    new = prev_target
                    st.state, st.hold_until = "plateau", now + self.probe_after
                elif st.ceiling is not None and old > st.ceiling:
                    st.ceiling = old            # ผ่านเพดานเดิมมาได้และคุ้ม - เพดานเลื่อนตาม ยังก้าวเล็กต่อ
            # โตเฉพาะตอนเธรดครบเป้าจริง: ถ้าคิวใกล้หมดหรือ pool หยุดสปอว์นแล้ว เพิ่มเป้าก็ไม่มีเธรดมาเติม
            if new == old and now >= st.hold_until and run_avg >= 0.9 * old:
                near = st.ceiling is not None and old * GROW > st.ceiling
                grown = min(self._cap(st), max(old + 1, math.ceil(old * (GROW_NEAR if near else GROW))))
                if grown > old:
                    new = grown
                    st.state, st.trial = "grow", (old, useful, run_avg)
                else:
                    st.state = "max"
        lane.threads = new
        return new != old or lane.rps != old_rps

    def summary(self) -> str:
        """สถานะที่ lane ส่วนใหญ่อยู่ - GUI แปลเป็นข้อความสั้น ๆ ข้างจำนวนเธรด"""
        counts: dict[str, int] = {}
        for st in self._states:
            if st.lane.alive:
                counts[st.state] = counts.get(st.state, 0) + 1
        return max(counts, key=counts.get) if counts else ""
