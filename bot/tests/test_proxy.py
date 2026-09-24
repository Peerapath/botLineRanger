"""ProxyPool: แบ่งงบ request และจำนวนเธรดตาม IP

บั๊กที่ชุดนี้กันไว้: เพดานเธรดที่ถูกตัดเงียบ ๆ ทำให้ผู้ใช้เชื่อว่าตั้ง 50 proxy x 96 เธรด
แล้วได้ 4,800 เธรดจริง ทั้งที่ระบบหั่นลงเหลือ 4,096 - "สูงสุดที่วัดได้" ไม่ใช่ "ที่ตั้งไว้"
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
import ratelimit                                            # noqa: E402
from engine.proxy import ProxyLane, ProxyPool, LANE_DEATH  # noqa: E402


class _FakeClock:
    """นาฬิกาที่เดินเฉพาะตอนถูกสั่ง - เทสต์เรื่องเวลาที่ใช้ time.sleep จริงจะช้าและแกว่ง"""
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_no_proxy_configured_gives_one_direct_lane():
    pool = ProxyPool([], rps=90, threads_per=96)
    assert [x.name for x in pool.lanes] == ["direct"]
    assert pool.lanes[0].parts is None


def test_each_proxy_becomes_its_own_lane_with_its_own_budget():
    pool = ProxyPool(["1.1.1.1:8000", "2.2.2.2:8000"], rps=90, threads_per=96)
    assert [x.name for x in pool.lanes] == ["1.1.1.1:8000", "2.2.2.2:8000"]
    assert pool.lanes[0].bucket is not pool.lanes[1].bucket


def test_a_proxy_with_credentials_keeps_them_out_of_the_lane_name():
    """ชื่อ lane ไปโผล่ใน log และบนหน้าจอ รหัสผ่านต้องไม่ติดไปด้วย"""
    pool = ProxyPool(["1.1.1.1:8000:bob:hunter2"], rps=90, threads_per=96)
    assert pool.lanes[0].name == "1.1.1.1:8000"
    assert "hunter2" not in pool.lanes[0].name


def test_threads_are_shared_out_per_lane():
    pool = ProxyPool(["1.1.1.1:8000", "2.2.2.2:8000"], rps=90, threads_per=96)
    assert [x.threads for x in pool.lanes] == [96, 96]
    assert pool.total_threads() == 192
    assert pool.capped == 0


def test_the_total_thread_ceiling_cuts_every_lane_and_says_how_much():
    """เกิน 4,096 เธรดแล้วงาน *ลดลง* ไม่ใช่แค่ไม่เพิ่ม - ตัดได้ แต่ต้องบอก"""
    pool = ProxyPool(["%d.1.1.1:8000" % i for i in range(50)], rps=90,
                     threads_per=96, max_threads=4096)
    assert pool.total_threads() <= 4096
    assert pool.capped == 50 * 96 - pool.total_threads()
    assert all(x.threads >= 1 for x in pool.lanes)


def test_a_lane_dies_only_after_three_failures_in_a_row():
    lane = ProxyLane("1.1.1.1:8000", None, rps=90, threads=8)
    for _ in range(LANE_DEATH - 1):
        assert lane.note_fail() is False
        assert lane.alive
    assert lane.note_fail() is True
    assert not lane.alive


def test_one_success_clears_the_failure_streak():
    """โปรเซสอื่นแย่งสายหลุดหนึ่งครั้งไม่ใช่ proxy ตาย ต้องไม่สะสมข้ามเวลา"""
    lane = ProxyLane("1.1.1.1:8000", None, rps=90, threads=8)
    lane.note_fail()
    lane.note_fail()
    lane.note_ok()
    assert lane.note_fail() is False
    assert lane.alive


def test_alive_lanes_drops_the_dead_one():
    pool = ProxyPool(["1.1.1.1:8000", "2.2.2.2:8000"], rps=90, threads_per=8)
    for _ in range(LANE_DEATH):
        pool.lanes[0].note_fail()
    assert [x.name for x in pool.alive_lanes()] == ["2.2.2.2:8000"]


def test_a_malformed_proxy_line_is_refused_loudly():
    """ยอมรับเงียบ ๆ แปลว่า worker ตายทีหลังโดยผู้ใช้เห็นแค่ 0 thread"""
    with pytest.raises(ValueError):
        ProxyPool(["not-a-proxy"], rps=90, threads_per=8)


def test_acquire_spends_a_token_from_the_lanes_own_bucket():
    """acquire() must actually draw from the lane's own TokenBucket, not just pass through.

    Added beyond the brief's 9 cases: every other test in this file builds lanes/pools
    but never calls acquire(), so a broken delegation (wrong attribute, forgot to call
    through, calls some shared/global bucket instead of self.bucket) would pass all of
    them and only show up once Task 4 wires a lane into a live worker and the game's
    ~100 req/s per-IP ceiling gets hit for real.
    """
    clock = _FakeClock()
    waits = []
    lane = ProxyLane("1.1.1.1:8000", None, rps=10, threads=8, clock=clock,
                      sleep=lambda s: (waits.append(s), clock.advance(s)))
    for _ in range(lane.bucket.burst + 1):
        lane.acquire()
    assert waits, "acquire() never paced once the burst was spent - is it still calling its TokenBucket?"


def test_each_lane_has_its_own_independent_guest_mint_quota(monkeypatch):
    """C6 (final review): the guest-mint quota (game-api allows 2 mints/IP/~60s) used to be
    ratelimit.quota_for("linegame-auth", ...) - cached on the name ALONE for the whole
    process, so every lane shared one 2-per-minute budget - GenID was capped at 2
    accounts/minute TOTAL no matter how many proxies were configured, a regression from the
    old fleet's 2 per PROCESS (= 2 per proxy, one process per proxy). Each lane must own an
    in-memory quota the same way it owns its own TokenBucket.
    """
    monkeypatch.setattr(ratelimit, "AUTH_QUOTA", "1/60")
    clock = _FakeClock()
    waits = []
    sleep = lambda s: (waits.append(s), clock.advance(s))
    a = ProxyLane("1.1.1.1:8000", None, rps=1000, threads=8, clock=clock, sleep=sleep)
    b = ProxyLane("2.2.2.2:8000", None, rps=1000, threads=8, clock=clock, sleep=sleep)
    assert a.auth_quota is not b.auth_quota
    a.auth_quota.acquire()
    b.auth_quota.acquire()      # independent budget - must not wait for a's single slot
    assert waits == []
