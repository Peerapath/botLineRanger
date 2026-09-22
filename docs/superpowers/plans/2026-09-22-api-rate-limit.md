# API Rate-Limit Pacer / Per-IP Bucket / Proxy Hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the bot's 50–300 headless workers from tripping the two rangers-api rate limits (per-account 300 ms min-gap answered as HTTP 400 + `errorCode 429`, and nginx per-IP ~100 req/s answered as HTTP 429) by shaping every request in one place, with an env-driven proxy hook so worker groups can later be spread over several egress IPs.

**Architecture:** A new stdlib-only module `tools/ratelimit.py` holds an in-process `AccountPacer` (min gap per cookie), a cross-process `IpBucket` (token bucket in a lock file, one file per proxy+host), an `is_app_429()` detector, and proxy/env helpers. Both HTTP funnels (`tools/rangers_api.py::call` and `tools/new_account.py::_do`) call pacer → bucket → send → pacer.done and treat app-429 like 429/503 (backoff + retry). `bot/main.py::_spawn_worker` passes the budget, proxy and lock dir to each worker through environment variables read from `config.ini`.

**Tech Stack:** Python 3.14 standard library (`msvcrt`/`fcntl` file locks, `http.client`, `urllib`), pytest 9 for tests (plain functions + `monkeypatch`, as in `tools/tests/test_relogin.py`).

Spec: `docs/superpowers/specs/2026-09-22-api-rate-limit-design.md`

## Global Constraints

- `tools/ratelimit.py` and everything it touches in `tools/new_account.py` stay **standard library only** (new_account is deliberately dependency-free).
- Env variables and defaults, verbatim from the spec: `LGRGS_MIN_GAP_MS=350`, `LGRGS_RPS_BUDGET=80` (`0` = bucket off), `LGRGS_RPS_BURST=20`, `LGRGS_RL_DIR` (default `%TEMP%/lgrgs-ratelimit`), `LGRGS_PROXY=""` (`host:port` or `host:port:user:pass`).
- Bucket lock file name: `bucket-<proxy_id>-<host>.txt`, `proxy_id` = `direct` or `sha1(LGRGS_PROXY)[:8]`, content `"<tokens> <ts>"`.
- `pacer.done(key)` is called after **every** received response (2xx/4xx/5xx alike); never after a socket error.
- The limiter must never crash a request: lock/file failures disable the bucket (warn once) instead of raising.
- A malformed `LGRGS_PROXY` raises `ValueError` at import time.
- Retry ceiling stays `LGRGS_MAX_RETRY` (default 8) in both funnels; after the last attempt the real status/body is returned.
- Config keys in `config.ini [settings]`: `apirps = 80`, `apiproxies =` (comma-separated).
- Run tests from the repo root: `python -m pytest tools/tests -q`.
- Commit after every task; commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/ratelimit.py` (create) | `is_app_429`, `AccountPacer`, `IpBucket`, `bucket_for(host)` cache, `PACER` singleton, `proxy_parts`/`proxy_url`, `parse_proxies`, `spawn_env` |
| `tools/tests/test_ratelimit.py` (create) | unit tests for the module above, incl. the two-subprocess bucket test |
| `tools/rangers_api.py` (modify) | wire pacer+bucket+app-429 retry into `call`; proxy tunnel in `_get_conn` |
| `tools/tests/test_rangers_api.py` (create) | fake-connection tests for `call` retry and proxy tunnel |
| `tools/new_account.py` (modify) | same wiring in `_do`; proxy opener |
| `tools/tests/test_new_account_do.py` (create) | fake-opener tests for `_do` |
| `tools/relogin.py` (modify) | app-429 counts as transient in `login` |
| `tools/tests/test_relogin.py` (modify) | one new test |
| `tools/stage_forge.py` (modify) | app-429 is transient in `enter`, re-post in `save` |
| `tools/tests/test_stage_forge.py` (modify) | two new tests |
| `bot/main.py` (modify) | read `apirps`/`apiproxies`, pass env in `_spawn_worker` |
| `bot/default_config/config.ini`, `bot/src/config.ini` (modify) | add the two keys |
| `tools/ratelimit_probe.py` (create) | integration probe: N workers through `rangers_api.call`, prints 429 counts |
| `README.md` (modify) | document the limits, env vars, config keys |

---

### Task 1: `ratelimit.py` — app-429 detector and `AccountPacer`

**Files:**
- Create: `tools/ratelimit.py`
- Create: `tools/tests/test_ratelimit.py`

**Interfaces:**
- Produces: `is_app_429(status: int, body) -> int | None` (gap ms, or `None` when not an app-429; `0` when the body has no usable `extras`)
- Produces: `class AccountPacer(min_gap_ms=None, clock=time.monotonic, sleep=time.sleep, max_keys=10000)` with `wait(key) -> float` (seconds slept) and `done(key) -> None`
- Produces: module constants `MIN_GAP_MS`, `RPS_BUDGET`, `BURST`, `PROXY` read from env at import, and the singleton `PACER = AccountPacer()`

- [ ] **Step 1: Write the failing tests**

Create `tools/tests/test_ratelimit.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/tests/test_ratelimit.py -q`
Expected: `ModuleNotFoundError: No module named 'ratelimit'`

- [ ] **Step 3: Write the module**

Create `tools/ratelimit.py`:

```python
r"""Client-side shaping for the two rangers-api rate limits (measured 2026-09-22, see
docs/superpowers/specs/2026-09-22-api-rate-limit-design.md).

1. Per account: a request that reaches the server < ~300 ms after it FINISHED the previous
   one for the same userKey is answered HTTP 400 + {"errorCode":429,"extras":{current,previous}}.
   Rejected calls count too, so hammering keeps you locked. -> AccountPacer keeps >= MIN_GAP_MS
   between "got the response" and "send the next one" per cookie, inside one process (an account
   is only ever driven by one worker at a time).
2. Per IP: nginx limit_req trips at ~100 req/s across everything this box sends (HTTP 429, HTML
   body). Workers are separate processes, so IpBucket is a token bucket in a lock file shared by
   every process that uses the same proxy (= egress IP) and host.

Standard library only: new_account.py must stay dependency-free.

Environment (also what bot/main.py hands each worker):
  LGRGS_MIN_GAP_MS  per-account gap, default 350
  LGRGS_RPS_BUDGET  bucket rate per IP+host, default 80; 0 disables the bucket
  LGRGS_RPS_BURST   bucket depth, default 20
  LGRGS_RL_DIR      lock-file directory, default %TEMP%/lgrgs-ratelimit
  LGRGS_PROXY       "host:port" or "host:port:user:pass"; empty = direct
"""

from __future__ import annotations

import base64
import hashlib
import os
import random
import sys
import tempfile
import threading
import time
import urllib.parse

MIN_GAP_MS = int(os.environ.get("LGRGS_MIN_GAP_MS", "350"))
RPS_BUDGET = float(os.environ.get("LGRGS_RPS_BUDGET", "80"))
BURST = int(os.environ.get("LGRGS_RPS_BURST", "20"))
PROXY = os.environ.get("LGRGS_PROXY", "")


def rl_dir() -> str:
    return os.environ.get("LGRGS_RL_DIR") or os.path.join(tempfile.gettempdir(), "lgrgs-ratelimit")


# --- app-level 429 --------------------------------------------------------------------------

def is_app_429(status, body):
    """Return the server-observed gap in ms when (status, body) is the per-account rejection
    (HTTP 400 + JSON errorCode 429), 0 if that rejection has no usable extras, else None."""
    if status != 400 or not isinstance(body, dict) or body.get("errorCode") != 429:
        return None
    extras = body.get("extras") or {}
    try:
        return int(extras.get("current")) - int(extras.get("previous"))
    except (TypeError, ValueError):
        return 0


# --- per-account pacer ----------------------------------------------------------------------

class AccountPacer:
    """Keep >= min_gap between the previous response and the next request, per key."""

    def __init__(self, min_gap_ms=None, clock=time.monotonic, sleep=time.sleep, max_keys=10000):
        self.gap = (MIN_GAP_MS if min_gap_ms is None else min_gap_ms) / 1000.0
        self._clock = clock
        self._sleep = sleep
        self._max = max_keys
        self._last = {}
        self._lock = threading.Lock()

    def wait(self, key) -> float:
        with self._lock:
            last = self._last.get(key)
        if last is None:
            return 0.0
        delay = last + self.gap - self._clock()
        if delay <= 0:
            return 0.0
        self._sleep(delay)
        return delay

    def done(self, key) -> None:
        with self._lock:
            if key not in self._last and len(self._last) >= self._max:
                self._last.clear()
            self._last[key] = self._clock()


PACER = AccountPacer()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/tests/test_ratelimit.py -q`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add tools/ratelimit.py tools/tests/test_ratelimit.py
git commit -m "feat(ratelimit): app-429 detector and per-account pacer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `ratelimit.py` — cross-process `IpBucket`, `bucket_for`, proxy and env helpers

**Files:**
- Modify: `tools/ratelimit.py` (append)
- Modify: `tools/tests/test_ratelimit.py` (append)

**Interfaces:**
- Consumes: `RPS_BUDGET`, `BURST`, `PROXY`, `rl_dir()` from Task 1
- Produces: `class IpBucket(host, rate=None, burst=None, rl_dir=None, proxy=None, clock=time.time, sleep=time.sleep)` with `acquire() -> None` and attribute `path`
- Produces: `bucket_for(host: str) -> IpBucket` (one cached instance per host per process)
- Produces: `proxy_parts(proxy=None) -> tuple[str, int, str | None] | None` (host, port, `"Basic ..."` header value or None); `proxy_url(proxy=None) -> str | None` (`http://[user:pass@]host:port`)
- Produces: `parse_proxies(text) -> list[str]`, `spawn_env(base_env, rps, proxies, index, rl_dir) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `tools/tests/test_ratelimit.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/tests/test_ratelimit.py -q`
Expected: failures with `AttributeError: module 'ratelimit' has no attribute 'IpBucket'` (and `proxy_parts`, `parse_proxies`, `spawn_env`, `_BUCKETS`)

- [ ] **Step 3: Append the implementation**

Append to `tools/ratelimit.py`:

```python
# --- per-IP token bucket (cross-process, lock file) -----------------------------------------

if os.name == "nt":
    import msvcrt

    def _lock(fh):
        # LK_LOCK gives up after 10 s with OSError; a busy box with hundreds of workers can hit
        # that legitimately, so just keep waiting.
        while True:
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                continue

    def _unlock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _proxy_id(proxy: str) -> str:
    return "direct" if not proxy else hashlib.sha1(proxy.encode()).hexdigest()[:8]


class IpBucket:
    """Token bucket shared by every process on this box that talks to `host` through the same
    proxy (= the same egress IP). State lives in one small lock file: "<tokens> <unix_ts>"."""

    def __init__(self, host, rate=None, burst=None, rl_dir=None, proxy=None,
                 clock=time.time, sleep=time.sleep):
        self.rate = RPS_BUDGET if rate is None else float(rate)
        self.burst = BURST if burst is None else int(burst)
        self._clock = clock
        self._sleep = sleep
        proxy = PROXY if proxy is None else proxy
        self.path = os.path.join(rl_dir or rl_dir_(), "bucket-%s-%s.txt" % (_proxy_id(proxy), host))
        self._disabled = self.rate <= 0

    def acquire(self) -> None:
        while not self._disabled:
            try:
                wait = self._take()
            except OSError as exc:
                print("ratelimit: bucket disabled (%s: %s)" % (self.path, exc), file=sys.stderr)
                self._disabled = True
                return
            if wait <= 0:
                return
            self._sleep(wait + random.uniform(0, 0.005))

    def _take(self) -> float:
        """One locked read-modify-write. Returns 0 when a token was taken, else seconds to wait."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        with os.fdopen(fd, "r+") as fh:
            _lock(fh)
            try:
                fh.seek(0)
                raw = fh.read()
                now = self._clock()
                try:
                    tokens, ts = (float(x) for x in raw.split())
                except ValueError:
                    tokens, ts = float(self.burst), now
                tokens = min(float(self.burst), tokens + max(0.0, now - ts) * self.rate)
                if tokens >= 1.0:
                    tokens -= 1.0
                    wait = 0.0
                else:
                    wait = (1.0 - tokens) / self.rate
                fh.seek(0)
                fh.truncate()
                fh.write("%.6f %.6f" % (tokens, now))
                fh.flush()
            finally:
                _unlock(fh)
        return wait


# rl_dir() is defined above; IpBucket reads it lazily so tests can set LGRGS_RL_DIR after import.
rl_dir_ = rl_dir

_BUCKETS: dict[str, IpBucket] = {}
_BUCKETS_LOCK = threading.Lock()


def bucket_for(host: str) -> IpBucket:
    """The process-wide bucket for `host` (through this process's LGRGS_PROXY)."""
    with _BUCKETS_LOCK:
        b = _BUCKETS.get(host)
        if b is None:
            b = _BUCKETS[host] = IpBucket(host)
        return b


# --- proxy / env helpers --------------------------------------------------------------------

def _split_proxy(proxy):
    parts = proxy.split(":")
    if len(parts) not in (2, 4) or not parts[0] or not parts[1].isdigit():
        raise ValueError("LGRGS_PROXY must be host:port or host:port:user:pass, got %r" % proxy)
    return parts


def proxy_parts(proxy=None):
    """(host, port, Proxy-Authorization value or None) for http.client.set_tunnel; None = direct."""
    proxy = PROXY if proxy is None else proxy
    if not proxy:
        return None
    parts = _split_proxy(proxy)
    auth = None
    if len(parts) == 4:
        auth = "Basic " + base64.b64encode(("%s:%s" % (parts[2], parts[3])).encode()).decode()
    return parts[0], int(parts[1]), auth


def proxy_url(proxy=None):
    """http://[user:pass@]host:port for urllib.request.ProxyHandler; None = direct."""
    proxy = PROXY if proxy is None else proxy
    if not proxy:
        return None
    parts = _split_proxy(proxy)
    cred = ""
    if len(parts) == 4:
        cred = "%s:%s@" % (urllib.parse.quote(parts[2], safe=""), urllib.parse.quote(parts[3], safe=""))
    return "http://%s%s:%s" % (cred, parts[0], parts[1])


def parse_proxies(text) -> list:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def spawn_env(base_env, rps, proxies, index, rl_dir_path) -> dict:
    """Environment for the index-th worker: shared budget, round-robin proxy, shared lock dir."""
    env = dict(base_env)
    env["LGRGS_RPS_BUDGET"] = str(rps)
    env["LGRGS_PROXY"] = proxies[index % len(proxies)] if proxies else ""
    env["LGRGS_RL_DIR"] = rl_dir_path
    return env


# Fail fast on a malformed proxy before anything is sent.
PROXY_PARTS = proxy_parts()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/tests/test_ratelimit.py -q`
Expected: `21 passed` (the subprocess test takes ~1.5 s)

- [ ] **Step 5: Commit**

```bash
git add tools/ratelimit.py tools/tests/test_ratelimit.py
git commit -m "feat(ratelimit): cross-process per-IP token bucket, proxy and spawn-env helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Wire `rangers_api.call` (pacer, bucket, app-429 retry, proxy tunnel)

**Files:**
- Modify: `tools/rangers_api.py:64-150` (`_get_conn`, `call`)
- Create: `tools/tests/test_rangers_api.py`

**Interfaces:**
- Consumes: `ratelimit.PACER.wait/done`, `ratelimit.bucket_for(HOST).acquire()`, `ratelimit.is_app_429`, `ratelimit.PROXY_PARTS`
- Produces: `call(cookie, path, method="GET", body=None, api=None) -> (status, parsed)` unchanged signature; new helper `_decode(raw: bytes, enc: str | None)` returning parsed JSON or text

- [ ] **Step 1: Write the failing tests**

Create `tools/tests/test_rangers_api.py`:

```python
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import pytest

import ratelimit
import rangers_api as ra

APP429 = json.dumps({"errorCode": 429, "extras": {"current": 20, "previous": 10}}).encode()
OK = json.dumps({"result": {"ok": True}}).encode()
NGINX = b"<html>429 Too Many Requests</html>"


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status = status
        self._body = body
        self._headers = headers or {}

    def read(self):
        return self._body

    def getheader(self, name):
        return self._headers.get(name)


class FakeConn:
    def __init__(self, script):
        self.script = list(script)      # [(status, body, headers), ...] consumed per request
        self.requests = []

    def request(self, method, url, body=None, headers=None):
        self.requests.append((method, url, body, headers))

    def getresponse(self):
        st, body, hdr = self.script.pop(0)
        return FakeResp(st, body, hdr)

    def close(self):
        pass


class Recorder:
    def __init__(self):
        self.waits = []
        self.dones = []
        self.acquired = 0
        self.sleeps = []

    def wait(self, key):
        self.waits.append(key); return 0.0

    def done(self, key):
        self.dones.append(key)

    def acquire(self):
        self.acquired += 1


@pytest.fixture
def wired(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(ratelimit, "PACER", rec)
    monkeypatch.setattr(ratelimit, "bucket_for", lambda host: rec)
    monkeypatch.setattr(ra, "_retry_sleep", lambda attempt, retry_after=None: rec.sleeps.append((attempt, retry_after)))
    return rec


def _wire_conn(monkeypatch, script):
    conn = FakeConn(script)
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    monkeypatch.setattr(ra, "_drop_conn", lambda: None)
    return conn


def test_call_paces_and_acquires_once_per_attempt(monkeypatch, wired):
    conn = _wire_conn(monkeypatch, [(200, OK, {})])
    st, data = ra.call("LF_AC=tok", "/home")
    assert (st, data) == (200, {"result": {"ok": True}})
    assert wired.waits == ["LF_AC=tok"] and wired.dones == ["LF_AC=tok"] and wired.acquired == 1
    assert conn.requests[0][1] == "/v12.3/home"


def test_call_retries_app_429_then_succeeds(monkeypatch, wired):
    _wire_conn(monkeypatch, [(400, APP429, {}), (400, APP429, {}), (200, OK, {})])
    st, data = ra.call("LF_AC=tok", "/stage/last")
    assert st == 200
    assert wired.sleeps == [(0, None), (1, None)]
    assert wired.dones == ["LF_AC=tok"] * 3          # rejected calls still stamp the pacer
    assert wired.acquired == 3


def test_call_retries_nginx_429_with_retry_after(monkeypatch, wired):
    _wire_conn(monkeypatch, [(429, NGINX, {"Retry-After": "2"}), (200, OK, {})])
    st, _ = ra.call("LF_AC=tok", "/stage/last")
    assert st == 200 and wired.sleeps == [(0, "2")]


def test_call_returns_real_status_after_last_attempt(monkeypatch, wired):
    monkeypatch.setattr(ra, "MAX_ATTEMPTS", 2)
    _wire_conn(monkeypatch, [(400, APP429, {}), (400, APP429, {})])
    st, data = ra.call("LF_AC=tok", "/stage/last")
    assert st == 400 and data["errorCode"] == 429 and len(wired.sleeps) == 1


def test_call_does_not_retry_plain_400(monkeypatch, wired):
    _wire_conn(monkeypatch, [(400, json.dumps({"errorCode": 102205}).encode(), {})])
    st, data = ra.call("LF_AC=tok", "/stage/save/1/st01", "POST", b"{}")
    assert st == 400 and data["errorCode"] == 102205 and wired.sleeps == []


def test_call_gunzips_and_falls_back_to_text(monkeypatch, wired):
    _wire_conn(monkeypatch, [(200, gzip.compress(OK), {"Content-Encoding": "gzip"})])
    assert ra.call("LF_AC=t", "/home")[1] == {"result": {"ok": True}}
    _wire_conn(monkeypatch, [(503, b"<html>maint</html>", {})])
    monkeypatch.setattr(ra, "MAX_ATTEMPTS", 1)
    assert ra.call("LF_AC=t", "/home") == (503, "<html>maint</html>")


class FakeHTTPS:
    made = []

    def __init__(self, host, port=None, timeout=None):
        self.host, self.port, self.tunnel = host, port, None
        FakeHTTPS.made.append(self)

    def set_tunnel(self, host, port=None, headers=None):
        self.tunnel = (host, port, headers)


def test_get_conn_direct(monkeypatch):
    FakeHTTPS.made.clear()
    monkeypatch.setattr(ra.http.client, "HTTPSConnection", FakeHTTPS)
    monkeypatch.setattr(ratelimit, "PROXY_PARTS", None)
    ra._drop_conn()
    c = ra._get_conn()
    assert (c.host, c.tunnel) == (ra.HOST, None)
    ra._drop_conn()


def test_get_conn_tunnels_through_proxy(monkeypatch):
    FakeHTTPS.made.clear()
    monkeypatch.setattr(ra.http.client, "HTTPSConnection", FakeHTTPS)
    monkeypatch.setattr(ratelimit, "PROXY_PARTS", ("10.0.0.1", 8080, "Basic dTpw"))
    ra._drop_conn()
    c = ra._get_conn()
    assert (c.host, c.port) == ("10.0.0.1", 8080)
    assert c.tunnel == (ra.HOST, 443, {"Proxy-Authorization": "Basic dTpw"})
    ra._drop_conn()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/tests/test_rangers_api.py -q`
Expected: `test_call_paces_and_acquires_once_per_attempt` fails (`wired.waits == []`), `test_call_retries_app_429_then_succeeds` fails (`st == 400`), proxy tests fail (`c.tunnel is None`)

- [ ] **Step 3: Modify `tools/rangers_api.py`**

Add the import after `import urllib.request` (top of file):

```python
import ratelimit
```

Replace `_get_conn` (the function starting `def _get_conn():`) with:

```python
def _get_conn():
    conn = getattr(_conn_tls, "conn", None)
    if conn is None:
        proxy = ratelimit.PROXY_PARTS
        if proxy:
            phost, pport, auth = proxy
            conn = http.client.HTTPSConnection(phost, pport, timeout=25)
            conn.set_tunnel(HOST, 443, headers={"Proxy-Authorization": auth} if auth else None)
        else:
            conn = http.client.HTTPSConnection(HOST, timeout=25)
        _conn_tls.conn = conn
    return conn
```

Add this helper right after `_drop_conn`:

```python
def _decode(raw: bytes, enc):
    if enc == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")
```

Replace the whole body of `call` (from `now = int(time.time() * 1000)` through the final `return`) with:

```python
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)     # pre-serialized (e.g. /stage/save wants compact, key-sorted JSON)
    else:
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    url = (api or API) + path
    bucket = ratelimit.bucket_for(HOST)
    status, parsed = 0, ""
    # http.client returns 4xx/5xx as a normal response (no exception), so no HTTPError branch is
    # needed. Three retry reasons: a dropped keep-alive socket (reconnect immediately), a nginx
    # 429/503 (per-IP overload), and the per-account HTTP 400 + errorCode 429 min-gap rejection.
    # Before every attempt: keep the per-account gap, then take a per-IP token.
    for attempt in range(MAX_ATTEMPTS):
        now = int(time.time() * 1000)
        headers = {
            "Host": HOST,
            "Accept": "*/*",
            "Content-Type": "application/json; charset=utf-8;",
            "App-Version": "LGRGS/%s;android/12" % CLIENT_VERSION,
            "User-Agent": "LGRGS/%s (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)" % CLIENT_VERSION,
            "Accept-Language": "en",
            "X-LINEGAME-MCC": "000",
            "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": str(now),
            "timeID": str(now),
            "Cookie": cookie,
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
        }
        ratelimit.PACER.wait(cookie)
        bucket.acquire()
        conn = _get_conn()
        try:
            conn.request(method, url, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()          # must read the full body to keep the connection reusable
            status = resp.status
            enc = resp.getheader("Content-Encoding")
            retry_after = resp.getheader("Retry-After")
        except (http.client.HTTPException, OSError):
            _drop_conn()
            if attempt == MAX_ATTEMPTS - 1:
                raise
            continue               # dropped socket: reconnect and retry right away
        ratelimit.PACER.done(cookie)   # the server stamps rejected calls too
        parsed = _decode(raw, enc)
        limited = status in RETRY_STATUSES or ratelimit.is_app_429(status, parsed) is not None
        if limited and attempt < MAX_ATTEMPTS - 1:
            _retry_sleep(attempt, retry_after)
            continue               # rate-limited/overloaded: wait, then retry
        break
    return status, parsed
```

Also update the comment block above `RETRY_STATUSES` (keep the constants) by appending one line:

```python
# The per-account limit answers HTTP 400 + {"errorCode":429} instead - detected via
# ratelimit.is_app_429 and retried the same way (see tools/ratelimit.py).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/tests/test_rangers_api.py tools/tests/test_stage_forge.py -q`
Expected: all pass (stage_forge tests still pass because `call` keeps its signature)

- [ ] **Step 5: Commit**

```bash
git add tools/rangers_api.py tools/tests/test_rangers_api.py
git commit -m "feat(rangers_api): pace per account, per-IP bucket, retry app-429, proxy tunnel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Wire `new_account._do` (pacer, bucket per host, app-429 retry, proxy opener) and `relogin.login`

**Files:**
- Modify: `tools/new_account.py:167-222` (`_do` and the retry block above it)
- Modify: `tools/relogin.py:112-121` (`login` transient condition)
- Create: `tools/tests/test_new_account_do.py`
- Modify: `tools/tests/test_relogin.py` (append one test)

**Interfaces:**
- Consumes: `ratelimit.PACER`, `ratelimit.bucket_for(host)`, `ratelimit.is_app_429`, `ratelimit.proxy_url()`
- Produces: `new_account._open(req)` (single place that picks proxy opener vs `urlopen`), `new_account._parse(raw, headers)`; `_do(req) -> (status, parsed, set_cookies)` unchanged signature

- [ ] **Step 1: Write the failing tests**

Create `tools/tests/test_new_account_do.py`:

```python
import email.message
import io
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import pytest

import new_account as na
import ratelimit

APP429 = json.dumps({"errorCode": 429, "extras": {"current": 20, "previous": 10}}).encode()
OK = json.dumps({"result": {"rsn": "abc"}}).encode()


def _headers(**kw):
    h = email.message.Message()
    for k, v in kw.items():
        h[k.replace("_", "-")] = v
    return h


class FakeResp:
    def __init__(self, status, body, headers):
        self.status, self._body, self.headers = status, body, headers

    def read(self):
        return self._body


class Recorder:
    def __init__(self):
        self.waits, self.dones, self.acquired, self.hosts, self.sleeps = [], [], 0, [], []

    def wait(self, key):
        self.waits.append(key); return 0.0

    def done(self, key):
        self.dones.append(key)

    def acquire(self):
        self.acquired += 1


@pytest.fixture
def wired(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(ratelimit, "PACER", rec)

    def bucket_for(host):
        rec.hosts.append(host); return rec
    monkeypatch.setattr(ratelimit, "bucket_for", bucket_for)
    monkeypatch.setattr(na, "_retry_sleep", lambda attempt, retry_after=None: rec.sleeps.append((attempt, retry_after)))
    return rec


def _script(monkeypatch, items):
    """items: list of (status, body, headers); 4xx/5xx are raised as HTTPError like urlopen does."""
    items = list(items)

    def fake_open(req):
        st, body, hdr = items.pop(0)
        if st >= 400:
            raise urllib.error.HTTPError(req.full_url, st, "err", hdr, io.BytesIO(body))
        return FakeResp(st, body, hdr)
    monkeypatch.setattr(na, "_open", fake_open)


def _req(cookie=None, host="rangers-api.line-apps.com"):
    h = {"Cookie": cookie} if cookie else {}
    return urllib.request.Request("https://%s/v12.3/login" % host, headers=h, method="GET")


def test_do_keys_pacer_by_cookie_and_bucket_by_host(monkeypatch, wired):
    _script(monkeypatch, [(200, OK, _headers(Set_Cookie="LF_AC=new; Path=/"))])
    st, parsed, cookies = na._do(_req("cc=1; udid=2; guestCookie=3;"))
    assert st == 200 and parsed["result"]["rsn"] == "abc" and cookies == ["LF_AC=new; Path=/"]
    assert wired.waits == ["cc=1; udid=2; guestCookie=3;"] == wired.dones
    assert wired.hosts == ["rangers-api.line-apps.com"] and wired.acquired == 1


def test_do_keys_pacer_by_url_without_cookie(monkeypatch, wired):
    _script(monkeypatch, [(200, OK, _headers())])
    na._do(_req(host="game-api.line.me"))
    assert wired.waits == ["https://game-api.line.me/v12.3/login"]
    assert wired.hosts == ["game-api.line.me"]


def test_do_retries_app_429(monkeypatch, wired):
    _script(monkeypatch, [(400, APP429, _headers()), (200, OK, _headers())])
    st, parsed, _ = na._do(_req("c=1"))
    assert st == 200 and wired.sleeps == [(0, None)] and wired.dones == ["c=1", "c=1"]


def test_do_retries_http_429_with_retry_after(monkeypatch, wired):
    _script(monkeypatch, [(429, b"<html>", _headers(Retry_After="3")), (200, OK, _headers())])
    st, _, _ = na._do(_req("c=1"))
    assert st == 200 and wired.sleeps == [(0, "3")]


def test_do_returns_last_status_after_retries(monkeypatch, wired):
    monkeypatch.setattr(na, "_MAX_ATTEMPTS", 2)
    _script(monkeypatch, [(400, APP429, _headers()), (400, APP429, _headers())])
    st, parsed, _ = na._do(_req("c=1"))
    assert st == 400 and parsed["errorCode"] == 429 and len(wired.sleeps) == 1


def test_do_network_error_backs_off_without_done(monkeypatch, wired):
    calls = {"n": 0}

    def fake_open(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("boom")
        return FakeResp(200, OK, _headers())
    monkeypatch.setattr(na, "_open", fake_open)
    st, _, _ = na._do(_req("c=1"))
    assert st == 200 and wired.sleeps == [(0, None)] and wired.dones == ["c=1"] and wired.acquired == 2


def test_open_uses_proxy_opener_when_configured(monkeypatch):
    seen = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            seen["req"] = req; return "opened"
    monkeypatch.setattr(na, "_OPENER", FakeOpener())
    assert na._open(_req()) == "opened" and seen["req"].full_url.endswith("/v12.3/login")
    monkeypatch.setattr(na, "_OPENER", None)
    monkeypatch.setattr(na.urllib.request, "urlopen", lambda req, timeout=None: "direct")
    assert na._open(_req()) == "direct"


def test_build_opener_from_proxy_url():
    op = na._build_opener("http://u:p@10.0.0.1:8080")
    handlers = [type(h).__name__ for h in op.handlers]
    assert "ProxyHandler" in handlers
    assert na._build_opener(None) is None
```

Append to `tools/tests/test_relogin.py`:

```python
def test_login_app_429_after_retries_is_transient(monkeypatch):
    monkeypatch.setattr(relogin.na, "_do",
                        lambda req: (400, {"errorCode": 429, "extras": {"current": 2, "previous": 1}}, []))
    monkeypatch.setattr(relogin.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(relogin.Transient):
        relogin.login("CC", "U", "OLD", "TH")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/tests/test_new_account_do.py tools/tests/test_relogin.py -q`
Expected: new_account tests fail with `AttributeError: module 'new_account' has no attribute '_open'` (and `_OPENER`, `_build_opener`); the relogin test fails because `login` returns `(400, None, None)` instead of raising

- [ ] **Step 3: Modify `tools/new_account.py`**

Add after the existing imports at the top of the file (it already has `import os`, `import urllib.request`, etc.; keep them):

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratelimit  # noqa: E402
```

(If `import sys` is missing at the top, add it.)

Replace `_do` (from `def _do(req):` down to `return status, parsed, (set_cookies or [])`) with:

```python
def _build_opener(url):
    """urllib opener that tunnels through the http proxy `url`; None = plain urlopen."""
    if not url:
        return None
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": url, "https": url}))


_OPENER = _build_opener(ratelimit.proxy_url())


def _open(req):
    if _OPENER is not None:
        return _OPENER.open(req, timeout=25)
    return urllib.request.urlopen(req, timeout=25)


def _parse(raw, resp_headers):
    if resp_headers is not None and resp_headers.get("Content-Encoding") == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return raw.decode("utf-8", "replace")


def _do(req):
    # Per-account pacing keys on the Cookie (login carries cc/udid/guestCookie); cookie-less
    # bootstrap calls (auth/signup) key on the URL. The per-IP bucket is per destination host
    # because game-api.line.me and rangers-api.line-apps.com have separate limits.
    key = req.get_header("Cookie") or req.full_url
    bucket = ratelimit.bucket_for(req.host)
    raw, status, resp_headers, parsed = b"", 0, None, {}
    for attempt in range(_MAX_ATTEMPTS):
        ratelimit.PACER.wait(key)
        bucket.acquire()
        try:
            resp = _open(req)
            raw, status, resp_headers = resp.read(), resp.status, resp.headers
        except urllib.error.HTTPError as err:
            raw, status, resp_headers = err.read(), err.code, err.headers
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            _retry_sleep(attempt)               # network blip: back off and retry
            continue
        ratelimit.PACER.done(key)               # the server stamps rejected calls too
        parsed = _parse(raw, resp_headers)
        limited = status in _RETRY_STATUSES or ratelimit.is_app_429(status, parsed) is not None
        if limited and attempt < _MAX_ATTEMPTS - 1:
            _retry_sleep(attempt, resp_headers.get("Retry-After"))  # rate-limited: wait, retry
            continue
        break
    set_cookies = resp_headers.get_all("Set-Cookie") if hasattr(resp_headers, "get_all") else None
    return status, parsed, (set_cookies or [])
```

Extend the comment above `_RETRY_STATUSES` with one line:

```python
# The per-account min-gap limit answers HTTP 400 + errorCode 429; ratelimit.is_app_429 catches it.
```

In `tools/relogin.py`, add `import ratelimit  # noqa: E402` next to `import rangers_api  # noqa: E402`, and change the transient check inside `login` from:

```python
            if status == 429 or (isinstance(status, int) and 500 <= status < 600):
```

to:

```python
            if (status == 429 or ratelimit.is_app_429(status, res) is not None
                    or (isinstance(status, int) and 500 <= status < 600)):
```

and update the docstring line `retry เองเมื่อเจอ network error / 429 / 5xx (RETRY_WAITS)` to `retry เองเมื่อเจอ network error / 429 / app-429 (HTTP 400+errorCode 429) / 5xx (RETRY_WAITS)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/tests -q`
Expected: all pass (existing relogin/stage_forge tests included)

- [ ] **Step 5: Commit**

```bash
git add tools/new_account.py tools/relogin.py tools/tests/test_new_account_do.py tools/tests/test_relogin.py
git commit -m "feat(new_account): pace, bucket per host, retry app-429, proxy opener; relogin treats app-429 as transient

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `stage_forge` — app-429 is transient on enter, re-post on save

**Files:**
- Modify: `tools/stage_forge.py:196-260` (`enter`, `clear_stage` save loop)
- Modify: `tools/tests/test_stage_forge.py` (append)

**Interfaces:**
- Consumes: `ratelimit.is_app_429`
- Produces: no signature changes; `enter` returns `(status, result, error)` with `error == 429` for the app-429 case so `run`'s existing transient path (backoff + retry) handles it

- [ ] **Step 1: Write the failing tests**

Append to `tools/tests/test_stage_forge.py`:

```python
APP429 = {"errorCode": 429, "extras": {"current": 20, "previous": 10}}


def test_enter_app_429_is_transient_not_tutorial_fallback(monkeypatch):
    calls = []

    def fake_call(cookie, path, method="GET", body=None, api=None):
        calls.append(path)
        return 400, APP429
    monkeypatch.setattr(sf, "call", fake_call)
    status, result, error = sf.enter("LF_AC=t", "st05")
    assert (status, error) == (400, 429)
    assert calls == ["/stage/enter/st05"]          # no /tutorial/stage/enter fallback


def test_clear_stage_reposts_same_battlesn_after_app_429(monkeypatch):
    posted = []
    enter_result = dict(_enter(), player={"hearts": {"total": 5}}, isEnterable=True)
    script = [(400, APP429), (200, {"result": {"battleResult": {"isCleared": True, "rewardExp": 10,
                                                                   "afterRewardPlayer": {"level": 2}}}})]

    def fake_call(cookie, path, method="GET", body=None, api=None):
        if path.startswith("/stage/enter/"):
            return 200, {"result": enter_result}
        posted.append(path)
        return script.pop(0)
    monkeypatch.setattr(sf, "call", fake_call)
    monkeypatch.setattr(sf.time, "sleep", lambda s: None)
    cleared, info = sf.clear_stage("LF_AC=t", "st02", "40cf0a20", pt=1)
    assert cleared and info["step"] == "save" and len(posted) == 2
    assert posted[0].split("?")[0] == posted[1].split("?")[0]   # same /stage/save/<battleSn>/st02
```

(`clear_stage(cookie, stc, rsn, pt=1)` is the enter → wait → save function at `tools/stage_forge.py:223`; the flow under test is: enter OK → first save answered app-429 → second save on the same path → cleared.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/tests/test_stage_forge.py -q -k "app_429"`
Expected: first test fails with `calls == ["/stage/enter/st05", "/tutorial/stage/enter/st05?tutorialType=START"]`; second fails with `len(posted) == 1`

- [ ] **Step 3: Modify `tools/stage_forge.py`**

Next to `from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402` add:

```python
import ratelimit  # noqa: E402
```

In `enter`, change:

```python
    if error in LOCKED or error == ERR_SUSPECTED_ABUSING or status in (401, 429) or status >= 500:
        return status, result, error
```

to:

```python
    if (error in LOCKED or error == ERR_SUSPECTED_ABUSING or status in (401, 429) or status >= 500
            or ratelimit.is_app_429(status, data) is not None):
        return status, result, error   # transient/locked: never try the tutorial route
```

In the save loop inside `clear_stage`, change:

```python
        error = _error_code(data)
        if error != ERR_BAD_BATTLE:
            break
        # the battle is still open and no heart was spent: wait again and re-post the same battleSn
        entered = time.time()
```

to:

```python
        error = _error_code(data)
        if error != ERR_BAD_BATTLE and ratelimit.is_app_429(status, data) is None:
            break
        # 102205 or a per-account rate-limit rejection: the battle is still open and no heart was
        # spent, so wait the margin again and re-post the same battleSn
        entered = time.time()
```

Update the module docstring line `rangers_api backs off on 429/503. Lower it only for short ranges.` to `rangers_api backs off on 429/503 and on the per-account HTTP 400/errorCode 429 (ratelimit.py), so --delay 0 is safe; the default keeps a polite per-account pace.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/tests/test_stage_forge.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tools/stage_forge.py tools/tests/test_stage_forge.py
git commit -m "fix(stage_forge): treat per-account 429 as transient on enter and re-post on save

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `bot/main.py` — config keys and worker environment

**Files:**
- Modify: `bot/main.py` (`_spawn_worker`, ~line 1699 region; `__init__` config block ~line 337)
- Modify: `bot/default_config/config.ini`, `bot/src/config.ini` (`[settings]`)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `ratelimit.parse_proxies`, `ratelimit.spawn_env`, `TOOLSDIR` (already exported by `from botLineRanger import *`)
- Produces: `EmulatorManager._worker_env() -> dict` and `_spawn_worker` passing `env=` to `subprocess.Popen`

- [ ] **Step 1: Add the config keys**

In `bot/default_config/config.ini` and `bot/src/config.ini`, inside `[settings]` right after `threadcount = ...` add:

```ini
apirps = 80
apiproxies =
```

- [ ] **Step 2: Write the helper and use it in `_spawn_worker`**

In `bot/main.py`, add this method to `EmulatorManager` immediately above `_spawn_worker`:

```python
    def _worker_env(self):
        """env ให้ worker คุม rate limit ร่วมกันทั้งเครื่อง (ดู tools/ratelimit.py):
        งบ req/s ต่อ IP, proxy แจกวนตามลำดับ worker, และโฟลเดอร์ lock file ที่ทุก worker ใช้ร่วมกัน"""
        if TOOLSDIR not in sys.path:
            sys.path.insert(0, TOOLSDIR)
        import ratelimit
        rps = self.config.get("settings", "apirps", fallback="80").strip() or "80"
        proxies = ratelimit.parse_proxies(self.config.get("settings", "apiproxies", fallback=""))
        index = self._worker_seq
        self._worker_seq += 1
        rl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ratelimit")
        return ratelimit.spawn_env(os.environ, rps, proxies, index, rl_dir)
```

In `__init__`, right after `self.thread_count = max(1, min(self.thread_count, 1024))`, add:

```python
        self._worker_seq = 0   # ลำดับ worker ที่สปอว์น ใช้แจก proxy วน (ดู _worker_env)
```

In `_spawn_worker`, change the final line:

```python
        return subprocess.Popen(args, cwd=botdir, creationflags=no_window)
```

to:

```python
        return subprocess.Popen(args, cwd=botdir, creationflags=no_window, env=self._worker_env())
```

Add to `.gitignore`:

```
bot/.ratelimit/
```

- [ ] **Step 3: Verify by importing the GUI module headlessly**

Run from `bot/`:

```
python -c "import sys; sys.argv=['x']; import main; print('import ok')"
```

Expected: `import ok` (no syntax error; the window is not created at import). Then run:

```
python - <<'EOF'
import configparser, os, sys
sys.path.insert(0, os.path.abspath("../tools"))
import ratelimit
cfg = configparser.ConfigParser(); cfg.read("src/config.ini")
print(cfg.get("settings", "apirps"), ratelimit.parse_proxies(cfg.get("settings", "apiproxies")))
EOF
```

Expected: `80 []`

- [ ] **Step 4: Smoke-run one worker with the env**

From `bot/`, with `LGRGS_RPS_BUDGET=80 LGRGS_RL_DIR=./.ratelimit`, start the GUI, set thread count 2, start Login mode for a few seconds and stop. Expected: `bot/.ratelimit/bucket-direct-rangers-api.line-apps.com.txt` exists and its content looks like `19.417 1790099999.123`.

- [ ] **Step 5: Commit**

```bash
git add bot/main.py bot/default_config/config.ini bot/src/config.ini .gitignore
git commit -m "feat(bot): apirps/apiproxies config, hand rate-limit env to each worker

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Integration probe tool and README

**Files:**
- Create: `tools/ratelimit_probe.py`
- Modify: `README.md` (the stage-forge section around line 331 and a new "Rate limit" subsection)

**Interfaces:**
- Consumes: `rangers_api.call`, `relogin.read_account/decrypt_lfac/login/CcPool` (to mint fresh tokens from `bot/input/*.xml`)
- Produces: CLI `python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10 --path /stage/last`

- [ ] **Step 1: Write the probe**

Create `tools/ratelimit_probe.py`:

```python
r"""Hammer rangers-api through rangers_api.call from N threads (one fresh guest token each) and
report how many nginx 429 / app-429 (HTTP 400 + errorCode 429) slipped through the limiter.

    python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10

With the limiter on (default env) both counts must be 0 and the throughput ~LGRGS_RPS_BUDGET.
Set LGRGS_RPS_BUDGET=0 LGRGS_MIN_GAP_MS=0 to see the raw server behaviour again.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratelimit  # noqa: E402
import rangers_api  # noqa: E402
import relogin  # noqa: E402


def fresh_token(xml_path, pool):
    acc = relogin.read_account(xml_path)
    guest_cookie = relogin.decrypt_lfac(acc["udid"], acc["enc"])
    _st, _res, lf = relogin.login(pool.get(), acc["udid"], guest_cookie, acc["nation"], acc["language"])
    return "LF_AC=" + lf if lf else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml-dir", default="bot/input")
    ap.add_argument("--workers", type=int, default=150)
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--path", default="/stage/last")
    args = ap.parse_args(argv)

    xmls = sorted(glob.glob(os.path.join(args.xml_dir, "*.xml")))[:args.workers]
    pool = relogin.CcPool()
    with cf.ThreadPoolExecutor(10) as ex:
        tokens = [t for t in ex.map(lambda x: fresh_token(x, pool), xmls) if t]
    print("tokens: %d/%d" % (len(tokens), len(xmls)))

    counts, lock = {}, threading.Lock()
    t_end = time.time() + args.seconds

    def worker(tok):
        while time.time() < t_end:
            status, body = rangers_api.call(tok, args.path)
            kind = ("app429" if ratelimit.is_app_429(status, body) is not None
                    else "nginx429" if status == 429 else "ok" if status == 200 else "other%s" % status)
            with lock:
                counts[kind] = counts.get(kind, 0) + 1

    t0 = time.time()
    with cf.ThreadPoolExecutor(len(tokens)) as ex:
        list(ex.map(worker, tokens))
    total = sum(counts.values())
    print("workers=%d total=%d rps=%.1f counts=%s" % (len(tokens), total, total / (time.time() - t0), counts))
    return 0 if not counts.get("app429") and not counts.get("nginx429") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the probe with the limiter on**

Run from the repo root:

```
python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10
```

Expected: `counts={'ok': N}` with no `app429`/`nginx429` keys, `rps` ≈ 75–80, exit code 0. Note: with 150 threads on one shared bucket of 80 req/s each thread only gets ~0.5 req/s, which is the intended shape.

- [ ] **Step 3: Run the probe with the limiter off (control)**

```
set LGRGS_RPS_BUDGET=0
set LGRGS_MIN_GAP_MS=0
set LGRGS_MAX_RETRY=1
python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10
```

Expected: `nginx429` and/or `app429` present, exit code 1 (this reproduces the 2026-09-22 measurement and proves the limiter is what fixed it). Unset the three variables afterwards.

- [ ] **Step 4: Document in README**

In `README.md`, replace the two lines starting `- เซิร์ฟเวอร์มี rate limit: เว้นระยะระหว่างด่านด้วย `--delay`` with:

```markdown
- เซิร์ฟเวอร์มี rate limit 2 ชั้น (วัด 2026-09-22): ต่อไอดีห้ามยิงซ้ำภายใน ~300 ms หลังคำตอบก่อนหน้า
  (ตอบ HTTP 400 + `errorCode 429`) และต่อ IP ~100 req/s (nginx ตอบ HTTP 429) — `tools/ratelimit.py`
  คุมให้ทั้งสองชั้นแล้ว (pacer 350 ms ต่อไอดี + token bucket 80 req/s ต่อ IP ใช้ร่วมกันทุก worker)
  `--delay` จึงเป็นแค่จังหวะพักต่อไอดี ตั้ง `--delay 0` ได้ปลอดภัย
```

Add a new subsection at the end of the API tools section:

```markdown
### Rate limit (tools/ratelimit.py)

ทุก request ที่ผ่าน `rangers_api.call` และ `new_account._do` จะ (1) รอให้ห่างจากคำตอบก่อนหน้าของไอดีเดิม
≥ 350 ms (2) ขอตั๋วจาก token bucket ต่อ IP+host ที่ทุกโปรเซสในเครื่องใช้ร่วมกันผ่าน lock file
(3) ถ้าเจอ HTTP 429/503 หรือ HTTP 400 + `errorCode 429` จะ backoff แล้วยิงซ้ำเอง (สูงสุด `LGRGS_MAX_RETRY`)

| env | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `LGRGS_MIN_GAP_MS` | 350 | ช่วงห่างขั้นต่ำต่อไอดี |
| `LGRGS_RPS_BUDGET` | 80 | งบ req/s ต่อ IP (0 = ปิด bucket) |
| `LGRGS_RPS_BURST` | 20 | ความลึกของ bucket |
| `LGRGS_RL_DIR` | `%TEMP%/lgrgs-ratelimit` | โฟลเดอร์ lock file (บอทตั้งเป็น `bot/.ratelimit`) |
| `LGRGS_PROXY` | ว่าง | `host:port[:user:pass]` ออกทาง proxy ตัวนี้ (bucket แยกต่อ proxy) |

บอท GUI อ่าน `config.ini [settings] apirps` และ `apiproxies` (คั่นด้วยจุลภาค แจกวนให้ worker ทีละตัว)
แล้วส่งเป็น env ให้ worker ทุกตัว ตรวจว่าตัวคุมทำงานด้วย
`python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10` (ต้องได้ 0 ทั้ง 429 สองแบบ)
```

- [ ] **Step 5: Run the whole suite and commit**

Run: `python -m pytest tools/tests -q`
Expected: all pass

```bash
git add tools/ratelimit_probe.py README.md
git commit -m "docs: rate-limit section and integration probe tool

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec §1 (`ratelimit.py`) → Tasks 1–2. §2 (wiring, relogin, stage_forge) → Tasks 3–5. §3 (proxy hook) → Tasks 2 (helpers), 3 (`set_tunnel`), 4 (`ProxyHandler`), 6 (round-robin). §4 (config/GUI) → Task 6. §5 (error handling: disable-not-crash, fail-fast proxy) → Task 2. Testing section → each task's tests + Task 7 probe.
- Naming used consistently: `ratelimit.PACER`, `ratelimit.bucket_for(host)`, `ratelimit.is_app_429`, `ratelimit.PROXY_PARTS`, `ratelimit.proxy_url()`, `ratelimit.parse_proxies`, `ratelimit.spawn_env`, `new_account._open/_OPENER/_build_opener/_parse`, `rangers_api._decode`.
- Task 2 defines `rl_dir_ = rl_dir` only so `IpBucket.__init__` can reference the function defined earlier in the file without shadowing its `rl_dir` parameter; keep both names.
