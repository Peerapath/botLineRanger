"""signup and login take their version and prefix from client_version - and the 401 rule
really does find signup's version through the real new_account code."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import pytest

import client_version as cv
import new_account as na
import relogin


def _install(tmp_path, monkeypatch, learn=False, **state):
    path = tmp_path / "api_version.json"
    if state:
        path.write_text(json.dumps(state), encoding="utf-8")
    inst = cv.ClientVersion(str(path), learn=learn,
                            oracle=lambda p, v: pytest.fail("signup/login must not need the oracle"))
    monkeypatch.setattr(cv, "_DEFAULT", inst)
    return inst


def _capture_do(monkeypatch, module, answer):
    seen = []

    def fake_do(req):
        seen.append(req)
        return answer(req)

    monkeypatch.setattr(module, "_do", fake_do)
    return seen


SIGNUP_OK = (200, {"result": {"id": "u", "mid": "m", "rsn": "r", "isNew": True, "level": 1,
                              "ruby": {"total": 20}, "coin": {"total": 0}}}, ["LF_AC=abc; Path=/"])


def test_signup_sends_its_pinned_version_under_the_managed_prefix(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, api_prefix="/v12.2")
    seen = _capture_do(monkeypatch, na, lambda req: SIGNUP_OK)
    session = na.signup_platform("cc1", "udid1")
    assert session["lf_ac"] == "abc"
    assert seen[0].full_url == "https://rangers-api.line-apps.com/v12.2/signup/platform"
    assert seen[0].get_header("App-version") == "LGRGS/12.2.0;android/12"
    assert seen[0].get_header("User-agent").startswith("LGRGS/12.2.0 ")


def test_game_login_sends_the_main_version(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, app_version="12.3.2")
    seen = _capture_do(monkeypatch, na, lambda req: (200, {"result": {"id": "u", "rsn": "r"}},
                                                     ["LF_AC=xyz"]))
    session = na.game_login("cc1", "udid1", guest_cookie="g")
    assert session["lf_ac"] == "xyz"
    assert seen[0].full_url == "https://rangers-api.line-apps.com/v12.3/login"
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"


def test_the_401_rule_finds_signups_version_through_the_real_signup_code(tmp_path, monkeypatch):
    inst = _install(tmp_path, monkeypatch, learn=True, route_pins={})

    def server(req):
        if req.get_header("App-version") == "LGRGS/12.2.0;android/12":
            return SIGNUP_OK
        return 401, {"errorCode": 401}, []

    seen = _capture_do(monkeypatch, na, server)
    session = na.signup_platform("cc1", "udid1")
    assert session["lf_ac"] == "abc"
    assert [r.get_header("App-version") for r in seen] == [
        "LGRGS/12.3.0;android/12", "LGRGS/12.4.0;android/12",
        "LGRGS/12.3.2;android/12", "LGRGS/12.2.0;android/12"]
    assert inst.route_pins == {"/signup/platform": "12.2.0"}


def test_relogin_login_uses_the_managed_route(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, api_prefix="/v12.2", app_version="12.3.2")
    seen = _capture_do(monkeypatch, na, lambda req: (200, {"result": {"rsn": "r"}}, ["LF_AC=new"]))
    status, result, lf_ac = relogin.login("cc", "udid", "guest", "TH")
    assert (status, result, lf_ac) == (200, {"rsn": "r"}, "new")
    assert seen[0].full_url == "https://rangers-api.line-apps.com/v12.2/login"
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"
    assert seen[0].get_header("Nation-code") == "TH"
