r"""Confirm LINE Rangers tutorial steps over the API (headless) - for new-account setup.

A brand-new account starts mid-tutorial; the game advances it by confirming each step.
This drives those confirmations directly so a freshly-created account can be pushed past
the tutorial without the UI. Confirming an already-done step is idempotent (returns true),
so running the full set is safe.

    python tools/tutorial.py --from-device               # DRY RUN: show the steps it would confirm
    python tools/tutorial.py --from-device --confirm     # confirm every step
    python tools/tutorial.py --cookie "LF_AC=..." --confirm --only TEAM,EVOLVE

Endpoint (verified live): GET /v12.3/tutorial/confirm/<STEP> -> {"result": true}
Standard library only.
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402

# The FULL server-side tutorial-step set (67 keys, verified live 2026-09-19 against a fresh guest's
# signup `tutorialStep` map - the old 15-item list was a small subset). /tutorial/confirm/<STEP>
# takes any of these via the dynamic `/tutorial/confirm/%s` route and marks it done idempotently.
# Live result on a brand-new guest: 64/66 pending steps -> {"result": true} in one pass.
#
# CAVEAT - two steps refuse confirm ({"result": false}): SALLY and YELLOW_STONE. They gate on the
# account actually OWNING the Sally unit / a yellow evolve-stone, which come from the tutorial GACHA +
# EVOLVE mechanics (POST /tutorial/gachagroup/play?tutorialType=GACHA {amount:1,useTicket:false,
# gachaIndex:0} returns 200 but playCount:0 = no grant without the full pull/claim flow; the evolve
# /tutorial/player/units/reinforce?tutorialType=EVOLVE 500s without materials). So a purely headless
# confirm run tops out at 65/67. THIS IS FINE: it suppresses tutorial popups AND the account is already
# fully usable - a fresh guest gets 5 starter units at signup (u45-james,u32-brown,u37-moon x2,u38-cony)
# and can enter/play stages (POST /stage/enter/st01 -> 200). SALLY/YELLOW_STONE are a bonus tutorial-gacha
# unit + an evolve demo, NOT blockers. (Read owned units via /player/units/equip?inven=true, NOT
# /player/units which 404s as 102001.) See [[lgrgs-tutorial-skip-api]] / [[headless-account-creation-lgrgs]].
STEPS = [
    "START", "HOME_INTRO", "TEAM", "GO_STAGE2", "TREASURE", "GACHA", "SALLY", "EVOLVE",
    "YELLOW_STONE", "SALLY_WEAPON", "UPGRADE", "UPGRADE_GET", "UPGRADE_MAX", "UPGRADE_MAX_GET",
    "ITEM", "GIFT", "FRIEND", "BINGO", "ROULETTE", "RANDOMDICE", "STAR_WISH",
    "TEAM_CHANGE", "TEAM_CHANGE_SET", "AUTO_BATTLE", "BATTLE_SPEED", "NRML_STG_AUTO_PLAY",
    "SPCL_STG_AUTO_PLAY", "HARD_MODE_STAGE", "EXTREME_MODE_STAGE", "SPCL_QUEST_NEWBIE",
    "SEVENDAYS_QUEST", "GACHA_PITY", "EQIP_GACHA", "EQUIP_GET", "EQUIP_GET_MTRL", "EQUIP_WEAR",
    "EQUIP_REINF", "EQUIP_SWITCH", "EQUIP_UNLIMIT", "EQUIP_SPECIALIZE", "EARN_DR_LEONARD",
    "EARN_SP_LEONARD", "EXTR_LAB", "EXTR_GRADE_SEVEN", "EXPEDITION_LAB", "EVENT_STAGE_MENU",
    "EVENT_STAGE_TEAM", "EVENT_STAGE_BATTLE", "EVENT_GUILD_RAID", "GUILD_WAR_MENU", "GUILD_WAR_TEAM",
    "PVP_ELEMENTAL", "ENDLESS", "ENDLESS_BOSS", "ENDLESS_TIME", "ENDLESS_V2", "ENDLESS_V2_BOSS",
    "ENDLESS_V2_SIEGE", "ENDLESS_V2_TIME", "LABYRINTH_MAIN", "LABYRINTH_BATTLE", "LABYRINTH_ARTIFACT",
    "SPACE_TRAIN_MAIN", "SPACE_TRAIN_BATTLE", "RANGERS_PASS", "RANGERS_PASS_BUY", "SKILL_PLUS_MATCH",
]


def confirm(cookie, step):
    status, data = call(cookie, "/tutorial/confirm/" + step)
    ok = status == 200 and isinstance(data, dict) and data.get("result") is True
    return ok, status, data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    parser.add_argument("--confirm", action="store_true", help="actually confirm (default is a dry run)")
    parser.add_argument("--only", help="comma-separated subset of steps to confirm")
    args = parser.parse_args()

    steps = [s.strip().upper() for s in args.only.split(",")] if args.only else STEPS
    cookie = resolve_cookie(args)

    if not args.confirm:
        print("DRY RUN - would confirm %d step(s):" % len(steps))
        print("  " + ", ".join(steps))
        print("\nRe-run with --confirm to send them.")
        return

    done = 0
    for step in steps:
        ok, status, data = confirm(cookie, step)
        print("  %-20s %s" % (step, "ok" if ok else "HTTP %s %s" % (status, str(data)[:60])))
        done += ok
    print("\nconfirmed %d/%d steps" % (done, len(steps)))


if __name__ == "__main__":
    main()
