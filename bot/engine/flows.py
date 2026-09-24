"""flow ของแต่ละ play mode - ฟังก์ชันล้วนที่รับ AccountSession เป็นตัวแรก

ห้ามฟังก์ชันไหนในไฟล์นี้อ่านหรือเขียนตัวแปรระดับโมดูลที่เปลี่ยนค่าได้ ทั้งไฟล์ถูกเรียก
จากหลายเธรดพร้อมกันบนคนละบัญชี
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))

import rangers_api          # noqa: E402
import relogin             # noqa: E402
import rewards             # noqa: E402
from device_session import decrypt_lfac   # noqa: E402

from .session import AccountSession, Outcome   # noqa: E402

MAX_ATTEMPTS = 3

# Gap (seconds) before each retry of a transient failure - one entry per gap between
# MAX_ATTEMPTS attempts, so len() == MAX_ATTEMPTS - 1. relogin.login() already backs off
# 2/4/8s internally for 429 / app-429 / 5xx before it raises (tools/relogin.py
# RETRY_WAITS), so this is not stacked on top of a wait that already happened - it is the
# wait for everything else that can fail in this loop: network hiccups in _fetch_home /
# _claim_rewards / _gacha / _account_info, or _relogin failing before it even reaches
# relogin.login (e.g. a bad account file).
RETRY_BACKOFF_SECONDS = (5.0, 15.0)


class PermanentFailure(Exception):
    """The server's real answer about this account, not a transient condition - e.g. a
    401 from relogin.login(), confirmed after a cc renew-and-retry. tools/relogin.py:91:
    "401 ไม่ retry (เป็นคำตอบจริงของเซิร์ฟเวอร์ ไม่ใช่ปัญหาชั่วคราว)". run_login must not
    spend a second and third attempt getting the same answer against a shared, measured
    2-per-IP-per-minute auth quota.
    """


class LevelGateFailure(Exception):
    """GenID's freshly-minted account never reached leveltarget - retryable exactly like
    any other transient failure (global constraint 10: this is "รอคิว", not "พัง" - hearts
    ran out, a stage locked, a play failed, for reasons that have nothing to do with
    whether this identity could ever work). The original (startBotGenID_API_headless)
    raises here too and lets its own attempt loop catch it, minting an entirely fresh
    account on the next try instead of ending the session on attempt 1 ("attempt ใหม่ =
    สร้างบัญชีใหม่สด (มินต์ก่อนหน้าถ้าพังหลัง signup ก็ปล่อยทิ้ง)" - _create_account's own
    docstring). Carries `status` so the LAST attempt's Outcome can still say LOWLV instead
    of the generic FAIL every other exception produces in this loop.
    """

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


class AccountClaimRegistry:
    """Guards one game account (by rsn) from being processed by two different account
    *files* in the same run - bot/input/ has 24,279 files and two of them can point at the
    same underlying game account (observed: a0bfb087, two files, gacha'd twice). Without
    this, both files claim rewards and draw gacha on that one account, spending a second
    real ticket for nothing.

    Thread-pool replacement for the original's os.O_CREAT|O_EXCL marker file under
    src/split-ID/ (_claimAccountThisRun/_releaseAccountThisRun, botLineRanger.py:3255) - a
    thread pool has no separate processes or filesystem races to coordinate, just one Lock
    over one in-memory set.
    """

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = threading.Lock()

    def claim(self, account_id: str) -> bool:
        """True if this caller is the first this run to claim account_id.

        Original (_claimAccountThisRun, botLineRanger.py:3262-3263): "ระบุบัญชีไม่ได้ ก็ทำ
        ตามปกติ ดีกว่าข้ามไปเฉยๆ" - an account this run can't identify (falsy id) always
        proceeds normally rather than being blocked by a guard that cannot tell accounts
        apart.
        """
        if not account_id:
            return True
        with self._lock:
            if account_id in self._claimed:
                return False
            self._claimed.add(account_id)
            return True

    def release(self, account_id: str) -> None:
        """Give back a claim that was never actually spent (rewards/gacha never ran under
        it), so a duplicate file for the same account can run instead of being blocked by
        a claim nobody is using any more."""
        if not account_id:
            return
        with self._lock:
            self._claimed.discard(account_id)


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
        if status == 401:
            # Confirmed twice above (the original cc, then a renewed one) - the same bar
            # process_file() in tools/relogin.py uses for its "rejected" bucket, the only
            # outcome that script treats as a real answer about this account rather than
            # an error worth a bare retry.
            raise PermanentFailure("relogin rejected (HTTP 401)")
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


# ที่ _create_account เขียนไฟล์ .xml ของบัญชีใหม่ที่เพิ่ง mint - CWD-relative เหมือนโค้ดเดิมทั้งไฟล์
# (os.path.join("execute", FILENAME) ฯลฯ ใน botLineRanger.py) และเหมือน sketch เดิมของ brief
# (os.path.join(os.getcwd(), "execute")) แค่ยกขึ้นเป็นตัวแปรระดับโมดูลตามข้อบังคับข้อ 3 (เทสต์ต้อง
# monkeypatch ได้) นี่คือค่าคงที่ที่อ่านอย่างเดียว ไม่มีเธรดไหนเขียนทับมันขณะรัน จึงไม่ใช่ mutable
# state ที่ข้อบังคับข้อ 1 ห้าม (เหมือน MAX_ATTEMPTS/RETRY_BACKOFF_SECONDS ข้างบน) - ตอน Task 9 ต่อสาย
# engine_main จริง ต้องชี้ค่านี้ไปที่ root เดียวกับที่ WorkQueue(root=...) ใช้ (bot/engine/queue.py)
# เหมือนที่ต้องยัด cfg["_rangers_config"] ให้ _account_info (ดู run_login's docstring ด้านบน)
EXECUTE_DIR = os.path.join(os.getcwd(), "execute")


def _level_up(s: AccountSession, cfg: dict) -> str:
    """เล่น st01 ซ้ำจนถึง leveltarget - ย้ายมาจาก apiLevelUpByStage1()

    วัดจริง: st01 จ่าย 600 exp ทุกรอบ เลเวล 1 -> 3 ใช้สองรอบ และการเลเวลอัพเติม heart
    ให้เอง (5 -> 9 -> 13) จึงไม่มีทาง heart หมดก่อนถึงเป้า

    คืน reason ("done"/"hearts"/"flagged"/...) จาก stage_forge.level_up - ต้นฉบับ
    (startBotLevel3_API_headless) เช็ค result["stop"] == "flagged" แยกจาก level<target เพื่อ
    ตั้ง sessionStatus "FLAG" กับ "LOWLV" ต่างกัน stage_forge.level_up คืน "flagged" ได้เฉพาะตอน
    level ยังไม่ถึง target เท่านั้น (ทุก successful clear เช็ค level>=target แล้ว return "done"
    ก่อนจะไปเช็ค error ต่อ - อ่านโค้ดจริงที่ tools/stage_forge.py:392-398) ดังนั้น "flagged" ไม่มี
    ทางมาพร้อม level ที่ถึงเป้าแล้ว แต่ run_level3/run_genid ยังต้องอ่านค่านี้ไว้ตั้ง status ให้
    ตรงกับต้นฉบับ ไม่ใช่แค่เดา "LOWLV" เสมอ
    """
    import stage_forge
    target = int(cfg.get("leveltarget") or 3)
    level, _plays, reason = stage_forge.level_up(s.cookie, s.rsn, target)
    s.level = int(level or s.level)
    return reason


def _create_account(s: AccountSession, cfg: dict) -> None:
    """สร้าง guest ใหม่ผ่าน /v12.3/signup/platform - ย้ายมาจาก _headlessCreateAccount()

    make_account เขียนไฟล์ .xml ให้เองเมื่อได้ write_xml_dir และคืน dict ที่มี lf_ac/rsn แต่ไม่คืน
    path ของไฟล์ (เปิด tools/new_account.py::write_account_xml ดูจริงแล้ว: name =
    account.get("rsn") or account.get("gameId"); path = xml_dir/name.xml - เรียกซ้ำที่นี่จึงเขียน
    ทับไฟล์เดิมด้วยเนื้อหาเดิม ไม่ใช่ไฟล์ใหม่ซ้อน มีไว้แค่ให้ได้ path คืนมาเท่านั้น)

    status == "pending-login" แปลว่าสร้างเครดิทเชียลได้แต่ล็อกอินไม่ผ่าน - เครดิทยังถูก
    เก็บไว้แล้วกู้ได้ด้วย --resume ห้ามถือว่าเป็นความสำเร็จ

    ต่างจาก _relogin ที่ reset_token() เคลียร์แค่โทเค็นของบัญชีเดิม - รอบนี้ identity ทั้งใบเปลี่ยน
    ("attempt ใหม่ = สร้างบัญชีใหม่สด (มินต์ก่อนหน้าถ้าพังหลัง signup ก็ปล่อยทิ้ง)" - คอมเมนต์เดิม
    ของ startBotGenID_API_headless) gacha_status/gacha_units จึงต้องล้างด้วย ไม่งั้นบัญชีที่เพิ่ง
    mint จะโดนสถานะของบัญชีก่อนหน้า (ที่พังกลางทางหลังสุ่มไปแล้วแล้วถูกทิ้ง) หลอกว่าเคยสุ่มไปแล้ว -
    ทำให้ข้ามกาชาจริงของบัญชีนี้ไปเฉย ๆ (ถ้า run_genid guard ด้วย gacha_status=="-" แบบเดียวกับ
    run_login) และแย่กว่านั้นคือเอา gacha_units ของบัญชีเก่ามาตัดสิน backup/output ให้บัญชีนี้ผิดๆ
    """
    import new_account
    s.reset_token()
    s.gacha_status, s.gacha_units = "-", []
    # Finding 2 (Task 9, review round 1): this used to read only the module-level EXECUTE_DIR
    # above, never cfg["_execute_dir"] that engine_main.py actually sets - harmless only
    # because both are os.getcwd()-based and computed back to back with no chdir between,
    # in the one process this ran in today. Falls back to the module value so CLI use and
    # every test that predates this fix (monkeypatch.setattr(flows, "EXECUTE_DIR", ...),
    # see test_flows_modes.py) keep behaving exactly as before.
    execute_dir = cfg.get("_execute_dir", EXECUTE_DIR)
    acct = new_account.make_account(write_xml_dir=execute_dir, skip_tut=True)
    if acct.get("status") != "ready" or not acct.get("lf_ac"):
        raise RuntimeError("signup incomplete (status=%s)" % acct.get("status"))
    s.src = new_account.write_account_xml(acct, execute_dir)
    s.cookie = "LF_AC=" + acct["lf_ac"]
    s.rsn = acct.get("rsn") or acct.get("gameId") or ""
    s.level = 1


def _force_stage(s: AccountSession, cfg: dict) -> str:
    """ดันด่านถึง settings.stageend - ย้ายมาจาก apiForceStage()

    clear_range รับ first และ last เป็นเลขด่าน (ไม่ใช่ stageCode) จุดเริ่มมาจาก start_stage()
    ซึ่งอ่านด่านล่าสุดของบัญชีจาก /stage/last - เริ่มที่ 1 เสมอคือการเล่นซ้ำด่านที่ผ่านแล้วทั้งหมด
    โดยจ่าย heart จริงทุกด่าน

    คืน stop reason ของ clear_range ("done" เมื่อไม่มีอะไรต้องเล่นเพิ่ม) - ต้นฉบับ
    (startBotStage_API_headless) เช็ค result["stop"] == "flagged" แล้วส่งไฟล์ไป 'login failed'
    แทน output/ ถ้าทิ้งค่านี้ไป (ตามที่ sketch เดิมของ brief ทำ - เรียก clear_range แล้วไม่เก็บ
    ค่าที่คืนมาเลย) บัญชีที่เซิร์ฟเวอร์ตีธงว่าโกงจะหลุดไปอยู่ output/ ปนกับไอดีที่ขายได้จริง

    เคลียร์ด่านได้ก็แปลว่า exp/level อาจขยับ - ต้นฉบับ (apiForceStage) อ่าน player_info ใหม่หลัง
    clear_range เพื่อได้ level หลังดัน (levelAfter) ซึ่งไหลต่อไปเป็น level ในชื่อไฟล์ที่ export
    ผ่าน getAccoutInfo()'s currentLevel() ถ้าไม่รีเฟรช s.level ตรงนี้ ชื่อไฟล์จะโชว์เลเวลก่อนดัน
    ด่าน (จาก _fetch_home) ทั้งที่ตอนนี้เลเวลขยับไปแล้วจริง ๆ
    """
    import stage_forge
    player = stage_forge.player_info(s.cookie)
    first = stage_forge.start_stage(s.cookie, player)
    last = int(cfg.get("stageend") or 150)
    if first > last:
        return "done"          # ผ่านเป้าไปแล้ว ไม่มีอะไรต้องทำ
    _cleared, reason = stage_forge.clear_range(s.cookie, s.rsn, first, last)
    try:
        s.level = int(stage_forge.player_info(s.cookie).get("level") or s.level)
    except Exception:
        pass    # อ่านเลเวลใหม่ไม่ได้ ไม่ใช่เหตุให้ทั้ง session พัง (เหมือน apiForceStage เดิม)
    return reason


# --- flow ต่อโหมด ---

def run_login(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    # Finding 2 (review round 1): see AccountClaimRegistry's own docstring for the guard
    # this restores (original: _claimAccountThisRun/_releaseAccountThisRun,
    # botLineRanger.py:3255, used in startBotLogin_API_headless:8042). Absent from cfg
    # (CLI use today, every test that predates this fix) claims stays None and every branch
    # below behaves exactly as it did before - a pure no-op.
    claims = cfg.get("_account_claims")
    account_id = ""      # claimed once per session, across every retry of the same file
    duplicate = False
    did_process = False

    def _release_unclaimed_account() -> None:
        # Original (startBotLogin_API_headless, botLineRanger.py:8109): "จองบัญชีไว้แต่สุ่ม
        # ไม่สำเร็จ ปล่อยให้ไฟล์ซ้ำของบัญชีนี้ (ถ้ามี) ได้สุ่มแทน" - only the session that
        # actually holds the claim (not a duplicate) and never got past rewards/gacha
        # under it may give it back. Safe to call from every exit point below: a no-op
        # whenever there is nothing to release.
        if claims is not None and account_id and not duplicate and not did_process:
            claims.release(account_id)

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
            if claims is not None and not account_id and s.rsn:
                # Original (_claimAccountThisRun, called from startBotLogin_API_headless
                # :8039-8042): "บัญชีนี้มีไฟล์อื่นในรอบเดียวกันทำไปแล้ว ไม่ต้องสุ่มซ้ำ (retry
                # ของ session ตัวเองไม่นับ)" - claim once, the first time s.rsn is known,
                # before rewards/gacha - not on every retry attempt of this same file.
                account_id = s.rsn
                if not claims.claim(account_id):
                    duplicate = True
                    # Original: gachaStatus = "dup-account" - a second, independent guard
                    # against a redraw, on top of `if not duplicate:` below.
                    s.gacha_status = "dup-account"
            if not duplicate:
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
                did_process = True
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
            # s.error is a non-fatal note (e.g. token write-back failed - see _relogin)
            # left by an attempt that otherwise ran to completion; nothing else in this
            # dataclass carries it back to the caller, so a successful Outcome still
            # needs to say so instead of dropping it silently.
            _release_unclaimed_account()
            return Outcome(dest=dest, name=_export_name(s), status="OK", error=s.error)
        except PermanentFailure as err:
            # The server already gave its real answer about this account (see
            # PermanentFailure above) - a second and third attempt would only spend more
            # of the shared auth quota to hear it again. Global constraint 10:
            # แยก "รอคิว" ออกจาก "พัง" - this is "พัง", not a queue to wait out.
            _release_unclaimed_account()
            return Outcome(dest="login failed", status="FAIL", error=str(err))
        except Exception as err:   # everything else is "รอคิว" - wait, then retry
            last = str(err)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
    _release_unclaimed_account()
    return Outcome(dest="login failed", status="FAIL", error=last)


def run_level3(s: AccountSession, cfg: dict) -> Outcome:
    target = int(cfg.get("leveltarget") or 3)
    last = ""
    # Finding 2 (review round 1): same guard as run_login (see AccountClaimRegistry's own
    # docstring) - the original applied it here too (startBotLevel3_API_headless:8344).
    # Absent from cfg this is a pure no-op, exactly like run_login.
    claims = cfg.get("_account_claims")
    account_id = ""      # claimed once per session, across every retry of the same file
    duplicate = False
    did_process = False

    def _release_unclaimed_account() -> None:
        # Same release check as startBotLevel3_API_headless:8417 (accountId and not
        # duplicateAccount and not gachaDone) - that line carries no comment of its own,
        # but startBotLogin_API_headless's identical check at :8108 does: "จองบัญชีไว้แต่
        # สุ่มไม่สำเร็จ ปล่อยให้ไฟล์ซ้ำของบัญชีนี้ (ถ้ามี) ได้สุ่มแทน" - only the session that
        # actually holds the claim (not a duplicate) and never got past rewards/gacha
        # under it may give it back.
        if claims is not None and account_id and not duplicate and not did_process:
            claims.release(account_id)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            s.reset_token()
            # reset_token() เพิ่งล้าง cache ทิ้ง - ยัด _rangers_config กลับเข้าไปใหม่ทุกรอบ
            # เหมือน run_login (ดู docstring ของ _account_info)
            s.cache["_rangers_config"] = cfg.get("_rangers_config")
            _relogin(s)
            _fetch_home(s)
            if claims is not None and not account_id and s.rsn:
                # Original (_claimAccountThisRun, botLineRanger.py:8344) claims here, before
                # the level gate below - the original levels up every file the same way
                # regardless of the claim (not a resource this guard protects); only
                # rewards/gacha are skipped for a file that lost the claim race.
                account_id = s.rsn
                if not claims.claim(account_id):
                    duplicate = True
                    s.gacha_status = "dup-account"   # second guard, same as run_login
            level_reason = "done"
            if s.level < target:
                level_reason = _level_up(s, cfg) or "done"
            if s.level < target:
                # ไม่ถึงเป้า = โหมดนี้ยังทำงานไม่สำเร็จ ส่งลง output ไม่ได้ (จุดประสงค์ของโหมดคือ
                # ได้ไอดีเลเวล 3 ปล่อยเลเวลต่ำปนลง output คือทำลายความหมายของโฟลเดอร์) ต้นฉบับแยก
                # "FLAG" ออกจาก "LOWLV" ตาม stop reason จริง (result["stop"] == "flagged") - ไม่ใช่
                # เดาว่า LOWLV เสมอ (level_up คืน "flagged" ได้เฉพาะตอน level ยังไม่ถึง target
                # เท่านั้น ดู _level_up's docstring จึงไม่มีทางชนกับกรณีถึงเป้าแล้ว)
                _release_unclaimed_account()
                return Outcome(dest="login failed",
                               status="FLAG" if level_reason == "flagged" else "LOWLV",
                               error="level %s < target %s (stop=%s)" % (s.level, target, level_reason))
            if not duplicate:
                _claim_rewards(s, cfg)
                # เหมือน run_login: กาชาหักตั๋วจริง ถ้าสุ่มไปแล้วแต่ขั้นหลังพัง retry ห้ามสุ่มซ้ำ
                if cfg.get("gacharanger") and s.gacha_status == "-":
                    _gacha(s, cfg)   # ตั้ง s.gacha_status เองจากผลจริง ห้ามเขียนทับ
                did_process = True
            _account_info(s)
            # เหมือน run_login: ต้นฉบับส่งบัญชีที่สุ่มได้เรนเจอร์เป้าหมายไป backup/ แทน output/ -
            # gotTarget = any(RANGERSCONFIG.get(code.lower()) for code in gachaUnits)
            targets = cfg.get("_rangers_config") or {}
            dest = "backup" if any(targets.get(code.lower()) for code in s.gacha_units) else "output"
            _release_unclaimed_account()
            return Outcome(dest=dest, name=_export_name(s), status="OK", error=s.error)
        except PermanentFailure as err:
            # เหมือน run_login: เซิร์ฟเวอร์ตอบจริงแล้วว่าบัญชีนี้ตาย (401 ยืนยันสองรอบใน _relogin) -
            # retry ซ้ำมีแต่จะเปลืองโควตา auth ร่วมเพื่อฟังคำตอบเดิม (constraint 10: แยก "รอคิว"
            # ออกจาก "พัง")
            _release_unclaimed_account()
            return Outcome(dest="login failed", status="FAIL", error=str(err))
        except Exception as err:   # อย่างอื่นทั้งหมดคือ "รอคิว" - รอแล้วลองใหม่
            last = str(err)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
    _release_unclaimed_account()
    return Outcome(dest="login failed", status="FAIL", error=last)


def run_genid(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            _create_account(s, cfg)
            # _create_account -> reset_token() เพิ่งล้าง cache ทิ้ง (บัญชีใหม่ทุก attempt) - ยัด
            # _rangers_config กลับเข้าไปใหม่ทุกรอบเหมือน run_login/run_level3
            s.cache["_rangers_config"] = cfg.get("_rangers_config")
            _fetch_home(s)
            if cfg.get("genidlevel3"):
                target = int(cfg.get("leveltarget") or 3)
                if s.level < target:
                    _level_up(s, cfg)
                if s.level < target:
                    # Finding 1 (review round 1): a bare `return` here used to end the
                    # whole flow after attempt 1 - spending only 1 of the original's
                    # budget of MAX_ATTEMPTS mints on what is a transient, "รอคิว" failure
                    # (hearts ran out, a stage locked, a play failed), not a permanent
                    # answer about this identity (constraint 10). Raising instead sends
                    # this through the exact same except/retry machinery as any other
                    # failure below, so attempt 2 and 3 mint an entirely fresh account
                    # each via _create_account at the top of this loop - see
                    # LevelGateFailure's own docstring for the original this mirrors.
                    raise LevelGateFailure(
                        "LOWLV", "level %s < target %s" % (s.level, target))
            _claim_rewards(s, cfg)
            # เหมือน run_level3 - แต่ที่ทำให้ guard นี้ยังถูกต้องสำหรับ GenID คือ _create_account
            # ล้าง gacha_status/gacha_units ทุก attempt (บัญชีใหม่ทุกครั้ง) ถ้าไม่ล้าง guard นี้จะ
            # กลายเป็นบั๊กคนละแบบ: บัญชีใหม่ที่ยังไม่เคยสุ่มเลยจะถูกข้ามกาชาไปเฉยๆ เพราะสถานะเก่าของ
            # บัญชีก่อนหน้าที่ถูกทิ้งยังค้างอยู่ (ดู docstring ของ _create_account)
            if cfg.get("gacharanger") and s.gacha_status == "-":
                _gacha(s, cfg)   # ตั้ง s.gacha_status เองจากผลจริง ห้ามเขียนทับ
            _account_info(s)
            # ต้นฉบับ (startBotGenID_API_headless) ก็มี gotTarget -> backup/ เหมือนกัน (คอมเมนต์เดิม
            # "backup เฉพาะที่กาชารอบนี้ได้เรนเจอร์เป้าหมาย...นอกนั้นลง output" - แต่
            # โค้ดจริงเรียก removeFileInExecute() ในกิ่ง else ซึ่งขัดกับคอมเมนต์ตัวเอง (ลบทิ้งเฉยๆ
            # ไม่ export เลย) และ Outcome ของ Task 8/9 ไม่มีปลายทาง "ลบทิ้ง" ให้เลือก (มีแค่
            # output/backup/login failed - ดู bot/engine/queue.py: DESTS) จึงยึดคอมเมนต์ + รูปแบบ
            # เดียวกับ run_login/run_level3: ไม่เจอเป้าหมาย -> output เหมือนเดิม ไม่ใช่ลบ - ดู
            # task-8-report.md สำหรับเหตุผลเต็ม
            targets = cfg.get("_rangers_config") or {}
            dest = "backup" if any(targets.get(code.lower()) for code in s.gacha_units) else "output"
            return Outcome(dest=dest, name=_export_name(s), status="OK", error=s.error)
        except PermanentFailure as err:
            return Outcome(dest="login failed", status="FAIL", error=str(err))
        except LevelGateFailure as err:
            last = str(err)
            if attempt >= MAX_ATTEMPTS:
                # Mint budget spent, still short of target - answer LOWLV, kept distinct
                # from the generic FAIL below exactly as before this fix (only the number
                # of attempts tried before answering has changed - see LevelGateFailure).
                return Outcome(dest="login failed", status=err.status, error=last)
            time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
        except Exception as err:
            last = str(err)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
    return Outcome(dest="login failed", status="FAIL", error=last)


def run_stage(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            s.reset_token()
            s.cache["_rangers_config"] = cfg.get("_rangers_config")
            _relogin(s)
            _fetch_home(s)
            reason = _force_stage(s, cfg)
            if reason == "flagged":
                # ต้นฉบับ (startBotStage_API_headless): บัญชีที่เซิร์ฟเวอร์ตีธงโกงย้ายไป
                # 'login failed' แทน output/ จะได้ไม่ปนกับไอดีที่ใช้ได้ - ไม่ retry ต่อ (เหมือน
                # PermanentFailure: นี่คือคำตอบจริงของเซิร์ฟเวอร์ ไม่ใช่ปัญหาชั่วคราว)
                return Outcome(dest="login failed", status="FLAG",
                               error="stage push flagged by server")
            # ต้นฉบับไม่เคยเรียก apiAcceptAllRewards ในโหมด Stage เลย (ต่างจาก Level3/GenID) -
            # ไม่มี _claim_rewards ตรงนี้จึงตรงกับของจริง ไม่ใช่ตกหล่น (ดู task-8-report.md)
            _account_info(s)
            return Outcome(dest="output", name=_export_name(s), status="OK", error=s.error)
        except PermanentFailure as err:
            return Outcome(dest="login failed", status="FAIL", error=str(err))
        except Exception as err:
            last = str(err)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
    return Outcome(dest="login failed", status="FAIL", error=last)


MODES = {
    "ranger_api_Login": run_login,
    "ranger_api_Level3": run_level3,
    "ranger_api_GenID": run_genid,
    "ranger_api_Stage": run_stage,
}


def run(mode: str, s: AccountSession, cfg: dict) -> Outcome:
    flow = MODES.get(mode)
    if flow is None:
        # สะกดผิดต้องดังออกมา ไม่ใช่ตกไปใช้โหมดปริยายแล้วผู้ใช้ได้ผลผิดโดยไม่รู้ตัว
        raise ValueError("unknown mode %r (expected one of %r)" % (mode, sorted(MODES)))
    return flow(s, cfg)
