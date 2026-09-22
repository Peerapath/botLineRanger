import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import ratelimit


# --- is_app_429 ---------------------------------------------------------------------------

APP429 = {"errorCode": 429,
          "extras": {"current": 1790091337516, "previous": 1790091337314, "userKey": "r7x1o4"},
          "timestamp": 1790091337517, "version": "12.3.0"}


def test_is_app_429_returns_gap_for_http400_errorcode429():
    assert ratelimit.is_app_429(400, APP429) == 202


def test_is_app_429_zero_when_extras_missing():
    assert ratelimit.is_app_429(400, {"errorCode": 429}) == 0


def test_is_app_429_none_for_other_shapes():
    assert ratelimit.is_app_429(400, {"errorCode": 500}) is None      # transient 500-in-400
    assert ratelimit.is_app_429(429, "<html>429 Too Many Requests</html>") is None  # nginx
    assert ratelimit.is_app_429(200, {"result": {}}) is None
    assert ratelimit.is_app_429(400, "not json") is None


# --- AccountPacer ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 4))
        self.t += s


def _pacer(gap_ms=350):
    clk = FakeClock()
    return ratelimit.AccountPacer(min_gap_ms=gap_ms, clock=clk.now, sleep=clk.sleep), clk


def test_pacer_first_call_never_waits():
    p, clk = _pacer()
    assert p.wait("LF_AC=a") == 0.0
    assert clk.slept == []


def test_pacer_waits_remaining_gap_after_done():
    p, clk = _pacer()
    p.done("LF_AC=a")
    clk.t += 0.10                      # 100 ms later
    assert abs(p.wait("LF_AC=a") - 0.25) < 1e-6
    assert clk.slept == [0.25]


def test_pacer_no_wait_when_gap_already_elapsed():
    p, clk = _pacer()
    p.done("LF_AC=a")
    clk.t += 0.5
    assert p.wait("LF_AC=a") == 0.0
    assert clk.slept == []


def test_pacer_keys_are_independent():
    p, clk = _pacer()
    p.done("LF_AC=a")
    assert p.wait("LF_AC=b") == 0.0


def test_pacer_evicts_when_over_max_keys():
    clk = FakeClock()
    p = ratelimit.AccountPacer(min_gap_ms=350, clock=clk.now, sleep=clk.sleep, max_keys=2)
    p.done("a"); p.done("b"); p.done("c")           # third key clears the table first
    assert p.wait("a") == 0.0 and clk.slept == []
    assert p.wait("c") > 0                          # c is still tracked


def test_module_defaults_from_env():
    assert ratelimit.MIN_GAP_MS == 350
    assert ratelimit.RPS_BUDGET == 80.0
    assert ratelimit.BURST == 20
    assert isinstance(ratelimit.PACER, ratelimit.AccountPacer)
