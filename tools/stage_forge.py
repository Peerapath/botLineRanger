r"""Clear LINE Rangers main stages over the API (headless) - forged battle save, no gameplay.

    python tools/stage_forge.py --acct roster/accounts/account-T0FF...json            # DRY RUN
    python tools/stage_forge.py --acct roster/accounts/account-T0FF...json --confirm  # -> st150
    python tools/stage_forge.py --xml bot/input/40d2cf61.xml --to 80 --confirm
    python tools/stage_forge.py --cookie "LF_AC=..." --from 1 --to 20 --confirm

The rangers server rate-limits, so stages are spaced by --delay seconds (default 3, plus jitter) and
rangers_api backs off on 429/503 and on the per-account HTTP 400/errorCode 429 (ratelimit.py), so
--delay 0 is safe; the default keeps a polite per-account pace.

Exit code tells a multi-account runner what happened: 0 done, 2 next stage locked, 3 out of hearts,
4 token rejected (401 - relogin first), 5 flagged by the server (102204 - drop the account),
6 other failure. The last stdout line is a JSON summary (never contains the token).

Per stage (verified live 2026-09-19: a fresh tutorial-skipped guest cleared st01..st151 back to back,
level 1 -> 86, no heart ever ran out):
  1. POST /stage/enter/{stc}  -> battleSn, rsaKeyBase{modulus,exponent}, enemyTowerHp
     (a guest still inside the tutorial gets no battleSn there; fall back to
      /tutorial/stage/enter/{stc}?tutorialType=START)
  2. body = a genuine captured battleLog (bm/bt/e/enemies/tt - reused for EVERY stage) plus
       stc, pt=1
       atw   = str(max(999999, towerHp*3 + 10000))    damage dealt to the enemy tower
       sn_e  = RSA(str(battleSn))   win_e = RSA("true")
       icu   = base64(iv + AES-128-CBC(HM16(HM16(rsn) + HM16(battleSn)), HM16(modulus)))
     RSA = textbook RSA_NO_PADDING with this enter's key, plaintext right-padded with spaces.
     HM16(s) = md5(s).hexdigest().upper()[:16].
     icu is THE check: leaving it out, random bytes, or the wrong rsn all lose silently.
     `i_e` (item list) must be absent or RSA("[]") - RSA("") or a booster dict makes it a silent loss.
     atw is optional (absent/"0"/"" still win), but a value below the tower HP is rejected (102205).
  3. POST /stage/save/{battleSn}/{stc}?reqId=<unix>, compact + key-sorted JSON, no sooner than pt
     after the enter: a save that claims more play time than really passed gets 400/102205 (battle
     stays open, no heart spent, the same battleSn can be re-posted later). We wait pt+0.5 s.
  A win is battleResult.isCleared == true. A loss is a 200 with that key absent and rewardExp 0 -
  and it still costs a heart.
  The server keeps pt as the stage's firstClearSec/minClearSec, so the default pt=1 leaves a
  1-second clear on record. A larger --pt looks more natural but every stage then takes pt seconds.

Needs pycryptodome (AES) - already a bot dependency.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import random
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402
import ratelimit  # noqa: E402

from Crypto.Cipher import AES  # noqa: E402
from Crypto.Util.Padding import pad  # noqa: E402

LAST_STAGE = 150
# The rangers server rate-limits: pause between stages (plus jitter, so parallel accounts do not
# march in lockstep). rangers_api.call already backs off on the 429/503 it returns when pushed.
DEFAULT_DELAY = 3.0
ERR_AREA_LOCKED = 102200         # enter: the stage's whole area is not open yet
ERR_STAGE_LOCKED = 102201        # enter: previous stage not cleared
ERR_SUSPECTED_ABUSING = 102204   # save: the server's cheat verdict - never re-forge after it
# save: hard reject of the battle data - pt longer than the real time since enter, 0 < atw < tower HP,
# or no battle log at all. The battle stays open and no heart is spent, so the same battleSn can be
# re-posted (which fixes the timing case).
ERR_BAD_BATTLE = 102205
LOCKED = (ERR_AREA_LOCKED, ERR_STAGE_LOCKED)
NET_ERRORS = (OSError, http.client.HTTPException)

# A genuine winning st02 battleLog pulled from battle_tempsave.db (SQLCipher) on 2026-09-19. The server
# does not re-simulate it, so the same log is replayed for every stage; the per-battle fields
# (stc/pt/atw/sn_e/win_e/icu) are rebuilt on each save.
TEMPLATE = {
    "bm": 0,
    "bt": "eNqLVjLACZR0RiVHJaGShoYwjiE+nYZk22mIppd4Yw1pFQiGQyLKDCk0ltSwNaSNsTRPJoMiVmK5ABEo/6o=",
    "e": [
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "2.03", "v": "u90007-abby"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "3.03", "v": "u90025-jerome"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "3.03", "v": "u90005-nut"},
        {"cen": 0, "en": 0, "et": "TOWER_DMG_HP", "t": "12.80", "v": "2498/12502"},
        {"cen": 0, "en": 0, "et": "TOWER_DMG_HP", "t": "14.73", "v": "2498/10004"},
        {"cen": 0, "en": 0, "et": "TOWER_DMG_HP", "t": "16.70", "v": "2498/7506"},
        {"cen": 0, "en": 0, "et": "TOWER_DMG_HP", "t": "18.63", "v": "2498/5008"},
        {"cen": 1300, "en": 400, "et": "UNIT", "t": "19.32", "v": "u2030e-jessica"},
        {"cen": 903, "en": 750, "et": "UNIT", "t": "19.35", "v": "u095e-james"},
        {"cen": 516, "en": 467, "et": "LEVELUP", "t": "22.93", "v": "100.889999"},
        {"cen": 563, "en": 541, "et": "LEVELUP", "t": "27.68", "v": "107.639999"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "32.08", "v": "u90007-abby"},
        {"cen": 629, "en": 610, "et": "UNIT", "t": "33.00", "v": "u021e-brown"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "33.07", "v": "u90005-nut"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "35.07", "v": "u90025-jerome"},
        {"cen": 0, "en": 0, "et": "TOWER", "t": "35.60", "v": "msl"},
        {"cen": 550, "en": 400, "et": "UNIT", "t": "37.67", "v": "u2030e-jessica"},
        {"cen": 638, "en": 629, "et": "LEVELUP", "t": "41.95", "v": "113.849998"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "46.27", "v": "u90007-abby"},
        {"cen": 0, "en": 410, "et": "ENEMY", "t": "47.25", "v": "u90025-jerome"},
        {"cen": 659, "en": 610, "et": "UNIT", "t": "47.28", "v": "u021e-brown"},
        {"cen": 0, "en": 0, "et": "END", "t": "47.75", "v": ""},
    ],
    "enemies": ["u90005-nut", "u90007-abby", "u90025-jerome"],
    "tt": "team1",
}


def stage_code(number: int) -> str:
    return "st%02d" % number


def stage_number(code: str) -> int:
    return int(code[2:])


def HM16(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest().upper()[:16]


def rsa_nopad(text: str, n: int, e: int) -> str:
    """base64(textbook RSA of `text` right-padded with spaces to the modulus size)."""
    size = (n.bit_length() + 7) // 8
    data = text.encode()
    if len(data) > size:
        raise ValueError("plaintext %d bytes > modulus %d bytes" % (len(data), size))
    block = data + b" " * (size - len(data))
    return base64.b64encode(pow(int.from_bytes(block, "big"), e, n).to_bytes(size, "big")).decode()


def icu_field(rsn: str, battle_sn, modulus_dec: str, iv: bytes | None = None) -> str:
    key = HM16(HM16(rsn) + HM16(str(battle_sn))).encode()
    iv = iv or os.urandom(16)
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(HM16(modulus_dec).encode(), 16))
    return base64.b64encode(iv + ciphertext).decode()


def build_save_body(enter_result: dict, stc: str, rsn: str, pt: int = 1,
                    template: dict | None = None, iv: bytes | None = None) -> bytes:
    """The /stage/save body for one enter response (compact, key-sorted JSON bytes)."""
    key = enter_result["rsaKeyBase"]
    n = int(key["modulus"])
    e = int(key.get("exponent") or key.get("publicExponent"))
    battle_sn = enter_result["battleSn"]
    tower = int(enter_result.get("enemyTowerHp") or 0)
    body = dict(template or TEMPLATE)
    body.update({
        "stc": stc,
        "pt": pt,
        "atw": str(max(999999, tower * 3 + 10000)),
        "sn_e": rsa_nopad(str(battle_sn), n, e),
        "win_e": rsa_nopad("true", n, e),
        "icu": icu_field(rsn, battle_sn, key["modulus"], iv),
    })
    body.pop("i_e", None)
    return json.dumps(dict(sorted(body.items())), separators=(",", ":")).encode()


def _result(data):
    if isinstance(data, dict):
        return data.get("result") if isinstance(data.get("result"), dict) else data
    return {}


def player_info(cookie: str) -> dict:
    status, data = call(cookie, "/player/units/equip?inven=false&team=false&deck=false")
    player = _result(data).get("player") or {}
    if status != 200 or not player:
        raise RuntimeError("player lookup failed (HTTP %s) %s" % (status, str(data)[:200]))
    return player


def hearts(player: dict) -> int:
    return int(((player or {}).get("hearts") or {}).get("total") or 0)


def heart_wait(player: dict) -> float:
    """Seconds until the next heart regenerates."""
    now = time.time() * 1000
    if player.get("nextHeartMills"):
        return player["nextHeartMills"] / 1000.0
    duration = player.get("heartDuration") or 420000
    first_heart = (player.get("heartEnded") or now) - (max(1, player.get("maxHeart") or 1) - 1) * duration
    wait = (first_heart - now) / 1000.0
    return wait if wait > 0 else duration / 1000.0


def _error_code(data):
    return data.get("errorCode") if isinstance(data, dict) else None


def enter(cookie: str, stc: str):
    """Return (status, result, errorCode). result has battleSn on success."""
    body = json.dumps({"friendUid": "", "guildMemberUid": "", "itemCodes": [], "mercenaryUid": "",
                       "stageCode": stc, "teamType": "team1"}, separators=(",", ":")).encode()
    status, data = call(cookie, "/stage/enter/%s" % stc, "POST", body)
    result = _result(data)
    if result.get("battleSn"):
        return status, result, None
    error = _error_code(data)
    if (error in LOCKED or error == ERR_SUSPECTED_ABUSING or status in (401, 429) or status >= 500
            or ratelimit.is_app_429(status, data) is not None):
        return status, result, error   # transient/locked: never try the tutorial route
    # a guest still inside the tutorial only gets a battle from the tutorial route
    status2, data2 = call(cookie, "/tutorial/stage/enter/%s?tutorialType=START" % stc, "POST", b"{}")
    result2 = _result(data2)
    if result2.get("battleSn"):
        return status2, result2, None
    return status, result, error


def cancel(cookie: str, battle_sn, stc: str):
    """Close a battle we entered but will not save (best effort - it also expires on its own)."""
    try:
        call(cookie, "/stage/cancel/%s/%s" % (battle_sn, stc), "POST", {})
    except NET_ERRORS:
        pass


def clear_stage(cookie: str, stc: str, rsn: str, pt: int = 1) -> tuple[bool, dict]:
    """Enter -> wait pt -> save one stage. Returns (cleared, info)."""
    status, result, error = enter(cookie, stc)
    if not result.get("battleSn"):
        info = {"stage": stc, "step": "enter", "http": status, "errorCode": error}
        if status == 401:
            info["step"] = "auth"
        elif error not in LOCKED and error != ERR_SUSPECTED_ABUSING:
            try:
                player = player_info(cookie)
            except (RuntimeError,) + NET_ERRORS:
                player = {}
            if player and hearts(player) < 1:
                info.update(step="hearts", wait_s=heart_wait(player))
        return False, info
    player = result.get("player") or {}
    if result.get("isEnterable") is False or (player.get("hearts") and hearts(player) < 1):
        cancel(cookie, result["battleSn"], stc)
        return False, {"stage": stc, "step": "hearts", "http": status, "wait_s": heart_wait(player)}
    # time from the enter that issued this battleSn - enter's own retries/fallback must not eat the margin
    entered = time.time()
    body = build_save_body(result, stc, rsn, pt)
    path = "/stage/save/%s/%s" % (result["battleSn"], stc)
    for _ in range(3):
        wait = entered + pt + 0.5 - time.time()
        if wait > 0:
            time.sleep(wait)
        status, data = call(cookie, "%s?reqId=%d" % (path, int(time.time())), "POST", body)
        error = _error_code(data)
        if error != ERR_BAD_BATTLE and ratelimit.is_app_429(status, data) is None:
            break
        # 102205 or a per-account rate-limit rejection: the battle is still open and no heart was
        # spent, so wait the margin again and re-post the same battleSn
        entered = time.time()
    battle = _result(data).get("battleResult") or {}
    after = battle.get("afterRewardPlayer") or {}
    info = {"stage": stc, "step": "save", "http": status,
            "errorCode": error if isinstance(data, dict) else str(data)[:120],
            "tower": result.get("enemyTowerHp"), "exp": battle.get("rewardExp"),
            "coin": battle.get("rewardedCoin"), "first": battle.get("isFirstComplete"),
            "level": after.get("level"), "hearts": hearts(after) if after.get("hearts") else None}
    return bool(battle.get("isCleared")), info


def frontier(cookie: str) -> dict:
    """/stage/last's lastStage: the highest stage ever ENTERED and whether it is cleared yet.

    player.lastStageCode moves on enter, not on clear (a fresh guest already reads "st01", and a
    stage that was only entered counts), so it cannot tell "cleared up to N" from "entered N".
    lastStage.complete can: {"stageCode": "st02", "complete": true, "clearCount": 1, ...}.
    """
    status, data = call(cookie, "/stage/last")
    if status != 200:
        return {}
    return _result(data).get("lastStage") or {}


def start_stage(cookie: str, player: dict) -> int:
    """First stage to play: the frontier stage, or the one after it once it is cleared."""
    last = frontier(cookie)
    code = last.get("stageCode") or player.get("lastStageCode") or "st01"
    return stage_number(code) + (1 if last.get("complete") else 0)


def credited(cookie: str, number: int) -> bool:
    """True when the frontier is stage `number` and the server has it as cleared."""
    last = frontier(cookie)
    return last.get("stageCode") == stage_code(number) and bool(last.get("complete"))


# why clear_range stopped -> process exit code, so a multi-account runner knows what to do next
EXIT_CODES = {"done": 0, "locked": 2, "hearts": 3, "auth": 4, "flagged": 5, "failed": 6}


def clear_range(cookie: str, rsn: str, first: int, last: int, pt: int = 1, retries: int = 2,
                max_heart_wait: float = 600, delay: float = DEFAULT_DELAY,
                progress=print) -> tuple[int, str]:
    """Clear stages first..last in order. Returns (highest stage cleared or first-1, stop reason).

    Stops at a locked stage, the server's cheat verdict, a rejected save, or a second plain loss on
    the same stage (a loss costs a heart and the forge is deterministic, so blind retries only burn
    hearts). Enter failures and network errors are retried with backoff; running out of hearts waits
    for regen when the next heart is at most `max_heart_wait` seconds away. `delay` (+ jitter) is
    paused between stages so a long run stays under the server's rate limit.
    """
    cleared = first - 1
    for number in range(first, last + 1):
        stc = stage_code(number)
        if number > first and delay > 0:
            time.sleep(delay + random.uniform(0, min(1.0, delay)))
        losses = attempt = heart_waits = 0
        while True:
            try:
                ok, info = clear_stage(cookie, stc, rsn, pt)
            except NET_ERRORS as err:
                ok, info = False, {"stage": stc, "step": "network", "error": repr(err)}
            if ok:
                progress("%s cleared  level=%s exp=+%s coin=+%s hearts=%s" % (
                    stc, info.get("level"), info.get("exp"), info.get("coin"), info.get("hearts")))
                cleared = number
                break
            error, step = info.get("errorCode"), info["step"]
            if step == "hearts":
                wait = info.get("wait_s") or 0
                if wait > max_heart_wait or heart_waits >= 3:
                    progress("%s out of hearts - next heart in %.0fs, stopping" % (stc, wait))
                    return cleared, "hearts"
                heart_waits += 1
                progress("%s out of hearts - waiting %.0fs for regen" % (stc, wait + 5))
                time.sleep(wait + 5)
                continue
            attempt += 1
            progress("%s FAILED (try %d/%d) %s" % (stc, attempt, retries + 1, json.dumps(info)))
            if step == "auth":
                return cleared, "auth"
            if error == ERR_SUSPECTED_ABUSING:
                return cleared, "flagged"
            if error in LOCKED:
                return cleared, "locked"
            if step == "save":
                if info.get("http") != 200:
                    return cleared, "failed"
                losses += 1
                if losses > 1:
                    return cleared, "failed"
            if attempt > retries:
                return cleared, "failed"
            time.sleep(min(30, 2 * 2 ** attempt))
            # a save that errored on our side may still have been credited (e.g. a re-sent request)
            if step != "enter":
                try:
                    if credited(cookie, number):
                        progress("%s was credited despite the error" % stc)
                        cleared = number
                        break
                except NET_ERRORS:
                    pass
    return cleared, "done"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    parser.add_argument("--acct", help="roster/accounts/account-*.json written by new_account.py")
    parser.add_argument("--rsn", help="player rsn (looked up from the API when omitted)")
    parser.add_argument("--from", dest="first", type=int,
                        help="first stage number (default: the one after lastStageCode)")
    parser.add_argument("--to", dest="last", type=int, default=LAST_STAGE,
                        help="last stage number (default %d)" % LAST_STAGE)
    parser.add_argument("--pt", type=int, default=1, help="claimed play time in seconds (default 1)")
    parser.add_argument("--max-heart-wait", type=float, default=600,
                        help="wait for heart regen up to this many seconds (default 600)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help="seconds to pause between stages, plus jitter - the server rate-limits "
                             "(default %.0f; 0 = as fast as possible)" % DEFAULT_DELAY)
    parser.add_argument("--confirm", action="store_true", help="actually play (default is a dry run)")
    args = parser.parse_args()

    # exactly one explicit account: resolve_cookie would otherwise fall back to the newest token in
    # captures/ - usually the main account, the last thing to forge 150 saves on by accident
    sources = [bool(args.cookie), bool(args.xml), bool(args.acct), bool(args.from_device)]
    if sum(sources) != 1:
        parser.error("give exactly one of --cookie / --xml / --acct / --from-device")
    if args.acct:
        with open(args.acct, "r", encoding="utf-8") as handle:
            acct = json.load(handle)
        if not acct.get("lf_ac"):
            raise SystemExit("account has no session (status=%s) - run new_account.py --resume or "
                             "tools/relogin.py first" % acct.get("status"))
        cookie = "LF_AC=" + acct["lf_ac"]
    else:
        cookie = resolve_cookie(args)

    try:
        player = player_info(cookie)
    except RuntimeError as err:
        raise SystemExit(str(err))
    # icu is keyed on the rsn and a wrong one is a silent loss, so trust the server's value
    rsn = args.rsn or player.get("rsn")
    if not rsn:
        raise SystemExit("no rsn for this account")
    print("rsn=%s level=%s lastStageCode=%s hearts=%s" % (
        rsn, player.get("level"), player.get("lastStageCode"), hearts(player)))
    if not args.confirm:
        print("DRY RUN - re-run with --confirm to clear up to st%02d" % args.last)
        return
    first = args.first or start_stage(cookie, player)
    if first > args.last:
        print("nothing to do (next stage st%02d is past --to)" % first)
        return
    print("clearing st%02d..st%02d" % (first, args.last))
    cleared, reason = clear_range(cookie, rsn, first, args.last, args.pt,
                                  max_heart_wait=args.max_heart_wait, delay=args.delay)
    try:
        after = player_info(cookie)
    except (RuntimeError,) + NET_ERRORS:
        after = {}
    summary = {"rsn": rsn, "first": first, "cleared": cleared, "to": args.last, "stop": reason,
               "levelBefore": player.get("level"), "levelAfter": after.get("level"),
               "lastStageCode": after.get("lastStageCode"), "hearts": hearts(after) if after else None}
    print("\ncleared up to %s | level %s -> %s | stop=%s" % (
        stage_code(cleared) if cleared >= first else "(none)", player.get("level"),
        after.get("level", "?"), reason))
    print(json.dumps(summary))
    sys.exit(EXIT_CODES[reason])


if __name__ == "__main__":
    main()
