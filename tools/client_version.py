r"""App-Version and URL prefix for every rangers-api call - chosen here, learned from the server.

On 2026-09-24 /signup/platform started answering 401 to App-Version 12.3.0 and GenID made zero
accounts with nothing in any log to say why; 12.2.0 was found by hand (commit abd580e). The
next game update will do the same to some other value. So no call site hardcodes a version or
a /v12.x prefix any more: each hands request() a send(prefix, app_version) function, and this
module is the one place that decides what those are - and notices when the server refuses them.

Design: docs/superpowers/specs/2026-09-24-client-version-autoswitch-design.md
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

import ratelimit

DEFAULT_APP_VERSION = "12.3.0"
DEFAULT_PREFIX = "/v12.3"
# /signup/platform refuses 12.3.0 and 12.4.0 with 401 and takes 12.2.0 (measured 2026-09-24,
# one fresh pending guest per cell). Seeded so a fresh install starts right instead of spending
# three signup attempts rediscovering it - the 401 rule would find it anyway.
DEFAULT_PINS = {"/signup/platform": "12.2.0"}
# Every App-Version that answered 200 on /v12.3/home on 2026-09-24.
DEFAULT_KNOWN_GOOD = ("12.2.0", "12.3.0", "12.3.2", "12.4.0")
HISTORY_KEEP = 20
UNKNOWN_VERSION = 119801    # errorCode: the server does not know this build at all
ORACLE_PATH = "/home"
ORACLE_COOKIE = "LF_AC=0"   # deliberately invalid: the server checks the version BEFORE the token
DEAD_COOLDOWN = 30.0        # seconds to fail fast after a sweep found nothing (used by learning)

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PREFIX_RE = re.compile(r"^/v\d+\.\d+$")
_PREFIXED_PATH_RE = re.compile(r"^/v\d")


class VersionUnavailable(Exception):
    """No App-Version or URL prefix the server accepts could be found.

    A plain Exception on purpose, never SystemExit: SystemExit slips past `except Exception` and
    threading.excepthook drops it without a word (commit abd580e). The engine catches this by
    name and stops the run, instead of failing - and moving - every account one by one.
    """


def headers(app_version: str) -> dict:
    return {
        "App-Version": "LGRGS/%s;android/12" % app_version,
        "User-Agent": "LGRGS/%s (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)" % app_version,
    }


def route_of(path: str) -> str:
    """'/stage/save/1234/st02?reqId=9' -> '/stage/save/*/*': fine enough to tell signup from
    login, coarse enough not to grow one entry per stage number, battleSn or reward seq."""
    bare = path.split("?", 1)[0]
    return "/".join("*" if any(ch.isdigit() for ch in seg) else seg for seg in bare.split("/"))


def classify(status, parsed) -> str:
    code = parsed.get("errorCode") if isinstance(parsed, dict) else None
    if status == 200:
        return "ok"
    if status == 400 and code == UNKNOWN_VERSION:
        return "version_unknown"
    if status == 404 and code == 400:
        return "route_missing"
    if status == 401:
        return "unauthorized"
    return "other"


class ClientVersion:
    def __init__(self, path: str, oracle=None, learn: bool = True, clock=time.monotonic):
        self.path = path
        self.learn = learn
        self._oracle_fn = oracle
        self._clock = clock
        self._lock = threading.RLock()
        self._loaded = False
        self._listeners = []
        self.app_version = DEFAULT_APP_VERSION
        self.api_prefix = DEFAULT_PREFIX
        self.route_pins = dict(DEFAULT_PINS)
        self.known_good = list(DEFAULT_KNOWN_GOOD)
        self.history = []
        self._proven = set()          # (route, version) that answered 200 in this process
        self._not_version = set()     # (route, version) whose 401 sweep found nothing
        self._generation = 0          # bumped on every change - single-flight for sweeps
        self._dead_until = 0.0
        self._dead_reason = ""

    # --- storage ------------------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except FileNotFoundError:
                self._save()          # make the file exist so a human can read and edit it
                return
            except (OSError, ValueError):
                return                # unreadable: run on the defaults, never crash over it
            if not isinstance(data, dict):
                return
            version = data.get("app_version")
            if isinstance(version, str) and _VERSION_RE.match(version):
                self.app_version = version
            prefix = data.get("api_prefix")
            if isinstance(prefix, str) and _PREFIX_RE.match(prefix):
                self.api_prefix = prefix
            pins = data.get("route_pins")
            if isinstance(pins, dict):
                self.route_pins = {r: v for r, v in pins.items()
                                   if isinstance(r, str) and isinstance(v, str) and _VERSION_RE.match(v)}
            known = data.get("known_good")
            if isinstance(known, list):
                merged = [v for v in known if isinstance(v, str) and _VERSION_RE.match(v)]
                merged += [v for v in DEFAULT_KNOWN_GOOD if v not in merged]
                self.known_good = merged
            history = data.get("history")
            if isinstance(history, list):
                self.history = [h for h in history if isinstance(h, dict)][-HISTORY_KEEP:]

    def _save(self) -> None:
        data = {"app_version": self.app_version, "api_prefix": self.api_prefix,
                "route_pins": dict(self.route_pins), "known_good": list(self.known_good),
                "history": self.history[-HISTORY_KEEP:]}
        tmp = "%s.%d.%d.tmp" % (self.path, os.getpid(), threading.get_ident())
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            for _attempt in range(5):
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:       # Windows: a reader has it open this instant
                    time.sleep(0.05)
            os.replace(tmp, self.path)
        except OSError as err:
            # Losing the file costs one rediscovery next run; crashing here would cost the run.
            print("client_version: could not save %s: %s" % (self.path, err), file=sys.stderr)
            try:
                os.remove(tmp)
            except OSError:
                pass

    # --- what to send -------------------------------------------------------------------

    def _resolve(self, route, pinned_prefix):
        version = self.route_pins.get(route, self.app_version)
        return (pinned_prefix or self.api_prefix), version, self._generation

    def _mark_ok(self, route, version) -> None:
        if (route, version) in self._proven:
            return
        with self._lock:
            self._proven.add((route, version))
            if version not in self.known_good:
                self.known_good.append(version)
                self._save()

    def request(self, path, send, pinned_prefix=None):
        """Send once with the values this route should use and return what send() returned.

        send(prefix, app_version) must return a tuple whose [0] is the HTTP status and [1] the
        parsed body. Pass `path` WITHOUT its /v12.x prefix - adding it is this module's job.
        """
        if _PREFIXED_PATH_RE.match(path):
            raise ValueError("pass the path without its /v12.x prefix: %r" % (path,))
        self._load()
        route = route_of(path)
        with self._lock:
            prefix, version, _generation = self._resolve(route, pinned_prefix)
        result = send(prefix, version)
        if classify(result[0], result[1]) == "ok":
            self._mark_ok(route, version)
        return result

    # --- reporting ----------------------------------------------------------------------

    def current(self):
        self._load()
        with self._lock:
            return self.api_prefix, self.app_version

    def describe(self) -> str:
        self._load()
        with self._lock:
            pins = ", ".join("%s=%s" % kv for kv in sorted(self.route_pins.items())) or "none"
            return "api version: %s + %s (pins: %s)" % (self.api_prefix, self.app_version, pins)

    def on_switch(self, callback) -> None:
        self._listeners.append(callback)


# --- the process-wide instance ------------------------------------------------------------

_DEFAULT = None
_DEFAULT_LOCK = threading.Lock()
_ORACLE = None


def default_path() -> str:
    return os.environ.get("LGRGS_VERSION_FILE") or os.path.join(ratelimit.rl_dir(), "api_version.json")


def set_oracle(fn) -> None:
    """rangers_api registers its transport here on import (it cannot be imported from this
    module: rangers_api imports client_version)."""
    global _ORACLE
    _ORACLE = fn


def _registered_oracle():
    if _ORACLE is None:
        import rangers_api  # noqa: F401 - registers rangers_api._oracle through set_oracle()
    return _ORACLE


def configure(path: str | None = None, learn: bool = True) -> ClientVersion:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = ClientVersion(path or default_path(), learn=learn)
        return _DEFAULT


def instance() -> ClientVersion:
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = ClientVersion(default_path())
    return _DEFAULT


def request(path, send, pinned_prefix=None):
    return instance().request(path, send, pinned_prefix)


def current():
    return instance().current()


def describe() -> str:
    return instance().describe()


def on_switch(callback) -> None:
    instance().on_switch(callback)
