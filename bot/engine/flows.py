"""flow ของแต่ละ play mode - ฟังก์ชันล้วนที่รับ AccountSession เป็นตัวแรก

ห้ามฟังก์ชันไหนในไฟล์นี้อ่านหรือเขียนตัวแปรระดับโมดูลที่เปลี่ยนค่าได้ ทั้งไฟล์ถูกเรียก
จากหลายเธรดพร้อมกันบนคนละบัญชี
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))

import rangers_api          # noqa: E402
import relogin             # noqa: E402
import rewards             # noqa: E402
from device_session import decrypt_lfac   # noqa: E402

from .session import AccountSession, Outcome   # noqa: E402

MAX_ATTEMPTS = 3


# --- ขั้นตอนย่อย (เทสต์ replace ตัวพวกนี้ทีละตัว) ---

def _relogin(s: AccountSession) -> None:
    """ขอ LF_AC สดจากไฟล์ผ่าน /v12.3/login - ย้ายมาจาก getLFACHeadless()

    cc ของ guest มาจาก pool ที่ engine mint ไว้ให้ก่อนสปอว์นเธรด (โควตา /auth คือ
    2 ครั้งต่อ IP ต่อนาที การให้ทุกเธรด mint เองจะชนโควตาทันทีที่เกิน 2 เธรด)

    That is what this docstring already promised before this function's body actually
    delivered it: building a fresh relogin.CcPool() inside this function on every call
    - what the task brief's own sketch did - cannot be "the pool the engine minted before
    spawning threads," because nothing then keeps every caller pointed at the SAME
    instance (CcPool's in-memory _cc/_proven_at, and the entire reason the class exists,
    only help if one object answers every call). Without a pre-populated LGRGS_CC_FILE,
    that sketch mints for real, unlocked, on every account and every retry attempt -
    hundreds of concurrent accounts against a 2/min-per-IP quota. See task-7-report.md
    for the full analysis (relogin.py's own CLI proves the fix: it builds ONE CcPool()
    before spawning its ThreadPoolExecutor and shares it by reference).

    Fix: read the pool off s.lane first (getattr, so any lane object works, including
    the bare test fake that has no such attribute) and only build a private one - the
    brief's original fallback - for standalone use before a caller wires lane.cc_pool up.
    Nothing in tasks 1-9's briefs currently does that wiring; the caller doing so is what
    actually keeps the quota safe, this is only the hook that makes it possible.
    """
    acct = relogin.read_account(s.src)
    guest_cookie = decrypt_lfac(acct["udid"], acct["enc"])
    pool = getattr(s.lane, "cc_pool", None)
    if pool is None:
        pool = relogin.CcPool(share_file=os.environ.get("LGRGS_CC_FILE") or None)
    cc = pool.get()
    status, result, lf_ac = relogin.login(
        cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
    if status == 401 and not result:
        cc = pool.renew(cc)
        status, result, lf_ac = relogin.login(
            cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
    if not result or not lf_ac:
        raise RuntimeError("relogin failed (HTTP %s)" % status)
    pool.mark_proven()
    try:
        relogin.atomic_write(s.src, relogin.replace_enc(acct["text"], acct["udid"], lf_ac))
    except OSError as err:
        # เขียนโทเค็นกลับไฟล์ไม่ได้ก็ยังยิง API ต่อได้ ไฟล์ที่ export จะมีโทเค็นเก่าเท่านั้น
        s.error = "token write failed: %s" % err
    s.cookie = "LF_AC=" + lf_ac
    s.rsn = result.get("rsn") or ""
    s.level = int(result.get("level") or 0)


def _fetch_home(s: AccountSession) -> None:
    """ดึง /home ครั้งเดียวต่อบัญชี แล้วให้ทุกคนที่ต้องใช้อ่านจาก s.home

    เดิมก้อนนี้ถูกดึงสี่ครั้ง: check_session, survey_attendance_package, currentLevel
    และ getRubyAndTicket
    """
    status, data = rangers_api.call(s.cookie, "/home")
    if status != 200 or not isinstance(data, dict) or "result" not in data:
        raise RuntimeError("home rejected (HTTP %s)" % status)
    s.home = data["result"]
    player = s.home.get("player") or {}
    s.rsn = player.get("rsn") or s.rsn
    s.level = int(player.get("level") or s.level)


def _claim_rewards(s: AccountSession, cfg: dict) -> None:
    rewards.claim_all(s.cookie, confirm=True,
                      passes=int(cfg.get("rewardpasses") or 3), home=s.home)


def _gacha(s: AccountSession, cfg: dict) -> None:
    """สุ่มกาชาด้วยตั๋วของบัญชีนี้

    draw_with_ticket คืน (granted_codes, status) - ต้องแกะเป็นสองค่า ไม่ใช่เก็บทั้ง tuple
    ลง gacha_units ซึ่งเป็น list ไม่งั้น len(s.gacha_units) จะได้ 2 เสมอไม่ว่าสุ่มได้กี่ตัว
    """
    import gacha as gacha_mod
    s.gacha_units, s.gacha_status = gacha_mod.draw_with_ticket(
        s.cookie, s.rsn,
        group=cfg.get("gacharangergroup"),
        cycles=int(cfg.get("gachacycles") or 1),
        stop_when_found=bool(cfg.get("stopwhenfound", True)),
        targets=cfg.get("_rangers_config"),
        cache=s.cache,
        gacha_mode=cfg.get("gachamode") or "NumberOfCycles",
        use_ruby=bool(cfg.get("useruby", False)))


def _account_info(s: AccountSession) -> None:
    """เติม rangers / ruby / ticket / level จากของที่ดึงมาแล้วให้มากที่สุด

    ruby อยู่ใน s.home ที่ดึงไปแล้ว เหลือแค่คลัง ranger กับจำนวนตั๋วที่ต้องยิงเพิ่ม
    เดิมขั้นนี้ยิง /home ซ้ำอีกสองครั้งผ่าน currentLevel() และ getRubyAndTicket()

    Bug in the task brief's own sketch, found while verifying this move: that version
    read `cfg.get("_rangers_config")` here, but this function's signature - and both
    given test stubs in test_flows_login.py, which fix that signature - take only `s`.
    `cfg` is not in scope; the brief's own code raises NameError the first time this
    branch runs for real (i.e. whenever /player/units/equip returns 200), which every
    given test hides because all of them replace this function outright. Fixed by
    having run_login stash the one value this step needs onto s.cache (refreshed after
    every reset_token(), since reset_token() clears the cache) instead of widening this
    function's signature - widening it would take a second positional argument, which
    breaks the given stubs' fixed one-argument shape (lambda s: ..., def info(sess): ...).
    """
    import gacha as gacha_mod
    import pull_roster

    ruby = (s.home or {}).get("rubyBalance") or {}
    s.ruby = str(ruby.get("total", "NA"))
    premium, _event = gacha_mod.ticket_counts(s.cookie, s.rsn)
    s.ticket = str(premium)
    status, data = rangers_api.call(
        s.cookie, "/player/units/equip?inven=true&team=false&deck=false")
    if status == 200 and isinstance(data, dict):
        units = (data.get("result") or {}).get("playerUnits") or []
        s.rangers = pull_roster.unit_names(units, s.cache.get("_rangers_config"))


def _export_name(s: AccountSession) -> str:
    return "%s_Rb%s_Tk%s_%s_Lv%s" % (s.rangers, s.ruby, s.ticket, s.rsn, s.level)


# --- flow ต่อโหมด ---

def run_login(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            s.reset_token()
            # reset_token() just cleared s.cache; _account_info (called below, single-arg
            # per the fixed test stubs) reads the ranger-target config back out of it,
            # since it has no other way to reach cfg - see _account_info's docstring.
            s.cache["_rangers_config"] = cfg.get("_rangers_config")
            _relogin(s)
            _fetch_home(s)
            _claim_rewards(s, cfg)
            # Original (startBotLogin_API_headless) guarded gacha with a gachaDone flag
            # that lived outside the retry loop, at this exact comment: "กาชาหักตั๋วจริง
            # ถ้าสุ่มไปแล้วแต่ขั้นหลังพัง (เช่น pull ไฟล์ไม่ได้) retry ห้ามสุ่มซ้ำ" (gacha
            # really spends tickets; if it already drew but a later step broke, a retry
            # must not draw again). The brief's sketch dropped that flag - restored here
            # as s.gacha_status == "-", the dataclass default that reset_token() leaves
            # untouched and that only _gacha() itself ever changes. Without this, attempt
            # 2 re-spends real tickets whenever attempt 1 got past gacha but failed after.
            if cfg.get("gacharanger") and s.gacha_status == "-":
                _gacha(s, cfg)   # ตั้ง s.gacha_status เองจากผลจริง ห้ามเขียนทับ
            _account_info(s)
            # Original routed a session that drew a target ranger to backup/ instead of
            # output/: gotTarget = any(RANGERSCONFIG.get(code.lower()) for code in
            # gachaUnits) - the same membership test draw_with_ticket's own
            # stop_when_found uses. The brief's sketch always returned dest="output" and
            # never reached Outcome's own documented "backup" case; nothing in tasks 8/9's
            # briefs produces "backup" either, so without this check that destination is
            # permanently unreachable. RANGERSCONFIG's new home is cfg["_rangers_config"]
            # (engine_main.load_config, task 9).
            targets = cfg.get("_rangers_config") or {}
            dest = "backup" if any(targets.get(code.lower()) for code in s.gacha_units) else "output"
            return Outcome(dest=dest, name=_export_name(s), status="OK")
        except Exception as err:        # ทุกความพลาดคือ "ลองใหม่ได้" จนกว่าจะครบ MAX_ATTEMPTS
            last = str(err)
    return Outcome(dest="login failed", status="FAIL", error=last)


MODES = {
    "ranger_api_Login": run_login,
}


def run(mode: str, s: AccountSession, cfg: dict) -> Outcome:
    flow = MODES.get(mode)
    if flow is None:
        # สะกดผิดต้องดังออกมา ไม่ใช่ตกไปใช้โหมดปริยายแล้วผู้ใช้ได้ผลผิดโดยไม่รู้ตัว
        raise ValueError("unknown mode %r (expected one of %r)" % (mode, sorted(MODES)))
    return flow(s, cfg)
