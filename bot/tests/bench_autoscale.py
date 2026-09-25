"""จำลองโหลดด้วยเธรดจริง + TokenBucket จริง ดูว่า autoscaler ไปหยุดที่ไหน - ไม่ยิงเซิร์ฟเวอร์เกม

รัน: PYTHONUTF8=1 python bot/tests/bench_autoscale.py server|bucket|cpu|genid [วินาที]
- server: เริ่มที่งบ 80 req/s แต่ "เซิร์ฟเวอร์" รับได้ 150 req/s (เกินนั้นตอบ 429 แล้วเธรด backoff 0.5 วิ
          ยิงซ้ำ เหมือน rangers_api) - autoscaler ต้องขยายงบไปหาขอบของเซิร์ฟเวอร์เอง
- bucket: งบตายตัว 80 req/s (apirpsmax = apirps) ผนังคือถังของเราเอง
- cpu:    ไม่มีถัง ผนังคือ "เครื่อง" ที่รับงานพร้อมกันได้แค่ 24 ช่อง (แทน CPU/GIL หรือเซิร์ฟเวอร์ช้า)
- genid:  ผนังคือโควตา mint (ย่อเหลือ 2 ครั้ง/6 วิ ให้เห็นผลในนาทีเดียว)

แต่ละบัญชี = REQ request, แต่ละ request = lane.acquire() + หน่วง LAT วิ (แทน RTT + pacer ต่อบัญชี)
เธรดหนึ่งตัวจึงยิงได้สูงสุด 1/LAT req/s -> ถัง RPS อิ่มที่ ~RPS*LAT เธรด
"""
import io
import json
import os
import sys
import tempfile
import threading
import time

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT)
sys.path.insert(0, os.path.join(os.path.dirname(BOT), "tools"))

import engine.autoscale as autoscale  # noqa: E402
import engine.pool as pool_mod        # noqa: E402
from engine.pool import EnginePool    # noqa: E402
from engine.queue import WorkQueue    # noqa: E402
from engine.report import Reporter    # noqa: E402
from engine.session import Outcome    # noqa: E402

scenario = sys.argv[1]
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 60
pool_mod.STAT_EVERY = 3.0

RPS, LAT, REQ = 80, 0.4, 10          # งบ 80 อิ่มที่ ~32 เธรด
SERVER_RPS = 150.0
cfg = {"autothreads": True, "apirps": RPS}
if scenario == "bucket":
    cfg["apirpsmax"] = RPS
if scenario == "cpu":
    RPS = 0                         # ไม่มีถัง - ผนังคือ "เครื่อง" ที่รับงานพร้อมกันได้แค่ 24 ช่อง
    cfg["apirps"] = 0
cpu = threading.Semaphore(24)


class Server:
    """ขีดจำกัดต่อ IP ฝั่งเซิร์ฟเวอร์: ถังโทเคน SERVER_RPS แบบไม่รอ - หมดถัง = ตอบ 429"""

    def __init__(self, rate, burst=20):
        self.rate, self.burst = rate, burst
        self.tokens, self.stamp = float(burst), time.monotonic()
        self.lock = threading.Lock()

    def admit(self):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.stamp) * self.rate)
            self.stamp = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


server = Server(SERVER_RPS)

root = tempfile.mkdtemp()
for sub in ("input", "execute", "output", "backup", "login failed", "log"):
    os.makedirs(os.path.join(root, sub))
for i in range(20000):
    open(os.path.join(root, "input", "%05d.xml" % i), "w").close()
q = WorkQueue(root, os.path.join(root, "log", "run.jsonl"))

if scenario == "genid":
    import ratelimit
    ratelimit.AUTH_QUOTA = "2/6"     # ProxyLane อ่านค่านี้ตอนสร้าง - ต้องตั้งก่อน EnginePool
    # pool ด้านล่างรันในชื่อโหมด Login (GenID จริงต้องให้ flow เขียนไฟล์เอง) - เริ่มที่เลขของ GenID แทน
    autoscale.START_BY_MODE["ranger_api_Login"] = autoscale.start_for("ranger_api_GenID")


def flow(mode, s, c):
    if scenario == "genid":
        s.mark("mint")
        s.lane.auth_quota.acquire()
    for i in range(REQ):
        s.mark("stage", "%d/%d" % (i + 1, REQ))
        s.lane.acquire()
        if scenario == "server":
            while not server.admit():            # 429 -> rangers_api นับให้ lane แล้ว backoff ยิงซ้ำ
                s.lane.note_limited()
                time.sleep(0.5)
                s.lane.acquire()
        if scenario == "cpu":
            with cpu:
                time.sleep(LAT)
        else:
            time.sleep(LAT)
    return Outcome(dest="output")


class Tee(io.StringIO):
    def write(self, text):
        for line in text.splitlines():
            row = json.loads(line)
            if row["t"] == "stat":
                print("%5.0fs threads=%-4s target=%-4s scale=%-8s rps=%-4s req/s=%-6s rpm=%-7s done=%s" % (
                    time.time() - t0, row.get("threads"), row.get("target"), row.get("scale"),
                    row.get("rps"), row.get("reqs"), row.get("rpm"), row.get("done")), flush=True)
        return len(text)


pool = EnginePool("ranger_api_Login", cfg, q, [], Reporter(Tee()), flow=flow)
t0 = time.time()
threading.Timer(DURATION, pool.request_stop).start()
pool.run()
