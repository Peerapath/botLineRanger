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
import time

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
    gui.bot_processes = {}            # the older ADB per-device flow; stop_bot_processes
                                       # touches this too, untouched by this task otherwise
    gui._worker_monitor_job = None
    gui._engine_reader_thread = None
    gui._engine_err = None
    gui._engine_reader_crashed = None
    gui.worker_summary_label = _FakeLabel()
    gui._logged = []
    gui.log = lambda msg: gui._logged.append(msg)
    return gui


class _FakeProc:
    """Minimal stand-in for a subprocess.Popen handle - only .poll()/.wait()/.terminate()
    are ever touched by the code under test in this file, never anything Popen-specific
    like .pid or .communicate()."""

    def __init__(self, exit_code=None):
        self._exit_code = exit_code   # None == still running, like the real .poll()
        self.terminated = False
        self.wait_calls = []

    def poll(self):
        return self._exit_code

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._exit_code is None:
            raise subprocess.TimeoutExpired(cmd="engine", timeout=timeout)
        return self._exit_code

    def terminate(self):
        self.terminated = True
        self._exit_code = -15   # SIGTERM-ish, so a later .poll() reflects the kill


class _FakeMultiprocessProc:
    """Stand-in for the older self.bot_processes entries (multiprocessing.Process, one
    per ADB device) - stop_bot_processes must keep hard-killing these regardless of
    `force`, since each one is already a single independent account, not a whole batch."""

    def __init__(self, alive=True):
        self._alive = alive
        self.terminated = False
        self.joined_timeout = None

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminated = True
        self._alive = False

    def join(self, timeout=None):
        self.joined_timeout = timeout


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

    # Identity, not just count (global constraint #6: a test must confirm WHICH rows were
    # attempted, not merely how many - len(calls) == 2 would stay green even if this picked
    # the wrong two rows from somewhere else).
    assert calls == [{"t": "note", "msg": "1"}, {"t": "note", "msg": "2"}], (
        "both rows must still be attempted, in order, even though the first raised")


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
    # .poll() -> 0 (already exited): _drain_engine_rows now cross-checks the process
    # itself, not just the reader thread, before treating a run as finished (Finding 3) -
    # a bare object() no longer models this branch, it would raise AttributeError.
    gui.worker_procs = {"engine": _FakeProc(exit_code=0)}

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
    gui.worker_procs = {"engine": _FakeProc(exit_code=0)}   # already exited - see the sibling test above
    scheduled = []
    gui.after = lambda ms, fn: scheduled.append((ms, fn)) or "job-id"

    main.EmulatorManager._drain_engine_rows(gui)

    assert gui._engine_last_stat.get("done") == 9, (
        "a row that lands in the exact gap between the two lock sections must still be "
        "drained, not lost - this is the mechanism behind the 1,427-account story above")
    assert not scheduled, "reader is dead -> must not reschedule even though a late row arrived"
    assert gui.worker_procs.get("engine") is None
    assert "done 9" in gui.worker_summary_label.texts[-1], (
        "the tally has to survive on the LABEL, not just in _engine_last_stat: "
        "_update_worker_summary counts worker_procs, which is emptied one line earlier, so "
        "calling it here repaints the idle placeholder over the final numbers in the same "
        "synchronous call and the user never sees what the run did. texts[-1] was "
        "'กด ▶ Start เพื่อเริ่ม' until that call was removed")


# --- log(): must delegate, not recurse ------------------------------------------------------

def test_log_delegates_to_the_module_level_botLineRanger_log(monkeypatch):
    gui = _make_fake_gui()
    del gui.log   # undo the test stub - exercise the real EmulatorManager.log this time
    calls = []
    monkeypatch.setattr(main, "log", lambda msg, **kw: calls.append(msg))
    main.EmulatorManager.log(gui, "hello")
    assert calls == ["hello"]


# --- round-1 review fixes ---------------------------------------------------------------
# Everything below covers the six findings from the first review pass: stop_bot_processes
# hard-killing the whole batch (1), a spawn failure being invisible in the windowed build
# (2), a dead reader thread permitting a second engine (3), a failed stop-flag write being
# reported as a successful graceful stop (4), a leaked stderr handle on a failed spawn (5),
# and this file's own test gaps (6).

# --- Finding 5: _spawn_engine must not leak its own stderr handle on a failed Popen ------

def test_spawn_engine_closes_its_own_stderr_handle_if_popen_raises(tmp_path):
    """subprocess.Popen (or _worker_env(), evaluated as one of its own arguments) can
    raise AFTER engine.err has already been opened and truncated just above it in
    _spawn_engine - without a try/finally there, that handle stays open and an empty
    engine.err sits on disk with nothing left to ever close it, until some unrelated
    LATER spawn attempt happens to close it as a side effect of its own
    "close the previous handle" step."""
    gui = _make_fake_gui()
    gui._app_root = lambda: str(tmp_path)
    gui._worker_env = lambda: dict(os.environ)

    def _boom(*a, **kw):
        raise OSError("no such file or directory")

    real_popen = subprocess.Popen
    subprocess.Popen = _boom
    try:
        raised = None
        try:
            main.EmulatorManager._spawn_engine(gui, mode="ranger_api_Login")
        except OSError as exc:
            raised = exc
    finally:
        subprocess.Popen = real_popen

    assert raised is not None, "the Popen failure must still propagate, not be swallowed"
    assert gui._engine_err.closed, "the handle just opened for this failed attempt must not leak"


# --- Finding 3: a reader that dies from anything but a bad JSON line must not be --------
# --- mistaken for the engine having finished --------------------------------------------

def test_read_engine_survives_an_exception_that_is_not_json_loads_and_records_it():
    """_read_engine used to catch only json.loads's ValueError - any OTHER exception (a
    bad pipe read, anything) killed the reader thread silently, with no record left
    behind. _drain_engine_rows's only proof the engine process is gone is this thread
    dying, so a crash here (not a real EOF) used to be indistinguishable from a genuine
    finish."""
    gui = _make_fake_gui()

    class _ExplodingStdout:
        def __iter__(self):
            raise OSError("pipe went away")

    class _Proc:
        stdout = _ExplodingStdout()

    main.EmulatorManager._read_engine(gui, _Proc())   # must not raise out of this call

    assert gui._engine_reader_crashed is not None


def test_drain_engine_rows_refuses_to_treat_a_crashed_reader_as_a_finished_engine():
    """The other half of Finding 3: even once the reader thread is confirmed dead,
    proc.poll() still saying "running" must block _drain_engine_rows from popping
    worker_procs - popping it here is exactly what would let _start_workers spawn a
    second engine over the same input/execute folders the still-running one already
    owns."""
    gui = _make_fake_gui()
    scheduled = []
    gui.after = lambda ms, fn: scheduled.append((ms, fn)) or "job-id"
    dead_reader = threading.Thread(target=lambda: None)
    dead_reader.start()
    dead_reader.join(timeout=2)
    assert not dead_reader.is_alive()
    gui._engine_reader_thread = dead_reader
    gui.worker_procs["engine"] = _FakeProc(exit_code=None)   # still running at the OS level

    main.EmulatorManager._drain_engine_rows(gui)

    assert gui.worker_procs.get("engine") is not None, (
        "the process is still alive - popping this would let a second engine be started "
        "over the same input/execute folders")
    assert scheduled, (
        "must keep polling so it notices the real exit later, instead of requiring an "
        "app restart to recover from what might just be a one-off reader glitch")
    assert gui._engine_reader_crashed is not None, "must be recorded, not silent"


def test_a_crashed_reader_blocks_start_workers_from_spawning_a_second_engine(monkeypatch):
    """End-to-end version of the two tests above, proving the actual promise of Finding 3:
    after a reader crash while the engine is still alive, and one _drain_engine_rows tick
    has noticed it, _start_workers really does refuse - not just that the two halves look
    right in isolation."""
    gui = _make_fake_gui()
    gui.after = lambda ms, fn: "job-id"
    gui.worker_procs["engine"] = _FakeProc(exit_code=None)   # still alive

    class _ExplodingStdout:
        def __iter__(self):
            raise OSError("pipe went away")

    class _Proc:
        stdout = _ExplodingStdout()

    reader = threading.Thread(target=main.EmulatorManager._read_engine, args=(gui, _Proc()))
    reader.start()
    reader.join(timeout=2)
    gui._engine_reader_thread = reader

    main.EmulatorManager._drain_engine_rows(gui)   # one tick, as the real self.after(1000, ...) would run

    gui.save_config = lambda: None
    gui.verify_subscription_sync = lambda: True
    monkeypatch.setattr(main, "readConfigFile", lambda: None)
    spawn_calls = []
    gui._spawn_engine = lambda mode: spawn_calls.append(mode) or _FakeProc(exit_code=None)
    monkeypatch.setattr(main.messagebox, "showwarning", lambda *a, **kw: None)

    main.EmulatorManager._start_workers(gui)

    assert spawn_calls == [], (
        "a crashed reader must not let a second engine spawn while the first is still alive")


# --- Finding 6 (double-start refusal + spawn-failure visibility, Finding 2) -------------

def test_start_workers_refuses_a_second_engine_while_one_is_alive(monkeypatch):
    gui = _make_fake_gui()
    gui.save_config = lambda: None
    gui.verify_subscription_sync = lambda: True
    monkeypatch.setattr(main, "readConfigFile", lambda: None)
    spawn_calls = []
    gui._spawn_engine = lambda mode: spawn_calls.append(mode) or _FakeProc(exit_code=None)
    alive_proc = _FakeProc(exit_code=None)
    gui.worker_procs["engine"] = alive_proc
    warnings = []
    monkeypatch.setattr(main.messagebox, "showwarning",
                         lambda title, msg: warnings.append((title, msg)))

    main.EmulatorManager._start_workers(gui)

    assert spawn_calls == [], "must not spawn a second engine while one is still alive"
    assert gui.worker_procs["engine"] is alive_proc, "must not touch the still-alive entry"
    assert warnings, "must tell the user why nothing happened"


def test_start_workers_spawns_the_engine_and_wires_up_the_reader_when_nothing_is_running(monkeypatch):
    """The happy path this whole task rests on: Start really does spawn exactly one
    engine and run its reader on a background thread when nothing is already running -
    this file had zero tests exercising _start_workers at all before this round."""
    gui = _make_fake_gui()
    gui.save_config = lambda: None
    gui.verify_subscription_sync = lambda: True
    monkeypatch.setattr(main, "readConfigFile", lambda: None)
    gui._currentModeKey = lambda: "ranger_api_GenID"   # skips _prepare_shared_cc entirely
    fake_proc = _FakeProc(exit_code=None)
    fake_proc.stdout = iter(())   # empty - the reader thread returns almost immediately
    gui._spawn_engine = lambda mode: fake_proc
    scheduled = []
    gui.after = lambda ms, fn: scheduled.append((ms, fn)) or "job-id"

    main.EmulatorManager._start_workers(gui)

    assert gui.worker_procs.get("engine") is fake_proc
    assert gui._engine_reader_thread is not None
    assert gui._engine_reader_thread is not threading.current_thread(), (
        "the reader must run on its own thread, never block _start_workers's caller")
    gui._engine_reader_thread.join(timeout=2)
    assert not gui._engine_reader_thread.is_alive()
    assert scheduled and scheduled[0][0] == 1000, "must schedule the once-a-second drain"


def test_start_workers_spawn_failure_is_visible_not_a_bare_print(monkeypatch):
    """Finding 2: a bare print() here is invisible in the shipped build - BotLineRanger.spec
    sets console=False, so there is no console for it to reach. This is the path a user
    hits by clicking Start into a broken install."""
    gui = _make_fake_gui()
    gui.save_config = lambda: None
    gui.verify_subscription_sync = lambda: True
    monkeypatch.setattr(main, "readConfigFile", lambda: None)
    gui._currentModeKey = lambda: "ranger_api_GenID"

    def _boom(mode):
        raise RuntimeError("no such file or directory")
    gui._spawn_engine = _boom

    errors = []
    monkeypatch.setattr(main.messagebox, "showerror",
                         lambda title, msg: errors.append((title, msg)))

    main.EmulatorManager._start_workers(gui)

    assert gui.worker_procs.get("engine") is None
    assert any("spawn" in m.lower() for m in gui._logged), (
        "must reach self.log(), not just a bare print() that a windowed build swallows")
    assert errors, "must also show a messagebox - print() alone never reaches this build's user"


# --- Finding 6 (background-thread move): the Stop button's grace wait must not block ----

def test_stop_workers_grace_wait_runs_on_a_background_thread_not_the_caller(tmp_path):
    """The Stop button's grace-wait + fallback terminate() must never block the caller -
    the Tk main thread, for a real click - or clicking Stop would freeze the whole window
    for up to 90 seconds. Pinned here with a real timing assertion, not just by reading
    the source."""
    gui = _make_fake_gui()
    gui._app_root = lambda: str(tmp_path)
    release = threading.Event()
    waited = threading.Event()

    class _NeverExitsQuickly(_FakeProc):
        def wait(self, timeout=None):
            waited.set()
            release.wait(timeout=5)   # bounded - a regression here must not hang the suite
            return super().wait(timeout=timeout)

    gui.worker_procs["engine"] = _NeverExitsQuickly(exit_code=None)
    try:
        started = time.time()
        main.EmulatorManager._stop_workers(gui, silent=True)
        elapsed = time.time() - started

        assert elapsed < 1.0, (
            "_stop_workers must return immediately - the grace wait belongs on a "
            "background thread, never the caller's")
        assert waited.wait(timeout=2), "the background thread must actually call proc.wait()"
    finally:
        release.set()   # let the background thread finish instead of leaking past the test


# --- Finding 4: a failed stop-flag write must be reported honestly ----------------------

def test_stop_workers_tells_the_truth_when_the_stop_flag_write_fails(tmp_path):
    """A failed stop.flag write must not be reported the same way as a normal graceful
    stop - if the engine can never see the flag, the "waiting..." message is a lie: it
    burns the full grace period and gets terminated anyway, having pretended to drain
    the whole time."""
    gui = _make_fake_gui()
    gui._app_root = lambda: str(tmp_path)
    # "src" exists as a plain FILE, not a directory, so os.makedirs(.../src/log) fails with
    # a real OSError - the same way a permissions problem or a full disk would, without
    # reaching into the stdlib to fake one.
    (tmp_path / "src").write_text("not a directory", encoding="utf-8")
    gui.worker_procs["engine"] = _FakeProc(exit_code=None)

    main.EmulatorManager._stop_workers(gui, silent=False)

    logged = " ".join(gui._logged)
    assert "flag" in logged and "fail" in logged, "must say the flag write itself failed"
    assert "waiting for in-flight accounts to finish" not in logged, (
        "must not claim a graceful drain is underway when the flag was never written")


# --- Finding 1: stop_bot_processes must drain, not kill, unless a caller explicitly ------
# --- asks for an immediate kill ----------------------------------------------------------

def test_stop_bot_processes_force_true_kills_the_engine_and_adb_processes_immediately(tmp_path):
    """stop_bot_processes used to hard-kill worker_procs unconditionally - no flag, no
    drain, no grace period. That must now be an explicit, opt-in choice (force=True),
    reserved for callers about to end the whole GUI process right after."""
    gui = _make_fake_gui()
    gui._app_root = lambda: str(tmp_path)
    engine = _FakeProc(exit_code=None)
    gui.worker_procs["engine"] = engine
    adb_proc = _FakeMultiprocessProc(alive=True)
    gui.bot_processes["dev1"] = adb_proc

    main.EmulatorManager.stop_bot_processes(gui, force=True)

    assert engine.terminated, "force=True must terminate the engine immediately"
    assert gui.worker_procs == {}, "force=True cleans up worker_procs synchronously"
    assert adb_proc.terminated and adb_proc.joined_timeout == 2, (
        "the older ADB per-device path is untouched by this task and must still be "
        "killed immediately regardless of `force`")
    assert not os.path.exists(os.path.join(str(tmp_path), "src", "log", "stop.flag")), (
        "force=True is an immediate kill, not a drain - it must not write the stop flag")


def test_stop_bot_processes_force_false_drains_instead_of_killing(tmp_path):
    """The actual fix for Finding 1: stop_bot_processes(force=False) must behave exactly
    like the Stop button (write the flag, wait in the background, do not kill on the
    spot) - not the old unconditional terminate() this method used to run for every one
    of its seven callers."""
    gui = _make_fake_gui()
    gui._app_root = lambda: str(tmp_path)
    release = threading.Event()
    waited = threading.Event()

    class _StillRunning(_FakeProc):
        def wait(self, timeout=None):
            waited.set()
            release.wait(timeout=5)
            raise subprocess.TimeoutExpired(cmd="engine", timeout=timeout)

    engine = _StillRunning(exit_code=None)
    gui.worker_procs["engine"] = engine
    try:
        main.EmulatorManager.stop_bot_processes(gui, force=False)

        assert waited.wait(timeout=2), "force=False must still ask the engine to drain"
        assert not engine.terminated, (
            "must not terminate immediately - draining instead of killing is the entire point")
        assert gui.worker_procs.get("engine") is engine, (
            "cleanup happens later, via _drain_engine_rows noticing the exit - not here")
        assert os.path.exists(os.path.join(str(tmp_path), "src", "log", "stop.flag")), (
            "force=False must write the stop flag so the engine actually hears the request")
    finally:
        release.set()


# --- play modes: every dropdown entry must reach a real engine flow ----------------------

def test_every_play_mode_the_dropdown_offers_has_an_engine_flow():
    """A mode the GUI offers but engine/flows.py does not know spawns an engine that dies
    at flows.run's ValueError on the first account - the user clicks Start and gets a run
    of nothing but FAIL rows."""
    from engine import flows
    assert set(main.ALL_PLAY_MODE_OPTIONS.values()) <= set(flows.MODES)


def test_login_quest_is_offered_to_anyone_licensed_for_stage():
    """The license API does not know ranger_api_Quest yet - without the composite rule the
    mode would never appear in the dropdown for a non-whitelisted user."""
    assert main.COMPOSITE_MODE_REQUIREMENTS["ranger_api_Quest"] == ["ranger_api_Stage"]
