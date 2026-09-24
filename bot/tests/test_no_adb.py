"""ยามกันไม่ให้ ADB คืนชีพ

บั๊กที่กันไว้: การลบของที่ตายแล้วโดยไม่ไล่หาผู้เรียก - โปรเจกต์พี่น้องเคยลบตัวสร้าง
โฟลเดอร์ทิ้งโดยที่ยังมีปุ่ม 15 ปุ่มเรียกมันอยู่ ทั้งคู่พังเงียบ

Text-scanning for absence (the three tests below the marker) proves the banned words
are gone from source. It proves nothing about whether the functions/methods that USED
to call them still work - a caller left calling a name that no longer exists would pass
every one of those three tests while being completely broken. The tests after the
marker close that gap: they actually import botLineRanger.py and main.py (not grep
their text) and check the live object graph - hasattr on a real imported module means
the interpreter agrees, not that a regex didn't happen to match. If Task 11 had deleted
a function some other live function still called, `import botLineRanger` itself would
already be fine (Python doesn't check names inside a function body until it runs), but
the surviving caller would carry a dangling reference forever - so these tests also
pin the specific names that must still resolve (the ones Task 11's brief says the
engine/GUI still needs) alongside the ones that must not.
"""
import os
import re

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("ADB.py", "nemu_capture.py", "bot_worker.py")
BANNED = ("ppadb", "uiautomator2", "adbutils", "cv2", "pytesseract",
          "pure-python-adb", "opencv")


def sources():
    for root, dirs, files in os.walk(BOT):
        dirs[:] = [d for d in dirs
                   if d not in ("build", "dist", "dist_pyarmor", "Version", "__pycache__",
                                "src", "input", "output", "backup", "execute", "tests")]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_the_adb_modules_are_gone():
    for name in GONE:
        assert not os.path.exists(os.path.join(BOT, name)), name


def test_nothing_imports_a_device_library_any_more():
    """ยืนยันตัวตนของไฟล์ที่ผิด ไม่ใช่แค่นับ - รายงานจะได้บอกว่าไปแก้ที่ไหน"""
    guilty = []
    for path in sources():
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for word in BANNED:
            if re.search(r"^\s*(import|from)\s+%s\b" % re.escape(word.replace("-", "_")),
                         text, re.M):
                guilty.append("%s imports %s" % (os.path.relpath(path, BOT), word))
    assert guilty == [], guilty


def test_requirements_no_longer_pull_the_device_stack():
    with open(os.path.join(BOT, "requirements.txt"), encoding="utf-8") as fh:
        text = fh.read().lower()
    for word in BANNED:
        assert word not in text, word


# ============================================================================
# Reachability, not absence: import the real modules and check the live
# object graph - see module docstring for why the tests above aren't enough.
# ============================================================================

def _import_bot_module(name):
    """import <name> with bot/ on sys.path, exactly like test_main_engine_wiring.py
    does for `main` - proven to work in this test environment already. A plain
    ImportError here (not caught) is itself the test failing loudly, which is the
    point: a dangling module-level reference (e.g. `client = AdbClient(...)` after
    the import of AdbClient was deleted) blows up at import time, not at call time.
    """
    import sys
    if BOT not in sys.path:
        sys.path.insert(0, BOT)
    import importlib
    return importlib.import_module(name)


def test_botlineranger_still_imports_and_the_adb_vision_ocr_surface_is_gone():
    """The module-level ADB wiring (AdbClient import, `client = AdbClient(...)`, the
    cv2/pytesseract/uiautomator2/nemu_capture lazy bindings) executes at import time,
    not call time - if any of it survived half-deleted, this import itself would raise
    NameError before a single test assertion runs.
    """
    botLineRanger = _import_bot_module("botLineRanger")

    # Device/vision/OCR primitives and every orchestrator built only to drive them
    # (tutorial*/playMainStage*/gacha-via-OCR/the special-quest farm/the old hybrid
    # startBot*_API entry points) - a representative sample, not the full ~120.
    gone_names = (
        "setUp", "tap", "click", "exists", "find", "wait", "waitLoading", "goTo",
        "goToHome", "textOCR", "numberOCR", "charOCR", "colorMatch", "pressBack",
        "playMainStage", "playMainStageAtNumber", "tutorial2", "tutorialInHomeScreen",
        "openLineRangers", "autoSetUp", "force_stop_LINE_Rangers", "getGameID",
        "getLFAC", "randomGachaRanger", "randomGachaGear", "randomGachaEvent",
        "closePopUp", "startBotGenID_API", "startBotLogin_API", "playStageHybrid",
        "startBotClearStage150", "clearSpecialQuest",
        # Step 4b: moved verbatim to tools/gacha.py + tools/pull_roster.py - the
        # originals were dead weight once the engine switched to the tools/ copies.
        "apiGachaWithTicket", "_gachaGroupPull", "matchGachaName", "add_ranger_name",
        "getTeanInfo", "getRubyAndTicket", "getAccoutInfo", "currentLevel",
        "apiGetPlayer",
        # Fix round 1: the *_API_headless entry-point family and the pure-API/file-
        # management cluster that only they reached - the Task 11 report found these
        # unreachable and flagged them as a concern instead of deleting them; finished
        # here after re-confirming (fresh grep) that no live caller was ever added.
        "setUpHeadless", "_loadBotConfig",
        "startBotCheckGameInfo_API", "startBotLogin_API_headless",
        "startBotStage_API_headless", "startBotLevel3_API_headless",
        "startBotGenID_API_headless",
        "apiAcceptAllRewards", "apiForceStage", "apiLevelUpByStage1",
        "_headlessCreateAccount", "logSession", "printRosterSummary",
        "getLFACHeadless", "getLFACFromFile", "_importApiTools", "_prefValue",
        "updateFileInExecute", "updateFileWithStage", "exportFileFromExecuteToBackup",
        "exportFileFromExecuteToInput", "exportFileFromExecuteToOutput",
        "removeFileInExecute", "exportFileFromExecuteToLoginFailed",
        "reImportFileInExecute", "_claimInputFile", "_claimAccountThisRun",
        "_releaseAccountThisRun", "importFileFromInputToExecute", "in_current_file",
        "removeAllFiles",
        # Same round: classes/module state a call-site grep can't see (nothing ever
        # "calls" a class or a bare variable) - found by re-deriving reachability
        # instead of trusting absence of a call site.
        "Color", "Location", "Region", "extract_clean_text", "fuzzy_match",
        "slotItem1", "slotItem2", "slotItem3", "slotItem4", "slotItem5",
        "current_screen", "current_screen_gray", "_last_capture_time", "_template_cache",
        "usenemu", "_nemu", "_nemu_next_try", "_nemu_black_streak",
        "NEMU_RETRY_SEC", "NEMU_BLACK_STREAK", "NEMU_MIN_INTERVAL",
        "cooldowncapturescreen", "timeoutopengame", "current_use_ruby",
    )
    still_there = [n for n in gone_names if hasattr(botLineRanger, n)]
    assert still_there == [], still_there

    # The pytesseract/cv2/nemu_capture/uiautomator2 lazy-load proxies themselves,
    # and the _LazyModule machinery that only existed to serve them.
    assert not hasattr(botLineRanger, "_LazyModule")
    assert not hasattr(botLineRanger, "cv2")
    assert not hasattr(botLineRanger, "pytesseract")
    assert not hasattr(botLineRanger, "nemu_capture")
    assert not hasattr(botLineRanger, "u2")

    # What main.py's surviving (non-ADB) code and the preserved pure-API layer
    # actually still call - deleting any of these would silently break a live
    # caller the way the sibling project's folder-helper deletion did.
    kept_names = (
        "log", "reloginFromInput", "getGachaBanner",       # main.py's refresh_gacha_banners
        "apiEnterStage", "apiSaveTeam", "apiUnitSpecs",     # pure-API layer, untouched
    )
    missing = [n for n in kept_names if not hasattr(botLineRanger, n)]
    assert missing == [], missing


def test_main_gui_still_imports_and_the_adb_device_flow_is_gone():
    """main.py's `from ADB import *` and the whole per-device Start/Stop/Import/Export
    UI it fed (add_emulator, start_bot, importID, exportID, run_bot, ...) - gone. The
    engine-process half Task 10 built (_start_workers/_stop_workers/_spawn_engine) and
    stop_bot_processes's ADB-per-device kill loop (kept deliberately - see its own
    docstring and test_main_engine_wiring.py's force=True test) must still be there.
    """
    main = _import_bot_module("main")

    gone_methods = (
        "start_adb", "kill_server_adb", "_update_emulator_ui", "add_emulator",
        "handle_menu_choice", "importID", "exportID", "open_screen_file",
        "start_bot", "start_auto_setup", "monitor_bot", "toggle_select",
    )
    still_there = [n for n in gone_methods if hasattr(main.EmulatorManager, n)]
    assert still_there == [], still_there

    gone_module_functions = ("run_bot", "run_auto_setup_with_log", "note_file_in_folder")
    still_there_module = [n for n in gone_module_functions if hasattr(main, n)]
    assert still_there_module == [], still_there_module

    kept_methods = (
        "_start_workers", "_stop_workers", "_spawn_engine", "_build_thread_panel",
        "stop_bot_processes",          # still hard-kills self.bot_processes - see its docstring
        "start_bot_for_selected", "stop_bot_for_selected", "render_left_panel",
        "_isHeadlessThreadMode",
    )
    missing = [n for n in kept_methods if not hasattr(main.EmulatorManager, n)]
    assert missing == [], missing
