"""EnginePool: เธรดทุกตัวดึงงานจากคิวเดียว แล้วรายงานผลเป็น JSONL

บั๊กที่ชุดนี้กันไว้: supervisor ที่ terminate() ทันที ทำให้ยอดสุดท้ายของลูกหาย -
รอบ mint จริงเคยขาดไป 1,427 ใบ ของไม่ได้หายแต่ตัวเลขผิด
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine.pool import EnginePool       # noqa: E402
from engine.queue import WorkQueue       # noqa: E402
from engine.report import Reporter       # noqa: E402
from engine.session import Outcome       # noqa: E402


def build(tmp_path, n):
    for sub in ("input", "execute", "output", "backup", "login failed", "log"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (tmp_path / "input" / ("%03d.xml" % i)).write_text("<map/>", encoding="utf-8")
    return WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))


def rows(buf):
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


def test_every_file_in_the_queue_is_processed_exactly_once(tmp_path):
    q = build(tmp_path, 60)
    seen = []
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 8}, q, [], Reporter(buf),
                      flow=lambda mode, s, cfg: (seen.append(os.path.basename(s.src)),
                                                 Outcome(dest="output"))[1])
    pool.run()
    assert len(seen) == 60
    assert len(set(seen)) == 60
    assert len(os.listdir(tmp_path / "output")) == 60
    assert os.listdir(tmp_path / "execute") == []


def test_a_flow_that_raises_sends_its_file_to_login_failed_and_the_pool_keeps_going(tmp_path):
    q = build(tmp_path, 10)
    buf = io.StringIO()

    def flow(mode, s, cfg):
        if s.src.endswith("005.xml"):
            raise RuntimeError("boom")
        return Outcome(dest="output")

    EnginePool("ranger_api_Login", {"threadsperproxy": 4}, q, [], Reporter(buf), flow=flow).run()
    assert len(os.listdir(tmp_path / "output")) == 9
    assert os.listdir(tmp_path / "login failed") == ["005.xml"]


def test_each_finished_account_is_reported_once(tmp_path):
    q = build(tmp_path, 12)
    buf = io.StringIO()
    EnginePool("ranger_api_Login", {"threadsperproxy": 4}, q, [], Reporter(buf),
               flow=lambda m, s, c: Outcome(dest="output")).run()
    assert len([r for r in rows(buf) if r["t"] == "acct"]) == 12


def test_the_final_stat_line_matches_what_landed_on_disk(tmp_path):
    """ตรวจจากดิสก์ ไม่ใช่จากตัวเลขที่รายงาน - ยอดที่ขาดไปเงียบ ๆ คือบั๊กที่แพงที่สุด"""
    q = build(tmp_path, 25)
    buf = io.StringIO()
    summary = EnginePool("ranger_api_Login", {"threadsperproxy": 5}, q, [], Reporter(buf),
                         flow=lambda m, s, c: Outcome(dest="output")).run()
    assert summary["done"] == len(os.listdir(tmp_path / "output")) == 25


def test_a_permanently_failing_final_move_is_not_counted_or_reported_as_done(tmp_path, monkeypatch):
    """Critical finding (review round 1): the test the finding said was missing.

    Reproduction, done by temporarily reverting queue.py's _close to a bare os.replace()
    and pool.py's _run_one to count done/fail before checking whether the move it just
    tried actually landed (both exactly as this task received them): with this same setup
    (3 accounts, every execute/->output/ move forced to fail permanently),
    summary["done"] came back 3 while output/ held 0 files and all three sat in execute/ -
    the invariant test_the_final_stat_line_matches_what_landed_on_disk exists to guard,
    reached by a path that test never drove (a *failing* move). After the fix below, the
    same setup instead reports summary["done"] == 0 and summary["stuck"] == 3.
    """
    import engine.queue as queue_mod

    q = build(tmp_path, 3)
    buf = io.StringIO()
    real_replace = os.replace

    def deny_the_final_move(src, dst):
        # Let claim() (input/ -> execute/) through untouched - only the move this test is
        # about (execute/ -> a destination folder) must fail, permanently, every attempt.
        if os.path.basename(os.path.dirname(dst)) == "execute":
            return real_replace(src, dst)
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(os, "replace", deny_the_final_move)
    # _replace_with_retry's own sleep between attempts is real time (constraint #13's
    # retry budget) - zero it so exhausting all 5 attempts, 3 times over, stays fast.
    monkeypatch.setattr(queue_mod, "_REPLACE_RETRY_DELAY_S", 0.0)

    summary = EnginePool("ranger_api_Login", {"threadsperproxy": 3}, q, [], Reporter(buf),
                         flow=lambda m, s, c: Outcome(dest="output")).run()

    assert summary["done"] == len(os.listdir(tmp_path / "output")) == 0
    assert len(os.listdir(tmp_path / "execute")) == 3   # stuck, not lost and not delivered
    assert summary["stuck"] == 3
    # The per-account line must not claim the file reached "output" either.
    acct_rows = [r for r in rows(buf) if r["t"] == "acct"]
    assert all(r["moved"] is False and r["dest"] == "execute" for r in acct_rows)


def test_a_stop_request_lets_running_accounts_finish(tmp_path):
    """ฆ่าทันทีคือการทิ้งงานที่ทำไปแล้วครึ่งทาง พร้อมยอดสุดท้ายของมัน"""
    import threading
    q = build(tmp_path, 200)
    buf = io.StringIO()
    started = threading.Event()

    def flow(mode, s, cfg):
        started.set()
        return Outcome(dest="output")

    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 4}, q, [], Reporter(buf), flow=flow)
    stopper = threading.Thread(target=lambda: (started.wait(2), pool.request_stop()))
    stopper.start()
    summary = pool.run()
    stopper.join()
    assert os.listdir(tmp_path / "execute") == []
    assert summary["done"] == len(os.listdir(tmp_path / "output"))


def test_the_reporter_writes_one_json_object_per_line(tmp_path):
    buf = io.StringIO()
    r = Reporter(buf)
    r.account(status="OK", rsn="ID1")
    r.stat(done=1, left=2)
    r.lane(name="1.1.1.1:8000", state="dead")
    got = rows(buf)
    assert [x["t"] for x in got] == ["acct", "stat", "lane"]


def test_a_capped_thread_count_is_announced_not_swallowed(tmp_path):
    """ตัดได้ แต่ต้องบอก - หน้าเว็บที่โกหกเรื่องเพดานเคยอยู่มาหลายวัน"""
    q = build(tmp_path, 1)
    buf = io.StringIO()
    EnginePool("ranger_api_Login",
               {"threadsperproxy": 96, "maxthreads": 8},
               q, ["%d.1.1.1:8000" % i for i in range(4)], Reporter(buf),
               flow=lambda m, s, c: Outcome(dest="output")).run()
    assert any(r["t"] == "note" and "capped" in r["msg"] for r in rows(buf))


def test_a_worker_on_a_dead_lane_stops_taking_work(tmp_path):
    """งานที่ยังไม่ถูก claim ต้องอยู่ในคิวให้ lane อื่นทำ ไม่ใช่ถูก lane ที่ตายแล้วดูดไปทิ้ง"""
    q = build(tmp_path, 40)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 2, "apirps": 1000},
                      q, ["1.1.1.1:8000", "2.2.2.2:8000"], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    for _ in range(3):
        pool.pool.lanes[0].note_fail()
    pool.run()
    assert len(os.listdir(tmp_path / "output")) == 40      # lane ที่เหลือทำครบ


def test_the_engine_stops_when_every_proxy_is_down(tmp_path):
    """ไม่มี proxy เหลือแล้ววิ่งต่อ = ยิงออก IP ของผู้ใช้เอง ซึ่งคือสิ่งที่เขาตั้ง proxy ไว้เลี่ยง"""
    import engine.pool as pool_mod
    q = build(tmp_path, 500)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 2, "apirps": 1000},
                      q, ["1.1.1.1:8000"], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    monkey = pool_mod.STAT_EVERY
    pool_mod.STAT_EVERY = 0.05
    try:
        for lane in pool.pool.lanes:
            for _ in range(3):
                lane.note_fail()
        pool.run()
    finally:
        pool_mod.STAT_EVERY = monkey
    assert any(r["t"] == "note" and "every proxy is down" in r["msg"] for r in rows(buf))
    assert q.remaining() > 0        # คิวยังเหลือ ไม่ได้ถูกกินทิ้ง


# --- extra coverage added for this task, beyond the brief's own Step 1 block above ---
#
# The controller's brief explicitly asked for one property to be confirmed here: each
# worker thread binds exactly one lane for its whole life and never rebinds. The test
# below is that confirmation - it spies on rangers_api.use_lane (what actually performs
# the bind) and checks both halves of the claim: every thread's calls name the same lane
# object every time, and no thread calls it more than once (bind-at-start, not
# bind-per-file). This is not hypothetical: rangers_api.call() keys note_ok()/note_fail()
# off current_lane() (tools/rangers_api.py:183,192), so a thread that rebinds would
# attribute a real connection failure to the wrong lane's health counter.
def test_a_worker_thread_binds_exactly_one_lane_for_its_whole_life(tmp_path):
    import threading

    import engine.pool as pool_mod

    q = build(tmp_path, 60)
    buf = io.StringIO()
    binds = []   # (thread_ident, lane) in call order, across every worker thread
    lock = threading.Lock()
    real_use_lane = pool_mod.rangers_api.use_lane

    def spy_use_lane(lane):
        with lock:
            binds.append((threading.get_ident(), lane))
        real_use_lane(lane)

    pool_mod.rangers_api.use_lane = spy_use_lane
    try:
        EnginePool("ranger_api_Login", {"threadsperproxy": 6, "apirps": 1000},
                   q, ["1.1.1.1:8000", "2.2.2.2:8000"], Reporter(buf),
                   flow=lambda m, s, c: Outcome(dest="output")).run()
    finally:
        pool_mod.rangers_api.use_lane = real_use_lane

    assert binds                                     # the spy actually saw calls
    by_thread = {}
    for ident, lane in binds:
        by_thread.setdefault(ident, []).append(lane)
    # ผูกครั้งเดียวต่อเธรด - ไม่ใช่ผูกซ้ำทุกไฟล์ (แม้จะเป็น lane เดิมก็ตาม)
    assert all(len(lanes) == 1 for lanes in by_thread.values())


def test_threadcount_sets_the_total_thread_budget_divided_across_lanes(tmp_path):
    """I2 (final review): bot/main.py:1353 writes cfg["threadcount"] from the GUI's
    thread-count spinner; nothing engine-side read it - EnginePool used threadsperproxy,
    a key absent from the user's real config, so the spinner (threadcount = 90 in their
    file) had zero effect and the engine silently ran the 96-default instead. Chosen:
    threadcount, when present, means the TOTAL thread budget across the whole pool
    (matching what it meant when 1 process was 1 unit of concurrency in the old fleet),
    divided evenly across lanes - not a second, independently-set per-lane number.
    """
    q = build(tmp_path, 1)
    buf = io.StringIO()
    solo = EnginePool("ranger_api_Login", {"threadcount": 90}, q, [], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    assert solo.pool.lanes[0].threads == 90     # apiproxies empty -> one lane, all of it

    split = EnginePool("ranger_api_Login", {"threadcount": 90},
                       q, ["1.1.1.1:8000", "2.2.2.2:8000", "3.3.3.3:8000"], Reporter(buf),
                       flow=lambda m, s, c: Outcome(dest="output"))
    assert [lane.threads for lane in split.pool.lanes] == [30, 30, 30]

    # threadsperproxy is still the direct per-lane override when threadcount is absent -
    # existing callers (tests, and any future non-GUI caller) must see no change at all.
    unaffected = EnginePool("ranger_api_Login", {"threadsperproxy": 8}, q, [], Reporter(buf),
                            flow=lambda m, s, c: Outcome(dest="output"))
    assert unaffected.pool.lanes[0].threads == 8


def test_genid_mode_does_not_claim_from_input_and_moves_the_file_the_flow_produced(tmp_path):
    """C2 (final review): GenID mints its own account file mid-flow (flows._create_account
    sets s.src to the freshly minted path) instead of consuming one queue.claim() handed
    out. Two bugs, one test: (a) the pool must not gate GenID on queue.claim() - input/ is
    empty here, and the old code returned None immediately so no account was ever
    processed; (b) the file that reaches output/ must be the one the flow actually wrote,
    not some other file the pool claimed - proven here by there being nothing to claim.
    """
    q = build(tmp_path, 0)      # empty input/ - GenID must still run
    buf = io.StringIO()
    minted = []

    def flow(mode, s, cfg):
        n = len(minted) + 1
        minted.append(n)
        path = tmp_path / "execute" / ("minted-%d.xml" % n)
        path.write_text("<map/>", encoding="utf-8")
        s.src = str(path)              # the flow "mints" a brand-new account file itself
        if n >= 3:
            pool.request_stop()        # GenID loops forever otherwise - stop after 3
        return Outcome(dest="output", name="acct-%d" % n)

    pool = EnginePool("ranger_api_GenID", {"threadsperproxy": 1}, q, [], Reporter(buf), flow=flow)
    pool.run()

    assert minted == [1, 2, 3]
    assert sorted(os.listdir(tmp_path / "output")) == ["acct-1.xml", "acct-2.xml", "acct-3.xml"]
    assert os.listdir(tmp_path / "execute") == []


def test_a_flow_returning_an_unrecognized_destination_fails_that_file_but_not_the_thread(tmp_path):
    """A flow bug (typo'd dest, a path nobody wired into DESTS) must not kill the worker
    thread that hit it - that would strand the claimed file in execute/ for the rest of
    the run and quietly shrink the pool by one thread, indistinguishable from a lane dying
    for a completely unrelated reason."""
    q = build(tmp_path, 5)
    buf = io.StringIO()
    EnginePool("ranger_api_Login", {"threadsperproxy": 2}, q, [], Reporter(buf),
               flow=lambda m, s, c: Outcome(dest="nowhere")).run()
    assert len(os.listdir(tmp_path / "login failed")) == 5
    assert os.listdir(tmp_path / "execute") == []
