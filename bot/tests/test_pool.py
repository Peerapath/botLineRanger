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


def test_a_stop_request_keeps_every_file_accounted_for(tmp_path):
    """ไอดีที่จบก่อนกด Stop ต้องอยู่ใน output/ ครบตามยอด ไม่มีอะไรค้าง execute/"""
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


def test_the_engine_waits_out_an_every_proxy_down_spell_instead_of_quitting(tmp_path, monkeypatch):
    """ไม่มี proxy เหลือ -> ห้ามยิงออก IP ของผู้ใช้เอง แต่ก็ห้ามหยุดทั้งรัน (ผู้ใช้ต้องการให้รันต่อเนื่อง):
    รอ ALL_DOWN_RETRY แล้วลอง proxy ทุกตัวใหม่ งานทั้งหมดต้องเสร็จหลัง proxy กลับมา"""
    import engine.pool as pool_mod
    monkeypatch.setattr(pool_mod, "ALL_DOWN_RETRY", 0.2)
    q = build(tmp_path, 50)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 2, "apirps": 1000},
                      q, ["1.1.1.1:8000"], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    for lane in pool.pool.lanes:
        for _ in range(3):
            lane.note_fail()
    assert not pool.pool.lanes[0].alive
    summary = pool.run()
    got = rows(buf)
    assert any(r["t"] == "note" and "every proxy is down" in r["msg"] for r in got)
    assert any(r["t"] == "lane" and r["state"] == "retry" for r in got)
    assert summary["done"] == len(os.listdir(tmp_path / "output")) == 50


def test_the_direct_lane_never_dies_so_a_network_blip_cannot_end_the_run(tmp_path):
    """ไม่ได้ตั้ง proxy = lane "direct" ตัวเดียว เดิมพังสามครั้งติดกันแล้ว engine หยุดทั้งรัน (2026-09-25)"""
    q = build(tmp_path, 20)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 2}, q, [], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    for _ in range(50):
        pool.pool.lanes[0].note_fail()
    assert pool.pool.lanes[0].alive
    assert pool.run()["done"] == 20


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


# --- จำนวนเธรดอัตโนมัติ (autothreads) + ตารางบัญชีที่กำลังทำ (แถว "active") ---

def test_auto_threads_grow_past_the_starting_count_and_every_file_still_runs_once(tmp_path, monkeypatch):
    """ทุกบัญชียิง request จำนวนเท่ากัน -> เธรดเพิ่ม req/s เพิ่มตาม autoscaler ต้องเพิ่มเธรดจริง
    (ไม่ใช่แค่ขยับเลขเป้า) และการสปอว์นกลางรันต้องไม่ทำให้ไฟล์ไหนถูกทำซ้ำหรือตกหล่น"""
    import threading
    import time

    import engine.autoscale as autoscale_mod
    monkeypatch.setattr(autoscale_mod, "WINDOW", 0.05)
    monkeypatch.setitem(autoscale_mod.START_BY_MODE, "ranger_api_Login", 2)
    q = build(tmp_path, 300)
    buf = io.StringIO()
    lock = threading.Lock()
    seen, live, peak = [], [0], [0]

    def flow(mode, s, cfg):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
            seen.append(os.path.basename(s.src))
        for _ in range(4):
            s.lane.acquire()
            time.sleep(0.005)
        with lock:
            live[0] -= 1
        return Outcome(dest="output")

    summary = EnginePool("ranger_api_Login", {"autothreads": True, "apirps": 100000}, q, [],
                         Reporter(buf), flow=flow).run()
    assert peak[0] > 2
    assert sorted(seen) == sorted(set(seen)) and len(seen) == 300
    assert summary["done"] == len(os.listdir(tmp_path / "output")) == 300


def test_threads_over_a_lowered_target_retire_between_accounts_without_dropping_work(tmp_path, monkeypatch):
    import threading
    import time

    import engine.autoscale as autoscale_mod
    monkeypatch.setattr(autoscale_mod, "WINDOW", 1000.0)   # เทสต์นี้ขยับเป้าเอง
    monkeypatch.setitem(autoscale_mod.START_BY_MODE, "ranger_api_Login", 8)
    q = build(tmp_path, 120)
    buf = io.StringIO()
    lock = threading.Lock()
    live, late_peak, count = [0], [0], [0]

    def flow(mode, s, cfg):
        with lock:
            count[0] += 1
            n = count[0]
            if n == 1:
                pool.pool.lanes[0].threads = 2
            live[0] += 1
            if n > 60:
                late_peak[0] = max(late_peak[0], live[0])
        time.sleep(0.01)
        with lock:
            live[0] -= 1
        return Outcome(dest="output")

    pool = EnginePool("ranger_api_Login", {"autothreads": True, "apirps": 100000}, q, [],
                      Reporter(buf), flow=flow)
    summary = pool.run()
    assert summary["done"] == len(os.listdir(tmp_path / "output")) == 120
    assert os.listdir(tmp_path / "execute") == []
    assert late_peak[0] <= 2


def test_workers_that_leave_because_input_ran_dry_are_not_replaced(tmp_path):
    q = build(tmp_path, 5)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 8}, q, [], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    pool.run()
    assert pool._seq == 8          # สปอว์นแค่ชุดแรก ไม่วนสปอว์นแทนเธรดที่ claim() ได้ None
    assert pool.pool.lanes[0].running == 0


def test_active_rows_show_each_in_flight_account_and_end_empty(tmp_path, monkeypatch):
    import time

    import engine.pool as pool_mod
    monkeypatch.setattr(pool_mod, "ACTIVE_EVERY", 0.01)
    q = build(tmp_path, 2)
    buf = io.StringIO()

    def flow(mode, s, cfg):
        s.mark("stage", "st012/150 Lv9")
        s.attempts = 2
        time.sleep(0.3)
        return Outcome(dest="output")

    EnginePool("ranger_api_Login", {"threadsperproxy": 2}, q, [], Reporter(buf), flow=flow,
               stat_every=0.01).run()
    got = rows(buf)
    active = [r for r in got if r["t"] == "active"]
    live = [row for r in active for row in r["rows"]]
    assert {row["id"] for row in live} == {"000", "001"}      # ชื่อไฟล์ไม่มีนามสกุล ก่อนรู้ rsn
    assert any(row["step"] == "stage" and row["detail"] == "st012/150 Lv9" and row["try"] == 2
               for row in live)
    assert active[-1]["rows"] == []
    stat = [r for r in got if r["t"] == "stat" and not r.get("final")]
    assert stat and {"rpm", "target", "auto", "scale", "threads", "rps", "reqs"} <= set(stat[-1])


def test_auto_threads_start_where_each_mode_is_expected_to_need_them(tmp_path):
    """GenID ติดโควตา mint ตั้งแต่เธรดแรก -> เริ่ม 2, Login/Level3 อิ่มที่ ~128 ต่อ IP -> เริ่ม 32
    โหมดอื่น (Stage/Quest) เริ่มที่ค่ากลาง autoscale.START - ทุกโหมดคิดต่อ lane"""
    import engine.autoscale as autoscale_mod

    q = build(tmp_path, 1)
    buf = io.StringIO()
    auto = {"autothreads": True}

    def lanes(mode, proxies=()):
        pool = EnginePool(mode, auto, q, list(proxies), Reporter(buf),
                          flow=lambda m, s, c: Outcome(dest="output"))
        return [lane.threads for lane in pool.pool.lanes]

    assert lanes("ranger_api_GenID") == [2]
    assert lanes("ranger_api_Login") == [32]
    assert lanes("ranger_api_Level3") == [32]
    assert lanes("ranger_api_Stage") == [autoscale_mod.START]
    assert lanes("ranger_api_Login", ["1.1.1.1:8000", "2.2.2.2:8000"]) == [32, 32]



# --- ปุ่ม Stop: ทุกอย่างต้องหยุดภายในไม่กี่วินาที ไม่ใช่รอไอดีที่ค้างทำจนจบ ---

def test_stop_cuts_in_flight_accounts_at_their_next_request_and_returns_them_to_input(tmp_path):
    """Stage/Quest ใช้ ~9 นาทีต่อไอดี - แบบเดิมกด Stop แล้วบอทยังดันด่านต่ออีกนาน ตอนนี้ request ถัดไป
    ของทุกไอดีโยน EngineStopped ไฟล์กลับ input/ (ทำต่อรอบหน้า) และไม่ถูกนับเป็น done หรือ fail"""
    import threading
    import time

    q = build(tmp_path, 20)
    buf = io.StringIO()
    busy = threading.Barrier(5)

    def endless_flow(mode, s, cfg):
        busy.wait(timeout=5)             # ทั้ง 4 เธรดเข้ามาทำไอดีแล้ว ก่อนเทสต์กด Stop
        while True:                      # ดันด่านไม่รู้จบ - มีแต่ Stop ที่หยุดได้
            s.lane.acquire()
            time.sleep(0.01)

    pool = EnginePool("ranger_api_Stage", {"threadsperproxy": 4, "apirps": 100000}, q, [],
                      Reporter(buf), flow=endless_flow)
    stopper = threading.Thread(target=lambda: (busy.wait(timeout=5), pool.request_stop()))
    stopper.start()
    began = time.time()
    summary = pool.run()
    stopper.join()

    assert time.time() - began < 3
    assert summary["done"] == summary["fail"] == 0
    assert summary["stopped"] == 4
    assert os.listdir(tmp_path / "execute") == []
    assert len(os.listdir(tmp_path / "input")) == 20        # 16 ที่ยังไม่ถูกหยิบ + 4 ที่ถูกตัด
    assert os.listdir(tmp_path / "login failed") == []      # ถูกสั่งหยุด ไม่ใช่ไอดีเสีย
    stopped_rows = [r for r in rows(buf) if r["t"] == "acct"]
    assert len(stopped_rows) == 4 and all(r["status"] == "STOP" and r["dest"] == "input"
                                          for r in stopped_rows)


def test_a_retry_loop_in_the_flow_cannot_swallow_the_stop(tmp_path):
    """flows ดัก `except Exception` แล้ว retry - EngineStopped ต้องทะลุ ไม่งั้นไอดีจะไป login failed"""
    import threading
    import time

    q = build(tmp_path, 1)
    buf = io.StringIO()
    inside = threading.Event()

    def flow_with_retry(mode, s, cfg):
        for _ in range(1000):
            try:
                inside.set()
                s.lane.acquire()
                time.sleep(0.01)
            except Exception:
                continue
        return Outcome(dest="output")

    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 1, "apirps": 100000}, q, [],
                      Reporter(buf), flow=flow_with_retry)
    threading.Thread(target=lambda: (inside.wait(5), pool.request_stop())).start()
    summary = pool.run()
    assert summary["stopped"] == 1 and summary["fail"] == 0
    assert os.listdir(tmp_path / "input") == ["000.xml"]


def test_the_engine_process_exits_promptly_even_with_a_thread_asleep_for_minutes(tmp_path):
    """เธรดที่หลับรอหัวใจเกิดใหม่ (stage_forge รอได้ถึง 10 นาที) ห้ามรั้งโปรเซสไว้ - ต้องออกจริง
    ทั้ง pool.run() ที่เลิกรอหลัง DRAIN_LIMIT และ os._exit ของ engine_main.run_and_exit"""
    import subprocess
    import textwrap
    import time

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = textwrap.dedent("""
        import os, sys, threading, time
        sys.path.insert(0, %(bot)r)
        sys.path.insert(0, os.path.join(os.path.dirname(%(bot)r), "tools"))
        from engine.pool import EnginePool
        from engine.queue import WorkQueue
        from engine.report import Reporter
        root = %(root)r
        for sub in ("input", "execute", "output", "backup", "login failed", "log"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        for i in range(3):
            open(os.path.join(root, "input", "%%d.xml" %% i), "w").close()
        q = WorkQueue(root, os.path.join(root, "log", "run.jsonl"))

        def flow(mode, s, cfg):
            time.sleep(600)          # รอหัวใจ - ไม่มี request ให้ Stop ตัดได้

        pool = EnginePool("ranger_api_Stage", {"threadsperproxy": 3}, q, [], Reporter(), flow=flow)
        threading.Timer(0.3, pool.request_stop).start()
        pool.run()
        q.close()
        sys.stdout.flush()
        os._exit(0)
    """) % {"bot": here, "root": str(tmp_path)}
    began = time.time()
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=30)
    assert done.returncode == 0, done.stderr
    assert time.time() - began < 10
    final = [json.loads(x) for x in done.stdout.splitlines() if '"final"' in x]
    assert final and final[-1]["stopped"] == 3      # หลับอยู่ทั้งสาม - engine คืนไฟล์แทนเธรดที่ไม่ตื่น
    assert sorted(os.listdir(tmp_path / "input")) == ["0.xml", "1.xml", "2.xml"]
    assert os.listdir(tmp_path / "execute") == []



def test_an_account_waiting_to_retry_wakes_up_on_stop_instead_of_sleeping_it_out(tmp_path):
    """flows._backoff รอ 5-15 วิระหว่าง retry - ต้องใช้ lane.nap ที่ตื่นทันทีเมื่อกด Stop"""
    import threading
    import time

    from engine import flows

    q = build(tmp_path, 1)
    buf = io.StringIO()
    waiting = threading.Event()

    def flow(mode, s, cfg):
        waiting.set()
        flows._backoff(s, 2, "relogin failed (HTTP 500)")     # 15 วิ
        return Outcome(dest="output")

    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 1}, q, [], Reporter(buf), flow=flow)
    threading.Thread(target=lambda: (waiting.wait(5), time.sleep(0.1), pool.request_stop())).start()
    began = time.time()
    summary = pool.run()
    assert time.time() - began < 2
    assert summary["stopped"] == 1
    assert os.listdir(tmp_path / "input") == ["000.xml"]


def test_stat_lane_and_note_rows_are_also_kept_on_disk_for_tuning(tmp_path):
    """GUI ไม่เก็บอะไรลงดิสก์ - ยอดและสถานะ autoscaler ของรันที่แล้วต้องย้อนดูได้จากไฟล์"""
    log = tmp_path / "engine-stats.jsonl"
    r = Reporter(io.StringIO(), log_path=str(log))
    r.stat(done=1, rps=80)
    r.account(status="OK")
    r.active(rows=[])
    r.note("hello")
    kept = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x["t"] for x in kept] == ["stat", "note"]
    assert all("ts" in x for x in kept)
