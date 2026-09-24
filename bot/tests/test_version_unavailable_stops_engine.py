"""VersionUnavailable stops the engine instead of failing account after account (spec 5).

If it were caught like any other error, Login would move every input file to "login failed/"
and GenID would burn the 2-per-minute guest-mint quota on every attempt.
"""
import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import client_version                          # noqa: E402
from engine import flows                       # noqa: E402
from engine.pool import EnginePool             # noqa: E402
from engine.session import AccountSession      # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "engine_main_under_test_version", os.path.join(HERE, "engine_main.py"))
engine_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_main)


class Lane:
    name, parts, alive, threads = "L", None, True, 1
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


class Recorder:
    def __init__(self):
        self.notes, self.accounts = [], []
    def account(self, **kw): self.accounts.append(kw)
    def stat(self, **kw): pass
    def lane(self, **kw): pass
    def note(self, msg): self.notes.append(msg)


class RecordingQueue:
    def __init__(self):
        self.failed, self.finished = [], []
    def claim(self): return None
    def fail(self, *a, **k): self.failed.append(a)
    def finish(self, *a, **k): self.finished.append(a)
    def remaining(self): return 0


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: None)


@pytest.mark.parametrize("mode", sorted(flows.MODES))
def test_every_flow_lets_it_through_on_the_first_attempt(monkeypatch, tmp_path, mode):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise client_version.VersionUnavailable("no App-Version the server knows")

    monkeypatch.setattr(flows, "_relogin", unavailable)
    monkeypatch.setattr(flows, "_create_account", unavailable)
    (tmp_path / "execute").mkdir()
    src = tmp_path / "execute" / "a.xml"
    src.write_text("<map/>", encoding="utf-8")
    session = AccountSession(src="" if mode in flows.SELF_SUPPLIED_MODES else str(src), lane=Lane())
    with pytest.raises(client_version.VersionUnavailable):
        flows.run(mode, session, {"_execute_dir": str(tmp_path / "execute")})
    assert calls == [1], "retrying it would only repeat the same answer MAX_ATTEMPTS times"


def _raise_unavailable(mode, session, cfg):
    raise client_version.VersionUnavailable("no URL prefix answers")


def test_the_pool_stops_and_leaves_the_file_in_execute(tmp_path):
    (tmp_path / "execute").mkdir()
    first = tmp_path / "execute" / "a.xml"
    second = tmp_path / "execute" / "b.xml"
    first.write_text("<map/>", encoding="utf-8")
    second.write_text("<map/>", encoding="utf-8")
    rec, queue = Recorder(), RecordingQueue()
    pool = EnginePool("ranger_api_Login", {}, queue, [], rec, flow=_raise_unavailable)

    pool._run_one(Lane(), str(first))
    pool._run_one(Lane(), str(second))           # a second thread reaching it too

    assert pool._stop.is_set()
    assert first.exists() and second.exists()
    assert queue.failed == [] and queue.finished == []
    assert (pool._done, pool._fail, pool._stuck) == (0, 0, 2)
    assert rec.accounts == []
    assert len(rec.notes) == 1 and "no URL prefix answers" in rec.notes[0]


def test_setup_client_version_uses_src_api_version_json_and_announces_it(tmp_path, monkeypatch):
    monkeypatch.setattr(client_version, "_DEFAULT", None)
    rec = Recorder()
    engine_main.setup_client_version(str(tmp_path), rec)
    inst = client_version.instance()
    assert inst.path == os.path.join(str(tmp_path), "src", "api_version.json")
    assert os.path.exists(inst.path)
    assert rec.notes == ["api version: /v12.3 + 12.3.0 (pins: /signup/platform=12.2.0)"]
    inst._emit(["App-Version: 12.3.0 -> 12.4.0 (server no longer knows 12.3.0: 119801)"])
    assert rec.notes[-1] == "App-Version: 12.3.0 -> 12.4.0 (server no longer knows 12.3.0: 119801)"
