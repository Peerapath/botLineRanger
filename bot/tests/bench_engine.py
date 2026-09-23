"""วัดเพดาน *ฝั่งเรา* โดยไม่ยิงเซิร์ฟเวอร์เกมสักครั้ง

รัน: PYTHONUTF8=1 python bot/tests/bench_engine.py 500 128
ตัวเลขที่ได้ตอบคำถามว่า "ถ้าเกมเร็วเป็นอนันต์ เราจะระบายคิวได้เร็วแค่ไหน" - รอบที่
ของจริงช้ากว่านี้มากแปลว่าคอขวดอยู่ที่ปลายทาง ไม่ใช่ที่เรา
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
