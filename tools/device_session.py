r"""Extract a live LINE Rangers session token straight from the device - the HYBRID path.

Fully-headless account CREATION is blocked by the game's native, certificate-pinned
first-login (it needs an SDK-provided X-LINEGAME-APPSECRET we can't reproduce off-device
yet). But once the app has logged an account in - guest or linked - the game stores the
session token (LF_AC) on disk, AES-encrypted. We read and decrypt it here, then every
other tool (pull_roster.py, gacha.py, tutorial.py) drives the account over the API with
no proxy and no capture needed.

The token is in shared_prefs/_LINE_COCOS_PREF_KEY.xml:
    _ENC_LF_AC_KEY   = base64( IV[16] + AES-CBC-PKCS5( LF_AC ) )
    _DEVICE_UUID_KEY = the AES key, base64-encoded (24 bytes -> AES-192)
Algorithm reverse-engineered from SimpleCrypto.decrypt2() in the app's dex. The rangers
API derives the player from LF_AC alone, so no UID is required.

    python tools/device_session.py                 # print LF_AC + player summary
    python tools/device_session.py --save          # also write roster/accounts/session-*.json
    python tools/device_session.py --device 127.0.0.1:16480

Needs: adb (auto-located), root/su on the device, and `cryptography`.
"""

from __future__ import annotations

import argparse
import base64
import glob
import gzip
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import client_version

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "roster", "accounts")
PKG = "com.linecorp.LGRGS"
PREF = "/data/data/%s/shared_prefs/_LINE_COCOS_PREF_KEY.xml" % PKG
HOST = "rangers-api.line-apps.com"


def find_adb() -> str:
    candidates = [
        os.environ.get("ADB"),
        r"D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\adb.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        "adb",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            subprocess.run([path, "version"], capture_output=True, check=True)
            return path
        except Exception:
            continue
    raise SystemExit("adb not found. Set the ADB env var to your adb.exe path.")


def pick_device(adb: str, device: str | None) -> str:
    if device:
        return device
    if os.environ.get("MITM_DEVICE"):
        return os.environ["MITM_DEVICE"]
    out = subprocess.run([adb, "devices"], capture_output=True, text=True).stdout
    devices = [line.split("\t")[0] for line in out.splitlines()[1:] if "\tdevice" in line]
    if not devices:
        raise SystemExit("No adb device. Start the emulator/phone and `adb connect` it.")
    return devices[0]


def _su_cat(adb: str, device: str, remote: str) -> str:
    # adb shell joins its args with spaces, so `su -c` must receive the whole command as a
    # single quoted token or su only sees the first word. Pass it as one arg.
    result = subprocess.run(
        [adb, "-s", device, "shell", "su -c 'cat %s'" % remote],
        capture_output=True, text=True,
    )
    if "_ENC_LF_AC_KEY" in result.stdout:
        return result.stdout
    # fall back to run-as (works on debuggable builds without root)
    result = subprocess.run(
        [adb, "-s", device, "shell", "run-as %s cat %s" % (PKG, remote)],
        capture_output=True, text=True,
    )
    return result.stdout


def _pref_value(xml: str, key: str) -> str | None:
    match = re.search(r'name="%s">(.*?)</string>' % re.escape(key), xml, re.S)
    return html.unescape(match.group(1)).strip() if match else None


def decrypt_lfac(device_uuid: str, enc_lfac: str) -> str:
    """AES-192-CBC/PKCS5, key = base64(device_uuid), blob = base64(enc), IV = blob[:16]."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = base64.b64decode(device_uuid)
    blob = base64.b64decode(re.sub(r"\s+", "", enc_lfac))
    iv, ciphertext = blob[:16], blob[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    return plain[: -plain[-1]].decode("utf-8", "replace")   # strip PKCS5 padding


def read_session(adb: str, device: str) -> dict:
    xml = _su_cat(adb, device, PREF)
    if "_ENC_LF_AC_KEY" not in xml:
        raise SystemExit(
            "No session on %s - the app isn't logged in there. Open LINE Rangers, "
            "sign in (guest or linked), reach the home screen, then run this again." % device
        )
    device_uuid = _pref_value(xml, "_DEVICE_UUID_KEY")
    enc = _pref_value(xml, "_ENC_LF_AC_KEY")
    user_type = _pref_value(xml, "_LF_UT_KEY")
    nation = _pref_value(xml, "USER_NATION_CODE")
    if not (device_uuid and enc):
        raise SystemExit("Session prefs incomplete on %s (no device UUID / LF_AC)." % device)
    return {"lf_ac": decrypt_lfac(device_uuid, enc), "userType": user_type,
            "nation": nation, "device_uuid": device_uuid}


def get_lfac_from_device(device: str | None = None) -> str:
    """Convenience for other tools: return a fresh LF_AC read off the device."""
    adb = find_adb()
    return read_session(adb, pick_device(adb, device))["lf_ac"]


def player_summary(lf_ac: str) -> dict:
    path = "/player/units/equip?inven=false&team=false&deck=false"

    def send(prefix, app_version):
        now = int(time.time() * 1000)
        version_headers = client_version.headers(app_version)
        headers = {
            "Host": HOST, "Accept": "*/*",
            "App-Version": version_headers["App-Version"],
            "User-Agent": version_headers["User-Agent"],
            "Accept-Language": "en", "X-LINEGAME-MCC": "000", "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": str(now), "timeID": str(now),
            "Cookie": "LF_AC=" + lf_ac, "Accept-Encoding": "gzip",
        }
        req = urllib.request.Request("https://" + HOST + prefix + path, headers=headers, method="GET")
        try:
            resp = urllib.request.urlopen(req, timeout=25)
            raw, status = resp.read(), resp.status
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        except urllib.error.HTTPError as err:
            raw, status = err.read(), err.code
        return status, json.loads(raw)

    status, data = client_version.request(path, send)
    if status != 200:
        raise SystemExit("LF_AC rejected (HTTP %s) - it likely expired. Re-open the game "
                         "so it refreshes the session, then run this again." % status)
    result = data["result"]
    return {"uid": result["player"].get("uid"), "mid": result["player"].get("mid"),
            "userName": result["player"].get("userName"), "level": result["player"].get("level"),
            "ruby": result.get("rubyBalance", {}).get("total")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", help="adb serial (default: first connected / $MITM_DEVICE)")
    parser.add_argument("--save", action="store_true", help="write the session to roster/accounts/")
    parser.add_argument("--quiet", action="store_true", help="print only the LF_AC value")
    args = parser.parse_args()

    adb = find_adb()
    device = pick_device(adb, args.device)
    session = read_session(adb, device)
    lf_ac = session["lf_ac"]

    if args.quiet:
        print(lf_ac)
        return

    print("device   : %s" % device)
    print("userType : %s   nation: %s" % (session["userType"], session["nation"]))
    summary = player_summary(lf_ac)
    print("player   : %s  uid=%s mid=%s level=%s ruby=%s" % (
        summary["userName"], summary["uid"], summary["mid"], summary["level"], summary["ruby"]))
    print("LF_AC    : %s" % lf_ac)

    if args.save:
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, "session-%s-%s.json" % (summary["mid"] or "unknown",
                                                             time.strftime("%Y%m%d-%H%M%S")))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"capturedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "device": device,
                       "lf_ac": lf_ac, **summary, "userType": session["userType"]},
                      handle, ensure_ascii=False, indent=1)
        print("saved    : %s" % path)


if __name__ == "__main__":
    main()
