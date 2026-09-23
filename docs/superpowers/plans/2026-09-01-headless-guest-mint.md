# Headless Guest Mint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mint a usable LINE Rangers guest account from Python alone (no emulator/app in the loop) so gacha rerolling is bottlenecked only by HTTP, not by driving the app UI.

**Architecture:** The Trident SDK mint chain already works offline in `tools/new_account.py`. The one missing piece is the rangers `/login` for a *fresh* guest, which the native client signs with an `X-LINEGAME-APPSECRET` header. We capture that header once with a Frida `SSL_write` hook on a rooted arm64 phone, decide whether it is a per-app-version constant or a derived value, reproduce it in Python, and wire it into `game_login()`. A thin `tools/reroll.py` then chains mint → claim rewards → roll one gacha → export XML. Phase 2 (stretch) reuses the same Frida technique on `/stage/save` to try granting levels 1→3 headlessly.

**Tech Stack:** Python 3 standard library only (matching every existing `tools/*.py`); `cryptography` only where `account_file.py` already needs it; `frida` / `frida-tools` (host has frida-python 17.17.0) driving frida-server on a rooted arm64 Android phone.

## Global Constraints

- **Standard library only** in every `tools/*.py` module (except `account_file.py`'s existing `cryptography` use). Copied verbatim from every tool's module docstring.
- **API version prefix is `/v12.3`** and client version `12.3.0` — the server routes each prefix separately; an older prefix silently drops newer handlers. `tools/rangers_api.py` is the single source of truth (`API = "/v12.3"`, `CLIENT_VERSION = "12.3.0"`).
- **Secrets never leave the machine.** `appSecret`, `LF_AC`, `userToken`, `refreshUserToken` authenticate the user's real accounts. Keep them in gitignored paths; send them only to the game's own servers (`rangers-api.line-apps.com`, `game-api.line.me`). Never put a token in a URL, header, or payload bound for any other host.
- **Mutations are measured, never trusted by status code.** A 200 does not mean the parameters were honored — read the exact counters a call should move, act, read again, assert the delta (the skill's core rule).
- **Testing convention:** no pytest in this repo. Pure-logic tasks add a `selftest()` run via `python tools/<mod>.py --selftest` using plain `assert` (mirror `tools/account_file.py`). API/RE tasks verify live by measuring state with explicit commands.
- **Throttle mints** — rapid guest creation (~10 in a burst) previously tripped a server abuse flag. Default a sleep between mints.
- **This repo is not yet a git repo.** Where a step says `git commit`, first ensure a repo exists (Task 0 handles `git init`); commits are local only unless the user asks to push.

---

## File Structure

- `tools/frida/dump_login.js` (new) — Frida hook: dump plaintext of outgoing TLS writes that look like the rangers `/login` request.
- `tools/frida/capture.py` (new) — frida-python runner that spawns the game, loads a hook script, and tees matching output to a gitignored scratch file.
- `tools/frida/README.md` (new) — one-time on-phone runbook (frida-server, WARP+guest+terms recipe, what to collect).
- `tools/appsecret.py` (new) — reconstruct `X-LINEGAME-APPSECRET` (constant or derived) with a `--selftest`.
- `tools/new_account.py` (modify) — bump SDK/app version; add native-login headers to `game_login()`; thread `appSecret` through.
- `tools/reroll.py` (new) — batch driver: mint → claim → gacha → export XML → append CSV → throttle.
- `.gitignore` (modify) — stop tracking token-bearing outputs.
- `tools/frida/dump_stagesave.js` (new, Phase 2) — Frida hook for `/stage/save`.
- `tools/stage_replay.py` (new, Phase 2) — replay a captured stage-save on a throwaway guest; measure exp/level delta.

---

## Task 0: Repo + secret hygiene

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- Produces: a git repo and a `.gitignore` that excludes every token-bearing output path. Later tasks' `git commit` steps rely on the repo existing.

- [ ] **Step 1: Initialise a repo if none exists**

Run:
```bash
cd "d:/Programing/ranger/Test-Mitmproxy-Api"
test -d .git || git init
```
Expected: `.git` exists (either already, or "Initialized empty Git repository").

- [ ] **Step 2: Extend `.gitignore` to cover token-bearing outputs**

Append to `.gitignore` (the file already ignores `captures/`, `*.jsonl`, `*.mitm`, `__pycache__/`, `*.pyc`):
```gitignore

# Account records and sessions hold LF_AC / userToken - never commit them.
roster/accounts/
roster/scratch/
roster/*.json
id/*.xml
bot/output/*.xml
bot/backup/*.xml
# Frida captures contain the live appSecret and cookies.
tools/frida/*.capture.txt
```

- [ ] **Step 3: Verify nothing secret is staged**

Run:
```bash
git add -A -n | grep -Ei "roster/accounts|/scratch/|LF_AC|\.capture\.txt|id/.*\.xml" || echo "clean: no secret paths would be added"
```
Expected: `clean: no secret paths would be added`.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore token-bearing account/session/capture outputs"
```

---

## Task 1: Frida login-capture tooling

**Files:**
- Create: `tools/frida/dump_login.js`
- Create: `tools/frida/capture.py`
- Create: `tools/frida/README.md`

**Interfaces:**
- Produces: a scratch file `roster/scratch/login-<ts>.capture.txt` containing the full plaintext of each outgoing rangers `/login` request (headers incl. `X-LINEGAME-APPSECRET`, cookie `cc`/`udid`). Task 2 consumes that file.

- [ ] **Step 1: Write the hook script**

Create `tools/frida/dump_login.js`:
```javascript
'use strict';
// Dump the plaintext of outgoing TLS writes that look like the rangers /login request.
// BoringSSL's SSL_write sees the bytes before encryption, so this catches the pinned,
// direct-dialled native call that mitmproxy can never see. We filter to /login and the
// X-LINEGAME headers so ordinary traffic stays out of the log.
function toText(buf, len) {
  const bytes = new Uint8Array(buf.readByteArray(len));
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    const c = bytes[i];
    out += (c >= 0x20 && c < 0x7f) || c === 0x0a || c === 0x0d ? String.fromCharCode(c) : '.';
  }
  return out;
}
function looksLikeLogin(text) {
  return text.indexOf('/v12.') !== -1 && text.indexOf('login') !== -1 &&
         text.indexOf('rangers-api') !== -1;
}
function hook(name) {
  const addr = Module.findExportByName(null, name);   // search every loaded module
  if (!addr) { console.log('[dump_login] ' + name + ' not found'); return false; }
  Interceptor.attach(addr, {
    onEnter(args) {
      const len = args[2].toInt32();
      if (len <= 0 || len > 65536) return;
      const text = toText(args[1], len);
      if (looksLikeLogin(text) || text.indexOf('X-LINEGAME-APPSECRET') !== -1) {
        console.log('=== ' + name + ' ' + len + ' bytes ===');
        console.log(text);
        console.log('=== end ===');
      }
    }
  });
  console.log('[dump_login] hooked ' + name + ' @ ' + addr);
  return true;
}
setImmediate(function () {
  const ok = hook('SSL_write');
  if (!ok) console.log('[dump_login] SSL_write missing - the app may statically link a renamed BoringSSL; list exports with Process.enumerateModules() and adjust.');
});
```

- [ ] **Step 2: Write the frida-python runner**

Create `tools/frida/capture.py`:
```python
r"""Spawn LINE Rangers under a Frida hook and tee matching output to a scratch file.

Run this on the host with a rooted arm64 phone attached (frida-server running on it).
Then, in the app: WARP on -> GUEST Login -> agree the terms -> reach home. That drives
the native /login the hook is watching for. Do it TWICE (two fresh guests) so Task 2 can
diff the two appSecret values.

    python tools/frida/capture.py --script tools/frida/dump_login.js
    python tools/frida/capture.py --script tools/frida/dump_login.js --device <frida-id>

Needs: frida-python (host) + a matching frida-server on the phone. Standard library + frida.
"""
from __future__ import annotations
import argparse, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import frida

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = os.path.join(ROOT, "roster", "scratch")
PKG = "com.linecorp.LGRGS"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", required=True, help="path to the .js hook to load")
    parser.add_argument("--device", help="frida device id (default: first USB device)")
    parser.add_argument("--out", help="capture file (default roster/scratch/login-<ts>.capture.txt)")
    args = parser.parse_args()

    os.makedirs(SCRATCH, exist_ok=True)
    out = args.out or os.path.join(SCRATCH, "login-%s.capture.txt" % time.strftime("%Y%m%d-%H%M%S"))
    sink = open(out, "w", encoding="utf-8")
    print("device : %s" % (args.device or "first USB"))
    print("script : %s" % args.script)
    print("writing: %s" % out)

    device = frida.get_device(args.device) if args.device else frida.get_usb_device(timeout=10)
    pid = device.spawn([PKG])
    session = device.attach(pid)
    with open(args.script, "r", encoding="utf-8") as handle:
        script = session.create_script(handle.read())

    def on_message(message, data):
        line = message.get("payload") if message.get("type") == "send" else str(message)
        print(line, flush=True)
        sink.write(str(line) + "\n"); sink.flush()

    script.on("message", on_message)
    # console.log in the hook arrives as log messages too:
    script.set_log_handler(lambda level, text: (print(text, flush=True), sink.write(text + "\n"), sink.flush()))
    script.load()
    device.resume(pid)
    print("\napp resumed. Create the guest in-app now (WARP -> GUEST Login -> terms -> home).")
    print("Press Ctrl+C when the /login block has printed.\n")
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        print("saved %s" % out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write the runbook**

Create `tools/frida/README.md`:
```markdown
# Frida capture runbook (rooted arm64 phone)

One-time capture of the native rangers `/login` request so the appSecret can be reproduced.

## Prep
1. Push a frida-server build matching the phone's arch (`arm64`) and the host's frida
   version (`frida --version`, currently 17.x) to `/data/local/tmp/frida-server`.
2. `adb shell "su -c 'chmod 755 /data/local/tmp/frida-server; /data/local/tmp/frida-server &'"`
3. Confirm from host: `frida-ps -U | grep LGRGS` (empty is fine; it just proves the link works).

## Capture (do it TWICE for two fresh guests)
1. `python tools/frida/capture.py --script tools/frida/dump_login.js`
2. In the app: WARP on -> GUEST Login -> agree the 3 required + 1 optional terms -> reach home.
3. When the `=== SSL_write ... ===` block with `X-LINEGAME-APPSECRET` prints, Ctrl+C.
4. Repeat from a cleared state for a second brand-new guest.

## Collect
Two files land in `roster/scratch/login-*.capture.txt`. Each must contain, for the
`/login` request: `X-LINEGAME-APPID`, `X-LINEGAME-APPSECRET`, `X-LINEGAME-USERKEY`,
`X-LINEGAME-MCC/MNC/TIMESTAMP`, and the `Cookie:` line (`cc=...; udid=...;`). Task 2 diffs them.

If `SSL_write` was not found, the app statically links a renamed BoringSSL; add
`Process.enumerateModules()` output to the issue and hook the `curl_easy_setopt`
CURLOPT_HTTPHEADER path instead.
```

- [ ] **Step 4: Byte-compile the runner (syntax gate; no phone needed)**

Run:
```bash
python -m py_compile tools/frida/capture.py && echo "compile ok"
```
Expected: `compile ok`.

- [ ] **Step 5: Commit**

```bash
git add tools/frida/dump_login.js tools/frida/capture.py tools/frida/README.md
git commit -m "feat: frida login-capture tooling (dump native /login via SSL_write)"
```

---

## Task 2: Capture appSecret and build the reconstructor

**Files:**
- Create: `tools/appsecret.py`
- Uses: two `roster/scratch/login-*.capture.txt` files from Task 1 (produced on the phone)

**Interfaces:**
- Produces: `appsecret.header(app_id, user_key, udid, ts_ms, device_id) -> str` returning the exact `X-LINEGAME-APPSECRET` value the native client sends. Task 3 calls it. Also `appsecret.CONSTANT` (str or None) and a `--selftest`.

- [ ] **Step 1: Extract and compare the two captured appSecret values**

Run (after both captures exist):
```bash
grep -h -i "X-LINEGAME-APPSECRET" roster/scratch/login-*.capture.txt
grep -h -i -E "X-LINEGAME-(APPID|USERKEY|TIMESTAMP)|^Cookie:" roster/scratch/login-*.capture.txt
```
Record: are the two `APPSECRET` values **identical** (→ constant branch) or **different** (→ derived branch)? Note whether each is a fixed length / base64 / hex — that hints at the primitive.

- [ ] **Step 2a: CONSTANT branch — write `appsecret.py` returning the fixed value**

If the two values were identical, create `tools/appsecret.py`:
```python
r"""Reproduce the native client's X-LINEGAME-APPSECRET header.

Captured once with tools/frida/dump_login.js (see tools/frida/README.md). This build's
appSecret was identical across two fresh guests and over time, so it is a per-app-version
constant. Re-capture and update CONSTANT when the client version changes.

    python tools/appsecret.py --selftest

The value authenticates the app to rangers; keep it here, do not paste it into logs/URLs.
"""
from __future__ import annotations
import argparse

# Verbatim from roster/scratch/login-*.capture.txt (client 12.3.0). Two captures matched.
CONSTANT = "<PASTE THE CAPTURED APPSECRET VERBATIM>"


def header(app_id=None, user_key=None, udid=None, ts_ms=None, device_id=None):
    """Return the X-LINEGAME-APPSECRET value. Args are accepted for a uniform call
    signature with the derived branch, and ignored while it is a constant."""
    return CONSTANT


def selftest():
    assert CONSTANT and CONSTANT != "<PASTE THE CAPTURED APPSECRET VERBATIM>", "fill in CONSTANT"
    assert header() == CONSTANT
    assert header("LGRGS", "T0FF0", "abc", "1", "dev") == CONSTANT   # extra args ignored
    print("appsecret selftest ok (constant)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
```

- [ ] **Step 2b: DERIVED branch — write `appsecret.py` reproducing the derivation**

If the two values differed, first identify the inputs by lining up each capture's
`APPID / USERKEY / TIMESTAMP / udid / DeviceId` against its `APPSECRET`. The Trident
signature in `new_account.py::sign()` is HMAC-SHA256 with key `trident%26LGRGS%26<ts>`;
the appSecret very likely reuses that primitive. Create `tools/appsecret.py`:
```python
r"""Reproduce the native client's X-LINEGAME-APPSECRET header (derived per request).

appSecret differed across captures, so it is computed. The formula below was recovered by
matching captured inputs -> captured output (tools/frida/README.md). If a capture ever
fails to reproduce, re-derive from a fresh capture; a static trace of libtrident.so
(setAppSecret caller) is the tie-breaker.

    python tools/appsecret.py --selftest

Secret-bearing: keep inputs/outputs out of logs and URLs.
"""
from __future__ import annotations
import argparse, base64, hashlib, hmac, urllib.parse

# The exact key/message layout is filled from the capture analysis. Start from the Trident
# shape and adjust the field order until a known (inputs -> output) sample reproduces.
def header(app_id, user_key, udid, ts_ms, device_id):
    key = urllib.parse.quote("trident&" + app_id + "&" + ts_ms, safe="").encode()
    msg = (user_key + udid).encode()          # ADJUST to the captured layout
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()  # ADJUST encoding to match capture

# One captured (inputs -> output) row, verbatim, as the regression oracle:
SAMPLE = {
    "app_id": "LGRGS", "user_key": "<from capture>", "udid": "<from capture>",
    "ts_ms": "<from capture>", "device_id": "<from capture>",
    "expected": "<the APPSECRET from that same capture>",
}


def selftest():
    got = header(SAMPLE["app_id"], SAMPLE["user_key"], SAMPLE["udid"],
                 SAMPLE["ts_ms"], SAMPLE["device_id"])
    assert got == SAMPLE["expected"], "derivation mismatch:\n got=%s\n exp=%s" % (got, SAMPLE["expected"])
    print("appsecret selftest ok (derived)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
```

- [ ] **Step 3: Run the selftest**

Run:
```bash
python tools/appsecret.py --selftest
```
Expected: `appsecret selftest ok (constant)` or `... (derived)`. For the derived branch, iterate the `msg`/encoding until it prints ok against the real `SAMPLE`.

- [ ] **Step 4: Commit**

```bash
git add tools/appsecret.py
git commit -m "feat: reproduce X-LINEGAME-APPSECRET from frida capture"
```

---

## Task 3: Wire the native-login headers into `game_login()`

**Files:**
- Modify: `tools/new_account.py` (constants near top; `game_login()`; its call sites `exchange_and_login` and `resume_pending`)

**Interfaces:**
- Consumes: `appsecret.header(...)` from Task 2; existing `guest` dict fields `userKey`, `userToken`, `refreshUserToken`; existing `udid`, `device_id`.
- Produces: `game_login(cc, udid, guest_cookie=None, *, user_key=None, device_id=None)` that returns the same session dict as today (`uid/mid/rsn/lf_ac/tutorialStep/cc`) but now succeeds for a **fresh** guest.

- [ ] **Step 1: Bump the version constants to the installed client**

In `tools/new_account.py`, change:
```python
SDK_VERSION = "3.12.1.422"
```
to keep as-is only if the capture's `X-Linegame-SdkVersion` matches; otherwise set it to the value seen in the capture. And change:
```python
UA_GAME = "LGRGS/12.2.4 (Linux; U; Android 12; en-US; ASUSAI2501B Build/V417IR)"
APP_VERSION = "LGRGS/12.2.4;android/12"
```
to:
```python
UA_GAME = "LGRGS/12.3.0 (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)"
APP_VERSION = "LGRGS/12.3.0;android/12"
```

- [ ] **Step 2: Add the native-login headers to `game_login()`**

Replace the `game_login` signature and header block. Change the signature line:
```python
def game_login(cc: str, udid: str, guest_cookie: str | None = None) -> dict:
```
to:
```python
def game_login(cc: str, udid: str, guest_cookie: str | None = None, *,
               user_key: str | None = None, device_id: str | None = None) -> dict:
```
Then, immediately before `req = urllib.request.Request(...)`, add the native headers the
fresh-guest login requires (names verbatim from the capture / libgame `0x1256638`):
```python
    # Fresh-guest login needs the native X-LINEGAME-* headers the pinned client sends;
    # the SDK-style headers above are enough only for an already-established guest.
    if user_key:
        import appsecret
        headers["X-LINEGAME-APPID"] = APP_ID
        headers["X-LINEGAME-USERKEY"] = user_key
        headers["X-LINEGAME-APPSECRET"] = appsecret.header(
            APP_ID, user_key, udid, ts_ms, device_id)
```

- [ ] **Step 3: Pass the new args through the call sites**

In `exchange_and_login`, change:
```python
    return game_login(cc, udid)
```
to:
```python
    return game_login(cc, udid, user_key=guest.get("userKey"), device_id=device_id)
```
In `resume_pending`, change:
```python
        session = game_login(cc, acct["udid"])
```
to:
```python
        session = game_login(cc, acct["udid"], user_key=acct.get("gameId"),
                             device_id=acct.get("deviceId"))
```

- [ ] **Step 4: Byte-compile**

Run:
```bash
python -m py_compile tools/new_account.py && echo "compile ok"
```
Expected: `compile ok`.

- [ ] **Step 5: Live verify — a fresh guest now logs in (measure state)**

Run:
```bash
python tools/new_account.py --count 1
```
Expected: the `login` line prints `HTTP 200 uid=... mid=... rsn=...` (not `FAILED HTTP 401`), and `roster/accounts/account-<gameId>-<dev>.json` gains an `lf_ac`. Confirm the session is real:
```bash
python tools/rewards.py --xml id/$(ls -t roster/accounts | head -1) 2>/dev/null || \
python -c "import glob,json,os; f=sorted(glob.glob('roster/accounts/account-*.json'),key=os.path.getmtime)[-1]; d=json.load(open(f)); print('gameId',d['gameId'],'level-check via /home next'); import sys; sys.path.insert(0,'tools'); from rewards import check_session; print(check_session('LF_AC='+d['lf_ac']))"
```
Expected: `check_session` returns a player dict with `level` 1. If it 401s with a blanket message, servers are mid-maintenance — retry later with `--resume`; the mint itself is fine.

- [ ] **Step 6: Commit**

```bash
git add tools/new_account.py
git commit -m "feat: fresh-guest headless login via native X-LINEGAME-APPSECRET headers"
```

---

## Task 4: `reroll.py` batch driver

**Files:**
- Create: `tools/reroll.py`
- Uses: `new_account.make_account`, `rewards.claim_all`, `gacha.ticket_counts`/`pick_ticket_group`/`cmd_roll`, `new_account.write_account_xml`

**Interfaces:**
- Consumes: `make_account(write_xml_dir=None) -> account dict` (has `lf_ac`, `gameId`, `rsn`, `udid`); `claim_all(cookie, confirm=True) -> int`; `ticket_counts(cookie) -> (premium,event)`; `pick_ticket_group(cookie) -> (groupId,price,name)`; `cmd_roll(cookie, uid, group_id, index, pay_type, do_confirm, save=False) -> [unit dicts]`.
- Produces: a CLI `python tools/reroll.py --count N [--xml-dir DIR] [--delay SEC]` that mints, claims, rolls once, exports XML, and appends one row per account to `roster/reroll-sessions.csv`.

- [ ] **Step 1: Write the driver**

Create `tools/reroll.py`:
```python
r"""Headless gacha reroll: mint a fresh guest, claim its free tickets, roll once, export.

No emulator or app in the loop - every step is an API call driven from the host. One
account yields its 5 free gacha tickets and one pull. Results append to a CSV for
monitoring. Mints are throttled to avoid the server's rapid-creation abuse flag.

    python tools/reroll.py --count 5
    python tools/reroll.py --count 20 --xml-dir id --delay 20

Standard library only (new_account.py adds cryptography for the XML).
"""
from __future__ import annotations
import argparse, csv, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import new_account, rewards, gacha

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "roster", "reroll-sessions.csv")
FIELDS = ["timestamp", "status", "seconds", "gameId", "rsn", "tickets", "units", "file", "error"]


def _roll_once(cookie):
    premium, _event = gacha.ticket_counts(cookie)
    group_id, price, _name = gacha.pick_ticket_group(cookie)
    if not group_id or premium < price:
        return premium, []
    granted = gacha.cmd_roll(cookie, None, group_id, 1, "TICKET", True) or []
    return premium, [u.get("unitCode", "") for u in granted if u.get("unitCode")]


def _log_row(row):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    new = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(FIELDS)
        writer.writerow(row)


def one(xml_dir):
    start = time.time()
    status, game_id, rsn, tickets, units, fpath, err = "FAIL", "-", "-", 0, "", "-", ""
    try:
        account = new_account.make_account(write_xml_dir=xml_dir)
        game_id = account.get("gameId") or "-"
        rsn = account.get("rsn") or "-"
        if not account.get("lf_ac"):
            err = "no session (pending-login)"
        else:
            cookie = "LF_AC=" + account["lf_ac"]
            rewards.claim_all(cookie, confirm=True)
            tickets, units = _roll_once(cookie)
            fpath = new_account.write_account_xml(account, xml_dir) if xml_dir else "-"
            status = "OK"
    except SystemExit as e:
        err = "exit: %s" % e
    except Exception as e:                       # a bad account must not sink the batch
        import traceback; traceback.print_exc()
        err = str(e)
    row = [time.strftime("%Y-%m-%d %H:%M:%S"), status, int(time.time() - start),
           game_id, rsn, tickets, ",".join(units) or "-", fpath or "-", " ".join(str(err).split())[:200]]
    print("[REROLL] %s %-4s %4ds  %-10s tickets=%s units=%s"
          % (row[0], status, row[2], game_id, tickets, ",".join(units) or "-"), flush=True)
    _log_row(row)
    return status == "OK"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--xml-dir", help="also write each account's shared_prefs .xml here")
    parser.add_argument("--delay", type=float, default=15.0, help="seconds between mints (abuse-flag throttle)")
    args = parser.parse_args()
    ok = 0
    for i in range(args.count):
        print("\n=== reroll %d/%d ===" % (i + 1, args.count))
        ok += one(args.xml_dir)
        if i + 1 < args.count:
            time.sleep(args.delay)
    print("\ndone: %d/%d ok" % (ok, args.count))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Byte-compile**

Run:
```bash
python -m py_compile tools/reroll.py && echo "compile ok"
```
Expected: `compile ok`.

- [ ] **Step 3: Live verify one reroll end-to-end (measure state)**

Run:
```bash
python tools/reroll.py --count 1 --xml-dir id
```
Expected: `[REROLL] ... OK` with `tickets=5 units=<code>`, a new `id/<rsn>.xml`, and a row appended to `roster/reroll-sessions.csv`. Confirm the ticket delta was real (spent, not ignored):
```bash
python -c "import csv; r=list(csv.DictReader(open('roster/reroll-sessions.csv',encoding='utf-8-sig'))); print('last row units:', r[-1]['units'])"
```
Expected: `last row units:` shows a non-empty unit code (a pull happened → 5 tickets were spent).

- [ ] **Step 4: Commit**

```bash
git add tools/reroll.py
git commit -m "feat: headless reroll driver (mint -> claim -> roll -> export -> csv)"
```

---

## Task 5 (Phase 2, stretch): Capture `/stage/save` with Frida

**Files:**
- Create: `tools/frida/dump_stagesave.js`

**Interfaces:**
- Produces: `roster/scratch/stagesave-<ts>.capture.txt` with the plaintext of `/stage/enter/...` and `/stage/save/...` for one won st01, incl. body and any signature header. Task 6/7 consume it.

- [ ] **Step 1: Write the hook (reuses the SSL_write technique, different filter)**

Create `tools/frida/dump_stagesave.js`:
```javascript
'use strict';
// Dump plaintext of outgoing TLS writes for the stage flow (enter + save). Same SSL_write
// technique as dump_login.js; only the URL filter changes.
function toText(buf, len) {
  const bytes = new Uint8Array(buf.readByteArray(len));
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    const c = bytes[i];
    out += (c >= 0x20 && c < 0x7f) || c === 0x0a || c === 0x0d ? String.fromCharCode(c) : '.';
  }
  return out;
}
function relevant(t) {
  return t.indexOf('/stage/') !== -1 && t.indexOf('rangers-api') !== -1;
}
setImmediate(function () {
  const addr = Module.findExportByName(null, 'SSL_write');
  if (!addr) { console.log('[dump_stagesave] SSL_write not found'); return; }
  Interceptor.attach(addr, {
    onEnter(args) {
      const len = args[2].toInt32();
      if (len <= 0 || len > 131072) return;
      const t = toText(args[1], len);
      if (relevant(t)) { console.log('=== stage ' + len + ' ==='); console.log(t); console.log('=== end ==='); }
    }
  });
  console.log('[dump_stagesave] hooked SSL_write @ ' + addr);
});
```

- [ ] **Step 2: Capture one won stage (on the phone)**

Run:
```bash
python tools/frida/capture.py --script tools/frida/dump_stagesave.js
```
Then in-app: log in a guest, play Valley-of-Wind **st01** to a win. Ctrl+C after the
`/stage/save` block prints. Expected: the capture file contains a `/stage/save/...` line
with a request body.

- [ ] **Step 3: Commit the hook (not the capture — it's gitignored)**

```bash
git add tools/frida/dump_stagesave.js
git commit -m "feat: frida hook to capture /stage/save (phase 2)"
```

---

## Task 6 (Phase 2, stretch): Confirm stage-save schema from the binary

**Files:**
- Uses: `lib/arm64-v8a/libgame.so` pulled from the phone/APK; the Task 5 capture

**Interfaces:**
- Produces: a documented, verbatim `/stage/save` route template and body field list (no guessed names) written into the top of `tools/stage_replay.py` (Task 7).

- [ ] **Step 1: Pull the arm64 `.so` and extract its strings**

Run (paths per your device):
```bash
adb shell "su -c 'cp /data/app/*com.linecorp.LGRGS*/lib/arm64/libgame.so /sdcard/libgame.so'" 2>/dev/null || \
adb shell pm path com.linecorp.LGRGS
adb pull /sdcard/libgame.so roster/scratch/libgame.so
python -c "import re,sys;[print(m.group().decode()) for m in re.finditer(rb'[\x20-\x7e]{5,}', open('roster/scratch/libgame.so','rb').read())]" > roster/scratch/libgame.strings.txt
```
Expected: `roster/scratch/libgame.strings.txt` exists (tens of thousands of lines).

- [ ] **Step 2: Find the stage-save route and neighbouring field names**

Run:
```bash
grep -nE '/stage/(save|enter|clear)[a-zA-Z0-9/_%{}?=&.$-]*' roster/scratch/libgame.strings.txt | sort -u
```
Cross-check every field name against the Task 5 capture body. **Do not invent names** — use
only strings present in both. Record the exact route template (e.g. `/stage/save/{stageId}/{n}`)
and the body schema. (Delegate the bulk grep/scan to qwen per `/qwen-agent` if desired.)

- [ ] **Step 3: Commit the extracted notes**

Write the confirmed route + fields as a comment block into a stub `tools/stage_replay.py`:
```python
r"""Replay a captured /stage/save to grant exp headlessly (PHASE 2, stretch, RISKY).

STATUS: experimental. stage-save is a mutation with no dry run; test ONLY on a throwaway
guest you can lose. If the server computes battles authoritatively it will reject or flag
this - stop and fall back to the hybrid genIDLevel1.

Route (verbatim from libgame.so + capture):  <PASTE ROUTE TEMPLATE>
Body fields (present in both binary and capture):  <PASTE FIELD LIST>
"""
```
```bash
git add tools/stage_replay.py
git commit -m "docs: confirmed /stage/save route+schema from libgame.so (phase 2)"
```

---

## Task 7 (Phase 2, stretch): Replay stage-save on a throwaway guest

**Files:**
- Modify: `tools/stage_replay.py`
- Uses: `rangers_api.call`, `appsecret.header`, `rewards.check_session`

**Interfaces:**
- Consumes: `call(cookie, path, method, body=None, api=None)` from `rangers_api`; `check_session(cookie) -> player dict` (has `level`).
- Produces: `replay_stage(cookie, times=2) -> (start_level, end_level)`; CLI `python tools/stage_replay.py --xml <throwaway>.xml --times 2 --confirm`.

- [ ] **Step 1: Implement the replay with a measured level gate**

Fill `tools/stage_replay.py` below its docstring:
```python
from __future__ import annotations
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangers_api import call, add_session_args, resolve_cookie
from rewards import check_session

STAGE_SAVE = "<PASTE ROUTE TEMPLATE>"   # from Task 6, e.g. "/stage/save/%s/%s"


def _save_body():
    # Verbatim from the capture (Task 5), fields confirmed in libgame.so (Task 6).
    return {}   # <FILL from capture>


def replay_stage(cookie, times=2, confirm=False):
    player = check_session(cookie)
    start_level = player.get("level")
    if not confirm:
        print("DRY RUN - would replay %d time(s) from level %s" % (times, start_level))
        return start_level, start_level
    for i in range(times):
        status, data = call(cookie, STAGE_SAVE, "POST", body=_save_body())
        ok = status == 200 and isinstance(data, dict) and "result" in data
        print("  save %d: HTTP %s %s" % (i + 1, status, "ok" if ok else str(data)[:120]))
        if not ok:
            print("  -> rejected; stopping (server likely validates battles). Use hybrid.")
            break
        time.sleep(2)
    end_level = check_session(cookie).get("level")
    print("level %s -> %s" % (start_level, end_level))
    return start_level, end_level


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_args(parser)
    parser.add_argument("--times", type=int, default=2)
    parser.add_argument("--confirm", action="store_true", help="actually replay (spends nothing but mutates server state)")
    args = parser.parse_args()
    replay_stage(resolve_cookie(args), args.times, args.confirm)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Byte-compile**

Run:
```bash
python -m py_compile tools/stage_replay.py && echo "compile ok"
```
Expected: `compile ok`.

- [ ] **Step 3: Live gate — mint a THROWAWAY guest and replay (measure level)**

Run:
```bash
python tools/reroll.py --count 1 --xml-dir roster/scratch    # throwaway; xml lands in gitignored scratch
python tools/stage_replay.py --xml roster/scratch/$(ls -t roster/scratch/*.xml | head -1 | xargs basename) --times 2 --confirm
```
Expected — one of two outcomes, both acceptable:
- **Works:** `level 1 -> 3` (or 1→2 per save). Phase 2 viable → proceed to Task 8.
- **Rejected:** `save 1: HTTP <4xx/5xx>` then `-> rejected ... Use hybrid.` Record the status/body in the plan's notes; Phase 2 stops here and level-3 stays hybrid. **This is a valid, expected result — not a failure of the task.**

- [ ] **Step 4: Commit**

```bash
git add tools/stage_replay.py
git commit -m "feat: stage-save replay with measured level gate (phase 2, experimental)"
```

---

## Task 8 (Phase 2, only if Task 7 worked): `--level` in reroll

**Files:**
- Modify: `tools/reroll.py`

**Interfaces:**
- Consumes: `stage_replay.replay_stage(cookie, times, confirm=True)`.
- Produces: `python tools/reroll.py --count N --level 3` replaying enough stage-saves to reach the target before claiming.

- [ ] **Step 1: Add the flag and the replay step**

In `tools/reroll.py`, add to `main()`'s parser:
```python
    parser.add_argument("--level", type=int, default=1, help="target level via stage-save replay (phase 2; 1 = skip)")
```
Change `one(xml_dir)` to `one(xml_dir, target_level)` and, right after `cookie = "LF_AC=" + account["lf_ac"]` and before `rewards.claim_all`, insert:
```python
            if target_level > 1:
                import stage_replay
                start, end = stage_replay.replay_stage(cookie, times=max(1, target_level - 1), confirm=True)
                if end is None or end < target_level:
                    err = "level %s < target %s (stage replay incomplete)" % (end, target_level)
```
Update the call in `main()`:
```python
        ok += one(args.xml_dir, args.level)
```

- [ ] **Step 2: Byte-compile and live-verify to level 3**

Run:
```bash
python -m py_compile tools/reroll.py && echo "compile ok"
python tools/reroll.py --count 1 --xml-dir roster/scratch --level 3
```
Expected: `[REROLL] ... OK` and the account's `check_session` level reads 3. If it reads <3, the CSV `error` column records why.

- [ ] **Step 3: Commit**

```bash
git add tools/reroll.py
git commit -m "feat: reroll --level via stage-save replay (phase 2)"
```

---

## Self-Review

**Spec coverage:**
- §1 headless mint + level-1 reroll → Tasks 3, 4. ✓
- §2 missing rangers `/login` crack → Tasks 1, 2, 3. ✓
- §3 Frida-first SSL_write, two-guest diff, constant/derived branches → Tasks 1, 2. ✓
- §4 integration (`new_account.py` login step, `reroll.py`, `genIDLevel1` untouched) → Tasks 3, 4 (bot file never modified). ✓
- §5 verification by state delta → Tasks 3 §5, 4 §3 (measure ticket/level, not status). ✓
- §6 safety (gitignore secrets, throttle, secrets stay local) → Task 0, Task 4 `--delay`. ✓
- §7 Phase 2 level-3 stretch with risk gate + hybrid fallback → Tasks 5–8, gate in Task 7 §3. ✓
- §8 risks (device-attestation, split arm64 .so) → Task 6 §1 pulls arm64 `.so`; Task 7 handles rejection. ✓

**Placeholder scan:** The only `<PASTE ...>` / `<FILL ...>` markers are the *captured secret values* and the *binary-confirmed route/fields* — data that by definition cannot exist until the one-time on-phone capture runs. Each is bounded to a single named location with the exact command that produces it. All executable scaffolding (Frida JS, runner, header wiring, reroll driver, replay harness) is complete and byte-compilable now.

**Type consistency:** `game_login(..., user_key, device_id)` matches both call sites (Task 3 §3). `cmd_roll(..., save=False)` matches its current signature. `claim_all(cookie, confirm=True)`, `ticket_counts`, `pick_ticket_group`, `check_session`, `call(..., api=None)` all match the current tool sources read during planning. `replay_stage` return `(start_level, end_level)` matches its use in Task 8.
