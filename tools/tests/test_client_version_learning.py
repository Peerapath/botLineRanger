"""client_version learning: the 401 rule, version and prefix sweeps, single-flight.

FakeServer answers exactly like rangers-api did on 2026-09-24 (spec section 2): it checks the
version before anything else, then the prefix, then the token. Each test's fake LACKS the thing
being proven - e.g. the 401-rule test uses a server where signup refuses 12.3.0 but /home
takes it, so a module that treated every 401 alike could not pass both halves.
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pytest

import client_version as cv


class FakeServer:
    def __init__(self, known=("12.2.0", "12.3.0", "12.3.2", "12.4.0"), signup_ok=("12.2.0",),
                 prefixes=("/v12.2", "/v12.3"), token_ok=True, missing_routes=(), oracle_delay=0.0):
        self.known = set(known)
        self.signup_ok = set(signup_ok)
        self.prefixes = set(prefixes)
        self.token_ok = token_ok
        self.missing_routes = set(missing_routes)
        self.oracle_delay = oracle_delay
        self.real = []
        self.oracle_calls = []
        self._lock = threading.Lock()

    def _answer(self, prefix, version, path, fake_token):
        if version not in self.known:
            return 400, {"errorCode": 119801, "extras": {"version": version}}
        if prefix not in self.prefixes or path in self.missing_routes:
            return 404, {"errorCode": 400, "errorMessage": prefix + path}
        if fake_token:
            return 401, {"errorCode": 401}
        if path == "/signup/platform":
            return (200, {"result": {"isNew": True}}) if version in self.signup_ok else (401, {"errorCode": 401})
        if not self.token_ok:
            return 401, {"errorCode": 401}
        return 200, {"result": {}}

    def send_for(self, path):
        def send(prefix, version):
            with self._lock:
                self.real.append((prefix, version))
            return self._answer(prefix, version, path, fake_token=False)
        return send

    def oracle(self, prefix, version):
        with self._lock:
            self.oracle_calls.append((prefix, version))
        if self.oracle_delay:
            time.sleep(self.oracle_delay)
        return self._answer(prefix, version, cv.ORACLE_PATH, fake_token=True)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, server, learn=True, clock=None, **state):
    path = tmp_path / "api_version.json"
    if state:
        path.write_text(json.dumps(state), encoding="utf-8")
    c = cv.ClientVersion(str(path), oracle=server.oracle, learn=learn,
                         clock=clock or time.monotonic)
    messages = []
    c.on_switch(messages.append)
    return c, path, messages


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_normal_answer_costs_one_request_and_no_oracle(tmp_path):
    server = FakeServer()
    c, _, _ = make(tmp_path, server)
    assert c.request("/home", server.send_for("/home"))[0] == 200
    assert server.real == [("/v12.3", "12.3.0")]
    assert server.oracle_calls == []


def test_119801_moves_the_main_version_to_the_newest_build_the_server_knows(tmp_path):
    server = FakeServer()
    c, path, messages = make(tmp_path, server, app_version="12.1.0")
    broken = []
    c.on_switch(lambda msg: broken.append(1 / 0))     # a listener that raises must not matter

    assert c.request("/home", server.send_for("/home"))[0] == 200
    assert server.real == [("/v12.3", "12.1.0"), ("/v12.3", "12.4.0")]
    assert server.oracle_calls == [("/v12.3", "13.0.0"), ("/v12.3", "12.4.0")]
    assert c.app_version == "12.4.0"
    assert saved(path)["app_version"] == "12.4.0"
    assert messages == ["App-Version: 12.1.0 -> 12.4.0 (server no longer knows 12.1.0: 119801)"]
    assert saved(path)["history"][-1]["what"] == "app_version"


def test_signup_refusing_the_main_version_gets_a_pin_of_its_own_and_it_is_saved(tmp_path):
    server = FakeServer()
    c, path, messages = make(tmp_path, server, route_pins={})
    send = server.send_for("/signup/platform")

    assert c.request("/signup/platform", send)[0] == 200
    assert server.real == [("/v12.3", "12.3.0"), ("/v12.3", "12.4.0"),
                           ("/v12.3", "12.3.2"), ("/v12.3", "12.2.0")]
    assert c.route_pins == {"/signup/platform": "12.2.0"}
    assert saved(path)["route_pins"] == {"/signup/platform": "12.2.0"}
    assert messages == ["App-Version /signup/platform: 12.3.0 -> 12.2.0 (401 on a never-proven route)"]
    assert server.oracle_calls == []

    server.real.clear()
    c.request("/signup/platform", send)
    assert server.real == [("/v12.3", "12.2.0")]


def test_a_401_on_a_route_already_proven_is_a_dead_token_and_costs_nothing_more(tmp_path):
    server = FakeServer()
    c, _, messages = make(tmp_path, server)
    c.request("/home", server.send_for("/home"))
    server.token_ok = False
    assert c.request("/home", server.send_for("/home"))[0] == 401
    assert server.real == [("/v12.3", "12.3.0"), ("/v12.3", "12.3.0")]
    assert server.oracle_calls == [] and messages == []


def test_a_dead_token_on_a_never_proven_route_is_swept_once_then_left_alone(tmp_path):
    server = FakeServer(token_ok=False)
    c, _, messages = make(tmp_path, server)
    send = server.send_for("/mission/list")
    assert c.request("/mission/list", send)[0] == 401
    assert server.real == [("/v12.3", "12.3.0"), ("/v12.3", "12.4.0"),
                           ("/v12.3", "12.3.2"), ("/v12.3", "12.2.0")]
    assert c.route_pins == {"/signup/platform": "12.2.0"} and messages == []

    server.real.clear()
    assert c.request("/mission/list", send)[0] == 401
    assert server.real == [("/v12.3", "12.3.0")]


def test_a_missing_endpoint_under_a_live_prefix_is_not_a_reason_to_move(tmp_path):
    server = FakeServer(missing_routes={"/event/old"})
    c, _, messages = make(tmp_path, server)
    assert c.request("/event/old", server.send_for("/event/old"))[0] == 404
    assert server.oracle_calls == [("/v12.3", "12.3.0")]
    assert c.api_prefix == "/v12.3" and messages == []


def test_a_dead_prefix_moves_to_the_newest_one_that_answers(tmp_path):
    server = FakeServer(prefixes={"/v12.2", "/v12.5"})
    c, path, messages = make(tmp_path, server)
    assert c.request("/home", server.send_for("/home"))[0] == 200
    assert server.oracle_calls == [("/v12.3", "12.3.0"), ("/v13.0", "12.3.0"),
                                   ("/v12.6", "12.3.0"), ("/v12.5", "12.3.0")]
    assert server.real[-1] == ("/v12.5", "12.3.0")
    assert c.api_prefix == "/v12.5" and saved(path)["api_prefix"] == "/v12.5"
    assert messages == ["API prefix: /v12.3 -> /v12.5 (/v12.3 no longer answers)"]


def test_a_pinned_prefix_never_moves(tmp_path):
    server = FakeServer(prefixes={"/v12.5"})
    c, _, _ = make(tmp_path, server)
    assert c.request("/home", server.send_for("/home"), pinned_prefix="/v12.3")[0] == 404
    assert server.oracle_calls == [] and c.api_prefix == "/v12.3"


def test_nothing_known_raises_then_fails_fast_until_the_cooldown_passes(tmp_path):
    server = FakeServer(known=())
    clock = Clock()
    c, _, _ = make(tmp_path, server, clock=clock)
    with pytest.raises(cv.VersionUnavailable):
        c.request("/home", server.send_for("/home"))
    real, asked = len(server.real), len(server.oracle_calls)

    with pytest.raises(cv.VersionUnavailable):
        c.request("/home", server.send_for("/home"))
    assert (len(server.real), len(server.oracle_calls)) == (real, asked)

    clock.t += cv.DEAD_COOLDOWN + 1
    server.known = {"12.3.0"}
    assert c.request("/home", server.send_for("/home"))[0] == 200


def test_32_threads_hitting_119801_together_share_one_sweep(tmp_path):
    server = FakeServer(oracle_delay=0.02)
    c, _, messages = make(tmp_path, server, app_version="12.1.0")
    start = threading.Barrier(32)
    statuses = []

    def worker():
        start.wait(timeout=5)
        statuses.append(c.request("/home", server.send_for("/home"))[0])

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads)
    assert statuses == [200] * 32
    assert server.oracle_calls == [("/v12.3", "13.0.0"), ("/v12.3", "12.4.0")]
    assert len(messages) == 1


def test_a_pin_the_server_no_longer_knows_gives_way_to_the_main_version(tmp_path):
    server = FakeServer(known={"12.3.0", "12.4.0"}, signup_ok={"12.3.0"})
    c, path, messages = make(tmp_path, server)
    assert c.request("/signup/platform", server.send_for("/signup/platform"))[0] == 200
    assert server.real == [("/v12.3", "12.2.0"), ("/v12.3", "12.3.0")]
    assert c.route_pins == {} and "12.2.0" not in c.known_good
    assert server.oracle_calls == []
    assert messages == ["App-Version /signup/platform: 12.2.0 -> 12.3.0 (server no longer knows 12.2.0: 119801)"]


def test_an_oracle_network_error_is_an_ordinary_failure_not_version_unavailable(tmp_path):
    server = FakeServer()

    def down(prefix, version):
        raise ConnectionError("proxy dropped")

    path = tmp_path / "api_version.json"
    path.write_text(json.dumps({"app_version": "12.1.0"}), encoding="utf-8")
    c = cv.ClientVersion(str(path), oracle=down)
    with pytest.raises(ConnectionError):
        c.request("/home", server.send_for("/home"))
    assert c.app_version == "12.1.0"
    with pytest.raises(ConnectionError):          # not "dead": the next call sweeps again
        c.request("/home", server.send_for("/home"))


def test_an_oracle_5xx_is_inconclusive_not_version_unavailable(tmp_path):
    server = FakeServer()
    path = tmp_path / "api_version.json"
    path.write_text(json.dumps({"app_version": "12.1.0"}), encoding="utf-8")
    c = cv.ClientVersion(str(path), oracle=lambda prefix, version: (503, "busy"))
    with pytest.raises(RuntimeError, match="inconclusive") as info:
        c.request("/home", server.send_for("/home"))
    assert not isinstance(info.value, cv.VersionUnavailable)


def test_learning_off_returns_every_refusal_untouched(tmp_path):
    server = FakeServer()
    c, _, _ = make(tmp_path, server, learn=False, app_version="12.1.0")
    status, body = c.request("/home", server.send_for("/home"))
    assert (status, body["errorCode"]) == (400, 119801)
    assert server.real == [("/v12.3", "12.1.0")] and server.oracle_calls == []


def test_candidates():
    assert cv.version_candidates("12.3.0") == [
        "12.3.0", "12.3.1", "12.3.2", "12.3.3", "12.3.4", "12.3.5",
        "12.2.0", "12.3.0", "12.4.0", "12.5.0", "13.0.0"]
    assert cv.prefix_candidates("/v12.3") == [
        "/v12.2", "/v12.3", "/v12.4", "/v12.5", "/v12.6", "/v13.0"]
