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
