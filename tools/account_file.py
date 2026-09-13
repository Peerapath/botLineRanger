r"""Build the on-disk account file the game reads (`_LINE_COCOS_PREF_KEY.xml`).

This is the inverse of `device_session.decrypt_lfac`: given a session token (LF_AC)
and a game device uuid, it produces the exact shared_prefs XML that the LINE Rangers
client restores a GUEST session from - the same file the old UI bot pushes with
`importFileFromInputToExecute()`.

    _DEVICE_UUID_KEY = 32 chars, base64-decodes to the 24-byte AES-192 key
    _ENC_LF_AC_KEY   = base64( IV[16] + AES-192-CBC-PKCS5( LF_AC ) )

    python tools/account_file.py --selftest              # round-trip against real files
    python tools/account_file.py --lf-ac "..." --udid <32hex> --out acct.xml

Standard library + `cryptography` (same dependency device_session.py already uses).
"""

from __future__ import annotations

import argparse
import base64
import glob
import html
import os
import re
import secrets
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from device_session import decrypt_lfac  # noqa: E402

# The game writes the blob wrapped at 76 chars with a trailing newline+indent, and
# Android's XML writer escapes those newlines as &#10;. Match it byte for byte.
WRAP = 76


def new_udid() -> str:
    """A fresh game device uuid: 32 hex chars, which base64-decode to a 24-byte key."""
    return secrets.token_hex(16)


def encrypt_lfac(device_uuid: str, lf_ac: str) -> str:
    """Inverse of decrypt_lfac - returns the base64 blob for _ENC_LF_AC_KEY."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = base64.b64decode(device_uuid)
    iv = secrets.token_bytes(16)
    plain = lf_ac.encode("utf-8")
    pad = 16 - (len(plain) % 16)          # PKCS5: always pads, full block if aligned
    plain += bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    blob = iv + encryptor.update(plain) + encryptor.finalize()
    return base64.b64encode(blob).decode("ascii")


def _wrapped(blob: str) -> str:
    """Lay the blob out the way the game's XML writer does (76-char lines, &#10;)."""
    lines = [blob[i:i + WRAP] for i in range(0, len(blob), WRAP)]
    return "&#10;".join(lines) + "&#10;    "


def build_pref_xml(lf_ac: str, device_uuid: str, nation: str = "TH", language: str = "en") -> str:
    enc = _wrapped(encrypt_lfac(device_uuid, lf_ac))
    return (
        "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
        "<map>\n"
        '    <string name="_ENC_LF_AC_KEY">%s</string>\n'
        '    <string name="_LF_UT_KEY">GUEST</string>\n'
        '    <string name="USER_NATION_CODE">%s</string>\n'
        '    <string name="LANGUAGE_TYPE_SETTING_KEY">%s</string>\n'
        '    <string name="_DEVICE_UUID_KEY">%s</string>\n'
        "</map>\n" % (enc, nation, language, device_uuid)
    )


def read_pref_xml(path: str) -> tuple[str, str]:
    """Return (device_uuid, lf_ac) from an existing account XML."""
    with open(path, "r", encoding="utf-8") as handle:
        xml = handle.read()

    def field(name):
        match = re.search(r'<string name="%s">(.*?)</string>' % name, xml, re.S)
        return html.unescape(match.group(1)).strip() if match else None

    uuid_ = field("_DEVICE_UUID_KEY")
    return uuid_, decrypt_lfac(uuid_, field("_ENC_LF_AC_KEY"))


def selftest(sample_dir: str) -> int:
    """Round-trip real account files: decrypt -> re-encrypt -> decrypt must match."""
    files = sorted(glob.glob(os.path.join(sample_dir, "*.xml")))[:5]
    if not files:
        print("no sample files in %s" % sample_dir)
        return 1
    failures = 0
    for path in files:
        udid, lf_ac = read_pref_xml(path)
        rebuilt = build_pref_xml(lf_ac, udid)
        # parse our own output back through the game's own reader path
        tmp = re.search(r'<string name="_ENC_LF_AC_KEY">(.*?)</string>', rebuilt, re.S).group(1)
        back = decrypt_lfac(udid, html.unescape(tmp))
        ok = back == lf_ac
        failures += not ok
        print("  %-16s udid=%s  lf_ac[%d]  round-trip %s"
              % (os.path.basename(path), udid[:12] + "...", len(lf_ac), "OK" if ok else "FAIL"))
    print("\n%d/%d round-tripped" % (len(files) - failures, len(files)))
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true", help="round-trip existing account files")
    parser.add_argument("--sample-dir", default="D:/Programing/ranger/Test-Mitmproxy-Api/bot/input",
                        help="folder of real account XMLs for --selftest")
    parser.add_argument("--from-device", action="store_true",
                        help="read the live session off a rooted, logged-in device")
    parser.add_argument("--device", help="adb serial for --from-device")
    parser.add_argument("--lf-ac", help="session token to wrap")
    parser.add_argument("--udid", help="game device uuid (32 chars); generated if omitted")
    parser.add_argument("--out", help="path to write the XML to")
    args = parser.parse_args()

    if args.selftest:
        raise SystemExit(selftest(args.sample_dir))

    lf_ac, udid = args.lf_ac, args.udid
    if args.from_device:
        from device_session import read_session, find_adb
        sess = read_session(find_adb(), args.device)
        lf_ac = sess["lf_ac"]
        udid = udid or sess["device_uuid"]
        print("from device: userType=%s nation=%s" % (sess.get("userType"), sess.get("nation")))
    if not lf_ac:
        raise SystemExit("need --lf-ac, --from-device, or --selftest")
    udid = udid or new_udid()
    xml = build_pref_xml(lf_ac, udid)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(xml)
        print("udid=%s\nwrote %s" % (udid, args.out))
    else:
        print(xml)


if __name__ == "__main__":
    main()
