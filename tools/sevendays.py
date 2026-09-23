r"""List and claim the LINE Rangers "New Players" 7-day event rewards (headless).

The NEW PLAYERS popup is the server's "sevendays" mission event: a cumulative
attendance track (Day 1..7), a set of daily missions per day, and one Final Reward
for finishing them. This lists the event and claims everything currently claimable.
Claiming needs --confirm (default is a dry run).

    python tools/sevendays.py list  --from-device
    python tools/sevendays.py claim --from-device            # DRY RUN
    python tools/sevendays.py claim --cookie "LF_AC=..." --confirm

Endpoints (verified live; all receives are POST):
    GET  /v12.3/mission/sevendays/list                                  -> result[0] (the event)
    POST /v12.3/mission/sevendays/receive/reward/{seq}/attendance/{day} -> claim attendance day
    POST /v12.3/mission/sevendays/receive/reward/{seq}/final            -> claim the Final Reward
    POST /v12.3/mission/sevendays/receive/reward/{seq}/daily/{day}/...  -> claim a daily mission
A reward is claimable when missionComplete==true and receiveReward==false (final:
finalMissionComplete==true and receiveFinalReward==false). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangers_api import call, add_session_args, resolve_cookie  # noqa: E402


def event(cookie):
    status, data = call(cookie, "/mission/sevendays/list")
    if status != 200 or not isinstance(data, dict) or not data.get("result"):
        raise SystemExit("sevendays/list failed (HTTP %s): %s" % (status, str(data)[:200]))
    return data["result"][0]


def _reward_str(mission):
    return ", ".join("%s x%s" % (r.get("code"), r.get("amount")) for r in mission.get("missionRewards", []))


def show(ev):
    seq = ev.get("seq")
    print("New Players event seq=%s  continuousDay=%s  finalComplete=%s finalReceived=%s"
          % (seq, ev.get("currentContinuousDay"), ev.get("finalMissionComplete"), ev.get("receiveFinalReward")))
    print("final reward: %s %s x%s" % (ev.get("finalRewardType"), ev.get("finalRewardCode"), ev.get("finalRewardCount")))

    print("\nattendance (day / complete / received / reward):")
    for a in ev.get("playerAttendanceMissions", []):
        day = a.get("missionCondition")
        print("  day %-2s  %-5s %-5s  %s" % (day, a.get("missionComplete"), a.get("receiveReward"), _reward_str(a)))

    print("\ndaily missions (only incomplete/unclaimed shown):")
    for dm in ev.get("playerDailyMissions", []):
        for m in dm.get("detail", []):
            if m.get("receiveReward"):
                continue
            print("  day %-2s %-16s %s/%s  complete=%s  %s" % (
                dm.get("day"), m.get("missionType"), m.get("currentCount"), m.get("completionCount"),
                m.get("missionComplete"), _reward_str(m)))


def claimable(ev):
    """Return lists of (kind, path, label) for everything claimable right now."""
    seq = ev.get("seq")
    out = []
    for a in ev.get("playerAttendanceMissions", []):
        if a.get("missionComplete") and not a.get("receiveReward"):
            day = a.get("missionCondition")
            out.append(("attendance",
                        "/mission/sevendays/receive/reward/%s/attendance/%s" % (seq, day),
                        "attendance day %s (%s)" % (day, _reward_str(a))))
    for dm in ev.get("playerDailyMissions", []):
        day = dm.get("day")
        for m in dm.get("detail", []):
            if m.get("missionComplete") and not m.get("receiveReward"):
                # daily receive path template is /daily/{day}/{missionType}/{sort}; server
                # identifies the mission by these. Left best-effort until one completes live.
                path = "/mission/sevendays/receive/reward/%s/daily/%s/%s/%s" % (
                    seq, day, m.get("missionType"), m.get("sort"))
                out.append(("daily", path, "day %s %s (%s)" % (day, m.get("missionType"), _reward_str(m))))
    if ev.get("finalMissionComplete") and not ev.get("receiveFinalReward"):
        out.append(("final",
                    "/mission/sevendays/receive/reward/%s/final" % seq,
                    "FINAL %s %s x%s" % (ev.get("finalRewardType"), ev.get("finalRewardCode"), ev.get("finalRewardCount"))))
    return out


def cmd_claim(cookie, do_confirm):
    todo = claimable(event(cookie))
    if not todo:
        print("nothing claimable right now (finish missions / log in on later days first)")
        return
    print("claimable now: %d" % len(todo))
    for _kind, _path, label in todo:
        print("  - " + label)
    if not do_confirm:
        print("\nDRY RUN - nothing claimed. Re-run with --confirm.")
        return
    print()
    for kind, path, label in todo:
        status, data = call(cookie, path, "POST")
        ok = status == 200 and isinstance(data, dict) and data.get("result") is not None
        print("  %-10s %-40s %s" % (kind, label, "ok" if ok else "HTTP %s %s" % (status, str(data)[:80])))


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
        show(event(cookie))
    elif args.command == "claim":
        cmd_claim(cookie, args.confirm)


if __name__ == "__main__":
    main()
