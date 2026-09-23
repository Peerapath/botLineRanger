r"""Pull the player-owned ranger roster from the LINE Rangers API.

The game's own roster call is certificate-pinned (libcurl CURLOPT_PINNEDPUBLICKEY),
so it cannot be read through mitmproxy. Instead we act as a legitimate client: we
reuse the LF_AC session token the game already sent on a bootstrap call (captured by
the proxy) and replay the roster request straight to the real server. No pinning is
involved because we are the client, not a man in the middle.

Endpoint (verified in libgame.so, fetched by UnitManager::requestPlayerUnit()):
    GET https://rangers-api.line-apps.com/v12.3/player/units/equip?inven=true&team=true&deck=true
    Cookie: LF_AC=<session token>
    UID:    <session uid>

The LF_AC token is short-lived (~1 hour). To get a fresh one:
  1. Run the proxy:   .\scripts\start-proxy.ps1 -Dump      (or capture.ps1)
  2. Start / restart the game so it re-authenticates through the proxy.
  3. Run this script - it reads the newest captured token automatically.

    python tools/pull_roster.py                 # newest token, write timestamped files
    python tools/pull_roster.py --cookie "LF_AC=..." --uid rnm0...   # explicit token

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import glob
import gzip
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
CAPTURE_GLOB = os.path.join(ROOT, "captures", "*.jsonl")
OUT_DIR = os.path.join(ROOT, "roster")

HOST = "rangers-api.line-apps.com"
ROSTER_PATH = "/v12.3/player/units/equip?inven=true&team=true&deck=true"

EVOLUTION = {"": "base", "e": "evolved", "h": "hyper", "u": "ultra", "s": "special"}


def _iter_rangers_records():
    for path in glob.glob(CAPTURE_GLOB):
        try:
            handle = open(path, "r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line or '"rangers-api' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("kind") == "http" and "rangers-api" in (record.get("host") or ""):
                    yield record


def newest_auth_from_captures():
    """Return (cookie, uid, when) for the freshest usable session, or (None, None, None).

    The token that authorizes game calls is the LF_AC set in the *login response*
    (Set-Cookie), paired with the login result's `id` as the UID. That is the
    primary source and works for both Google and Guest logins with only the proxy
    running. As a fallback we use an authenticated GET (e.g. exapi/nation.nhn),
    which carries LF_AC in the request cookie plus a UID header - but that only
    reaches the proxy when native traffic is being redirected (iptables DNAT).
    """
    primary = None   # from login response: (when, "LF_AC=...", uid)
    fallback = None   # from authed request: (when, cookie, uid)
    for record in _iter_rangers_records():
        path = record.get("path") or ""
        when = record.get("time", "")

        # captures can hold either prefix - the client bumped 12.2 -> 12.3 mid-project
        if "/login" in path and path.startswith("/v12."):
            lf = None
            for key, value in record["response"]["headers"].items():
                if key.lower() == "set-cookie" and "LF_AC=" in value:
                    match = re.search(r"LF_AC=([^;]+)", value)
                    if match:
                        lf = match.group(1)
            body = record["response"]["body"]
            uid = body["json"].get("result", {}).get("id") if body.get("kind") == "json" else None
            if lf and uid and (primary is None or when > primary[0]):
                primary = (when, "LF_AC=" + lf, uid)

        headers = {k.lower(): v for k, v in record["request"]["headers"].items()}
        cookie = headers.get("cookie", "")
        uid_header = headers.get("uid")
        if "LF_AC" in cookie and uid_header and (fallback is None or when > fallback[0]):
            fallback = (when, cookie, uid_header)

    best = primary or fallback
    if primary and fallback and fallback[0] > primary[0]:
        best = fallback
    if not best:
        return None, None, None
    return best[1], best[2], best[0]


def fetch_roster(cookie: str, uid: str) -> bytes:
    now = int(time.time() * 1000)
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
    }
    if uid:   # optional - the server derives the player from LF_AC, so device sessions omit it
        headers["UID"] = uid
    request = urllib.request.Request("https://" + HOST + ROSTER_PATH, headers=headers, method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=25)
        raw = response.read()
        status = response.status
        encoding = response.headers.get("Content-Encoding")
    except urllib.error.HTTPError as err:
        raw = err.read()
        status = err.code
        encoding = err.headers.get("Content-Encoding")
    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    if status != 200:
        raise SystemExit(
            "Server returned HTTP %s: %s\n"
            "The session token has most likely expired - restart the game with the proxy "
            "running to capture a fresh one, then try again." % (status, raw[:200].decode("utf-8", "replace"))
        )
    return raw


def base_name(code: str) -> str:
    match = re.match(r"u\d+[a-z]?-(.+)", code or "")
    return match.group(1) if match else (code or "")


def evolution_of(code: str) -> str:
    match = re.match(r"u(\d+)([a-z]?)-", code or "")
    return EVOLUTION.get(match.group(2), match.group(2)) if match else "?"


def fuzzy_match(ocr_text, target_text, threshold=1):
    # ลบช่องว่าง และทำเป็น lower case เพื่อลดความผิดพลาด
    o = re.sub(r"\s+", "", ocr_text).lower()
    t = re.sub(r"\s+", "", target_text).lower()

    ratio = difflib.SequenceMatcher(None, o, t).ratio()
    return ratio >= threshold, ratio


def matchGachaName(allNames:dict, name:str):
    for key in allNames.keys():
        is_match, score = fuzzy_match(key, name)
        # print(is_match, f"{score:.2f}", "||", key, "=", name)
        if is_match:
            return True, allNames[key].replace(" ", "")
    return False, name.replace(" ", "")


def add_ranger_name(rangerNames: str, rangerName: str) -> str:

    if rangerNames == "":
        return rangerName

    names = rangerNames.split("_")

    def split_name_number(name):
        m = re.match(r"^(.*?)(\d+)$", name)
        if m:
            return m.group(1), int(m.group(2))
        return name, None

    base_matches = []
    for i, name in enumerate(names):
        base, num = split_name_number(name)
        if base == rangerName:
            base_matches.append((i, base, num))

    if not base_matches:
        return rangerNames + "_" + rangerName

    # ให้ update ชื่อเก่าตัวแรกที่เจอ (index ต่ำสุด)
    idx, base, num = base_matches[0]

    # ถ้าไม่มีเลข เช่น Cony → Cony2
    if num is None:
        new_name = f"{base}2"
    else:
        new_name = f"{base}{num + 1}"

    names[idx] = new_name

    return "_".join(names)


def unit_names(units, ranger_config=None):
    """สรุปคลัง ranger เป็นข้อความสำหรับตั้งชื่อไฟล์ที่ export

    ย้ายมาจาก botLineRanger.getTeanInfo() ตัวที่ยิง API ไม่ได้ย้ายมาด้วยเพราะผู้เรียก
    ฝั่ง engine ยิงเองแล้วส่งผลลัพธ์เข้ามา - จะได้ไม่ยิงซ้ำ

    Correction to that framing: the loop this function moves (RANGERSCONFIG match ->
    add_ranger_name accumulate) is not in getTeanInfo's own body - it lives in the caller
    that consumes getTeanInfo's result, botLineRanger.getAccoutInfo() (its rangerNames
    variable is exactly this function's return value, fed into the exported filename as
    f"{rangerNames}_Rb{ruby}_Tk{ticket}_{gameID}_Lv{level}"). getTeanInfo itself only
    fetches the roster and tags each row with base_name()/evolution_of(); it never calls
    matchGachaName or add_ranger_name. See task-6-report.md for the full note - this is
    called out rather than silently "corrected" so it can be checked against the source.

    units: playerUnits-shaped dicts (only "unitCode" is read - the raw API list and
      getTeanInfo's transformed rows both qualify, so callers can pass either)
    ranger_config: RANGERSCONFIG-shaped dict (unitCode.lower() -> display name), the same
      dict matchGachaName takes as allNames. None (the default) means "nothing configured
      as a target", so every unit is a no-match and the result is "" - not a crash.

    matchGachaName's threshold defaults to 1 (100% SequenceMatcher ratio), so despite the
    name this is an exact match after whitespace-stripping and lowercasing, not a fuzzy
    one - same effective lookup as targets.get(code.lower()) in gacha.draw_with_ticket,
    just written as an O(n) scan instead of a dict get. add_ranger_name then folds each
    match into the accumulated string, incrementing a numeric suffix for repeats
    (Cony, Cony -> "Cony2", not "Cony_Cony2" - see add_ranger_name above).
    """
    ranger_config = ranger_config or {}
    rangerNames = ""
    for i in units:
        unitCode = i["unitCode"]
        is_match, rangerName = matchGachaName(ranger_config, unitCode)
        if is_match:
            rangerNames = add_ranger_name(rangerNames, rangerName)
    return rangerNames


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cookie", help="LF_AC=... cookie value (overrides capture auto-detect)")
    parser.add_argument("--uid", help="session UID (optional; server derives it from LF_AC)")
    parser.add_argument("--from-device", action="store_true",
                        help="read the live LF_AC straight off the logged-in device (hybrid path)")
    parser.add_argument("--device", help="adb serial for --from-device")
    parser.add_argument("--xml", help="account file (_LINE_COCOS_PREF_KEY.xml) to read the session from")
    args = parser.parse_args()

    cookie, uid = args.cookie, args.uid
    if args.xml:
        from account_file import read_pref_xml
        cookie, uid = "LF_AC=" + read_pref_xml(args.xml)[1], None
    elif args.from_device:
        from device_session import get_lfac_from_device
        cookie, uid = "LF_AC=" + get_lfac_from_device(args.device), None
        print("Using LF_AC read from device %s" % (args.device or "(default)"))
    elif not cookie:
        cookie, uid, when = newest_auth_from_captures()
        if not cookie:
            raise SystemExit(
                "No session token. Either --from-device (app logged in on an adb device), or "
                "start the proxy and (re)launch the game so it authenticates through it."
            )
        print("Using session token captured at %s (UID %s)" % (when, uid))

    raw = fetch_roster(cookie, uid)
    data = json.loads(raw)
    units = data["result"]["playerUnits"]

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(OUT_DIR, "roster_raw-%s.json" % stamp), "wb") as handle:
        handle.write(raw)

    rows = []
    for unit in units:
        code = unit.get("unitCode", "")
        rows.append(
            {
                "invenId": unit.get("invenId"),
                "unitCode": code,
                "name": base_name(code),
                "level": unit.get("unitLevel"),
                "maxLevel": unit.get("playerUnitMaxLevel"),
                "evolution": evolution_of(code),
                "locked": unit.get("lockYn"),
                "talentGrade": unit.get("talentGrade"),
            }
        )

    csv_path = os.path.join(OUT_DIR, "rangers_roster-%s.csv" % stamp)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    from collections import Counter

    print("\nTotal owned rangers: %d" % len(rows))
    print("Distinct characters:  %d" % len(set(r["name"] for r in rows)))
    print("\nBy evolution tier:")
    for tier, count in Counter(r["evolution"] for r in rows).most_common():
        print("  %-8s %d" % (tier, count))
    print("\nMost-owned characters:")
    for name, count in Counter(r["name"] for r in rows).most_common(15):
        print("  %-16s x%d" % (name, count))
    print("\nSaved: %s" % csv_path)


if __name__ == "__main__":
    main()
