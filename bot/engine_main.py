"""entry ของ engine - รันโหมด headless หนึ่งโหมดจนคิวหมด แล้วออก

ไม่ import GUI: ไฟล์นี้คือ __main__ ของโปรเซส engine การให้มันเป็น main.py แปลว่า
customtkinter ถูกโหลดในทุกโปรเซสที่สปอว์น
"""
import configparser
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

from engine import flows                     # noqa: E402
from engine.pool import EnginePool, STOP_FLAG # noqa: E402
from engine.queue import WorkQueue            # noqa: E402
from engine.report import Reporter            # noqa: E402

import ratelimit    # noqa: E402

BOOLS = ("gacharanger", "genidlevel3", "stopwhenfound")
INTS = ("leveltarget", "stageend", "rewardpasses", "threadsperproxy", "maxthreads",
        "gachacycles")


def load_config(path, rangers_path=None):
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    cfg = dict(parser["settings"]) if parser.has_section("settings") else {}
    for key in BOOLS:
        if key in cfg:
            cfg[key] = str(cfg[key]).strip().lower() in ("true", "1", "yes")
    for key in INTS:
        if key in cfg:
            try:
                cfg[key] = int(cfg[key])
            except ValueError:
                del cfg[key]        # ค่าเสีย = ใช้ค่าปริยาย ไม่ใช่ล้มทั้ง engine
    # รายชื่อ ranger เป้าหมาย - เคยเป็น global RANGERSCONFIG ใน botLineRanger ตอนนี้เดินทาง
    # ไปกับ cfg เพื่อให้ flows ไม่ต้องอ่านอะไรจากระดับโมดูล
    if rangers_path and os.path.isfile(rangers_path):
        rparser = configparser.ConfigParser()
        rparser.read(rangers_path, encoding="utf-8")
        # ค่าเป็น "ชื่อที่แสดง" ไม่ใช่ธงเปิด/ปิด - configRangers.ini เก็บ
        # unitCode -> ชื่อภาษาไทย และ pull_roster.unit_names เอาชื่อนั้นไปตั้งชื่อไฟล์ที่ export
        # ส่วนกาชาใช้มันเป็น truthiness ถ้าแปลงเป็น bool ทุกตัวจะกลายเป็น False
        # = ไม่มีเรนเจอร์เป้าหมายสักตัว และชื่อไฟล์จะว่างเปล่า
        cfg["_rangers_config"] = {
            k.lower(): str(v).strip()
            for section in rparser.sections()
            for k, v in rparser[section].items()}
    else:
        cfg["_rangers_config"] = {}
    return cfg


def main(argv):
    # stdout เป็นช่องรายงาน JSONL ข้อความไทยต้องไม่ตายที่ cp1252
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    mode = argv[1] if len(argv) > 1 else "ranger_api_Login"
    root = os.getcwd()
    cfg = load_config(os.path.join(root, "src", "config.ini"),
                      os.path.join(root, "src", "configRangers.ini"))

    # สองค่าที่ flows อ่านจาก cfg แต่ cfg เองสร้างเองไม่ได้ - ถ้าไม่ใส่ตรงนี้
    # flows จะทำงานต่อได้เงียบ ๆ โดยปิดความสามารถไปทีละอย่าง โดยเทสต์ยังเขียวหมด
    cfg["_account_claims"] = flows.AccountClaimRegistry()   # กันไฟล์สองใบของบัญชีเดียวสุ่มซ้ำ
    cfg["_execute_dir"] = os.path.join(root, "execute")     # GenID เขียนไฟล์ใหม่ลงที่เดียวกับ WorkQueue

    reporter = Reporter()

    queue = WorkQueue(root, os.path.join(root, "src", "log", "run.jsonl"))
    # Must run exactly once, here, before any worker thread ever calls queue.claim() -
    # see WorkQueue.recover()'s own docstring for why it refuses to run a second time.
    rescued = queue.recover()
    if rescued:
        reporter.note("recovered %d file(s) left in execute/ by an earlier run" % rescued)
    if queue.recover_failures:
        # These never made it back to input/ (e.g. a locked file) - queue.remaining()
        # will not count them and they will not be worked this run. Silence here is
        # exactly the "128 files quietly missing" failure queue.py was written to end.
        reporter.note("could not recover %d file(s) stuck in execute/ - check them by hand"
                      % queue.recover_failures)

    proxies = ratelimit.parse_proxies(cfg.get("apiproxies", ""))
    pool = EnginePool(mode, cfg, queue, proxies, reporter)

    stop_flag = os.path.join(root, "src", "log", STOP_FLAG)
    if os.path.exists(stop_flag):
        os.remove(stop_flag)

    def watch():
        while not os.path.exists(stop_flag):
            time.sleep(1.0)
        pool.request_stop()

    threading.Thread(target=watch, daemon=True, name="stop-flag-watch").start()

    try:
        pool.run()
    finally:
        queue.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
