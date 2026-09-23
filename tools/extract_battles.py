"""Extract LINE Rangers stage-battle exchanges from a capture, after the fact.

The live addon (addons/stage_battle_recorder.py) writes per-battle files while
you play. This does the same thing offline, reading either a mitmproxy flow
file (.mitm) or a game_api_logger transcript (.jsonl), so an existing capture
can be mined without replaying it - and so a play session captured with only
the general logger still yields clean battle files.

Usage:
    python tools/extract_battles.py captures/flows-rangers-api-live.mitm
    python tools/extract_battles.py captures/api-20260915-....jsonl
    python tools/extract_battles.py --scan captures            # every file in a dir
    python tools/extract_battles.py --out captures/battles <file>

It pairs each /stage/enter (which carries battleSn + rsaKeyBase.modulus) with
the /stage/save that follows (which carries the encrypted battleKey + log) and
reports, per save, whether log/battleKey/modulus were present. Prints a summary
even when nothing matched, so an empty result is never ambiguous.
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
from datetime import datetime

ENTER_FRAGMENTS = ("/stage/enter/", "/tutorial/stage/enter")
SAVE_FRAGMENTS = ("/stage/save/", "/tutorial/stage/save")
RESEND_FRAGMENTS = ("/stage/resend", "/tutorial/stage/resend")


# -- shared parsing helpers (mirrors the live addon) ----------------------

def body_view(raw: bytes) -> dict:
    if not raw:
        return {"kind": "empty", "size": 0}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "kind": "binary",
            "size": len(raw),
            "base64": base64.b64encode(raw).decode("ascii"),
            "hex_head": raw[:48].hex(),
        }
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            return {"kind": "json", "size": len(raw), "json": json.loads(stripped)}
        except ValueError:
            pass
    return {"kind": "text", "size": len(raw), "text": text}


def json_of(view):
    return view.get("json") if isinstance(view, dict) else None


def dig(obj, *keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def find_key(obj, target):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target:
                return v
            found = find_key(v, target)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key(item, target)
            if found is not None:
                return found
    return None


def match(path, fragments):
    low = (path or "").lower()
    return any(fr in low for fr in fragments)


def sn_and_stage_from_save_path(path):
    clean = (path or "").split("?", 1)[0]
    parts = [p for p in clean.split("/") if p]
    if "save" in parts:
        i = parts.index("save")
        stage = parts[i + 1] if i + 1 < len(parts) else None
        sn = parts[i + 2] if i + 2 < len(parts) else None
        return stage, sn
    return None, None


def stage_from_enter_path(path):
    clean = (path or "").split("?", 1)[0]
    parts = [p for p in clean.split("/") if p]
    if "enter" in parts:
        i = parts.index("enter")
        return parts[i + 1] if i + 1 < len(parts) else None
    return None


# -- source readers: yield uniform (path, status, req_view, resp_view) ----

def iter_mitm(path):
    from mitmproxy.io import FlowReader
    from mitmproxy.http import HTTPFlow

    with open(path, "rb") as fh:
        for f in FlowReader(fh).stream():
            if not isinstance(f, HTTPFlow):
                continue
            req = f.request
            resp = f.response
            yield (
                req.path,
                resp.status_code if resp else None,
                body_view(req.raw_content or b""),
                body_view((resp.raw_content if resp else b"") or b""),
            )


def iter_jsonl(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") != "http":
                continue
            req = rec.get("request", {}) or {}
            resp = rec.get("response", {}) or {}
            # game_api_logger already stored bodies as {"kind","json"/"text"/...}.
            yield (
                rec.get("path"),
                rec.get("status"),
                req.get("body", {}) or {},
                resp.get("body", {}) or {},
            )


def iter_source(path):
    if path.lower().endswith(".mitm"):
        return iter_mitm(path)
    if path.lower().endswith(".jsonl"):
        return iter_jsonl(path)
    raise ValueError("unknown capture type (need .mitm or .jsonl): %s" % path)


# -- extraction -----------------------------------------------------------

def extract(files, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    enters = {}
    last_enter = None
    battles = []
    enters_seen = 0

    for path in files:
        try:
            it = iter_source(path)
        except ValueError as e:
            print("  skip:", e)
            continue
        for rpath, status, req_view, resp_view in it:
            if match(rpath, ENTER_FRAGMENTS):
                enters_seen += 1
                resp_json = json_of(resp_view)
                sn = find_key(resp_json, "battleSn")
                modulus = dig(resp_json, "result", "rsaKeyBase", "modulus") or find_key(resp_json, "modulus")
                rec = {
                    "kind": "tutorial" if "/tutorial/" in (rpath or "").lower() else "stage",
                    "stageCode": stage_from_enter_path(rpath),
                    "battleSn": sn,
                    "path": rpath,
                    "status": status,
                    "request": req_view,
                    "response": resp_view,
                    "rsaKeyBase_modulus": modulus,
                }
                if sn is not None:
                    enters[str(sn)] = rec
                last_enter = rec
            elif match(rpath, SAVE_FRAGMENTS) or match(rpath, RESEND_FRAGMENTS):
                is_resend = match(rpath, RESEND_FRAGMENTS)
                stage, sn = sn_and_stage_from_save_path(rpath)
                enter_rec = enters.get(str(sn)) if sn is not None else None
                if enter_rec is None:
                    enter_rec = last_enter
                req_json = json_of(req_view)
                log_field = find_key(req_json, "log") if req_json else None
                battle_key = find_key(req_json, "battleKey") if req_json else None
                top = sorted(req_json.keys()) if isinstance(req_json, dict) else None
                modulus = enter_rec.get("rsaKeyBase_modulus") if enter_rec else None
                resp_json = json_of(resp_view)
                battles.append({
                    "kind": "tutorial" if "/tutorial/" in (rpath or "").lower() else "stage",
                    "is_resend": bool(is_resend),
                    "stageCode": stage,
                    "battleSn": sn,
                    "save": {"path": rpath, "status": status, "request": req_view, "response": resp_view},
                    "enter": enter_rec,
                    "analysis": {
                        "save_top_level_fields": top,
                        "has_log": log_field is not None,
                        "log_len": len(log_field) if isinstance(log_field, str) else None,
                        "has_battleKey": battle_key is not None,
                        "battleKey_len": len(battle_key) if isinstance(battle_key, str) else None,
                        "paired_enter_found": bool(enter_rec and enter_rec.get("battleSn") is not None),
                        "rsaKeyBase_modulus_len": len(str(modulus)) if modulus else None,
                        "response_errorCode": find_key(resp_json, "errorCode") if resp_json else None,
                    },
                })

    written = []
    for i, b in enumerate(battles, 1):
        fname = "extract_%s_%s_sn%s_%s.json" % (
            "resend" if b["is_resend"] else "save",
            b["stageCode"] or "unknown",
            b["battleSn"] or "none",
            b["save"]["status"] or "err",
        )
        outp = os.path.join(out_dir, fname)
        with open(outp, "w", encoding="utf-8") as fh:
            json.dump(b, fh, ensure_ascii=False, indent=2, default=str)
        written.append(outp)

    print("\n==== extract_battles summary ====")
    print("enters seen        :", enters_seen)
    print("saves/resends found:", len(battles))
    for b in battles:
        a = b["analysis"]
        print("  - %s sn=%s stage=%s status=%s  log=%s(%s) battleKey=%s(%s) modulus=%s errCode=%s" % (
            "resend" if b["is_resend"] else "save",
            b["battleSn"], b["stageCode"], b["save"]["status"],
            a["has_log"], a["log_len"], a["has_battleKey"], a["battleKey_len"],
            a["rsaKeyBase_modulus_len"], a["response_errorCode"],
        ))
    if written:
        print("wrote %d file(s) to %s" % (len(written), out_dir))
    else:
        print("no battles found in the given capture(s).")
    return battles


def main():
    ap = argparse.ArgumentParser(description="Extract stage-battle exchanges from a capture.")
    ap.add_argument("inputs", nargs="*", help=".mitm or .jsonl capture file(s)")
    ap.add_argument("--scan", metavar="DIR", help="scan every .mitm/.jsonl in DIR")
    ap.add_argument("--out", default="captures/battles", help="output directory")
    args = ap.parse_args()

    files = list(args.inputs)
    if args.scan:
        files += sorted(glob.glob(os.path.join(args.scan, "*.mitm")))
        files += sorted(glob.glob(os.path.join(args.scan, "*.jsonl")))
    if not files:
        ap.error("give at least one capture file, or --scan DIR")
    extract(files, args.out)


if __name__ == "__main__":
    main()
