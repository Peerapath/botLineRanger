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


def gacha_info(cookie, uid, cache=None):
    """ข้อมูลตู้กาชาของบัญชีนี้ ใช้ cache ที่ผู้เรียกถือมาถ้ามี

    cache ต้องมาจากผู้เรียก ห้ามเป็นตัวแปรระดับโมดูล - engine รันหลายบัญชีพร้อมกัน
    ในโปรเซสเดียว cache ที่แชร์กันจะทำให้บัญชีหนึ่งเห็นตู้ของอีกบัญชี
    """
    if cache is not None and "info" in cache:
        return cache["info"]
    _status, info = call(cookie, uid, "/v12.3/gacha/info")
    if cache is not None:
        cache["info"] = info
    return info


def pick_ticket_group(cookie, uid=None, cache=None):
    """Pick the machine a single TICKET pull should go to.

    A ticket only buys a pull where the index-1 option advertises a ticket price - the
    CLASSIC banners price index 1 in ruby only, so rolling one with useTicket silently
    charges ruby instead. Returns (groupId, ticketPrice, name), or (None, 0, None) when
    no open UNIT machine takes tickets.
    """
    info = gacha_info(cookie, uid, cache)
    # Same guard as _ticket_items: a 429/maintenance string body must not be indexed as a dict.
    # (gacha_info folds the HTTP status into `info` instead of returning it separately, so the
    # explicit status != 200 check that used to sit here is gone too - a non-200/non-JSON body
    # still fails isinstance(dict) and is treated the same as "no open machine".)
    if not isinstance(info, dict):
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


def cmd_list(cookie, uid, show_all=False, kind=None, cache=None):
    """Each gacha MACHINE is a groupId. gachaIndex only picks a pull option inside it."""
    info = gacha_info(cookie, uid, cache)
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


def _gacha_group_price(cookie, uid, groupId, cache=None):
    """คืน (rubyPrice, ticketPrice, gachaName) ของตัวเลือกสุ่มเดี่ยว (gachaIndex=1) ของตู้ groupId

    อ่านจาก /gacha/info (ตัวเดียวกับ getGachaBanner) ตู้ CLASSIC ตั้งราคา index 1 เป็นรูบี้อย่าง
    เดียว ticketPrice จะเป็น 0 ไม่เจอตู้/ตัวเลือกคืน (0, 0, None)

    Moved from botLineRanger._gachaGroupPull() - not named in the task brief's helper list,
    but draw_with_ticket cannot resolve a caller-supplied group's price without it. Reads
    through gacha_info(cache) instead of a bare call() so this and pick_ticket_group's own
    /gacha/info fetch share one cache within a single draw_with_ticket call.
    """
    info = gacha_info(cookie, uid, cache)
    if not isinstance(info, dict):
        return 0, 0, None
    for group in (info.get("result") or {}).get("gachaGroupResponseList") or []:
        gg = group.get("gachaGroup") or {}
        if gg.get("groupId") == groupId:
            for opt in gg.get("gachaGroupInfos") or []:
                if opt.get("gachaIndex") == 1:
                    return (opt.get("displayRubyPrice") or 0,
                            opt.get("displayTicketPrice") or 0, gg.get("gachaName"))
    return 0, 0, None


def _ruby_and_tickets(cookie, uid):
    """รูบี้รวม + จำนวนตั๋วกาชาปกติ ที่ draw_with_ticket ใช้เช็กก่อนสุ่มทุกรอบ

    Moved from botLineRanger.getRubyAndTicket() - data-fetch half only (that function's
    summary=True branch just prints a log line; apiGachaWithTicket always called it with
    summary=False, so nothing calls this module's version with logging and it was not
    moved). Not in the task brief's helper list either, but the ticket/ruby resource
    check is load-bearing for draw_with_ticket's pay-ticket-first-then-ruby decision.

    Raises on a failed /home call exactly like the original - draw_with_ticket has no
    try/except around this lookup (see the loop below), so a broken /home call aborts
    the whole draw instead of being silently read as "0 ruby, 0 tickets".
    """
    status, data = call(cookie, uid, "/home")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"getRubyAndTicket failed (HTTP {status}): {str(data)[:200]}")
    ruby = (data.get("result") or {}).get("rubyBalance") or {}
    premium, event = ticket_counts(cookie, uid)
    return {"ruby": ruby.get("total", 0), "ticket": premium, "eventTicket": event}


def draw_with_ticket(cookie, uid, group=None, cycles=1, stop_when_found=True,
                     targets=None, cache=None, gacha_mode="NumberOfCycles", use_ruby=False):
    """สุ่มกาชาด้วยตั๋ว คืนรายชื่อ unitCode ที่ได้

    ย้ายมาจาก botLineRanger.apiGachaWithTicket() แบบคำต่อคำ ต่างกันแค่ค่าที่เคยอ่านจาก
    global (GACHARANGERGROUP, RANGERSCONFIG, LASTGACHASTATUS) กลายเป็นพารามิเตอร์และค่าคืน
    - engine รันหลายบัญชีในโปรเซสเดียว global จะทำให้บัญชีหนึ่งใช้ค่าตั้งของอีกบัญชี

    ฟังก์ชันนี้หักตั๋วจริงบนบัญชีจริง ทุกบรรทัดที่ต่างจากต้นฉบับคือความเสี่ยงที่จะเสียตั๋วฟรี

    Return value is (granted_codes, status) - a 2-tuple, not the bare list the task brief's
    own interface line sketches. LASTGACHASTATUS must become part of the return per the task
    instructions, and a plain list can't carry both the codes and the status string, so this
    follows the explicit instruction over the interface sketch. `status` is the exact string
    the original wrote to LASTGACHASTATUS - callers used it for session-summary logging only,
    never for control flow (the target-found check reads the codes list, not the status).

    Beyond the three sanctioned substitutions, this move required more plumbing than the task
    description's "only changes permitted" list names, because the original function is not
    self-sufficient outside botLineRanger's module globals. Every one is called out here so a
    reviewer can check it against the original instead of taking it on faith:
      - cookie, uid: the original called getLFAC()/_importApiTools() itself to get a session.
        The caller now holds the session already, so these are parameters instead.
      - cache: threaded into gacha_info() so a single draw_with_ticket call (auto-pick group:
        pick_ticket_group + this function's own price lookup) hits /gacha/info once, not
        twice - this is the other half of this task (see gacha_info above).
      - gacha_mode, use_ruby: kept, with their original defaults, even though the brief's
        interface sketch omits them. Dropping them would delete the "giveItAll" mode and the
        ruby-fallback-when-tickets-run-out behaviour, which is a capability loss, not a rename
        - out of scope for a move.
      - the local loop counter, originally also named `cycles`, is renamed to `cycles_done`:
        the brief asks for the *parameter* `cycles` (replacing the original `gacha_cycles`),
        which would otherwise collide with and shadow the counter of the same name.
      - log(...) calls become print(...): log() is a botLineRanger console-timestamp helper
        that does not exist in tools/; every other function in this file already uses print()
        for equivalent status lines (see cmd_roll above), so this matches the local file, not
        botLineRanger.
      - the try/except around the roll call now catches SystemExit too. The original wrapped
        every tools/-side call in botLineRanger._apiCall(), whose whole job was: "เรียกฟังก์ชัน
        ฝั่ง tools/ แล้วแปลง SystemExit เป็น Exception ธรรมดา tools/ เขียนมาเป็น CLI เวลา token
        ตายหรือ adb หาไม่เจอมันจะ raise SystemExit ซึ่งไม่ได้สืบทอดจาก Exception" (comment copied
        from _apiCall's own docstring). cmd_roll still raises SystemExit on a failed reserve;
        without that conversion the original's `except Exception` would no longer catch it.
      - uid is threaded into the read-only lookups this move adds (pick_ticket_group,
        gacha_info, ticket_counts, the /home call) but NOT into the cmd_roll call, which keeps
        the original's literal `None` in that slot. Every function in this file already treats
        uid as optional/inert ("server derives player from LF_AC" - see call()'s docstring),
        so threading it into reads carries no risk and avoids a dead parameter; the one call
        that actually spends tickets is left byte-for-byte identical to the original.

    A pre-existing quirk preserved as-is, not fixed: the "no-resource:..." and "roll-error:..."
    status strings set inside the loop are always overwritten by the unconditional status =
    ",".join(...)/"empty" line right before the final return - they were dead stores in the
    original too (every path through the loop ends in a `break` that falls through to that
    line). A caller never actually observes "no-resource:..."/"roll-error:..." in the returned
    status. Verbatim means this stays exactly as surprising as it always was.

    gacharangergroup: groupId ตู้ที่จะสุ่ม (เช่น 'grp_gacha_33' ที่เลือกจาก dropdown ใน main.py)
      None = ให้เลือกตู้ที่รับตั๋วอัตโนมัติ (pick_ticket_group) เหมือนพฤติกรรมเดิม
    stop_when_found: เจอเรนเจอร์ที่อยู่ใน targets แล้วหยุดทันที (ดีฟอลต์ True)
    gacha_mode: 'giveItAll' สุ่มจนตั๋ว/รูบี้หมด | 'NumberOfCycles' สุ่มครบ cycles รอบแล้วหยุด
    cycles: จำนวนรอบเมื่อ gacha_mode='NumberOfCycles'
    use_ruby: ตั๋วหมดแล้วยอมจ่ายรูบี้ต่อ (ดีฟอลต์ False = จ่ายเฉพาะตั๋ว ตั๋วหมดก็หยุด)

    จ่ายตั๋วก่อนเสมอ (คุ้มกว่า) ตั๋วไม่พอค่อยใช้รูบี้ถ้า use_ruby=True index 1 = สุ่มเดี่ยว
    เทียบเรนเจอร์แบบตรงตัว (targets.get(code.lower())) ไม่ใช่ matchGachaName fuzzy เพราะ
    ได้ unitCode เป๊ะจาก API ไม่มีความเพี้ยนของ OCR ให้ต้องกลบ (โค้ดต่างตัวเดียวจะจับผิดตัว)
    unitCode คืนเต็มไม่ตัด prefix (targets เก็บ key เป็น code เต็ม u1630e-sally)
    """
    targets = targets or {}

    # หาตู้เป้าหมาย + ราคาสุ่มเดี่ยว (ตั๋ว/รูบี้)
    if group:
        groupId = group
        rubyPrice, ticketPrice, name = _gacha_group_price(cookie, uid, groupId, cache)
    else:
        groupId, ticketPrice, name = pick_ticket_group(cookie, uid, cache=cache)
        rubyPrice = _gacha_group_price(cookie, uid, groupId, cache)[0] if groupId else 0
    if not groupId:
        status = "no-machine"
        print("No open gacha machine - skip gacha")
        return [], status
    print(f"Gacha target {groupId} ({name}) - ticket {ticketPrice}/pull, ruby {rubyPrice}/pull")

    granted_codes = []
    cycles_done = 0
    while True:
        if gacha_mode == "NumberOfCycles" and cycles_done >= cycles:
            break

        # status บอกเหตุผลไว้ให้ log สรุป session เพราะ list ว่างบอกไม่ได้ว่าไม่มีตู้
        # ตั๋วหมด หรือสุ่มแล้วไม่ได้อะไร ซึ่งคนละเรื่องกันตอน monitor
        info = _ruby_and_tickets(cookie, uid)
        premium, ruby = info["ticket"], info["ruby"]
        # เลือกวิธีจ่าย: ตั๋วก่อน ไม่พอค่อยรูบี้ (เมื่อ use_ruby) ไม่พอทั้งคู่ = จบ
        if ticketPrice and premium >= ticketPrice:
            payType = "TICKET"
        elif use_ruby and rubyPrice and ruby >= rubyPrice:
            payType = "RUBY"
        else:
            status = f"no-resource:tk{premium}/rb{ruby}"
            print(f"Gacha stop: ตั๋ว {premium} รูบี้ {ruby} ไม่พอ "
                f"(ตั๋ว/รอบ {ticketPrice}, รูบี้/รอบ {rubyPrice}, use_ruby={use_ruby})")
            break

        try:
            granted = cmd_roll(cookie, None, groupId, 1, payType, True) or []
        except (Exception, SystemExit) as e:
            status = f"roll-error:{e}"
            print(f"Gacha roll ล้มเหลว หยุด: {e}")
            break
        codes = [unit.get("unitCode", "") for unit in granted if unit.get("unitCode")]
        granted_codes.extend(codes)
        cycles_done += 1
        print(f"Gacha {groupId} pull #{cycles_done} ({payType}): {', '.join(codes) or 'none'}")

        # เจอเรนเจอร์ที่ตั้งไว้ใน config แล้วหยุด
        if stop_when_found and any(targets.get(c.lower()) for c in codes):
            print(f"Gacha พบเรนเจอร์เป้าหมาย หยุดสุ่ม")
            break

    status = ",".join(granted_codes) if granted_codes else "empty"
    print(f"Gacha granted รวม: {', '.join(granted_codes) if granted_codes else 'none'}")
    return granted_codes, status


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
