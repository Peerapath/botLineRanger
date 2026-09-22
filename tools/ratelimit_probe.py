r"""Hammer rangers-api through rangers_api.call from N threads (one fresh guest token each) and
report how many nginx 429 / app-429 (HTTP 400 + errorCode 429) slipped through the limiter.

    python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10

With the limiter on (default env) both counts must be 0 and the throughput ~LGRGS_RPS_BUDGET.
Set LGRGS_RPS_BUDGET=0 LGRGS_MIN_GAP_MS=0 to see the raw server behaviour again.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratelimit  # noqa: E402
import rangers_api  # noqa: E402
import relogin  # noqa: E402


def fresh_token(xml_path, pool):
    acc = relogin.read_account(xml_path)
    guest_cookie = relogin.decrypt_lfac(acc["udid"], acc["enc"])
    _st, _res, lf = relogin.login(pool.get(), acc["udid"], guest_cookie, acc["nation"], acc["language"])
    return "LF_AC=" + lf if lf else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml-dir", default="bot/input")
    ap.add_argument("--workers", type=int, default=150)
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--path", default="/stage/last")
    args = ap.parse_args(argv)

    xmls = sorted(glob.glob(os.path.join(args.xml_dir, "*.xml")))[:args.workers]
    pool = relogin.CcPool()
    with cf.ThreadPoolExecutor(10) as ex:
        tokens = [t for t in ex.map(lambda x: fresh_token(x, pool), xmls) if t]
    print("tokens: %d/%d" % (len(tokens), len(xmls)))

    counts, lock = {}, threading.Lock()
    t_end = time.time() + args.seconds

    def worker(tok):
        while time.time() < t_end:
            status, body = rangers_api.call(tok, args.path)
            kind = ("app429" if ratelimit.is_app_429(status, body) is not None
                    else "nginx429" if status == 429 else "ok" if status == 200 else "other%s" % status)
            with lock:
                counts[kind] = counts.get(kind, 0) + 1

    t0 = time.time()
    with cf.ThreadPoolExecutor(len(tokens)) as ex:
        list(ex.map(worker, tokens))
    total = sum(counts.values())
    print("workers=%d total=%d rps=%.1f counts=%s" % (len(tokens), total, total / (time.time() - t0), counts))
    return 0 if not counts.get("app429") and not counts.get("nginx429") else 1


if __name__ == "__main__":
    sys.exit(main())
