# แผนลงมือ: ตรวจและสลับ App-Version / URL prefix อัตโนมัติ

> **สำหรับ agent ที่ลงมือ:** ต้องใช้ skill `superpowers:subagent-driven-development`
> (แนะนำ) หรือ `superpowers:executing-plans` ทำทีละ task ทุกขั้นเป็น checkbox (`- [ ]`)

**Goal:** ให้ทุกคำขอที่ยิง `rangers-api.line-apps.com` ได้ `App-Version`/`User-Agent` และ URL prefix
จากโมดูลเดียว ที่เรียนรู้จากคำตอบของเซิร์ฟเวอร์ สลับเองเมื่อถูกปฏิเสธ และจำลงไฟล์

**Architecture:** `tools/client_version.py` ใหม่ถือสถานะ (เวอร์ชันหลัก, prefix, pin ต่อ route,
known_good) และฟังก์ชัน `request(path, send)` ที่ผู้เรียกส่งตัวยิงของตัวเองเข้ามา — โมดูลนี้ไม่รู้จัก
http.client/urllib · จุดยิงทั้ง 6 จุดเปลี่ยนเป็นส่ง `send(prefix, app_version)` แทนการฮาร์ดโค้ด ·
engine หยุดทั้งตัวเมื่อได้ `VersionUnavailable`

**Tech Stack:** Python 3.11 stdlib (`json` `threading` `re`) · pytest · PyArmor + PyInstaller

**Spec:** [`../specs/2026-09-24-client-version-autoswitch-design.md`](../specs/2026-09-24-client-version-autoswitch-design.md)

**จุดเริ่ม:** branch `feat/engine-rewrite` @ `0206e33` (spec) — เทสต์ทั้งชุดผ่าน 346 ตัว

---

## Global Constraints

ใช้กับ **ทุก task**

1. **ตอนทุกอย่างปกติ ยิงคำขอจริงครั้งเดียวพอดี** ห้ามมี oracle หรือการยิงซ้ำใด ๆ บนเส้นทาง 200
   Login mode ทำ 181 บัญชี/นาทีที่ 128 เธรดและชนเพดาน 80 req/s ของเราเองอยู่แล้ว
2. **401 นับเป็นเรื่องเวอร์ชันเฉพาะเมื่อ `(route, version)` ยังไม่เคยได้ 200 ในโปรเซสนี้** และยังไม่อยู่ใน
   `not_version` — Login mode เจอโทเคนตายหลายพันครั้งต่อรัน ต้องเสียคำขอเพิ่ม 0 ครั้ง
3. สัญญาณ: `400 + errorCode 119801` = เวอร์ชันที่เซิร์ฟเวอร์ไม่รู้จัก · `404 + errorCode 400` = route ไม่มี
   · oracle = `GET {prefix}/home` + `Cookie: LF_AC=0` → 401 = รู้จัก/มีอยู่, 119801 = ไม่รู้จัก, 404 = ไม่มี
4. **URL prefix ย้ายเฉพาะเมื่อ prefix ปัจจุบันพัง** (oracle ของ prefix ปัจจุบันไม่ตอบ 401) — ผู้ใช้เลือกเอง
5. `VersionUnavailable` **เป็น `Exception` ห้ามเป็น `SystemExit`** (บทเรียน `abd580e`: SystemExit
   ทำให้เธรดตายเงียบ) engine หยุด ไฟล์ที่ค้างอยู่ใน `execute/` ห้ามถูกย้ายไป `login failed/`
6. ค่าตั้งต้น: `app_version "12.3.0"` · `api_prefix "/v12.3"` · `route_pins {"/signup/platform": "12.2.0"}`
   · `known_good ["12.2.0", "12.3.0", "12.3.2", "12.4.0"]` · history เก็บ 20 รายการ
7. ไฟล์: engine ใช้ `<root>/src/api_version.json` · CLI ใช้ env `LGRGS_VERSION_FILE` หรือ
   `ratelimit.rl_dir()/api_version.json` · ไฟล์ไม่มี/เสีย/เขียนไม่ได้ **ห้ามทำให้ล้ม**
8. `client_version` คือข้อยกเว้นเดียวที่ถือสถานะระดับโมดูลได้ (เวอร์ชันเป็นของทั้งโปรเซสโดยธรรมชาติ)
   และทุกการแก้สถานะต้องอยู่ใต้ `self._lock`
9. **เทสต์ห้ามยิงเซิร์ฟเวอร์จริง** — `conftest.py` ที่รากใส่ oracle ที่ล้มทันทีให้ทุกเทสต์ เทสต์ของ
   `client_version` ต้องส่ง `oracle=` เองทุกครั้ง
10. **ตัวปลอมต้องขาดสิ่งที่กำลังพิสูจน์** และ **เทสต์ต้องยืนยันตัวตน ไม่ใช่จำนวน** (นับจำนวนได้ แต่ต้อง
    ยืนยันด้วยว่าเป็นเวอร์ชัน/prefix ไหน)
11. **รักษา line ending ของไฟล์เดิม** — CRLF: `tools/new_account.py` `tools/rangers_api.py`
    `tools/relogin.py` `tools/pull_roster.py` `tools/device_session.py` `bot/build.bat` ·
    LF: `tools/gacha.py` `bot/engine/*.py` `bot/engine_main.py` `bot/BotLineRanger.spec` และเทสต์
    ใช้ Edit tool (รักษาให้เอง) ถ้าเขียนด้วยสคริปต์ให้เช็กด้วย
    `python -c "d=open(P,'rb').read(); print(d.count(b'\r\n'), d.count(b'\n')-d.count(b'\r\n'))"`
    และ `git diff --stat` ต้องไม่ขึ้นว่าแก้ทั้งไฟล์
12. **ห้าม `git add -A`** — `bot/input/` `bot/output/` มีไฟล์บัญชีจริงหลายหมื่นไฟล์ add เฉพาะไฟล์ที่ task ระบุ
13. คำสั่งเทสต์: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q` ทุก task ต้องจบด้วยเขียวทั้งชุด
14. ท้าย commit message ทุกอัน: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

---

## โครงไฟล์

| ไฟล์ | หน้าที่ | task |
|---|---|---|
| `tools/client_version.py` (ใหม่) | เลือก/เรียนรู้/จำ App-Version และ prefix | 1, 2 |
| `conftest.py` (ใหม่, รากโปรเจกต์) | ให้ทุกเทสต์ได้อินสแตนซ์แยก `learn=False` + oracle ที่ห้ามถูกเรียก | 1 |
| `tools/tests/test_client_version.py` (ใหม่) | ที่เก็บ, header, route, เส้นทางปกติ | 1 |
| `tools/tests/test_client_version_learning.py` (ใหม่) | กฎ 401, สำรวจเวอร์ชัน/prefix, single-flight | 2 |
| `tools/rangers_api.py` | `call` → `_send_raw` + `request`, ลงทะเบียน oracle | 3 |
| `tools/gacha.py` | `call` ส่งต่อให้ `rangers_api.call`, path ไม่มี prefix | 3 |
| `tools/pull_roster.py` `tools/device_session.py` | ยิงผ่าน `request` | 3 |
| `bot/build.bat` `bot/BotLineRanger.spec` | บันเดิล `client_version` แบบเข้ารหัส | 3 |
| `tools/tests/test_client_version_wiring.py` (ใหม่) | จุดยิงกลุ่ม business | 3 |
| `tools/tests/test_build_bundles_tools.py` (ใหม่) | ทุก tool ที่ pyarmor เข้ารหัสต้องอยู่ใน hiddenimports | 3 |
| `tools/tests/test_gacha_cache.py` `tools/tests/test_gacha_draw.py` | path ในตัวปลอมตัด `/v12.3` ออก | 3 |
| `tools/new_account.py` `tools/relogin.py` | signup/login ผ่าน `request` ลบค่าฮาร์ดโค้ด | 4 |
| `tools/tests/test_client_version_login_signup.py` (ใหม่) | signup/login + ปลายทางเรียนรู้จริง | 4 |
| `tools/tests/test_no_hardcoded_client_version.py` (ใหม่) | AST: ห้ามมีเวอร์ชัน/prefix ฝังในสตริง | 4 |
| `bot/engine/flows.py` `bot/engine/pool.py` `bot/engine_main.py` | ปล่อยผ่าน/หยุด engine/ตั้งค่า+log | 5 |
| `bot/tests/test_version_unavailable_stops_engine.py` (ใหม่) | flows + pool + engine_main | 5 |

---

### Task 1: `client_version` — ที่เก็บ, header, route และเส้นทางปกติ

**Files:**
- Create: `tools/client_version.py`
- Create: `conftest.py` (รากโปรเจกต์ ข้าง `pytest.ini`)
- Test: `tools/tests/test_client_version.py`

**Interfaces:**
- Produces (task ถัดไปใช้):
  - `class VersionUnavailable(Exception)`
  - `headers(app_version: str) -> dict` คืน `{"App-Version": "LGRGS/<v>;android/12", "User-Agent": "LGRGS/<v> (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)"}`
  - `route_of(path: str) -> str` · `classify(status, parsed) -> str` คืนหนึ่งใน `"ok" "version_unknown" "route_missing" "unauthorized" "other"`
  - `class ClientVersion(path: str, oracle=None, learn: bool = True, clock=time.monotonic)` มีเมธอด
    `request(path, send, pinned_prefix=None)`, `current() -> (prefix, app_version)`, `describe() -> str`,
    `on_switch(callback)`, attribute `path`, `app_version`, `api_prefix`, `route_pins`, `known_good`, `history`
  - ระดับโมดูล: `request` `current` `describe` `on_switch` `configure(path=None, learn=True)` `instance()`
    `set_oracle(fn)` `default_path()` และค่าคงที่ `ORACLE_PATH = "/home"` `ORACLE_COOKIE = "LF_AC=0"`
  - `send(prefix, app_version)` ต้องคืน tuple ที่ `[0]` คือ HTTP status และ `[1]` คือ body ที่ parse แล้ว
    `request` คืน tuple นั้นทั้งก้อนไม่แตะ (ผู้เรียกจึงแนบ cookies/raw ต่อท้ายได้)

- [ ] **Step 1: เขียนเทสต์ที่ล้มก่อน** — `tools/tests/test_client_version.py`

```python
"""client_version: storage, headers, routes and the plain path (no learning yet).

Design: docs/superpowers/specs/2026-09-24-client-version-autoswitch-design.md
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pytest

import client_version as cv


class Send:
    """A send() that records what it was asked to send and replays scripted answers."""

    def __init__(self, *answers):
        self.answers = list(answers) or [(200, {"result": {}})]
        self.sent = []

    def __call__(self, prefix, app_version):
        self.sent.append((prefix, app_version))
        return self.answers[min(len(self.sent), len(self.answers)) - 1]


def _cv(tmp_path, **state):
    path = tmp_path / "api_version.json"
    if state:
        path.write_text(json.dumps(state), encoding="utf-8")
    return cv.ClientVersion(str(path)), path


def test_version_unavailable_is_an_ordinary_exception_not_a_systemexit():
    # SystemExit slips past `except Exception` and threading drops it silently (abd580e).
    assert issubclass(cv.VersionUnavailable, Exception)
    assert not issubclass(cv.VersionUnavailable, SystemExit)


def test_headers_put_the_version_in_both_app_version_and_user_agent():
    h = cv.headers("12.2.0")
    assert h == {
        "App-Version": "LGRGS/12.2.0;android/12",
        "User-Agent": "LGRGS/12.2.0 (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)",
    }


@pytest.mark.parametrize("path,route", [
    ("/home", "/home"),
    ("/signup/platform", "/signup/platform"),
    ("/stage/enter/st01", "/stage/enter/*"),
    ("/stage/save/1234/st02?reqId=99", "/stage/save/*/*"),
    ("/mission/sevendays/receive/reward/123/attendance/1",
     "/mission/sevendays/receive/reward/*/attendance/*"),
])
def test_route_of_folds_every_numbered_segment_and_drops_the_query(path, route):
    assert cv.route_of(path) == route


@pytest.mark.parametrize("status,body,kind", [
    (200, {"result": {}}, "ok"),
    (400, {"errorCode": 119801, "extras": {"version": "11.9.0"}}, "version_unknown"),
    (400, {"errorCode": 429}, "other"),          # the per-account min-gap, not a version answer
    (404, {"errorCode": 400, "errorMessage": "/v12.4/home"}, "route_missing"),
    (404, "<html>not found</html>", "other"),
    (401, {"errorCode": 401}, "unauthorized"),
    (500, {"errorCode": 500}, "other"),
])
def test_classify(status, body, kind):
    assert cv.classify(status, body) == kind


def test_a_missing_file_gives_the_defaults_and_is_written_so_a_human_can_see_it(tmp_path):
    c, path = _cv(tmp_path)
    assert c.current() == ("/v12.3", "12.3.0")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["app_version"] == "12.3.0"
    assert saved["api_prefix"] == "/v12.3"
    assert saved["route_pins"] == {"/signup/platform": "12.2.0"}
    assert saved["known_good"] == ["12.2.0", "12.3.0", "12.3.2", "12.4.0"]


def test_a_corrupt_file_gives_the_defaults_without_raising(tmp_path):
    path = tmp_path / "api_version.json"
    path.write_text("{not json", encoding="utf-8")
    c = cv.ClientVersion(str(path))
    assert c.current() == ("/v12.3", "12.3.0")


def test_bad_fields_fall_back_one_by_one_and_good_ones_are_kept(tmp_path):
    c, _ = _cv(tmp_path, app_version="twelve", api_prefix="/v12.2",
               route_pins={"/signup/platform": "12.2.0", "/x": "junk"})
    assert c.current() == ("/v12.2", "12.3.0")
    assert c.route_pins == {"/signup/platform": "12.2.0"}


def test_an_empty_pin_table_in_the_file_means_no_pins(tmp_path):
    c, _ = _cv(tmp_path, route_pins={})
    send = Send()
    c.request("/signup/platform", send)
    assert send.sent == [("/v12.3", "12.3.0")]


def test_the_file_decides_what_gets_sent(tmp_path):
    c, _ = _cv(tmp_path, app_version="12.3.2", api_prefix="/v12.2")
    send = Send()
    c.request("/home", send)
    assert send.sent == [("/v12.2", "12.3.2")]


def test_a_route_pin_overrides_the_main_version_for_that_route_only(tmp_path):
    c, _ = _cv(tmp_path)
    signup, home = Send(), Send()
    c.request("/signup/platform", signup)
    c.request("/home", home)
    assert signup.sent == [("/v12.3", "12.2.0")]
    assert home.sent == [("/v12.3", "12.3.0")]


def test_a_normal_answer_costs_exactly_one_request_and_comes_back_whole(tmp_path):
    c, _ = _cv(tmp_path)
    send = Send((200, {"result": {"x": 1}}, ["LF_AC=abc"]))
    assert c.request("/home", send) == (200, {"result": {"x": 1}}, ["LF_AC=abc"])
    assert len(send.sent) == 1


def test_a_pinned_prefix_is_sent_as_given(tmp_path):
    c, _ = _cv(tmp_path)
    send = Send()
    c.request("/home", send, pinned_prefix="/v12.2")
    assert send.sent == [("/v12.2", "12.3.0")]


def test_a_path_that_still_carries_its_prefix_is_refused(tmp_path):
    c, _ = _cv(tmp_path)
    with pytest.raises(ValueError):
        c.request("/v12.3/home", Send())


def test_a_new_version_that_answers_200_joins_known_good_and_is_saved(tmp_path):
    c, path = _cv(tmp_path, app_version="12.3.5")
    c.request("/home", Send())
    assert "12.3.5" in c.known_good
    assert "12.3.5" in json.loads(path.read_text(encoding="utf-8"))["known_good"]


def test_describe_is_the_engine_start_line(tmp_path):
    c, _ = _cv(tmp_path)
    assert c.describe() == "api version: /v12.3 + 12.3.0 (pins: /signup/platform=12.2.0)"


def test_a_file_that_cannot_be_written_does_not_raise(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    c = cv.ClientVersion(str(blocker / "api_version.json"))
    assert c.current() == ("/v12.3", "12.3.0")          # tried to create the file, could not


def test_configure_points_the_module_functions_at_that_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "_DEFAULT", None)
    target = tmp_path / "src" / "api_version.json"
    cv.configure(str(target))
    assert cv.instance().path == str(target)
    send = Send()
    cv.request("/home", send)
    assert send.sent == [("/v12.3", "12.3.0")]
    assert target.exists()


def test_default_path_honours_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("LGRGS_VERSION_FILE", str(tmp_path / "v.json"))
    assert cv.default_path() == str(tmp_path / "v.json")
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version.py -q`
Expected: ERROR ตอน collect ด้วย `ModuleNotFoundError: No module named 'client_version'`

- [ ] **Step 3: สร้าง `tools/client_version.py`** (LF line endings)

```python
r"""App-Version and URL prefix for every rangers-api call - chosen here, learned from the server.

On 2026-09-24 /signup/platform started answering 401 to App-Version 12.3.0 and GenID made zero
accounts with nothing in any log to say why; 12.2.0 was found by hand (commit abd580e). The
next game update will do the same to some other value. So no call site hardcodes a version or
a /v12.x prefix any more: each hands request() a send(prefix, app_version) function, and this
module is the one place that decides what those are - and notices when the server refuses them.

Design: docs/superpowers/specs/2026-09-24-client-version-autoswitch-design.md
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

import ratelimit

DEFAULT_APP_VERSION = "12.3.0"
DEFAULT_PREFIX = "/v12.3"
# /signup/platform refuses 12.3.0 and 12.4.0 with 401 and takes 12.2.0 (measured 2026-09-24,
# one fresh pending guest per cell). Seeded so a fresh install starts right instead of spending
# three signup attempts rediscovering it - the 401 rule would find it anyway.
DEFAULT_PINS = {"/signup/platform": "12.2.0"}
# Every App-Version that answered 200 on /v12.3/home on 2026-09-24.
DEFAULT_KNOWN_GOOD = ("12.2.0", "12.3.0", "12.3.2", "12.4.0")
HISTORY_KEEP = 20
UNKNOWN_VERSION = 119801    # errorCode: the server does not know this build at all
ORACLE_PATH = "/home"
ORACLE_COOKIE = "LF_AC=0"   # deliberately invalid: the server checks the version BEFORE the token
DEAD_COOLDOWN = 30.0        # seconds to fail fast after a sweep found nothing (used by learning)

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PREFIX_RE = re.compile(r"^/v\d+\.\d+$")
_PREFIXED_PATH_RE = re.compile(r"^/v\d")


class VersionUnavailable(Exception):
    """No App-Version or URL prefix the server accepts could be found.

    A plain Exception on purpose, never SystemExit: SystemExit slips past `except Exception` and
    threading.excepthook drops it without a word (commit abd580e). The engine catches this by
    name and stops the run, instead of failing - and moving - every account one by one.
    """


def headers(app_version: str) -> dict:
    return {
        "App-Version": "LGRGS/%s;android/12" % app_version,
        "User-Agent": "LGRGS/%s (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)" % app_version,
    }


def route_of(path: str) -> str:
    """'/stage/save/1234/st02?reqId=9' -> '/stage/save/*/*': fine enough to tell signup from
    login, coarse enough not to grow one entry per stage number, battleSn or reward seq."""
    bare = path.split("?", 1)[0]
    return "/".join("*" if any(ch.isdigit() for ch in seg) else seg for seg in bare.split("/"))


def classify(status, parsed) -> str:
    code = parsed.get("errorCode") if isinstance(parsed, dict) else None
    if status == 200:
        return "ok"
    if status == 400 and code == UNKNOWN_VERSION:
        return "version_unknown"
    if status == 404 and code == 400:
        return "route_missing"
    if status == 401:
        return "unauthorized"
    return "other"


class ClientVersion:
    def __init__(self, path: str, oracle=None, learn: bool = True, clock=time.monotonic):
        self.path = path
        self.learn = learn
        self._oracle_fn = oracle
        self._clock = clock
        self._lock = threading.RLock()
        self._loaded = False
        self._listeners = []
        self.app_version = DEFAULT_APP_VERSION
        self.api_prefix = DEFAULT_PREFIX
        self.route_pins = dict(DEFAULT_PINS)
        self.known_good = list(DEFAULT_KNOWN_GOOD)
        self.history = []
        self._proven = set()          # (route, version) that answered 200 in this process
        self._not_version = set()     # (route, version) whose 401 sweep found nothing
        self._generation = 0          # bumped on every change - single-flight for sweeps
        self._dead_until = 0.0
        self._dead_reason = ""

    # --- storage ------------------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except FileNotFoundError:
                self._save()          # make the file exist so a human can read and edit it
                return
            except (OSError, ValueError):
                return                # unreadable: run on the defaults, never crash over it
            if not isinstance(data, dict):
                return
            version = data.get("app_version")
            if isinstance(version, str) and _VERSION_RE.match(version):
                self.app_version = version
            prefix = data.get("api_prefix")
            if isinstance(prefix, str) and _PREFIX_RE.match(prefix):
                self.api_prefix = prefix
            pins = data.get("route_pins")
            if isinstance(pins, dict):
                self.route_pins = {r: v for r, v in pins.items()
                                   if isinstance(r, str) and isinstance(v, str) and _VERSION_RE.match(v)}
            known = data.get("known_good")
            if isinstance(known, list):
                merged = [v for v in known if isinstance(v, str) and _VERSION_RE.match(v)]
                merged += [v for v in DEFAULT_KNOWN_GOOD if v not in merged]
                self.known_good = merged
            history = data.get("history")
            if isinstance(history, list):
                self.history = [h for h in history if isinstance(h, dict)][-HISTORY_KEEP:]

    def _save(self) -> None:
        data = {"app_version": self.app_version, "api_prefix": self.api_prefix,
                "route_pins": dict(self.route_pins), "known_good": list(self.known_good),
                "history": self.history[-HISTORY_KEEP:]}
        tmp = "%s.%d.%d.tmp" % (self.path, os.getpid(), threading.get_ident())
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            for _attempt in range(5):
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:       # Windows: a reader has it open this instant
                    time.sleep(0.05)
            os.replace(tmp, self.path)
        except OSError as err:
            # Losing the file costs one rediscovery next run; crashing here would cost the run.
            print("client_version: could not save %s: %s" % (self.path, err), file=sys.stderr)
            try:
                os.remove(tmp)
            except OSError:
                pass

    # --- what to send -------------------------------------------------------------------

    def _resolve(self, route, pinned_prefix):
        version = self.route_pins.get(route, self.app_version)
        return (pinned_prefix or self.api_prefix), version, self._generation

    def _mark_ok(self, route, version) -> None:
        if (route, version) in self._proven:
            return
        with self._lock:
            self._proven.add((route, version))
            if version not in self.known_good:
                self.known_good.append(version)
                self._save()

    def request(self, path, send, pinned_prefix=None):
        """Send once with the values this route should use and return what send() returned.

        send(prefix, app_version) must return a tuple whose [0] is the HTTP status and [1] the
        parsed body. Pass `path` WITHOUT its /v12.x prefix - adding it is this module's job.
        """
        if _PREFIXED_PATH_RE.match(path):
            raise ValueError("pass the path without its /v12.x prefix: %r" % (path,))
        self._load()
        route = route_of(path)
        with self._lock:
            prefix, version, _generation = self._resolve(route, pinned_prefix)
        result = send(prefix, version)
        if classify(result[0], result[1]) == "ok":
            self._mark_ok(route, version)
        return result

    # --- reporting ----------------------------------------------------------------------

    def current(self):
        self._load()
        with self._lock:
            return self.api_prefix, self.app_version

    def describe(self) -> str:
        self._load()
        with self._lock:
            pins = ", ".join("%s=%s" % kv for kv in sorted(self.route_pins.items())) or "none"
            return "api version: %s + %s (pins: %s)" % (self.api_prefix, self.app_version, pins)

    def on_switch(self, callback) -> None:
        self._listeners.append(callback)


# --- the process-wide instance ------------------------------------------------------------

_DEFAULT = None
_DEFAULT_LOCK = threading.Lock()
_ORACLE = None


def default_path() -> str:
    return os.environ.get("LGRGS_VERSION_FILE") or os.path.join(ratelimit.rl_dir(), "api_version.json")


def set_oracle(fn) -> None:
    """rangers_api registers its transport here on import (it cannot be imported from this
    module: rangers_api imports client_version)."""
    global _ORACLE
    _ORACLE = fn


def _registered_oracle():
    if _ORACLE is None:
        import rangers_api  # noqa: F401 - registers rangers_api._oracle through set_oracle()
    return _ORACLE


def configure(path: str | None = None, learn: bool = True) -> ClientVersion:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = ClientVersion(path or default_path(), learn=learn)
        return _DEFAULT


def instance() -> ClientVersion:
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = ClientVersion(default_path())
    return _DEFAULT


def request(path, send, pinned_prefix=None):
    return instance().request(path, send, pinned_prefix)


def current():
    return instance().current()


def describe() -> str:
    return instance().describe()


def on_switch(callback) -> None:
    instance().on_switch(callback)
```

- [ ] **Step 4: สร้าง `conftest.py` ที่รากโปรเจกต์** (LF)

```python
"""Repo-wide pytest setup.

client_version keeps its state in a JSON file and, with learning on, re-sends a refused request
with other App-Versions and asks an "oracle" - a REAL GET /home - when the server says a
version or route is unknown. No test written before it existed expects any of that: a fake that
answers 401 would suddenly see extra calls, and a fake that answers 404 would reach the network.
So every test gets its own non-learning instance in its own tmp_path, and an oracle that fails
loudly if anything reaches it. client_version's own tests build their instances explicitly.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import client_version  # noqa: E402


def _no_network_oracle(prefix, app_version):
    raise AssertionError("a test reached the real version oracle (%s, %s)" % (prefix, app_version))


@pytest.fixture(autouse=True)
def _client_version_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(client_version, "_DEFAULT",
                        client_version.ClientVersion(str(tmp_path / "api_version.json"), learn=False))
    monkeypatch.setattr(client_version, "_ORACLE", _no_network_oracle)
    yield
```

- [ ] **Step 5: รันเทสต์ของ task นี้**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version.py -q`
Expected: PASS ทั้งหมด (28 ตัว รวม parametrize)

- [ ] **Step 6: รันทั้งชุด**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q`
Expected: `374 passed` (346 เดิม + 28 ใหม่) — ถ้าจำนวนต่างให้รายงานตัวเลขจริง ห้ามปรับเทสต์ให้ตรง

- [ ] **Step 7: Commit**

```bash
git add tools/client_version.py conftest.py tools/tests/test_client_version.py
git commit -m "feat(client-version): one place that decides App-Version and URL prefix

Storage in a JSON file (defaults when missing or corrupt, never a crash on write),
headers(), route_of(), classify() and a plain request() that sends once with the route's
pinned or main version. No learning yet - that is the next commit.

conftest.py gives every test its own non-learning instance and an oracle that fails loudly,
so no pre-existing fake can trigger a re-send or reach the network.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `client_version` — การเรียนรู้ (กฎ 401, สำรวจเวอร์ชัน/prefix, single-flight)

**Files:**
- Modify: `tools/client_version.py`
- Test: `tools/tests/test_client_version_learning.py`

**Interfaces:**
- Consumes: ทุกอย่างจาก Task 1
- Produces: `ClientVersion.request` ที่เรียนรู้เมื่อ `learn=True` (ค่าตั้งต้น) · `version_candidates(v)` ·
  `prefix_candidates(p)` · ข้อความ `on_switch` สามรูปแบบตาม spec ข้อ 6:
  `App-Version /signup/platform: 12.3.0 -> 12.2.0 (401 on a never-proven route)` ·
  `App-Version: 12.1.0 -> 12.4.0 (server no longer knows 12.1.0: 119801)` ·
  `API prefix: /v12.3 -> /v12.5 (/v12.3 no longer answers)`

- [ ] **Step 1: เขียนเทสต์ที่ล้มก่อน** — `tools/tests/test_client_version_learning.py`

```python
"""client_version learning: the 401 rule, version and prefix sweeps, single-flight.

FakeServer answers exactly like rangers-api did on 2026-09-24 (spec section 2): it checks the
version before anything else, then the prefix, then the token. Each test's fake LACKS the thing
being proven - e.g. the 401-rule test uses a server where signup refuses 12.3.0 but /home
takes it, so a module that treated every 401 alike could not pass both halves.
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pytest

import client_version as cv


class FakeServer:
    def __init__(self, known=("12.2.0", "12.3.0", "12.3.2", "12.4.0"), signup_ok=("12.2.0",),
                 prefixes=("/v12.2", "/v12.3"), token_ok=True, missing_routes=(), oracle_delay=0.0):
        self.known = set(known)
        self.signup_ok = set(signup_ok)
        self.prefixes = set(prefixes)
        self.token_ok = token_ok
        self.missing_routes = set(missing_routes)
        self.oracle_delay = oracle_delay
        self.real = []
        self.oracle_calls = []
        self._lock = threading.Lock()

    def _answer(self, prefix, version, path, fake_token):
        if version not in self.known:
            return 400, {"errorCode": 119801, "extras": {"version": version}}
        if prefix not in self.prefixes or path in self.missing_routes:
            return 404, {"errorCode": 400, "errorMessage": prefix + path}
        if fake_token:
            return 401, {"errorCode": 401}
        if path == "/signup/platform":
            return (200, {"result": {"isNew": True}}) if version in self.signup_ok else (401, {"errorCode": 401})
        if not self.token_ok:
            return 401, {"errorCode": 401}
        return 200, {"result": {}}

    def send_for(self, path):
        def send(prefix, version):
            with self._lock:
                self.real.append((prefix, version))
            return self._answer(prefix, version, path, fake_token=False)
        return send

    def oracle(self, prefix, version):
        with self._lock:
            self.oracle_calls.append((prefix, version))
        if self.oracle_delay:
            time.sleep(self.oracle_delay)
        return self._answer(prefix, version, cv.ORACLE_PATH, fake_token=True)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, server, learn=True, clock=None, **state):
    path = tmp_path / "api_version.json"
    if state:
        path.write_text(json.dumps(state), encoding="utf-8")
    c = cv.ClientVersion(str(path), oracle=server.oracle, learn=learn,
                         clock=clock or time.monotonic)
    messages = []
    c.on_switch(messages.append)
    return c, path, messages


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_normal_answer_costs_one_request_and_no_oracle(tmp_path):
    server = FakeServer()
    c, _, _ = make(tmp_path, server)
    assert c.request("/home", server.send_for("/home"))[0] == 200
    assert server.real == [("/v12.3", "12.3.0")]
    assert server.oracle_calls == []


def test_119801_moves_the_main_version_to_the_newest_build_the_server_knows(tmp_path):
    server = FakeServer()
    c, path, messages = make(tmp_path, server, app_version="12.1.0")
    broken = []
    c.on_switch(lambda msg: broken.append(1 / 0))     # a listener that raises must not matter

    assert c.request("/home", server.send_for("/home"))[0] == 200
    assert server.real == [("/v12.3", "12.1.0"), ("/v12.3", "12.4.0")]
    assert server.oracle_calls == [("/v12.3", "13.0.0"), ("/v12.3", "12.4.0")]
    assert c.app_version == "12.4.0"
    assert saved(path)["app_version"] == "12.4.0"
    assert messages == ["App-Version: 12.1.0 -> 12.4.0 (server no longer knows 12.1.0: 119801)"]
    assert saved(path)["history"][-1]["what"] == "app_version"


def test_signup_refusing_the_main_version_gets_a_pin_of_its_own_and_it_is_saved(tmp_path):
    server = FakeServer()
    c, path, messages = make(tmp_path, server, route_pins={})
    send = server.send_for("/signup/platform")

    assert c.request("/signup/platform", send)[0] == 200
    assert server.real == [("/v12.3", "12.3.0"), ("/v12.3", "12.4.0"),
                           ("/v12.3", "12.3.2"), ("/v12.3", "12.2.0")]
    assert c.route_pins == {"/signup/platform": "12.2.0"}
    assert saved(path)["route_pins"] == {"/signup/platform": "12.2.0"}
    assert messages == ["App-Version /signup/platform: 12.3.0 -> 12.2.0 (401 on a never-proven route)"]
    assert server.oracle_calls == []

    server.real.clear()
    c.request("/signup/platform", send)
    assert server.real == [("/v12.3", "12.2.0")]


def test_a_401_on_a_route_already_proven_is_a_dead_token_and_costs_nothing_more(tmp_path):
    server = FakeServer()
    c, _, messages = make(tmp_path, server)
    c.request("/home", server.send_for("/home"))
    server.token_ok = False
    assert c.request("/home", server.send_for("/home"))[0] == 401
    assert server.real == [("/v12.3", "12.3.0"), ("/v12.3", "12.3.0")]
    assert server.oracle_calls == [] and messages == []


def test_a_dead_token_on_a_never_proven_route_is_swept_once_then_left_alone(tmp_path):
    server = FakeServer(token_ok=False)
    c, _, messages = make(tmp_path, server)
    send = server.send_for("/mission/list")
    assert c.request("/mission/list", send)[0] == 401
    assert server.real == [("/v12.3", "12.3.0"), ("/v12.3", "12.4.0"),
                           ("/v12.3", "12.3.2"), ("/v12.3", "12.2.0")]
    assert c.route_pins == {"/signup/platform": "12.2.0"} and messages == []

    server.real.clear()
    assert c.request("/mission/list", send)[0] == 401
    assert server.real == [("/v12.3", "12.3.0")]


def test_a_missing_endpoint_under_a_live_prefix_is_not_a_reason_to_move(tmp_path):
    server = FakeServer(missing_routes={"/event/old"})
    c, _, messages = make(tmp_path, server)
    assert c.request("/event/old", server.send_for("/event/old"))[0] == 404
    assert server.oracle_calls == [("/v12.3", "12.3.0")]
    assert c.api_prefix == "/v12.3" and messages == []


def test_a_dead_prefix_moves_to_the_newest_one_that_answers(tmp_path):
    server = FakeServer(prefixes={"/v12.2", "/v12.5"})
    c, path, messages = make(tmp_path, server)
    assert c.request("/home", server.send_for("/home"))[0] == 200
    assert server.oracle_calls == [("/v12.3", "12.3.0"), ("/v13.0", "12.3.0"),
                                   ("/v12.6", "12.3.0"), ("/v12.5", "12.3.0")]
    assert server.real[-1] == ("/v12.5", "12.3.0")
    assert c.api_prefix == "/v12.5" and saved(path)["api_prefix"] == "/v12.5"
    assert messages == ["API prefix: /v12.3 -> /v12.5 (/v12.3 no longer answers)"]


def test_a_pinned_prefix_never_moves(tmp_path):
    server = FakeServer(prefixes={"/v12.5"})
    c, _, _ = make(tmp_path, server)
    assert c.request("/home", server.send_for("/home"), pinned_prefix="/v12.3")[0] == 404
    assert server.oracle_calls == [] and c.api_prefix == "/v12.3"


def test_nothing_known_raises_then_fails_fast_until_the_cooldown_passes(tmp_path):
    server = FakeServer(known=())
    clock = Clock()
    c, _, _ = make(tmp_path, server, clock=clock)
    with pytest.raises(cv.VersionUnavailable):
        c.request("/home", server.send_for("/home"))
    real, asked = len(server.real), len(server.oracle_calls)

    with pytest.raises(cv.VersionUnavailable):
        c.request("/home", server.send_for("/home"))
    assert (len(server.real), len(server.oracle_calls)) == (real, asked)

    clock.t += cv.DEAD_COOLDOWN + 1
    server.known = {"12.3.0"}
    assert c.request("/home", server.send_for("/home"))[0] == 200


def test_32_threads_hitting_119801_together_share_one_sweep(tmp_path):
    server = FakeServer(oracle_delay=0.02)
    c, _, messages = make(tmp_path, server, app_version="12.1.0")
    start = threading.Barrier(32)
    statuses = []

    def worker():
        start.wait(timeout=5)
        statuses.append(c.request("/home", server.send_for("/home"))[0])

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads)
    assert statuses == [200] * 32
    assert server.oracle_calls == [("/v12.3", "13.0.0"), ("/v12.3", "12.4.0")]
    assert len(messages) == 1


def test_a_pin_the_server_no_longer_knows_gives_way_to_the_main_version(tmp_path):
    server = FakeServer(known={"12.3.0", "12.4.0"}, signup_ok={"12.3.0"})
    c, path, messages = make(tmp_path, server)
    assert c.request("/signup/platform", server.send_for("/signup/platform"))[0] == 200
    assert server.real == [("/v12.3", "12.2.0"), ("/v12.3", "12.3.0")]
    assert c.route_pins == {} and "12.2.0" not in c.known_good
    assert server.oracle_calls == []
    assert messages == ["App-Version /signup/platform: 12.2.0 -> 12.3.0 (server no longer knows 12.2.0: 119801)"]


def test_an_oracle_network_error_is_an_ordinary_failure_not_version_unavailable(tmp_path):
    server = FakeServer()

    def down(prefix, version):
        raise ConnectionError("proxy dropped")

    path = tmp_path / "api_version.json"
    path.write_text(json.dumps({"app_version": "12.1.0"}), encoding="utf-8")
    c = cv.ClientVersion(str(path), oracle=down)
    with pytest.raises(ConnectionError):
        c.request("/home", server.send_for("/home"))
    assert c.app_version == "12.1.0"
    with pytest.raises(ConnectionError):          # not "dead": the next call sweeps again
        c.request("/home", server.send_for("/home"))


def test_an_oracle_5xx_is_inconclusive_not_version_unavailable(tmp_path):
    server = FakeServer()
    path = tmp_path / "api_version.json"
    path.write_text(json.dumps({"app_version": "12.1.0"}), encoding="utf-8")
    c = cv.ClientVersion(str(path), oracle=lambda prefix, version: (503, "busy"))
    with pytest.raises(RuntimeError, match="inconclusive") as info:
        c.request("/home", server.send_for("/home"))
    assert not isinstance(info.value, cv.VersionUnavailable)


def test_learning_off_returns_every_refusal_untouched(tmp_path):
    server = FakeServer()
    c, _, _ = make(tmp_path, server, learn=False, app_version="12.1.0")
    status, body = c.request("/home", server.send_for("/home"))
    assert (status, body["errorCode"]) == (400, 119801)
    assert server.real == [("/v12.3", "12.1.0")] and server.oracle_calls == []


def test_candidates():
    assert cv.version_candidates("12.3.0") == [
        "12.3.0", "12.3.1", "12.3.2", "12.3.3", "12.3.4", "12.3.5",
        "12.2.0", "12.3.0", "12.4.0", "12.5.0", "13.0.0"]
    assert cv.prefix_candidates("/v12.3") == [
        "/v12.2", "/v12.3", "/v12.4", "/v12.5", "/v12.6", "/v13.0"]
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version_learning.py -q`
Expected: FAIL — `AttributeError: module 'client_version' has no attribute 'version_candidates'` และ
เทสต์ที่คาดการสลับค่าล้มเพราะ `request` ยังส่งครั้งเดียว

- [ ] **Step 3: เพิ่มฟังก์ชันระดับโมดูล** ใน `tools/client_version.py` ต่อจาก `classify()` (ก่อน `class ClientVersion`)

```python
def _vkey(version: str) -> tuple:
    return tuple(int(x) for x in version.split("."))


def _pkey(prefix: str) -> tuple:
    return tuple(int(x) for x in prefix[2:].split("."))


def version_candidates(current: str) -> list:
    """Builds worth asking about when `current` stops being known: every patch 0-5 of its
    minor, the minors either side of it, and the next major. The caller sorts newest first."""
    major, minor, _patch = _vkey(current)
    out = ["%d.%d.%d" % (major, minor, p) for p in range(0, 6)]
    out += ["%d.%d.0" % (major, m) for m in range(max(0, minor - 1), minor + 3)]
    out.append("%d.0.0" % (major + 1))
    return out


def prefix_candidates(current: str) -> list:
    major, minor = _pkey(current)
    out = ["/v%d.%d" % (major, m) for m in range(max(0, minor - 1), minor + 4)]
    out.append("/v%d.0" % (major + 1))
    return out
```

- [ ] **Step 4: แทน `ClientVersion.request` ทั้งเมธอด** ด้วยตัวนี้ แล้วเพิ่มเมธอดที่เหลือต่อท้ายส่วน
  `# --- what to send ---` (ก่อน `# --- reporting ---`)

```python
    def request(self, path, send, pinned_prefix=None):
        """Send with the values this route should use; on a version refusal, find values the
        server takes, re-send, remember them. Returns the tuple the LAST send() returned.

        send(prefix, app_version) must return a tuple whose [0] is the HTTP status and [1] the
        parsed body. Pass `path` WITHOUT its /v12.x prefix - adding it is this module's job.
        Re-sending is safe for every signal handled here: 119801, a missing route and 401 are
        all refusals made before the server did anything.
        """
        if _PREFIXED_PATH_RE.match(path):
            raise ValueError("pass the path without its /v12.x prefix: %r" % (path,))
        self._load()
        route = route_of(path)
        if self.learn:
            self._check_dead()
        with self._lock:
            prefix, version, generation = self._resolve(route, pinned_prefix)
        result = send(prefix, version)
        hops = 0
        while True:
            kind = classify(result[0], result[1])
            if kind == "ok":
                self._mark_ok(route, version)
                return result
            if not self.learn or hops >= 3:     # 3 = pin dropped -> version swept -> prefix swept
                return result
            if kind == "unauthorized":
                return self._after_401(route, prefix, version, send, result)
            if kind == "version_unknown":
                self._after_unknown_version(route, version, generation)
            elif kind == "route_missing" and pinned_prefix is None:
                if not self._after_route_missing(prefix, version, generation):
                    return result
            else:
                return result
            hops += 1
            with self._lock:
                prefix, version, generation = self._resolve(route, pinned_prefix)
            result = send(prefix, version)

    # --- learning -----------------------------------------------------------------------
    #
    # Every sweep runs while holding self._lock. That is the single-flight: 128 threads that
    # all get 119801 at once queue on the lock, and each one that gets in after the first
    # sees self._generation moved on and simply re-sends with the new values.

    def _after_401(self, route, prefix, version, send, result):
        """The 401 rule (spec 4.3). A 401 is byte-identical whether the version was refused or
        the token is dead, so it only counts as a version problem on a route that has never
        answered 200 with this version in this process. Login mode proves /login and /home on
        its first good account; after that every dead token costs nothing extra."""
        messages = []
        retry_with = None
        try:
            with self._lock:
                if (route, version) in self._proven or (route, version) in self._not_version:
                    return result
                current = self.route_pins.get(route, self.app_version)
                if current != version:
                    retry_with = current        # another thread already found this route's version
                else:
                    candidates = sorted((v for v in self.known_good if v != version),
                                        key=_vkey, reverse=True)
                    for cand in candidates:
                        attempt = send(prefix, cand)
                        kind = classify(attempt[0], attempt[1])
                        if kind == "ok":
                            self._proven.add((route, cand))
                            messages.append(self._record("route_pin", route, version, cand,
                                                         "401 on a never-proven route"))
                            self.route_pins[route] = cand
                            self._generation += 1
                            self._save()
                            return attempt
                        if kind == "version_unknown":
                            self._forget(cand)
                    self._not_version.add((route, version))
                    return result
        finally:
            self._emit(messages)
        attempt = send(prefix, retry_with)
        if classify(attempt[0], attempt[1]) == "ok":
            self._mark_ok(route, retry_with)
        return attempt

    def _after_unknown_version(self, route, version, generation) -> None:
        messages = []
        try:
            with self._lock:
                if self._generation != generation:
                    return                           # another thread already moved us on
                self._check_dead()
                self._forget(version)
                if self.route_pins.get(route) == version:
                    del self.route_pins[route]
                    messages.append(self._record("route_pin", route, version, self.app_version,
                                                 "server no longer knows %s: 119801" % version))
                    self._generation += 1
                    self._save()
                    if self.app_version != version:
                        return                       # the main version may still do
                candidates = sorted({v for v in list(self.known_good) + version_candidates(version)
                                     if v != version}, key=_vkey, reverse=True)
                for cand in candidates:              # newest first: the first "known" is the newest
                    answer = self._ask_oracle(self.api_prefix, cand)
                    if answer == "known":
                        messages.append(self._record("app_version", None, version, cand,
                                                     "server no longer knows %s: 119801" % version))
                        self.app_version = cand
                        if cand not in self.known_good:
                            self.known_good.append(cand)
                        self._generation += 1
                        self._save()
                        return
                    if answer == "unknown":
                        self._forget(cand)
                self._save()
                self._give_up("no App-Version the server knows (tried %d builds around %s)"
                              % (len(candidates), version))
        finally:
            self._emit(messages)

    def _after_route_missing(self, prefix, version, generation) -> bool:
        """True = the prefix moved, re-send. False = keep the 404 (spec 4.6: move only when the
        current prefix itself is dead, never because one endpoint went away)."""
        messages = []
        try:
            with self._lock:
                if self._generation != generation:
                    return self.api_prefix != prefix
                self._check_dead()
                if self._ask_oracle(prefix, version) == "known":
                    return False
                candidates = sorted(set(prefix_candidates(prefix)) - {prefix}, key=_pkey, reverse=True)
                for cand in candidates:
                    if self._ask_oracle(cand, version) == "known":
                        messages.append(self._record("api_prefix", None, prefix, cand,
                                                     "%s no longer answers" % prefix))
                        self.api_prefix = cand
                        self._generation += 1
                        self._save()
                        return True
                self._give_up("no URL prefix answers (tried %d around %s)" % (len(candidates), prefix))
        finally:
            self._emit(messages)

    def _ask_oracle(self, prefix, version) -> str:
        """GET {prefix}/home with a fake token. The server checks the version first, so:
        401 = version known and prefix alive, 119801 = version unknown, 404 = prefix missing.
        Network errors propagate; 429/5xx raise - neither may ever count as "unknown", or a
        blip mid-sweep would stop the whole engine."""
        oracle = self._oracle_fn or _registered_oracle()
        if oracle is None:
            raise RuntimeError("client_version: no oracle transport registered")
        answer = oracle(prefix, version)
        status, parsed = answer[0], answer[1]
        kind = classify(status, parsed)
        if kind == "unauthorized":
            return "known"
        if kind == "version_unknown":
            return "unknown"
        if kind == "route_missing":
            return "missing"
        if status == 429 or ratelimit.is_app_429(status, parsed) is not None or (
                isinstance(status, int) and status >= 500):
            raise RuntimeError("version probe inconclusive: HTTP %s" % status)
        return "other"

    def _forget(self, version) -> None:
        if version in self.known_good:
            self.known_good.remove(version)

    def _check_dead(self) -> None:
        if self._dead_until and self._clock() < self._dead_until:
            raise VersionUnavailable(self._dead_reason)

    def _give_up(self, reason) -> None:
        self._dead_until = self._clock() + DEAD_COOLDOWN
        self._dead_reason = reason
        raise VersionUnavailable(reason)

    def _record(self, what, route, old, new, why) -> str:
        self.history.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "what": what,
                             "route": route, "from": old, "to": new, "why": why})
        del self.history[:-HISTORY_KEEP]
        label = {"app_version": "App-Version", "api_prefix": "API prefix",
                 "route_pin": "App-Version %s" % route}[what]
        return "%s: %s -> %s (%s)" % (label, old, new, why)

    def _emit(self, messages) -> None:
        for message in messages:
            for callback in list(self._listeners):
                try:
                    callback(message)
                except Exception:
                    pass          # a broken listener must not undo a switch that already happened
```

- [ ] **Step 5: รันเทสต์ของ task นี้ และของ Task 1**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version_learning.py tools/tests/test_client_version.py -q`
Expected: PASS ทั้งหมด

- [ ] **Step 6: รันทั้งชุด**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q`
Expected: เขียวทั้งหมด (374 + 15 = 389)

- [ ] **Step 7: Commit**

```bash
git add tools/client_version.py tools/tests/test_client_version_learning.py
git commit -m "feat(client-version): learn from refusals - 401 rule, version and prefix sweeps

119801 moves the main version to the newest build a fake-token GET /home says the server
knows; a 401 only counts as a version problem on a route that never answered 200 with that
version, and is then fixed with a per-route pin; a 404 moves the prefix only when the current
prefix itself stops answering. Sweeps run under one lock (single-flight), network errors and
5xx during a sweep are ordinary failures, and a sweep that finds nothing raises
VersionUnavailable and fails fast for 30 s.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: ต่อจุดยิงกลุ่ม business — rangers_api, gacha, pull_roster, device_session + build

**Files:**
- Modify: `tools/rangers_api.py` (CRLF) — `call()` ช่วงบรรทัด 128–194 และคอมเมนต์บรรทัด 28–33
- Modify: `tools/gacha.py` (LF) — `call()` บรรทัด 52–102 และ path ที่บรรทัด 129, 160, 198, 265, 279
- Modify: `tools/pull_roster.py` (CRLF) — `ROSTER_PATH` บรรทัด 51, `fetch_roster()` บรรทัด 118–157
- Modify: `tools/device_session.py` (CRLF) — `player_summary()` บรรทัด 139–166
- Modify: `bot/build.bat` (CRLF) บรรทัด 98 และ 114–119 · `bot/BotLineRanger.spec` (LF) hiddenimports
- Modify: `tools/tests/test_gacha_cache.py` `tools/tests/test_gacha_draw.py` — path ในตัวปลอม
- Test: `tools/tests/test_client_version_wiring.py` `tools/tests/test_build_bundles_tools.py`

**Interfaces:**
- Consumes: `client_version.request/headers/set_oracle/ORACLE_PATH/ORACLE_COOKIE`, `ClientVersion`
- Produces: `rangers_api.call(cookie, path, method="GET", body=None, api=None, extra_headers=None)` ·
  `rangers_api._send_raw(cookie, url, method, data, app_version, extra_headers=None) -> (status, parsed)` ·
  `rangers_api._oracle(prefix, app_version)` · `gacha.call(cookie, uid, path, method="GET", body=None)`
  ที่รับ path **ไม่มี** prefix

- [ ] **Step 1: เขียนเทสต์ที่ล้มก่อน** — `tools/tests/test_client_version_wiring.py`

```python
"""The business-tier call sites take their version and prefix from client_version.

Each test installs its own non-learning ClientVersion whose file says /v12.2 + 12.3.2 - values
nothing in the codebase hardcodes - so a call site that still built its own header or URL
could not pass.
"""
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import pytest

import client_version as cv
import rangers_api as ra


@pytest.fixture
def odd_version(tmp_path, monkeypatch):
    path = tmp_path / "api_version.json"
    path.write_text(json.dumps({"app_version": "12.3.2", "api_prefix": "/v12.2"}), encoding="utf-8")
    inst = cv.ClientVersion(str(path), learn=False)
    monkeypatch.setattr(cv, "_DEFAULT", inst)
    return inst


@pytest.fixture(autouse=True)
def _lane_isolated():
    ra.use_lane(None)
    yield
    ra.use_lane(None)


class Lane:
    name, parts, alive = "L", None, True
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


class FakeResp:
    status = 200
    def __init__(self, body=b'{"result":{}}'):
        self._body = body
    def read(self): return self._body
    def getheader(self, name, default=None): return None


class FakeConn:
    def __init__(self):
        self.sent = []
    def request(self, method, url, body=None, headers=None):
        self.sent.append((method, url, headers))
    def getresponse(self):
        return FakeResp()


def test_call_sends_the_prefix_and_version_client_version_chose(odd_version, monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    ra.use_lane(Lane())
    status, body = ra.call("LF_AC=wiring-1", "/home")
    assert status == 200
    method, url, headers = conn.sent[0]
    assert (method, url) == ("GET", "/v12.2/home")
    assert headers["App-Version"] == "LGRGS/12.3.2;android/12"
    assert headers["User-Agent"].startswith("LGRGS/12.3.2 ")


def test_call_api_argument_pins_the_prefix(odd_version, monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    ra.use_lane(Lane())
    ra.call("LF_AC=wiring-2", "/home", api="/v12.3")
    assert conn.sent[0][1] == "/v12.3/home"


def test_call_extra_headers_are_sent(odd_version, monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ra, "_get_conn", lambda: conn)
    ra.use_lane(Lane())
    ra.call("LF_AC=wiring-3", "/gacha/info", extra_headers={"UID": "u9"})
    assert conn.sent[0][2]["UID"] == "u9"


def test_the_oracle_is_a_fake_token_get_of_home(monkeypatch):
    seen = []
    monkeypatch.setattr(ra, "_send_raw", lambda *a, **k: (seen.append(a), (401, {"errorCode": 401}))[1])
    assert ra._oracle("/v12.4", "12.4.0") == (401, {"errorCode": 401})
    cookie, url, method, data, version = seen[0][:5]
    assert (cookie, url, method, data, version) == ("LF_AC=0", "/v12.4/home", "GET", None, "12.4.0")


def test_importing_rangers_api_registers_its_oracle():
    code = ("import sys; sys.path.insert(0, %r); import rangers_api, client_version; "
            "assert client_version._ORACLE is rangers_api._oracle" % TOOLS)
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_gacha_call_goes_through_rangers_api_with_its_uid(monkeypatch):
    import gacha
    seen = []
    monkeypatch.setattr(ra, "call", lambda *a, **k: (seen.append((a, k)), (200, {}))[1])
    gacha.call("LF_AC=g", "u1", "/gacha/info")
    gacha.call("LF_AC=g", None, "/gacha/group/reserve", "POST", {"groupId": "x"})
    assert seen[0] == (("LF_AC=g", "/gacha/info", "GET", None), {"extra_headers": {"UID": "u1"}})
    assert seen[1] == (("LF_AC=g", "/gacha/group/reserve", "POST", {"groupId": "x"}),
                       {"extra_headers": None})


class UrlResp(io.BytesIO):
    status = 200
    headers = {}


def test_fetch_roster_uses_client_version(odd_version, monkeypatch):
    import pull_roster
    seen = []
    monkeypatch.setattr(pull_roster.urllib.request, "urlopen",
                        lambda req, timeout=None: (seen.append(req), UrlResp(b'{"result":{}}'))[1])
    assert pull_roster.fetch_roster("LF_AC=r", None) == b'{"result":{}}'
    assert seen[0].full_url == ("https://rangers-api.line-apps.com/v12.2"
                                "/player/units/equip?inven=true&team=true&deck=true")
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"


def test_device_session_player_summary_uses_client_version(odd_version, monkeypatch):
    import device_session
    body = json.dumps({"result": {"player": {"uid": 1, "mid": "m", "userName": "n", "level": 3},
                                  "rubyBalance": {"total": 5}}}).encode()
    seen = []
    monkeypatch.setattr(device_session.urllib.request, "urlopen",
                        lambda req, timeout=None: (seen.append(req), UrlResp(body))[1])
    assert device_session.player_summary("tok")["level"] == 3
    assert seen[0].full_url == ("https://rangers-api.line-apps.com/v12.2"
                                "/player/units/equip?inven=false&team=false&deck=false")
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"
```

และ `tools/tests/test_build_bundles_tools.py`:

```python
"""Every tools module the build obfuscates must also be a PyInstaller hidden import.

The engine imports tools/ modules by bare name after a sys.path insert that means nothing once
frozen, so a module pyarmor encrypts but the spec does not list is silently left out of the exe
- and client_version is imported by rangers_api, i.e. by every mode.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pyarmor_tools():
    text = open(os.path.join(ROOT, "bot", "build.bat"), encoding="utf-8", errors="replace").read()
    command = []
    for line in text.split("pyarmor gen --output dist_pyarmor", 1)[1].splitlines():
        command.append(line)
        if line.strip() and not line.rstrip().endswith("^"):
            break
    return set(re.findall(r"\.\.\\tools\\(\w+)\.py", "\n".join(command)))


def _hidden_imports():
    text = open(os.path.join(ROOT, "bot", "BotLineRanger.spec"), encoding="utf-8").read()
    block = text.split("hiddenimports=[", 1)[1].split("\n    ],", 1)[0]
    return set(re.findall(r"^\s*'(\w+)',", block, re.M))


def test_client_version_is_obfuscated_and_bundled():
    assert "client_version" in _pyarmor_tools()
    assert "client_version" in _hidden_imports()


def test_every_obfuscated_tool_is_a_hidden_import():
    assert _pyarmor_tools() - _hidden_imports() == set()
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version_wiring.py tools/tests/test_build_bundles_tools.py -q`
Expected: FAIL — URL ยังเป็น `/v12.3/home`, header ยังเป็น 12.3.0, `ra._oracle` ไม่มี, `client_version` ไม่อยู่ใน build

- [ ] **Step 3: `tools/rangers_api.py`** — เพิ่ม `import client_version` ต่อจาก `import ratelimit` (บรรทัด 24) แล้ว
  แทนคอมเมนต์+ค่าคงที่บรรทัด 28–33 ด้วย:

```python
# Old names, kept because standalone scripts still read them. Nothing in tools/ or bot/engine/
# sends with them any more: every call takes its prefix and App-Version from client_version,
# which learns from the server when a value stops being accepted (see that module). The server
# does route each version separately - /v12.3/popup/reward/<seq> returns 500 for a CLS_GACHA
# reward under an older prefix - which is exactly why the prefix is managed, not hardcoded.
API = "/v12.3"
CLIENT_VERSION = "12.3.0"
```

  แล้วแทน `def call(...)` ทั้งฟังก์ชัน (จนถึง `return status, parsed` ก่อน `def add_session_args`) ด้วย:

```python
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
```

- [ ] **Step 4: `tools/gacha.py`** — แทน `def call(...)` ทั้งฟังก์ชัน (บรรทัด 52 จนจบ `return status, raw.decode(...)`) ด้วย:

```python
def call(cookie, uid, path, method="GET", body=None):
    """(status, parsed) through rangers_api.call - its keep-alive connection, retry policy,
    per-account pacing, lane bucket, and the App-Version/prefix client_version manages.

    `path` must NOT carry the /v12.x prefix. `uid` is optional: the server derives the player
    from LF_AC, so device sessions omit it. Before 2026-09-24 this function built its own
    headers and loop and skipped the per-account pacer and lane bucket entirely; going through
    rangers_api.call adds both, and the per-account HTTP 400 + errorCode 429 retry with them.
    """
    import rangers_api
    return rangers_api.call(cookie, path, method, body,
                            extra_headers={"UID": uid} if uid else None)
```

  แล้วตัด `/v12.3` ออกจาก path ทั้ง 5 จุด: บรรทัด 129 `"/v12.3/player/item?..."` → `"/player/item?..."` ·
  บรรทัด 160 `"/v12.3/gacha/info"` → `"/gacha/info"` · บรรทัด 198 `"/v12.3/player/units/equip?..."` →
  `"/player/units/equip?..."` · บรรทัด 265 `"/v12.3/gacha/group/reserve"` → `"/gacha/group/reserve"` ·
  บรรทัด 279 `"/v12.3/gacha/group/confirm"` → `"/gacha/group/confirm"` (docstring บรรทัด 17–18 ไม่ต้องแตะ)
  จากนั้นเช็กว่า import ไหนไม่มีใครใช้แล้ว:
  `grep -n 'gzip\.\|http\.client\|time\.' tools/gacha.py` — ลบบรรทัด `import gzip` / `import http.client` /
  `import time` เฉพาะตัวที่ grep ไม่เจอการใช้งานอื่นเหลือเลย

- [ ] **Step 5: แก้ตัวปลอมในเทสต์ gacha เดิม** ให้ใช้ path ที่ไม่มี prefix (LF ทั้งสองไฟล์)

Run: `sed -i 's#"/v12\.3/#"/#g' tools/tests/test_gacha_cache.py tools/tests/test_gacha_draw.py`
แล้ว `grep -n 'v12' tools/tests/test_gacha_cache.py tools/tests/test_gacha_draw.py` ต้องไม่เหลือ

- [ ] **Step 6: `tools/pull_roster.py`** — เพิ่ม `import client_version` ต่อจาก `import urllib.request` (บรรทัด 39;
  โมดูลอยู่ใน `tools/` จึง import ตรง ๆ ได้) เปลี่ยนบรรทัด 51 เป็น
  `ROSTER_PATH = "/player/units/equip?inven=true&team=true&deck=true"` แล้วแทน `fetch_roster` ทั้งฟังก์ชัน:

```python
def fetch_roster(cookie: str, uid: str) -> bytes:
    def send(prefix, app_version):
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
        }
        if uid:   # optional - the server derives the player from LF_AC, so device sessions omit it
            headers["UID"] = uid
        request = urllib.request.Request("https://" + HOST + prefix + ROSTER_PATH,
                                         headers=headers, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=25)
            raw = response.read()
            status = response.status
            encoding = response.headers.get("Content-Encoding")
        except urllib.error.HTTPError as err:
            raw = err.read()
            status = err.code
            encoding = err.headers.get("Content-Encoding")
        if encoding == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        return status, parsed, raw

    status, _parsed, raw = client_version.request(ROSTER_PATH, send)
    if status != 200:
        raise SystemExit(
            "Server returned HTTP %s: %s\n"
            "The session token has most likely expired - restart the game with the proxy "
            "running to capture a fresh one, then try again." % (status, raw[:200].decode("utf-8", "replace"))
        )
    return raw
```

- [ ] **Step 7: `tools/device_session.py`** — เพิ่ม `import client_version` ต่อจาก `import urllib.request` (บรรทัด 37)
  แล้วแทน `player_summary`:

```python
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
```

- [ ] **Step 8: build** — `bot/build.bat` (CRLF, ใช้ Edit tool): บรรทัด 98 `REM ..\tools\*.py (11 files): the reverse-engineered API layer - rangers_api, relogin,`
  → `REM ..\tools\*.py (12 files): the reverse-engineered API layer - rangers_api, client_version, relogin,`
  และบรรทัด 116 เพิ่ม `..\tools\client_version.py` หน้าตัวแรก:

```bat
    ..\tools\account_file.py ..\tools\client_version.py ..\tools\device_session.py ..\tools\gacha.py ^
```

  `bot/BotLineRanger.spec`: ในกลุ่ม tools ของ `hiddenimports` เพิ่ม `'client_version',` ถัดจาก `'account_file',`
  พร้อมคอมเมนต์หนึ่งบรรทัดเหนือรายการเดิม:

```python
        # client_version (2026-09-24): imported by rangers_api, i.e. by every mode.
        'account_file',
        'client_version',
```

- [ ] **Step 9: รันเทสต์ของ task นี้**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version_wiring.py tools/tests/test_build_bundles_tools.py tools/tests/test_gacha_cache.py tools/tests/test_gacha_draw.py tools/tests/test_rangers_api.py -q`
Expected: PASS ทั้งหมด

- [ ] **Step 10: รันทั้งชุด + เช็ก line ending**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q` → เขียวทั้งหมด
Run: `git diff --stat` → ไม่มีไฟล์ไหนขึ้นว่าแก้เกือบทั้งไฟล์ (สัญญาณว่า CRLF ถูกเปลี่ยนเป็น LF)

- [ ] **Step 11: Commit**

```bash
git add tools/rangers_api.py tools/gacha.py tools/pull_roster.py tools/device_session.py \
        bot/build.bat bot/BotLineRanger.spec tools/tests/test_gacha_cache.py tools/tests/test_gacha_draw.py \
        tools/tests/test_client_version_wiring.py tools/tests/test_build_bundles_tools.py
git commit -m "feat(client-version): business-tier calls take version and prefix from client_version

rangers_api.call now wraps its unchanged retry loop (_send_raw) in client_version.request and
registers the fake-token GET /home oracle. gacha.call delegates to it instead of carrying a
second copy of the headers and loop - which also brings gacha under the per-account pacer and
lane bucket it used to skip. pull_roster and device_session go through request() too, and no
path carries /v12.3 any more. client_version is obfuscated and bundled like the other tools.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: ต่อ signup/login — new_account, relogin + ห้ามฮาร์ดโค้ด

**Files:**
- Modify: `tools/new_account.py` (CRLF) — ลบบรรทัด 99–123 (`UA_GAME` `APP_VERSION` คอมเมนต์ยาว
  `SIGNUP_APP_VERSION`) แทน `game_login` (บรรทัด ~410–456) และ `signup_platform` (~458–512)
- Modify: `tools/relogin.py` (CRLF) — ลบบรรทัด 40–41, 43 (`UA_GAME` `APP_VERSION` `LOGIN_PATH`) แก้ `login()`
- Test: `tools/tests/test_client_version_login_signup.py` `tools/tests/test_no_hardcoded_client_version.py`

**Interfaces:**
- Consumes: `client_version.request/headers/ClientVersion` · `new_account._do(req) -> (status, parsed, set_cookies)`
- Produces: `new_account.signup_platform(cc, udid, user_type="LINE")` และ `new_account.game_login(cc, udid,
  guest_cookie=None)` คืนค่าเหมือนเดิม · `relogin.login(cc, udid, guest_cookie, nation, language="en")`
  คืน `(status, result_or_None, lf_ac_or_None)` เหมือนเดิม · `relogin.LOGIN_ROUTE = "/login"`

- [ ] **Step 1: เขียนเทสต์ที่ล้มก่อน** — `tools/tests/test_client_version_login_signup.py`

```python
"""signup and login take their version and prefix from client_version - and the 401 rule
really does find signup's version through the real new_account code."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import pytest

import client_version as cv
import new_account as na
import relogin


def _install(tmp_path, monkeypatch, learn=False, **state):
    path = tmp_path / "api_version.json"
    if state:
        path.write_text(json.dumps(state), encoding="utf-8")
    inst = cv.ClientVersion(str(path), learn=learn,
                            oracle=lambda p, v: pytest.fail("signup/login must not need the oracle"))
    monkeypatch.setattr(cv, "_DEFAULT", inst)
    return inst


def _capture_do(monkeypatch, module, answer):
    seen = []

    def fake_do(req):
        seen.append(req)
        return answer(req)

    monkeypatch.setattr(module, "_do", fake_do)
    return seen


SIGNUP_OK = (200, {"result": {"id": "u", "mid": "m", "rsn": "r", "isNew": True, "level": 1,
                              "ruby": {"total": 20}, "coin": {"total": 0}}}, ["LF_AC=abc; Path=/"])


def test_signup_sends_its_pinned_version_under_the_managed_prefix(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, api_prefix="/v12.2")
    seen = _capture_do(monkeypatch, na, lambda req: SIGNUP_OK)
    session = na.signup_platform("cc1", "udid1")
    assert session["lf_ac"] == "abc"
    assert seen[0].full_url == "https://rangers-api.line-apps.com/v12.2/signup/platform"
    assert seen[0].get_header("App-version") == "LGRGS/12.2.0;android/12"
    assert seen[0].get_header("User-agent").startswith("LGRGS/12.2.0 ")


def test_game_login_sends_the_main_version(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, app_version="12.3.2")
    seen = _capture_do(monkeypatch, na, lambda req: (200, {"result": {"id": "u", "rsn": "r"}},
                                                     ["LF_AC=xyz"]))
    session = na.game_login("cc1", "udid1", guest_cookie="g")
    assert session["lf_ac"] == "xyz"
    assert seen[0].full_url == "https://rangers-api.line-apps.com/v12.3/login"
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"


def test_the_401_rule_finds_signups_version_through_the_real_signup_code(tmp_path, monkeypatch):
    inst = _install(tmp_path, monkeypatch, learn=True, route_pins={})

    def server(req):
        if req.get_header("App-version") == "LGRGS/12.2.0;android/12":
            return SIGNUP_OK
        return 401, {"errorCode": 401}, []

    seen = _capture_do(monkeypatch, na, server)
    session = na.signup_platform("cc1", "udid1")
    assert session["lf_ac"] == "abc"
    assert [r.get_header("App-version") for r in seen] == [
        "LGRGS/12.3.0;android/12", "LGRGS/12.4.0;android/12",
        "LGRGS/12.3.2;android/12", "LGRGS/12.2.0;android/12"]
    assert inst.route_pins == {"/signup/platform": "12.2.0"}


def test_relogin_login_uses_the_managed_route(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, api_prefix="/v12.2", app_version="12.3.2")
    seen = _capture_do(monkeypatch, na, lambda req: (200, {"result": {"rsn": "r"}}, ["LF_AC=new"]))
    status, result, lf_ac = relogin.login("cc", "udid", "guest", "TH")
    assert (status, result, lf_ac) == (200, {"rsn": "r"}, "new")
    assert seen[0].full_url == "https://rangers-api.line-apps.com/v12.2/login"
    assert seen[0].get_header("App-version") == "LGRGS/12.3.2;android/12"
    assert seen[0].get_header("Nation-code") == "TH"
```

และ `tools/tests/test_no_hardcoded_client_version.py`:

```python
"""No request code bakes in an App-Version or a /v12.x prefix any more (spec test 15).

Scans string constants with ast, so comments and docstrings - which legitimately record what
was measured - do not count. client_version.py holds the defaults and is the one exception.
"""
import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))
               + glob.glob(os.path.join(ROOT, "bot", "engine", "*.py")))
BAKED = re.compile(r"LGRGS/\d|^/v\d+\.\d+/")


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def test_no_string_in_request_code_carries_a_version_or_prefix():
    hits = []
    for path in FILES:
        if os.path.basename(path) == "client_version.py":
            continue
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and BAKED.search(node.value)):
                hits.append("%s:%d %r" % (os.path.relpath(path, ROOT), node.lineno, node.value[:60]))
    assert hits == []


def test_only_rangers_api_still_names_its_old_constants():
    users = []
    for path in FILES:
        if os.path.basename(path) == "rangers_api.py":
            continue
        with open(path, encoding="utf-8") as fh:
            if re.search(r"\bCLIENT_VERSION\b|rangers_api\.API\b", fh.read()):
                users.append(os.path.relpath(path, ROOT))
    assert users == []
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version_login_signup.py tools/tests/test_no_hardcoded_client_version.py -q`
Expected: FAIL — URL ยังเป็น `/v12.3/...` ตายตัว, header มาจากค่าคงที่, AST เจอ `new_account.py` และ `relogin.py`

- [ ] **Step 3: `tools/new_account.py`** — เพิ่ม `import client_version` ในกลุ่ม import ของโมดูล (ข้าง `import rangers_api`)
  ลบบรรทัด 99–123 (`UA_GAME = ...` ถึง `SIGNUP_APP_VERSION = ...` รวมคอมเมนต์ยาว — ความรู้นี้ย้ายไปอยู่ใน
  `client_version.DEFAULT_PINS` แล้ว) **เก็บ `UA_SDK` ไว้** (ใช้กับ game-api) แล้วแทนสองฟังก์ชัน:

```python
def game_login(cc: str, udid: str, guest_cookie: str | None = None) -> dict:
    """GET <prefix>/login exactly as the client sends it (captured from a real session).

    The client's cookie jar carries three things: `cc` (the fresh SDK userToken),
    `udid` (the game's own device uuid, also the AES key for the stored token) and,
    once a session exists, `guestCookie` - the first 16 chars of the previous LF_AC.
    Prefix and App-Version come from client_version.
    """
    cookie = "cc=%s; udid=%s;" % (cc, udid)
    if guest_cookie:
        cookie += " guestCookie=%s" % guest_cookie

    def send(prefix, app_version):
        version_headers = client_version.headers(app_version)
        headers = {
            "App-Version": version_headers["App-Version"],
            "userType": "",
            "Nation-Code": NATION,
            "Accept-Language": LANG,
            "User-Agent": version_headers["User-Agent"],
            "marketId": "",
            "useLGC": "true",
            "X-LINEGAME-MCC": "000",
            "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": str(int(time.time() * 1000)),
            "Host": RANGERS_HOST,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Cookie": cookie,
        }
        # login is GET-only; POST returns 405.
        return _do(urllib.request.Request("https://" + RANGERS_HOST + prefix + "/login",
                                          headers=headers, method="GET"))

    st, res, cookies = client_version.request("/login", send)
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
    """GET <prefix>/signup/platform - creates the rangers PLAYER for a brand-new guest.

    This is the endpoint the native client hits on a genuine first login (a fresh guest
    has no player yet, so /login returns 401). It is NOT certificate-pinned and carries no
    X-LINEGAME-APPSECRET: the same cc+udid cookie jar as a relogin, plus an empty LF_AC to
    signal "no session yet". Response body already includes the starter ruby/coin/level and
    a Set-Cookie: LF_AC for every subsequent authenticated call.
    Verified live 2026-09-14: fresh guest -> HTTP 200, isNew=true, level 1, ruby 20.

    Since 2026-09-24 this route refuses App-Version 12.3.0 with 401 while every other route
    takes it; client_version pins it to a version it accepts (see DEFAULT_PINS there) and
    finds a new one by itself if that pin stops working.
    """
    cookie = "cc=%s; udid=%s;, LF_AC=; udid=%s;" % (cc, udid, udid)

    def send(prefix, app_version):
        version_headers = client_version.headers(app_version)
        headers = {
            "App-Version": version_headers["App-Version"],
            "userType": user_type,
            "Nation-Code": NATION,
            "Accept-Language": LANG,
            "User-Agent": version_headers["User-Agent"],
            "marketId": "",
            "useLGC": "true",
            "X-LINEGAME-MCC": "000",
            "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": str(int(time.time() * 1000)),
            "Host": RANGERS_HOST,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Cookie": cookie,
        }
        return _do(urllib.request.Request("https://" + RANGERS_HOST + prefix + "/signup/platform",
                                          headers=headers, method="GET"))

    global LAST_SIGNUP_HTTP
    st, res, cookies = client_version.request("/signup/platform", send)
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
```

  เช็กว่าไม่มีใครใช้ชื่อที่ลบแล้ว: `grep -n 'UA_GAME\|APP_VERSION\|SIGNUP_APP_VERSION' tools/new_account.py` ต้องว่าง

- [ ] **Step 4: `tools/relogin.py`** — เพิ่ม `import client_version  # noqa: E402` ถัดจาก `import ratelimit  # noqa: E402`
  ลบบรรทัด `UA_GAME = ...` `APP_VERSION = ...` `LOGIN_PATH = ...` แล้วใส่แทน `LOGIN_PATH`:

```python
LOGIN_ROUTE = "/login"   # prefix and App-Version come from client_version
```

  แก้ docstring บรรทัดแรกของ `login()` จาก `ยิง GET /v12.3/login ...` เป็น `ยิง GET <prefix>/login ...` แล้วแทน
  ตัวลูป `for attempt in range(len(RETRY_WAITS) + 1):` ทั้งก้อนด้วย:

```python
    cookie = "cc=%s; udid=%s; guestCookie=%s;" % (cc, udid, guest_cookie)

    def send(prefix, app_version):
        version_headers = client_version.headers(app_version)
        headers = {
            "App-Version": version_headers["App-Version"],
            "userType": "",
            "Nation-Code": nation,
            "Accept-Language": language,
            "User-Agent": version_headers["User-Agent"],
            "marketId": "",
            "useLGC": "true",
            "X-LINEGAME-MCC": "000",
            "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": str(int(time.time() * 1000)),
            "Host": RANGERS_HOST,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Cookie": cookie,
        }
        return na._do(urllib.request.Request("https://" + RANGERS_HOST + prefix + LOGIN_ROUTE,
                                             headers=headers, method="GET"))

    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            status, res, cookies = client_version.request(LOGIN_ROUTE, send)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # na._do already retried the network error with backoff (_NET_ATTEMPTS); looping
            # again here would multiply the wait (8 x 4 ~ 16 min per file when the net is down).
            raise Transient("network: %s" % exc)
        else:
            if (status == 429 or ratelimit.is_app_429(status, res) is not None
                    or (isinstance(status, int) and 500 <= status < 600)):
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
```

  (บรรทัด `cookie = ...` และ `last = None` เดิมที่อยู่เหนือลูปถูกแทนด้วยก้อนนี้แล้ว — อย่าให้ซ้ำ)

- [ ] **Step 5: รันเทสต์ของ task นี้ + เทสต์เดิมของสองไฟล์นี้**

Run: `PYTHONUTF8=1 python -m pytest tools/tests/test_client_version_login_signup.py tools/tests/test_no_hardcoded_client_version.py tools/tests/test_relogin.py tools/tests/test_new_account_do.py -q`
Expected: PASS ทั้งหมด

- [ ] **Step 6: รันทั้งชุด + เช็ก line ending**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q` → เขียวทั้งหมด
Run: `git diff --stat` → `new_account.py` และ `relogin.py` ต้องไม่ขึ้นว่าแก้ทั้งไฟล์

- [ ] **Step 7: Commit**

```bash
git add tools/new_account.py tools/relogin.py \
        tools/tests/test_client_version_login_signup.py tools/tests/test_no_hardcoded_client_version.py
git commit -m "feat(client-version): signup and login go through client_version

SIGNUP_APP_VERSION, APP_VERSION, UA_GAME and LOGIN_PATH are gone; signup's 12.2.0 lives on
as client_version's seeded pin, and the 401 rule is proven to rediscover it through the real
signup_platform code. An AST test now fails if any request code bakes a version or a /v12.x
prefix into a string again.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: engine — ปล่อยผ่าน, หยุดทั้งตัว, ตั้งค่าและ log

**Files:**
- Modify: `bot/engine/flows.py` (LF) — import และ `except` หน้า `PermanentFailure` ทั้ง 4 จุด (บรรทัด ~419, ~499, ~557, ~594)
- Modify: `bot/engine/pool.py` (LF) — import, `__init__`, `_run_one`, เมธอดใหม่ `_stop_for_version`
- Modify: `bot/engine_main.py` (LF) — import และฟังก์ชันใหม่ `setup_client_version` เรียกใน `main`
- Test: `bot/tests/test_version_unavailable_stops_engine.py`

**Interfaces:**
- Consumes: `client_version.VersionUnavailable/configure/on_switch/describe/instance`
- Produces: `engine_main.setup_client_version(root: str, reporter) -> None` ·
  `EnginePool._stop_for_version(session, err) -> None`

- [ ] **Step 1: เขียนเทสต์ที่ล้มก่อน** — `bot/tests/test_version_unavailable_stops_engine.py`

```python
"""VersionUnavailable stops the engine instead of failing account after account (spec 5).

If it were caught like any other error, Login would move every input file to "login failed/"
and GenID would burn the 2-per-minute guest-mint quota on every attempt.
"""
import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import client_version                          # noqa: E402
from engine import flows                       # noqa: E402
from engine.pool import EnginePool             # noqa: E402
from engine.session import AccountSession      # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "engine_main_under_test_version", os.path.join(HERE, "engine_main.py"))
engine_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_main)


class Lane:
    name, parts, alive, threads = "L", None, True, 1
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


class Recorder:
    def __init__(self):
        self.notes, self.accounts = [], []
    def account(self, **kw): self.accounts.append(kw)
    def stat(self, **kw): pass
    def lane(self, **kw): pass
    def note(self, msg): self.notes.append(msg)


class RecordingQueue:
    def __init__(self):
        self.failed, self.finished = [], []
    def claim(self): return None
    def fail(self, *a, **k): self.failed.append(a)
    def finish(self, *a, **k): self.finished.append(a)
    def remaining(self): return 0


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: None)


@pytest.mark.parametrize("mode", sorted(flows.MODES))
def test_every_flow_lets_it_through_on_the_first_attempt(monkeypatch, tmp_path, mode):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise client_version.VersionUnavailable("no App-Version the server knows")

    monkeypatch.setattr(flows, "_relogin", unavailable)
    monkeypatch.setattr(flows, "_create_account", unavailable)
    (tmp_path / "execute").mkdir()
    src = tmp_path / "execute" / "a.xml"
    src.write_text("<map/>", encoding="utf-8")
    session = AccountSession(src="" if mode in flows.SELF_SUPPLIED_MODES else str(src), lane=Lane())
    with pytest.raises(client_version.VersionUnavailable):
        flows.run(mode, session, {"_execute_dir": str(tmp_path / "execute")})
    assert calls == [1], "retrying it would only repeat the same answer MAX_ATTEMPTS times"


def _raise_unavailable(mode, session, cfg):
    raise client_version.VersionUnavailable("no URL prefix answers")


def test_the_pool_stops_and_leaves_the_file_in_execute(tmp_path):
    (tmp_path / "execute").mkdir()
    first = tmp_path / "execute" / "a.xml"
    second = tmp_path / "execute" / "b.xml"
    first.write_text("<map/>", encoding="utf-8")
    second.write_text("<map/>", encoding="utf-8")
    rec, queue = Recorder(), RecordingQueue()
    pool = EnginePool("ranger_api_Login", {}, queue, [], rec, flow=_raise_unavailable)

    pool._run_one(Lane(), str(first))
    pool._run_one(Lane(), str(second))           # a second thread reaching it too

    assert pool._stop.is_set()
    assert first.exists() and second.exists()
    assert queue.failed == [] and queue.finished == []
    assert (pool._done, pool._fail, pool._stuck) == (0, 0, 2)
    assert rec.accounts == []
    assert len(rec.notes) == 1 and "no URL prefix answers" in rec.notes[0]


def test_setup_client_version_uses_src_api_version_json_and_announces_it(tmp_path, monkeypatch):
    monkeypatch.setattr(client_version, "_DEFAULT", None)
    rec = Recorder()
    engine_main.setup_client_version(str(tmp_path), rec)
    inst = client_version.instance()
    assert inst.path == os.path.join(str(tmp_path), "src", "api_version.json")
    assert os.path.exists(inst.path)
    assert rec.notes == ["api version: /v12.3 + 12.3.0 (pins: /signup/platform=12.2.0)"]
    inst._emit(["App-Version: 12.3.0 -> 12.4.0 (server no longer knows 12.3.0: 119801)"])
    assert rec.notes[-1] == "App-Version: 12.3.0 -> 12.4.0 (server no longer knows 12.3.0: 119801)"
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/test_version_unavailable_stops_engine.py -q`
Expected: FAIL — flows retry 3 ครั้ง, pool ย้ายไฟล์ไป fail, `setup_client_version` ไม่มี

- [ ] **Step 3: `bot/engine/flows.py`** — เพิ่ม `import client_version     # noqa: E402` ถัดจาก `import rangers_api`
  แล้วหน้า `except PermanentFailure as err:` ของ `run_login` ใส่:

```python
        except client_version.VersionUnavailable:
            # ไม่มีเวอร์ชัน/prefix ไหนที่เซิร์ฟเวอร์รับ - ลองซ้ำก็ได้คำตอบเดิม และถ้ากลืนไว้ที่นี่
            # บัญชีจะไหลไป "login failed" ทีละใบจนหมดคิว ปล่อยขึ้นไปให้ pool หยุด engine ทั้งตัว
            _release_unclaimed_account()
            raise
```

  และหน้า `except PermanentFailure as err:` ของ `run_level3` `run_genid` `run_stage` ใส่:

```python
        except client_version.VersionUnavailable:
            raise           # ให้ pool หยุด engine - ดูคอมเมนต์เดียวกันใน run_login
```

- [ ] **Step 4: `bot/engine/pool.py`** — เพิ่ม `import client_version  # noqa: E402` ถัดจาก `import rangers_api`
  ใน `__init__` ต่อจาก `self._stuck = 0` เพิ่ม `self._version_stopped = False`
  ใน `_run_one` ใส่ก่อน `except (Exception, SystemExit) as err:`:

```python
        except client_version.VersionUnavailable as err:
            self._stop_for_version(session, err)
            return
```

  แล้วเพิ่มเมธอดใหม่ต่อจาก `request_stop`:

```python
    def _stop_for_version(self, session, err) -> None:
        """ไม่มี App-Version หรือ URL prefix ไหนที่เซิร์ฟเวอร์รับเลย (client_version สำรวจแล้ว)

        ทุกบัญชีหลังจากนี้จะล้มแบบเดียวกัน ถ้าปล่อยให้เป็น FAIL ธรรมดา Login จะย้ายไฟล์ input
        ทั้งหมดไป login failed/ และ GenID จะเผาโควตา mint ทิ้งทุกรอบ จึงหยุดรับงาน ไม่ย้ายไฟล์
        (ค้างใน execute/ แล้ว queue.recover() คืนเข้า input/ ตอนรันถัดไป) และบอกผู้ใช้ครั้งเดียว
        """
        with self._lock:
            first = not self._version_stopped
            self._version_stopped = True
            if session.src:
                self._stuck += 1
        if first:
            self.reporter.note("stopping: %s - accounts in progress stay in execute/ and go back "
                               "to input/ on the next run" % err)
        self.request_stop()
```

- [ ] **Step 5: `bot/engine_main.py`** — เพิ่ม `import client_version  # noqa: E402` ในกลุ่ม `import ratelimit`
  เพิ่มฟังก์ชันก่อน `def main(argv):`

```python
def setup_client_version(root: str, reporter) -> None:
    """เวอร์ชัน/prefix ที่ค้นเจอจำลง src/api_version.json ข้าง config.ini และทุกการสลับขึ้น log ของ GUI"""
    client_version.configure(os.path.join(root, "src", "api_version.json"))
    client_version.on_switch(reporter.note)
    reporter.note(client_version.describe())
```

  และใน `main` ต่อจาก `reporter = Reporter()` เรียก `setup_client_version(root, reporter)`

- [ ] **Step 6: รันเทสต์ของ task นี้ และของ engine ที่แตะ**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/test_version_unavailable_stops_engine.py bot/tests/test_pool.py bot/tests/test_flows_login.py bot/tests/test_flows_modes.py bot/tests/test_no_adb.py -q`
Expected: PASS ทั้งหมด

- [ ] **Step 7: รันทั้งชุด**

Run: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q` → เขียวทั้งหมด

- [ ] **Step 8: Commit**

```bash
git add bot/engine/flows.py bot/engine/pool.py bot/engine_main.py bot/tests/test_version_unavailable_stops_engine.py
git commit -m "feat(engine): stop the run when no App-Version or prefix is accepted, log every switch

Every flow lets VersionUnavailable through on its first attempt; the pool notes it once,
stops taking work and leaves the account's file in execute/ for the next run to recover -
instead of Login moving every input file to login failed/ or GenID burning the mint quota.
engine_main keeps the learned values in src/api_version.json and sends each switch to the
GUI log.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: พิสูจน์กับเซิร์ฟเวอร์จริง (controller ทำเอง ไม่ส่ง subagent)

ข้อ (ก)–(ง) ของ spec ข้อ 7 ใช้ sandbox และสคริปต์ใน scratchpad ของ session นี้ ทุกข้อสร้างบัญชี guest จริง
จำนวนเล็กน้อย ซึ่งเป็นงานปกติของ GenID

- [ ] **(ก) signup หาเวอร์ชันเอง** — sandbox ของ `genid_bench.py` เขียน `src/api_version.json` เป็น
  `{"route_pins": {}}` ก่อนสปอว์น engine รัน GenID 2 เธรด 150 วินาที ต้องเห็นบรรทัด note
  `App-Version /signup/platform: 12.3.0 -> ...` และได้บัญชี OK อย่างน้อย 1 ใบ และ `route_pins` ในไฟล์ถูกเขียน
  — ข้อนี้พิสูจน์ (ง) ไปด้วย: signup ที่ได้ 200 ส่ง UA เวอร์ชันเดียวกับ App-Version ถ้าไม่มีเวอร์ชันไหนผ่าน
  แปลว่า UA ต้องคงเวอร์ชันหลัก — กลับไปแก้ `headers()` ตาม spec ข้อ 3.1
- [ ] **(ข) เวอร์ชันหลักตาย** — sandbox เขียน `{"app_version": "12.1.0"}` รัน GenID 1 เธรด 90 วินาที ต้องเห็น
  `App-Version: 12.1.0 -> 12.4.0 (server no longer knows 12.1.0: 119801)` และบัญชี OK
- [ ] **(ค) โทเคนตายไม่เสียคำขอเพิ่ม** — สคริปต์ in-process: `rangers_api.call` `/home` ด้วย LF_AC สดของบัญชีที่
  เพิ่งสร้าง (200) แล้วตามด้วย `/home` ด้วย LF_AC ปลอม 5 ตัว โดยห่อ `rangers_api._send_raw` นับจำนวน
  → ต้องนับได้ 6 ครั้งพอดี (ไม่มี oracle และไม่มีการยิงซ้ำ)
- [ ] **(จ) build** — ใน `bot/` รันเฉพาะสองคำสั่งของ build.bat ขั้น [3/8] และ [4/8] (ไม่รันทั้ง build.bat เพราะ
  ขั้นท้ายถามแล้วอัปโหลดเวอร์ชันขึ้นเซิร์ฟเวอร์):
  `pyarmor gen --output dist_pyarmor main.py botLineRanger.py engine_main.py config_secure.py hwid.py protection.py engine ..\tools\account_file.py ..\tools\client_version.py ..\tools\device_session.py ..\tools\gacha.py ..\tools\new_account.py ..\tools\pull_roster.py ..\tools\rangers_api.py ..\tools\ratelimit.py ..\tools\relogin.py ..\tools\rewards.py ..\tools\stage_forge.py ..\tools\tutorial.py`
  แล้ว `pyinstaller --clean --noconfirm BotLineRanger.spec` → ใน `dist\BotLineRanger\` ต้องไม่มี
  `client_version.py` · สร้าง `dist\BotLineRanger\src\config.ini` (คัดจาก `bot\src\config.ini`) และ `input\` ว่าง
  แล้วรัน `dist\BotLineRanger\BotLineRanger.exe --engine ranger_api_Login` → ต้องจบเอง และ
  `dist\BotLineRanger\src\api_version.json` ต้องถูกสร้าง (พิสูจน์ว่าโมดูลอยู่ใน bundle และทำงานตอน frozen)
- [ ] บันทึกผลทั้งหมดลง `.superpowers/sdd/progress.md` และ memory `lgrgs-signup-needs-appversion-12-2-0`
  (เปลี่ยน How to apply ให้ชี้ไปที่ `client_version` แทน `SIGNUP_APP_VERSION`)
