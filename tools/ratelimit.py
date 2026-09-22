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
