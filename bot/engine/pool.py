"""thread pool ที่แทนฝูง 128 โปรเซส

เธรดหนึ่งตัว = หนึ่งบัญชีที่กำลังทำอยู่ เธรดทุกตัวของ lane เดียวกันใช้งบ request
ก้อนเดียวกัน และทุกตัวดึงงานจากคิวกลางตัวเดียว ไม่มีการแบ่งงานล่วงหน้า - แบ่งล่วงหน้า
แปลว่า worker ที่เจอบัญชีพังรัว ๆ จบก่อนแล้วนั่งว่างขณะที่ตัวอื่นยังมีคิวยาว
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))
import client_version  # noqa: E402
import rangers_api   # noqa: E402

from . import flows as flows_mod   # noqa: E402
from .proxy import ProxyPool       # noqa: E402
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
DRAIN_LIMIT = 60.0     # ให้เวลาบัญชีที่ค้างอยู่จบก่อนเลิก
LANE_RETRY = 300.0     # วินาที - proxy ที่ล่มชั่วคราวได้กลับมาเอง ไม่ต้องรีสตาร์ททั้ง engine

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
        lane_count = len(proxies) or 1     # ProxyPool falls back to one "direct" lane too
        if "threadcount" in cfg:
            threads_per = max(1, int(cfg["threadcount"]) // lane_count)
        else:
            threads_per = int(cfg.get("threadsperproxy") or 96)
        self.pool = ProxyPool(
            proxies,
            rps=float(cfg.get("apirps") or 90),
            threads_per=threads_per,
            max_threads=int(cfg.get("maxthreads") or 4096))
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
        self._version_stopped = False

    def request_stop(self) -> None:
        """หยุดรับงานใหม่ บัญชีที่ค้างอยู่ทำต่อจนจบ

        ตรงข้ามกับ terminate() ทันที ซึ่งทิ้งทั้งงานครึ่งทางและยอดสุดท้ายของมัน
        """
        with self._lock:
            if self._stop_at is None:
                self._stop_at = time.time()
        self._stop.set()

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
        while not self._stop.is_set():
            if not lane.alive:
                # proxy ของเธรดนี้ตาย - ออกไปเลย งานที่ยังไม่ถูก claim ยังอยู่ในคิวให้ lane
                # อื่นหยิบต่อ ไม่มีอะไรหาย
                return
            if self_supplied:
                src = ""       # _run_one's session starts empty; the flow fills s.src itself
            else:
                src = self.queue.claim()
                if src is None:
                    return
            self._run_one(lane, src)

    def _run_one(self, lane, src) -> None:
        started = time.time()
        session = AccountSession(src=src, lane=lane)
        try:
            out = self.flow(self.mode, session, self.cfg)
            if out.dest not in DESTS:
                # A flow bug returning a destination nobody wired up must not kill this
                # worker thread - that would strand this account's file at execute/ forever
                # (this run never retries a claimed file) and quietly shrink the pool by one
                # thread, indistinguishable from a lane dying for an unrelated reason.
                raise ValueError("flow returned an unknown destination %r" % (out.dest,))
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

    def _spawn(self, lane, threads: list, prefix: str = "") -> None:
        for i in range(lane.threads):
            t = threading.Thread(target=self._worker, args=(lane,),
                                 name="%s-%s%d" % (lane.name, prefix, i), daemon=True)
            t.start()
            threads.append(t)

    def run(self) -> dict:
        started = time.time()
        stat_every = self._stat_every if self._stat_every is not None else STAT_EVERY
        poll_every = self._poll_every if self._poll_every is not None else POLL_EVERY
        drain_limit = self._drain_limit if self._drain_limit is not None else DRAIN_LIMIT
        lane_retry = self._lane_retry if self._lane_retry is not None else LANE_RETRY

        threads: list[threading.Thread] = []
        for lane in self.pool.alive_lanes():
            self._spawn(lane, threads)

        announced = set()
        last_stat = 0.0
        last_retry = time.time()
        revivals = 0

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
            if not alive:
                # วิ่งต่อโดยไม่มี proxy เลย = ทุก request ออก IP ของเครื่องผู้ใช้เอง
                # ซึ่งเป็นสิ่งที่ผู้ใช้ตั้ง proxy ไว้เพื่อหลีกเลี่ยงพอดี หยุดดีกว่า
                self.reporter.note("every proxy is down - stopping")
                self.request_stop()
                break

            running = [t for t in threads if t.is_alive()]
            if not running:
                # Nothing left to wait for: either the queue drained on its own, or (if
                # request_stop() was called) every in-flight account already finished.
                # Sitting out the rest of drain_limit here would only delay the final
                # numbers, never change them.
                break

            if time.time() - last_retry >= lane_retry:
                last_retry = time.time()
                revivals += 1
                for lane in self.pool.lanes:
                    if not lane.alive:
                        lane.revive()
                        announced.discard(lane.name)
                        self.reporter.lane(name=lane.name, state="retry")
                        self._spawn(lane, threads, prefix="r%d-" % revivals)

            if time.time() - last_stat >= stat_every:
                last_stat = time.time()
                # Refreshed, not the running above: the lane-retry step just above may have
                # spawned more threads this same tick, and a stat line that undercounts
                # them for one cycle is a needless (if minor) lie to whoever is watching.
                running_now = [t for t in threads if t.is_alive()]
                with self._lock:
                    done, fail, stuck = self._done, self._fail, self._stuck
                elapsed = max(0.001, time.time() - started)
                self.reporter.stat(done=done, fail=fail, stuck=stuck,
                                   left=self.queue.remaining(),
                                   rate=round(done / elapsed, 2),
                                   threads=len(running_now), lanes=len(alive))

            if (self._stop.is_set() and self._stop_at is not None
                    and time.time() - self._stop_at > drain_limit):
                # Some worker is still running well after the drain window - stop waiting
                # on it here so a hung account can't block this loop forever. The join
                # below still gives every thread its own, separate drain_limit.
                break

            self._sleep(poll_every)

        # A shared deadline, not t.join(timeout=drain_limit) per thread in a plain loop:
        # with thousands of threads a naive per-thread timeout could in the worst case
        # (every single one hung) add up to threads*drain_limit before this returns. A live
        # thread makes join() return the moment it actually finishes, so this only matters
        # when something really is stuck - and then it bounds the whole wait to
        # drain_limit, not drain_limit times the pool size.
        deadline = time.time() + drain_limit
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.time()))

        with self._lock:
            done, fail, stuck = self._done, self._fail, self._stuck
        elapsed = max(0.001, time.time() - started)
        # "stuck" is a new key (global constraint: existing keys keep their meaning) -
        # done/fail must never count a file that never reached its destination folder,
        # so an account whose final move failed lands here instead of inflating either.
        summary = {"done": done, "fail": fail, "stuck": stuck, "left": self.queue.remaining(),
                   "seconds": round(elapsed, 1), "rate": round(done / elapsed, 2)}
        self.reporter.stat(**dict(summary, final=True))
        return summary
