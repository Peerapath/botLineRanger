"""A helper that raises SystemExit must cost one account, never a worker thread.

Measured live 2026-09-24 while benchmarking GenID thread scaling: `engine_main.py
ranger_api_GenID` with LGRGS_AUTH_QUOTA=0 and threadcount=16 printed 16 "deviceId=" lines
(one per worker), then produced NOTHING - no account, no error, no traceback - and exited
with code 0 after 117 s as if it had finished its work. Twenty-two lines of output in total.

The cause is a language detail, not a logic error. tools/ raises SystemExit for "this call
did not work" in a dozen places the engine reaches - new_account.py:367 (auth, i.e. the
HTTP 429 a burst of mints earns), new_account.py:381 (refresh), gacha.py:118/269,
rewards.py:75, gifts.py:35, sevendays.py:40, export_account.py:40, pull_roster.py:152/283 -
because those files started life as CLI tools, where SystemExit IS the error path. But
SystemExit derives from BaseException, so `except Exception` does not catch it, and
threading.excepthook deliberately ignores it: a thread that raises SystemExit dies silently,
printing nothing at all. EnginePool._run_one's `except Exception` therefore let the thread
die, EnginePool.run() saw no live threads and broke out of its loop, and the engine reported
a clean finish.

tools/relogin.py:183 already wraps exactly this for the Login path
(`Transient("guest mint failed: ...")`). These tests hold the two places that were missed:
the pool boundary, which must survive it for EVERY mode, and GenID's own mint, which must
spend its retry budget on it instead of giving up on attempt 1.
"""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine import flows                       # noqa: E402
from engine.pool import EnginePool             # noqa: E402
from engine.session import AccountSession      # noqa: E402


class Lane:
    name, parts = "L", None
    alive = True
    threads = 1
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


class Recorder:
    """Only the reporter surface EnginePool actually calls."""

    def __init__(self):
        self.accounts = []
        self._lock = threading.Lock()

    def account(self, **kw):
        with self._lock:
            self.accounts.append(kw)

    def stat(self, **kw): pass
    def lane(self, **kw): pass
    def note(self, msg): pass


class EmptyQueue:
    def claim(self): return None
    def fail(self, *a, **kw): pass
    def finish(self, *a, **kw): pass
    def remaining(self): return 0


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: None)


def test_run_one_survives_a_systemexit_and_still_reports_the_account():
    """The pool boundary. Not GenID-specific on purpose: gacha, rewards, gifts, sevendays,
    export_account and pull_roster all raise SystemExit too, so Login/Level3/Stage can reach
    this the same way. A dead worker is unrecoverable - it never re-enters _worker's while
    loop - and takes the pool down one thread at a time with nothing written anywhere."""
    rec = Recorder()
    pool = EnginePool("ranger_api_Login", {}, EmptyQueue(), [], rec)

    def flow(mode, session, cfg):
        raise SystemExit("  auth(terms) FAILED HTTP 429: quota")

    pool.flow = flow
    died = []

    def worker():
        try:
            pool._run_one(Lane(), "")
        except BaseException as err:          # noqa: BLE001 - that is the thing under test
            died.append("%s: %s" % (type(err).__name__, err))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive(), "must not hang"
    assert died == [], "the worker thread died instead of failing one account: %s" % died
    assert len(rec.accounts) == 1, (
        "a silently dead thread reports nothing at all - that is what made a 16-thread run "
        "look like a clean, successful, empty run")
    assert rec.accounts[0]["status"] == "FAIL"
    # the reporter's field is "err", not "error" - see EnginePool._run_one's own call
    assert "429" in str(rec.accounts[0].get("err", "")), (
        "the message SystemExit carried is the only clue why; it must reach the report")


def test_keyboardinterrupt_is_still_allowed_through():
    """The fix must widen the net to SystemExit, not to BaseException. Ctrl-C has to keep
    unwinding the thread; swallowing it would turn the stop key into a no-op."""
    pool = EnginePool("ranger_api_Login", {}, EmptyQueue(), [], Recorder())

    def flow(mode, session, cfg):
        raise KeyboardInterrupt()

    pool.flow = flow
    with pytest.raises(KeyboardInterrupt):
        pool._run_one(Lane(), "")


def test_genid_spends_its_retry_budget_when_the_mint_raises_systemexit(monkeypatch):
    """A 429 on the mint is the textbook transient: the very next minute has fresh quota.
    Before the fix the SystemExit escaped run_genid's `except Exception` on attempt 1, so
    the flow gave up after ONE mint and the other two attempts in its budget went unused."""
    import new_account

    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise SystemExit("  auth(terms) FAILED HTTP 429: quota")

    monkeypatch.setattr(new_account, "make_account", boom)
    session = AccountSession(src="", lane=Lane())

    out = flows.run("ranger_api_GenID", session, {"_execute_dir": "."})

    assert len(calls) == flows.MAX_ATTEMPTS, (
        "expected %d mint attempts, got %d" % (flows.MAX_ATTEMPTS, len(calls)))
    assert out.dest == "login failed"
    assert out.status == "FAIL"
    assert "429" in (out.error or "")


def test_the_mint_failure_keeps_naming_guest_mint_like_the_login_path_does(monkeypatch):
    """tools/relogin.py:183 already answers this with "guest mint failed: ...". Reusing the
    wording means one grep finds both paths in a log."""
    import new_account

    monkeypatch.setattr(new_account, "make_account", lambda *a, **k: (_ for _ in ()).throw(
        SystemExit("  refresh failed: 401")))
    session = AccountSession(src="", lane=Lane())

    out = flows.run("ranger_api_GenID", session, {"_execute_dir": "."})

    assert "guest mint failed" in (out.error or ""), out.error
