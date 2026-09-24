"""client_version: storage, headers, routes and the plain path (no learning yet).

Design: docs/superpowers/specs/2026-09-24-client-version-autoswitch-design.md
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pytest

import client_version as cv


class Send:
    """A send() that records what it was asked to send and replays scripted answers."""

    def __init__(self, *answers):
        self.answers = list(answers) or [(200, {"result": {}})]
        self.sent = []

    def __call__(self, prefix, app_version):
        self.sent.append((prefix, app_version))
        return self.answers[min(len(self.sent), len(self.answers)) - 1]


def _cv(tmp_path, **state):
    path = tmp_path / "api_version.json"
    if state:
        path.write_text(json.dumps(state), encoding="utf-8")
    return cv.ClientVersion(str(path)), path


def test_version_unavailable_is_an_ordinary_exception_not_a_systemexit():
    # SystemExit slips past `except Exception` and threading drops it silently (abd580e).
    assert issubclass(cv.VersionUnavailable, Exception)
    assert not issubclass(cv.VersionUnavailable, SystemExit)


def test_headers_put_the_version_in_both_app_version_and_user_agent():
    h = cv.headers("12.2.0")
    assert h == {
        "App-Version": "LGRGS/12.2.0;android/12",
        "User-Agent": "LGRGS/12.2.0 (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)",
    }


@pytest.mark.parametrize("path,route", [
    ("/home", "/home"),
    ("/signup/platform", "/signup/platform"),
    ("/stage/enter/st01", "/stage/enter/*"),
    ("/stage/save/1234/st02?reqId=99", "/stage/save/*/*"),
    ("/mission/sevendays/receive/reward/123/attendance/1",
     "/mission/sevendays/receive/reward/*/attendance/*"),
])
def test_route_of_folds_every_numbered_segment_and_drops_the_query(path, route):
    assert cv.route_of(path) == route


@pytest.mark.parametrize("status,body,kind", [
    (200, {"result": {}}, "ok"),
    (400, {"errorCode": 119801, "extras": {"version": "11.9.0"}}, "version_unknown"),
    (400, {"errorCode": 429}, "other"),          # the per-account min-gap, not a version answer
    (404, {"errorCode": 400, "errorMessage": "/v12.4/home"}, "route_missing"),
    (404, "<html>not found</html>", "other"),
    (401, {"errorCode": 401}, "unauthorized"),
    (500, {"errorCode": 500}, "other"),
])
def test_classify(status, body, kind):
    assert cv.classify(status, body) == kind


def test_a_missing_file_gives_the_defaults_and_is_written_so_a_human_can_see_it(tmp_path):
    c, path = _cv(tmp_path)
    assert c.current() == ("/v12.3", "12.3.0")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["app_version"] == "12.3.0"
    assert saved["api_prefix"] == "/v12.3"
    assert saved["route_pins"] == {"/signup/platform": "12.2.0"}
    assert saved["known_good"] == ["12.2.0", "12.3.0", "12.3.2", "12.4.0"]


def test_a_corrupt_file_gives_the_defaults_without_raising(tmp_path):
    path = tmp_path / "api_version.json"
    path.write_text("{not json", encoding="utf-8")
    c = cv.ClientVersion(str(path))
    assert c.current() == ("/v12.3", "12.3.0")


def test_bad_fields_fall_back_one_by_one_and_good_ones_are_kept(tmp_path):
    c, _ = _cv(tmp_path, app_version="twelve", api_prefix="/v12.2",
               route_pins={"/signup/platform": "12.2.0", "/x": "junk"})
    assert c.current() == ("/v12.2", "12.3.0")
    assert c.route_pins == {"/signup/platform": "12.2.0"}


def test_an_empty_pin_table_in_the_file_means_no_pins(tmp_path):
    c, _ = _cv(tmp_path, route_pins={})
    send = Send()
    c.request("/signup/platform", send)
    assert send.sent == [("/v12.3", "12.3.0")]


def test_the_file_decides_what_gets_sent(tmp_path):
    c, _ = _cv(tmp_path, app_version="12.3.2", api_prefix="/v12.2")
    send = Send()
    c.request("/home", send)
    assert send.sent == [("/v12.2", "12.3.2")]


def test_a_route_pin_overrides_the_main_version_for_that_route_only(tmp_path):
    c, _ = _cv(tmp_path)
    signup, home = Send(), Send()
    c.request("/signup/platform", signup)
    c.request("/home", home)
    assert signup.sent == [("/v12.3", "12.2.0")]
    assert home.sent == [("/v12.3", "12.3.0")]


def test_a_normal_answer_costs_exactly_one_request_and_comes_back_whole(tmp_path):
    c, _ = _cv(tmp_path)
    send = Send((200, {"result": {"x": 1}}, ["LF_AC=abc"]))
    assert c.request("/home", send) == (200, {"result": {"x": 1}}, ["LF_AC=abc"])
    assert len(send.sent) == 1


def test_a_pinned_prefix_is_sent_as_given(tmp_path):
    c, _ = _cv(tmp_path)
    send = Send()
    c.request("/home", send, pinned_prefix="/v12.2")
    assert send.sent == [("/v12.2", "12.3.0")]


def test_a_path_that_still_carries_its_prefix_is_refused(tmp_path):
    c, _ = _cv(tmp_path)
    with pytest.raises(ValueError):
        c.request("/v12.3/home", Send())


def test_a_new_version_that_answers_200_joins_known_good_and_is_saved(tmp_path):
    c, path = _cv(tmp_path, app_version="12.3.5")
    c.request("/home", Send())
    assert "12.3.5" in c.known_good
    assert "12.3.5" in json.loads(path.read_text(encoding="utf-8"))["known_good"]


def test_describe_is_the_engine_start_line(tmp_path):
    c, _ = _cv(tmp_path)
    assert c.describe() == "api version: /v12.3 + 12.3.0 (pins: /signup/platform=12.2.0)"


def test_a_file_that_cannot_be_written_does_not_raise(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    c = cv.ClientVersion(str(blocker / "api_version.json"))
    assert c.current() == ("/v12.3", "12.3.0")          # tried to create the file, could not


def test_configure_points_the_module_functions_at_that_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "_DEFAULT", None)
    target = tmp_path / "src" / "api_version.json"
    cv.configure(str(target))
    assert cv.instance().path == str(target)
    send = Send()
    cv.request("/home", send)
    assert send.sent == [("/v12.3", "12.3.0")]
    assert target.exists()


def test_default_path_honours_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("LGRGS_VERSION_FILE", str(tmp_path / "v.json"))
    assert cv.default_path() == str(tmp_path / "v.json")
