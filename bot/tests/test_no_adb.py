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
import ast
import builtins
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
        # Fix round 2: apiEnterStage/apiUpgradeStatus/apiUpgradeMachine/apiReadTeamGroup/
        # apiSaveTeamGroup/apiUnitSpecs called getLFAC() - deleted above, in the very
        # same gone_names list this test already checked - on every real invocation, a
        # guaranteed NameError the old hasattr-only check couldn't see. setUpTeamA1
        # called getTeanInfo() (also already deleted) the same way. apiSaveTeam/
        # apiReadTeam/apiUpgradeEnergy/stageCodeOf/_apiBalance/_balanceDelta/
        # _loadUnitSpecs/_saveUnitSpecs/TeamUnitRejected/MACHINE_UPGRADE_TYPES/
        # NONDEPLOYABLENAMES/TEAMGROUPREPFIELD/UNITSPECCACHE/UNITSPECPATH/
        # UNITSPECLOADED only existed to call, or be called by, that broken cluster -
        # re-grepped bot/ + tools/ for each name before deleting any of it; zero live
        # callers anywhere outside this file's own (wrong) kept_names below.
        "apiEnterStage", "apiUpgradeStatus", "apiUpgradeMachine", "apiUpgradeEnergy",
        "apiReadTeamGroup", "apiReadTeam", "apiSaveTeamGroup", "apiSaveTeam",
        "apiUnitSpecs", "setUpTeamA1", "stageCodeOf", "_apiBalance", "_balanceDelta",
        "TeamUnitRejected", "MACHINE_UPGRADE_TYPES", "NONDEPLOYABLENAMES",
        "TEAMGROUPREPFIELD", "UNITSPECCACHE", "UNITSPECPATH", "UNITSPECLOADED",
        "_loadUnitSpecs", "_saveUnitSpecs",
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

    # What main.py's surviving (non-ADB) code actually still calls - deleting any of
    # these would silently break a live caller the way the sibling project's
    # folder-helper deletion did. This used to also pin a "preserved pure-API layer"
    # (apiEnterStage/apiSaveTeam/apiUnitSpecs) as untouched; Fix round 2 found that
    # framing false - every one of those crashed on first call - and deleted the
    # whole cluster instead (see the Fix round 2 note in gone_names above).
    kept_names = (
        "log", "reloginFromInput", "getGachaBanner",       # main.py's refresh_gacha_banners
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


# ============================================================================
# Static reachability INSIDE function bodies: every test above proves a name
# EXISTS on the module (hasattr) or that the module/main.py import without
# raising - neither proves a function's own BODY still resolves every name it
# loads. That gap is exactly how Fix round 2's seven getLFAC()/getTeanInfo()
# calls survived 301 green tests: the functions themselves were real, intact
# objects - only calling them hit a NameError, and nothing here ever called
# them. This walks botLineRanger.py's AST (no import, no execution - it must
# catch the bug even if nothing has ever exercised the broken path) and, for
# every function/method in it, checks that each name it loads resolves to a
# builtin, a module-level name, something bound in an enclosing function (a
# closure), or something bound inside that function itself - a parameter, a
# local assignment, a lazy `import` (this file imports every tools/ module
# lazily, inside whichever function uses it), a `for`/`with`/`except ... as`
# target, or a comprehension/lambda parameter.
# ============================================================================

_BUILTIN_NAMES = frozenset(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__class__",
}


def _param_names(args):
    """Every name an `ast.arguments` node binds as a parameter. Defaults and
    annotations run in the ENCLOSING scope at def-time, not this function's
    own body, so they are deliberately not scanned here."""
    names = {a.arg for a in (args.posonlyargs + args.args + args.kwonlyargs)}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _scan_scope(node_or_stmts):
    """Collect (bound, loaded, child_funcs) for one scope - a module body, a
    function body (a list of statements), or a lambda body (a single
    expression). `bound` is every name this scope binds directly; `loaded` is
    every name it reads; `child_funcs` is the FunctionDef/AsyncFunctionDef
    nodes it owns (methods included, via the ClassDef branch below), each a
    separate scope the caller must recurse into on its own.

    Recurses through plain control flow (if/for/while/try/with/...) because
    those share their enclosing scope, but stops at a nested def/class/lambda
    - each opens its own scope. A bare `ast.Name` already carries Store vs.
    Load in `.ctx`, and Python threads that through tuple/list/starred
    unpacking and comprehension/for/with targets automatically, so generic
    recursion plus the one Name check below is enough for all of those; the
    remaining special cases exist only because Import/Global/Nonlocal/
    ExceptHandler bind identifiers stored as plain strings, not Name nodes,
    so generic recursion would never see them as bindings at all.
    """
    bound, loaded, child_funcs = set(), set(), []

    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            child_funcs.append(node)
            return
        if isinstance(node, ast.ClassDef):
            bound.add(node.name)
            for child in list(node.bases) + [kw.value for kw in node.keywords]:
                visit(child)
            # A class body sees its enclosing scope (like a function would),
            # but is NOT part of the closure chain for its own methods - fold
            # its non-self-bound loads into THIS scope, and hand its methods
            # up as if they were defined directly in this scope instead.
            cls_bound, cls_loaded, cls_children = _scan_scope(node.body)
            loaded.update(cls_loaded - cls_bound)
            child_funcs.extend(cls_children)
            return
        if isinstance(node, ast.Lambda):
            lam_bound, lam_loaded, _lam_children = _scan_scope(node.body)
            lam_bound |= _param_names(node.args)
            loaded.update(lam_loaded - lam_bound)
            return
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else bound).add(node.id)
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    bound.add(alias.asname or alias.name.split(".")[0])
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            # global reaches module scope (module_bound already covers every
            # name declared this way in this file); nonlocal is only legal
            # Python when CPython's own compiler can already see a binding in
            # an enclosing function - the plain `import botLineRanger` in the
            # test above already exercises that check - so trusting it here
            # adds no blind spot for the bug class this test targets.
            bound.update(node.names)
            return
        if isinstance(node, ast.ExceptHandler):
            if node.name:
                bound.add(node.name)
            for child in ast.iter_child_nodes(node):
                visit(child)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    if isinstance(node_or_stmts, list):
        for stmt in node_or_stmts:
            visit(stmt)
    else:
        visit(node_or_stmts)
    return bound, loaded, child_funcs


def _collect_unresolved(func, ancestor_bound_chain, module_bound, violations):
    """Recurse over `func` and everything nested inside it, appending a
    "name (line N): bad, names" entry to `violations` for every function or
    method whose body loads a name nothing in scope binds."""
    own_bound, own_loaded, children = _scan_scope(func.body)
    own_bound |= _param_names(func.args)

    allowed = set(_BUILTIN_NAMES) | module_bound | own_bound
    for ancestor in ancestor_bound_chain:
        allowed |= ancestor

    bad = sorted(own_loaded - allowed)
    if bad:
        violations.append("%s (line %d): %s" % (func.name, func.lineno, ", ".join(bad)))

    for child in children:
        _collect_unresolved(child, ancestor_bound_chain + [own_bound], module_bound, violations)


def test_botlineranger_function_bodies_only_load_resolvable_names():
    """Would have failed on the pre-fix file: apiEnterStage/apiUpgradeStatus/
    apiUpgradeMachine/apiReadTeamGroup/apiSaveTeamGroup/apiUnitSpecs each
    loaded getLFAC, and setUpTeamA1 loaded getTeanInfo - neither bound
    anywhere (no def, import or assignment) after Task 11 deleted them. The
    hasattr-based test above only proves the FUNCTION objects exist; this is
    the check that would have caught all seven guaranteed NameErrors without
    anyone having to call them first.
    """
    path = os.path.join(BOT, "botLineRanger.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=path)

    module_bound, _module_loaded, module_children = _scan_scope(tree.body)

    violations = []
    for func in module_children:
        _collect_unresolved(func, [], module_bound, violations)

    assert violations == [], violations
