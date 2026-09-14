import os
import sys
import re
import html

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import relogin
from device_session import decrypt_lfac

# ไฟล์ตัวอย่าง 2 แบบ: CRLF (792 B แบบใน 15-3) และ LF (784 B) โครงเดียวกัน
CRLF_XML = (
    "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\r\n"
    "<map>\r\n"
    '    <string name="_ENC_LF_AC_KEY">OLDBLOB&#10;    </string>\r\n'
    '    <string name="_LF_UT_KEY">GUEST</string>\r\n'
    '    <string name="USER_NATION_CODE">TH</string>\r\n'
    '    <string name="LANGUAGE_TYPE_SETTING_KEY">en</string>\r\n'
    '    <string name="_DEVICE_UUID_KEY">49b1e91378be2e631276ee38125f818b</string>\r\n'
    "</map>\r\n"
)

LF_XML = (
    "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
    "<map>\n"
    '    <string name="_ENC_LF_AC_KEY">OLDBLOB&#10;    </string>\n'
    '    <string name="_LF_UT_KEY">GUEST</string>\n'
    '    <string name="USER_NATION_CODE">TH</string>\n'
    '    <string name="LANGUAGE_TYPE_SETTING_KEY">en</string>\n'
    '    <string name="_DEVICE_UUID_KEY">49b1e91378be2e631276ee38125f818b</string>\n'
    "</map>\n"
)


def test_read_account_pulls_fields():
    acct = relogin.read_account_from_text(CRLF_XML)
    assert acct["udid"] == "49b1e91378be2e631276ee38125f818b"
    assert acct["nation"] == "TH"
    assert acct["language"] == "en"
    assert acct["enc"] == "OLDBLOB"
    assert acct["text"] == CRLF_XML


def test_replace_enc_keeps_every_other_byte_and_roundtrips():
    udid = "49b1e91378be2e631276ee38125f818b"
    new_lfac = "LF_AC-brand-new-token-value-1234567890"
    out = relogin.replace_enc(CRLF_XML, udid, new_lfac)
    # ทุกอย่างนอกค่า _ENC_LF_AC_KEY เหมือนเดิม: เทียบด้วยการลบค่าออกทั้งคู่
    strip = lambda s: re.sub(r'(<string name="_ENC_LF_AC_KEY">).*?(</string>)', r'\1X\2', s, flags=re.S)
    assert strip(out) == strip(CRLF_XML)
    assert "\r\n" in out and out.count("\r\n") == CRLF_XML.count("\r\n")
    # ถอดรหัสค่าใหม่กลับมาต้องได้ new_lfac
    m = re.search(r'<string name="_ENC_LF_AC_KEY">(.*?)</string>', out, re.S)
    blob = html.unescape(m.group(1)).strip()
    assert decrypt_lfac(udid, blob) == new_lfac


def test_read_account_missing_key_raises():
    import pytest
    bad = "<map>\n    <string name=\"USER_NATION_CODE\">TH</string>\n</map>\n"
    with pytest.raises(relogin.BadFile):
        relogin.read_account_from_text(bad)


def test_replace_enc_preserves_lf_layout():
    """Verify byte preservation works for LF (Unix-style) line endings"""
    udid = "49b1e91378be2e631276ee38125f818b"
    new_lfac = "LF_AC-brand-new-token-value-1234567890"
    out = relogin.replace_enc(LF_XML, udid, new_lfac)
    # ทุกอย่างนอกค่า _ENC_LF_AC_KEY เหมือนเดิม
    strip = lambda s: re.sub(r'(<string name="_ENC_LF_AC_KEY">).*?(</string>)', r'\1X\2', s, flags=re.S)
    assert strip(out) == strip(LF_XML)
    # ต้องไม่มี CRLF เลย คงเป็น LF เท่านั้น
    assert "\r\n" not in out
    assert "\n" in out and out.count("\n") == LF_XML.count("\n")
    # ถอดรหัสค่าใหม่กลับมาต้องได้ new_lfac
    m = re.search(r'<string name="_ENC_LF_AC_KEY">(.*?)</string>', out, re.S)
    blob = html.unescape(m.group(1)).strip()
    assert decrypt_lfac(udid, blob) == new_lfac
