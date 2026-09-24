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

BOOLS = ("gacharanger", "genidlevel3", "stopwhenfound", "useruby")
INTS = ("leveltarget", "stageend", "rewardpasses", "threadsperproxy", "maxthreads",
        "gachacycles", "threadcount")

# C4 (final review): "useruby" used to be missing from BOOLS. cfg["useruby"] then stayed the
# raw ini STRING "False" all the way to flows.py's bool(cfg.get("useruby", False)) -  and
# bool("False") is True in Python (any non-empty string is truthy). default_config/
# config.ini ships useruby = False, so a fresh install drew gacha with ruby too, on every
# account, while the file said ruby was off. Audited every other key the engine coerces at
# the same time: everything flows.py reads with bool(cfg.get(...)) is in BOOLS, everything
# it reads with int(cfg.get(...)) is in INTS (gachamode is a string enum - "giveItAll" /
# "NumberOfCycles" / "LimitOfRuby" - and needs neither).

# I1 (final review): the engine read stopwhenfound/gachacycles/gachamode/useruby - names
# neither the GUI nor the user's real config ever writes. The GUI still keeps two
# independent copies of every gacha setting - Login-family ("r") vs GenID ("g") - because a
# user commonly wants Login conservative (NumberOfCycles) while GenID drains ruby on every
# freshly minted account (LimitOfRuby): bot/src/config.ini has only
# rstopwhenfound/gstopwhenfound, rgachamode/ggachamode, rgachacycles/ggachacycles,
# ruseruby/guse200ruby ("useruby"'s g-side key is spelled guse200ruby, not guseruby - kept
# exactly as the user's file has it: global constraint 4 forbids renaming a key that
# already exists there). The old reader picked the pair by which startBot*_API_headless
# function was running (af264b0:bot/botLineRanger.py:353-356,368-371); this does the same
# by mode. Login and Level3 both read the "r" globals in the original
# (startBotLevel3_API_headless, af264b0:bot/botLineRanger.py:8366, reads RGACHACYCLES, not
# a level3-specific pair); Stage reads neither - it never gachas at all (flows.run_stage).
_MODE_KEY_ALIASES = {
    "stopwhenfound": {"r": "rstopwhenfound", "g": "gstopwhenfound"},
    "gachamode": {"r": "rgachamode", "g": "ggachamode"},
    "gachacycles": {"r": "rgachacycles", "g": "ggachacycles"},
    "useruby": {"r": "ruseruby", "g": "guse200ruby"},
}
_GENID_MODES = ("ranger_api_GenID",)


def _resolve_mode_aliases(cfg, mode):
    """Copy the mode-appropriate r/g-prefixed raw string into cfg's generic key name, so the
    BOOLS/INTS loop right after this call coerces it exactly like every other setting -
    one coercion path, not two. A config missing the per-mode split (default_config/
    config.ini's own shape: only the generic key, no prefix) is untouched here, so its
    generic value survives as the fallback I1 asks for."""
    prefix = "g" if mode in _GENID_MODES else "r"
    for generic, per_mode in _MODE_KEY_ALIASES.items():
        specific = per_mode[prefix]
        if specific in cfg:
            cfg[generic] = cfg[specific]


def load_config(path, rangers_path=None, mode=None):
    # strict=False on every parser here, deliberately. These are files the user edits by
    # hand, and a repeated key is the normal way that goes wrong - bot/src/configRangers.ini
    # has u1206e-moon twice at line 137 right now. A strict parser answers that with
    # DuplicateOptionError, which would take the whole engine down at startup before a
    # single account was touched, over a duplicated ranger name. The bot this replaces hit
    # exactly that and carried a comment saying so; losing it here reintroduced the bug.
    # strict=False keeps the last value, which is what a user retyping a line means.
    parser = configparser.ConfigParser(strict=False)
    parser.read(path, encoding="utf-8")
    cfg = dict(parser["settings"]) if parser.has_section("settings") else {}
    # I1: resolve the r/g-prefixed pair for this mode into the generic key BEFORE the
    # BOOLS/INTS loop below, so the resolved value is coerced through the exact same path
    # as every other setting instead of a second, parallel one.
    _resolve_mode_aliases(cfg, mode)
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
        rparser = configparser.ConfigParser(strict=False)
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
                      os.path.join(root, "src", "configRangers.ini"), mode)

    # สองค่าที่ flows อ่านจาก cfg แต่ cfg เองสร้างเองไม่ได้ - ถ้าไม่ใส่ตรงนี้
    # flows จะทำงานต่อได้เงียบ ๆ โดยปิดความสามารถไปทีละอย่าง โดยเทสต์ยังเขียวหมด
    cfg["_account_claims"] = flows.AccountClaimRegistry()   # กันไฟล์สองใบของบัญชีเดียวสุ่มซ้ำ
    # Finding 2 (Task 9, review round 1): until this fix, flows._create_account never actually read
    # this key - it used its own module-level EXECUTE_DIR instead - so the comment above
    # ("two values that flows reads from cfg") was only true of _account_claims. flows now
    # reads cfg.get("_execute_dir", EXECUTE_DIR), so this line is genuinely load-bearing:
    # it keeps GenID's freshly minted files landing in the same root/execute that
    # WorkQueue(root=...) below also uses, not wherever os.getcwd() happened to be when
    # flows.py was imported.
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
