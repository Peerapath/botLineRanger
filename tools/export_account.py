r"""Export a LINE Rangers account's identity + snapshot to a JSON file (headless).

Mirrors the old UI bot's "export" step: capture what identifies and describes the
account so it can be catalogued or restored later - the in-game GAME_ID (rsn), the
account mid/uid, type, resources, and roster size. Works off any session source.

    python tools/export_account.py --from-device            # rooted, logged-in device (guest)
    python tools/export_account.py --cookie "LF_AC=..."     # e.g. a captured Google login
    python tools/export_account.py --from-device --guest-file roster/accounts/account-*.json

If you also pass a --guest-file produced by new_account.py, its userToken /
refreshUserToken (the credentials to re-login a guest headlessly) are merged in.
Standard library only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "roster", "accounts")


def snapshot(cookie) -> dict:
    status, equip = call(cookie, "/player/units/equip?inven=true&team=false&deck=false")
    if status != 200 or not isinstance(equip, dict):
        raise SystemExit("player call failed (HTTP %s) - session likely expired: %s"
                         % (status, str(equip)[:150]))
    result = equip["result"]
    player = result.get("player", {})
    roster = result.get("playerUnits", []) or []

    _, items = call(cookie, "/player/item?pGacha=true&etGacha=true&battleAuto=false"
                            "&battleManual=false&exp=false&evolve=false&equip=false")
    tickets = {}
    if isinstance(items, dict):
        for group, label in (("premiumGachaTicketItems", "premiumGachaTicket"),
                              ("eventGachaTicketItems", "eventGachaTicket")):
            for item in items["result"].get(group, []) or []:
                tickets[label] = tickets.get(label, 0) + item.get("amount", 0)

    return {
        "exportedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gameId": player.get("rsn"),          # the "GAME ID" shown in-game
        "mid": player.get("mid"),
        "uid": player.get("uid"),
        "userName": player.get("userName"),
        "level": player.get("level"),
        "userType": result.get("userType") or player.get("userType"),
        "ruby": result.get("rubyBalance", {}).get("total"),
        "tickets": tickets,
        "rosterCount": len(roster),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    parser.add_argument("--guest-file", help="account-*.json from new_account.py to merge credentials from")
    args = parser.parse_args()

    cookie = resolve_cookie(args)
    account = snapshot(cookie)
    account["lf_ac"] = cookie[len("LF_AC="):]

    if args.guest_file:
        matches = glob.glob(args.guest_file)
        if matches:
            with open(matches[0], "r", encoding="utf-8") as handle:
                guest = json.load(handle)
            for key in ("deviceId", "userToken", "refreshUserToken", "refreshUserTokenExpireTime"):
                if guest.get(key):
                    account[key] = guest[key]

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "account-%s.json" % (account["gameId"] or "unknown"))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(account, handle, ensure_ascii=False, indent=1)

    print("GAME_ID=%s  mid=%s  type=%s  level=%s  ruby=%s  rangers=%s" % (
        account["gameId"], account["mid"], account["userType"],
        account["level"], account["ruby"], account["rosterCount"]))
    print("tickets: %s" % account["tickets"])
    print("saved: %s" % path)


if __name__ == "__main__":
    main()
