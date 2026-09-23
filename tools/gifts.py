r"""List and claim LINE Rangers giftbox items over the API (headless).

The giftbox holds login bonuses, event rewards, etc. Listing is free; claiming is a
mutation, so it needs --confirm (default is a dry run that only shows what's pending).

    python tools/gifts.py list --from-device                 # show pending gifts
    python tools/gifts.py claim --from-device                # DRY RUN: list, don't claim
    python tools/gifts.py claim --from-device --confirm      # POST receive/all - grants items
    python tools/gifts.py list --cookie "LF_AC=..."          # explicit token

Endpoints (verified live):
    GET  /v12.3/giftbox/list                 -> result.giftBox.gift.playerGifts[]
    POST /v12.3/giftbox/gift/receive/all     -> claims every pending gift (spends nothing)
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


def pending_gifts(cookie):
    status, data = call(cookie, "/giftbox/list")
    if status != 200 or not isinstance(data, dict):
        raise SystemExit("giftbox/list failed (HTTP %s): %s" % (status, str(data)[:200]))
    gift = data["result"].get("giftBox", {}).get("gift", {}) or {}
    return [g for g in gift.get("playerGifts", []) if not g.get("receive")]


def show(gifts):
    if not gifts:
        print("no pending gifts")
        return
    print("pending gifts: %d" % len(gifts))
    for g in gifts:
        print("  %-40s x%-4s [%s %s]  from %s" % (
            g.get("giftName"), g.get("giftCount"), g.get("giftType"), g.get("dataCode"),
            g.get("senderName")))


def cmd_list(cookie):
    show(pending_gifts(cookie))


def cmd_claim(cookie, do_confirm):
    gifts = pending_gifts(cookie)
    show(gifts)
    if not gifts:
        return
    if not do_confirm:
        print("\nDRY RUN - nothing claimed. Re-run with --confirm to receive all.")
        return
    status, data = call(cookie, "/giftbox/gift/receive/all", "POST")
    print("\nreceive/all HTTP %s" % status)
    if status != 200:
        print(str(data)[:300])

    # receive/all skips some kinds (MINI_GACHA material boxes, etc.) - mop those up one by one
    remaining = pending_gifts(cookie)
    for gift in remaining:
        sn = gift.get("giftSn")
        st, _ = call(cookie, "/giftbox/gift/receive/%d" % sn, "POST")
        print("  receive %-40s %s" % (gift.get("giftName"), "ok" if st == 200 else "HTTP %s" % st))

    left = pending_gifts(cookie)
    print("\nclaimed %d gift(s); %d still pending" % (len(gifts) - len(left), len(left)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    claim = sub.add_parser("claim")
    claim.add_argument("--confirm", action="store_true", help="actually claim (default is a dry run)")
    args = parser.parse_args()

    cookie = resolve_cookie(args)
    if args.command == "list":
        cmd_list(cookie)
    elif args.command == "claim":
        cmd_claim(cookie, args.confirm)


if __name__ == "__main__":
    main()
