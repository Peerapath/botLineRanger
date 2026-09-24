"""วัดเพดาน *ฝั่งเรา* โดยไม่ยิงเซิร์ฟเวอร์เกมสักครั้ง

รัน: PYTHONUTF8=1 python bot/tests/bench_engine.py 500 128
ตัวเลขที่ได้ตอบคำถามว่า "ถ้าเกมเร็วเป็นอนันต์ เราจะระบายคิวได้เร็วแค่ไหน" - รอบที่
ของจริงช้ากว่านี้มากแปลว่าคอขวดอยู่ที่ปลายทาง ไม่ใช่ที่เรา

What this measures: EnginePool.run() end to end, with the network replaced by a flat
time.sleep(LATENCY) per account - an upper bound on how fast this process's own
queue/thread/journal machinery can drain a full queue, with the one part nobody here
controls (the game server) removed from the picture entirely.

Correction (review round 1, 2026-09-24): the first report measured ~150-165 accounts/s on
this machine (PYTHONUTF8=1 python bot/tests/bench_engine.py 2000 256 -> 164.8 accounts/s
one run, 149.8 accounts/s on a repeat - see task-9-report.md's isolation table; flat
regardless of thread count from 16 threads up) and then judged that ceiling irrelevant in
production by arguing from "128 concurrent accounts". That argument does not hold: 128 was
the OLD process-per-worker architecture's RAM ceiling (5.5 GB for 128 OS processes - see
AccountSession's own docstring), the exact limit this thread-pool rewrite exists to remove,
so it cannot be used to size the new one.

The number that actually matters is the plan's per-IP target: a 90 req/s per-proxy budget
divided by ~16 requests/account is 5.6 accounts/s per proxy (see
.superpowers/sdd/review-534a348..9a4b8d4.diff). Dividing this bench's ~150-165 accounts/s
ceiling by that 5.6 accounts/s/proxy gives the proxy count at which this process's own
queue - not the game server, not the network - becomes the binding constraint: roughly 27
to 29 proxies. That falls inside the 5-to-50 proxies the user intends to run, not past the
edge of it, so this ceiling is a real planning input, not a curiosity to footnote.

Caveat: this ceiling may be specific to this dev box. task-9-report.md's isolation
experiments narrowed it to the OS/filesystem layer - raw os.replace() calls with zero
project code involved reproduce the same order-of-magnitude ceiling - and named Windows
Defender real-time scanning as the leading suspect, unconfirmed (a read-only
Get-MpComputerStatus check hung and never returned output). Re-measure this bench on the
actual deployment host before sizing a 50-proxy plan on the strength of the ~27-29
crossover computed above.

Correction (final whole-branch review, I3, re-verified 2026-09-24): the "Windows itself"
diagnosis above was wrong, and the fix is three lines, not a redesign. The actual cause was
bot/engine/queue.py's own lock discipline: claim() (input/ -> execute/) held self._lock for
its rename, but _close() (execute/ -> output/backup/login failed) did not - two directions
of UNSYNCHRONIZED concurrent renames landing on the SAME execute/ directory (every claim()
writes into it, every _close() reads out of it), fighting each other for that directory's
metadata lock rather than "os.replace() itself" being slow. Moving _close()'s rename under
the same lock claim() already uses fixed it. Re-measured independently with this same
script (2000 accounts, 256 threads), same correctness at every point (done=2000, 2000 files
in output/, 0 stuck):

  as shipped (lock outside _close):              ~150-210 accounts/s
  _close() rename under the same lock (the fix):  ~1,680-1,750 accounts/s
  fake queue touching no files (same LATENCY):    ~4,760 accounts/s

(The review's own run measured 147.5 / 1,193 / 1,236 respectively - the exact numbers are
machine-specific per the caveat above, but the ~10x effect of the lock fix and "fixed
nearly reaches the no-file-I/O ceiling" shape reproduce on a different run of the same
machine.) At the 5.6 accounts/s/proxy target this moves the crossover from ~27-29 proxies
to roughly 210-310, well outside the 5-to-50 this design is sized for - no architecture
change is needed.
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine.pool import EnginePool       # noqa: E402
from engine.queue import WorkQueue       # noqa: E402
from engine.report import Reporter       # noqa: E402
from engine.session import Outcome       # noqa: E402

LATENCY = 0.05      # วินาทีต่อบัญชี แทนเวลารอเน็ต


def main(count, threads):
    root = tempfile.mkdtemp(prefix="bench-")
    try:
        for sub in ("input", "execute", "output", "backup", "login failed", "log"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        for i in range(count):
            with open(os.path.join(root, "input", "%06d.xml" % i), "w", encoding="utf-8") as fh:
                fh.write("<map/>")
        queue = WorkQueue(root, os.path.join(root, "log", "run.jsonl"))

        def flow(mode, s, cfg):
            time.sleep(LATENCY)
            return Outcome(dest="output", name="")

        started = time.time()
        summary = EnginePool("ranger_api_Login", {"threadsperproxy": threads},
                             queue, [], Reporter(io.StringIO()), flow=flow).run()
        queue.close()
        elapsed = time.time() - started
        print("%d accounts - %d threads - %.1fs - %.1f accounts/s (ideal %.1f)"
              % (count, threads, elapsed, count / elapsed, threads / LATENCY))
        return summary
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500,
         int(sys.argv[2]) if len(sys.argv) > 2 else 128)
