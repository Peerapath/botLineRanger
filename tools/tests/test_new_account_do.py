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
import rangers_api as ra


@pytest.fixture(autouse=True)
def _no_stale_lane_binding(monkeypatch):
    """lane เป็น thread-local ที่ผูกกับเธรดของ pytest เอง (เทสต์ C5/C6 ด้านล่างเรียก
    ra.use_lane() บนเธรดนี้) - ถ้าไม่ล้างก่อน/หลังทุกเทสต์ การรันไฟล์เทสต์อื่นในเธรดเดียวกัน
    ก่อนหรือหลังไฟล์นี้จะเห็น lane ที่ทดสอบทิ้งไว้ (เหมือน fixture เดียวกันใน
    tools/tests/test_rangers_api.py, สโคปเฉพาะไฟล์นั้น - อันนี้สโคปไฟล์นี้) - also gives every
    test a fresh per-lane opener cache, so one test's cached opener can't hide whether the
    next one actually built its own."""
    ra.use_lane(None)
    monkeypatch.setattr(na, "_LANE_OPENERS", {})
    yield
    ra.use_lane(None)

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


def test_do_builds_a_fresh_request_for_every_attempt(monkeypatch, wired):
    """urllib's ProxyHandler mutates the Request in place; a retry must not reuse it."""
    seen = []

    def fake_open(req):
        seen.append(req)
        if len(seen) == 1:
            req.set_proxy("10.0.0.1:8080", "https")          # what ProxyHandler.proxy_open does
            req.add_unredirected_header("Proxy-Authorization", "Basic x")
            raise urllib.error.HTTPError(req.full_url, 400, "err", _headers(), io.BytesIO(APP429))
        assert req is not seen[0]
        assert req.host == "rangers-api.line-apps.com"
        assert req.full_url == "https://rangers-api.line-apps.com/v12.3/login"
        assert req.get_header("Cookie") == "c=1"
        assert not req.has_header("Proxy-authorization") and not req.has_header("Proxy-Authorization")
        assert req.get_header("Proxy-authorization") is None
        return FakeResp(200, OK, _headers())
    monkeypatch.setattr(na, "_open", fake_open)
    st, _, _ = na._do(_req("c=1"))
    assert st == 200 and len(seen) == 2


def test_do_fresh_request_keeps_data_and_content_type(monkeypatch, wired):
    seen = []

    def fake_open(req):
        seen.append(req)
        if len(seen) == 1:
            req.set_proxy("10.0.0.1:8080", "https")
            req.add_unredirected_header("Proxy-Authorization", "Basic x")
            raise urllib.error.HTTPError(req.full_url, 400, "err", _headers(), io.BytesIO(APP429))
        return FakeResp(200, OK, _headers())
    monkeypatch.setattr(na, "_open", fake_open)
    req = urllib.request.Request("https://game-api.line.me/auth/v3.5/check/GUEST", data=b"payload",
                                 headers={"Content-Type": "application/x-msgpack",
                                          "X-Linegame-Authorization": 'ts="1", si="abc"'}, method="POST")
    st, _, _ = na._do(req)
    assert st == 200 and len(seen) == 2 and seen[1] is not seen[0]
    assert seen[1].data == b"payload" and seen[1].get_method() == "POST"
    assert seen[1].get_header("Content-type") == "application/x-msgpack"
    assert seen[1].get_header("X-linegame-authorization") == 'ts="1", si="abc"'
    assert seen[1].host == "game-api.line.me" and not seen[1].has_header("Proxy-authorization")


def test_do_network_errors_have_their_own_budget(monkeypatch, wired):
    monkeypatch.setattr(na, "_NET_ATTEMPTS", 3)
    calls = {"n": 0}

    def fake_open(req):
        calls["n"] += 1
        raise urllib.error.URLError("down")
    monkeypatch.setattr(na, "_open", fake_open)
    with pytest.raises(urllib.error.URLError):
        na._do(_req("c=1"))
    assert calls["n"] == 3 and wired.acquired == 3
    assert wired.sleeps == [(0, None), (1, None)] and wired.dones == []


def test_do_net_budget_never_exceeds_max_attempts(monkeypatch, wired):
    monkeypatch.setattr(na, "_NET_ATTEMPTS", 10)
    monkeypatch.setattr(na, "_MAX_ATTEMPTS", 2)

    def fake_open(req):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(na, "_open", fake_open)
    with pytest.raises(TimeoutError):
        na._do(_req("c=1"))
    assert wired.acquired == 2 and wired.sleeps == [(0, None)]


class FakeQuota:
    def __init__(self):
        self.acquired = 0

    def acquire(self):
        self.acquired += 1


def test_do_queues_authentication_through_auth_quota(monkeypatch, wired):
    q = FakeQuota()
    monkeypatch.setattr(ratelimit, "auth_quota", lambda: q)
    _script(monkeypatch, [(429, b"<html>429</html>", _headers()), (200, OK, _headers())])
    req = urllib.request.Request("https://game-api.line.me" + na.AUTH_PATH, data=b"x", method="POST")
    st, _, _ = na._do(req)
    assert st == 200 and q.acquired == 2                 # once per attempt
    assert wired.sleeps == [(0, str(na._AUTH_429_WAIT))]  # auth 429 waits a chunk of the window


def test_do_other_paths_do_not_touch_auth_quota(monkeypatch, wired):
    q = FakeQuota()
    monkeypatch.setattr(ratelimit, "auth_quota", lambda: q)
    _script(monkeypatch, [(429, b"<html>", _headers()), (200, OK, _headers())])
    st, _, _ = na._do(_req("c=1"))
    assert st == 200 and q.acquired == 0 and wired.sleeps == [(0, None)]


def test_register_guest_is_a_single_authentication_call(monkeypatch):
    calls = []

    def fake_game_call(path, device_id, body, **kw):
        calls.append(path)
        return 200, {"userToken": "UT", "refreshUserToken": "RT", "userKey": "T0FF"}, []
    monkeypatch.setattr(na, "game_call", fake_game_call)
    res = na.register_guest("d" * 32)
    assert res["userToken"] == "UT" and calls == [na.AUTH_PATH]


def test_register_guest_raises_systemexit_with_status(monkeypatch):
    monkeypatch.setattr(na, "game_call", lambda *a, **k: (429, "<html>429</html>", []))
    with pytest.raises(SystemExit) as info:
        na.register_guest("d" * 32)
    assert "HTTP 429" in str(info.value)


# --- C5/C6 (final review): login/signup never went through a proxy lane -----------------------
#
# _OPENER used to be built ONCE at import from LGRGS_PROXY, and _do() always spent from
# ratelimit.bucket_for(host)/ratelimit.auth_quota() (the file-lock bucket/quota) - never
# rangers_api.current_lane(). So every account's first request left through whichever proxy
# happened to be in the env var at process start (proxy[0], or the user's own IP when
# apiproxies was empty), and the guest-mint quota was shared by the whole engine instead of
# per lane (see test_each_lane_has_its_own_independent_guest_mint_quota in
# bot/tests/test_proxy.py for that half). Fix: use the calling thread's bound lane
# (rangers_api.use_lane/current_lane - the exact mechanism tools/rangers_api.py already
# uses), falling back to the module-level value when no lane is bound so the CLI tools
# still work unchanged.

class FakeLane:
    def __init__(self, parts):
        self.parts = parts
        self.acquired = 0
        self.auth_quota = FakeQuota()

    def acquire(self):
        self.acquired += 1


def test_open_uses_the_bound_lanes_proxy_not_the_frozen_module_opener(monkeypatch):
    """C5: every request must leave through the LANE this thread is bound to, not
    proxy[0]/LGRGS_PROXY frozen at import. Proven two ways at once: the module-level opener
    (what a bare CLI run would have built) must never be touched, and the opener that IS
    used must be built from the lane's own proxy, not the module's. No real socket is
    opened anywhere here - _build_opener itself is replaced with a fake that hands back a
    fake opener, the same shape test_open_uses_proxy_opener_when_configured already uses.
    """
    class ExplodingOpener:
        def open(self, req, timeout=None):
            raise AssertionError("must not use the module-level opener when a lane is bound")
    monkeypatch.setattr(na, "_OPENER", ExplodingOpener())

    built = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            built["opened"] = True
            return "opened-via-lane"

    def fake_build_opener(url):
        built["url"] = url
        return FakeOpener()
    monkeypatch.setattr(na, "_build_opener", fake_build_opener)

    lane = FakeLane(("10.0.0.9", 8080, None))
    ra.use_lane(lane)
    assert na._open(_req()) == "opened-via-lane"
    assert built == {"url": "http://10.0.0.9:8080", "opened": True}


def test_open_falls_back_to_the_module_opener_when_no_lane_is_bound(monkeypatch):
    """CLI tools (no engine, no lane) must keep behaving exactly as before - unchanged
    regression check alongside the existing test_open_uses_proxy_opener_when_configured."""
    assert ra.current_lane() is None
    seen = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            seen["req"] = req
            return "opened"
    monkeypatch.setattr(na, "_OPENER", FakeOpener())
    assert na._open(_req()) == "opened"


def test_do_uses_the_bound_lanes_bucket_not_the_file_backed_one(monkeypatch, wired):
    """C5's other half: _do spent from ratelimit.bucket_for(host) - the file-lock bucket
    the rewrite exists to retire - unconditionally, taking msvcrt.locking per request from
    every thread regardless of which lane it was on.
    """
    lane = FakeLane(None)
    ra.use_lane(lane)
    _script(monkeypatch, [(200, OK, _headers())])
    na._do(_req("c=1"))
    assert lane.acquired == 1
    assert wired.hosts == []       # the file-backed bucket must never have been touched


def test_do_queues_authentication_through_the_lanes_own_quota(monkeypatch, wired):
    """C6: the guest-mint quota must come from the bound lane, not the process-wide
    ratelimit.auth_quota() every lane used to share (see bot/tests/test_proxy.py)."""
    module_quota = FakeQuota()
    monkeypatch.setattr(ratelimit, "auth_quota", lambda: module_quota)
    lane = FakeLane(None)
    ra.use_lane(lane)
    _script(monkeypatch, [(200, OK, _headers())])
    req = urllib.request.Request("https://game-api.line.me" + na.AUTH_PATH, data=b"x", method="POST")
    na._do(req)
    assert lane.auth_quota.acquired == 1
    assert module_quota.acquired == 0
