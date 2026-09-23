r"""LINE Rangers gacha: check resources, list banners, and roll.

Reuses the captured session token (see pull_roster.py). All READ actions and a
roll's `reserve` step are side-effect-free. The `confirm` step is the ONLY thing
that spends ruby/tickets and grants units - it runs only with --confirm.

    python tools/gacha.py resources                 # ruby + gacha ticket counts
    python tools/gacha.py list                       # banners with costs (50r/5t single, 300r 7-pull)
    python tools/gacha.py roll grp_gacha_6 1 RUBY    # DRY RUN: reserve only, shows cost, no spend
    python tools/gacha.py roll grp_gacha_6 1 RUBY --confirm    # REAL: spends 50 ruby, grants a unit
    python tools/gacha.py roll grp_gacha_6 1 TICKET --confirm  # REAL: spends 5 gacha tickets
    python tools/gacha.py roll grp_gacha_6 2 RUBY --confirm    # REAL: spends 300 ruby, 6+1 pull

Roll model (verified against the live API):
  index 1 = single pull, payable with 50 ruby OR 5 tickets (choose via RUBY/TICKET)
  index 2 = 6+1 pull, payable with 300 ruby
  reserve  POST /v12.3/gacha/group/reserve  {groupId,gachaIndex}      -> reserveSeq (no spend)
  confirm  POST /v12.3/gacha/group/confirm  {groupId,gachaIndex,reserveSeq,useTicket} -> results (spends)
  useTicket=true pays 5 tickets; false pays ruby. NOTE: gachaPlayType is NOT the payment
  selector - sending it is ignored and the server silently charges ruby.

Standard library only.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import http.client
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from pull_roster import newest_auth_from_captures  # noqa: E402

HOST = "rangers-api.line-apps.com"


def call(cookie, uid, path, method="GET", body=None):
    # Reuse rangers_api's per-thread keep-alive connection (same HOST) so gacha rolls skip the
    # TLS handshake on every call after the first, and its shared retry policy: reconnect on a
    # dropped socket, back off (jittered) and retry on a 429/503 rate-limit/overload.
    import rangers_api
    now = int(time.time() * 1000)
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Host": HOST,
        "Accept": "*/*",
        "Content-Type": "application/json; charset=utf-8;",
        "App-Version": "LGRGS/12.3.0;android/12",
        "User-Agent": "LGRGS/12.3.0 (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)",
        "Accept-Language": "en",
        "X-LINEGAME-MCC": "000",
        "X-LINEGAME-MNC": "00",
        "X-LINEGAME-TIMESTAMP": str(now),
        "timeID": str(now),
        "Cookie": cookie,
        "Accept-Encoding": "gzip",
        "Connection": "keep-alive",
        **({"UID": uid} if uid else {}),   # optional: server derives player from LF_AC
    }
    raw = b""
    status = 0
    enc = None
    for attempt in range(rangers_api.MAX_ATTEMPTS):
        conn = rangers_api._get_conn()
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
            enc = resp.getheader("Content-Encoding")
            retry_after = resp.getheader("Retry-After")
        except (http.client.HTTPException, OSError):
            rangers_api._drop_conn()
            if attempt == rangers_api.MAX_ATTEMPTS - 1:
                raise
            continue               # dropped socket: reconnect and retry right away
        if status in rangers_api.RETRY_STATUSES and attempt < rangers_api.MAX_ATTEMPTS - 1:
            rangers_api._retry_sleep(attempt, retry_after)
            continue               # rate-limited/overloaded: wait, then retry
        break
    if enc == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def auth_or_die(from_device=False, device=None, cookie=None, xml=None):
    if cookie:
        return (cookie if cookie.startswith("LF_AC=") else "LF_AC=" + cookie), None, "cookie"
    if xml:
        from account_file import read_pref_xml
        return "LF_AC=" + read_pref_xml(xml)[1], None, xml
    if from_device:
        from device_session import get_lfac_from_device
        return "LF_AC=" + get_lfac_from_device(device), None, "device"
    cookie, uid, when = newest_auth_from_captures()
    if not cookie:
        raise SystemExit(
            "No session token. Either --from-device (app logged in on an adb device), or "
            "start the proxy and (re)launch the game so it authenticates through it."
        )
    return cookie, uid, when


def _ticket_items(cookie, uid=None):
    """The player-item response narrowed to the two gacha-ticket groups."""
    status, items = call(
        cookie, uid,
        "/v12.3/player/item?pGacha=true&etGacha=true&battleAuto=false&battleManual=false&exp=false&evolve=false&equip=false",
    )
    # A rate-limited / maintenance response comes back as a non-JSON string (e.g. an HTML
    # "429 Too Many Requests" page). Indexing that as a dict raised a bare
    # "string indices must be integers, not 'str'" TypeError far from the cause; surface the
    # real HTTP status instead so the caller/log says "429" not a mystery TypeError.
    if status != 200 or not isinstance(items, dict):
        raise RuntimeError("player/item failed (HTTP %s): %s" % (status, str(items)[:200]))
    return items.get("result") or {}


def ticket_counts(cookie, uid=None):
    """Return (premium, event) gacha-ticket totals held by the account.

    Held quantity lives in `amount` (= freeAmount + paidAmount). Note `rewardAmount`
    is the catalogue's per-grant size, NOT how many you own - reading that shows 0.
    Classic tickets (ni-33) never appear here; they live in a separate system.
    """
    result = _ticket_items(cookie, uid)
    return tuple(sum(item.get("amount", 0) for item in result.get(group, []) or [])
                 for group in ("premiumGachaTicketItems", "eventGachaTicketItems"))


def pick_ticket_group(cookie, uid=None):
    """Pick the machine a single TICKET pull should go to.

    A ticket only buys a pull where the index-1 option advertises a ticket price - the
    CLASSIC banners price index 1 in ruby only, so rolling one with useTicket silently
    charges ruby instead. Returns (groupId, ticketPrice, name), or (None, 0, None) when
    no open UNIT machine takes tickets.
    """
    status, info = call(cookie, uid, "/v12.3/gacha/info")
    # Same guard as _ticket_items: a 429/maintenance string body must not be indexed as a dict.
    if status != 200 or not isinstance(info, dict):
        return None, 0, None
    now_ms = int(time.time() * 1000)
    groups = sorted((info.get("result") or {}).get("gachaGroupResponseList", []),
                    key=lambda g: g.get("gachaGroup", {}).get("sortOrder", 999))
    for group in groups:
        gg = group.get("gachaGroup", {})
        start, end = gg.get("exposureStartDate"), gg.get("exposureEndDate")
        if not (start and end and start <= now_ms <= end):
            continue
        if gg.get("gachaResultType") != "UNIT":
            continue
        for option in gg.get("gachaGroupInfos", []):
            if option.get("gachaIndex") == 1 and option.get("displayTicketPrice"):
                return gg.get("groupId"), option["displayTicketPrice"], gg.get("gachaName")
    return None, 0, None


def cmd_resources(cookie, uid):
    _, roster = call(cookie, uid, "/v12.3/player/units/equip?inven=false&team=false&deck=false")
    player = roster["result"].get("player", {})
    ruby = roster["result"].get("rubyBalance", {}).get("total")
    print("account rsn=%s level=%s" % (player.get("rsn"), player.get("level")))
    print("ruby: %s" % ruby)
    result = _ticket_items(cookie, uid)
    for group, label in (("premiumGachaTicketItems", "premium gacha ticket"),
                         ("eventGachaTicketItems", "event gacha ticket")):
        for item in result.get(group, []) or []:
            print("%s (%s): %s   [free=%s paid=%s]" % (
                label, item.get("itemCode"), item.get("amount", 0),
                item.get("freeAmount", 0), item.get("paidAmount", 0)))


def _period(start_ms, end_ms):
    fmt = lambda ms: time.strftime("%m/%d %H:%M", time.localtime(ms / 1000)) if ms else "?"
    return "%s~%s" % (fmt(start_ms), fmt(end_ms))


def cmd_list(cookie, uid, show_all=False, kind=None):
    """Each gacha MACHINE is a groupId. gachaIndex only picks a pull option inside it."""
    _, info = call(cookie, uid, "/v12.3/gacha/info")
    now_ms = int(time.time() * 1000)
    groups = sorted(
        info["result"].get("gachaGroupResponseList", []),
        key=lambda g: g.get("gachaGroup", {}).get("sortOrder", 999),
    )
    shown = 0
    for group in groups:
        gg = group.get("gachaGroup", {})
        start, end = gg.get("exposureStartDate"), gg.get("exposureEndDate")
        live = bool(start and end and start <= now_ms <= end)
        if not show_all and not live:
            continue
        if kind and gg.get("gachaResultType") != kind:
            continue
        shown += 1
        print("\n%s   [%s/%s]%s" % (
            gg.get("groupId"), gg.get("gachaResultType"), gg.get("gachaDisplayType"),
            "" if live else "  (CLOSED)"))
        print("   name  : %s" % gg.get("gachaName"))
        print("   period: %s" % _period(start, end))
        if gg.get("titleRewardCodes"):
            print("   featured: %s" % ", ".join(gg["titleRewardCodes"][:6]))
        for i in gg.get("gachaGroupInfos", []):
            costs = []
            if i.get("displayRubyPrice"):
                costs.append("%d ruby" % i["displayRubyPrice"])
            if i.get("displayTicketPrice"):
                costs.append("%d ticket" % i["displayTicketPrice"])
            if i.get("displayFriendshipPrice"):
                costs.append("%d friendship" % i["displayFriendshipPrice"])
            if i.get("displayEventTicketPrice"):
                costs.append("%d event-ticket" % i["displayEventTicketPrice"])
            total = (i.get("gachaCount") or 0) + (i.get("bonusCount") or 0)
            print("   idx%-2s : %d pull(s)%s  for  %s" % (
                i.get("gachaIndex"), total,
                " (%d+%d)" % (i.get("gachaCount"), i.get("bonusCount")) if i.get("bonusCount") else "",
                " OR ".join(costs) or "free"))
    if not shown:
        print("no matching gacha machines (try --all)")


def cmd_roll(cookie, uid, group_id, index, pay_type, do_confirm, save=False):
    # reserve: side-effect free, just claims a slot
    use_ticket = pay_type == "TICKET"
    status, reserved = call(
        cookie, uid, "/v12.3/gacha/group/reserve", "POST",
        {"groupId": group_id, "gachaIndex": index, "useTicket": use_ticket},
    )
    if status != 200 or not isinstance(reserved, dict) or "result" not in reserved:
        raise SystemExit("reserve failed (HTTP %s): %s" % (status, reserved))
    reserve_seq = reserved["result"].get("reserveSeq")
    print("reserved: groupId=%s index=%s payType=%s reserveSeq=%s" % (group_id, index, pay_type, reserve_seq))

    if not do_confirm:
        print("\nDRY RUN - nothing was spent. Re-run with --confirm to actually roll.")
        return []

    # confirm: THIS SPENDS ruby/tickets and grants units
    status, result = call(
        cookie, uid, "/v12.3/gacha/group/confirm", "POST",
        {"groupId": group_id, "gachaIndex": index, "reserveSeq": reserve_seq, "useTicket": use_ticket},
    )
    print("\nconfirm HTTP %s" % status)
    if status != 200:
        print(json.dumps(result, ensure_ascii=False)[:600])
        return []
    res = result.get("result", result)
    granted = []
    used_ruby = used_ticket = used_event = 0
    after_ruby = None
    for gr in res.get("gachaResults", []):
        used_ruby += (gr.get("usedRuby") or {}).get("total", 0)
        used_ticket += gr.get("usedTickets", 0) or 0
        used_event += gr.get("usedEventTickets", 0) or 0
        if gr.get("afterRubyBalance"):
            after_ruby = gr["afterRubyBalance"].get("total")
        for reward in gr.get("rewards", []):
            unit = reward.get("rewardUnit")
            if unit:
                granted.append(unit)
    print("granted %d unit(s):" % len(granted))
    for unit in granted:
        code = unit.get("unitCode", "")
        name = re.sub(r"^u\d+[a-z]?-", "", code)
        print("  %-16s (%s)  maxLv=%s invenId=%s" % (name, code, unit.get("playerUnitMaxLevel"), unit.get("invenId")))
    if used_ruby:
        print("spent %d ruby" % used_ruby)
    if used_ticket:
        print("spent %d gacha ticket(s)" % used_ticket)
    if used_event:
        print("spent %d event ticket(s)" % used_event)
    if after_ruby is not None:
        print("ruby remaining: %s" % after_ruby)
    if res.get("pityCount") is not None:
        print("pity count: %s" % res.get("pityCount"))
    # Off by default: a bot run rolls on every generated account, and dumping the raw
    # response each time buried roster/ under thousands of files nobody reads. The units
    # granted are printed above and returned to the caller, so nothing is lost. Pass
    # save=True (CLI: --save) when the raw response is actually wanted for debugging.
    if save:
        out = os.path.join(ROOT, "roster", "gacha-result-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=1)
        print("saved %s" % out)
    return granted


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-device", action="store_true",
                        help="read the live LF_AC off the logged-in device (hybrid path)")
    parser.add_argument("--device", help="adb serial for --from-device")
    parser.add_argument("--cookie", help='explicit "LF_AC=..." cookie value')
    parser.add_argument("--xml", help="account file to read the session from")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resources")
    lst = sub.add_parser("list")
    lst.add_argument("--all", action="store_true", help="include closed/expired machines")
    lst.add_argument("--kind", choices=("UNIT", "EQUIP"), help="only UNIT (rangers) or EQUIP (gear)")
    roll = sub.add_parser("roll")
    roll.add_argument("group_id")
    roll.add_argument("index", type=int, choices=(1, 2))
    roll.add_argument("pay_type", choices=("RUBY", "TICKET"))
    roll.add_argument("--confirm", action="store_true", help="actually spend and roll (default is a dry run)")
    roll.add_argument("--save", action="store_true", help="also write the raw response to roster/gacha-result-*.json")
    args = parser.parse_args()

    cookie, uid, when = auth_or_die(args.from_device, args.device, args.cookie, args.xml)
    if args.command == "resources":
        cmd_resources(cookie, uid)
    elif args.command == "list":
        cmd_list(cookie, uid, show_all=args.all, kind=args.kind)
    elif args.command == "roll":
        cmd_roll(cookie, uid, args.group_id, args.index, args.pay_type, args.confirm, save=args.save)


if __name__ == "__main__":
    main()
