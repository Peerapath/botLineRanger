"""AutoScaler: หาเลขเธรดต่อ lane ที่ได้บัญชี/นาทีสูงสุดเอง

ทุกเทสต์ในไฟล์นี้ป้อน lane ปลอมที่ผู้เทสต์คุมตัวนับเอง (req สะสม, เธรดที่รอถัง, 429 สะสม)
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
    """ตัวนับของ ProxyLane ที่เทสต์ตั้งเองได้ - waiting คือจำนวนเธรดที่ยืนรอถัง/โควตาอยู่"""

    def __init__(self, threads, name="direct"):
        self.name = name
        self.threads = threads
        self.running = threads
        self.alive = True
        self.waiting = 0
        self.sent = 0
        self.limited = 0

    def counters(self):
        return self.waiting, self.sent, self.limited


def run_window(scaler, lane, now, rate, waiting=0, limited=0, running=None):
    """หนึ่ง window: เธรดครบเป้า (ถ้าไม่ระบุ running) ส่ง rate req/s และมี waiting เธรดยืนรอ"""
    lane.running = lane.threads if running is None else running
    lane.waiting = waiting
    lane.sent += int(rate * W)
    lane.limited += limited
    scaler.tick(now + W / 2)          # ตัวอย่างกลาง window
    scaler.tick(now + W)              # ครบ window -> ตัดสินใจ
    return now + W


def test_grows_by_half_while_nothing_waits_and_more_threads_keep_paying():
    lane = FakeLane(16)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    now = run_window(scaler, lane, 0.0, rate=32)          # 16 เธรด 2 req/s ต่อเธรด
    assert lane.threads == 24
    now = run_window(scaler, lane, now, rate=48)          # เพิ่ม 50% ได้ req/s เพิ่ม 50% - คุ้ม
    assert lane.threads == 36
    assert scaler.summary() == "grow"


def test_trims_to_what_the_bucket_can_feed_once_most_threads_just_wait_on_it():
    """Login ชนถัง 80 req/s: เธรด 200 ตัวครึ่งหนึ่งยืนรอโทเคน - เพิ่มก็ได้แค่คิวยาวขึ้น"""
    lane = FakeLane(200)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    run_window(scaler, lane, 0.0, rate=80, waiting=100)
    # เธรดที่ทำงานจริง 100 ตัว + เผื่อ 25% + 1
    assert lane.threads == 126
    assert scaler.summary() == "full"


def test_holds_steady_in_the_band_where_the_bucket_is_just_full():
    lane = FakeLane(128)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    now = 0.0
    for _ in range(5):
        now = run_window(scaler, lane, now, rate=80, waiting=25)    # รอ ~20%
    assert lane.threads == 128
    assert scaler.summary() == "full"


def test_genid_threads_parked_on_the_mint_quota_are_trimmed_to_a_handful():
    """GenID: โควตา mint 2 ครั้ง/นาที/IP - เธรดเกือบทั้งหมดยืนรอโควตา เพิ่มเธรดไม่ได้บัญชีเพิ่ม"""
    lane = FakeLane(16)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    run_window(scaler, lane, 0.0, rate=3, waiting=14)
    assert lane.threads == 4          # เธรดที่ทำงานจริง 2 ตัว x 1.25 ปัดขึ้นเป็น 3 แล้ว +1
    assert lane.threads < 16


def test_growth_that_brings_no_extra_requests_is_undone_then_retried_later():
    """คอขวดที่ไม่ใช่ถังของเรา (CPU/GIL, เซิร์ฟเวอร์ช้า): เธรดเพิ่ม 50% แต่ req/s เท่าเดิม"""
    lane = FakeLane(64)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0, probe_after=60.0)
    now = run_window(scaler, lane, 0.0, rate=100)
    assert lane.threads == 96
    now = run_window(scaler, lane, now, rate=101)         # เพิ่มแล้วได้แค่ +1%
    assert lane.threads == 64
    assert scaler.summary() == "plateau"
    now = run_window(scaler, lane, now, rate=100)
    assert lane.threads == 64                              # ยังอยู่ในช่วงพัก ไม่ลองซ้ำทันที
    for _ in range(5):
        now = run_window(scaler, lane, now, rate=100)
    assert lane.threads == 96                              # พักครบ 60 วิ -> ลองเพิ่มอีกครั้ง


def test_a_burst_of_429s_backs_the_lane_off():
    lane = FakeLane(128)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    run_window(scaler, lane, 0.0, rate=100, limited=50)   # 5% ของ 1000 request โดนตีกลับ
    assert lane.threads == 96
    assert scaler.summary() == "backoff"


def test_a_stray_429_is_not_a_reason_to_back_off():
    lane = FakeLane(32)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    run_window(scaler, lane, 0.0, rate=64, limited=1)
    assert lane.threads == 48


def test_never_grows_past_the_per_lane_or_total_ceiling():
    lanes = [FakeLane(16, "a"), FakeLane(16, "b")]
    scaler = AutoScaler(lanes, lane_max=40, total_max=60, now=0.0)
    now = 0.0
    for _ in range(10):
        for lane in lanes:
            lane.running = lane.threads
            lane.sent += int(lane.threads * 2 * W)
        scaler.tick(now + W)
        now += W
    assert all(lane.threads <= 40 for lane in lanes)
    assert sum(lane.threads for lane in lanes) <= 60


def test_does_not_raise_the_target_when_threads_are_not_filling_it():
    """คิว input/ ใกล้หมด: pool ไม่สปอว์นเธรดมาเติมแล้ว เพิ่มเป้าไปก็ไม่มีใครมาทำ"""
    lane = FakeLane(64)
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    run_window(scaler, lane, 0.0, rate=20, running=10)
    assert lane.threads == 64


def test_a_dead_lane_is_left_alone():
    lane = FakeLane(32)
    lane.alive = False
    scaler = AutoScaler([lane], lane_max=256, total_max=4096, now=0.0)
    run_window(scaler, lane, 0.0, rate=0)
    assert lane.threads == 32
    assert scaler.summary() == ""
