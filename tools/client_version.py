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


def _vkey(version: str) -> tuple:
    return tuple(int(x) for x in version.split("."))


def _pkey(prefix: str) -> tuple:
    return tuple(int(x) for x in prefix[2:].split("."))


def version_candidates(current: str) -> list:
    """Builds worth asking about when `current` stops being known: every patch 0-5 of its
    minor, the minors either side of it, and the next major. The caller sorts newest first."""
    major, minor, _patch = _vkey(current)
    out = ["%d.%d.%d" % (major, minor, p) for p in range(0, 6)]
    out += ["%d.%d.0" % (major, m) for m in range(max(0, minor - 1), minor + 3)]
    out.append("%d.0.0" % (major + 1))
    return out


def prefix_candidates(current: str) -> list:
    major, minor = _pkey(current)
    out = ["/v%d.%d" % (major, m) for m in range(max(0, minor - 1), minor + 4)]
    out.append("/v%d.0" % (major + 1))
    return out


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
        """Send with the values this route should use; on a version refusal, find values the
        server takes, re-send, remember them. Returns the tuple the LAST send() returned.

        send(prefix, app_version) must return a tuple whose [0] is the HTTP status and [1] the
        parsed body. Pass `path` WITHOUT its /v12.x prefix - adding it is this module's job.
        Re-sending is safe for every signal handled here: 119801, a missing route and 401 are
        all refusals made before the server did anything.
        """
        if _PREFIXED_PATH_RE.match(path):
            raise ValueError("pass the path without its /v12.x prefix: %r" % (path,))
        self._load()
        route = route_of(path)
        if self.learn:
            self._check_dead()
        with self._lock:
            prefix, version, generation = self._resolve(route, pinned_prefix)
        result = send(prefix, version)
        hops = 0
        while True:
            kind = classify(result[0], result[1])
            if kind == "ok":
                self._mark_ok(route, version)
                return result
            if not self.learn or hops >= 3:     # 3 = pin dropped -> version swept -> prefix swept
                return result
            if kind == "unauthorized":
                return self._after_401(route, prefix, version, send, result)
            if kind == "version_unknown":
                self._after_unknown_version(route, version, generation)
            elif kind == "route_missing" and pinned_prefix is None:
                if not self._after_route_missing(prefix, version, generation):
                    return result
            else:
                return result
            hops += 1
            with self._lock:
                prefix, version, generation = self._resolve(route, pinned_prefix)
            result = send(prefix, version)

    # --- learning -----------------------------------------------------------------------
    #
    # Every sweep runs while holding self._lock. That is the single-flight: 128 threads that
    # all get 119801 at once queue on the lock, and each one that gets in after the first
    # sees self._generation moved on and simply re-sends with the new values.

    def _after_401(self, route, prefix, version, send, result):
        """The 401 rule (spec 4.3). A 401 is byte-identical whether the version was refused or
        the token is dead, so it only counts as a version problem on a route that has never
        answered 200 with this version in this process. Login mode proves /login and /home on
        its first good account; after that every dead token costs nothing extra."""
        messages = []
        retry_with = None
        try:
            with self._lock:
                if (route, version) in self._proven or (route, version) in self._not_version:
                    return result
                current = self.route_pins.get(route, self.app_version)
                if current != version:
                    retry_with = current        # another thread already found this route's version
                else:
                    candidates = sorted((v for v in self.known_good if v != version),
                                        key=_vkey, reverse=True)
                    forgotten = False
                    for cand in candidates:
                        attempt = send(prefix, cand)
                        kind = classify(attempt[0], attempt[1])
                        if kind == "ok":
                            self._proven.add((route, cand))
                            messages.append(self._record("route_pin", route, version, cand,
                                                         "401 on a never-proven route"))
                            self.route_pins[route] = cand
                            self._generation += 1
                            self._save()
                            return attempt
                        if kind == "version_unknown":
                            self._forget(cand)
                            forgotten = True
                    self._not_version.add((route, version))
                    if forgotten:          # dead versions dropped from known_good, no winner:
                        self._save()       # persist the drop or the file keeps offering them
                    return result
        finally:
            self._emit(messages)
        attempt = send(prefix, retry_with)
        if classify(attempt[0], attempt[1]) == "ok":
            self._mark_ok(route, retry_with)
        return attempt

    def _after_unknown_version(self, route, version, generation) -> None:
        messages = []
        try:
            with self._lock:
                # The generation counter only proves SOME change happened, not that it was the
                # value this call depends on - another thread's unrelated switch bumps it too.
                # Skip the sweep only when this route would now resolve to a different version.
                if self._generation != generation:
                    if self.route_pins.get(route, self.app_version) != version:
                        return                       # our version problem is already fixed
                self._check_dead()
                self._forget(version)
                if self.route_pins.get(route) == version:
                    del self.route_pins[route]
                    messages.append(self._record("route_pin", route, version, self.app_version,
                                                 "server no longer knows %s: 119801" % version))
                    self._generation += 1
                    self._save()
                    if self.app_version != version:
                        return                       # the main version may still do
                candidates = sorted({v for v in list(self.known_good) + version_candidates(version)
                                     if v != version}, key=_vkey, reverse=True)
                for cand in candidates:              # newest first: the first "known" is the newest
                    answer = self._ask_oracle(self.api_prefix, cand)
                    if answer == "known":
                        messages.append(self._record("app_version", None, version, cand,
                                                     "server no longer knows %s: 119801" % version))
                        self.app_version = cand
                        if cand not in self.known_good:
                            self.known_good.append(cand)
                        self._generation += 1
                        self._save()
                        return
                    if answer == "unknown":
                        self._forget(cand)
                self._save()
                self._give_up("no App-Version the server knows (tried %d builds around %s)"
                              % (len(candidates), version))
        finally:
            self._emit(messages)

    def _after_route_missing(self, prefix, version, generation) -> bool:
        """True = the prefix moved, re-send. False = keep the 404 (spec 4.6: move only when the
        current prefix itself is dead, never because one endpoint went away)."""
        messages = []
        try:
            with self._lock:
                # Same reasoning as _after_unknown_version: the counter alone does not say the
                # prefix we depend on moved. Skip only when it demonstrably did; otherwise fall
                # through and check the current prefix ourselves, still single-flighted by the lock.
                if self._generation != generation and self.api_prefix != prefix:
                    return True
                self._check_dead()
                if self._ask_oracle(prefix, version) == "known":
                    return False
                candidates = sorted(set(prefix_candidates(prefix)) - {prefix}, key=_pkey, reverse=True)
                for cand in candidates:
                    if self._ask_oracle(cand, version) == "known":
                        messages.append(self._record("api_prefix", None, prefix, cand,
                                                     "%s no longer answers" % prefix))
                        self.api_prefix = cand
                        self._generation += 1
                        self._save()
                        return True
                self._give_up("no URL prefix answers (tried %d around %s)" % (len(candidates), prefix))
        finally:
            self._emit(messages)

    def _ask_oracle(self, prefix, version) -> str:
        """GET {prefix}/home with a fake token. The server checks the version first, so:
        401 = version known and prefix alive, 119801 = version unknown, 404 = prefix missing.
        Network errors propagate; 429/5xx raise - neither may ever count as "unknown", or a
        blip mid-sweep would stop the whole engine."""
        oracle = self._oracle_fn or _registered_oracle()
        if oracle is None:
            raise RuntimeError("client_version: no oracle transport registered")
        answer = oracle(prefix, version)
        status, parsed = answer[0], answer[1]
        kind = classify(status, parsed)
        if kind == "unauthorized":
            return "known"
        if kind == "version_unknown":
            return "unknown"
        if kind == "route_missing":
            return "missing"
        if status == 429 or ratelimit.is_app_429(status, parsed) is not None or (
                isinstance(status, int) and status >= 500):
            raise RuntimeError("version probe inconclusive: HTTP %s" % status)
        return "other"

    def _forget(self, version) -> None:
        if version in self.known_good:
            self.known_good.remove(version)

    def _check_dead(self) -> None:
        if self._dead_until and self._clock() < self._dead_until:
            raise VersionUnavailable(self._dead_reason)

    def _give_up(self, reason) -> None:
        self._dead_until = self._clock() + DEAD_COOLDOWN
        self._dead_reason = reason
        raise VersionUnavailable(reason)

    def _record(self, what, route, old, new, why) -> str:
        self.history.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "what": what,
                             "route": route, "from": old, "to": new, "why": why})
        del self.history[:-HISTORY_KEEP]
        label = {"app_version": "App-Version", "api_prefix": "API prefix",
                 "route_pin": "App-Version %s" % route}[what]
        return "%s: %s -> %s (%s)" % (label, old, new, why)

    def _emit(self, messages) -> None:
        for message in messages:
            for callback in list(self._listeners):
                try:
                    callback(message)
                except Exception:
                    pass          # a broken listener must not undo a switch that already happened

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
