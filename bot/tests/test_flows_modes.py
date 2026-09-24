"""flow Level3 / GenID / Stage: เหมือน test_flows_login.py แต่คนละโหมด

โครง stub/make/CFG/Lane ลอกมาจาก test_flows_login.py ตามที่ brief สั่ง ("ลอกโครง stub จาก
test_flows_login.py") ยกเว้นจุดเดียวที่แก้: stub()'s ของเดิมรับพารามิเตอร์ level= มา แต่ไม่เคย
setattr(s, "level", ...) จริง - มันยัด level ไว้ใน home dict ("player": {"level": level}) เฉย ๆ
ซึ่ง _fetch_home ตัวจริงจะอ่านออกมาใส่ s.level แต่ _fetch_home ที่ stub() เขียนแทนไม่ทำแบบนั้น
(แค่ setattr(s, "home", ...) เท่านั้น) ทดสอบ Login ของเดิมไม่มีอะไรตัดสินใจจาก s.level เลยจึงไม่
เคยเจอบั๊กนี้ แต่ Level3/GenID ทั้งคู่ตัดสินใจจาก s.level ตรง ๆ (if s.level < target) - ถ้าไม่แก้
stub(monkeypatch, calls, level=3) จะไม่ทำให้บัญชีดูเหมือนถึงเป้าเลย (s.level จะค้างที่ 0 ซึ่งเป็น
ค่าเริ่มต้นของ AccountSession เสมอ) แล้ว test_level3_skips_the_stage_replay_when_the_account_is_already_there
จะพังแม้โค้ดจริงถูกต้องแล้วก็ตาม - ดูรายละเอียดเต็มใน task-8-report.md
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine import flows                       # noqa: E402
from engine.session import AccountSession      # noqa: E402


class Lane:
    name, parts = "L", None
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


CFG = {"gacharanger": False, "rewardpasses": 3, "gachacycles": 1}


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """เหมือน test_flows_login.py: กัน retry ของ Finding 1 ไม่ให้เทสต์ตัวไหนต้องรอจริง"""
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: None)


def make(tmp_path, name="a.xml"):
    (tmp_path / "execute").mkdir(exist_ok=True)
    path = tmp_path / "execute" / name
    path.write_text("<map/>", encoding="utf-8")
    return AccountSession(src=str(path), lane=Lane())


def stub(monkeypatch, calls, rsn="ID1", level=3):
    """ตัวปลอมที่ *ไม่* เก็บ token ให้เอง - สิ่งที่พิสูจน์คือ session เป็นคนถือ

    ต่างจาก test_flows_login.py ตรงบรรทัดสุดท้ายของ _fetch_home (setattr(s, "level", level))
    เท่านั้น - เหตุผลอยู่ใน docstring บนสุดของไฟล์นี้
    """
    monkeypatch.setattr(flows, "_relogin", lambda s: (
        calls.append("relogin"), setattr(s, "cookie", "LF_AC=t-" + os.path.basename(s.src)),
        setattr(s, "rsn", rsn))[0])
    monkeypatch.setattr(flows, "_fetch_home", lambda s: (
        calls.append("home"),
        setattr(s, "home", {"player": {"rsn": rsn, "level": level},
                            "rubyBalance": {"total": 10}}),
        setattr(s, "level", level))[0])
    monkeypatch.setattr(flows, "_claim_rewards", lambda s, cfg: calls.append("claim"))
    monkeypatch.setattr(flows, "_gacha", lambda s, cfg: calls.append("gacha"))
    monkeypatch.setattr(flows, "_account_info", lambda s: calls.append("info"))


# --- brief's own 6 tests (verbatim) ---

def test_level3_skips_the_stage_replay_when_the_account_is_already_there(tmp_path, monkeypatch):
    """ถึงเป้าอยู่แล้วให้ login เฉย ๆ - เล่นซ้ำคือการจ่ายค่า request ฟรี"""
    calls = []
    stub(monkeypatch, calls, level=3)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: calls.append("levelup"))
    flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, leveltarget=3))
    assert "levelup" not in calls


def test_level3_replays_stage_one_when_the_account_is_below_target(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls, level=1)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: (
        calls.append("levelup"), setattr(s, "level", 3))[0])
    out = flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, leveltarget=3))
    assert "levelup" in calls
    assert out.dest == "output"


def test_level3_sends_an_account_that_never_reached_target_to_login_failed(tmp_path, monkeypatch):
    """จุดประสงค์ของโหมดคือได้ไอดีเลเวล 3 ปล่อยเลเวลต่ำปนลง output คือทำลายความหมายของโฟลเดอร์"""
    stub(monkeypatch, [], level=1)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: None)
    out = flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, leveltarget=3))
    assert out.dest == "login failed"


def test_genid_does_not_claim_a_file_from_the_queue(tmp_path, monkeypatch):
    """GenID สร้างบัญชีใหม่ มันไม่มีไฟล์ต้นทาง - src ต้องว่างได้"""
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_create_account", lambda s, cfg: calls.append("create"))
    s = AccountSession(src="", lane=Lane())
    out = flows.run("ranger_api_GenID", s, dict(CFG, genidlevel3=False))
    assert "create" in calls
    assert out.dest in ("output", "backup")


def test_every_mode_in_the_gui_has_a_flow():
    """โหมดที่ dropdown เสนอแต่ engine ไม่รู้จัก = ผู้ใช้กดแล้วไม่เกิดอะไรขึ้น"""
    assert set(flows.MODES) == {
        "ranger_api_Login", "ranger_api_Level3", "ranger_api_GenID", "ranger_api_Stage",
        "ranger_api_Quest"}


def test_adding_a_fifth_mode_needs_nothing_but_a_new_entry(tmp_path, monkeypatch):
    """spec ข้อ 1.5: โหมด Quest ต้อง port กลับเข้ามาได้โดยไม่แก้ pool.py หรือ queue.py"""
    stub(monkeypatch, [])
    flows.MODES["ranger_api_Fake"] = lambda s, cfg: flows.Outcome(dest="output", name="x")
    try:
        assert flows.run("ranger_api_Fake", make(tmp_path), CFG).name == "x"
    finally:
        del flows.MODES["ranger_api_Fake"]


# --- extra coverage: Level3 - proving the 5 defects don't recur (see run_login's own
# extra-coverage section for the pattern this follows) ---

def test_level3_does_not_redraw_gacha_on_a_retry_after_it_already_succeeded(tmp_path, monkeypatch):
    """เหมือน run_login: กาชาหักตั๋วจริง ถ้าสุ่มไปแล้วแต่ขั้นหลังพัง retry ห้ามสุ่มซ้ำ (Finding 2 -
    brief's run_level3 sketch calls _gacha under a bare `if cfg.get("gacharanger"):`, with no
    s.gacha_status == "-" guard, so a retry after a successful draw would redraw for real)
    """
    calls = []
    stub(monkeypatch, calls)

    def gacha_once(s, cfg):
        calls.append("gacha")
        s.gacha_units, s.gacha_status = ["u1630e-sally"], "u1630e-sally"

    monkeypatch.setattr(flows, "_gacha", gacha_once)

    attempts_seen = []

    def flaky_info(s):
        attempts_seen.append(s.attempts)
        if s.attempts == 1:
            raise RuntimeError("transient: units endpoint timed out")

    monkeypatch.setattr(flows, "_account_info", flaky_info)
    out = flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, gacharanger=True, leveltarget=3))

    assert calls.count("gacha") == 1
    assert attempts_seen == [1, 2]
    assert out.status == "OK"


def test_level3_routes_a_drawn_target_ranger_to_backup(tmp_path, monkeypatch):
    """ต้นฉบับ (startBotLevel3_API_headless): gotTarget = any(RANGERSCONFIG.get(code.lower())
    for code in gachaUnits) ส่งไฟล์ไป backup/ แทน output/ - brief's run_level3 sketch always
    returns dest="output" and never reaches this branch (Finding 3, applied to Level3)
    """
    calls = []
    stub(monkeypatch, calls)

    def gacha_found_target(s, cfg):
        calls.append("gacha")
        s.gacha_units = ["u1630e-sally", "u9999e-other"]
        s.gacha_status = "u1630e-sally,u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_found_target)
    cfg = dict(CFG, gacharanger=True, _rangers_config={"u1630e-sally": "Sally"}, leveltarget=3)
    out = flows.run("ranger_api_Level3", make(tmp_path), cfg)

    assert out.dest == "backup"
    assert out.status == "OK"


def test_level3_account_info_reads_the_ranger_target_config_without_crashing(tmp_path, monkeypatch):
    """_account_info ของจริง (ใช้ร่วมกับทุกโหมด) อ่าน _rangers_config จาก s.cache - ค่านี้ต้องถูก
    ยัดกลับเข้า cache ทุกครั้งหลัง reset_token() ล้างมันทิ้ง (Finding 1) มิฉะนั้น s.rangers จะว่าง
    เปล่าเสมอแม้ตั้ง target ไว้ตรง เพราะ pull_roster.unit_names(units, None) ถือว่าไม่มีเป้าหมาย
    """
    import gacha as gacha_mod
    import rangers_api as rangers_api_mod

    calls = []

    def fake_relogin(s):
        calls.append("relogin")
        s.cookie, s.rsn, s.level = "LF_AC=t", "ID1", 3

    def fake_fetch_home(s):
        calls.append("home")
        s.home = {"player": {"rsn": "ID1", "level": 3}, "rubyBalance": {"total": 10}}
        s.level = 3

    monkeypatch.setattr(flows, "_relogin", fake_relogin)
    monkeypatch.setattr(flows, "_fetch_home", fake_fetch_home)
    monkeypatch.setattr(flows, "_claim_rewards", lambda s, cfg: calls.append("claim"))
    monkeypatch.setattr(flows, "_gacha", lambda s, cfg: calls.append("gacha"))
    monkeypatch.setattr(gacha_mod, "ticket_counts", lambda cookie, uid=None: (7, 0))
    monkeypatch.setattr(rangers_api_mod, "call", lambda cookie, path, **kw: (
        200, {"result": {"playerUnits": [{"unitCode": "u1630e-sally"}]}}))

    cfg = dict(CFG, _rangers_config={"u1630e-sally": "Sally"}, leveltarget=3)
    out = flows.run("ranger_api_Level3", make(tmp_path), cfg)

    assert out.status == "OK", out.error
    assert out.name == "Sally_Rb10_Tk7_ID1_Lv3"


def test_level3_a_permanent_failure_from_relogin_is_attempted_exactly_once(tmp_path, monkeypatch):
    """Finding 5: a 401 is the server's real answer (see PermanentFailure), not something a
    second and third attempt could fix - run_level3 must special-case it exactly like
    run_login, not fold it into one bare `except Exception` that retries everything blindly.
    """
    stub(monkeypatch, [])
    attempts_seen = []

    def boom(s):
        attempts_seen.append(s.attempts)
        raise flows.PermanentFailure("relogin rejected (HTTP 401)")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Level3", make(tmp_path), CFG)

    assert attempts_seen == [1]
    assert out.dest == "login failed"
    assert out.status == "FAIL"


def test_level3_a_transient_failure_retries_with_backoff(tmp_path, monkeypatch):
    """Finding 5's other half: an ordinary (non-permanent) failure still gets all
    MAX_ATTEMPTS, but waits between them instead of hammering the server back to back.
    """
    sleeps = []
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: sleeps.append(seconds))
    stub(monkeypatch, [])
    attempts_seen = []

    def boom(s):
        attempts_seen.append(s.attempts)
        raise RuntimeError("network hiccup")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Level3", make(tmp_path), CFG)

    assert attempts_seen == [1, 2, 3]
    assert out.dest == "login failed"
    assert sleeps == list(flows.RETRY_BACKOFF_SECONDS)


# --- extra coverage: GenID ---

def test_genid_a_stale_gacha_flag_from_an_abandoned_account_does_not_suppress_the_next_accounts_draw(
        tmp_path, monkeypatch):
    """GenID มินต์บัญชีใหม่ทุก attempt ("attempt ใหม่ = สร้างบัญชีใหม่สด...ปล่อยทิ้ง" - คอมเมนต์
    เดิมของ startBotGenID_API_headless) ต่างจาก Login/Level3/Stage ที่ attempt ถัดไปยังเป็น
    บัญชีเดียวกัน ถ้า _create_account ไม่ล้าง gacha_status/gacha_units ของบัญชีก่อนหน้าที่พัง
    กลางทาง (แต่สุ่มกาชาไปแล้ว) บัญชีใหม่จะถูกมองว่า "สุ่มไปแล้ว" ทั้งที่ไม่เคยสุ่มเลย - ทั้งข้าม
    กาชาจริงของมันไป (ถ้ามี guard แบบเดียวกับ run_login) และยังลาก gacha_units ของบัญชีเก่ามา
    ตัดสิน backup/output ให้บัญชีที่ไม่เกี่ยวข้องกันเลย พิสูจน์ทั้งสองเรื่องพร้อมกัน: _gacha ต้องถูก
    เรียกสำหรับบัญชีที่สอง (ไม่ถูกข้าม) และผลลัพธ์สุดท้ายต้องมาจากการสุ่มของบัญชีที่สองเท่านั้น
    """
    import new_account as new_account_mod

    calls = []
    stub(monkeypatch, calls)   # _relogin (genid ไม่ใช้), _fetch_home, _claim_rewards ปกติ

    minted = []

    def fake_make_account(write_xml_dir=None, skip_tut=True):
        n = len(minted) + 1
        minted.append(n)
        return {"status": "ready", "lf_ac": "lfac-%d" % n, "rsn": "rsn-%d" % n,
                "gameId": "gid-%d" % n}

    def fake_write_account_xml(acct, xml_dir):
        os.makedirs(xml_dir, exist_ok=True)
        path = os.path.join(xml_dir, acct["rsn"] + ".xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<map/>")
        return path

    monkeypatch.setattr(new_account_mod, "make_account", fake_make_account)
    monkeypatch.setattr(new_account_mod, "write_account_xml", fake_write_account_xml)
    monkeypatch.setattr(flows, "EXECUTE_DIR", str(tmp_path / "execute"))

    gacha_calls = []

    def gacha_spy(s, cfg):
        gacha_calls.append(s.rsn)
        if s.rsn == "rsn-1":
            s.gacha_units, s.gacha_status = ["u1630e-sally"], "u1630e-sally"
        else:
            s.gacha_units, s.gacha_status = ["u9999e-other"], "u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_spy)

    info_calls = []

    def flaky_info(s):
        info_calls.append(s.rsn)
        if len(info_calls) == 1:
            raise RuntimeError("transient: units endpoint timed out")

    monkeypatch.setattr(flows, "_account_info", flaky_info)

    s = AccountSession(src="", lane=Lane())
    cfg = dict(CFG, gacharanger=True, _rangers_config={"u1630e-sally": "Sally"})
    out = flows.run("ranger_api_GenID", s, cfg)

    assert gacha_calls == ["rsn-1", "rsn-2"]   # บัญชีที่สองต้องได้สุ่มจริง ไม่ถูกข้าม
    assert out.status == "OK"
    assert s.rsn == "rsn-2"
    assert out.dest == "output"                # ต้องตัดสินจากของบัญชีที่สอง ไม่ใช่ของเก่าที่ทิ้งไปแล้ว
    assert "rsn-2" in out.name


def test_genid_sends_an_account_that_never_reached_target_level_to_login_failed(tmp_path, monkeypatch):
    """เหมือน Level3: genidlevel3 แปลว่าผลลัพธ์ต้องเป็นเลเวล 3 เท่านั้น ดันไม่ถึงต้องไม่ปนกับ output

    level=1 ต้องส่งผ่าน stub() (ไม่ใช่ setattr เองใน _create_account lambda) เพราะ _fetch_home's
    stub รันทีหลังและ setattr(s, "level", level)'s ทับอยู่ดี - ดู stub()'s "level" param
    """
    calls = []
    stub(monkeypatch, calls, level=1)
    monkeypatch.setattr(flows, "_create_account", lambda s, cfg: calls.append("create"))
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: None)
    s = AccountSession(src="", lane=Lane())
    out = flows.run("ranger_api_GenID", s, dict(CFG, genidlevel3=True, leveltarget=3))
    assert out.dest == "login failed"
    assert out.status == "LOWLV"


def test_genid_routes_a_drawn_target_ranger_to_backup(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_create_account", lambda s, cfg: (
        calls.append("create"), setattr(s, "rsn", "ID1"), setattr(s, "level", 3))[0])

    def gacha_found_target(s, cfg):
        calls.append("gacha")
        s.gacha_units = ["u1630e-sally", "u9999e-other"]
        s.gacha_status = "u1630e-sally,u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_found_target)
    s = AccountSession(src="", lane=Lane())
    cfg = dict(CFG, gacharanger=True, _rangers_config={"u1630e-sally": "Sally"})
    out = flows.run("ranger_api_GenID", s, cfg)
    assert out.dest == "backup"


def test_genid_a_transient_failure_retries_with_backoff(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: sleeps.append(seconds))
    calls = []
    stub(monkeypatch, calls)
    attempts_seen = []

    def boom(s, cfg):
        attempts_seen.append(s.attempts)
        raise RuntimeError("signup 500")

    monkeypatch.setattr(flows, "_create_account", boom)
    s = AccountSession(src="", lane=Lane())
    out = flows.run("ranger_api_GenID", s, CFG)

    assert attempts_seen == [1, 2, 3]
    assert out.dest == "login failed"
    assert sleeps == list(flows.RETRY_BACKOFF_SECONDS)


# --- extra coverage: Stage ---

def test_force_stage_propagates_the_flagged_reason_from_clear_range(tmp_path, monkeypatch):
    """ถ้าทิ้ง reason ของ clear_range (ตามที่ sketch เดิมของ brief ทำ - เรียกแล้วไม่เก็บค่าที่คืนมา)
    run_stage จะไม่มีทางรู้เลยว่าบัญชีโดนตีธง แล้วจะส่งไฟล์ไป output/ ปนกับไอดีที่ใช้ได้จริง (ต้นฉบับ
    startBotStage_API_headless เช็ค result["stop"] == "flagged" แล้วส่งไป login failed แทน)
    """
    import stage_forge

    monkeypatch.setattr(stage_forge, "player_info", lambda cookie: {"rsn": "ID1", "level": 5})
    monkeypatch.setattr(stage_forge, "start_stage", lambda cookie, player: 12)
    monkeypatch.setattr(stage_forge, "clear_range",
                         lambda cookie, rsn, first, last, **kw: (11, "flagged"))

    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t", rsn="ID1")
    reason = flows._force_stage(s, dict(CFG, stageend=50))
    assert reason == "flagged"


def test_force_stage_skips_the_replay_when_already_past_the_target(tmp_path, monkeypatch):
    import stage_forge

    monkeypatch.setattr(stage_forge, "player_info", lambda cookie: {"rsn": "ID1", "level": 20})
    monkeypatch.setattr(stage_forge, "start_stage", lambda cookie, player: 151)

    def exploding_clear_range(*a, **kw):
        raise AssertionError("must not replay stages once past the target")

    monkeypatch.setattr(stage_forge, "clear_range", exploding_clear_range)

    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t", rsn="ID1")
    reason = flows._force_stage(s, dict(CFG, stageend=150))
    assert reason == "done"


def test_stage_routes_a_flagged_push_to_login_failed_not_output(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_force_stage", lambda s, cfg: "flagged")
    out = flows.run("ranger_api_Stage", make(tmp_path), CFG)
    assert out.dest == "login failed"
    assert out.status == "FLAG"


def test_stage_a_successful_push_exports_to_output(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_force_stage", lambda s, cfg: (calls.append("stage"), "done")[1])
    out = flows.run("ranger_api_Stage", make(tmp_path), CFG)
    assert "stage" in calls
    assert out.dest == "output"
    assert out.status == "OK"


def test_stage_does_not_claim_rewards_unlike_the_other_modes(tmp_path, monkeypatch):
    """ต้นฉบับ (startBotStage_API_headless) ไม่เคยเรียก apiAcceptAllRewards เลย ต่างจาก
    Level3/GenID ที่เรียกทั้งคู่ sketch เดิมของ brief เพิ่ม _claim_rewards เข้ามาใน run_stage
    ซึ่งไม่ตรงกับของจริง - ตัดออกเพื่อความตรงกับต้นฉบับ (ดู task-8-report.md)
    """
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_force_stage", lambda s, cfg: "done")
    flows.run("ranger_api_Stage", make(tmp_path), CFG)
    assert "claim" not in calls


def test_stage_a_permanent_failure_from_relogin_is_attempted_exactly_once(tmp_path, monkeypatch):
    stub(monkeypatch, [])
    attempts_seen = []

    def boom(s):
        attempts_seen.append(s.attempts)
        raise flows.PermanentFailure("relogin rejected (HTTP 401)")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Stage", make(tmp_path), CFG)

    assert attempts_seen == [1]
    assert out.dest == "login failed"
    assert out.status == "FAIL"


def test_force_stage_refreshes_the_level_after_clearing_stages(tmp_path, monkeypatch):
    """ต้นฉบับ (apiForceStage) อ่าน player_info ใหม่หลัง clear_range เพื่อเอา level หลังดันด่าน
    ไปใส่ชื่อไฟล์ที่ export (ผ่าน getAccoutInfo -> currentLevel()) ถ้าไม่รีเฟรชตรงนี้ s.level จะ
    ค้างที่ค่าก่อนดันด่าน (จาก _fetch_home) ทั้งที่เคลียร์ด่านไปหลายสิบด่านจริง ๆ แล้ว
    """
    import stage_forge

    calls = []

    def fake_player_info(cookie):
        calls.append("player_info")
        # ครั้งแรก (ก่อนดัน) level ต่ำ ครั้งที่สอง (หลัง clear_range) level สูงขึ้นแล้ว
        return {"rsn": "ID1", "level": 5 if len(calls) == 1 else 12}

    monkeypatch.setattr(stage_forge, "player_info", fake_player_info)
    monkeypatch.setattr(stage_forge, "start_stage", lambda cookie, player: 3)
    monkeypatch.setattr(stage_forge, "clear_range",
                         lambda cookie, rsn, first, last, **kw: (50, "done"))

    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t", rsn="ID1", level=5)
    reason = flows._force_stage(s, dict(CFG, stageend=50))
    assert reason == "done"
    assert s.level == 12
    assert calls == ["player_info", "player_info"]


# --- Review findings, round 1 ---
#
# Finding 1: run_genid's level-gate branch did a bare `return` on attempt 1, ending the
# whole flow - the original (startBotGenID_API_headless) raises instead, so its own
# attempt loop mints an entirely fresh account on the next try ("attempt ใหม่ = สร้างบัญชี
# ใหม่สด (มินต์ก่อนหน้าถ้าพังหลัง signup ก็ปล่อยทิ้ง)" - _create_account's own docstring),
# spending its full budget of MAX_ATTEMPTS mints before giving up on a level-gate failure.
# test_genid_sends_an_account_that_never_reached_target_level_to_login_failed (above)
# asserts only dest/status, which stay identical either way - that's why 1-of-3 went
# unnoticed. The test below counts _create_account calls directly.


def test_genid_mints_a_fresh_account_on_every_retry_after_a_level_gate_failure(
        tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls, level=1)
    mint_attempts = []
    monkeypatch.setattr(flows, "_create_account",
                         lambda s, cfg: mint_attempts.append(s.attempts))
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: None)
    s = AccountSession(src="", lane=Lane())
    out = flows.run("ranger_api_GenID", s, dict(CFG, genidlevel3=True, leveltarget=3))

    assert mint_attempts == [1, 2, 3]       # one fresh mint per attempt, not just attempt 1
    assert out.dest == "login failed"
    assert out.status == "LOWLV"            # final outcome unchanged - only the count was


# Finding 2: bot/input/ has 24,279 files and two of them can be the same underlying game
# account (observed: a0bfb087, two files, gacha'd twice). The original
# (startBotLevel3_API_headless:8344, like startBotLogin_API_headless:8042) claims the
# account id once per session and skips rewards/gacha for a file that lost the race, while
# still exporting it. See test_flows_login.py for AccountClaimRegistry's own unit tests and
# the threaded proof against run_login - these two only prove run_level3 wires it the same
# way, and that run_genid deliberately does NOT (a fresh mint's identity can't collide with
# another input/ file's, since it never came from input/ at all).


def test_level3_a_duplicate_account_skips_rewards_and_gacha_but_still_exports(
        tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)             # stub()'s default rsn is "ID1"
    registry = flows.AccountClaimRegistry()
    assert registry.claim("ID1")         # another input/ file already claimed this account
    cfg = dict(CFG, gacharanger=True, leveltarget=3, _account_claims=registry)
    out = flows.run("ranger_api_Level3", make(tmp_path), cfg)

    assert "claim" not in calls          # _claim_rewards
    assert "gacha" not in calls
    assert out.status == "OK"
    assert out.dest in ("output", "backup")


def test_level3_releases_the_claim_when_the_level_gate_rejects_the_account(
        tmp_path, monkeypatch):
    """Original: "จองบัญชีไว้แต่สุ่มไม่สำเร็จ ปล่อยให้ไฟล์ซ้ำของบัญชีนี้ (ถ้ามี) ได้สุ่มแทน" - a
    session that claims an id but is rejected by the level gate before ever reaching
    rewards/gacha must give the claim back.
    """
    stub(monkeypatch, [], level=1)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: None)
    registry = flows.AccountClaimRegistry()
    out = flows.run("ranger_api_Level3", make(tmp_path),
                     dict(CFG, leveltarget=3, _account_claims=registry))

    assert out.dest == "login failed"
    assert out.status == "LOWLV"
    assert registry.claim("ID1") is True   # never actually spent - released, claimable again


def test_genid_ignores_account_claims_even_when_present(tmp_path, monkeypatch):
    """GenID mints a brand-new game account every attempt - there is no input/ file whose
    identity could collide with another file's, which is the only scenario
    AccountClaimRegistry defends against (see its own docstring). A claim already held
    under the rsn GenID is about to mint must not suppress this account's own, first-ever
    draw - proving GenID stays correct even if cfg carries _account_claims for every mode.
    """
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_create_account", lambda s, cfg: (
        calls.append("create"), setattr(s, "rsn", "ID1"), setattr(s, "level", 3))[0])

    def gacha_spy(s, cfg):
        calls.append("gacha")
        s.gacha_units, s.gacha_status = ["u9999e-other"], "u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_spy)
    registry = flows.AccountClaimRegistry()
    assert registry.claim("ID1")         # an unrelated prior claim on the same rsn
    s = AccountSession(src="", lane=Lane())
    cfg = dict(CFG, gacharanger=True, _account_claims=registry)
    out = flows.run("ranger_api_GenID", s, cfg)

    assert "gacha" in calls
    assert out.status == "OK"


# --- Login Quest (ranger_api_Quest): relogin -> skip tutorial -> push stages -> NEWBI quests ---

def quest_stub(monkeypatch, calls, stage="done", quest="quest 18/29 blocked@idx18 exp_booster"):
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_skip_tutorial", lambda s: (calls.append("tutorial"), (65, 67))[1])
    monkeypatch.setattr(flows, "_force_stage", lambda s, cfg: (calls.append("stage"), stage)[1])
    monkeypatch.setattr(flows, "_newbie_quest", lambda s: (calls.append("quest"), quest)[1])


def test_quest_skips_tutorial_then_pushes_stages_then_walks_quests_then_exports(tmp_path, monkeypatch):
    """ลำดับตามที่ผู้ใช้สั่ง: ข้ามการสอนก่อน ดันด่านถึง 150 แล้วค่อยทำเควส (stage_special ติดเลเวล 20)
    และ /home ต้องถูกดึงใหม่หลังเควส - ruby ในชื่อไฟล์ต้องรวมหลักไมล์ 50/150/200 ที่เพิ่งเคลม"""
    calls = []
    quest_stub(monkeypatch, calls)
    out = flows.run("ranger_api_Quest", make(tmp_path), CFG)
    assert calls == ["relogin", "home", "tutorial", "stage", "quest", "home", "info"]
    assert out.dest == "output"
    assert out.status == "OK"
    assert out.error == "quest 18/29 blocked@idx18 exp_booster"


def test_quest_does_not_claim_rewards_or_draw_gacha(tmp_path, monkeypatch):
    """โหมดนี้ไม่ได้ขอให้รับของ/สุ่มกาชา - กาชาหักตั๋วจริง ห้ามติดมาเพราะ cfg ของโหมดอื่นเปิดไว้"""
    calls = []
    quest_stub(monkeypatch, calls)
    flows.run("ranger_api_Quest", make(tmp_path), dict(CFG, gacharanger=True))
    assert "claim" not in calls
    assert "gacha" not in calls


def test_quest_routes_a_flagged_push_to_login_failed_without_walking_quests(tmp_path, monkeypatch):
    calls = []
    quest_stub(monkeypatch, calls, stage="flagged")
    out = flows.run("ranger_api_Quest", make(tmp_path), CFG)
    assert out.dest == "login failed"
    assert out.status == "FLAG"
    assert "quest" not in calls


def test_quest_a_short_stage_push_still_walks_quests_and_says_so(tmp_path, monkeypatch):
    """heart หมด/ด่านล็อกกลางทางไม่ใช่เหตุให้ทิ้งไอดี แต่แถวของบัญชีต้องบอกว่าดันไม่ถึงเป้า"""
    calls = []
    quest_stub(monkeypatch, calls, stage="hearts")
    out = flows.run("ranger_api_Quest", make(tmp_path), CFG)
    assert "quest" in calls
    assert out.dest == "output"
    assert out.error == "stage stop=hearts; quest 18/29 blocked@idx18 exp_booster"


def test_quest_a_retry_does_not_redo_the_tutorial_or_the_stage_push(tmp_path, monkeypatch):
    """ดันด่านจ่าย heart จริงทุกด่าน - พังตอนทำเควสแล้ว retry ต้องไม่ดันซ้ำ"""
    calls = []
    quest_stub(monkeypatch, calls)
    walks = []

    def flaky_quest(s):
        walks.append(s.attempts)
        if len(walks) == 1:
            raise RuntimeError("network down")
        return "quest 18/29 blocked@idx18 exp_booster"

    monkeypatch.setattr(flows, "_newbie_quest", flaky_quest)
    out = flows.run("ranger_api_Quest", make(tmp_path), CFG)
    assert walks == [1, 2]
    assert calls.count("relogin") == 2
    assert calls.count("tutorial") == 1
    assert calls.count("stage") == 1
    assert out.status == "OK"


def test_quest_a_token_death_mid_push_retries_the_push(tmp_path, monkeypatch):
    """"auth" = โทเค็นตายกลางทาง การดันยังไม่จบจริง ต้อง relogin แล้วดันต่อ ไม่ใช่ถือว่าจบแล้ว"""
    calls = []
    quest_stub(monkeypatch, calls)
    reasons = iter(["auth", "done"])
    monkeypatch.setattr(flows, "_force_stage", lambda s, cfg: (calls.append("stage"), next(reasons))[1])
    out = flows.run("ranger_api_Quest", make(tmp_path), CFG)
    assert calls.count("stage") == 2
    assert calls.count("quest") == 1
    assert out.status == "OK"
    assert out.error == "quest 18/29 blocked@idx18 exp_booster"


def test_quest_a_permanent_failure_from_relogin_is_attempted_exactly_once(tmp_path, monkeypatch):
    quest_stub(monkeypatch, [])
    attempts_seen = []

    def boom(s):
        attempts_seen.append(s.attempts)
        raise flows.PermanentFailure("relogin rejected (HTTP 401)")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Quest", make(tmp_path), CFG)
    assert attempts_seen == [1]
    assert out.dest == "login failed"
    assert out.status == "FAIL"


def test_skip_tutorial_fires_only_the_steps_login_says_are_pending(monkeypatch):
    import tutorial

    fired = []
    monkeypatch.setattr(tutorial, "STEPS", ["START", "TEAM", "SALLY"])
    monkeypatch.setattr(tutorial, "confirm", lambda cookie, step: (
        fired.append(step), (step != "SALLY", 200, {}))[1])
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t")
    s.cache["tutorial_steps"] = {"START": True, "TEAM": False, "SALLY": False}
    assert flows._skip_tutorial(s) == (1, 2)
    assert fired == ["TEAM", "SALLY"]


def test_skip_tutorial_fires_every_step_without_a_map_from_login(monkeypatch):
    import tutorial

    fired = []
    monkeypatch.setattr(tutorial, "STEPS", ["START", "TEAM"])
    monkeypatch.setattr(tutorial, "confirm", lambda cookie, step: (fired.append(step), (True, 200, {}))[1])
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t")
    assert flows._skip_tutorial(s) == (2, 2)
    assert fired == ["START", "TEAM"]


def test_skip_tutorial_stops_on_a_rejected_token(monkeypatch):
    import tutorial

    fired = []
    monkeypatch.setattr(tutorial, "STEPS", ["START", "TEAM", "GACHA"])
    monkeypatch.setattr(tutorial, "confirm", lambda cookie, step: (fired.append(step), (False, 401, {}))[1])
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t")
    with pytest.raises(RuntimeError):
        flows._skip_tutorial(s)
    assert fired == ["START"]


def test_relogin_keeps_the_tutorial_map_that_login_returns(tmp_path, monkeypatch):
    import relogin as relogin_mod

    class Pool:
        def get(self): return "cc"
        def renew(self, cc): return "cc"
        def mark_proven(self): pass

    class LaneWithPool(Lane):
        cc_pool = Pool()

    monkeypatch.setattr(relogin_mod, "read_account", lambda path: {
        "udid": "u", "enc": "e", "nation": "TH", "language": "en", "text": "<map/>"})
    monkeypatch.setattr(flows, "decrypt_lfac", lambda udid, enc: "guest")
    monkeypatch.setattr(relogin_mod, "login", lambda cc, *a, **kw: (
        200, {"rsn": "R", "level": 1, "tutorialStep": {"START": True}}, "lfac"))
    monkeypatch.setattr(relogin_mod, "atomic_write", lambda *a, **k: None)
    monkeypatch.setattr(relogin_mod, "replace_enc", lambda *a, **k: "")
    s = make(tmp_path)
    s.lane = LaneWithPool()
    flows._relogin(s)
    assert s.cache["tutorial_steps"] == {"START": True}


def _pdq(claimed, total=29, current=None, current_type="exp_booster"):
    contents = [{"index": i, "missionType": "stage_main", "receiveReward": i < claimed,
                 "currentQuest": i == current} for i in range(total)]
    if current is not None:
        contents[current]["missionType"] = current_type
    return {"contents": contents}


def test_newbie_quest_walks_quietly_claims_the_milestone_and_summarises(monkeypatch):
    """progress=print ของ walk จะลง stdout ซึ่งเป็นช่อง JSONL ของ GUI - ต้องส่ง _quiet เข้าไปเสมอ"""
    import newbie_quest

    seen = {}
    reads = iter([(_pdq(0, current=0, current_type="stage_main"), 200),
                  (_pdq(18, current=18), 200)])
    monkeypatch.setattr(newbie_quest, "get_quest", lambda cookie: next(reads))

    def fake_walk(cookie, confirm=True, **kw):
        seen.update(kw, confirm=confirm)
        return "blocked:exp_booster", list(range(18))

    monkeypatch.setattr(newbie_quest, "walk", fake_walk)
    monkeypatch.setattr(newbie_quest, "claim_special", lambda cookie: seen.setdefault("special", True))
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t")
    assert flows._newbie_quest(s) == "quest 18/29 blocked@idx18 exp_booster"
    assert seen["progress"] is flows._quiet
    assert seen["confirm"] is True
    assert seen["special"] is True


def test_newbie_quest_on_an_account_without_the_chain_does_nothing(monkeypatch):
    import newbie_quest

    monkeypatch.setattr(newbie_quest, "get_quest", lambda cookie: ({}, 200))

    def exploding_walk(*a, **kw):
        raise AssertionError("no chain - nothing to walk")

    monkeypatch.setattr(newbie_quest, "walk", exploding_walk)
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t")
    assert flows._newbie_quest(s) == "quest -"


def test_newbie_quest_raises_when_the_token_dies_mid_walk(monkeypatch):
    """"auth" ต้องกลายเป็น exception ให้ run_quest retry - ไม่ใช่สรุปว่าจบแล้วส่งออก"""
    import newbie_quest

    monkeypatch.setattr(newbie_quest, "get_quest", lambda cookie: (_pdq(3, current=3), 200))
    monkeypatch.setattr(newbie_quest, "walk", lambda cookie, **kw: ("auth", [0, 1, 2]))
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t")
    with pytest.raises(RuntimeError):
        flows._newbie_quest(s)


def test_force_stage_keeps_clear_range_progress_off_stdout(monkeypatch):
    """stdout ของ engine คือช่อง JSONL - clear_range ต้องไม่ print ทีละด่านลงไปแทรกแถวของ Reporter"""
    import stage_forge

    seen = {}
    monkeypatch.setattr(stage_forge, "player_info", lambda cookie: {"rsn": "ID1", "level": 5})
    monkeypatch.setattr(stage_forge, "start_stage", lambda cookie, player: 3)

    def fake_clear_range(cookie, rsn, first, last, **kw):
        seen.update(kw)
        return last, "done"

    monkeypatch.setattr(stage_forge, "clear_range", fake_clear_range)
    s = AccountSession(src="x", lane=Lane(), cookie="LF_AC=t", rsn="ID1")
    flows._force_stage(s, dict(CFG, stageend=150))
    assert seen["progress"] is flows._quiet


def _delay_seen(monkeypatch, cfg):
    import stage_forge

    seen = {}
    monkeypatch.setattr(stage_forge, "player_info", lambda cookie: {"rsn": "ID1", "level": 5})
    monkeypatch.setattr(stage_forge, "start_stage", lambda cookie, player: 3)
    monkeypatch.setattr(stage_forge, "clear_range",
                        lambda cookie, rsn, first, last, **kw: (seen.update(kw), (last, "done"))[1])
    flows._force_stage(AccountSession(src="x", lane=Lane(), cookie="LF_AC=t", rsn="ID1"), cfg)
    return seen["delay"]


def test_force_stage_does_not_pause_between_stages_by_default(monkeypatch):
    """ค่า 3 วิ (+สุ่มถึง 1 วิ) ของ CLI เคยเป็นครึ่งหนึ่งของเวลาต่อด่าน - rate limit มีตัวคุมใน rangers_api แล้ว"""
    assert _delay_seen(monkeypatch, dict(CFG, stageend=150)) == 0


def test_force_stage_uses_the_configured_stage_delay(monkeypatch):
    assert _delay_seen(monkeypatch, dict(CFG, stageend=150, stagedelay=2.5)) == 2.5


def test_stage_with_the_quest_box_ticked_runs_the_quest_flow(tmp_path, monkeypatch):
    """ติ๊ก "ทำเควสมือใหม่ต่อ" ในโหมด Stage = ข้ามการสอน -> ดันด่าน -> เควส เหมือน Login Quest"""
    calls = []
    quest_stub(monkeypatch, calls)
    out = flows.run("ranger_api_Stage", make(tmp_path), dict(CFG, newbiequest=True))
    assert calls == ["relogin", "home", "tutorial", "stage", "quest", "home", "info"]
    assert out.dest == "output"
    assert out.error == "quest 18/29 blocked@idx18 exp_booster"


def test_stage_without_the_quest_box_stays_a_plain_stage_push(tmp_path, monkeypatch):
    calls = []
    quest_stub(monkeypatch, calls)
    out = flows.run("ranger_api_Stage", make(tmp_path), dict(CFG, newbiequest=False))
    assert calls == ["relogin", "home", "stage", "info"]
    assert out.dest == "output"
