r"""Create a brand-new LINE Rangers guest account, fully headless (no app/emulator).

After login it also auto-confirms the tutorial (all 67 steps via /tutorial/confirm/<STEP>) so the
guest lands PAST the tutorial and is immediately usable - it already has 5 starter units and can
enter/play stages. Two steps (SALLY, YELLOW_STONE) stay pending (tutorial gacha/evolve, non-blocking).
Disable with --no-skip-tutorial. See tools/tutorial.py for the step list.

The whole account-creation chain runs through the LINE Game "Trident" SDK's
bootstrap endpoints, which are NOT certificate-pinned. Every /auth/v3.* request is
signed with X-Linegame-Authorization, whose scheme was reverse-engineered from
libtrident.so and is reproducible offline (see sign() below). Because the signing
key is derived only from appId + timestamp - no server secret, no device keystore -
we can mint accounts without the game running at all.

Flow (each new random deviceId = a new account):
  1. POST /auth/v3.5/check/GUEST           {uuid}                  -> "Not exists user"
  2. POST /auth/v3.8/authentication/GUEST  {uuid,country}          -> "terms required"
  3. POST /auth/v3.8/authentication/GUEST  {uuid,termsResult,country}
                                           -> userKey/userToken/refreshUserToken (ACCOUNT MINTED)
  4. POST /auth/v3.8/refresh               {providerId,refreshUserToken,country}
                                           -> a fresh userToken; this is the `cc` cookie
                                              (/auth/v3.0/token is DELETE-only - it revokes)
  5. GET  /auth/v3.5/authorization         signed, X-Linegame-UserToken -> signedIn
  6. GET  /v12.3/signup/platform           Cookie: cc=...; udid=...;, LF_AC=; udid=...;
                                           -> CREATES the rangers player: uid/mid/rsn +
                                              starter ruby/coin/level + Set-Cookie: LF_AC

Step 6 is the fresh-account create call. A brand-new guest has no rangers player yet, so
GET /v12.3/login returns 401 (that endpoint is for RETURNING users - it needs a prior
session as the continuity credential; see tools/relogin.py). /signup/platform is what the
native client actually hits on first login: not certificate-pinned, no X-LINEGAME-APPSECRET,
just the cc+udid cookie jar with an empty LF_AC to signal "no session yet". `udid` is the
game's own device uuid (the value that becomes _DEVICE_UUID_KEY on disk). Verified live
2026-09-14: fresh guest -> HTTP 200, isNew=true, level 1, ruby 20, coin 500, LF_AC returned.

Two files come out per account:
  roster/accounts/account-<gameId>-<dev>.json   deviceId, udid, refreshUserToken, uid,
                                                mid (= GAME_ID), LF_AC - feeds the API tools
  <xml-dir>/<rsn>.xml                           the shared_prefs _LINE_COCOS_PREF_KEY.xml the
                                                game restores a GUEST session from, i.e. what
                                                the UI bot's input/ queue consumes

Credentials are written the moment the account is minted, before the game login, so a
server-side outage can never strand a real account: re-run with --resume to finish it.
Standard library only (account_file.py adds `cryptography` for the XML).

    python tools/new_account.py --count 5 --xml-dir ../bot/input
    python tools/new_account.py --resume --xml-dir ../bot/input
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import random
import secrets
import sys
import time
import urllib.error
import urllib.request
import hmac
import hashlib
import base64
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratelimit  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "roster", "accounts")

APP_ID = "LGRGS"
SDK_VERSION = "3.12.1.422"
GAME_HOST = "game-api.line.me"
RANGERS_HOST = "rangers-api.line-apps.com"
COUNTRY = "TH"
NATION = "TH"
LANG = "en"

# Device fingerprint copied from a real client. The DeviceId is randomised per
# account; the rest only has to look like a plausible install.
UA_SDK = "android;12;V417IR;GOOGLEPLAY;en"
UA_GAME = "LGRGS/12.3.0 (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)"
APP_VERSION = "LGRGS/12.3.0;android/12"

# Terms the server currently requires. If these fall out of date the auth step
# returns the up-to-date list in its error body - copy it back in here.
AGREEMENTS = [
    {"termsId": "LGRGS_AgreementRegardingUseofInformation", "country": "TH", "language": "en", "revisionDate": "20241105", "agree": True},
    {"termsId": "LGRGS_privacy", "country": "TH", "language": "en", "revisionDate": "20231130", "agree": True},
    {"termsId": "LGRGS_term", "country": "TH", "language": "en", "revisionDate": "20231001", "agree": True},
    {"termsId": "LGRGS_TH_PDPA", "country": "TH", "language": "en", "revisionDate": "20250818", "agree": True},
]


# --- tiny msgpack encoder (only maps of string->string, which is all we send) ---

def _mp_str(s: str) -> bytes:
    raw = s.encode("utf-8")
    n = len(raw)
    if n < 32:
        return bytes([0xA0 | n]) + raw
    if n < 256:
        return bytes([0xD9, n]) + raw
    if n < 65536:
        return bytes([0xDA, n >> 8, n & 0xFF]) + raw
    return bytes([0xDB]) + n.to_bytes(4, "big") + raw


def mp_map(pairs) -> bytes:
    out = bytes([0x80 | len(pairs)])
    for key, value in pairs:
        out += _mp_str(key) + _mp_str(value)
    return out


# --- Trident request signature (reverse-engineered from libtrident.so) ---

def sign(ts_ms: str, body: bytes) -> str:
    """X-Linegame-Authorization si value (URL-encoded base64 HMAC-SHA256).

    key = urlencode("trident&" + appId + "&" + ts)  ==  "trident%26LGRGS%26<ts>"
    msg = raw request body bytes.
    """
    key = ("trident&" + APP_ID + "&" + ts_ms)
    key = urllib.parse.quote(key, safe="").encode()   # -> trident%26LGRGS%26<ts>
    digest = hmac.new(key, body, hashlib.sha256).digest()
    return urllib.parse.quote(base64.b64encode(digest).decode(), safe="")


def _now():
    secs = int(time.time())
    ts_ms = str(secs) + "000"
    iso = time.strftime("%Y-%m-%dT%H:%M:%S.000+0700", time.localtime(secs))
    return ts_ms, iso


def game_call(path: str, device_id: str, body: bytes | None, *,
              content_type="application/x-msgpack", user_token=None, signed=True):
    ts_ms, iso = _now()
    headers = {
        "Accept-Encoding": "identity",
        "X-Linegame-DeviceId": device_id,
        "X-Linegame-AppId": APP_ID,
        "Content-Type": content_type,
        "User-Agent": UA_SDK,
        "X-Linegame-Timestamp": iso,
        "X-Linegame-SdkVersion": SDK_VERSION,
        "X-Linegame-MCC": "",
        "X-Linegame-MNC": "",
        "Host": GAME_HOST,
        "Connection": "Keep-Alive",
    }
    if signed:
        headers["X-Linegame-Authorization"] = 'ts="%s", si="%s"' % (ts_ms, sign(ts_ms, body or b""))
    if user_token is not None:
        headers["X-Linegame-UserToken"] = user_token
    req = urllib.request.Request("https://" + GAME_HOST + path, data=body, headers=headers, method="POST")
    return _do(req)


# 429/503 backoff-retry for the account-creation path (mint/refresh/authorize/signup/login all
# funnel through _do). Same policy as tools/rangers_api.py, kept self-contained so this module
# stays standard-library only. Under thousands of concurrent workers these bootstrap endpoints
# rate-limit too; without a retry ~half of signups failed outright. Bounded + exponential +
# jittered so the retries don't become their own load spike; honor Retry-After when sent.
# The per-account min-gap limit answers HTTP 400 + errorCode 429; ratelimit.is_app_429 catches it.
_RETRY_STATUSES = (429, 503)
_MAX_ATTEMPTS = max(1, int(os.environ.get("LGRGS_MAX_RETRY", "8")))
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 8.0

# HTTP status of the most recent signup_platform call - lets the bot's error message say WHY a
# headless signup failed (429 rate-limit vs a real rejection) instead of a bare "no LF_AC".
LAST_SIGNUP_HTTP = None


def _retry_sleep(attempt, retry_after=None):
    delay = None
    if retry_after:
        try:
            delay = min(float(retry_after), _BACKOFF_CAP * 2)
        except (TypeError, ValueError):
            delay = None
    if delay is None:
        delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt))
    time.sleep(delay + random.uniform(0, _BACKOFF_BASE))


def _build_opener(url):
    """urllib opener that tunnels through the http proxy `url`; None = plain urlopen."""
    if not url:
        return None
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": url, "https": url}))


_OPENER = _build_opener(ratelimit.proxy_url())


def _open(req):
    if _OPENER is not None:
        return _OPENER.open(req, timeout=25)
    return urllib.request.urlopen(req, timeout=25)


def _parse(raw, resp_headers):
    if resp_headers is not None and resp_headers.get("Content-Encoding") == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return raw.decode("utf-8", "replace")


def _do(req):
    # Per-account pacing keys on the Cookie (login carries cc/udid/guestCookie); cookie-less
    # bootstrap calls (auth/signup) key on the URL. The per-IP bucket is per destination host
    # because game-api.line.me and rangers-api.line-apps.com have separate limits.
    key = req.get_header("Cookie") or req.full_url
    bucket = ratelimit.bucket_for(req.host)
    raw, status, resp_headers, parsed = b"", 0, None, {}
    for attempt in range(_MAX_ATTEMPTS):
        ratelimit.PACER.wait(key)
        bucket.acquire()
        try:
            resp = _open(req)
            raw, status, resp_headers = resp.read(), resp.status, resp.headers
        except urllib.error.HTTPError as err:
            raw, status, resp_headers = err.read(), err.code, err.headers
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            _retry_sleep(attempt)               # network blip: back off and retry
            continue
        ratelimit.PACER.done(key)               # the server stamps rejected calls too
        parsed = _parse(raw, resp_headers)
        limited = status in _RETRY_STATUSES or ratelimit.is_app_429(status, parsed) is not None
        if limited and attempt < _MAX_ATTEMPTS - 1:
            _retry_sleep(attempt, resp_headers.get("Retry-After"))  # rate-limited: wait, retry
            continue
        break
    set_cookies = resp_headers.get_all("Set-Cookie") if hasattr(resp_headers, "get_all") else None
    return status, parsed, (set_cookies or [])


def register_guest(device_id: str) -> dict:
    # 1. check (informational - a fresh deviceId is always "not exists")
    st, res, _ = game_call("/auth/v3.5/check/GUEST", device_id, mp_map([("uuid", device_id)]))
    print("  check     : HTTP %s %s" % (st, _err(res)))

    # 2. authenticate without terms -> server demands ToS agreement
    st, res, _ = game_call("/auth/v3.8/authentication/GUEST", device_id,
                           mp_map([("uuid", device_id), ("country", COUNTRY)]))
    print("  auth(bare): HTTP %s %s" % (st, _err(res)))

    # 3. authenticate WITH terms -> mints the account
    terms = urllib.parse.quote(json.dumps({"agreements": AGREEMENTS}, separators=(",", ":")), safe="")
    st, res, _ = game_call("/auth/v3.8/authentication/GUEST", device_id,
                           mp_map([("uuid", device_id), ("termsResult", terms), ("country", COUNTRY)]))
    if not isinstance(res, dict) or "userToken" not in res:
        raise SystemExit("  auth(terms) FAILED HTTP %s: %s" % (st, json.dumps(res, ensure_ascii=False)[:400]))
    print("  auth(terms): HTTP %s  userKey=%s" % (st, res.get("userKey")))
    return res


def refresh_token(device_id: str, refresh_user_token: str) -> str:
    """Trade the long-lived refresh token for a fresh userToken - this is the `cc` cookie."""
    body = mp_map([("providerId", "GUEST"),
                   ("refreshUserToken", refresh_user_token),
                   ("country", COUNTRY)])
    st, res, _ck = game_call("/auth/v3.8/refresh", device_id, body)
    token = res.get("userToken") if isinstance(res, dict) else None
    print("  refresh   : HTTP %s  userToken=%s" % (st, "yes" if token else "MISSING"))
    if not token:
        raise SystemExit("  refresh failed: %s" % json.dumps(res, ensure_ascii=False)[:300])
    return token


def authorize(device_id: str, user_token: str) -> bool:
    """Confirm the SDK considers this token signed in (cheap sanity check before login)."""
    ts_ms, iso = _now()
    headers = {
        "Accept-Encoding": "identity",
        "X-Linegame-DeviceId": device_id,
        "X-Linegame-AppId": APP_ID,
        "User-Agent": UA_SDK,
        "X-Linegame-Timestamp": iso,
        "X-Linegame-SdkVersion": SDK_VERSION,
        "X-Linegame-MCC": "",
        "X-Linegame-MNC": "",
        "Host": GAME_HOST,
        "Connection": "Keep-Alive",
        "X-Linegame-UserToken": user_token,
        "X-Linegame-Authorization": 'ts="%s", si="%s"' % (ts_ms, sign(ts_ms, b"")),
    }
    req = urllib.request.Request("https://" + GAME_HOST + "/auth/v3.5/authorization",
                                 headers=headers, method="GET")
    st, res, _ck = _do(req)
    signed = bool(isinstance(res, dict) and res.get("authChecker", {}).get("signedIn"))
    print("  authorize : HTTP %s  signedIn=%s" % (st, signed))
    return signed


def game_login(cc: str, udid: str, guest_cookie: str | None = None) -> dict:
    """GET /v12.3/login exactly as the client sends it (captured from a real session).

    The client's cookie jar carries three things: `cc` (the fresh SDK userToken),
    `udid` (the game's own device uuid, also the AES key for the stored token) and,
    once a session exists, `guestCookie` - the first 16 chars of the previous LF_AC.
    """
    cookie = "cc=%s; udid=%s;" % (cc, udid)
    if guest_cookie:
        cookie += " guestCookie=%s" % guest_cookie
    ts_ms = str(int(time.time() * 1000))
    headers = {
        "App-Version": APP_VERSION,
        "userType": "",
        "Nation-Code": NATION,
        "Accept-Language": LANG,
        "User-Agent": UA_GAME,
        "marketId": "",
        "useLGC": "true",
        "X-LINEGAME-MCC": "000",
        "X-LINEGAME-MNC": "00",
        "X-LINEGAME-TIMESTAMP": ts_ms,
        "Host": RANGERS_HOST,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Cookie": cookie,
    }
    # login is GET-only; POST returns 405.
    req = urllib.request.Request("https://" + RANGERS_HOST + "/v12.3/login",
                                 headers=headers, method="GET")
    st, res, cookies = _do(req)
    lf_ac = _cookie_value(cookies, "LF_AC")
    if not isinstance(res, dict) or "result" not in res:
        hint = ""
        if st == 401:
            hint = (" (a blanket 401 - including on tokens that worked minutes earlier -"
                    " means the game servers are in maintenance or mid-version-bump;"
                    " the account is already minted, finish it later with --resume)")
        print("  login     : FAILED HTTP %s %s%s"
              % (st, json.dumps(res, ensure_ascii=False)[:200], hint))
        return None
    result = res["result"]
    print("  login     : HTTP %s  uid=%s mid=%s rsn=%s userType=%s" % (
        st, result.get("id"), result.get("mid"), result.get("rsn"), result.get("userType")))
    return {"uid": result.get("id"), "mid": result.get("mid"), "rsn": result.get("rsn"),
            "lf_ac": lf_ac, "tutorialStep": result.get("tutorialStep"), "cc": cc}


def signup_platform(cc: str, udid: str, user_type: str = "LINE") -> dict | None:
    """GET /v12.3/signup/platform - creates the rangers PLAYER for a brand-new guest.

    This is the endpoint the native client hits on a genuine first login (a fresh guest
    has no player yet, so /v12.3/login returns 401). It is NOT certificate-pinned and
    carries no X-LINEGAME-APPSECRET: the same cc+udid cookie jar as a relogin, plus an
    empty LF_AC to signal "no session yet". Response body already includes the starter
    ruby/coin/level and a Set-Cookie: LF_AC for every subsequent authenticated call.
    Verified live 2026-09-14: fresh guest -> HTTP 200, isNew=true, level 1, ruby 20.
    """
    cookie = "cc=%s; udid=%s;, LF_AC=; udid=%s;" % (cc, udid, udid)
    ts_ms = str(int(time.time() * 1000))
    headers = {
        "App-Version": APP_VERSION,
        "userType": user_type,
        "Nation-Code": NATION,
        "Accept-Language": LANG,
        "User-Agent": UA_GAME,
        "marketId": "",
        "useLGC": "true",
        "X-LINEGAME-MCC": "000",
        "X-LINEGAME-MNC": "00",
        "X-LINEGAME-TIMESTAMP": ts_ms,
        "Host": RANGERS_HOST,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Cookie": cookie,
    }
    req = urllib.request.Request("https://" + RANGERS_HOST + "/v12.3/signup/platform",
                                 headers=headers, method="GET")
    global LAST_SIGNUP_HTTP
    st, res, cookies = _do(req)
    LAST_SIGNUP_HTTP = st
    lf_ac = _cookie_value(cookies, "LF_AC")
    if not isinstance(res, dict) or "result" not in res:
        print("  signup    : FAILED HTTP %s %s" % (st, json.dumps(res, ensure_ascii=False)[:200]))
        return None
    result = res["result"]
    ruby = (result.get("ruby") or {}).get("total")
    coin = (result.get("coin") or {}).get("total")
    print("  signup    : HTTP %s  uid=%s mid=%s rsn=%s isNew=%s level=%s ruby=%s coin=%s" % (
        st, result.get("id"), result.get("mid"), result.get("rsn"),
        result.get("isNew"), result.get("level"), ruby, coin))
    return {"uid": result.get("id"), "mid": result.get("mid"), "rsn": result.get("rsn"),
            "lf_ac": lf_ac, "tutorialStep": result.get("tutorialStep"), "cc": cc,
            "level": result.get("level"), "ruby": ruby, "coin": coin,
            "isNew": result.get("isNew")}


def exchange_and_login(device_id: str, guest: dict, udid: str) -> dict | None:
    """Fresh guest: refresh -> authorize -> SIGN UP (create the player, get LF_AC).

    A brand-new guest has no rangers player, so the create call is /signup/platform, not
    /login (which is for returning users and 401s here). If signup ever reports the player
    already exists, fall back to /login so a re-run of an already-created account still works.
    """
    cc = refresh_token(device_id, guest["refreshUserToken"])
    authorize(device_id, cc)
    session = signup_platform(cc, udid)
    if session:
        return session
    return game_login(cc, udid)


def _err(res):
    if isinstance(res, dict) and res.get("error"):
        return res["error"].get("code", "") + " " + res["error"].get("message", "")
    if isinstance(res, dict):
        return "ok"
    return str(res)[:60]


def _cookie_value(set_cookies, name):
    for c in set_cookies:
        for part in c.split(";"):
            part = part.strip()
            if part.startswith(name + "="):
                return part[len(name) + 1:]
    return None


def _save_json(account):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "account-%s-%s.json"
                        % (account["gameId"] or "unknown", account["deviceId"][:8]))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(account, handle, ensure_ascii=False, indent=1)
    return path


def write_account_xml(account, xml_dir):
    """Emit the shared_prefs XML the game restores a GUEST session from."""
    from account_file import build_pref_xml
    os.makedirs(xml_dir, exist_ok=True)
    name = account.get("rsn") or account.get("gameId")
    path = os.path.join(xml_dir, "%s.xml" % name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(build_pref_xml(account["lf_ac"], account["udid"], NATION, LANG))
    return path


def skip_tutorial(cookie):
    """Confirm every server-side tutorial step so a fresh guest lands past the tutorial.

    Uses GET /v12.3/tutorial/confirm/<STEP> (dynamic + idempotent) over the FULL 67-step set from
    tools/tutorial.py. Runs on the CURRENT session cookie only - never re-logs-in, because a re-login
    rotates the LF_AC and would strand the token we just saved. Returns (done, total, pending). Two
    steps (SALLY, YELLOW_STONE) stay pending: they gate on the tutorial gacha/evolve mechanics, not a
    flag, and are non-blocking - the guest already has 5 starter units and can enter stages at 65/67.
    """
    from tutorial import STEPS, confirm  # same dir; pulls in rangers_api.call
    done, pending = 0, []
    for step in STEPS:
        ok, _status, _data = confirm(cookie, step)
        if ok:
            done += 1
        else:
            pending.append(step)
    return done, len(STEPS), pending


def _finish(account, session, write_xml_dir, skip_tut=True):
    """Fold a successful login into the account record and emit its XML."""
    account.update({
        "mid": session["mid"],
        "uid": session["uid"],
        "rsn": session["rsn"],
        "lf_ac": session["lf_ac"],
        "tutorialDone": _tutorial_done(session.get("tutorialStep")),
        "status": "ready",
    })
    if skip_tut and account.get("lf_ac"):
        try:
            done, total, pending = skip_tutorial("LF_AC=" + account["lf_ac"])
            account["tutorialDone"] = "%d/%d" % (done, total)
            if pending:
                account["tutorialPending"] = pending
            print("  tutorial  : confirmed %d/%d%s"
                  % (done, total, (" (pending: %s)" % ",".join(pending)) if pending else ""))
        except Exception as err:  # a tutorial hiccup must never lose a freshly-minted account
            print("  tutorial  : skip FAILED (%s) - account still saved" % err)
    _save_json(account)
    if write_xml_dir and account.get("lf_ac"):
        print("  account file -> %s" % write_account_xml(account, write_xml_dir))
    return account


def make_account(write_xml_dir=None, skip_tut=True):
    device_id = secrets.token_hex(16)   # trident SDK DeviceId
    udid = secrets.token_hex(16)        # the game's own device uuid (_DEVICE_UUID_KEY)
    print("deviceId=%s  udid=%s" % (device_id, udid))
    guest = register_guest(device_id)

    # Persist the credentials the moment the account exists. The game login can fail
    # for reasons that have nothing to do with this account (maintenance, a version
    # bump); losing the refresh token to that would strand a real account forever.
    account = {
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deviceId": device_id,
        "udid": udid,                          # needed to rebuild the on-disk account file
        "gameId": guest.get("userKey"),        # the T0FF... code shown in-game
        "userToken": guest.get("userToken"),
        "refreshUserToken": guest.get("refreshUserToken"),
        "refreshUserTokenExpireTime": guest.get("refreshUserTokenExpireTime"),
        "status": "pending-login",
    }
    print("  saved     : %s" % _save_json(account))

    session = exchange_and_login(device_id, guest, udid)
    if not session:
        print("  PENDING   gameId=%s - credentials kept; run --resume to finish it"
              % account["gameId"])
        return account
    return _finish(account, session, write_xml_dir, skip_tut)


def resume_pending(write_xml_dir=None, skip_tut=True):
    """Finish accounts that were minted but never got a session (e.g. server was down)."""
    files = sorted(glob.glob(os.path.join(OUT_DIR, "account-*.json")))
    pending = []
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            acct = json.load(handle)
        if not acct.get("lf_ac") and acct.get("refreshUserToken") and acct.get("udid"):
            pending.append(acct)
    if not pending:
        print("nothing pending (every saved account already has a session)")
        return []
    print("resuming %d pending account(s)" % len(pending))
    done = []
    for acct in pending:
        print("=== %s ===" % acct["gameId"])
        try:
            cc = refresh_token(acct["deviceId"], acct["refreshUserToken"])
        except SystemExit as err:
            print("  %s" % err)
            continue
        authorize(acct["deviceId"], cc)
        session = signup_platform(cc, acct["udid"]) or game_login(cc, acct["udid"])
        if session:
            done.append(_finish(acct, session, write_xml_dir, skip_tut))
    print("completed %d/%d" % (len(done), len(pending)))
    return done


def _tutorial_done(steps):
    if not isinstance(steps, dict):
        return None
    total = len(steps)
    done = sum(1 for v in steps.values() if v)
    return "%d/%d" % (done, total)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=1, help="how many accounts to mint")
    parser.add_argument("--xml-dir", help="write the shared_prefs .xml here (the UI bot's input/ queue)")
    parser.add_argument("--resume", action="store_true",
                        help="finish already-minted accounts that never got a session")
    parser.add_argument("--no-skip-tutorial", dest="skip_tut", action="store_false",
                        help="do NOT auto-confirm the tutorial (default: confirm all 67 steps -> past tutorial)")
    args = parser.parse_args()
    if args.resume:
        resume_pending(args.xml_dir, args.skip_tut)
        return
    for i in range(args.count):
        print("\n=== account %d/%d ===" % (i + 1, args.count))
        make_account(args.xml_dir, args.skip_tut)


if __name__ == "__main__":
    main()
