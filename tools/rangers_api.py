r"""Shared helpers for driving the LINE Rangers API with a captured/decrypted LF_AC.

Every game call is the same pinned endpoint replayed as a legit client: LF_AC cookie,
the app's exact headers, and NO UID (the server derives the player from LF_AC). Tools
get their session three ways, in priority order:
  --cookie "LF_AC=..."     explicit token
  --xml <account.xml>      decrypt it out of an account file (what new_account.py writes)
  --from-device [--device] decrypt it off a rooted, logged-in device (guest accounts)
  (captured jsonl)         newest login Set-Cookie from captures/ (proxy path)
"""

from __future__ import annotations

import gzip
import http.client
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

import ratelimit
import client_version

HOST = "rangers-api.line-apps.com"

# Old names, kept because standalone scripts still read them. Nothing in tools/ or bot/engine/
# sends with them any more: every call takes its prefix and App-Version from client_version,
# which learns from the server when a value stops being accepted (see that module). The server
# does route each version separately - /v12.3/popup/reward/<seq> returns 500 for a CLS_GACHA
# reward under an older prefix - which is exactly why the prefix is managed, not hardcoded.
API = "/v12.3"
CLIENT_VERSION = "12.3.0"

# --- 429/503 backoff-retry -------------------------------------------------------------
# Running many workers hammers one shared server, so it answers some calls with 429 (Too Many
# Requests) or 503 (overload/maintenance) - a non-JSON HTML body. Instead of failing the call
# (which used to surface as a mystery "string indices" TypeError downstream), wait and retry.
# Bounded + exponential + JITTERED so the retries themselves don't become a thundering herd
# that amplifies the very overload we're backing off from; honor Retry-After when the server
# sends it. Tune the ceiling with LGRGS_MAX_RETRY (total tries per call, incl. the first).
# The per-account limit answers HTTP 400 + {"errorCode":429} instead - detected via
# ratelimit.is_app_429 and retried the same way (see tools/ratelimit.py).
RETRY_STATUSES = (429, 503)
MAX_ATTEMPTS = max(1, int(os.environ.get("LGRGS_MAX_RETRY", "8")))
_BACKOFF_BASE = 0.5   # seconds
_BACKOFF_CAP = 8.0    # seconds (per-wait ceiling for the exponential term)


def _retry_sleep(attempt, retry_after=None):
    """Sleep before the next retry after a rate-limited/overloaded response.

    Honors a numeric Retry-After header (capped so a bogus huge value can't hang a worker),
    otherwise exponential backoff base*2**attempt capped at _BACKOFF_CAP, plus random jitter
    in [0, base) so thousands of workers that all got 429 at once don't retry in lockstep.
    """
    delay = None
    if retry_after:
        try:
            delay = min(float(retry_after), _BACKOFF_CAP * 2)
        except (TypeError, ValueError):
            delay = None
    if delay is None:
        delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt))
    time.sleep(delay + random.uniform(0, _BACKOFF_BASE))


# Connection และ lane ต้องเป็น thread-local คู่กัน: lane บอกว่า "ออก IP ไหนและใช้งบของใคร"
# ส่วน connection คือ socket ที่เปิดไปบน IP นั้นแล้ว ถ้าเก็บ lane ไว้ระดับโมดูล (แบบที่
# ratelimit.PROXY_PARTS เคยเป็น) เธรดจะได้ socket ของ IP หนึ่งแต่ไปหักงบของอีก IP
# พอโปรเซสเดียววิ่งหลาย proxy พร้อมกัน
_tls = threading.local()


def use_lane(lane) -> None:
    """ผูก lane เข้ากับเธรดนี้ ต้องเรียกก่อน call() ตัวแรกของเธรด

    เปลี่ยน lane = ทิ้ง connection เดิม เพราะ socket เก่าเปิดไปบน proxy ตัวก่อน
    การใช้ต่อคือการส่ง request ออก IP ที่ไม่ได้ตั้งใจโดยที่งบไปหักอีกที่หนึ่ง
    """
    if getattr(_tls, "lane", None) is not lane:
        _drop_conn()
    _tls.lane = lane


def current_lane():
    return getattr(_tls, "lane", None)


def _get_conn():
    conn = getattr(_tls, "conn", None)
    if conn is None:
        lane = current_lane()
        # ไม่มี lane = ถูกเรียกจาก CLI ของ tools/ ตัวใดตัวหนึ่ง ใช้ค่าระดับโมดูลแบบเดิม
        proxy = lane.parts if lane is not None else ratelimit.PROXY_PARTS
        if proxy:
            phost, pport, auth = proxy
            conn = http.client.HTTPSConnection(phost, pport, timeout=25)
            conn.set_tunnel(HOST, 443, headers={"Proxy-Authorization": auth} if auth else None)
        else:
            conn = http.client.HTTPSConnection(HOST, timeout=25)
        _tls.conn = conn
    return conn


def _drop_conn():
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _tls.conn = None


def _decode(raw: bytes, enc):
    if enc == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def call(cookie: str, path: str, method: str = "GET", body=None, api: str | None = None,
         extra_headers: dict | None = None):
    """Return (status, parsed). `cookie` is the full 'LF_AC=...' value.

    `path` is relative to the API prefix and must NOT carry it - client_version picks the
    prefix and App-Version, and switches them when the server stops accepting them. `api` pins
    this one call to a prefix that is never switched. `extra_headers` are added as-is (gacha
    sends its UID this way).
    """
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)     # pre-serialized (e.g. /stage/save wants compact, key-sorted JSON)
    else:
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)

    def send(prefix, app_version):
        return _send_raw(cookie, prefix + path, method, data, app_version, extra_headers)

    return client_version.request(path, send, pinned_prefix=api)


def _send_raw(cookie, url, method, data, app_version, extra_headers=None):
    """One logical request with this module's retry policy and no version logic at all - the
    transport under call() and under the version oracle. Uses a reused keep-alive connection;
    a stale/closed connection is transparently reconnected once."""
    lane = current_lane()
    status, parsed = 0, ""
    # http.client returns 4xx/5xx as a normal response (no exception), so no HTTPError branch is
    # needed. Three retry reasons: a dropped keep-alive socket (reconnect immediately), a nginx
    # 429/503 (per-IP overload), and the per-account HTTP 400 + errorCode 429 min-gap rejection.
    # Before every attempt: keep the per-account gap, then take a per-IP token.
    for attempt in range(MAX_ATTEMPTS):
        # wait first, then stamp: a bucket wait can take seconds at 300 workers and the
        # X-LINEGAME-TIMESTAMP / timeID headers must reflect the actual send time
        ratelimit.PACER.wait(cookie)
        if lane is not None:
            lane.acquire()
        else:
            ratelimit.bucket_for(HOST).acquire()   # เส้นทาง CLI: ไม่มี lane ใช้ถังไฟล์แบบเดิม
        now = int(time.time() * 1000)
        version_headers = client_version.headers(app_version)
        headers = {
            "Host": HOST,
            "Accept": "*/*",
            "Content-Type": "application/json; charset=utf-8;",
            "App-Version": version_headers["App-Version"],
            "User-Agent": version_headers["User-Agent"],
            "Accept-Language": "en",
            "X-LINEGAME-MCC": "000",
            "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": str(now),
            "timeID": str(now),
            "Cookie": cookie,
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            # _get_conn() itself can raise (bad proxy tuple, tunnel setup) same as the socket
            # ops below it - that must reach lane.note_fail() too, or a proxy that can never
            # even connect goes on getting work forever. Keep it inside the try, not above it.
            conn = _get_conn()
            conn.request(method, url, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()          # must read the full body to keep the connection reusable
            status = resp.status
            enc = resp.getheader("Content-Encoding")
            retry_after = resp.getheader("Retry-After")
        except (http.client.HTTPException, OSError):
            if lane is not None:
                lane.note_fail()
            _drop_conn()
            if attempt == MAX_ATTEMPTS - 1:
                raise
            if attempt >= 1:
                _retry_sleep(attempt - 1)   # repeated socket failures: back off, don't hammer
            continue               # first drop = stale keep-alive socket: reconnect right away
        ratelimit.PACER.done(cookie)   # the server stamps rejected calls too
        if lane is not None:
            lane.note_ok()     # ตอบกลับมาได้ = proxy ยังดี ล้างสตรีคความพังทิ้ง
        parsed = _decode(raw, enc)
        limited = status in RETRY_STATUSES or ratelimit.is_app_429(status, parsed) is not None
        if limited and attempt < MAX_ATTEMPTS - 1:
            _retry_sleep(attempt, retry_after)
            continue               # rate-limited/overloaded: wait, then retry
        break
    return status, parsed


def _oracle(prefix, app_version):
    """client_version's probe: GET {prefix}/home with a token that is never valid. The server
    checks the version before the token, so the answer says whether it knows `app_version`
    (401 vs 400/119801) and whether `prefix` exists (401 vs 404) without touching an account."""
    return _send_raw(client_version.ORACLE_COOKIE, prefix + client_version.ORACLE_PATH,
                     "GET", None, app_version)


client_version.set_oracle(_oracle)


def add_session_args(parser):
    parser.add_argument("--cookie", help='explicit "LF_AC=..." cookie value')
    parser.add_argument("--xml", help="account file (_LINE_COCOS_PREF_KEY.xml) to read the session from")
    parser.add_argument("--from-device", action="store_true",
                        help="read the live LF_AC off a rooted, logged-in device")
    parser.add_argument("--device", help="adb serial for --from-device")


def resolve_cookie(args) -> str:
    if getattr(args, "cookie", None):
        return args.cookie if args.cookie.startswith("LF_AC=") else "LF_AC=" + args.cookie
    if getattr(args, "xml", None):
        from account_file import read_pref_xml
        return "LF_AC=" + read_pref_xml(args.xml)[1]
    if getattr(args, "from_device", False):
        from device_session import get_lfac_from_device
        return "LF_AC=" + get_lfac_from_device(getattr(args, "device", None))
    # fall back to the newest token in captures/
    from pull_roster import newest_auth_from_captures
    cookie, _uid, when = newest_auth_from_captures()
    if not cookie:
        raise SystemExit("No session. Use --cookie \"LF_AC=...\", or --from-device, or capture a login.")
    print("Using session captured at %s" % when)
    return cookie if cookie.startswith("LF_AC=") else "LF_AC=" + cookie
