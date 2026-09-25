"""AutoScaler: หาเลขเธรดและงบ req/s ต่อ lane ที่ได้บัญชี/นาทีสูงสุดเอง

ทุกเทสต์ในไฟล์นี้ป้อน lane ปลอมที่ผู้เทสต์คุมตัวนับเอง (req สะสม, เธรดที่รอถัง/โควตา, 429 สะสม)
แล้วเดินนาฬิกาเองทีละ window - ไม่มี sleep จริง ไม่มีเธรดจริง
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine import autoscale                 # noqa: E402
from engine.autoscale import AutoScaler      # noqa: E402

W = autoscale.WINDOW


class FakeLane:
    """ตัวนับของ ProxyLane ที่เทสต์ตั้งเองได้"""

    def __init__(self, threads, rps=80.0, name="direct"):
        self.name = name
        self.threads = threads
        self.running = threads
        self.rps = rps
        self.alive = True
        self.wait_bucket = 0
        self.wait_quota = 0
        self.sent = 0
        self.limited = 0
        self.neterr = 0

    def set_rps(self, rps):
        self.rps = rps

    def signals(self):
        return {"wait_bucket": self.wait_bucket, "wait_quota": self.wait_quota,
                "sent": self.sent, "limited": self.limited, "neterr": self.neterr}


def run_window(scaler, lane, now, rate, bucket=0, quota=0, limited=0, neterr=0, running=None):
    """หนึ่ง window: เธรดครบเป้า (ถ้าไม่ระบุ running) ส่ง rate req/s มี bucket/quota เธรดยืนรอ"""
    lane.running = lane.threads if running is None else running
    lane.wait_bucket, lane.wait_quota = bucket, quota
    lane.sent += int(rate * W)
    lane.limited += limited
    lane.neterr += neterr
    scaler.tick(now + W / 2)          # ตัวอย่างกลาง window
    scaler.tick(now + W)              # ครบ window -> ตัดสินใจ
    return now + W


def scaler_for(*lanes, **kw):
    kw.setdefault("lane_max", 512)
    kw.setdefault("total_max", 4096)
    return AutoScaler(list(lanes), now=0.0, **kw)


# --- เธรด ---

def test_grows_by_half_while_nothing_waits_and_more_threads_keep_paying():
    lane = FakeLane(16)
    scaler = scaler_for(lane)
    now = run_window(scaler, lane, 0.0, rate=32)          # 16 เธรด 2 req/s ต่อเธรด
    assert lane.threads == 24
    now = run_window(scaler, lane, now, rate=48)          # เพิ่ม 50% ได้ req/s เพิ่ม 50% - คุ้ม
    assert lane.threads == 36
    assert scaler.summary() == "grow"


def test_growth_that_brings_no_extra_requests_is_undone_then_retried_later():
    """คอขวดที่ไม่ใช่ถังของเรา (CPU/GIL, เซิร์ฟเวอร์ช้า): เธรดเพิ่ม 50% แต่ req/s เท่าเดิม"""
    lane = FakeLane(64)
    scaler = scaler_for(lane, probe_after=60.0)
    now = run_window(scaler, lane, 0.0, rate=100)
    assert lane.threads == 96
    now = run_window(scaler, lane, now, rate=101)         # เพิ่มแล้วได้แค่ +1%
    assert lane.threads == 64
    assert scaler.summary() == "plateau"
    reverted_at = now
    while now + W < reverted_at + 60.0:
        now = run_window(scaler, lane, now, rate=100)
        assert lane.threads == 64                          # ยังอยู่ในช่วงพัก ไม่ลองซ้ำทันที
    run_window(scaler, lane, now, rate=100)
    assert lane.threads == 96                              # พักครบ 60 วิ -> ลองเพิ่มอีกครั้ง


def test_does_not_raise_the_target_when_threads_are_not_filling_it():
    """คิว input/ ใกล้หมด: pool ไม่สปอว์นเธรดมาเติมแล้ว เพิ่มเป้าไปก็ไม่มีใครมาทำ"""
    lane = FakeLane(64)
    scaler = scaler_for(lane)
    run_window(scaler, lane, 0.0, rate=20, running=10)
    assert lane.threads == 64


def test_never_grows_past_the_per_lane_or_total_ceiling():
    lanes = [FakeLane(16, name="a"), FakeLane(16, name="b")]
    scaler = scaler_for(*lanes, lane_max=40, total_max=60)
    now = 0.0
    for _ in range(10):
        for lane in lanes:
            lane.running = lane.threads
            lane.sent += int(lane.threads * 2 * W)
        scaler.tick(now + W)
        now += W
    assert all(lane.threads <= 40 for lane in lanes)
    assert sum(lane.threads for lane in lanes) <= 60


# --- งบ req/s ---

def test_threads_waiting_on_our_own_bucket_raise_the_budget_not_trim_threads():
    """รันจริง 2026-09-25: ค้าง 108 เธรด ~250 บัญชี/นาทีทั้งรัน เพราะชนถัง 80 req/s ของเราเอง
    ขณะที่เซิร์ฟเวอร์ยังไม่ตอบ 429 สักครั้ง - ต้องขยายงบ ไม่ใช่ตัดเธรดทิ้ง"""
    lane = FakeLane(108, rps=80.0)
    scaler = scaler_for(lane)
    now = run_window(scaler, lane, 0.0, rate=80, bucket=54)
    assert lane.rps == 80.0 * autoscale.RPS_RAISE
    assert lane.threads == 108
    assert scaler.summary() == "raise"
    for _ in range(5):
        now = run_window(scaler, lane, now, rate=lane.rps, bucket=54)
    assert lane.rps > 150


def test_a_burst_of_429s_cuts_the_budget_and_pauses_raising_it():
    lane = FakeLane(128, rps=140.0)
    scaler = scaler_for(lane)
    now = run_window(scaler, lane, 0.0, rate=140, limited=30, bucket=40)   # 4% โดนตีกลับ
    assert lane.rps == 140.0 * autoscale.RPS_CUT
    assert lane.threads == 128                  # หดงบอย่างเดียว ไม่ถอยเธรดซ้ำจากสัญญาณเดียว
    assert scaler.summary() == "cut"
    held, cut_at = lane.rps, now
    while now + W < cut_at + autoscale.RPS_HOLD:
        now = run_window(scaler, lane, now, rate=held, bucket=20)
        assert lane.rps == held                 # ช่วงพัก: ยืนรอถังแค่ไหนก็ไม่ขยายกลับ
    run_window(scaler, lane, now, rate=held, bucket=20)
    assert lane.rps > held                      # พักครบ -> ค่อย ๆ ขยายใหม่


def test_a_stray_429_neither_cuts_the_budget_nor_backs_threads_off():
    lane = FakeLane(32, rps=80.0)
    scaler = scaler_for(lane)
    run_window(scaler, lane, 0.0, rate=64, limited=1)
    assert lane.rps == 80.0
    assert lane.threads == 48


def test_the_budget_never_passes_apirpsmax():
    lane = FakeLane(200, rps=90.0)
    scaler = scaler_for(lane, rps_max=100.0)
    now = 0.0
    for _ in range(5):
        now = run_window(scaler, lane, now, rate=lane.rps, bucket=100)
        assert lane.rps <= 100.0
    assert lane.rps == 100.0


def test_once_the_budget_is_capped_surplus_waiting_threads_are_trimmed():
    lane = FakeLane(200, rps=100.0)
    scaler = scaler_for(lane, rps_max=100.0)
    run_window(scaler, lane, 0.0, rate=100, bucket=100)
    # เธรดที่ทำงานจริง 100 ตัว + เผื่อ 25% + 1
    assert lane.threads == 126
    assert scaler.summary() == "full"


def test_holds_steady_in_the_band_where_a_capped_bucket_is_just_full():
    lane = FakeLane(128, rps=100.0)
    scaler = scaler_for(lane, rps_max=100.0)
    now = 0.0
    for _ in range(5):
        now = run_window(scaler, lane, now, rate=100, bucket=25)    # รอ ~20%
    assert lane.threads == 128
    assert scaler.summary() == "full"


# --- โควตา mint / ต่อไม่ติด / ไม่มีถัง ---

def test_genid_threads_parked_on_the_mint_quota_are_trimmed_and_the_budget_is_left_alone():
    """GenID: โควตา mint 2 ครั้ง/นาที/IP - ขยายงบ req/s ไม่ช่วย ต้องตัดเธรดที่ยืนรอ"""
    lane = FakeLane(16, rps=80.0)
    scaler = scaler_for(lane)
    run_window(scaler, lane, 0.0, rate=3, quota=14)
    assert lane.threads == 4          # เธรดที่ทำงานจริง 2 ตัว x 1.25 ปัดขึ้นเป็น 3 แล้ว +1
    assert lane.rps == 80.0


def test_repeated_connection_failures_back_the_threads_off():
    lane = FakeLane(160, rps=80.0)
    scaler = scaler_for(lane)
    run_window(scaler, lane, 0.0, rate=80, neterr=20)
    assert lane.threads == 120
    assert lane.rps == 80.0
    assert scaler.summary() == "backoff"


def test_with_the_bucket_switched_off_429s_back_the_threads_off_instead():
    """apirps = 0 ปิดถัง - ไม่มีงบให้หด เหลือคันโยกเดียวคือจำนวนเธรด"""
    lane = FakeLane(128, rps=0.0)
    scaler = scaler_for(lane)
    run_window(scaler, lane, 0.0, rate=100, limited=50)
    assert lane.threads == 96
    assert lane.rps == 0.0


def test_a_dead_lane_is_left_alone():
    lane = FakeLane(32)
    lane.alive = False
    scaler = scaler_for(lane)
    run_window(scaler, lane, 0.0, rate=0)
    assert lane.threads == 32
    assert scaler.summary() == ""


# --- เพดานที่เคยชน: เข้าหาด้วยก้าวเล็ก ไม่ชนซ้ำทุกนาที ---

def test_after_a_backoff_threads_creep_back_toward_the_old_ceiling_in_small_steps():
    """รันจริง 2026-09-25 02:13: ถอยแล้วโตกลับ x1.5 ชนขอบเดิมซ้ำ เธรดแกว่ง 156 -> 96 -> 141 ทุกนาที"""
    lane = FakeLane(156, rps=0.0)
    scaler = scaler_for(lane, probe_after=60.0)
    now = run_window(scaler, lane, 0.0, rate=80, neterr=20)
    assert lane.threads == 117
    backed_off_at = now
    while now < backed_off_at + 60.0:
        now = run_window(scaler, lane, now, rate=60)
    assert lane.threads == 129                 # 117 x1.5 = 176 จะข้าม 156 -> ก้าวเล็ก x1.1


def test_after_a_429_cut_the_budget_creeps_back_in_small_steps():
    lane = FakeLane(128, rps=140.0)
    scaler = scaler_for(lane)
    now = run_window(scaler, lane, 0.0, rate=140, limited=30, bucket=40)
    assert lane.rps == 112.0
    cut_at = now
    while now + W < cut_at + autoscale.RPS_HOLD:
        now = run_window(scaler, lane, now, rate=112, bucket=40)
    now = run_window(scaler, lane, now, rate=112, bucket=40)
    assert abs(lane.rps - 112.0 * 1.15) < 1e-6    # ยังห่างเพดาน 140 -> ก้าวใหญ่
    run_window(scaler, lane, now, rate=lane.rps, bucket=40)
    assert abs(lane.rps - 112.0 * 1.15 * 1.03) < 1e-6   # ก้าวใหญ่จะข้าม 140 -> ก้าวเล็ก


def test_once_the_servers_edge_is_known_later_cuts_are_gentler():
    lane = FakeLane(128, rps=150.0)
    scaler = scaler_for(lane)
    now = run_window(scaler, lane, 0.0, rate=150, limited=30, bucket=40)
    assert lane.rps == 150.0 * autoscale.RPS_CUT                  # ครั้งแรก: ยังไม่รู้ขอบ หด 20%
    now = run_window(scaler, lane, now, rate=lane.rps, limited=30, bucket=40)
    assert lane.rps == 150.0 * autoscale.RPS_CUT * autoscale.RPS_CUT_NEAR   # รู้ขอบแล้ว หด 10%
