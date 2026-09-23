"""Summarise a captured transcript: which endpoints the game actually calls.

    python tools/summarize.py                     # newest transcript in captures/
    python tools/summarize.py captures/api-x.jsonl
    python tools/summarize.py --host lgrgs        # only hosts matching a substring
    python tools/summarize.py --show /api/user    # full detail for matching paths

Standard library only, so the system Python runs it without a virtualenv.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, OrderedDict

CAPTURE_GLOB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "api-*.jsonl")

# Collapse the parts of a path that are identifiers so repeated calls to the
# same endpoint group together instead of showing up as hundreds of one-offs.
_DIGITS = re.compile(r"^\d+$")
_HEXISH = re.compile(r"^[0-9a-fA-F]{8,}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def normalise(path: str) -> str:
    path = path.split("?", 1)[0]
    parts = []
    for part in path.split("/"):
        if _DIGITS.match(part):
            parts.append("{id}")
        elif _UUID.match(part):
            parts.append("{uuid}")
        elif _HEXISH.match(part):
            parts.append("{hex}")
        else:
            parts.append(part)
    return "/".join(parts) or "/"


def load(path: str):
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                print("  (skipped unparseable line %d)" % line_no, file=sys.stderr)
    return records


def newest_capture() -> str:
    matches = sorted(glob.glob(CAPTURE_GLOB), key=os.path.getmtime, reverse=True)
    if not matches:
        raise SystemExit("No transcripts found. Run a capture first (scripts\\capture.ps1).")
    return matches[0]


def body_summary(body: dict, limit: int) -> str:
    if not body:
        return ""
    kind = body.get("kind")
    if kind == "empty":
        return "(empty)"
    if kind == "json":
        text = json.dumps(body.get("json"), ensure_ascii=False)
    elif kind == "text":
        text = body.get("text", "")
    elif "protobuf_guess" in body:
        text = "protobuf? " + json.dumps(body["protobuf_guess"], ensure_ascii=False)
    else:
        text = "<binary %d bytes> %s" % (body.get("size", 0), body.get("hex_head", ""))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + " ..."
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", nargs="?", help="path to an api-*.jsonl file")
    parser.add_argument("--host", default="", help="only include hosts containing this substring")
    parser.add_argument("--show", default="", help="print full detail for paths containing this substring")
    parser.add_argument("--limit", type=int, default=400, help="max characters per body in --show output")
    args = parser.parse_args()

    path = args.transcript or newest_capture()
    records = load(path)
    print("transcript: %s  (%d entries)" % (path, len(records)))

    http = [r for r in records if r.get("kind") == "http"]
    if args.host:
        needle = args.host.lower()
        http = [r for r in http if needle in (r.get("host") or "").lower()]

    hosts = Counter(r.get("host") for r in http)
    if hosts:
        print("\nhosts")
        width = max(len(h or "") for h in hosts)
        for host, count in hosts.most_common():
            print("  %-*s  %d" % (width, host, count))

    endpoints = OrderedDict()
    for record in http:
        key = (record.get("method"), record.get("host"), normalise(record.get("path") or ""))
        entry = endpoints.setdefault(key, {"count": 0, "status": Counter(), "durations": [], "sent": 0, "received": 0})
        entry["count"] += 1
        entry["status"][record.get("status")] += 1
        if record.get("duration_ms") is not None:
            entry["durations"].append(record["duration_ms"])
        entry["sent"] += (record.get("request", {}).get("body", {}) or {}).get("size", 0)
        entry["received"] += (record.get("response", {}).get("body", {}) or {}).get("size", 0)

    if endpoints:
        print("\nendpoints")
        rows = sorted(endpoints.items(), key=lambda kv: -kv[1]["count"])
        label_width = max(len("%s %s%s" % (k[0], k[1], k[2])) for k in endpoints)
        label_width = min(label_width, 90)
        print("  %-*s  %5s  %-14s  %8s  %10s" % (label_width, "endpoint", "calls", "status", "avg ms", "sent/recv"))
        for (method, host, norm_path), entry in rows:
            label = "%s %s%s" % (method, host, norm_path)
            if len(label) > label_width:
                label = label[: label_width - 3] + "..."
            statuses = ",".join("%s x%d" % (s, c) for s, c in entry["status"].most_common(3))
            if entry["durations"]:
                avg = "%d" % (sum(entry["durations"]) / len(entry["durations"]))
            else:
                avg = "-"
            traffic = "%d/%d" % (entry["sent"], entry["received"])
            print("  %-*s  %5d  %-14s  %8s  %10s" % (label_width, label, entry["count"], statuses, avg, traffic))

    failures = [r for r in records if r.get("kind") == "tls_failed"]
    if failures:
        print("\nTLS handshakes that failed (these hosts likely pin their certificate)")
        for host, count in Counter(r.get("host") for r in failures).most_common():
            print("  %-50s  %d" % (host, count))

    errors = [r for r in records if r.get("kind") == "http_error"]
    if errors:
        print("\nrequest errors")
        for message, count in Counter("%s - %s" % (r.get("host"), r.get("error")) for r in errors).most_common(15):
            print("  %-70s  %d" % (message, count))

    websockets = [r for r in records if r.get("kind") == "websocket"]
    if websockets:
        print("\nwebsocket messages: %d" % len(websockets))
        for host, count in Counter(r.get("host") for r in websockets).most_common():
            print("  %-50s  %d" % (host, count))

    tcp = [r for r in records if r.get("kind") == "tcp_message"]
    if tcp:
        print("\nraw TCP messages: %d" % len(tcp))
        per_host = defaultdict(lambda: {"out": 0, "in": 0, "bytes_out": 0, "bytes_in": 0})
        for record in tcp:
            entry = per_host[record.get("host")]
            size = (record.get("body") or {}).get("size", 0)
            if record.get("direction") == "client->server":
                entry["out"] += 1
                entry["bytes_out"] += size
            else:
                entry["in"] += 1
                entry["bytes_in"] += size
        for host, entry in sorted(per_host.items(), key=lambda kv: -(kv[1]["bytes_in"] + kv[1]["bytes_out"])):
            print("  %-40s  sent %d msg / %d B   received %d msg / %d B" % (
                host, entry["out"], entry["bytes_out"], entry["in"], entry["bytes_in"]))
        readable = [r for r in tcp if (r.get("body") or {}).get("kind") in ("json", "text")]
        print("  %d of %d messages decoded as text or JSON" % (len(readable), len(tcp)))

    if args.show:
        needle = args.show.lower()
        matching = [r for r in http if needle in (r.get("path") or "").lower()]
        print("\ndetail for paths containing %r  (%d matches)" % (args.show, len(matching)))
        for record in matching:
            print("\n  [#%s] %s %s -> %s  %s ms" % (
                record.get("seq"), record.get("method"), record.get("url"),
                record.get("status"), record.get("duration_ms")))
            print("    -> %s" % body_summary(record.get("request", {}).get("body"), args.limit))
            print("    <- %s" % body_summary(record.get("response", {}).get("body"), args.limit))


if __name__ == "__main__":
    main()
