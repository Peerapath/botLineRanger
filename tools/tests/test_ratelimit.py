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


import subprocess
import pytest


# --- IpBucket -------------------------------------------------------------------------------

def _bucket(tmp_path, rate=10.0, burst=3, proxy=""):
    clk = FakeClock()
    b = ratelimit.IpBucket("rangers-api.line-apps.com", rate=rate, burst=burst,
                           rl_dir=str(tmp_path), proxy=proxy, clock=clk.now, sleep=clk.sleep)
    return b, clk


def test_bucket_file_name_direct_and_proxy(tmp_path):
    b, _ = _bucket(tmp_path)
    assert os.path.basename(b.path) == "bucket-direct-rangers-api.line-apps.com.txt"
    b2, _ = _bucket(tmp_path, proxy="10.0.0.1:8080")
    import hashlib
    pid = hashlib.sha1(b"10.0.0.1:8080").hexdigest()[:8]
    assert os.path.basename(b2.path) == "bucket-%s-rangers-api.line-apps.com.txt" % pid


def test_bucket_burst_then_waits_for_refill(tmp_path):
    b, clk = _bucket(tmp_path, rate=10.0, burst=3)
    for _ in range(3):
        b.acquire()
    assert clk.slept == []                       # burst is free
    b.acquire()                                  # 4th: bucket empty -> wait 1/rate (+ <= 5 ms jitter)
    assert len(clk.slept) == 1 and 0.1 <= clk.slept[0] <= 0.106
    with open(b.path) as fh:
        tokens, ts = fh.read().split()
    assert float(tokens) < 1.0


def test_bucket_disabled_when_rate_zero(tmp_path):
    b, clk = _bucket(tmp_path, rate=0)
    for _ in range(50):
        b.acquire()
    assert clk.slept == [] and not os.path.exists(b.path)


def test_bucket_corrupt_file_resets(tmp_path):
    b, clk = _bucket(tmp_path, rate=10.0, burst=3)
    os.makedirs(os.path.dirname(b.path), exist_ok=True)
    with open(b.path, "w") as fh:
        fh.write("garbage")
    b.acquire()
    assert clk.slept == []


def test_bucket_unwritable_dir_disables_without_raising(tmp_path, capsys):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    clk = FakeClock()
    b = ratelimit.IpBucket("h", rate=10.0, burst=3, rl_dir=str(blocker / "sub"),
                           clock=clk.now, sleep=clk.sleep)
    for _ in range(5):
        b.acquire()                              # must not raise
    assert "bucket disabled" in capsys.readouterr().err


WORKER = r"""
import os, sys, time
sys.path.insert(0, %r)
import ratelimit
b = ratelimit.IpBucket("h", rate=50, burst=10, rl_dir=%r)
n = 0
end = time.time() + 1.0
while time.time() < end:
    b.acquire(); n += 1
print(n)
"""


def test_bucket_is_shared_across_processes(tmp_path):
    code = WORKER % (TOOLS, str(tmp_path))
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
             for _ in range(2)]
    counts = [int(p.communicate(timeout=30)[0].strip()) for p in procs]
    total = sum(counts)
    # one shared bucket: burst 10 + 50/s over ~1 s (+ timing slack); two private ones would give ~120
    assert 40 <= total <= 75, counts


def test_bucket_is_fair_across_processes(tmp_path):
    code = WORKER % (TOOLS, str(tmp_path))
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
             for _ in range(4)]
    counts = [int(p.communicate(timeout=30)[0].strip()) for p in procs]
    total = sum(counts)
    assert 40 <= total <= 80, counts          # still one shared bucket, not four private ones
    assert min(counts) >= 3, counts           # no worker starved out by the lock


def test_bucket_for_caches_per_host(monkeypatch, tmp_path):
    monkeypatch.setenv("LGRGS_RL_DIR", str(tmp_path))
    ratelimit._BUCKETS.clear()
    a = ratelimit.bucket_for("rangers-api.line-apps.com")
    b = ratelimit.bucket_for("game-api.line.me")
    assert a is ratelimit.bucket_for("rangers-api.line-apps.com") and a is not b
    assert a.path != b.path


# --- proxy / env helpers --------------------------------------------------------------------

def test_proxy_parts_and_url():
    assert ratelimit.proxy_parts("") is None
    assert ratelimit.proxy_parts("10.0.0.1:8080") == ("10.0.0.1", 8080, None)
    host, port, auth = ratelimit.proxy_parts("p.example:3128:us er:p@ss")
    assert (host, port) == ("p.example", 3128)
    assert auth == "Basic " + __import__("base64").b64encode(b"us er:p@ss").decode()
    assert ratelimit.proxy_url("10.0.0.1:8080") == "http://10.0.0.1:8080"
    assert ratelimit.proxy_url("p.example:3128:us er:p@ss") == "http://us%20er:p%40ss@p.example:3128"
    assert ratelimit.proxy_url("") is None


def test_proxy_parts_rejects_malformed():
    with pytest.raises(ValueError):
        ratelimit.proxy_parts("nocolon")
    with pytest.raises(ValueError):
        ratelimit.proxy_parts("h:notaport")
    with pytest.raises(ValueError):
        ratelimit.proxy_parts("h:1:useronly")


def test_parse_proxies():
    assert ratelimit.parse_proxies("") == []
    assert ratelimit.parse_proxies(" a:1 , b:2,,") == ["a:1", "b:2"]


def test_spawn_env_round_robins_proxies():
    base = {"PATH": "x"}
    e0 = ratelimit.spawn_env(base, 80, ["a:1", "b:2"], 0, "D:/bot/.ratelimit")
    e1 = ratelimit.spawn_env(base, 80, ["a:1", "b:2"], 1, "D:/bot/.ratelimit")
    e2 = ratelimit.spawn_env(base, 80, ["a:1", "b:2"], 2, "D:/bot/.ratelimit")
    assert (e0["LGRGS_PROXY"], e1["LGRGS_PROXY"], e2["LGRGS_PROXY"]) == ("a:1", "b:2", "a:1")
    assert e0["LGRGS_RPS_BUDGET"] == "80" and e0["LGRGS_RL_DIR"] == "D:/bot/.ratelimit"
    assert e0["PATH"] == "x" and base == {"PATH": "x"}          # copy, not mutation
    assert ratelimit.spawn_env(base, 0, [], 5, "d")["LGRGS_PROXY"] == ""
