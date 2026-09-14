# แผนสร้างเครื่องมือต่ออายุโทเค็นแบบไม่ใช้เกม (Headless Relogin Batch)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** สร้าง CLI `tools/relogin.py` ที่ต่ออายุ `_ENC_LF_AC_KEY` ในไฟล์บัญชี GUEST ทั้งโฟลเดอร์ โดยไม่ต้องเปิดเกม แล้วเขียนโทเค็นใหม่ทับไฟล์เดิม

**Architecture:** ต่อยอดจากที่พิสูจน์กับเซิร์ฟเวอร์จริงแล้ว — เซิร์ฟเวอร์ระบุผู้เล่นจาก LF_AC เก่าที่เก็บในไฟล์ ยิง `GET /v12.3/login` ด้วย `cc` (userToken ของ guest ที่ mint จาก API) + `udid` + `guestCookie` (LF_AC เก่าเต็ม) แล้วได้ LF_AC ใหม่กลับมาทาง Set-Cookie จากนั้นเข้ารหัสด้วย udid เดิมแล้วแทนที่เฉพาะค่า `_ENC_LF_AC_KEY` ในไฟล์ ใช้ thread pool + สำรองไฟล์ + log แบบ resume ได้

**Tech Stack:** Python 3 standard library เท่านั้น (ยกเว้น `cryptography` ที่ `account_file.py`/`device_session.py` ใช้อยู่แล้ว) ใช้ `concurrent.futures.ThreadPoolExecutor` สำหรับงานขนาน

## Global Constraints

- **Standard library เท่านั้น** ในทุก `tools/*.py` ยกเว้น `cryptography` ที่ `account_file.py`/`device_session.py` ใช้อยู่แล้ว
- **API prefix เป็น `/v12.3`** และ client version `12.3.0` — ดึงจาก `rangers_api.API` และ `rangers_api.CLIENT_VERSION` (แหล่งเดียว) ห้าม hardcode `new_account.py` ยังเป็น 12.2.4 จึงห้ามเรียก `game_login()` ตรง ๆ
- **โทเค็นห้ามออกนอกเครื่อง** — `cc`, LF_AC, userToken ล็อกอินบัญชีจริงได้ ห้ามพิมพ์ออกจอ ห้ามใส่ใน log ส่งได้เฉพาะไปที่ `rangers-api.line-apps.com` และ `game-api.line.me`
- **แทนที่เฉพาะค่าโทเค็น** — ไม่สร้างไฟล์ใหม่ทั้งไฟล์ เพราะ 15-3 มีทั้ง CRLF (792 B) และ LF (784 B) ต้องคงทุกไบต์นอกค่า `_ENC_LF_AC_KEY`
- **Testing convention:** repo นี้ไม่มี pytest ที่ผ่านมา แต่ host มี pytest 9.1.1 แผนนี้ใช้ pytest กับไฟล์ทดสอบใน `tools/tests/` (ตรรกะล้วน ไม่แตะเน็ต) ส่วนการยืนยันกับเซิร์ฟเวอร์จริงทำด้วยคำสั่งวัดผลตามที่ระบุใน task สุดท้าย
- **ห้าม commit ไฟล์ที่มีโทเค็น** — เพิ่ม `bot/input/`, `*_backup/`, `*.relogin.csv` ใน `.gitignore`

---

## File Structure

- `tools/relogin.py` (สร้างใหม่) — โมดูลหลัก + CLI: อ่าน/เข้ารหัสไฟล์, ล็อกอิน, CcPool, วนงานขนาน, log, resume
- `tools/tests/test_relogin.py` (สร้างใหม่) — ทดสอบตรรกะล้วน (replace_enc, parse, resume, การนับหยุด)
- `.gitignore` (แก้) — กันไฟล์บัญชี/สำรอง/log หลุด git

โครงภายใน `tools/relogin.py` แบ่งเป็น 3 กลุ่ม:
1. ฟังก์ชันบริสุทธิ์ (ทดสอบง่าย): `read_account`, `replace_enc`, `parse_log`, `iter_targets`
2. ฟังก์ชันแตะเครือข่าย: `login`, `CcPool`
3. ตัวขับ: `process_file`, `run`, `main`

---

## Task 1: โครงไฟล์ + parse + replace_enc (ตรรกะล้วน)

**Files:**
- Create: `tools/relogin.py`
- Create: `tools/tests/test_relogin.py`
- Create: `tools/tests/__init__.py` (ไฟล์ว่าง)

**Interfaces:**
- Consumes: `account_file.encrypt_lfac(device_uuid, lf_ac) -> str`, `account_file._wrapped(blob) -> str`, `device_session.decrypt_lfac(device_uuid, enc) -> str`
- Produces:
  - `read_account(path) -> dict` คืน `{"udid", "enc", "nation", "language", "text"}` (text = ข้อความไฟล์ดิบ) หรือ raise `BadFile` ถ้าไม่มี `_DEVICE_UUID_KEY`/`_ENC_LF_AC_KEY`
  - `replace_enc(text, udid, lf_ac) -> str` แทนที่เฉพาะค่าใน `<string name="_ENC_LF_AC_KEY">…</string>` ด้วย `_wrapped(encrypt_lfac(udid, lf_ac))` คงส่วนอื่นทุกไบต์
  - `class BadFile(Exception)`

- [ ] **Step 1: เขียน test ที่ต้องล้มก่อน**

สร้าง `tools/tests/__init__.py` เป็นไฟล์ว่าง แล้วเขียน `tools/tests/test_relogin.py`:

```python
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
```

- [ ] **Step 2: รัน test ให้เห็นว่าล้ม**

Run: `python -m pytest tools/tests/test_relogin.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'relogin'` หรือ `AttributeError`

- [ ] **Step 3: เขียน `tools/relogin.py` ให้ผ่านเฉพาะส่วนตรรกะ**

```python
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
```

หมายเหตุ: `read_account` เปิดไฟล์ด้วย `newline=""` เพื่อไม่ให้ Python แปลง CRLF เป็น LF (คงไบต์เดิม)

- [ ] **Step 4: รัน test ให้ผ่าน**

Run: `python -m pytest tools/tests/test_relogin.py -q`
Expected: PASS ทั้ง 3 ข้อ

- [ ] **Step 5: commit**

```bash
git add tools/relogin.py tools/tests/__init__.py tools/tests/test_relogin.py
git commit -m "feat(relogin): read/replace _ENC_LF_AC_KEY preserving byte layout"
```

---

## Task 2: login() + CcPool (แตะเครือข่าย)

**Files:**
- Modify: `tools/relogin.py`
- Test: `tools/tests/test_relogin.py` (เพิ่ม test ที่ mock เครือข่าย)

**Interfaces:**
- Consumes: `new_account.register_guest(device_id) -> dict` (มี `["userToken"]`), `new_account._do(req) -> (status, parsed, set_cookies)`, `new_account._cookie_value(set_cookies, name) -> str|None`, `rangers_api.API`, `rangers_api.CLIENT_VERSION`, `time.monotonic`, `secrets.token_hex`
- Produces:
  - `login(cc, udid, guest_cookie, nation, language="en") -> (status, result, lf_ac)` โดย `result` เป็น dict ที่มี `rsn`/`level` หรือ `None`, `lf_ac` เป็น str หรือ `None`
  - `class CcPool` มี `.get() -> str`, `.renew(old_cc) -> str`, `.is_proven() -> bool`, `.mark_proven()`

- [ ] **Step 1: เขียน test ที่ mock เครือข่าย (ต้องล้มก่อน)**

เพิ่มใน `tools/tests/test_relogin.py`:

```python
def test_login_builds_v123_cookie_and_reads_setcookie(monkeypatch):
    seen = {}

    def fake_do(req):
        seen["cookie"] = req.headers["Cookie"]
        seen["url"] = req.full_url
        seen["app_version"] = req.headers["App-version"]  # urllib title-cases header keys
        return 200, {"result": {"rsn": "1097a844", "level": 3, "isNew": False}}, ["LF_AC=NEWTOKEN123; Domain=line-apps.com"]

    monkeypatch.setattr(relogin.na, "_do", fake_do)
    st, result, lf = relogin.login("CCVAL", "UDIDVAL", "OLDLFAC", "TH")
    assert st == 200 and lf == "NEWTOKEN123" and result["rsn"] == "1097a844"
    assert "cc=CCVAL" in seen["cookie"]
    assert "udid=UDIDVAL" in seen["cookie"]
    assert "guestCookie=OLDLFAC" in seen["cookie"]
    assert "/v12.3/login" in seen["url"]
    assert seen["app_version"] == "LGRGS/12.3.0;android/12"


def test_login_401_returns_none_lfac(monkeypatch):
    monkeypatch.setattr(relogin.na, "_do",
                        lambda req: (401, {"errorCode": 401}, []))
    st, result, lf = relogin.login("CC", "U", "OLD", "TH")
    assert st == 401 and lf is None and result is None


def test_ccpool_renew_only_once_per_stale_cc(monkeypatch):
    calls = {"n": 0}

    def fake_register(dev):
        calls["n"] += 1
        return {"userToken": "cc-%d" % calls["n"]}

    monkeypatch.setattr(relogin.na, "register_guest", fake_register)
    pool = relogin.CcPool()
    first = pool.get()
    # สอง thread เห็น cc เดิมเดียวกันแล้วขอ renew พร้อมกัน -> สร้างใหม่ครั้งเดียว
    a = pool.renew(first)
    b = pool.renew(first)
    assert a == b != first
    assert calls["n"] == 2  # ครั้งแรกตอน get(), ครั้งที่สองตอน renew()
```

- [ ] **Step 2: รัน test ให้เห็นว่าล้ม**

Run: `python -m pytest tools/tests/test_relogin.py -q -k "login or ccpool"`
Expected: FAIL — `AttributeError: module 'relogin' has no attribute 'login'`

- [ ] **Step 3: เพิ่ม login() + CcPool ใน `tools/relogin.py`**

เพิ่ม import ด้านบน (ต่อจาก import เดิม):

```python
import secrets
import threading
import time
import urllib.error
import urllib.request

import new_account as na
import rangers_api

UA_GAME = "LGRGS/%s (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)" % rangers_api.CLIENT_VERSION
APP_VERSION = "LGRGS/%s;android/12" % rangers_api.CLIENT_VERSION
RANGERS_HOST = rangers_api.HOST
LOGIN_PATH = rangers_api.API + "/login"
PROVEN_WINDOW = 60.0  # วินาที: cc ที่เพิ่งสำเร็จภายในช่วงนี้ ถือว่า 401 = ไฟล์เสียเอง
RETRY_WAITS = (2, 4, 8)  # backoff เมื่อเจอ network error / 429 / 5xx


class Transient(Exception):
    """error ชั่วคราวที่ retry แล้วยังไม่หาย -> ให้ตัวเรียกนับเป็น error"""


def login(cc, udid, guest_cookie, nation, language="en"):
    """ยิง GET /v12.3/login คืน (status, result_or_None, lf_ac_or_None).

    retry เองเมื่อเจอ network error / 429 / 5xx (RETRY_WAITS). ถ้ายังไม่หายหลัง
    retry ครบ -> raise Transient ให้ process_file นับเป็น error. 401 ไม่ retry
    (เป็นคำตอบจริงของเซิร์ฟเวอร์ ไม่ใช่ปัญหาชั่วคราว).
    """
    cookie = "cc=%s; udid=%s; guestCookie=%s;" % (cc, udid, guest_cookie)
    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        ts_ms = str(int(time.time() * 1000))
        headers = {
            "App-Version": APP_VERSION,
            "userType": "",
            "Nation-Code": nation,
            "Accept-Language": language,
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
        req = urllib.request.Request("https://" + RANGERS_HOST + LOGIN_PATH,
                                     headers=headers, method="GET")
        try:
            status, res, cookies = na._do(req)
        except urllib.error.URLError:
            last = "network"
            status = None
        else:
            if status == 429 or (isinstance(status, int) and 500 <= status < 600):
                last = status
            else:
                lf_ac = na._cookie_value(cookies, "LF_AC")
                result = res.get("result") if isinstance(res, dict) and "result" in res else None
                if not result or not lf_ac:
                    return status, None, None
                return status, result, lf_ac
        if attempt < len(RETRY_WAITS):
            time.sleep(RETRY_WAITS[attempt])
    raise Transient("transient after retries: %s" % last)


class CcPool:
    """เก็บ cc ที่ทุก thread ใช้ร่วมกัน สร้างใหม่แค่ครั้งเดียวต่อ cc ที่ตายแล้ว"""

    def __init__(self):
        self._lock = threading.Lock()
        self._cc = None
        self._proven_at = 0.0
        self._mint()

    def _mint(self):
        self._cc = na.register_guest(secrets.token_hex(16))["userToken"]
        self._proven_at = 0.0

    def get(self):
        with self._lock:
            return self._cc

    def renew(self, old_cc):
        with self._lock:
            if self._cc == old_cc:   # ยังไม่มีใคร renew cc ตัวนี้ -> สร้างใหม่
                self._mint()
            return self._cc

    def mark_proven(self):
        with self._lock:
            self._proven_at = time.monotonic()

    def is_proven(self):
        with self._lock:
            return (time.monotonic() - self._proven_at) < PROVEN_WINDOW
```

- [ ] **Step 4: รัน test ให้ผ่าน**

Run: `python -m pytest tools/tests/test_relogin.py -q`
Expected: PASS ทุกข้อ

- [ ] **Step 5: commit**

```bash
git add tools/relogin.py tools/tests/test_relogin.py
git commit -m "feat(relogin): add v12.3 login and shared cc pool"
```

---

## Task 3: parse_log + iter_targets (resume, ตรรกะล้วน)

**Files:**
- Modify: `tools/relogin.py`
- Test: `tools/tests/test_relogin.py`

**Interfaces:**
- Consumes: `csv`, `os.walk`
- Produces:
  - `parse_log(log_path) -> dict[str, str]` map จาก rel-path -> status ล่าสุด (อ่านไฟล์ CSV ที่มีอยู่ ไม่มีไฟล์ = {})
  - `iter_targets(root, done, force, limit) -> list[str]` คืน list ของ path เต็ม เรียงตาม rel-path ข้าม path ที่ `done.get(rel) == "ok"` เว้นแต่ `force`; ตัดที่ `limit` ถ้า `limit` ไม่ใช่ None

- [ ] **Step 1: เขียน test (ต้องล้มก่อน)**

เพิ่มใน `tools/tests/test_relogin.py`:

```python
def test_parse_log_keeps_latest_status(tmp_path):
    log = tmp_path / "x.relogin.csv"
    log.write_text(
        "path,status,rsn,level,time\n"
        "a.xml,error,,,2026-09-14T10:00:00\n"
        "a.xml,ok,111,3,2026-09-14T10:05:00\n"
        "b.xml,rejected,,,2026-09-14T10:06:00\n",
        encoding="utf-8",
    )
    done = relogin.parse_log(str(log))
    assert done == {"a.xml": "ok", "b.xml": "rejected"}


def test_iter_targets_skips_ok_unless_force(tmp_path):
    root = tmp_path / "acc"
    (root / "sub").mkdir(parents=True)
    for rel in ("a.xml", "sub/b.xml", "c.xml"):
        (root / rel).write_text("x", encoding="utf-8")
    done = {"a.xml": "ok", "c.xml": "rejected"}
    got = relogin.iter_targets(str(root), done, force=False, limit=None)
    rels = sorted(os.path.relpath(p, str(root)).replace("\\", "/") for p in got)
    assert rels == ["c.xml", "sub/b.xml"]        # a.xml (ok) ถูกข้าม
    got_force = relogin.iter_targets(str(root), done, force=True, limit=None)
    assert len(got_force) == 3
    got_limit = relogin.iter_targets(str(root), {}, force=False, limit=2)
    assert len(got_limit) == 2
```

- [ ] **Step 2: รัน test ให้เห็นว่าล้ม**

Run: `python -m pytest tools/tests/test_relogin.py -q -k "log or targets"`
Expected: FAIL — `AttributeError: ... 'parse_log'`

- [ ] **Step 3: เพิ่ม parse_log + iter_targets ใน `tools/relogin.py`**

เพิ่ม `import csv` ด้านบน แล้วเพิ่มฟังก์ชัน:

```python
def parse_log(log_path):
    """อ่าน log เดิม คืน map rel-path -> status ล่าสุด (บรรทัดท้ายชนะ)"""
    done = {}
    if not os.path.exists(log_path):
        return done
    with open(log_path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("path"):
                done[row["path"]] = row.get("status", "")
    return done


def iter_targets(root, done, force, limit):
    """คืน path เต็มของ .xml ที่ต้องทำ เรียงตาม rel-path ข้ามที่ ok แล้ว"""
    rels = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".xml"):
                full = os.path.join(dirpath, name)
                rels.append((os.path.relpath(full, root).replace("\\", "/"), full))
    rels.sort(key=lambda t: t[0])
    out = []
    for rel, full in rels:
        if not force and done.get(rel) == "ok":
            continue
        out.append(full)
        if limit is not None and len(out) >= limit:
            break
    return out
```

- [ ] **Step 4: รัน test ให้ผ่าน**

Run: `python -m pytest tools/tests/test_relogin.py -q`
Expected: PASS ทุกข้อ

- [ ] **Step 5: commit**

```bash
git add tools/relogin.py tools/tests/test_relogin.py
git commit -m "feat(relogin): resumable log parsing and target iteration"
```

---

## Task 4: process_file — งานของไฟล์เดียว (สำรอง เขียนทับ ตรวจซ้ำ)

**Files:**
- Modify: `tools/relogin.py`
- Test: `tools/tests/test_relogin.py`

**Interfaces:**
- Consumes: `read_account`, `login`, `replace_enc`, `decrypt_lfac`, `CcPool`, `shutil.copy2`, `os.replace`, `tempfile`
- Produces:
  - `process_file(full_path, root, pool, backup_root) -> dict` คืน `{"rel", "status", "rsn", "level"}` โดย status ∈ `{"ok","rejected","error","bad_file"}` ไม่พิมพ์โทเค็นใด ๆ
  - `backup_once(full_path, root, backup_root)` คัดลอกต้นฉบับไป `backup_root/<rel>` ครั้งแรกครั้งเดียว (มีแล้วไม่ทับ)
  - `atomic_write(full_path, text)` เขียน temp ในโฟลเดอร์เดียวกันแล้ว `os.replace`

- [ ] **Step 1: เขียน test (ต้องล้มก่อน)**

เพิ่มใน `tools/tests/test_relogin.py` (ใช้ helper สร้างไฟล์จริงแล้ว mock แค่ `login`):

```python
def _write_guest_xml(path, udid, lf_ac):
    import account_file
    path.write_text(account_file.build_pref_xml(lf_ac, udid, "TH", "en"),
                    encoding="utf-8")


def test_process_file_ok_overwrites_and_backs_up(tmp_path, monkeypatch):
    import account_file
    udid = account_file.new_udid()
    src = tmp_path / "acc" / "a.xml"
    src.parent.mkdir()
    _write_guest_xml(src, udid, "OLD-DEAD-LFAC")
    original = src.read_text(encoding="utf-8")

    monkeypatch.setattr(relogin, "login",
        lambda cc, u, gc, nation, language="en": (200, {"rsn": "111", "level": 3}, "FRESH-LFAC-VALUE"))

    class DummyPool:
        def get(self): return "ccval"
        def is_proven(self): return True
        def mark_proven(self): pass
        def renew(self, old): return "cc2"

    backup = tmp_path / "acc_backup"
    res = relogin.process_file(str(src), str(tmp_path / "acc"), DummyPool(), str(backup))
    assert res["status"] == "ok" and res["rsn"] == "111" and res["level"] == 3
    # ไฟล์ถูกเขียนโทเค็นใหม่ (ถอดได้ FRESH-LFAC-VALUE)
    from device_session import decrypt_lfac
    acct = relogin.read_account(str(src))
    assert decrypt_lfac(acct["udid"], acct["enc"]) == "FRESH-LFAC-VALUE"
    # ไฟล์สำรอง = ต้นฉบับเป๊ะ
    assert (backup / "a.xml").read_text(encoding="utf-8") == original


def test_process_file_rejected_when_401_and_cc_proven(tmp_path, monkeypatch):
    import account_file
    udid = account_file.new_udid()
    src = tmp_path / "acc" / "b.xml"
    src.parent.mkdir()
    _write_guest_xml(src, udid, "OLD")
    before = src.read_text(encoding="utf-8")
    monkeypatch.setattr(relogin, "login",
        lambda *a, **k: (401, None, None))

    class ProvenPool:
        def get(self): return "cc"
        def is_proven(self): return True
        def renew(self, old): raise AssertionError("must not renew when proven")
        def mark_proven(self): pass

    res = relogin.process_file(str(src), str(tmp_path / "acc"), ProvenPool(), str(tmp_path / "b_backup"))
    assert res["status"] == "rejected"
    assert src.read_text(encoding="utf-8") == before   # ไฟล์ไม่ถูกแตะ


def test_process_file_bad_file(tmp_path):
    src = tmp_path / "acc" / "c.xml"
    src.parent.mkdir()
    src.write_text("<map></map>", encoding="utf-8")

    class P:
        def get(self): return "cc"
        def is_proven(self): return True
    res = relogin.process_file(str(src), str(tmp_path / "acc"), P(), str(tmp_path / "bk"))
    assert res["status"] == "bad_file"
```

- [ ] **Step 2: รัน test ให้เห็นว่าล้ม**

Run: `python -m pytest tools/tests/test_relogin.py -q -k process_file`
Expected: FAIL — `AttributeError: ... 'process_file'`

- [ ] **Step 3: เพิ่ม process_file + helper ใน `tools/relogin.py`**

เพิ่ม import: `import shutil`, `import tempfile` แล้วเพิ่ม:

```python
def atomic_write(full_path, text):
    d = os.path.dirname(full_path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, full_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def backup_once(full_path, root, backup_root):
    rel = os.path.relpath(full_path, root)
    dest = os.path.join(backup_root, rel)
    if os.path.exists(dest):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(full_path, dest)


def process_file(full_path, root, pool, backup_root):
    rel = os.path.relpath(full_path, root).replace("\\", "/")
    try:
        acct = read_account(full_path)
    except (BadFile, OSError):
        return {"rel": rel, "status": "bad_file", "rsn": "", "level": ""}
    try:
        guest_cookie = decrypt_lfac(acct["udid"], acct["enc"])
    except Exception:
        return {"rel": rel, "status": "bad_file", "rsn": "", "level": ""}

    cc = pool.get()
    try:
        status, result, lf_ac = login(cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
        if status == 401 and not result:
            if pool.is_proven():
                return {"rel": rel, "status": "rejected", "rsn": "", "level": ""}
            cc = pool.renew(cc)
            status, result, lf_ac = login(cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
            if status == 401 and not result:
                return {"rel": rel, "status": "rejected", "rsn": "", "level": ""}
    except Transient:
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}
    if not result or not lf_ac:
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}

    pool.mark_proven()
    backup_once(full_path, root, backup_root)
    new_text = replace_enc(acct["text"], acct["udid"], lf_ac)
    atomic_write(full_path, new_text)
    # ตรวจซ้ำ: ถอดจากไฟล์ที่เขียนแล้วต้องได้ lf_ac เดิม ไม่ตรง = คืนข้อความเดิม
    check = read_account(full_path)
    if decrypt_lfac(check["udid"], check["enc"]) != lf_ac:
        atomic_write(full_path, acct["text"])
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}
    return {"rel": rel, "status": "ok",
            "rsn": result.get("rsn", ""), "level": result.get("level", "")}
```

- [ ] **Step 4: รัน test ให้ผ่าน**

Run: `python -m pytest tools/tests/test_relogin.py -q`
Expected: PASS ทุกข้อ

- [ ] **Step 5: commit**

```bash
git add tools/relogin.py tools/tests/test_relogin.py
git commit -m "feat(relogin): per-file relogin with backup, atomic write, verify"
```

---

## Task 5: run() + main() — วนงานขนาน หยุดอัตโนมัติ log ความคืบหน้า

**Files:**
- Modify: `tools/relogin.py`
- Test: `tools/tests/test_relogin.py` (ทดสอบตัวนับหยุดแบบแยกฟังก์ชัน)

**Interfaces:**
- Consumes: `concurrent.futures.ThreadPoolExecutor`, `parse_log`, `iter_targets`, `process_file`, `CcPool`, `csv`, `time`
- Produces:
  - `class StopTracker` ติดตามสถานะที่เสร็จตามลำดับ: `.record(status) -> str|None` คืนเหตุผลถ้าต้องหยุด (`"maintenance"` เมื่อ rejected ติดกัน `REJECT_STOP`=10; `"errors"` เมื่อ error ติดกันเกินเกณฑ์) หรือ None
  - `run(root, workers, limit, force) -> dict` ตัวขับหลัก คืนสรุปนับ
  - `main(argv=None)` parse args แล้วเรียก run

- [ ] **Step 1: เขียน test ตัวนับหยุด (ต้องล้มก่อน)**

เพิ่มใน `tools/tests/test_relogin.py`:

```python
def test_stop_tracker_stops_after_10_consecutive_rejected():
    t = relogin.StopTracker()
    reasons = [t.record("rejected") for _ in range(10)]
    assert reasons[:9] == [None] * 9
    assert reasons[9] == "maintenance"


def test_stop_tracker_ok_resets_rejected_streak():
    t = relogin.StopTracker()
    for _ in range(9):
        assert t.record("rejected") is None
    assert t.record("ok") is None          # ok คั่น -> เริ่มนับใหม่
    for _ in range(9):
        assert t.record("rejected") is None
    assert t.record("rejected") == "maintenance"  # ครบ 10 อีกรอบ
```

- [ ] **Step 2: รัน test ให้เห็นว่าล้ม**

Run: `python -m pytest tools/tests/test_relogin.py -q -k stop_tracker`
Expected: FAIL — `AttributeError: ... 'StopTracker'`

- [ ] **Step 3: เพิ่ม StopTracker + run + main ใน `tools/relogin.py`**

เพิ่ม import ด้านบน: `import concurrent.futures`, `import threading` (มีแล้วจาก Task 2) แล้วเพิ่ม:

```python
REJECT_STOP = 10   # rejected ติดกันเท่านี้ = น่าจะเซิร์ฟเวอร์ปิดปรับปรุง -> หยุด
ERROR_STOP = 60    # error ติดกันเท่านี้ -> หยุด (พักระหว่างทางจัดการใน run)


class StopTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._rejected = 0
        self._error = 0

    def record(self, status):
        with self._lock:
            if status == "rejected":
                self._rejected += 1
                self._error = 0
            elif status == "error":
                self._error += 1
                self._rejected = 0
            else:  # ok, bad_file คั่น streak การหยุด
                self._rejected = 0
                self._error = 0
            if self._rejected >= REJECT_STOP:
                return "maintenance"
            if self._error >= ERROR_STOP:
                return "errors"
            return None


def _fmt_summary(counts):
    return " ".join("%s=%d" % (k, counts.get(k, 0))
                    for k in ("ok", "rejected", "error", "bad_file"))


def run(root, workers, limit, force):
    root = os.path.abspath(root)
    log_path = root.rstrip("/\\") + ".relogin.csv"
    backup_root = root.rstrip("/\\") + "_backup"
    done = parse_log(log_path)
    targets = iter_targets(root, done, force, limit)
    total = len(targets)
    print("targets: %d (skipped %d already ok)" % (total, sum(1 for s in done.values() if s == "ok")))
    if not total:
        return {}

    pool = CcPool()
    tracker = StopTracker()
    counts = {}
    log_lock = threading.Lock()
    new_log = not os.path.exists(log_path)
    stop_reason = [None]

    log_fh = open(log_path, "a", encoding="utf-8", newline="")
    writer = csv.writer(log_fh)
    if new_log:
        writer.writerow(["path", "status", "rsn", "level", "time"])

    done_n = [0]

    def worker(path):
        if stop_reason[0]:
            return None
        res = process_file(path, root, pool, backup_root)
        with log_lock:
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            writer.writerow([res["rel"], res["status"], res["rsn"], res["level"],
                             time.strftime("%Y-%m-%dT%H:%M:%S")])
            log_fh.flush()
            done_n[0] += 1
            if done_n[0] % 100 == 0:
                print("[%d/%d] %s" % (done_n[0], total, _fmt_summary(counts)))
        reason = tracker.record(res["status"])
        if reason and not stop_reason[0]:
            stop_reason[0] = reason
        return res

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(worker, p) for p in targets]
            for _ in concurrent.futures.as_completed(futures):
                if stop_reason[0]:
                    for f in futures:
                        f.cancel()
    finally:
        log_fh.close()

    if stop_reason[0] == "maintenance":
        print("STOP: rejected %d ครั้งติดกัน — น่าจะเซิร์ฟเวอร์ปิดปรับปรุง (ทุกคำขอ 401). รันซ้ำภายหลังได้" % REJECT_STOP)
    elif stop_reason[0] == "errors":
        print("STOP: error ติดกันมากเกินไป — หยุดไว้ก่อน ตรวจเน็ต/เซิร์ฟเวอร์แล้วรันซ้ำ")
    print("done: %s" % _fmt_summary(counts))
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="โฟลเดอร์ที่มีไฟล์ .xml (รวมโฟลเดอร์ย่อย)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="ทำซ้ำแม้เคย ok แล้ว")
    args = parser.parse_args(argv)
    run(args.folder, args.workers, args.limit, args.force)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: รัน test ทั้งไฟล์ให้ผ่าน**

Run: `python -m pytest tools/tests/test_relogin.py -q`
Expected: PASS ทุกข้อ

- [ ] **Step 5: commit**

```bash
git add tools/relogin.py tools/tests/test_relogin.py
git commit -m "feat(relogin): parallel runner with auto-stop and resumable log"
```

---

## Task 6: .gitignore + ทดสอบกับเซิร์ฟเวอร์จริง

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `tools/relogin.py` (เสร็จแล้ว)
- Produces: การยืนยันว่าเครื่องมือทำงานกับเซิร์ฟเวอร์จริง และไฟล์โทเค็นไม่หลุด git

- [ ] **Step 1: เพิ่ม .gitignore กันไฟล์โทเค็น**

เพิ่มท้าย `.gitignore`:

```gitignore

# Relogin batch: account inputs, backups, and its log all carry live LF_AC.
bot/input/
*_backup/
*.relogin.csv
```

- [ ] **Step 2: ยืนยันว่า git ไม่ track ไฟล์บัญชี**

Run: `git status --porcelain bot/input | head; git check-ignore bot/input/15-3`
Expected: ไม่มีไฟล์ `bot/input/...` ใน output ของ `git status`, และ `git check-ignore` พิมพ์ `bot/input/15-3`

- [ ] **Step 3: เตรียมโฟลเดอร์ทดสอบใน scratchpad (คัดลอก 3 ไฟล์ ไม่แตะต้นฉบับ)**

Run:
```bash
S="C:/Users/Benz/AppData/Local/Temp/claude/d--Programing-ranger-Test-Mitmproxy-Api/2a2eb418-639a-4547-833d-4c8fe36be0b7/scratchpad/relogin_live"
rm -rf "$S"; mkdir -p "$S"
i=0; for f in bot/input/15-3/*.xml; do cp "$f" "$S/"; i=$((i+1)); [ $i -ge 3 ] && break; done
ls "$S"
```
Expected: มีไฟล์ .xml 3 ไฟล์

- [ ] **Step 4: รัน relogin กับโฟลเดอร์ทดสอบ**

Run:
```bash
python tools/relogin.py "C:/Users/Benz/AppData/Local/Temp/claude/d--Programing-ranger-Test-Mitmproxy-Api/2a2eb418-639a-4547-833d-4c8fe36be0b7/scratchpad/relogin_live" --limit 3 --workers 2
```
Expected: `done: ok=3 ...` และมีไฟล์ `..._backup/` กับ `....relogin.csv` เกิดขึ้นข้างโฟลเดอร์

- [ ] **Step 5: ยืนยันโทเค็นใหม่ใช้ได้จริงด้วย /home**

Run:
```bash
python - <<'PY'
import sys, os, glob, html, re
sys.path.insert(0, "tools")
import relogin, rewards
from device_session import decrypt_lfac
S = "C:/Users/Benz/AppData/Local/Temp/claude/d--Programing-ranger-Test-Mitmproxy-Api/2a2eb418-639a-4547-833d-4c8fe36be0b7/scratchpad/relogin_live"
for f in sorted(glob.glob(S + "/*.xml")):
    acct = relogin.read_account(f)
    st, data = rewards.call("LF_AC=" + decrypt_lfac(acct["udid"], acct["enc"]), "/home")
    ok = st == 200 and isinstance(data, dict) and "result" in data
    print(os.path.basename(f), st, "rsn", data["result"]["player"].get("rsn") if ok else data)
PY
```
Expected: ทั้ง 3 ไฟล์ HTTP 200 พร้อม rsn (ตรงกับคอลัมน์ rsn ใน `.relogin.csv`)

- [ ] **Step 6: ยืนยัน backup + resume**

Run:
```bash
S="C:/Users/Benz/AppData/Local/Temp/claude/d--Programing-ranger-Test-Mitmproxy-Api/2a2eb418-639a-4547-833d-4c8fe36be0b7/scratchpad"
ls "$S/relogin_live_backup"           # ต้องมี 3 ไฟล์ต้นฉบับ
python tools/relogin.py "$S/relogin_live"   # รันซ้ำ
```
Expected: รอบสอง `targets: 0 (skipped 3 already ok)` — ข้ามครบ

- [ ] **Step 7: commit**

```bash
git add .gitignore
git commit -m "chore: gitignore relogin account inputs, backups, and logs"
```

---

## บันทึกหลังทำเสร็จ (ให้ผู้รัน)

- รันจริงกับ `bot/input/15-3`: เริ่มด้วย `--limit 20` ก่อน แล้วค่อยปล่อยทั้งโฟลเดอร์ด้วย `--workers 4`
- ถ้าเจอ `STOP: maintenance` ให้รอแล้วรันคำสั่งเดิมซ้ำ (จะ resume เอง)
- ถ้าต่ออายุแล้วนำไปใช้ผ่าน bot อัปเดต memory `lgrgs-headless-relogin-from-xml` ด้วยผลรันจริง
