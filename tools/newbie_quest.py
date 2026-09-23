r"""Drive the LINE Rangers "SPECIAL QUEST" (the NEWBI daily-quest chain) over the API, headless.

    python tools/newbie_quest.py --acct roster/accounts/account-*.json          # DRY RUN (show the chain)
    python tools/newbie_quest.py --xml bot/input/40cf0a20.xml --confirm         # forge as far as it can
    python tools/newbie_quest.py --from-device --device 127.0.0.1:16384 --confirm

The popup titled SPECIAL QUEST is `playerDailyQuest`, questType **NEWBI**: 29 quests in a FIXED,
STRICTLY SEQUENTIAL order. Only the one quest with `currentQuest=true` accepts progress; an action
done while another quest is current does NOT count. So the chain must be completed in order:
  do the current quest's action -> its currentCount hits completionCount -> POST the claim
  -> the next quest becomes current -> repeat.

  GET  /dailyquest                                   -> result.playerDailyQuest.contents[] (+ specialReward)
  POST /dailyquest/receive/reward/NEWBI/<index>      -> claim a completed quest
  POST /dailyquest/receive/special/reward/NEWBI      -> claim the milestone (specialReward), when unlocked

Forgeable quest types (this tool drives them):
  stage_main          clear main stages           -> stage_forge (enter + forged save)
  treasure            open an area's treasure      -> just clear that area's main stages (auto-opens)
  stage_special       clear special/daily dungeons -> /special/stage/enter + forged /special/stage/save
                                                      (same crypto as main stage; opens at account level 20)
  battle_pvp / pvp_victory  play/win a PvP battle  -> pick -> challenge -> /pvp/battle/enter/<type>
                                                      -> forged /pvp/battle/save (small DAILY limit: ec 102013)
  unit_reinforce      feed a spare unit into one  -> POST /player/units/reinforce?reqId= {invenId, materialInvenIds}
  fort_upgrade_times  upgrade the machine/tower   -> POST /player/upgrade/ {reinforceType, reinforceLevel}
  gear_equip          attach a gear to a unit      -> POST /player/units/equip/attach {unitInvenId, equipType, equipInvenId}
  bonus_quest         milestone, auto-completes   -> no action, just claim
  attendant           login attendance            -> usually already satisfied; just claim if complete

Types this tool does NOT forge yet (not-yet-reversed endpoints, and several need real other players, so
the sequential chain cannot be finished by API alone on one account):
  gear_evolve, exp_booster, complete_training, production_material (lab/item endpoints not reversed),
  guild_join, guild_help (needs another guild member), raid_play (needs a guild).
When the current quest is one of these, the tool stops and reports it (unless already complete, which it
will still claim). It also stops if a forgeable quest stops progressing (e.g. a `treasure` quest whose
area was already cleared before it became current -> forge stages IN ORDER, do not pre-advance).

Exit code: 0 all done or claimed as far as possible, 2 blocked on an unsupported quest type,
4 token rejected, 6 other error. The last stdout line is a JSON summary (never the token).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402
import stage_forge as sf  # noqa: E402

QUEST_TYPE = "NEWBI"
# quest types this tool knows how to drive (or that need no action). `treasure` is driven by
# clearing that area's main stages: the server fills+auto-opens the area treasure, so a treasure
# quest completes once enough of its area is cleared (verified: clearing st09 finished the ar01 treasure).
FORGEABLE = {"stage_main", "unit_reinforce", "fort_upgrade_times", "treasure", "gear_equip",
             "stage_special", "battle_pvp", "pvp_victory", "bonus_quest", "attendant"}
# equipItemCode prefix -> the equipType enum the attach call wants
EQUIP_TYPE = {"eq_wpn": "WEAPON", "eq_amr": "ARMOR", "eq_acc": "ACCESSORY"}
# a machine-upgrade type that a low-level account can always afford one step of
FORT_TYPE = "MACHINE_ATTACK"


def _result(data):
    if isinstance(data, dict):
        return data.get("result") if isinstance(data.get("result"), dict) else data
    return {}


def get_quest(cookie):
    """Return (playerDailyQuest dict, http status)."""
    status, data = call(cookie, "/dailyquest")
    return _result(data).get("playerDailyQuest") or {}, status


def current_quest(pdq):
    for m in pdq.get("contents") or []:
        if m.get("currentQuest"):
            return m
    return None


def claim(cookie, index):
    status, data = call(cookie, "/dailyquest/receive/reward/%s/%d" % (QUEST_TYPE, index), "POST", {})
    return status, (data.get("errorCode") if isinstance(data, dict) else None)


def claim_special(cookie):
    status, data = call(cookie, "/dailyquest/receive/special/reward/%s" % QUEST_TYPE, "POST", {})
    return status, (data.get("errorCode") if isinstance(data, dict) else None)


# ---- per-type forge actions: each does ONE unit of progress on the current quest ----------------

def _team_inven_ids(cookie):
    """invenIds currently placed on any team/deck (must not be fed as reinforce material)."""
    status, data = call(cookie, "/home")
    teams = _result(data).get("playerUnitTeams")
    ids = set()

    def scan(o):
        if isinstance(o, dict):
            if "invenId" in o:
                ids.add(o["invenId"])
            for v in o.values():
                scan(v)
        elif isinstance(o, list):
            for v in o:
                scan(v)
    scan(teams)
    return ids


def _spare_units(cookie):
    """Owned units split into (all units, safe-to-consume material units).

    A reinforce material is DESTROYED, so a material must be: a duplicate of its unitCode (keep the
    best copy), not the highest-level copy of that code, not locked, and not on a team/deck. That
    leaves the throwaway level-1 duplicates (a fresh guest hoards many, e.g. u002s-leonard).
    """
    status, data = call(cookie, "/player/units/equip?inven=true&team=true&deck=true")
    units = _result(data).get("playerUnits") or []
    on_team = _team_inven_ids(cookie)
    from collections import defaultdict
    by_code = defaultdict(list)
    for u in units:
        by_code[u.get("unitCode")].append(u)
    spares = []
    for code, group in by_code.items():
        if len(group) < 2:
            continue                      # keep the only copy
        group.sort(key=lambda u: u.get("unitLevel") or 0)   # lowest level first
        best = group[-1]                  # protect the strongest copy
        for u in group[:-1]:
            if u["invenId"] == best["invenId"]:
                continue
            if u.get("lockYn") or u["invenId"] in on_team:
                continue
            spares.append(u)
    return units, spares


def forge_reinforce(cookie):
    units, spares = _spare_units(cookie)
    if not spares:
        return False, "no spare (duplicate) unit to feed as reinforce material"
    mat = spares[0]
    # reinforce a keeper (a leveled team unit is fine as the target - it only GAINS exp)
    target = max((u for u in units if u["invenId"] != mat["invenId"]),
                 key=lambda u: u.get("unitLevel") or 0, default=None)
    if not target:
        return False, "no reinforce target"
    body = {"invenId": str(target["invenId"]), "materialInvenIds": [str(mat["invenId"])]}
    status, data = call(cookie, "/player/units/reinforce?reqId=%d" % int(time.time()), "POST", body)
    if status == 200 and isinstance(data, dict) and isinstance(data.get("result"), dict):
        return True, "reinforced %s with %s" % (target.get("unitCode"), mat.get("unitCode"))
    return False, "reinforce failed HTTP %s %s" % (status, str(data)[:120])


def forge_fort_upgrade(cookie):
    status, data = call(cookie, "/player/upgrade/status")
    lvl = (_result(data).get("playerUpgradeLevelStatus") or {}).get("machineAttackLevel") or 1
    status, data = call(cookie, "/player/upgrade/", "POST",
                        {"reinforceType": FORT_TYPE, "reinforceLevel": lvl + 1})
    if status == 200 and not (isinstance(data, dict) and data.get("errorCode")):
        return True, "upgraded %s -> %d" % (FORT_TYPE, lvl + 1)
    return False, "fort upgrade failed HTTP %s %s" % (status, str(data)[:120])


def forge_gear_equip(cookie):
    """Attach an owned gear to a unit (the reward gears from earlier quests make this possible)."""
    status, data = call(cookie, "/player/item?pGacha=false&battleAuto=false&battleManual=false"
                                "&exp=false&evolve=false&equip=true")
    gears = _result(data).get("playerEquipItems") or []
    if not gears:
        return False, "no gear item to equip (clear stages / claim earlier quest gear rewards first)"
    status, data = call(cookie, "/player/units/equip?inven=true&team=true&deck=true")
    units = _result(data).get("playerUnits") or []
    if not units:
        return False, "no unit to equip onto"
    gear = gears[0]
    etype = EQUIP_TYPE.get(str(gear.get("equipItemCode"))[:6])
    if not etype:
        return False, "unknown equip type for %s" % gear.get("equipItemCode")
    # equip onto the strongest unit (attach only adds the gear; nothing is consumed)
    unit = max(units, key=lambda u: u.get("unitLevel") or 0)
    body = {"unitInvenId": str(unit["invenId"]), "equipType": etype,
            "equipInvenId": str(gear["invenId"])}
    status, data = call(cookie, "/player/units/equip/attach", "POST", body)
    if status == 200 and isinstance(data, dict) and isinstance(data.get("result"), dict):
        return True, "equipped %s (%s) on %s" % (gear.get("equipItemCode"), etype, unit.get("unitCode"))
    return False, "gear attach failed HTTP %s %s" % (status, str(data)[:120])


ERR_NO_STAGE = 102004  # enter: no such stage (past the last released main stage) / area not open


def forge_stage(cookie, treasure=False):
    """Clear a main stage to advance a stage_main or treasure quest.

    A `stage_main` quest just counts clears, and re-clearing an already-cleared stage counts (verified),
    so we always re-clear **st01** for it - the cheapest clear and the one that grants the least EXP, so
    the account doesn't level up (per the user's request not to gain EXP from these quests).
    A `treasure` quest instead needs a NEW area's stages cleared to fill+open that area's treasure, so it
    advances the frontier; if already at the last released stage (enter -> errorCode 102004) it re-clears
    st01 as a fallback (harmless).
    """
    rsn = (sf.player_info(cookie) or {}).get("rsn")
    if not treasure:
        ok, info = sf.clear_stage(cookie, "st01", rsn)
        return (True, "cleared st01") if ok else (False, "stage clear failed %s" % json.dumps(info))
    nxt = sf.start_stage(cookie, sf.player_info(cookie))
    ok, info = sf.clear_stage(cookie, sf.stage_code(nxt), rsn)
    if ok:
        return True, "cleared %s" % sf.stage_code(nxt)
    if info.get("errorCode") == ERR_NO_STAGE:
        ok, info = sf.clear_stage(cookie, "st01", rsn)
        if ok:
            return True, "re-cleared st01 (at content boundary)"
    return False, "stage clear failed %s" % json.dumps(info)


def forge_pvp(cookie):
    """Play (and win) one PvP battle: pick -> challenge -> enter -> forged save.

    Route/body reversed from FUN_00c70988 (enter) + FUN_00c7d994 (save):
      GET  /pvp/battle/pick/opponent?pickAgain=false      -> opponentUid, pvpBattleType
      GET  /pvp/battle/challenge/<opponentUid>/<battleType>   (confirms the match)
      POST /pvp/battle/enter/<battleType>  {itemCodes:[], opponentUid, teamType} -> battleSn, rsaKeyBase
      POST /pvp/battle/save/<battleSn>/<battleType>  = stage battleLog + opponentUid + pvpBattleType, win_e=RSA(true)
    PvP has a small daily entry limit (errorCode 102013 when exhausted) - then the quest can't progress further.
    """
    pick = _result(call(cookie, "/pvp/battle/pick/opponent?pickAgain=false")[1])
    opp = pick.get("opponentUid")
    bt = pick.get("pvpBattleType") or "NORMAL"
    if not opp:
        ec = pick.get("errorCode")
        return False, "no PvP opponent (ec=%s - daily limit?)" % ec
    rsn = (sf.player_info(cookie) or {}).get("rsn") or ""
    call(cookie, "/pvp/battle/challenge/%s/%s" % (opp, bt))
    body = json.dumps({"itemCodes": [], "opponentUid": opp, "teamType": "team1"},
                      separators=(",", ":")).encode()
    status, data = call(cookie, "/pvp/battle/enter/%s" % bt, "POST", body)
    r = _result(data)
    if not r.get("battleSn"):
        return False, "PvP enter failed ec=%s (102013 = daily PvP limit reached)" % (
            data.get("errorCode") if isinstance(data, dict) else "-")
    entered = time.time()
    key = r["rsaKeyBase"]
    n = int(key["modulus"])
    e = int(key.get("exponent") or key.get("publicExponent"))
    save = json.loads(sf.build_save_body(r, opp, rsn).decode())
    save["opponentUid"] = opp
    save["pvpBattleType"] = bt
    save["win_e"] = sf.rsa_nopad("true", n, e)
    raw = json.dumps(dict(sorted(save.items())), separators=(",", ":")).encode()
    wait = entered + 1.5 - time.time()
    if wait > 0:
        time.sleep(wait)
    path = "/pvp/battle/save/%s/%s?reqId=%d" % (r["battleSn"], bt, int(time.time()))
    status, data = call(cookie, path, "POST", raw)
    if status == 200 and not (isinstance(data, dict) and data.get("errorCode")):
        return True, "played PvP vs %s" % pick.get("playerPvPOpponentInfo", {}).get("opponentDisplayName", opp[:8])
    return False, "PvP save failed HTTP %s ec=%s" % (status, data.get("errorCode") if isinstance(data, dict) else "-")


def _pick_special_stage(cookie):
    """Cheapest open special stage (daily/period dungeons open at account level 20).

    /special/area?admission=true -> areas[].specialStages[] with stageCode/needHeart/restrictionLevel.
    """
    status, data = call(cookie, "/special/area?admission=true")
    areas = _result(data).get("areas") or []
    level = (sf.player_info(cookie) or {}).get("level") or 0
    best = None
    for a in areas:
        if not a.get("useable", True):
            continue
        for s in a.get("specialStages") or []:
            if (s.get("restrictionLevel") or 0) > level:
                continue
            if best is None or (s.get("needHeart") or 99) < (best.get("needHeart") or 99):
                best = s
    return best


def forge_special_stage(cookie):
    """Clear one special stage via /special/stage/enter + a forged /special/stage/save (main-stage crypto)."""
    stage = _pick_special_stage(cookie)
    if not stage:
        return False, "no open special stage (need account level 20+ and an area available today)"
    stc = stage["stageCode"]
    rsn = (sf.player_info(cookie) or {}).get("rsn")
    body = json.dumps({"friendUid": "", "guildMemberUid": "", "itemCodes": [], "mercenaryUid": "",
                       "stageCode": stc, "teamType": "team1"}, separators=(",", ":")).encode()
    status, data = call(cookie, "/special/stage/enter/%s" % stc, "POST", body)
    r = _result(data)
    if not r.get("battleSn"):
        return False, "special enter %s failed HTTP %s ec=%s" % (
            stc, status, data.get("errorCode") if isinstance(data, dict) else "-")
    entered = time.time()
    save_body = sf.build_save_body(r, stc, rsn)
    wait = entered + 1.5 - time.time()
    if wait > 0:
        time.sleep(wait)
    path = "/special/stage/save/%s/%s?reqId=%d" % (r["battleSn"], stc, int(time.time()))
    status, data = call(cookie, path, "POST", save_body)
    battle = _result(data).get("battleResult") or {}
    if battle.get("isCleared"):
        return True, "cleared special %s (+%s exp)" % (stc, battle.get("rewardExp"))
    return False, "special save %s not cleared HTTP %s %s" % (stc, status, str(data)[:100])


def drive_current(cookie, m):
    """Advance the current quest by one action. Returns (progressed, note)."""
    t = m.get("missionType")
    if t in ("stage_main", "treasure"):
        # treasure needs a NEW area cleared; stage_main just needs clears (re-clears count)
        return forge_stage(cookie, treasure=(t == "treasure"))
    if t == "unit_reinforce":
        return forge_reinforce(cookie)
    if t == "fort_upgrade_times":
        return forge_fort_upgrade(cookie)
    if t == "gear_equip":
        return forge_gear_equip(cookie)
    if t == "stage_special":
        return forge_special_stage(cookie)
    if t in ("battle_pvp", "pvp_victory"):
        return forge_pvp(cookie)
    if t in ("bonus_quest", "attendant"):
        # nothing to do here - completes from cumulative progress / prior logins
        return False, "no direct action (%s completes passively)" % t
    return False, "unsupported quest type %s" % t


# ---- the walker ---------------------------------------------------------------------------------

def walk(cookie, confirm=True, max_actions=400, max_stall=8, progress=print):
    done = []
    actions = 0
    stall_idx, stall = None, 0     # forged an action but the current quest's count didn't move
    while True:
        pdq, status = get_quest(cookie)
        if status == 401:
            return "auth", done
        m = current_quest(pdq)
        if not m:
            progress("no current quest - chain finished or not started")
            return "done", done
        idx, t = m["index"], m["missionType"]
        # already complete -> just claim and advance
        if m.get("missionComplete") and not m.get("receiveReward"):
            if not confirm:
                progress("idx%d %s COMPLETE -> would claim" % (idx, t))
                return "dryrun", done
            cs, ec = claim(cookie, idx)
            progress("idx%d %s claimed (HTTP %s ec=%s)" % (idx, t, cs, ec))
            done.append(idx)
            continue
        if not confirm:
            progress("idx%d %-20s %s/%s  (next action: %s)"
                     % (idx, t, m.get("currentCount"), m.get("completionCount"),
                        "forge" if t in FORGEABLE else "NOT forgeable"))
            return "dryrun", done
        if t not in FORGEABLE:
            progress("idx%d %s is not forgeable by this tool - stopping" % (idx, t))
            return "blocked:%s" % t, done
        if t in ("bonus_quest", "attendant"):
            # passive: if it isn't complete yet, we can't push it; stop
            progress("idx%d %s not complete and has no forge action - stopping" % (idx, t))
            return "blocked:%s" % t, done
        if actions >= max_actions:
            return "budget", done
        before = m.get("currentCount") or 0
        ok, note = drive_current(cookie, m)
        actions += 1
        progress("idx%d %s: %s" % (idx, t, note))
        if not ok:
            return "blocked:%s" % t, done
        # detect a quest that our action can't actually advance (e.g. a treasure whose area was already
        # cleared before this quest became current) so we don't burn hundreds of stage clears for nothing
        after = current_quest(get_quest(cookie)[0])
        moved = after and after.get("index") != idx  # advanced/claimed
        if not moved and after and (after.get("currentCount") or 0) <= before:
            stall = stall + 1 if stall_idx == idx else 1
            stall_idx = idx
            if stall >= max_stall:
                progress("idx%d %s not progressing after %d actions - stopping" % (idx, t, stall))
                return "stalled:%s" % t, done
        else:
            stall_idx, stall = None, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    parser.add_argument("--acct", help="roster/accounts/account-*.json (uses its lf_ac)")
    parser.add_argument("--confirm", action="store_true", help="actually forge (default is a dry run)")
    args = parser.parse_args()

    if args.acct:
        with open(args.acct, "r", encoding="utf-8") as handle:
            acct = json.load(handle)
        if not acct.get("lf_ac"):
            raise SystemExit("account has no session (status=%s)" % acct.get("status"))
        cookie = "LF_AC=" + acct["lf_ac"]
    else:
        cookie = resolve_cookie(args)

    pdq, status = get_quest(cookie)
    if status == 401:
        raise SystemExit("token rejected (401) - relogin first")
    if not pdq:
        raise SystemExit("no NEWBI special quest on this account (questType=%s)"
                         % (pdq.get("questType") if pdq else None))
    total = len(pdq.get("contents") or [])
    m = current_quest(pdq)
    print("SPECIAL QUEST (NEWBI): %d quests, current idx=%s (%s)"
          % (total, m["index"] if m else "-", m["missionType"] if m else "none"))
    # full chain map: what each quest needs and whether this tool can forge it
    for q in pdq.get("contents") or []:
        rw = ",".join("%s:%s" % (x.get("code"), x.get("amount")) for x in (q.get("missionRewards") or []))
        state = "claimed" if q.get("receiveReward") else ("READY" if q.get("missionComplete")
                else ("current" if q.get("currentQuest") else "locked"))
        tag = "forge" if q["missionType"] in FORGEABLE else "manual"
        print("  idx%-2d %-20s %s/%s  %-8s %-6s [%s]"
              % (q["index"], q["missionType"], q.get("currentCount"), q.get("completionCount"),
                 state, tag, rw))

    outcome, done = walk(cookie, confirm=args.confirm)
    # try the milestone reward if anything unlocked
    if args.confirm and done:
        cs, ec = claim_special(cookie)
        if cs == 200 and not ec:
            print("milestone specialReward claimed")

    pdq, _ = get_quest(cookie)
    m = current_quest(pdq)
    summary = {"total": total, "claimed_this_run": done, "outcome": outcome,
               "stopped_at_idx": m["index"] if m else None,
               "stopped_at_type": m["missionType"] if m else None}
    print(json.dumps(summary, ensure_ascii=False))
    if outcome == "auth":
        sys.exit(4)
    if outcome.startswith("blocked") or outcome.startswith("stalled"):
        sys.exit(2)
    if outcome in ("done", "dryrun"):
        sys.exit(0)
    sys.exit(6)


if __name__ == "__main__":
    main()
