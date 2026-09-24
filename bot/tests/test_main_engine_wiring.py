"""bot/main.py's GUI-side half of the engine wiring (Task 10): one engine subprocess
instead of up to 128 bot_worker.py processes, read back over stdout as JSONL.

Bug this class of test guards against - found empirically while verifying this task, not
invented after the fact: the brief's own sketch for _drain_engine_rows rescheduled itself
on `if self.worker_procs:` - true from the instant Start is clicked, and nothing anywhere
pops that key back out - so following it literally would mean the once-a-second drain
timer never stops on its own, OR (if something else popped the dict entry the moment the
process exited) could drop whatever line the reader thread was still one line behind on.
The one line that must never be that dropped line is the final stat(final=True) summary -
see test_pool.py's own docstring for the real run this exact shape of bug once cost 1,427
accounts, just on the engine's own supervisor loop instead of the GUI's reader.

These tests exercise the real bound methods on bot.main.EmulatorManager, not copies. A
plain object.__new__(EmulatorManager) is used to reach them without constructing a real
Tk window (no display, no subscription/ADB/protection side effects) - noted where that
technique itself has a sharp edge (see _make_fake_gui's docstring).
"""
import contextlib
import io
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402


class _FakeLabel:
    """Stands in for the real ctk.CTkLabel widget (self.worker_summary_label).

    Needed because EmulatorManager extends tkinter.Tk, whose own __getattr__ delegates
    any attribute Python can't find normally to the Tcl interpreter (self.tk) - and on an
    object.__new__'d instance that never ran Tk.__init__, self.tk does not exist either,
    so even a bare hasattr(gui, "worker_summary_label") for an attribute that was truly
    never set recurses through that __getattr__ forever (confirmed while writing this
    file: it blew Python's recursion limit before this stub existed). Explicitly setting
    a real attribute - even a fake one - makes ordinary attribute lookup succeed first, so
    __getattr__ is never reached for this name. _updateEngineStats's own hasattr guard is
    therefore only provably safe to test with the label present, not genuinely absent.
    """

    def __init__(self):
        self.texts = []
        self.colors = []

    def winfo_exists(self):
        return True

    def configure(self, text=None, text_color=None, **kw):
        self.texts.append(text)
        self.colors.append(text_color)


def _make_fake_gui():
    gui = object.__new__(main.EmulatorManager)
    gui._engine_lock = threading.Lock()
    gui._engine_rows = []
    gui._engine_last_stat = {}
    gui._engine_lanes = {}
    gui._engine_session_rows = []
    gui.worker_procs = {}
    gui._worker_monitor_job = None
    gui._engine_reader_thread = None
    gui._engine_err = None
    gui.worker_summary_label = _FakeLabel()
    gui._logged = []
    gui.log = lambda msg: gui._logged.append(msg)
    return gui


# --- _app_root / _spawn_engine: command construction, never a real subprocess ---------------

def test_app_root_uses_the_exe_dir_when_frozen_and_file_dir_otherwise(monkeypatch):
    gui = _make_fake_gui()
    assert main.EmulatorManager._app_root(gui) == os.path.dirname(os.path.abspath(main.__file__))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert main.EmulatorManager._app_root(gui) == os.path.dirname(sys.executable)


def _spawn_engine_with_fake_popen(gui, tmp_path, mode):
    """Runs the real _spawn_engine but with subprocess.Popen replaced by a recorder, so
    no process is ever actually started - _app_root is hardcoded to _app_root() for real
    deployments (there is only one), which is exactly why this must never be allowed to
    really launch: it would point cwd at the real bot/ and start claiming bot/input/."""
    gui._app_root = lambda: str(tmp_path)
    gui._worker_env = lambda: dict(os.environ, LGRGS_CC_FILE=str(tmp_path / "cc.txt"))
    calls = []

    class FakeProc:
        def __init__(self, args, **kw):
            calls.append((args, kw))

    real_popen = subprocess.Popen
    subprocess.Popen = FakeProc
    try:
        main.EmulatorManager._spawn_engine(gui, mode=mode)
    finally:
        subprocess.Popen = real_popen
    return calls[0]


def test_spawn_engine_source_mode_runs_engine_main_py_with_python(tmp_path):
    gui = _make_fake_gui()
    args, kw = _spawn_engine_with_fake_popen(gui, tmp_path, "ranger_api_Login")
    assert args == [sys.executable, str(tmp_path / "engine_main.py"), "ranger_api_Login"]
    assert kw["cwd"] == str(tmp_path)
    assert kw["stdout"] == subprocess.PIPE
    assert kw["stderr"] is gui._engine_err
    assert kw["text"] is True
    assert kw["env"]["LGRGS_CC_FILE"] == str(tmp_path / "cc.txt")
    # Created eagerly, before the (fake) process ever writes to it - constraint #9: stderr
    # of background work always has somewhere to land, never DEVNULL.
    assert (tmp_path / "src" / "log" / "engine.err").exists()
    gui._engine_err.close()


def test_spawn_engine_frozen_mode_reinvokes_the_exe_with_a_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    gui = _make_fake_gui()
    args, kw = _spawn_engine_with_fake_popen(gui, tmp_path, "ranger_api_GenID")
    # Frozen: python can't run a loose engine_main.py, so re-exec the same exe instead -
    # main.py's own __main__ block (--engine) is what dispatches this back into engine_main.
    assert args == [sys.executable, "--engine", "ranger_api_GenID"]
    assert kw["cwd"] == str(tmp_path)
    gui._engine_err.close()


def test_spawn_engine_closes_the_previous_stderr_handle_before_reopening(tmp_path):
    """Each Start click used to open a fresh engine.err handle without ever closing the
    last one - a real fd leak over a long GUI session (the new "w" open still truncates
    the same path, so it was invisible in the file's contents, only in open-handle count)."""
    gui = _make_fake_gui()
    first_args, _ = _spawn_engine_with_fake_popen(gui, tmp_path, "ranger_api_Login")
    first_handle = gui._engine_err
    assert not first_handle.closed
    _spawn_engine_with_fake_popen(gui, tmp_path, "ranger_api_Login")
    assert first_handle.closed, "the previous run's stderr handle must be closed, not leaked"
    gui._engine_err.close()


# --- _dispatch_engine_row: routes every JSONL row kind bot/engine/report.py emits -----------
# Field names below are exactly those bot/engine/pool.py's Reporter calls use (see
# EnginePool._run_one, .run) - pinned here so a rename on either side shows up as a failure
# instead of the two sides silently drifting apart.

def test_dispatch_routes_every_row_kind_report_py_actually_emits():
    gui = _make_fake_gui()
    main.EmulatorManager._dispatch_engine_row(gui, {
        "t": "stat", "done": 3, "fail": 1, "stuck": 0, "left": 56, "rate": 0.4,
        "threads": 96, "lanes": 1})
    assert gui._engine_last_stat["done"] == 3
    assert "done 3" in gui.worker_summary_label.texts[-1]

    main.EmulatorManager._dispatch_engine_row(gui, {
        "t": "acct", "status": "OK", "rsn": "deadbeef", "lv": 3, "ms": 9800,
        "dest": "output", "moved": True, "lane": "direct", "err": "", "move_err": ""})
    assert gui._engine_session_rows[-1]["rsn"] == "deadbeef"
    assert "rsn=deadbeef" in gui._logged[-1]

    main.EmulatorManager._dispatch_engine_row(gui, {
        "t": "lane", "name": "1.2.3.4:8080", "state": "dead", "reason": "connect failed 3x in a row"})
    assert gui._engine_lanes["1.2.3.4:8080"]["state"] == "dead"
    assert "connect failed 3x in a row" in gui._logged[-1]

    main.EmulatorManager._dispatch_engine_row(gui, {"t": "note", "msg": "every proxy is down - stopping"})
    assert gui._logged[-1] == "every proxy is down - stopping"


def test_update_engine_stats_tolerates_the_final_rows_missing_keys():
    """The real final stat row (EnginePool.run()'s closing summary) has no "threads" or
    "lanes" key - confirmed against a real engine_main.py run while verifying this task.
    A plain row["threads"] here would KeyError; row.get(key, "-") is what this pins."""
    gui = _make_fake_gui()
    final_row = {"done": 2, "fail": 0, "stuck": 0, "left": 0, "seconds": 9.8,
                 "rate": 0.2, "final": True}   # no "threads"/"lanes" - see docstring
    main.EmulatorManager._updateEngineStats(gui, final_row)
    assert "- thread" in gui.worker_summary_label.texts[-1]
    assert "finished" in gui.worker_summary_label.texts[-1]


def test_append_session_row_caps_history_at_500():
    gui = _make_fake_gui()
    for i in range(520):
        main.EmulatorManager._appendSessionRow(gui, {"status": "OK", "rsn": "r%d" % i, "lv": 1,
                                                      "dest": "output", "ms": 1})
    assert len(gui._engine_session_rows) == 500
    assert gui._engine_session_rows[-1]["rsn"] == "r519"          # newest kept
    assert gui._engine_session_rows[0]["rsn"] == "r20"            # oldest 20 dropped


def test_drain_engine_rows_keeps_going_after_one_row_raises():
    """A single malformed/unexpected row must not silently break _drain_engine_rows for
    the rest of the run: if the reschedule after it never runs, nothing drains
    _engine_rows again even though the engine process keeps writing to it - see that
    method's own docstring. Every real row kind here is guarded with .get(), so this
    forces the failure directly by replacing the dispatcher instead of crafting a row
    that happens to break today's field access (which real rows never will anyway)."""
    gui = _make_fake_gui()
    calls = []

    def exploding_dispatch(row):
        calls.append(row)
        raise RuntimeError("boom")

    gui._dispatch_engine_row = exploding_dispatch
    gui._engine_rows = [{"t": "note", "msg": "1"}, {"t": "note", "msg": "2"}]
    gui._engine_reader_thread = None   # already "dead" -> takes the single final-drain path

    with contextlib.redirect_stdout(io.StringIO()):   # swallow the printed "bad row" lines
        main.EmulatorManager._drain_engine_rows(gui)

    assert len(calls) == 2, "both rows must still be attempted even though the first raised"


# --- _drain_engine_rows: reschedules on the reader thread's own liveness -------------------

def test_drain_engine_rows_reschedules_while_the_reader_thread_is_alive():
    gui = _make_fake_gui()
    scheduled = []
    gui.after = lambda ms, fn: scheduled.append((ms, fn)) or "job-id"
    still_running = threading.Event()
    reader = threading.Thread(target=still_running.wait, daemon=True)
    reader.start()
    gui._engine_reader_thread = reader
    gui.worker_procs = {"engine": object()}
    gui._engine_rows.append({"t": "note", "msg": "hello"})

    try:
        main.EmulatorManager._drain_engine_rows(gui)
        assert scheduled and scheduled[0][0] == 1000
        assert gui.worker_procs.get("engine") is not None, "must not prune while the reader is alive"
        assert gui._logged == ["hello"]
    finally:
        still_running.set()
        reader.join(timeout=2)


def test_drain_engine_rows_stops_once_the_reader_dies_with_nothing_left_to_drain():
    gui = _make_fake_gui()
    scheduled = []
    gui.after = lambda ms, fn: scheduled.append((ms, fn)) or "job-id"
    already_done = threading.Event()
    already_done.set()
    reader = threading.Thread(target=already_done.wait, daemon=True)
    reader.start()
    reader.join(timeout=2)
    assert not reader.is_alive()
    gui._engine_reader_thread = reader
    gui.worker_procs = {"engine": object()}

    main.EmulatorManager._drain_engine_rows(gui)

    assert not scheduled, "reader is dead -> must not reschedule"
    assert gui.worker_procs.get("engine") is None, "must prune worker_procs once truly done"


class _InjectOnFirstRelease:
    """Stands in for gui._engine_lock. Its __exit__ fires exactly where the real
    threading.Lock's does - when a `with self._engine_lock:` block ends - and, the FIRST
    time only, appends one row to gui._engine_rows right then. That reproduces, on
    purpose, the exact gap _drain_engine_rows's docstring names: a row landing after
    phase 1 copies-and-clears _engine_rows but before the reader-liveness check that
    follows. Real threading.Lock cannot be told to do this, which is why this exists."""

    def __init__(self, gui, row):
        self._gui = gui
        self._row = row
        self._fired = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self._fired:
            self._fired = True
            self._gui._engine_rows.append(self._row)
        return False


def test_drain_engine_rows_second_phase_catches_a_row_that_lands_in_the_exact_gap():
    """The precise race the module docstring calls out, not just its outcome: a row
    injected in the gap between phase 1's copy-and-clear and the reader-liveness check
    must still reach _dispatch_engine_row, cleanup must still run, and the timer must
    not reschedule. Without the second drain pass in _drain_engine_rows, a row landing
    exactly here - which could be the final stat(final=True) summary - would sit in
    _engine_rows forever once nothing ever calls this method again."""
    gui = _make_fake_gui()
    late_row = {"t": "stat", "done": 9, "fail": 0, "stuck": 0, "left": 0, "final": True}
    gui._engine_lock = _InjectOnFirstRelease(gui, late_row)
    already_done = threading.Event()
    already_done.set()
    reader = threading.Thread(target=already_done.wait, daemon=True)
    reader.start()
    reader.join(timeout=2)
    gui._engine_reader_thread = reader
    gui.worker_procs = {"engine": object()}
    scheduled = []
    gui.after = lambda ms, fn: scheduled.append((ms, fn)) or "job-id"

    main.EmulatorManager._drain_engine_rows(gui)

    assert gui._engine_last_stat.get("done") == 9, (
        "a row that lands in the exact gap between the two lock sections must still be "
        "drained, not lost - this is the mechanism behind the 1,427-account story above")
    assert not scheduled, "reader is dead -> must not reschedule even though a late row arrived"
    assert gui.worker_procs.get("engine") is None


# --- log(): must delegate, not recurse ------------------------------------------------------

def test_log_delegates_to_the_module_level_botLineRanger_log(monkeypatch):
    gui = _make_fake_gui()
    del gui.log   # undo the test stub - exercise the real EmulatorManager.log this time
    calls = []
    monkeypatch.setattr(main, "log", lambda msg, **kw: calls.append(msg))
    main.EmulatorManager.log(gui, "hello")
    assert calls == ["hello"]
