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

# Round 2 change 1 (2026-09-24), CORRECTING I1 above: I1's fix branched on mode - GenID
# resolved the g-prefixed keys, everything else resolved r - on the theory that the old
# bot split gacha behaviour by mode too. That theory is what is being corrected here, so
# it was re-verified against af264b0:bot/botLineRanger.py rather than trusted a second
# time: ALL FIVE call sites of apiGachaWithTicket (lines 6995, 7118, 8052, 8366, and 8527
# - the last one inside startBotGenID_API_headless, GenID's own original) pass only
# gacharangergroup=GACHARANGERGROUP and gacha_cycles=RGACHACYCLES, taking
# apiGachaWithTicket's own defaults (stop_when_found=True, gacha_mode="NumberOfCycles",
# use_ruby=False - its signature at :6777-6778) for everything else.
# GSTOPWHENFOUND/GUSE200RUBY/GGACHAMODE/GGACHACYCLES are read NOWHERE in that file:
# defined at 127-130, loaded from config.ini at 368-371, never referenced by any call
# site. Routing GenID to the g-prefixed keys was therefore an unannounced behaviour
# change, and it mattered: this repo's own bot/src/config.ini has ggachamode =
# LimitOfRuby (a mode tools/gacha.py does not implement - see draw_with_ticket's own
# _KNOWN_GACHA_MODES fallback) and guse200ruby = True, so GenID would have drawn until
# tickets AND ruby were both gone, with rgachacycles's conservative "1" silently unused.
#
# Nothing regresses by no longer reading the g-prefixed keys: the GUI's GenID gacha tab
# has never driven them either, in the old bot or this one. bot/main.py's
# create_playmode_frame builds self.rgacha_cycles - bound to "rgachacycles", the SAME
# attribute and the SAME config key - under BOTH the Login/Level3 branch (:777-787) and
# the GenID branch (:833-843); self.ggacha_cycles / self.guse_200ruby / self.ggacha_mode_var
# / self.gstop_when_found are referenced by save_config's writes (:601-680) but no
# create_playmode_frame branch ever instantiates them, so every one of those writes
# silently AttributeErrors and is swallowed (bare `except Exception: pass`). The
# g-prefixed keys in config.ini can only ever have been set by hand-editing the file.
_GACHA_KEY_ALIASES = {
    "stopwhenfound": "rstopwhenfound",
    "gachamode": "rgachamode",
    "gachacycles": "rgachacycles",
    "useruby": "ruseruby",
}


def _resolve_mode_aliases(cfg, mode):
    """Copy the r-prefixed raw string into cfg's generic key name, so the BOOLS/INTS loop
    right after this call coerces it exactly like every other setting - one coercion
    path, not a mode-dependent one. A config missing the per-mode split (default_config/
    config.ini's own shape: only the generic key, no prefix) is untouched here, so its
    generic value survives as the fallback I1 asked for and Round 2 change 1 keeps.

    `mode` is accepted, not read: load_config()'s callers (main() below and this file's
    own tests) already pass it, and every mode now resolves the same keys, so there is
    nothing left for it to select.
    """
    for generic, specific in _GACHA_KEY_ALIASES.items():
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
    # I1/Round 2 change 1: resolve the r-prefixed gacha keys into their generic names
    # BEFORE the BOOLS/INTS loop below, so the resolved value is coerced through the exact
    # same path as every other setting instead of a second, parallel one.
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
