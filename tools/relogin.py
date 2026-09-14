r"""ต่ออายุ LF_AC ในไฟล์บัญชี GUEST ทั้งโฟลเดอร์แบบไม่ใช้เกม แล้วเขียนทับไฟล์เดิม.

เซิร์ฟเวอร์ระบุผู้เล่นจาก LF_AC เก่าที่เก็บในไฟล์ (guestCookie) ไม่ใช่จากเครื่อง จึง
ยิง GET /v12.3/login ด้วย cc (userToken ของ guest ที่ mint จาก API) + udid + guestCookie
เพื่อขอ LF_AC ใหม่ แล้วเข้ารหัสด้วย udid เดิมทับเฉพาะค่า _ENC_LF_AC_KEY ในไฟล์.

Standard library เท่านั้น (account_file/device_session ใช้ cryptography อยู่แล้ว).

    python tools/relogin.py bot/input/15-3 --workers 4
    python tools/relogin.py bot/input/15-3 --limit 3
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from account_file import encrypt_lfac, _wrapped  # noqa: E402
from device_session import decrypt_lfac  # noqa: E402

ENC_RE = re.compile(r'(<string name="_ENC_LF_AC_KEY">)(.*?)(</string>)', re.S)


class BadFile(Exception):
    """ไฟล์อ่านไม่ได้ หรือไม่มีคีย์ที่จำเป็น"""


def _field(text, name):
    m = re.search(r'<string name="%s">(.*?)</string>' % re.escape(name), text, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def read_account_from_text(text):
    udid = _field(text, "_DEVICE_UUID_KEY")
    enc = _field(text, "_ENC_LF_AC_KEY")
    if not udid or not enc:
        raise BadFile("missing _DEVICE_UUID_KEY or _ENC_LF_AC_KEY")
    return {
        "udid": udid,
        "enc": enc,
        "nation": _field(text, "USER_NATION_CODE") or "TH",
        "language": _field(text, "LANGUAGE_TYPE_SETTING_KEY") or "en",
        "text": text,
    }


def read_account(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return read_account_from_text(fh.read())


def replace_enc(text, udid, lf_ac):
    """แทนที่เฉพาะค่า _ENC_LF_AC_KEY ด้วย blob ใหม่ คงส่วนอื่นทุกไบต์"""
    wrapped = _wrapped(encrypt_lfac(udid, lf_ac))
    return ENC_RE.sub(lambda m: m.group(1) + wrapped + m.group(3), text, count=1)
