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
import re
import sys
import tempfile
import threading
import time
import urllib.parse

MIN_GAP_MS = int(os.environ.get("LGRGS_MIN_GAP_MS") or "350")
RPS_BUDGET = float(os.environ.get("LGRGS_RPS_BUDGET") or "80")
BURST = int(os.environ.get("LGRGS_RPS_BURST") or "20")
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


# --- per-IP token bucket (cross-process, lock file) -----------------------------------------

_LOCK_TIMEOUT_S = 10.0   # give up -> LockTimeout -> acquire() paces and retries instead of hanging


class LockTimeout(OSError):
    """The bucket file stayed locked for _LOCK_TIMEOUT_S; the caller waits one token period and retries."""


if os.name == "nt":
    import msvcrt

    def _lock(fh):
        # LK_LOCK only retries once per second, which starves contending workers (measured: one
        # of 8 processes got 58 tokens, others 1-2). Poll LK_NBLCK with a few-ms jittered sleep
        # instead; a lock that never frees within _LOCK_TIMEOUT_S raises so acquire() can bail.
        deadline = time.monotonic() + _LOCK_TIMEOUT_S
        while True:
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LockTimeout("bucket file stayed locked for %.1fs" % _LOCK_TIMEOUT_S) from exc
                time.sleep(random.uniform(0.001, 0.005))

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
        # burst < 1 can never reach the 1-token threshold -> acquire() would wait forever.
        self.burst = max(1, BURST if burst is None else int(burst))
        self._clock = clock
        self._sleep = sleep
        proxy = PROXY if proxy is None else proxy
        safe_host = re.sub(r"[^A-Za-z0-9._-]", "_", host)     # "host:port" is not a valid file name
        self.path = os.path.join(rl_dir or rl_dir_(), "bucket-%s-%s.txt" % (_proxy_id(proxy), safe_host))
        self._disabled = self.rate <= 0
        self._fails = 0             # consecutive file/lock failures; 3 in a row disable the bucket
        self._warned_timeout = False
        if not self._disabled:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
            except OSError:
                pass            # os.open in _take() reports it, and acquire() disables the bucket

    def acquire(self) -> None:
        while not self._disabled:
            try:
                wait = self._take()
            except LockTimeout as exc:
                # fail closed: pace at the budget and keep the cap armed; say so once
                if not self._warned_timeout:
                    self._warned_timeout = True
                    print("ratelimit: bucket lock timeout, pacing at budget (%s: %s)" % (self.path, exc),
                          file=sys.stderr)
                self._sleep(1.0 / self.rate)
                continue
            except OSError as exc:
                # Transient file trouble (AV scan, sharing violation, lock dir wiped mid-run) must
                # not switch the cap off for the rest of the process: recreate the dir and retry,
                # and only three consecutive failures disable the bucket.
                self._fails += 1
                try:
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                except OSError:
                    pass
                if self._fails < 3:
                    self._sleep(0.05)
                    continue
                print("ratelimit: bucket disabled after %d failures (%s: %s)" % (self._fails, self.path, exc),
                      file=sys.stderr)
                self._disabled = True
                return
            self._fails = 0
            if wait <= 0:
                return
            self._sleep(wait + random.uniform(0, 0.005))

    def _take(self) -> float:
        """One locked read-modify-write. Returns 0 when a token was taken, else seconds to wait."""
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
