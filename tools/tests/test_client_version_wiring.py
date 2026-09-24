"""The business-tier call sites take their version and prefix from client_version.

Each test installs its own non-learning ClientVersion whose file says /v12.2 + 12.3.2 - values
nothing in the codebase hardcodes - so a call site that still built its own header or URL
could not pass.
"""
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import pytest

import client_version as cv
import rangers_api as ra


@pytest.fixture
def odd_version(tmp_path, monkeypatch):
    path = tmp_path / "api_version.json"
    path.write_text(json.dumps({"app_version": "12.3.2", "api_prefix": "/v12.2"}), encoding="utf-8")
    inst = cv.ClientVersion(str(path), learn=False)
    monkeypatch.setattr(cv, "_DEFAULT", inst)
    return inst


@pytest.fixture(autouse=True)
def _lane_isolated():
    ra.use_lane(None)
    yield
    ra.use_lane(None)


class Lane:
    name, parts, alive = "L", None, True
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


class FakeResp:
    status = 200
    def __init__(self, body=b'{"result":{}}'):
        self._body = body
    def read(self): return self._body
    def getheader(self, name, default=None): return None


class FakeConn:
    def __init__(self):
        self.sent = []
    def request(self, method, url, body=None, headers=None):
        self.sent.append((method, url, headers))
    def getresponse(self):
        return FakeResp()


def test_call_sends_the_prefix_and_version_client_version_chose(odd_version, monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    ra.use_lane(Lane())
    status, body = ra.call("LF_AC=wiring-1", "/home")
    assert status == 200
    method, url, headers = conn.sent[0]
    assert (method, url) == ("GET", "/v12.2/home")
    assert headers["App-Version"] == "LGRGS/12.3.2;android/12"
    assert headers["User-Agent"].startswith("LGRGS/12.3.2 ")


def test_call_api_argument_pins_the_prefix(odd_version, monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    ra.use_lane(Lane())
    ra.call("LF_AC=wiring-2", "/home", api="/v12.3")
    assert conn.sent[0][1] == "/v12.3/home"


def test_call_extra_headers_are_sent(odd_version, monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    ra.use_lane(Lane())
    ra.call("LF_AC=wiring-3", "/gacha/info", extra_headers={"UID": "u9"})
    assert conn.sent[0][2]["UID"] == "u9"


def test_the_oracle_is_a_fake_token_get_of_home(monkeypatch):
    seen = []
    monkeypatch.setattr(ra, "_send_raw", lambda *a, **k: (seen.append(a), (401, {"errorCode": 401}))[1])
    assert ra._oracle("/v12.4", "12.4.0") == (401, {"errorCode": 401})
    cookie, url, method, data, version = seen[0][:5]
    assert (cookie, url, method, data, version) == ("LF_AC=0", "/v12.4/home", "GET", None, "12.4.0")


def test_importing_rangers_api_registers_its_oracle():
    code = ("import sys; sys.path.insert(0, %r); import rangers_api, client_version; "
            "assert client_version._ORACLE is rangers_api._oracle" % TOOLS)
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_gacha_call_goes_through_rangers_api_with_its_uid(monkeypatch):
    import gacha
    seen = []
    monkeypatch.setattr(ra, "call", lambda *a, **k: (seen.append((a, k)), (200, {}))[1])
    gacha.call("LF_AC=g", "u1", "/gacha/info")
    gacha.call("LF_AC=g", None, "/gacha/group/reserve", "POST", {"groupId": "x"})
    assert seen[0] == (("LF_AC=g", "/gacha/info", "GET", None), {"extra_headers": {"UID": "u1"}})
    assert seen[1] == (("LF_AC=g", "/gacha/group/reserve", "POST", {"groupId": "x"}),
                       {"extra_headers": None})


class UrlResp(io.BytesIO):
    status = 200
    headers = {}


def test_fetch_roster_uses_client_version(odd_version, monkeypatch):
    import pull_roster
    seen = []
    monkeypatch.setattr(pull_roster.urllib.request, "urlopen",
                        lambda req, timeout=None: (seen.append(req), UrlResp(b'{"result":{}}'))[1])
    assert pull_roster.fetch_roster("LF_AC=r", None) == b'{"result":{}}'
    assert seen[0].full_url == ("https://rangers-api.line-apps.com/v12.2"
                                "/player/units/equip?inven=true&team=true&deck=true")
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"


def test_device_session_player_summary_uses_client_version(odd_version, monkeypatch):
    import device_session
    body = json.dumps({"result": {"player": {"uid": 1, "mid": "m", "userName": "n", "level": 3},
                                  "rubyBalance": {"total": 5}}}).encode()
    seen = []
    monkeypatch.setattr(device_session.urllib.request, "urlopen",
                        lambda req, timeout=None: (seen.append(req), UrlResp(body))[1])
    assert device_session.player_summary("tok")["level"] == 3
    assert seen[0].full_url == ("https://rangers-api.line-apps.com/v12.2"
                                "/player/units/equip?inven=false&team=false&deck=false")
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"
