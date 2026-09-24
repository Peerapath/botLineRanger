r"""Sweep every reward the game hands out and claim what is claimable (headless).

LINE Rangers gives things away through half a dozen unrelated systems - the gift box,
the 7-day New Players event, the daily quest, daily/weekly missions, the free daily
attendance package and the Rangers Pass. Login bonuses and maintenance-compensation
rewards ("Check your Gift Box") all land in the gift box, so claiming that covers them.
This walks all of them, reports what is claimable, and claims it with --confirm.

    python tools/rewards.py --xml id/20a09064.xml              # DRY RUN: survey only
    python tools/rewards.py --xml id/20a09064.xml --confirm    # claim everything claimable
    python tools/rewards.py --from-device --confirm

Endpoints and methods (probed live against 12.3.0 - every claim is POST except the
attendance package, which the client fetches with a GET):
    GET  /giftbox/list                    POST /giftbox/gift/receive/all
                                          POST /giftbox/gift/receive/<giftSn>
    GET  /mission/sevendays/list          POST /mission/sevendays/receive/reward/<seq>/attendance/<day>
                                          POST /mission/sevendays/receive/reward/<seq>/final
    GET  /dailyquest                      POST /dailyquest/receive/reward/<questType>/<index>
    GET  /mission/list/new/               POST /mission/receive/reward/daily|weekly/<no>/<type>
    GET  /home -> attendancePackageList   GET  /package/attendance?playerSeq=&packSeq=
    GET  /pass/main                       POST /pass/receive/reward/<seq>/pass/all

A reward counts as claimable only when it is complete/earned and not yet received, so a
dry run is an accurate list of what a --confirm would send. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rangers_api  # noqa: E402
from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402

MARKET_LOCALE = "TH"


def _rewards_of(entry):
    parts = []
    for reward in entry.get("missionRewards") or entry.get("rewards") or []:
        parts.append("%s x%s" % (reward.get("code"), reward.get("amount")))
    return ", ".join(parts)


def _get(cookie, path):
    status, data = call(cookie, path)
    if status != 200 or not isinstance(data, dict):
        return None
    return data.get("result")


def check_session(cookie, home=None):
    """Fail loudly on a dead token.

    Every collector treats a non-200 as "nothing here", so an expired session would
    otherwise render as a clean "nothing to claim" - the most misleading output this
    tool could produce.

    `home` lets a caller that already fetched /home hand it over. One account used to
    pay for that same payload four times (here, in survey_attendance_package, in
    currentLevel and in getRubyAndTicket) - the single most repeated call in the bot.
    """
    if home is None:
        status, data = call(cookie, "/home")
        if not (status == 200 and isinstance(data, dict) and "result" in data):
            raise SystemExit(
                "session rejected (HTTP %s) - the token in this account file is stale.\n"
                "LF_AC changes every time the game is launched; refresh it with:\n"
                "  python tools/account_file.py --from-device --device <serial> --out <that .xml>"
                % status)
        home = data["result"]
    return home["player"]


# --- one collector per reward system; each returns a list of claim jobs ---

def _pending_gifts(cookie):
    result = _get(cookie, "/giftbox/list")
    if not result:
        return []
    gift = (result.get("giftBox", {}) or {}).get("gift", {}) or {}
    return [g for g in gift.get("playerGifts", []) if not g.get("receive")]


def claim_giftbox(cookie, pending=None):
    """receive/all, then mop up the kinds it skips (MINI_GACHA boxes) one by one.

    `pending` is the list survey_giftbox already fetched. Without it this function
    listed the box twice more per call - once to find the leftovers and once to
    confirm - on top of the listing the survey had just done.

    The return value says "something was claimed", not "the box is now empty".
    Nothing here can say the latter: the loop re-posts every entry the survey listed,
    including ones receive/all already swept, and a redundant claim's status is not
    something this codebase has ever observed. Only a fresh listing settles it, and
    removing that listing is the point of this function's new shape.

    So it stays optimistic on purpose. An AND-chain was tried and reverted: with it, a
    failed receive/all followed by leftovers that all succeed - a genuinely drained box -
    returned False, and since the gift box is the only job a refresh pass can produce,
    claim_all counted zero claims and broke out of its remaining passes. That turned a
    wrong log line into a skipped sweep. Being too optimistic costs an inaccurate "ok";
    being too pessimistic costs the pass that exists to catch a gift depositing a gift.
    """
    status, _data = call(cookie, "/giftbox/gift/receive/all", "POST")
    done = status == 200
    leftovers = _pending_gifts(cookie) if pending is None else pending
    for gift_entry in leftovers:
        sub, _ = call(cookie, "/giftbox/gift/receive/%s" % gift_entry.get("giftSn"), "POST")
        done = done or sub == 200
    return done


def survey_giftbox(cookie):
    pending = _pending_gifts(cookie)
    if not pending:
        return []
    names = ", ".join("%s x%s" % (g.get("giftName"), g.get("giftCount")) for g in pending[:3])
    if len(pending) > 3:
        names += ", ..."
    # ผูกรายการที่เพิ่งดึงมาเข้ากับงาน claim เลย ผู้เรียกจะได้ไม่ต้องไปถามซ้ำ
    return [("giftbox", lambda c: claim_giftbox(c, pending),
             "%d gift(s): %s" % (len(pending), names))]


def survey_sevendays(cookie):
    result = _get(cookie, "/mission/sevendays/list")
    if not result:
        return []
    jobs = []
    for event in result:
        seq = event.get("seq")
        for attendance in event.get("playerAttendanceMissions", []) or []:
            if attendance.get("missionComplete") and not attendance.get("receiveReward"):
                day = attendance.get("missionCondition")
                jobs.append(("7day", ("POST", "/mission/sevendays/receive/reward/%s/attendance/%s" % (seq, day)),
                             "attendance day %s (%s)" % (day, _rewards_of(attendance))))
        for daily in event.get("playerDailyMissions", []) or []:
            for entry in daily.get("detail", []) or []:
                if entry.get("missionComplete") and not entry.get("receiveReward"):
                    jobs.append(("7day",
                                 ("POST", "/mission/sevendays/receive/reward/%s/daily/%s/%s/%s"
                                  % (seq, daily.get("day"), entry.get("missionType"), entry.get("sort"))),
                                 "day %s %s (%s)" % (daily.get("day"), entry.get("missionType"),
                                                     _rewards_of(entry))))
        if event.get("finalMissionComplete") and not event.get("receiveFinalReward"):
            jobs.append(("7day", ("POST", "/mission/sevendays/receive/reward/%s/final" % seq),
                         "FINAL %s x%s" % (event.get("finalRewardCode"), event.get("finalRewardCount"))))
    return jobs


def survey_dailyquest(cookie):
    result = _get(cookie, "/dailyquest")
    if not result:
        return []
    quest = result.get("playerDailyQuest") or {}
    quest_type = quest.get("questType")
    jobs = []
    for entry in quest.get("contents", []) or []:
        if entry.get("missionComplete") and not entry.get("receiveReward"):
            jobs.append(("dailyquest",
                         ("POST", "/dailyquest/receive/reward/%s/%s" % (quest_type, entry.get("index"))),
                         "%s (%s)" % (entry.get("missionType"), _rewards_of(entry))))
    return jobs


def survey_missions(cookie):
    result = _get(cookie, "/mission/list/new/")
    if not result:
        return []
    jobs = []
    for tab, kind, number_key in (("dailyMissionTab", "daily", "dailyNo"),
                                  ("weeklyMissionTab", "weekly", "weeklyNo")):
        block = result.get(tab) or {}
        number = block.get(number_key)
        for entry in block.get("detail", []) or []:
            if entry.get("missionComplete") and not entry.get("receiveReward"):
                jobs.append(("mission-%s" % kind,
                             ("POST", "/mission/receive/reward/%s/%s/%s"
                              % (kind, number, entry.get("missionType"))),
                             "%s (%s)" % (entry.get("missionType"), _rewards_of(entry))))
    # specialMissionTab comes back as a bare list (the other two are dicts holding `detail`)
    special = result.get("specialMissionTab") or []
    if isinstance(special, dict):
        special = special.get("detail") or []
    for entry in special:
        if entry.get("missionComplete") and not entry.get("receiveReward"):
            number = entry.get("missionNo") or entry.get("seq")
            jobs.append(("mission-special",
                         ("POST", "/mission/receive/reward/%s" % number),
                         "%s (%s)" % (entry.get("missionType"), _rewards_of(entry))))
    return jobs


def _attendance_jobs(result):
    jobs = []
    for pack in result.get("attendancePackageList", []) or []:
        if pack.get("received") or pack.get("receiveReward"):
            continue
        player_seq = pack.get("playerSeq")
        pack_seq = pack.get("packSeq") or pack.get("seq")
        if player_seq is None or pack_seq is None:
            continue
        jobs.append(("attendance-pkg",
                     ("GET", "/package/attendance?playerSeq=%s&packSeq=%s" % (player_seq, pack_seq)),
                     "attendance package seq=%s" % pack_seq))
    return jobs


def survey_attendance_package(cookie, home=None):
    """The free 'Daily Free Item' package - the client fetches it with a GET that grants.

    `home` lets a caller that already fetched /home hand it over instead of paying for
    the same payload again (see check_session).
    """
    result = home if home is not None else _get(cookie, "/home")
    if not result:
        return []
    return _attendance_jobs(result)


def survey_pass(cookie):
    result = _get(cookie, "/pass/main")
    if not result:
        return []
    event = result.get("rangersPassEvent") or {}
    player = result.get("playerRangersPass") or {}
    seq = event.get("seq")
    if seq is None:
        return []
    earned = [r for r in player.get("playerRangersPassRewards", []) or []
              if not r.get("received") and not r.get("receiveReward")]
    if not earned and not player.get("receivableRandomBox"):
        return []
    return [("pass", ("POST", "/pass/receive/reward/%s/pass/all" % seq),
             "Rangers Pass seq=%s (%d earned)" % (seq, len(earned)))]


def survey_popups(cookie):
    """The "Maintenance Completion Rewards" / "Surprise Login Bonuses" popups.

    Tapping OK on one of these in-game is what actually deposits the goods into the gift
    box - before the tap the box is empty, after it the gift is there (measured). The
    client learns about them from its first home call, which carries two lists:
    `salesPopupResponse.salesPopups` (store offers) and `popupsWOSales` (everything else).
    Acknowledging one is POST /popup/reward/<id>, so this claims them the same way the OK
    button does.
    """
    now = int(time.time() * 1000)
    result = _get(cookie, "/home/raw?isFirst=true&Timestamp=%s&marketLocale=%s" % (now, MARKET_LOCALE))
    if not result:
        return []
    popups = list(result.get("popupsWOSales") or [])
    popups += list((result.get("salesPopupResponse") or {}).get("salesPopups") or [])
    jobs = []
    for popup in popups:
        # Most entries are plain announcements; only `rewardable` ones carry goods.
        # Do NOT gate on `ableToReceive` - that flag tracks the separate LINE-account
        # subscribe bonus and reads false even on a popup that has never been claimed.
        # The list itself is the unclaimed signal: a popup drops out of it once taken
        # (verified - seq 8115 vanished the moment it was claimed).
        if not popup.get("rewardable"):
            continue
        seq = popup.get("seq")
        if seq is None:
            continue
        jobs.append(("popup", ("POST", "/popup/reward/%s" % seq),
                     "%s (seq %s)" % (popup.get("contentTitle") or "login popup", seq)))
    return jobs


SOURCES = [
    ("login popups", survey_popups),
    ("gift box", survey_giftbox),
    ("7-day event", survey_sevendays),
    ("daily quest", survey_dailyquest),
    ("missions", survey_missions),
    ("attendance package", survey_attendance_package),
    ("rangers pass", survey_pass),
]
# ตัวที่ต้องถามใหม่ทุกรอบมีแค่กล่องของขวัญ ระบบที่เหลือจ่ายของ *เข้า* กล่อง ไม่ได้จ่าย
# เข้าหากัน การสำรวจครบเจ็ดแหล่งในรอบสองจึงเป็นการถามคำถามที่รู้คำตอบแล้วหกครั้ง
REFRESH_SOURCES = [("gift box", survey_giftbox)]


def survey(cookie, home=None, sources=None):
    """Collect claim jobs from every source.

    The collectors are independent read-only GETs, so they run concurrently: run
    back to back they cost the SUM of every round trip (~4.2s measured, with the
    popup call alone ~1.5s), in parallel only the slowest one.
    """
    sources = SOURCES if sources is None else sources

    def args_for(collect):
        return (cookie, home) if collect is survey_attendance_package else (cookie,)

    results = []
    if rangers_api.current_lane() is not None:
        # ใน engine (เธรดนี้ผูก lane ไว้): ถามทีละแหล่งบนเธรดนี้เอง ห้ามแตก thread pool
        # lane เป็น thread-local เธรดใน pool จึงไม่มี lane -> rangers_api ถอยไปใช้ถังแบบไฟล์ล็อก
        # (ของยุคหลายโปรเซส) และ proxy จาก env แทนของ lane ไม่ถูกนับในงบ req/s ของ lane และ
        # ปุ่ม Stop ตัดไม่ได้ วัดจริง 2026-09-25: ที่ ~160 เธรด survey แตกเธรดเพิ่มอีกเจ็ดเท่าแย่งล็อก
        # ไฟล์ถังจนค้าง ("bucket file stayed locked for 10.0s") ไอดีเสร็จเหลือ 2-3 ใบ/10 วิ แล้ว lane
        # ตายทั้งรัน ความขนานในบัญชีเดียวก็ไม่ได้อะไรอยู่แล้ว: เซิร์ฟเวอร์บังคับช่องว่าง ~300 ms ต่อบัญชี
        # ยิงพร้อมกันเจ็ดตัวได้ HTTP 400 errorCode 429 แล้วต้อง retry - engine ขนานกันที่ระดับบัญชีแทน
        for label, collect in sources:
            try:
                results.append((label, collect(*args_for(collect)), None))
            except Exception as err:        # one dead system must not sink the whole sweep
                results.append((label, [], err))
    else:
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            pending = [(label, pool.submit(collect, *args_for(collect)))
                       for label, collect in sources]
            for label, future in pending:
                try:
                    results.append((label, future.result(), None))
                except Exception as err:        # one dead system must not sink the whole sweep
                    results.append((label, [], err))

    jobs = []
    for label, found, err in results:
        if err is not None:
            print("  %-20s error: %s" % (label, str(err)[:70]))
            continue
        print("  %-20s %s" % (label, "%d claimable" % len(found) if found else "-"))
        jobs.extend(found)
    return jobs


def claim_all(cookie, confirm=True, passes=3, home=None):
    """Sweep every reward source and claim what is claimable. Returns how many were taken.

    Pass 1 surveys everything. Later passes re-check only the gift box: the other six
    systems pay INTO the gift box, never into each other, so none of them can hold
    anything new as a result of pass 1 - narrowing THEM to skip is free. That argument
    says nothing about the gift box itself, though: claim_giftbox mops up MINI_GACHA
    boxes that receive/all skips, and whether claiming one can drop a further gift back
    into the box is not established anywhere in this codebase. Three passes - not two -
    give that possible second hop somewhere to be caught; two would drop it silently.
    The extra pass costs one GET /giftbox/list in the common case where there was
    nothing left, since an empty survey breaks before issuing any claim.
    """
    total = 0
    for attempt in range(1, passes + 1):
        sources = SOURCES if attempt == 1 else REFRESH_SOURCES
        print("surveying reward sources (pass %d):" % attempt)
        jobs = survey(cookie, home=home if attempt == 1 else None, sources=sources)
        if not jobs:
            print("\nnothing left to claim" if attempt > 1 else "\nnothing to claim right now")
            break
        print("\n%d claimable item(s):" % len(jobs))
        for source, _action, label in jobs:
            print("  [%-14s] %s" % (source, label))

        if not confirm:
            print("\nDRY RUN - nothing claimed. Re-run with --confirm.")
            return 0

        print()
        claimed = 0
        for source, action, label in jobs:
            if callable(action):                      # multi-step claim (the gift box)
                good, detail = action(cookie), ""
            else:
                method, path = action
                status, data = call(cookie, path, method)
                good = status == 200 and isinstance(data, dict) and "result" in data
                detail = "" if good else "HTTP %s %s" % (status, str(data)[:60])
            claimed += bool(good)
            print("  [%-14s] %-44s %s" % (source, label[:44], "ok" if good else detail or "failed"))
        total += claimed
        print("\npass %d: claimed %d/%d" % (attempt, claimed, len(jobs)))
        if claimed == 0:                              # nothing succeeded - stop retrying
            break
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    parser.add_argument("--confirm", action="store_true", help="actually claim (default is a dry run)")
    args = parser.parse_args()

    cookie = resolve_cookie(args)
    player = check_session(cookie)
    print("account %s (level %s)" % (player.get("rsn"), player.get("level")))

    total = claim_all(cookie, confirm=args.confirm)
    if args.confirm:
        print("\ntotal claimed: %d" % total)


if __name__ == "__main__":
    main()
