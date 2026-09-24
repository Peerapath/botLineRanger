"""thread pool ที่แทนฝูง 128 โปรเซส

เธรดหนึ่งตัว = หนึ่งบัญชีที่กำลังทำอยู่ เธรดทุกตัวของ lane เดียวกันใช้งบ request
ก้อนเดียวกัน และทุกตัวดึงงานจากคิวกลางตัวเดียว ไม่มีการแบ่งงานล่วงหน้า - แบ่งล่วงหน้า
แปลว่า worker ที่เจอบัญชีพังรัว ๆ จบก่อนแล้วนั่งว่างขณะที่ตัวอื่นยังมีคิวยาว
"""
from __future__ import annotations

import collections
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))
import client_version  # noqa: E402
import rangers_api   # noqa: E402

from . import autoscale           # noqa: E402
from . import flows as flows_mod   # noqa: E402
from .proxy import EngineStopped, ProxyPool   # noqa: E402
from .queue import DESTS           # noqa: E402
from .session import AccountSession, Outcome   # noqa: E402

# STAT_EVERY / DRAIN_LIMIT / LANE_RETRY stay module-level (not copied onto self in
# __init__) so a test can monkeypatch them (pool_mod.STAT_EVERY = ...) the way this task's
# own "every proxy is down" test does: run() re-reads the module global at the point of
# use, so a patch applied any time before that read still lands.
#
# POLL_EVERY is new, not one of the three the task brief named. It splits "how often the
# supervisor wakes up to check whether it is done" from "how often it emits a stat line"
# (STAT_EVERY - throttled for the GUI, see report.py's own docstring). Without that split,
# every test below that does not override STAT_EVERY would sit out a real 2-second sleep
# before noticing its fake, sub-millisecond flow had already finished - exactly the "test
# that waits on wall-clock time" the brief called out as this task's risk.
STAT_EVERY = 2.0       # วินาที - ผูกกับเวลา ไม่ใช่จำนวนบัญชี คิวที่เดินช้าก็ยังมีสัญญาณชีพ
POLL_EVERY = 0.05      # seconds between supervisor wake-ups (thread/lane health checks)
# หลังกด Stop: รอเธรดวางมือได้นานสุดเท่านี้ แล้วเลิกรอ - เธรดที่ยังหลับอยู่ (รอหัวใจ, รอ retry,
# รอโควตา mint) เป็น daemon ตายไปพร้อมโปรเซส ไฟล์ของมันค้าง execute/ แล้ว recover() คืน input/ ตอนเริ่มรอบหน้า
# เดิม 60 วิและปล่อยให้ไอดีที่ค้างทำจนจบ - Stage/Quest ใช้ ~9 นาทีต่อไอดี กด Stop แล้วบอทยังวิ่งต่ออีกนาน
DRAIN_LIMIT = 3.0
LANE_RETRY = 300.0     # วินาที - proxy ที่ล่มชั่วคราวได้กลับมาเอง ไม่ต้องรีสตาร์ททั้ง engine
ALL_DOWN_RETRY = 30.0  # วินาที - proxy ล่มหมดทุกตัว: ลองใหม่เร็วกว่านี้ ไม่ใช่หยุดทั้งรัน
ACTIVE_EVERY = 1.0     # วินาที - ตารางบัญชีที่กำลังทำใน GUI อัปเดตถี่เท่านี้
ACTIVE_MAX = 500       # แถวต่อหนึ่งรายงาน - กันบรรทัด JSONL ยาวเกินเหตุตอนเธรดเยอะมาก
RPM_WINDOW = 60.0      # วินาที - "บัญชี/นาที" ใน stat คิดจากช่วงล่าสุดเท่านี้ ไม่ใช่เฉลี่ยทั้งรัน

# Named here (not just a literal string inline in engine_main.py) so anything that needs to
# know the flag's filename - engine_main.py's watcher thread today, a GUI later - imports
# one name instead of copying the string a second place it can drift out of sync with.
STOP_FLAG = "stop.flag"


class EnginePool:
    def __init__(self, mode, cfg, queue, proxies, reporter, flow=None,
                 stat_every=None, poll_every=None, drain_limit=None, lane_retry=None,
                 sleep=None) -> None:
        self.mode = mode
        self.cfg = cfg
        self.queue = queue
        self.reporter = reporter
        self.flow = flow if flow is not None else flows_mod.run
        # Each of these falls back to the module constant, read fresh inside run() and not
        # here, so the monkeypatch behavior described above still works. A caller that
        # wants a fixed value regardless of the module globals (this task's own timing
        # tests) passes it directly here instead, with no shared mutable state to leak
        # between tests.
        self._stat_every = stat_every
        self._poll_every = poll_every
        self._drain_limit = drain_limit
        self._lane_retry = lane_retry
        self._sleep = sleep if sleep is not None else time.sleep
        # I2 (final review): threadcount is the GUI's thread-count spinner
        # (bot/main.py:1180-1360, saved at :1353) - it wrote a number nothing engine-side
        # read. threadsperproxy is a NEW, PER-LANE knob this rewrite introduced (spec sec 6)
        # that scales UP as proxies are added; threadcount meant "total concurrency" back
        # when 1 process was 1 unit of concurrency in the old fleet, and the user's real
        # config sets it (threadcount = 90, apiproxies empty -> exactly one lane, so the two
        # numbers mean the same thing there). Chosen: threadcount, when present, is the
        # TOTAL thread budget, divided evenly across lanes (>= 1 each, same rule maxthreads'
        # own overflow already uses below) - not a second, independently-set per-lane
        # number. threadsperproxy stays the direct per-lane override for any caller (tests,
        # a future non-GUI caller) that never sets threadcount.
        #
        # autothreads (engine_main ตั้งเป็น True เป็นค่าปริยาย GUI ไม่มีช่องตั้งเลขแล้ว): ทั้งสองคีย์ข้างบน
        # ถูกข้าม เริ่มที่ autoscale.start_for(mode) ต่อ lane (GenID 2, Login 32) แล้วให้ AutoScaler
        # หาเลขที่ได้บัญชี/นาทีสูงสุดเอง
        # ค่าปริยายของคลาสนี้ยังเป็นเลขคงที่ เทสต์และผู้เรียกอื่นที่ส่ง threadsperproxy มาได้ผลเดิมทุกอย่าง
        lane_count = len(proxies) or 1     # ProxyPool falls back to one "direct" lane too
        max_threads = int(cfg.get("maxthreads") or 4096)
        self._auto = bool(cfg.get("autothreads", False))
        self._lane_max = max(1, min(autoscale.LANE_MAX, max_threads // lane_count))
        if self._auto:
            threads_per = min(autoscale.start_for(mode), self._lane_max)
        elif "threadcount" in cfg:
            threads_per = max(1, int(cfg["threadcount"]) // lane_count)
        else:
            threads_per = int(cfg.get("threadsperproxy") or 96)
        self.pool = ProxyPool(
            proxies,
            rps=float(cfg.get("apirps") or 90),
            threads_per=threads_per,
            max_threads=max_threads)
        if self.pool.capped:
            self.reporter.note(
                "threads capped: %d requested, %d running (ceiling %s)"
                % (self.pool.capped + self.pool.total_threads(),
                   self.pool.total_threads(), cfg.get("maxthreads") or 4096))
        self._stop = threading.Event()
        self._stop_at = None    # set once, by request_stop() - anchors the drain window
        self._lock = threading.Lock()
        self._done = 0
        self._fail = 0
        # Finding 1b (review round 1): accounts whose flow finished but whose file could
        # not be moved out of execute/ after _replace_with_retry exhausted every attempt -
        # see _run_one. Counted separately from done/fail so neither of those can ever
        # claim a destination folder holds a file that is still sitting in execute/.
        self._stuck = 0
        # ไอดีที่ถูกตัดกลางทางเพราะกด Stop - ไฟล์คืน input/ แล้ว ไม่ใช่ done/fail
        self._aborted = 0
        self._version_stopped = False
        # คิว input/ หมดแล้ว (มีเธรดที่ claim() ได้ None) - ห้ามสปอว์นเธรดมาแทนตัวที่ออกไป
        self._exhausted = False
        self._seq = 0              # เลขท้ายชื่อเธรด ไม่ซ้ำตลอดรัน
        # บัญชีที่กำลังทำอยู่ (key -> session) ให้ตารางใน GUI - เขียนจากเธรด worker
        # อ่านจาก supervisor ทุก ACTIVE_EVERY
        self._active: dict = {}
        self._active_seq = 0

    def request_stop(self) -> None:
        """หยุดทุกอย่าง: ไม่รับงานใหม่ และไอดีที่ค้างอยู่วางมือที่ request ถัดไป (lane โยน EngineStopped)

        ผู้ใช้กด Stop = ต้องหยุดจริงภายในไม่กี่วินาที ไม่ใช่รอไอดีที่ค้างทำจนจบ ไฟล์ของไอดีที่ถูกตัด
        คืนเข้า input/ (_abort) ส่วนยอดสุดท้ายยังส่งครบเพราะ engine ออกเองหลัง DRAIN_LIMIT วินาที
        ไม่ใช่ถูก terminate() กลางทาง
        """
        with self._lock:
            if self._stop_at is None:
                self._stop_at = time.time()
        self._stop.set()
        for lane in self.pool.lanes:
            lane.stop()

    def _stop_for_version(self, session, err) -> None:
        """ไม่มี App-Version หรือ URL prefix ไหนที่เซิร์ฟเวอร์รับเลย (client_version สำรวจแล้ว)

        ทุกบัญชีหลังจากนี้จะล้มแบบเดียวกัน ถ้าปล่อยให้เป็น FAIL ธรรมดา Login จะย้ายไฟล์ input
        ทั้งหมดไป login failed/ และ GenID จะเผาโควตา mint ทิ้งทุกรอบ จึงหยุดรับงาน ไม่ย้ายไฟล์
        (ค้างใน execute/ แล้ว queue.recover() คืนเข้า input/ ตอนรันถัดไป) และบอกผู้ใช้ครั้งเดียว
        """
        with self._lock:
            first = not self._version_stopped
            self._version_stopped = True
            if session.src:
                self._stuck += 1
        if first:
            self.reporter.note("stopping: %s - accounts in progress stay in execute/ and go back "
                               "to input/ on the next run" % err)
        self.request_stop()

    def _worker(self, lane) -> None:
        # Bind ONCE, for this thread's entire life: lane is fixed the moment
        # threading.Thread(target=self._worker, args=(lane,)) is built, and nothing below
        # ever calls use_lane again or rebinds the name. That is the guarantee Task 4's
        # reviewer asked to have confirmed here - see
        # test_a_worker_thread_binds_exactly_one_lane_for_its_whole_life below. It matters
        # beyond bookkeeping: rangers_api.call() keys note_ok()/note_fail() off
        # current_lane() (tools/rangers_api.py:183,192), so a thread that ever rebinds
        # would attribute a connection failure to the wrong lane's health counter.
        rangers_api.use_lane(lane)
        # C2 (final review): GenID must not need queue.claim() to find work - it mints its
        # own account instead of consuming an input/ file (see flows.SELF_SUPPLIED_MODES's
        # own docstring). Gating it on claim() made it consume one input file per account
        # AND stop dead the moment input/ ran dry, when the mode is meant to run until told
        # to stop.
        self_supplied = self.mode in flows_mod.SELF_SUPPLIED_MODES
        retired = False
        try:
            while not self._stop.is_set():
                if not lane.alive:
                    # proxy ของเธรดนี้ตาย - ออกไปเลย งานที่ยังไม่ถูก claim ยังอยู่ในคิวให้ lane
                    # อื่นหยิบต่อ ไม่มีอะไรหาย
                    return
                if lane.retire_one():
                    # autoscaler ลดเป้าของ lane - ออกตรงรอยต่อระหว่างบัญชี ไม่ทิ้งงานครึ่งทาง
                    retired = True
                    return
                if self_supplied:
                    src = ""       # _run_one's session starts empty; the flow fills s.src itself
                else:
                    src = self.queue.claim()
                    if src is None:
                        self._exhausted = True
                        return
                self._run_one(lane, src)
        finally:
            if not retired:        # retire_one() หักตัวเองออกจาก running ไปแล้วในล็อก
                lane.leave()

    def _run_one(self, lane, src) -> None:
        started = time.time()
        session = AccountSession(src=src, lane=lane)
        with self._lock:
            self._active_seq += 1
            key = self._active_seq
            self._active[key] = session
        try:
            self._run_session(lane, session, started)
        finally:
            with self._lock:
                self._active.pop(key, None)

    def _abort(self, lane, session, started) -> None:
        """ไอดีที่ถูกกด Stop กลางทาง: คืนไฟล์เข้า input/ ทำต่อรอบหน้า - ไม่นับเป็น done หรือ fail"""
        dest = "none"
        move_err = ""
        if session.src:
            try:
                self.queue.release(session.src)
                dest = "input"
            except OSError as err:
                dest = "execute"          # recover() ตอนเริ่มรอบหน้าคืนให้แทน
                move_err = str(err)
        with self._lock:
            self._aborted += 1
        self.reporter.account(status="STOP", rsn=session.rsn, lv=session.level,
                              ms=int((time.time() - started) * 1000), dest=dest,
                              moved=dest == "input", lane=lane.name, err="stopped",
                              move_err=move_err[:120])

    def _run_session(self, lane, session, started) -> None:
        try:
            out = self.flow(self.mode, session, self.cfg)
            if out.dest not in DESTS:
                # A flow bug returning a destination nobody wired up must not kill this
                # worker thread - that would strand this account's file at execute/ forever
                # (this run never retries a claimed file) and quietly shrink the pool by one
                # thread, indistinguishable from a lane dying for an unrelated reason.
                raise ValueError("flow returned an unknown destination %r" % (out.dest,))
        except EngineStopped:
            self._abort(lane, session, started)
            return
        except client_version.VersionUnavailable as err:
            self._stop_for_version(session, err)
            return
        except (Exception, SystemExit) as err:
            # SystemExit ต้องอยู่ตรงนี้ด้วย ไม่ใช่แค่ Exception: ไฟล์ใน tools/ ที่เกิดมาเป็น CLI
            # ยัง raise SystemExit แทนคำว่า "คำขอนี้ไม่ผ่าน" อยู่หลายที่ที่ทุกโหมดเดินไปถึง -
            # new_account 367/381, gacha 118/269, rewards 75, gifts 35, sevendays 40,
            # export_account 40, pull_roster 152/283 - และ SystemExit สืบจาก BaseException
            # จึงลอด `except Exception` ไปได้ ที่ร้ายคือ threading.excepthook จงใจข้าม
            # SystemExit ทิ้ง เธรดจึงตายแบบ *ไม่พิมพ์อะไรเลย* ไม่มี traceback ไม่มีแถวรายงาน
            # แล้ว run() เห็นว่าไม่เหลือเธรดที่ยังมีชีวิตก็เลิกลูป = engine จบแบบ "สำเร็จ"
            # ทั้งที่ไม่ได้บัญชีสักใบ (วัดจริง 2026-09-24: 16 เธรด quota ปิด -> 16 เธรดตาย
            # เงียบ 0 บัญชี exit code 0 เอาต์พุตทั้งรันมี 22 บรรทัด)
            #
            # จงใจไม่ดัก BaseException: Ctrl-C ต้องยังทะลุขึ้นไปได้ตามเดิม
            out = Outcome(dest="login failed", status="FAIL", error=str(err)[:200])

        # C2 (final review): a flow can replace session.src with a file IT produced (GenID
        # mints a brand-new account and writes its own .xml - flows._create_account,
        # bot/engine/flows.py:295) instead of the file this call started with. The file
        # that must move to out.dest is whichever one the flow actually ended up holding -
        # `src` (the queue.claim() result, "" for a self-supplied mode) is stale the moment
        # the flow reassigns it. For every non-self-supplied mode s.src never changes, so
        # this is a no-op there. Outcome still only NAMES a destination; the pool still does
        # the moving - only which path it moves has changed.
        moved_src = session.src

        moved = True
        move_err = ""
        if not moved_src:
            # A self-supplied mode (GenID) whose every mint attempt raised before a file
            # ever reached disk - nothing exists to move. The original
            # (startBotGenID_API_headless) took the same path on a total failure: log and
            # let the outer while True: mint a fresh attempt, no export call at all.
            pass
        else:
            try:
                if out.dest == "login failed":
                    self.queue.fail(moved_src, out.error or out.status)
                else:
                    self.queue.finish(moved_src, out.dest, out.name)
            except OSError as err:
                # Finding 1b (review round 1): this used to be logged and nothing else - the
                # account was then still counted and reported below as if the move above had
                # succeeded, while its file stayed in execute/ (queue.py's _close now retries
                # the move itself; this is what happens once those retries are also exhausted).
                # moved=False is what stops that: out.status/out.dest are still the flow's own,
                # genuine verdict (that work really happened), but nothing past this point may
                # claim the file reached out.dest, because it did not.
                moved = False
                move_err = str(err)
                self.reporter.note("could not move %s: %s" % (os.path.basename(moved_src), err))

        with self._lock:
            if not moved_src:
                # No file was ever produced (see above) - a real, counted failure, but not
                # "stuck": nothing is stranded in execute/ for recover() to pick up later.
                self._fail += 1
            elif not moved:
                # Neither done nor fail: out.dest was never reached, so counting this
                # under either would claim a destination folder holds a file that is
                # still sitting in execute/ - reproduced as the Critical finding this
                # comment marks (forced _close failure -> summary["done"] counted 3 while
                # output/ held 0). queue.recover() picks execute/'s stragglers back up as
                # retry candidates on the next run; `stuck` is how this run surfaces that
                # it happened instead of the account just quietly missing from every total.
                self._stuck += 1
            elif out.status == "OK":
                self._done += 1
            else:
                self._fail += 1
        self.reporter.account(status=out.status, rsn=session.rsn, lv=session.level,
                              ms=int((time.time() - started) * 1000),
                              dest=(out.dest if (moved and moved_src)
                                    else ("execute" if moved_src else "none")),
                              moved=moved, lane=lane.name, err=(out.error or "")[:120],
                              move_err=move_err[:120])

    def _spawn(self, lane, threads: list, count: int) -> None:
        for _ in range(count):
            self._seq += 1
            lane.enter()       # นับก่อน start: รอบ _fill ถัดไปต้องเห็นเธรดนี้แล้ว ไม่งั้นสปอว์นซ้ำ
            t = threading.Thread(target=self._worker, args=(lane,),
                                 name="%s-%d" % (lane.name, self._seq), daemon=True)
            t.start()
            threads.append(t)

    def _fill(self, threads: list) -> None:
        """เติมเธรดให้ทุก lane ที่ยังมีชีวิตถึงเป้า (lane.threads)

        ครั้งแรกคือการสปอว์นตอนเริ่ม หลังจากนั้นคือเธรดที่ autoscaler เพิ่มเป้า และ lane ที่ฟื้นจาก
        proxy ล่ม - ไม่เติมเมื่อสั่งหยุดแล้วหรือคิว input/ หมดแล้ว (เธรดใหม่จะ claim() ได้ None ทันที)
        """
        if self._stop.is_set() or self._exhausted:
            return
        for lane in self.pool.alive_lanes():
            missing = lane.threads - lane.running
            if missing > 0:
                self._spawn(lane, threads, missing)

    def _active_rows(self, now: float) -> list:
        """แถวของตาราง "บัญชีที่กำลังทำ" ใน GUI เก่าสุดก่อน - อ่าน step/detail ที่ flows เขียนผ่าน s.mark()"""
        with self._lock:
            items = sorted(self._active.items())[:ACTIVE_MAX]
        return [{"k": key,
                 "id": s.rsn or os.path.splitext(os.path.basename(s.src))[0],
                 "step": s.step, "detail": s.detail, "try": s.attempts,
                 "age": round(now - s.started, 1)}
                for key, s in items]

    def run(self) -> dict:
        started = time.time()
        stat_every = self._stat_every if self._stat_every is not None else STAT_EVERY
        poll_every = self._poll_every if self._poll_every is not None else POLL_EVERY
        drain_limit = self._drain_limit if self._drain_limit is not None else DRAIN_LIMIT
        lane_retry = self._lane_retry if self._lane_retry is not None else LANE_RETRY

        threads: list[threading.Thread] = []
        self._fill(threads)
        scaler = (autoscale.AutoScaler(self.pool.lanes, lane_max=self._lane_max,
                                       total_max=int(self.cfg.get("maxthreads") or 4096),
                                       now=started)
                  if self._auto else None)

        announced = set()
        last_stat = 0.0
        last_active = 0.0
        last_retry = time.time()
        down_since = None          # เวลาที่ proxy ล่มครบทุกตัว (None = ยังมี lane ที่ใช้ได้)
        done_hist = collections.deque([(started, 0)])

        # A do-while, deliberately not "while any(t.is_alive() for t in threads):" - every
        # lane can be dead before this loop ever runs (all proxies bad from the start, or
        # killed between construction and run()). threads is then empty and that
        # while-condition is False on the very first check, so the "every proxy is down"
        # note a few lines down would never fire. The checks below must run at least once
        # no matter what was or was not spawned.
        while True:
            for lane in self.pool.lanes:
                if not lane.alive and lane.name not in announced:
                    announced.add(lane.name)
                    self.reporter.lane(name=lane.name, state="dead",
                                       reason="connect failed 3x in a row")

            alive = self.pool.alive_lanes()
            if not alive and down_since is None:
                # ห้ามถอยไปยิงออก IP ของเครื่องผู้ใช้เอง (สิ่งที่ตั้ง proxy ไว้เลี่ยง) แต่ก็ไม่หยุดทั้งรัน
                # อีกแล้ว - เดิมหยุดตรงนี้ แล้วไอดีที่ค้างถูกตัดหมด ผู้ใช้ต้องการให้รันต่อเนื่อง proxy
                # ที่ล่มชั่วคราวกลับมาได้ รอ ALL_DOWN_RETRY แล้วลองทุกตัวใหม่ (lane "direct" ไม่มีวันตาย)
                down_since = time.time()
                self.reporter.note("every proxy is down - retrying in %ds" % ALL_DOWN_RETRY)
            elif alive:
                down_since = None

            # เธรดที่ retire/จบไปแล้วทิ้งออกจาก list - autoscaler สปอว์นใหม่ได้ตลอดรัน list จะโตไม่หยุด
            threads[:] = [t for t in threads if t.is_alive()]
            if not threads and (self._stop.is_set() or self._exhausted):
                # Nothing left to wait for: either the queue drained on its own, or (if
                # request_stop() was called) every in-flight account already finished.
                # Sitting out the rest of drain_limit here would only delay the final
                # numbers, never change them. No threads for any OTHER reason (every proxy
                # down, surplus threads retired) is not the end - _fill below respawns.
                break

            now = time.time()
            if ((down_since is not None and now - down_since >= ALL_DOWN_RETRY)
                    or now - last_retry >= lane_retry):
                last_retry = now
                down_since = None
                for lane in self.pool.lanes:
                    if not lane.alive:
                        lane.revive()
                        announced.discard(lane.name)
                        self.reporter.lane(name=lane.name, state="retry")

            if scaler is not None:
                scaler.tick(time.time())
            # เติมหลัง revive และหลัง autoscaler ขยับเป้า - รอบเดียวจบทั้งสองกรณี
            self._fill(threads)

            now = time.time()
            if now - last_active >= ACTIVE_EVERY:
                last_active = now
                self.reporter.active(rows=self._active_rows(now))

            if now - last_stat >= stat_every:
                last_stat = now
                with self._lock:
                    done, fail, stuck = self._done, self._fail, self._stuck
                elapsed = max(0.001, now - started)
                done_hist.append((now, done))
                while len(done_hist) > 2 and now - done_hist[1][0] >= RPM_WINDOW:
                    done_hist.popleft()
                t0, d0 = done_hist[0]
                self.reporter.stat(done=done, fail=fail, stuck=stuck,
                                   left=self.queue.remaining(),
                                   rate=round(done / elapsed, 2),
                                   rpm=round((done - d0) * 60.0 / max(0.001, now - t0), 1),
                                   threads=sum(x.running for x in self.pool.lanes),
                                   target=sum(x.threads for x in alive),
                                   auto=self._auto,
                                   scale=scaler.summary() if scaler is not None else "",
                                   lanes=len(alive))

            if (self._stop.is_set() and self._stop_at is not None
                    and time.time() - self._stop_at > drain_limit):
                # Some worker is still running well after the drain window - stop waiting
                # on it here so a hung account can't block this loop forever. The join
                # below shares the same window (anchored on _stop_at), it does not add another.
                break

            self._sleep(poll_every)

        # A shared deadline, not t.join(timeout=drain_limit) per thread in a plain loop:
        # with thousands of threads a naive per-thread timeout could in the worst case
        # (every single one hung) add up to threads*drain_limit before this returns. A live
        # thread makes join() return the moment it actually finishes, so this only matters
        # when something really is stuck - and then it bounds the whole wait to
        # drain_limit, not drain_limit times the pool size.
        # หลังกด Stop นับจากเวลาที่กด ไม่ใช่เริ่มนับใหม่ตรงนี้ - ลูปข้างบนรอไปแล้ว ไม่งั้น Stop ช้าเป็นสองเท่า
        start = self._stop_at if self._stop_at is not None else time.time()
        deadline = max(time.time(), start + drain_limit)
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.time()))

        if self._stop.is_set():
            # เธรดที่ยังหลับอยู่ (รอหัวใจเกิดใหม่, รอโควตา mint, ค้างใน HTTP) ไม่ได้รอให้ตื่น - โปรเซสจะออก
            # เลย คืนไฟล์ของมันเข้า input/ แทนมันตรงนี้ ถ้ามันตื่นทันก่อนโปรเซสปิด request ถัดไปของมัน
            # โยน EngineStopped แล้ว _abort เจอไฟล์ไม่อยู่แล้ว (OSError) ซึ่งจัดการไว้แล้ว
            with self._lock:
                stragglers = list(self._active.values())
            for s in stragglers:
                if s.src:
                    try:
                        self.queue.release(s.src)
                    except OSError:
                        pass            # recover() ตอนเริ่มรอบหน้าคืนให้แทน

        self.reporter.active(rows=[])     # ตารางใน GUI ว่าง - ไม่เหลือบัญชีที่กำลังทำ
        with self._lock:
            done, fail, stuck = self._done, self._fail, self._stuck
            # ตัดกลางทางแล้วคืน input/ + เธรดที่ยังหลับอยู่ตอนเลิกรอ (ไฟล์ค้าง execute/ คืนตอนเริ่มรอบหน้า)
            stopped = self._aborted + len(self._active)
        elapsed = max(0.001, time.time() - started)
        # "stuck" is a new key (global constraint: existing keys keep their meaning) -
        # done/fail must never count a file that never reached its destination folder,
        # so an account whose final move failed lands here instead of inflating either.
        summary = {"done": done, "fail": fail, "stuck": stuck, "left": self.queue.remaining(),
                   "seconds": round(elapsed, 1), "rate": round(done / elapsed, 2),
                   "stopped": stopped}
        self.reporter.stat(**dict(summary, final=True))
        return summary
