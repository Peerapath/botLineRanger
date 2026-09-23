import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import ratelimit


class _FakeClock:
    """นาฬิกาที่เดินเฉพาะตอนถูกสั่ง - เทสต์เรื่องเวลาที่ใช้ time.sleep จริงจะช้าและแกว่ง"""
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


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


def test_bucket_burst_below_one_is_clamped(tmp_path):
    b, clk = _bucket(tmp_path, rate=10.0, burst=0)
    assert b.burst == 1
    b.acquire()                                  # burst 0 could never reach 1 token -> would hang


def test_bucket_lock_timeout_paces_and_stays_armed(tmp_path, monkeypatch):
    b, clk = _bucket(tmp_path, rate=10.0, burst=3)
    real_lock, calls = ratelimit._lock, []

    def flaky_lock(fh):
        calls.append(1)
        if len(calls) == 1:
            raise ratelimit.LockTimeout("held")
        return real_lock(fh)                     # later calls lock for real, so _unlock matches

    monkeypatch.setattr(ratelimit, "_lock", flaky_lock)
    b.acquire()                                  # must retry, not disable the cap
    assert clk.slept[0] == 0.1                   # one token period = 1.0 / rate, no jitter
    assert b._disabled is False


@pytest.mark.skipif(os.name != "nt", reason="msvcrt byte-range locking")
def test_lock_raises_locktimeout_when_file_is_held(tmp_path, monkeypatch):
    import io
    import msvcrt
    import time as _time

    monkeypatch.setattr(ratelimit, "_LOCK_TIMEOUT_S", 0.2)
    path = str(tmp_path / "bucket.txt")
    open(path, "w").close()
    holder = io.open(path, "r+b")
    holder.seek(0)
    msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
    other = io.open(path, "r+b")
    try:
        t0 = _time.monotonic()
        with pytest.raises(ratelimit.LockTimeout):
            ratelimit._lock(other)
        assert _time.monotonic() - t0 < 1.0      # bounded wait, not a 10 s stall or a spin
    finally:
        holder.seek(0)
        msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
        holder.close()
        other.close()


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


def _worker_counts(tmp_path, nproc):
    """Run nproc children against one shared bucket -> (per-process counts, their stderr)."""
    code = WORKER % (TOOLS, str(tmp_path))
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(nproc)]
    try:
        outs = [p.communicate(timeout=30) for p in procs]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    return [int(o.strip()) for o, _ in outs], "".join(e for _, e in outs)


def test_bucket_is_shared_across_processes(tmp_path):
    counts, err = _worker_counts(tmp_path, 2)
    total = sum(counts)
    # one shared bucket: burst 10 + 50/s over ~1 s (+ timing slack); two private ones would give ~120
    assert 40 <= total <= 75, (counts, err)


def test_bucket_is_fair_across_processes(tmp_path):
    counts, err = _worker_counts(tmp_path, 4)
    total = sum(counts)
    assert 40 <= total <= 80, (counts, err)   # still one shared bucket, not four private ones
    assert min(counts) >= 3, (counts, err)    # no worker starved out by the lock


def test_bucket_for_caches_per_host(monkeypatch, tmp_path):
    monkeypatch.setenv("LGRGS_RL_DIR", str(tmp_path))
    monkeypatch.setattr(ratelimit, "_BUCKETS", {})
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


def test_bucket_transient_oserror_does_not_disable(tmp_path):
    b, clk = _bucket(tmp_path, rate=10.0, burst=3)
    calls = {"n": 0}

    def flaky_take():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError("sharing violation")
        return 0.0
    b._take = flaky_take
    b.acquire()
    assert b._disabled is False and calls["n"] == 3
    assert clk.slept == [0.05, 0.05]


def test_bucket_disables_only_after_three_consecutive_failures(tmp_path, capsys):
    b, clk = _bucket(tmp_path, rate=10.0, burst=3)

    def always_fail():
        raise OSError("gone")
    b._take = always_fail
    b.acquire()
    assert b._disabled is True and clk.slept == [0.05, 0.05]
    assert "bucket disabled after 3 failures" in capsys.readouterr().err
    b.acquire()                                  # stays a no-op afterwards
    assert clk.slept == [0.05, 0.05]


def test_bucket_host_is_sanitized_in_filename(tmp_path):
    clk = FakeClock()
    b = ratelimit.IpBucket("game-api.line.me:443", rate=10.0, burst=3, rl_dir=str(tmp_path),
                           proxy="", clock=clk.now, sleep=clk.sleep)
    assert os.path.basename(b.path) == "bucket-direct-game-api.line.me_443.txt"


def test_bucket_lock_timeout_warns_once(tmp_path, capsys):
    b, clk = _bucket(tmp_path, rate=10.0, burst=3)
    calls = {"n": 0}

    def timing_out_take():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ratelimit.LockTimeout("held")
        return 0.0
    b._take = timing_out_take
    b.acquire()
    assert b._disabled is False and clk.slept == [0.1, 0.1]
    assert capsys.readouterr().err.count("bucket lock timeout") == 1


def _quota(tmp_path, limit=2, window=60.0):
    clk = FakeClock()
    q = ratelimit.SlidingQuota("t", limit, window, rl_dir=str(tmp_path), proxy="",
                               clock=clk.now, sleep=clk.sleep, margin=1.0)
    return q, clk


def test_quota_allows_limit_then_waits_for_oldest_to_expire(tmp_path):
    q, clk = _quota(tmp_path, limit=2, window=60.0)
    q.acquire(); clk.t += 10
    q.acquire(); clk.t += 10           # two sends at t=1000 and t=1010
    assert clk.slept == []
    q.acquire()                         # third: oldest (1000) + 60 + margin 1 - now (1020) = 41 (+jitter <= 0.25)
    assert len(clk.slept) == 1 and 41.0 <= clk.slept[0] <= 41.3
    with open(q.path) as fh:
        stamps = [float(x) for x in fh.read().split()]
    assert len(stamps) == 2 and abs(stamps[-1] - clk.t) < 0.01   # file keeps 3 decimals


def test_quota_file_name_and_disabled_spec(tmp_path):
    q, _ = _quota(tmp_path)
    assert os.path.basename(q.path) == "quota-direct-t.txt"
    q0, clk = _quota(tmp_path, limit=0)
    for _ in range(5):
        q0.acquire()
    assert clk.slept == []


def test_quota_is_shared_across_instances_via_file(tmp_path):
    a, clk_a = _quota(tmp_path, limit=1, window=30.0)
    b, clk_b = _quota(tmp_path, limit=1, window=30.0)
    a.acquire()
    clk_b.t = clk_a.t + 5
    b.acquire()                         # sees a's stamp in the same file -> waits 30 + 1 - 5 = 26
    assert len(clk_b.slept) == 1 and 26.0 <= clk_b.slept[0] <= 26.3


def test_quota_for_parses_spec_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("LGRGS_RL_DIR", str(tmp_path))
    monkeypatch.setattr(ratelimit, "_QUOTAS", {})
    q = ratelimit.quota_for("x", "2/60")
    assert (q.limit, q.window) == (2, 60.0) and ratelimit.quota_for("x", "9/9") is q
    off = ratelimit.quota_for("off", "0")
    assert off._disabled is True
    with pytest.raises(ValueError):
        ratelimit.quota_for("bad", "two/60")


def test_auth_quota_uses_env_spec(monkeypatch, tmp_path):
    monkeypatch.setenv("LGRGS_RL_DIR", str(tmp_path))
    monkeypatch.setattr(ratelimit, "_QUOTAS", {})
    monkeypatch.setattr(ratelimit, "AUTH_QUOTA", "3/120")
    q = ratelimit.auth_quota()
    assert (q.limit, q.window) == (3, 120.0)
    assert os.path.basename(q.path) == "quota-direct-linegame-auth.txt"


def test_locked_file_creates_and_round_trips(tmp_path):
    path = str(tmp_path / "sub" / "cc.txt")
    with ratelimit.locked_file(path) as fh:
        assert fh.read() == ""
        fh.seek(0); fh.write("abc 123"); fh.flush()
    with ratelimit.locked_file(path) as fh:
        fh.seek(0)
        assert fh.read() == "abc 123"


# --- TokenBucket (in-process) ----------------------------------------------------------------

def test_token_bucket_hands_out_the_burst_without_waiting():
    clock, waits = _FakeClock(), []
    b = ratelimit.TokenBucket(rate=10, burst=5, clock=clock, sleep=waits.append)
    for _ in range(5):
        b.acquire()
    assert waits == []


def test_token_bucket_paces_at_the_configured_rate_once_the_burst_is_spent():
    """เกินเบิร์สต์แล้วต้องรอ 1/rate ต่อ token ไม่ใช่ปล่อยผ่าน"""
    clock, waits = _FakeClock(), []
    b = ratelimit.TokenBucket(rate=10, burst=1, clock=clock, sleep=lambda s: (waits.append(s), clock.advance(s)))
    b.acquire()
    b.acquire()
    assert waits and abs(sum(waits) - 0.1) < 0.01


def test_token_bucket_never_waits_when_time_has_already_passed():
    clock, waits = _FakeClock(), []
    b = ratelimit.TokenBucket(rate=10, burst=1, clock=clock, sleep=waits.append)
    b.acquire()
    clock.advance(5.0)
    b.acquire()
    assert waits == []


def test_token_bucket_hands_each_token_to_exactly_one_thread():
    """เบิร์สต์ 50 ใบกับ 20 เธรดที่ขอคนละ 5 ใบ: ต้องไม่มีใครได้ token ผีเพิ่ม"""
    import threading
    import time
    b = ratelimit.TokenBucket(rate=1000, burst=50)
    got = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            b.acquire()
            with lock:
                got.append(1)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    for t in ts:
        t.start()
    # Bound the wait: a deadlock/livelock regression in acquire() must fail this test, not hang
    # the whole suite forever. One shared deadline (not a per-thread timeout) caps the worst case
    # at ~5s total even if every thread is stuck, instead of 20 * timeout.
    deadline = time.monotonic() + 5.0
    for t in ts:
        t.join(timeout=max(0.0, deadline - time.monotonic()))
    for t in ts:
        assert not t.is_alive()
    assert len(got) == 100


def test_the_old_file_backed_bucket_is_still_available_under_its_new_name():
    """ของเดิมต้องไม่หาย มันคือทางเดียวที่กันข้ามโปรเซสได้ถ้าวันหนึ่งต้องกลับไปหลาย engine"""
    assert hasattr(ratelimit, "FileTokenBucket")
    assert hasattr(ratelimit.FileTokenBucket, "acquire")
