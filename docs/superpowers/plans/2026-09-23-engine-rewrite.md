# แผนลงมือ: รื้อบอทเป็น engine เธรดเดียวไร้ ADB

> **สำหรับ agent ที่ลงมือ:** ต้องใช้ skill `superpowers:subagent-driven-development`
> (แนะนำ) หรือ `superpowers:executing-plans` ทำทีละ task ทุกขั้นเป็น checkbox (`- [ ]`)

**Goal:** เปลี่ยนบอทจาก 128 โปรเซส (5.5 GB · 181 บัญชี/นาที) เป็น engine โปรเซสเดียวที่ถือ
thread pool (ราว 400–700 MB · ~360 บัญชี/นาทีต่อ IP) พร้อมลบระบบ ADB ทิ้งทั้งหมดและทำให้
การเพิ่ม proxy เป็นการเติมบรรทัดใน config

**Architecture:** `tools/` ถือความรู้เรื่องโปรโตคอลเกมเหมือนเดิม · `bot/engine/` เป็นชั้นใหม่ที่
ถือคิวงาน เธรด และ proxy lane โดยไม่รู้จักโปรโตคอล · `bot/main.py` เหลือหน้าที่ตั้งค่า
สปอว์น engine หนึ่งตัว และแสดงผลจาก JSONL ที่ engine พ่นออก stdout · ไฟล์ `.xml`
ยังเป็นที่เก็บผลลัพธ์จริง มี journal กันงานค้างแทน lock file

**Tech Stack:** Python 3.11 · stdlib ล้วนในชั้น engine (`threading` `queue` `json` `http.client`)
· customtkinter สำหรับ GUI · PyInstaller + PyArmor สำหรับ build

**Spec:** [`../specs/2026-09-23-engine-rewrite-design.md`](../specs/2026-09-23-engine-rewrite-design.md)

**จุดเริ่ม:** branch `feat/engine-rewrite` แตกจาก `master` @ `b569399` working tree สะอาด

---

## Global Constraints

ข้อบังคับทั้งหมดนี้ใช้กับ **ทุก task** ไม่ต้องเขียนซ้ำในแต่ละข้อ

1. **ห้ามมี mutable state ระดับโมดูล** ในอะไรที่เธรดแตะ ทุกค่าส่งผ่านพารามิเตอร์หรือ instance
   attribute เท่านั้น — นี่คือเหตุผลทั้งหมดของงานรื้อรอบนี้
2. **ห้าม `git add -A`** `bot/input/` มี 24,279 ไฟล์และ `bot/output/` มี 19,769 ไฟล์ที่ถือ
   LF_AC จริง `git add` เฉพาะไฟล์ที่ task ระบุ
3. **เทสต์ห้ามแตะโฟลเดอร์จริง** (`bot/input` `bot/output` `bot/backup` `bot/execute`
   `bot/login failed` `bot/src/log`) ใช้ `tmp_path` เสมอ และต้อง monkeypatch ทุกตัวแปร path
   ระดับโมดูลที่โค้ดที่ทดสอบเอื้อมถึง
4. **เทสต์ห้ามยิงเซิร์ฟเวอร์เกมจริง** ห้ามเรียก `rangers_api.call` `relogin.login`
   `new_account.register_guest` ตัวจริง ให้ inject ตัวปลอมเสมอ
5. **ตัวปลอมต้องขาดสิ่งที่กำลังพิสูจน์** — stub ที่ใส่ค่าที่ต้องการกลับมาให้ทุกครั้งทำให้เทสต์
   เขียวเท่ากันทั้งตอนโค้ดถูกและผิด
6. **เทสต์ต้องยืนยันตัวตน ไม่ใช่จำนวน** — `assert len(x) == 3` เขียวแม้หยิบผิดตัว
7. **ห้ามแก้เทสต์ให้ผ่าน** ถ้าเทสต์ในแผนคาดผลผิดให้รายงานกลับมา ถ้าโค้ดต้องอ่อนข้อเรื่อง
   ความปลอดภัยเพื่อให้เขียว คำตอบคือปฏิเสธ
8. **คอมเมนต์อธิบาย "ทำไม" ไม่ใช่ "อะไร"** ทุกจุดที่ดูแปลกต้องมีบรรทัดบอกว่ามันกันอะไรไว้
   ภาษาไทยหรืออังกฤษก็ได้ แต่ถ้าใช้โมเดลราคาถูก **ให้คัดลอกข้อความไทยจาก brief เท่านั้น
   ห้ามแต่งเอง** (มันวางวรรณยุกต์ผิดแล้วรายงานว่าสำเร็จ)
9. **stderr ของงานเบื้องหลังต้องมีที่ลง** ห้าม `DEVNULL`
10. **แยก "รอคิว" ออกจาก "พัง"** — resource ไม่ว่างต้องรอแล้วลองใหม่ ทำไม่ได้จริงต้องเด้ง
    ถ้าปฏิบัติเหมือนกันหมด ระบบจะพังทั้งแถวจากเรื่องที่ควรแค่ช้าลง
11. **ทุกคำสั่ง Python รันด้วย `PYTHONUTF8=1`** คอนโซลเครื่องนี้เป็น cp1252 ข้อความไทย
    และอีโมจิจะตายที่ encoding ถ้าไม่ตั้ง
12. **ห้ามฆ่าโปรเซสด้วยชื่อ image** (`taskkill /IM python.exe`) ฆ่าได้เฉพาะ pid ที่ตัวเองสร้าง
13. Windows: `os.replace` ได้ `Access is denied` แปลว่ายังมี handle เปิดค้างบนปลายทาง
    `yield` ที่อยู่ใน `with open(...)` คือตัวการคลาสสิก
14. ทุก task จบด้วย `git commit` ของตัวเอง

**ลำดับ:** งานลบ ADB อยู่ที่ Task 11 ไม่ใช่ Task 1 ตามที่ spec เรียงไว้ — เพราะโค้ดเดิมคือ
**ตัวอ้างอิงเดียวที่มี** ว่าแต่ละ flow เรียกอะไรบ้าง ลบก่อนแล้วเขียนใหม่คือการเขียนจากความจำ

---

## โครงไฟล์

| ไฟล์ | หน้าที่ | task |
|---|---|---|
| `bot/engine/__init__.py` | ว่าง | 1 |
| `bot/engine/queue.py` | คิวงาน + journal + ย้ายไฟล์ | 1 |
| `tools/ratelimit.py` | เพิ่ม `TokenBucket` ในแรม เก็บของเดิมเป็น `FileTokenBucket` | 2 |
| `bot/engine/proxy.py` | `ProxyLane` · `ProxyPool` | 3 |
| `tools/rangers_api.py` | รับ lane ต่อเธรดแทน global | 4 |
| `tools/rewards.py` | รับ `/home` ที่ดึงแล้ว + ลดรอบสำรวจ | 5 |
| `tools/gacha.py` | cache `/gacha/info` | 6 |
| `bot/engine/session.py` | `AccountSession` · `Outcome` | 7 |
| `bot/engine/flows.py` | flow ทั้ง 4 โหมด | 7, 8 |
| `bot/engine/report.py` | JSONL ออก stdout | 9 |
| `bot/engine/pool.py` | thread pool + supervisor | 9 |
| `bot/engine_main.py` | entry ของ engine | 9 |
| `bot/main.py` | GUI สปอว์น engine | 10 |
| `bot/ADB.py` `bot/nemu_capture.py` `bot/bot_worker.py` | ลบ | 11 |
| `bot/BotLineRanger.spec` `bot/build.bat` | onedir | 12 |

---

## Task 1: WorkQueue + journal

**Files:**
- Create: `bot/engine/__init__.py`
- Create: `bot/engine/queue.py`
- Create: `bot/tests/__init__.py`
- Create: `bot/tests/test_queue.py`

**Interfaces:**
- Consumes: ไม่มี (ไม่พึ่ง task อื่น)
- Produces:
  ```python
  class WorkQueue:
      def __init__(self, root: str, journal_path: str) -> None
      def recover(self) -> int                                   # คืนจำนวนไฟล์ที่กู้กลับ input/
      def claim(self) -> str | None                              # path ใน execute/ หรือ None เมื่อคิวหมด
      def finish(self, src: str, dest: str, new_name: str = "") -> str
      def fail(self, src: str, reason: str) -> str
      def remaining(self) -> int
      def close(self) -> None
  DESTS = ("output", "backup", "login failed")
  ```

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `bot/tests/__init__.py` เป็นไฟล์ว่าง แล้วสร้าง `bot/tests/test_queue.py`:

```python
"""WorkQueue: คิวไฟล์บัญชี + journal ที่ทำให้งานค้างกลับมาได้

บั๊กที่เทสต์ชุดนี้กันไว้: รอบทดสอบที่ถูกฆ่ากลางทางทิ้งไฟล์ค้างใน execute/ ไว้ 128 ไฟล์
โดยไม่มีอะไรพากลับมา ไฟล์พวกนั้นหายจากทุกรอบถัดไปโดยไม่มีใครรู้
"""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.queue import WorkQueue  # noqa: E402


def build(tmp_path, names):
    for sub in ("input", "execute", "output", "backup", "login failed", "log"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for name in names:
        (tmp_path / "input" / name).write_text("<map/>", encoding="utf-8")
    return WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))


def test_claim_moves_the_file_into_execute_and_hands_back_its_path(tmp_path):
    q = build(tmp_path, ["a.xml"])
    got = q.claim()
    assert got == str(tmp_path / "execute" / "a.xml")
    assert os.path.isfile(got)
    assert not os.path.exists(tmp_path / "input" / "a.xml")


def test_claim_returns_none_when_the_queue_is_empty(tmp_path):
    q = build(tmp_path, [])
    assert q.claim() is None


def test_each_file_is_handed_out_exactly_once_under_concurrency(tmp_path):
    """ยืนยัน *ตัวตน* ไม่ใช่จำนวน: ถ้าสองเธรดได้ไฟล์เดียวกัน set จะสั้นกว่า list"""
    q = build(tmp_path, ["%03d.xml" % i for i in range(200)])
    got = []
    lock = threading.Lock()

    def worker():
        while True:
            path = q.claim()
            if path is None:
                return
            with lock:
                got.append(os.path.basename(path))

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 200
    assert len(set(got)) == 200


def test_finish_renames_into_the_destination_folder(tmp_path):
    q = build(tmp_path, ["a.xml"])
    src = q.claim()
    out = q.finish(src, "output", "brown_Rb10_Tk2_ID1_Lv3")
    assert out == str(tmp_path / "output" / "brown_Rb10_Tk2_ID1_Lv3.xml")
    assert os.path.isfile(out)
    assert not os.path.exists(src)


def test_finish_keeps_the_original_name_when_none_is_given(tmp_path):
    q = build(tmp_path, ["a.xml"])
    out = q.finish(q.claim(), "output")
    assert os.path.basename(out) == "a.xml"


def test_finish_rejects_a_folder_that_is_not_a_destination(tmp_path):
    """สะกดผิดต้องดังออกมา ไม่ใช่สร้างโฟลเดอร์ใหม่เงียบ ๆ แล้วไฟล์หายไปจากทุกคำสั่ง"""
    q = build(tmp_path, ["a.xml"])
    with pytest.raises(ValueError):
        q.finish(q.claim(), "outptu")


def test_fail_moves_into_login_failed_and_records_the_reason(tmp_path):
    q = build(tmp_path, ["a.xml"])
    out = q.fail(q.claim(), "HTTP 401")
    assert out == str(tmp_path / "login failed" / "a.xml")
    lines = [json.loads(x) for x in (tmp_path / "log" / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x for x in lines if x["t"] == "fail"][0]["why"] == "HTTP 401"


def test_recover_returns_a_claim_that_was_never_closed(tmp_path):
    """โปรเซสตายหลัง claim: ไฟล์ต้องกลับไป input/ ไม่ใช่ค้างใน execute/ ตลอดกาล"""
    q = build(tmp_path, ["a.xml", "b.xml"])
    q.claim()
    q.close()

    q2 = WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))
    assert q2.recover() == 1
    assert sorted(os.listdir(tmp_path / "input")) == ["a.xml", "b.xml"]
    assert os.listdir(tmp_path / "execute") == []


def test_recover_leaves_alone_a_claim_that_was_closed(tmp_path):
    q = build(tmp_path, ["a.xml"])
    q.finish(q.claim(), "output")
    q.close()
    q2 = WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))
    assert q2.recover() == 0
    assert os.listdir(tmp_path / "output") == ["a.xml"]


def test_recover_also_rescues_a_stray_file_with_no_journal_line(tmp_path):
    """ไฟล์ตกค้างจากบอทรุ่นก่อนไม่มีบรรทัดใน journal แต่ก็ต้องกลับมาเหมือนกัน"""
    q = build(tmp_path, [])
    (tmp_path / "execute" / "old.xml").write_text("<map/>", encoding="utf-8")
    assert q.recover() == 1
    assert os.listdir(tmp_path / "input") == ["old.xml"]


def test_recover_survives_a_journal_whose_last_line_was_cut_off(tmp_path):
    """โปรเซสถูกฆ่ากลางการเขียน บรรทัดสุดท้ายจึงไม่ใช่ JSON ที่สมบูรณ์"""
    q = build(tmp_path, ["a.xml"])
    q.claim()
    q.close()
    path = tmp_path / "log" / "run.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + '{"t":"cla', encoding="utf-8")
    q2 = WorkQueue(str(tmp_path), str(path))
    assert q2.recover() == 1


def test_remaining_counts_down_as_files_are_claimed(tmp_path):
    q = build(tmp_path, ["a.xml", "b.xml", "c.xml"])
    assert q.remaining() == 3
    q.claim()
    assert q.remaining() == 2
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_queue.py -q`
คาดผล: FAIL ทุกตัว ด้วย `ModuleNotFoundError: No module named 'engine'`

- [ ] **Step 3: เขียน `bot/engine/queue.py`**

สร้าง `bot/engine/__init__.py` เป็นไฟล์ว่าง แล้วสร้าง `bot/engine/queue.py`:

```python
"""คิวไฟล์บัญชี: input/ -> execute/ -> output/ | backup/ | login failed/

เลิกใช้ split-ID + .lock ของยุคหลายโปรเซส เพราะตอนนี้มี engine ตัวเดียว คิวจึงเป็น deque
ในแรมที่ป้องกันด้วย Lock ตัวเดียว การย้ายไฟล์ใช้เวลาไมโครวินาทีเทียบกับ 13 วินาทีที่แต่ละ
บัญชีใช้รอเน็ต มันจึงไม่มีทางเป็นคอขวด

journal มีไว้ตอบคำถามเดียว: "ไฟล์ไหนถูกหยิบไปแล้วยังไม่มีใครบอกว่าจบ" รอบทดสอบที่ถูกฆ่า
กลางทางทิ้งไฟล์ค้างใน execute/ ไว้ 128 ไฟล์ ซึ่งหายจากทุกรอบถัดไปโดยไม่มีใครรู้ - lock file
แก้เรื่องนี้ไม่ได้เพราะล็อกที่ค้างหลังโปรเซสตายก็ค้างเหมือนกัน
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time

DESTS = ("output", "backup", "login failed")


class WorkQueue:
    def __init__(self, root: str, journal_path: str) -> None:
        self.root = root
        self.journal_path = journal_path
        self._lock = threading.Lock()
        self._pending: collections.deque[str] = collections.deque()
        self._scanned = False
        os.makedirs(os.path.dirname(journal_path) or ".", exist_ok=True)
        for sub in ("input", "execute") + DESTS:
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        # buffering=1 = line buffered: บรรทัดถึงดิสก์ทันทีที่เขียนจบ ถ้าบัฟเฟอร์ค้าง
        # แล้วโปรเซสถูกฆ่า journal จะไม่รู้จัก claim ที่เพิ่งเกิด ซึ่งคือเคสที่มันมีไว้แก้พอดี
        self._journal = open(journal_path, "a", encoding="utf-8", buffering=1)

    # --- journal ---

    def _write(self, **row) -> None:
        row["ts"] = int(time.time())
        self._journal.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _open_claims(self) -> set:
        """ชื่อไฟล์ที่มีบรรทัด claim แต่ไม่มีบรรทัดปิด"""
        if not os.path.isfile(self.journal_path):
            return set()
        open_ = set()
        with open(self.journal_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    # บรรทัดสุดท้ายถูกตัดกลางคันตอนโปรเซสถูกฆ่า - ข้ามไป ไม่ใช่ล้มทั้ง recover
                    continue
                name = row.get("f")
                if not name:
                    continue
                if row.get("t") == "claim":
                    open_.add(name)
                else:
                    open_.discard(name)
        return open_

    # --- งานหลัก ---

    def recover(self) -> int:
        """คืนไฟล์ที่ค้างใน execute/ กลับ input/ คืนจำนวนที่กู้ได้

        กู้ทุกไฟล์ที่อยู่ใน execute/ ไม่ใช่เฉพาะที่มีบรรทัดค้างใน journal เพราะไฟล์ที่
        ตกค้างจากบอทรุ่นก่อน (ยุค split-ID) ไม่มีบรรทัดใน journal เลย แต่ก็ต้องกลับมาเหมือนกัน
        """
        execute = os.path.join(self.root, "execute")
        stale = self._open_claims()
        moved = 0
        for name in sorted(os.listdir(execute)):
            if not name.endswith(".xml"):
                continue
            src = os.path.join(execute, name)
            dst = os.path.join(self.root, "input", name)
            try:
                os.replace(src, dst)
            except OSError:
                continue
            self._write(t="recover", f=name, known=name in stale)
            moved += 1
        return moved

    def _scan(self) -> None:
        folder = os.path.join(self.root, "input")
        self._pending.extend(
            sorted(n for n in os.listdir(folder) if n.endswith(".xml")))
        self._scanned = True

    def claim(self) -> str | None:
        with self._lock:
            if not self._scanned:
                self._scan()
            while self._pending:
                name = self._pending.popleft()
                src = os.path.join(self.root, "input", name)
                dst = os.path.join(self.root, "execute", name)
                try:
                    os.replace(src, dst)
                except OSError:
                    continue      # ไฟล์หายไประหว่างทาง (คนลบเอง) - ข้ามไปตัวถัดไป
                self._write(t="claim", f=name)
                return dst
            return None

    def _close(self, src: str, dest: str, new_name: str, **extra) -> str:
        if dest not in DESTS:
            raise ValueError("unknown destination %r (expected one of %r)" % (dest, DESTS))
        name = os.path.basename(src)
        out_name = (new_name + ".xml") if new_name else name
        out = os.path.join(self.root, dest, out_name)
        os.replace(src, out)
        with self._lock:
            self._write(f=name, dest=dest, **extra)
        return out

    def finish(self, src: str, dest: str, new_name: str = "") -> str:
        return self._close(src, dest, new_name, t="done")

    def fail(self, src: str, reason: str) -> str:
        return self._close(src, "login failed", "", t="fail", why=str(reason)[:200])

    def remaining(self) -> int:
        with self._lock:
            if not self._scanned:
                self._scan()
            return len(self._pending)

    def close(self) -> None:
        try:
            self._journal.close()
        except Exception:
            pass
```

- [ ] **Step 4: รันเทสต์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_queue.py -q`
คาดผล: PASS ทั้ง 12 ตัว

- [ ] **Step 5: พิสูจน์ว่าเทสต์จับบั๊กได้จริง**

แก้ `claim()` ชั่วคราวให้ใช้ `self._pending[0]` แทน `popleft()` แล้วรันเทสต์ใหม่
คาดผล: `test_each_file_is_handed_out_exactly_once_under_concurrency` ต้อง **แดง**
จากนั้นย้อนกลับแล้วรันอีกครั้งให้เขียว — เทสต์ที่ไม่เคยเห็นแดงคือเทสต์ที่ยังพิสูจน์ไม่ได้

- [ ] **Step 6: Commit**

```bash
git add bot/engine/__init__.py bot/engine/queue.py bot/tests/__init__.py bot/tests/test_queue.py
git commit -m "feat(engine): a work queue that gives every account file back after a crash"
```

---

## Task 2: TokenBucket ในแรม

**Files:**
- Modify: `tools/ratelimit.py` (เพิ่ม `TokenBucket`, เปลี่ยนชื่อ `IpBucket` → `FileTokenBucket`)
- Modify: `tools/tests/test_ratelimit.py`

**Interfaces:**
- Consumes: ไม่มี
- Produces:
  ```python
  class TokenBucket:
      def __init__(self, rate: float, burst: int | None = None,
                   clock=time.monotonic, sleep=time.sleep) -> None
      def acquire(self) -> None
  FileTokenBucket = <คลาสเดิมที่ชื่อ IpBucket>
  ```

**เหตุผล:** `IpBucket` ปัจจุบันเปิด/ล็อก/ปิดไฟล์ทุกครั้งที่ขอ token เพราะต้องกันข้าม 128 โปรเซส
เหลือโปรเซสเดียวแล้วต้นทุนนั้นไม่มีเหตุผล และที่สำคัญกว่าคือเส้นทาง `LockTimeout`
กับ `_disabled` หายไปทั้งคลาส **ห้ามลบของเดิมทิ้ง** เก็บไว้เป็น `FileTokenBucket`
เผื่อวันที่ต้องรันสองเครื่องแชร์ proxy pool กัน

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

เพิ่มท้าย `tools/tests/test_ratelimit.py`:

```python
def test_token_bucket_hands_out_the_burst_without_waiting():
    clock, waits = _FakeClock(), []
    b = ratelimit.TokenBucket(rate=10, burst=5, clock=clock, sleep=waits.append)
    for _ in range(5):
        b.acquire()
    assert waits == []


def test_token_bucket_paces_at_the_configured_rate_once_the_burst_is_spent():
    """เกินเบิร์สต์แล้วต้องรอ 1/rate ต่อ token ไม่ใช่ปล่อยผ่าน"""
    clock, waits = _FakeClock(), []
    b = ratelimit.TokenBucket(rate=10, burst=1, clock=clock, sleep=lambda s: (waits.append(s), clock.advance(s)))
    b.acquire()
    b.acquire()
    assert waits and abs(sum(waits) - 0.1) < 0.01


def test_token_bucket_never_waits_when_time_has_already_passed():
    clock, waits = _FakeClock(), []
    b = ratelimit.TokenBucket(rate=10, burst=1, clock=clock, sleep=waits.append)
    b.acquire()
    clock.advance(5.0)
    b.acquire()
    assert waits == []


def test_token_bucket_hands_each_token_to_exactly_one_thread():
    """เบิร์สต์ 50 ใบกับ 20 เธรดที่ขอคนละ 5 ใบ: ต้องไม่มีใครได้ token ผีเพิ่ม"""
    import threading
    b = ratelimit.TokenBucket(rate=1000, burst=50)
    got = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            b.acquire()
            with lock:
                got.append(1)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(got) == 100


def test_the_old_file_backed_bucket_is_still_available_under_its_new_name():
    """ของเดิมต้องไม่หาย มันคือทางเดียวที่กันข้ามโปรเซสได้ถ้าวันหนึ่งต้องกลับไปหลาย engine"""
    assert hasattr(ratelimit, "FileTokenBucket")
    assert hasattr(ratelimit.FileTokenBucket, "acquire")
```

ถ้าไฟล์ยังไม่มี `_FakeClock` ให้เพิ่มไว้บนสุด:

```python
class _FakeClock:
    """นาฬิกาที่เดินเฉพาะตอนถูกสั่ง - เทสต์เรื่องเวลาที่ใช้ time.sleep จริงจะช้าและแกว่ง"""
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/test_ratelimit.py -q`
คาดผล: FAIL ด้วย `AttributeError: module 'ratelimit' has no attribute 'TokenBucket'`

- [ ] **Step 3: เพิ่ม `TokenBucket` ลง `tools/ratelimit.py`**

แทรกก่อนบรรทัด `class IpBucket:`

```python
class TokenBucket:
    """ถังโทเคนในแรม คุมอัตรา request ของ IP หนึ่งเส้น

    ใช้แทน IpBucket (ที่ตอนนี้ชื่อ FileTokenBucket) ตั้งแต่บอทเหลือ engine โปรเซสเดียว
    ของเดิมต้องเปิด/ล็อก/เขียน/ปิดไฟล์ทุกครั้งที่ขอหนึ่งโทเคน เพราะเป็นทางเดียวที่ 128
    โปรเซสจะแชร์งบกันได้ พอทุกเธรดอยู่ในโปรเซสเดียวกัน Lock ตัวเดียวก็พอ และเส้นทาง
    LockTimeout / ปิดถังถาวรหลังพลาด 3 ครั้ง หายไปทั้งหมด
    """

    def __init__(self, rate: float, burst: int | None = None,
                 clock=time.monotonic, sleep=time.sleep) -> None:
        self.rate = max(0.001, float(rate))
        self.burst = max(1, int(burst if burst is not None else BURST))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = float(self.burst)
        self._stamp = clock()

    def acquire(self) -> None:
        """รอจนถึงคิวของตัวเองแล้วหักหนึ่งโทเคน

        คำนวณเวลาที่ต้องรอ *ในล็อก* แล้วหักโทเคนทันที ส่วนการ sleep ทำนอกล็อก
        ไม่งั้นเธรดที่กำลังรอจะกันเธรดอื่นไม่ให้แม้แต่จองคิว แล้วอัตราจริงจะตกต่ำกว่า
        ที่ตั้งไว้มากเมื่อเธรดเยอะ
        """
        while True:
            with self._lock:
                now = self._clock()
                self._tokens = min(self.burst, self._tokens + (now - self._stamp) * self.rate)
                self._stamp = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            self._sleep(wait)
```

- [ ] **Step 4: เปลี่ยนชื่อคลาสเดิมและคง alias ไว้**

ใน `tools/ratelimit.py` เปลี่ยน `class IpBucket:` เป็น `class FileTokenBucket:` แล้วเพิ่ม
ใต้คลาสนั้น:

```python
# ชื่อเดิมของ FileTokenBucket สมัยที่บอทยังเป็น 128 โปรเซส เก็บไว้ให้โค้ดเก่าที่ยัง
# อ้างถึงมันระหว่างการรื้อยังทำงานได้ ลบได้เมื่อ Task 11 ลบผู้เรียกกลุ่มสุดท้ายแล้ว
IpBucket = FileTokenBucket
```

- [ ] **Step 5: รันเทสต์ทั้งไฟล์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/test_ratelimit.py -q`
คาดผล: PASS ทั้งหมด รวมเทสต์เดิมที่ยังอ้าง `IpBucket`

- [ ] **Step 6: Commit**

```bash
git add tools/ratelimit.py tools/tests/test_ratelimit.py
git commit -m "feat(ratelimit): an in-process token bucket, with the file-backed one kept for many engines"
```

---

## Task 3: ProxyLane และ ProxyPool

**Files:**
- Create: `bot/engine/proxy.py`
- Create: `bot/tests/test_proxy.py`

**Interfaces:**
- Consumes: `ratelimit.TokenBucket` (task 2) · `ratelimit.proxy_parts` (มีอยู่แล้ว)
- Produces:
  ```python
  class ProxyLane:
      name: str                 # "direct" หรือ "host:port"
      parts: tuple | None       # (host, port, auth) หรือ None = ต่อตรง
      threads: int
      alive: bool
      def acquire(self) -> None
      def note_ok(self) -> None
      def note_fail(self) -> bool        # True = lane นี้เพิ่งตาย
  class ProxyPool:
      def __init__(self, proxies, rps, threads_per, max_threads=4096, clock=..., sleep=...)
      lanes: list[ProxyLane]
      capped: int                        # เธรดที่ถูกตัดเพราะชนเพดาน 0 = ไม่โดนตัด
      def alive_lanes(self) -> list[ProxyLane]
      def total_threads(self) -> int
  LANE_DEATH = 3                          # connect fail ติดกันกี่ครั้งถึงถอด
  ```

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `bot/tests/test_proxy.py`:

```python
"""ProxyPool: แบ่งงบ request และจำนวนเธรดตาม IP

บั๊กที่ชุดนี้กันไว้: เพดานเธรดที่ถูกตัดเงียบ ๆ ทำให้ผู้ใช้เชื่อว่าตั้ง 50 proxy x 96 เธรด
แล้วได้ 4,800 เธรดจริง ทั้งที่ระบบหั่นลงเหลือ 4,096 - "สูงสุดที่วัดได้" ไม่ใช่ "ที่ตั้งไว้"
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine.proxy import ProxyLane, ProxyPool, LANE_DEATH  # noqa: E402


def test_no_proxy_configured_gives_one_direct_lane():
    pool = ProxyPool([], rps=90, threads_per=96)
    assert [x.name for x in pool.lanes] == ["direct"]
    assert pool.lanes[0].parts is None


def test_each_proxy_becomes_its_own_lane_with_its_own_budget():
    pool = ProxyPool(["1.1.1.1:8000", "2.2.2.2:8000"], rps=90, threads_per=96)
    assert [x.name for x in pool.lanes] == ["1.1.1.1:8000", "2.2.2.2:8000"]
    assert pool.lanes[0].bucket is not pool.lanes[1].bucket


def test_a_proxy_with_credentials_keeps_them_out_of_the_lane_name():
    """ชื่อ lane ไปโผล่ใน log และบนหน้าจอ รหัสผ่านต้องไม่ติดไปด้วย"""
    pool = ProxyPool(["1.1.1.1:8000:bob:hunter2"], rps=90, threads_per=96)
    assert pool.lanes[0].name == "1.1.1.1:8000"
    assert "hunter2" not in pool.lanes[0].name


def test_threads_are_shared_out_per_lane():
    pool = ProxyPool(["1.1.1.1:8000", "2.2.2.2:8000"], rps=90, threads_per=96)
    assert [x.threads for x in pool.lanes] == [96, 96]
    assert pool.total_threads() == 192
    assert pool.capped == 0


def test_the_total_thread_ceiling_cuts_every_lane_and_says_how_much():
    """เกิน 4,096 เธรดแล้วงาน *ลดลง* ไม่ใช่แค่ไม่เพิ่ม - ตัดได้ แต่ต้องบอก"""
    pool = ProxyPool(["%d.1.1.1:8000" % i for i in range(50)], rps=90,
                     threads_per=96, max_threads=4096)
    assert pool.total_threads() <= 4096
    assert pool.capped == 50 * 96 - pool.total_threads()
    assert all(x.threads >= 1 for x in pool.lanes)


def test_a_lane_dies_only_after_three_failures_in_a_row():
    lane = ProxyLane("1.1.1.1:8000", None, rps=90, threads=8)
    for _ in range(LANE_DEATH - 1):
        assert lane.note_fail() is False
        assert lane.alive
    assert lane.note_fail() is True
    assert not lane.alive


def test_one_success_clears_the_failure_streak():
    """โปรเซสอื่นแย่งสายหลุดหนึ่งครั้งไม่ใช่ proxy ตาย ต้องไม่สะสมข้ามเวลา"""
    lane = ProxyLane("1.1.1.1:8000", None, rps=90, threads=8)
    lane.note_fail()
    lane.note_fail()
    lane.note_ok()
    assert lane.note_fail() is False
    assert lane.alive


def test_alive_lanes_drops_the_dead_one():
    pool = ProxyPool(["1.1.1.1:8000", "2.2.2.2:8000"], rps=90, threads_per=8)
    for _ in range(LANE_DEATH):
        pool.lanes[0].note_fail()
    assert [x.name for x in pool.alive_lanes()] == ["2.2.2.2:8000"]


def test_a_malformed_proxy_line_is_refused_loudly():
    """ยอมรับเงียบ ๆ แปลว่า worker ตายทีหลังโดยผู้ใช้เห็นแค่ 0 thread"""
    with pytest.raises(ValueError):
        ProxyPool(["not-a-proxy"], rps=90, threads_per=8)
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_proxy.py -q`
คาดผล: FAIL ด้วย `ModuleNotFoundError: No module named 'engine.proxy'`

- [ ] **Step 3: เขียน `bot/engine/proxy.py`**

```python
"""1 proxy = 1 IP = 1 งบ request = กลุ่มเธรดของตัวเอง

เพดานของเกมคือ ~100 req/s ต่อ IP การเพิ่มเธรดบน IP เดิมจึงไม่ได้งานเพิ่ม ได้แค่คิวที่ยาวขึ้น
สิ่งที่เพิ่มงานได้จริงมีอย่างเดียวคือเพิ่ม IP โครงนี้จึงผูกงบกับ lane ไม่ใช่กับทั้งโปรแกรม
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))
import ratelimit  # noqa: E402

# connect ไม่ติดกี่ครั้งติดกันถึงถือว่า proxy ตาย หนึ่งครั้งคือสายหลุดธรรมดา ซึ่งเกิดได้
# ตลอดเวลาบนเน็ตที่ปกติดี ถอด lane เพราะเรื่องนั้นคือการตัดกำลังตัวเองฟรี ๆ
LANE_DEATH = 3


class ProxyLane:
    def __init__(self, name: str, parts, rps: float, threads: int,
                 clock=None, sleep=None) -> None:
        self.name = name
        self.parts = parts
        self.threads = threads
        self.alive = True
        kw = {}
        if clock is not None:
            kw["clock"] = clock
        if sleep is not None:
            kw["sleep"] = sleep
        self.bucket = ratelimit.TokenBucket(rate=rps, **kw)
        self._lock = threading.Lock()
        self._fails = 0

    def acquire(self) -> None:
        self.bucket.acquire()

    def note_ok(self) -> None:
        with self._lock:
            self._fails = 0

    def note_fail(self) -> bool:
        """คืน True เฉพาะครั้งที่ทำให้ lane ตาย ผู้เรียกจะได้รายงานครั้งเดียว ไม่ใช่ทุกครั้ง"""
        with self._lock:
            self._fails += 1
            if self._fails >= LANE_DEATH and self.alive:
                self.alive = False
                return True
            return False

    def revive(self) -> None:
        with self._lock:
            self._fails = 0
            self.alive = True


class ProxyPool:
    def __init__(self, proxies, rps: float, threads_per: int,
                 max_threads: int = 4096, clock=None, sleep=None) -> None:
        entries = [p.strip() for p in (proxies or []) if p and p.strip()]
        self.lanes: list[ProxyLane] = []
        if not entries:
            self.lanes.append(ProxyLane("direct", None, rps, threads_per, clock, sleep))
        else:
            for entry in entries:
                # proxy_parts โยน ValueError เมื่อรูปแบบผิด ปล่อยให้ขึ้นไปถึงผู้เรียก:
                # ยอมรับเงียบ ๆ แปลว่า engine สตาร์ทแล้ววิ่งผ่าน IP ของเครื่องตัวเองแทน
                parts = ratelimit.proxy_parts(entry)
                host, port = parts[0], parts[1]
                self.lanes.append(
                    ProxyLane("%s:%s" % (host, port), parts, rps, threads_per, clock, sleep))

        wanted = sum(x.threads for x in self.lanes)
        self.capped = 0
        if wanted > max_threads:
            # หารเฉลี่ยลงมา อย่างน้อย lane ละ 1 เธรด แล้วบันทึกส่วนต่างไว้ให้ผู้เรียกบอกผู้ใช้
            per = max(1, max_threads // len(self.lanes))
            for lane in self.lanes:
                lane.threads = per
            self.capped = wanted - sum(x.threads for x in self.lanes)

    def alive_lanes(self) -> list[ProxyLane]:
        return [x for x in self.lanes if x.alive]

    def total_threads(self) -> int:
        return sum(x.threads for x in self.lanes)
```

- [ ] **Step 4: รันเทสต์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_proxy.py -q`
คาดผล: PASS ทั้ง 9 ตัว

- [ ] **Step 5: Commit**

```bash
git add bot/engine/proxy.py bot/tests/test_proxy.py
git commit -m "feat(engine): one request budget and thread group per proxy, with a stated thread ceiling"
```

---

## Task 4: `rangers_api` รับ lane ต่อเธรด

**Files:**
- Modify: `tools/rangers_api.py`
- Modify: `tools/tests/test_rangers_api.py`

**Interfaces:**
- Consumes: `ProxyLane` (task 3) — แต่รับเป็น duck type ไม่ import เพื่อไม่ให้ `tools/`
  ต้องรู้จัก `bot/`
- Produces:
  ```python
  def use_lane(lane) -> None        # ผูก lane เข้ากับเธรดปัจจุบัน
  def current_lane()                # lane ของเธรดนี้ หรือ None
  def call(cookie, path, method="GET", body=None, api=None) -> (status, parsed)
  ```

**เหตุผล:** วันนี้ `rangers_api` อ่าน `ratelimit.PROXY_PARTS` ซึ่งเป็นค่าระดับโมดูลที่ตั้ง
ครั้งเดียวตอน import — ถูกต้องเมื่อหนึ่งโปรเซสใช้หนึ่ง proxy แต่ผิดทันทีที่โปรเซสเดียว
ต้องวิ่งหลาย IP พร้อมกัน connection ก็เป็น thread-local อยู่แล้ว lane จึงต้องเป็น
thread-local คู่กัน ไม่งั้นเธรดจะได้ socket ของ IP หนึ่งแต่จ่ายงบของอีก IP

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

เพิ่มท้าย `tools/tests/test_rangers_api.py`:

```python
def test_each_thread_keeps_its_own_lane():
    """สองเธรดที่ผูกคนละ lane ต้องไม่เห็น lane ของกันและกัน"""
    import threading
    seen = {}

    class Lane:
        def __init__(self, name):
            self.name, self.parts = name, None
        def acquire(self): pass
        def note_ok(self): pass
        def note_fail(self): return False

    def work(name):
        rangers_api.use_lane(Lane(name))
        seen[name] = rangers_api.current_lane().name

    ts = [threading.Thread(target=work, args=("lane-%d" % i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert seen == {"lane-%d" % i: "lane-%d" % i for i in range(4)}


def test_call_takes_a_token_from_the_lane_of_this_thread(monkeypatch):
    taken = []

    class Lane:
        name, parts = "L", None
        def acquire(self): taken.append(1)
        def note_ok(self): pass
        def note_fail(self): return False

    rangers_api.use_lane(Lane())
    monkeypatch.setattr(rangers_api, "_get_conn", lambda: _FakeConn(200, b'{"result":{}}'))
    rangers_api.call("LF_AC=x", "/home")
    assert taken == [1]


def test_a_socket_failure_is_reported_to_the_lane(monkeypatch):
    """lane ต้องรู้ว่า proxy ของมันต่อไม่ติด ไม่งั้น proxy ตายแล้วยังถูกแจกงานต่อ"""
    marks = []

    class Lane:
        name, parts = "L", None
        def acquire(self): pass
        def note_ok(self): marks.append("ok")
        def note_fail(self): marks.append("fail"); return False

    rangers_api.use_lane(Lane())

    def boom():
        raise OSError("connect refused")

    monkeypatch.setattr(rangers_api, "_get_conn", boom)
    monkeypatch.setattr(rangers_api, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(rangers_api, "_retry_sleep", lambda *a, **k: None)
    with pytest.raises(OSError):
        rangers_api.call("LF_AC=x", "/home")
    assert "fail" in marks
```

ถ้ายังไม่มี `_FakeConn` ในไฟล์ ให้เพิ่มไว้บนสุด:

```python
class _FakeResp:
    def __init__(self, status, body):
        self.status, self._body = status, body
    def read(self): return self._body
    def getheader(self, name): return None


class _FakeConn:
    """ตัวปลอมที่ *ไม่มี* keep-alive จริงและไม่มี bucket ในตัว - สิ่งที่กำลังพิสูจน์
    คือ call() ไปเอา token จาก lane ไม่ใช่จากที่อื่น ตัวปลอมจึงต้องไม่แจก token เอง"""
    def __init__(self, status=200, body=b'{"result":{}}'):
        self.status, self.body = status, body
    def request(self, *a, **k): pass
    def getresponse(self): return _FakeResp(self.status, self.body)
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/test_rangers_api.py -q`
คาดผล: FAIL ด้วย `AttributeError: module 'rangers_api' has no attribute 'use_lane'`

- [ ] **Step 3: เพิ่ม lane แบบ thread-local**

ใน `tools/rangers_api.py` แทนที่บล็อก `_conn_tls = threading.local()` ถึงท้าย `_drop_conn()`
ด้วย:

```python
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
```

- [ ] **Step 4: ให้ `call()` ใช้ lane แทน bucket ระดับโมดูล**

ใน `call()` แทนที่ `bucket = ratelimit.bucket_for(HOST)` ด้วย:

```python
    lane = current_lane()
```

แทนที่คู่บรรทัด `ratelimit.PACER.wait(cookie)` / `bucket.acquire()` ด้วย:

```python
        ratelimit.PACER.wait(cookie)
        if lane is not None:
            lane.acquire()
        else:
            ratelimit.bucket_for(HOST).acquire()   # เส้นทาง CLI: ไม่มี lane ใช้ถังไฟล์แบบเดิม
```

ในบล็อก `except (http.client.HTTPException, OSError):` เพิ่มเป็นบรรทัดแรกของบล็อก:

```python
            if lane is not None:
                lane.note_fail()
```

และหลัง `ratelimit.PACER.done(cookie)` เพิ่ม:

```python
        if lane is not None:
            lane.note_ok()     # ตอบกลับมาได้ = proxy ยังดี ล้างสตรีคความพังทิ้ง
```

- [ ] **Step 5: รันเทสต์ทั้งไฟล์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/ -q`
คาดผล: PASS ทั้งหมด (เทสต์เดิมที่ไม่ตั้ง lane ต้องยังเขียว เพราะเส้นทาง `lane is None`
ทำงานเหมือนเดิมทุกประการ)

- [ ] **Step 6: Commit**

```bash
git add tools/rangers_api.py tools/tests/test_rangers_api.py
git commit -m "feat(api): the proxy a call goes out on is the thread's, not the module's"
```

---

## Task 5: ลดจำนวน request ใน `rewards.py`

**Files:**
- Modify: `tools/rewards.py`
- Create: `tools/tests/test_rewards.py`

**Interfaces:**
- Consumes: ไม่มี
- Produces:
  ```python
  def check_session(cookie, home=None) -> dict          # home ที่ดึงมาแล้ว = ไม่ยิงซ้ำ
  def survey(cookie, home=None) -> list
  def claim_all(cookie, confirm=True, passes=3, home=None) -> int
  ```

**ที่มาของตัวเลข** (นับจากโค้ดปัจจุบัน):

| เส้นทาง | request วันนี้ | หลังแก้ |
|---|---|---|
| บัญชีที่ไม่มีของให้เก็บ | 16 | 13 |
| บัญชีที่มีของเก็บครบทุกรอบ | 38 | 20 |

`/home` ถูกยิง **4 ครั้งต่อบัญชี** วันนี้: `check_session` · `survey_attendance_package`
· `currentLevel` · `getRubyAndTicket` — สามตัวหลังเป็นคนละฟังก์ชันที่ต่างคนต่างดึง
ก้อนเดียวกัน

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `tools/tests/test_rewards.py`:

```python
"""rewards: เลิกถามซ้ำสิ่งที่รู้คำตอบแล้ว โดยไม่เก็บของได้น้อยลง

บั๊กที่ชุดนี้กันไว้: การ "ประหยัด request" ที่ทำให้ของที่เคยเก็บได้หายไปเงียบ ๆ
เทสต์จึงตรวจสองอย่างคู่กันเสมอ - จำนวน request *และ* รายการที่เก็บได้
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApi:
    """ตัวปลอมที่จดทุก path ที่ถูกเรียก

    *ไม่* จำว่าเคยตอบอะไรไปแล้ว ทุกการเรียกจึงต้องเป็นการเรียกจริง ๆ ที่นับได้ -
    ถ้ามันแคชให้เอง เทสต์จะเขียวเท่ากันทั้งตอนโค้ดยิงซ้ำและไม่ยิงซ้ำ
    """

    def __init__(self, gifts=1):
        self.calls = []
        self.gifts = gifts

    def __call__(self, cookie, path, method="GET", body=None, api=None):
        self.calls.append((method, path.split("?")[0]))
        if path.startswith("/giftbox/list"):
            pending = [{"giftSn": i, "giftName": "g%d" % i, "giftCount": 1, "receive": False}
                       for i in range(self.gifts)]
            return 200, {"result": {"giftBox": {"gift": {"playerGifts": pending}}}}
        if path.startswith("/giftbox/gift/receive/all"):
            self.gifts = 0
            return 200, {"result": {}}
        if path == "/home":
            return 200, {"result": {"player": {"rsn": "ID1", "level": 3},
                                    "rubyBalance": {"total": 10}}}
        return 200, {"result": {}}

    def count(self, path):
        return sum(1 for _m, p in self.calls if p == path)


def test_check_session_does_not_refetch_home_when_it_is_handed_one(monkeypatch):
    rewards = load("rewards")
    api = FakeApi()
    monkeypatch.setattr(rewards, "call", api)
    home = {"player": {"rsn": "ID1", "level": 3}}
    assert rewards.check_session("c", home=home)["rsn"] == "ID1"
    assert api.count("/home") == 0


def test_check_session_still_fetches_home_when_given_nothing(monkeypatch):
    rewards = load("rewards")
    api = FakeApi()
    monkeypatch.setattr(rewards, "call", api)
    assert rewards.check_session("c")["rsn"] == "ID1"
    assert api.count("/home") == 1


def test_survey_asks_home_once_even_though_two_collectors_want_it(monkeypatch):
    rewards = load("rewards")
    api = FakeApi()
    monkeypatch.setattr(rewards, "call", api)
    rewards.survey("c", home={"player": {}, "rubyBalance": {}})
    assert api.count("/home") == 0


def test_the_second_pass_only_rechecks_the_gift_box(monkeypatch):
    """ระบบอื่นจ่ายของ *เข้า* กล่อง ไม่ได้จ่ายเข้าหากัน รอบสองจึงมีแค่กล่องที่เปลี่ยน"""
    rewards = load("rewards")
    api = FakeApi(gifts=2)
    monkeypatch.setattr(rewards, "call", api)
    rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert api.count("/mission/list/new/") == 1
    assert api.count("/dailyquest") == 1
    assert api.count("/pass/main") == 1


def test_the_gift_box_is_not_listed_twice_inside_one_claim(monkeypatch):
    """claim_giftbox เคยดึงรายการก่อนและหลัง ทั้งที่ survey เพิ่งดึงมาให้แล้ว"""
    rewards = load("rewards")
    api = FakeApi(gifts=1)
    monkeypatch.setattr(rewards, "call", api)
    rewards.claim_all("c", confirm=True, passes=1, home={"player": {}, "rubyBalance": {}})
    assert api.count("/giftbox/list") <= 2


def test_an_account_with_nothing_to_claim_costs_no_more_than_thirteen_calls(monkeypatch):
    rewards = load("rewards")
    api = FakeApi(gifts=0)
    monkeypatch.setattr(rewards, "call", api)
    rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert len(api.calls) <= 11, api.calls


def test_the_gifts_are_still_all_claimed(monkeypatch):
    """ตัวเลขที่ลดลงต้องไม่แลกมาด้วยของที่เก็บไม่ครบ"""
    rewards = load("rewards")
    api = FakeApi(gifts=3)
    monkeypatch.setattr(rewards, "call", api)
    total = rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert total >= 1
    assert api.gifts == 0
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/test_rewards.py -q`
คาดผล: FAIL — `check_session() got an unexpected keyword argument 'home'`

- [ ] **Step 3: ให้ `check_session` และ collector รับ `/home` ที่ดึงมาแล้ว**

ใน `tools/rewards.py` แทนที่ `check_session` ด้วย:

```python
def check_session(cookie, home=None):
    """Fail loudly on a dead token.

    Every collector treats a non-200 as "nothing here", so an expired session would
    otherwise render as a clean "nothing to claim" - the most misleading output this
    tool could produce.

    `home` lets a caller that already fetched /home hand it over. One account used to
    pay for that same payload four times (here, in survey_attendance_package, in
    currentLevel and in getRubyAndTicket) - the single most repeated call in the bot.
    """
    if home is None:
        status, data = call(cookie, "/home")
        if not (status == 200 and isinstance(data, dict) and "result" in data):
            raise SystemExit(
                "session rejected (HTTP %s) - the token in this account file is stale.\n"
                "LF_AC changes every time the game is launched; refresh it with:\n"
                "  python tools/account_file.py --from-device --device <serial> --out <that .xml>"
                % status)
        home = data["result"]
    return home["player"]
```

แทนที่ `survey_attendance_package` เดิมให้รับ `home`:

```python
def survey_attendance_package(cookie, home=None):
    result = home if home is not None else _get(cookie, "/home")
    if not result:
        return []
    return _attendance_jobs(result)
```

> หมายเหตุสำหรับผู้ลงมือ: ย้ายเนื้อเดิมของ `survey_attendance_package` ที่อยู่หลัง
> `result = _get(cookie, "/home")` ไปเป็นฟังก์ชัน `_attendance_jobs(result)` แบบคำต่อคำ
> ห้ามเขียนตรรกะใหม่ ให้เป็นการย้ายล้วน

- [ ] **Step 4: ให้ `survey()` ส่ง `home` ต่อ และ `claim_all` ลดรอบ**

แทนที่ `SOURCES` · `survey` · `claim_all` ด้วย:

```python
# ตัวที่ต้องถามใหม่ทุกรอบมีแค่กล่องของขวัญ ระบบที่เหลือจ่ายของ *เข้า* กล่อง ไม่ได้จ่าย
# เข้าหากัน การสำรวจครบเจ็ดแหล่งในรอบสองจึงเป็นการถามคำถามที่รู้คำตอบแล้วหกครั้ง
SOURCES = [
    ("login popups", survey_popups),
    ("gift box", survey_giftbox),
    ("7-day event", survey_sevendays),
    ("daily quest", survey_dailyquest),
    ("missions", survey_missions),
    ("attendance package", survey_attendance_package),
    ("rangers pass", survey_pass),
]
REFRESH_SOURCES = [("gift box", survey_giftbox)]


def survey(cookie, home=None, sources=None):
    """Collect claim jobs from every source.

    The collectors are independent read-only GETs, so they run concurrently: run
    back to back they cost the SUM of every round trip (~4.2s measured, with the
    popup call alone ~1.5s), in parallel only the slowest one.
    """
    sources = SOURCES if sources is None else sources
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        pending = []
        for label, collect in sources:
            if collect is survey_attendance_package:
                pending.append((label, pool.submit(collect, cookie, home)))
            else:
                pending.append((label, pool.submit(collect, cookie)))
        results = []
        for label, future in pending:
            try:
                results.append((label, future.result(), None))
            except Exception as err:        # one dead system must not sink the whole sweep
                results.append((label, [], err))

    jobs = []
    for label, found, err in results:
        if err is not None:
            print("  %-20s error: %s" % (label, str(err)[:70]))
            continue
        print("  %-20s %s" % (label, "%d claimable" % len(found) if found else "-"))
        jobs.extend(found)
    return jobs


def claim_all(cookie, confirm=True, passes=3, home=None):
    """Sweep every reward source and claim what is claimable. Returns how many were taken.

    Pass 1 surveys everything. Later passes re-check only the gift box, because that is
    the one place the other systems deposit into - nothing else can have gained an item
    as a result of pass 1. Three full passes used to cost 21 GETs per account to find,
    almost always, nothing.
    """
    total = 0
    for attempt in range(1, passes + 1):
        sources = SOURCES if attempt == 1 else REFRESH_SOURCES
        print("surveying reward sources (pass %d):" % attempt)
        jobs = survey(cookie, home=home if attempt == 1 else None, sources=sources)
        if not jobs:
            print("\nnothing left to claim" if attempt > 1 else "\nnothing to claim right now")
            break
        print("\n%d claimable item(s):" % len(jobs))
        for source, _action, label in jobs:
            print("  [%-14s] %s" % (source, label))

        if not confirm:
            print("\nDRY RUN - nothing claimed. Re-run with --confirm.")
            return 0

        print()
        claimed = 0
        for source, action, label in jobs:
            if callable(action):                      # multi-step claim (the gift box)
                good, detail = action(cookie), ""
            else:
                method, path = action
                status, data = call(cookie, path, method)
                good = status == 200 and isinstance(data, dict) and "result" in data
                detail = "" if good else "HTTP %s %s" % (status, str(data)[:60])
            claimed += bool(good)
            print("  [%-14s] %-44s %s" % (source, label[:44], "ok" if good else detail or "failed"))
        total += claimed
        print("\npass %d: claimed %d/%d" % (attempt, claimed, len(jobs)))
        if claimed == 0:                              # nothing succeeded - stop retrying
            break
    return total
```

- [ ] **Step 5: เลิกดึงรายการกล่องของขวัญซ้ำใน `claim_giftbox`**

แทนที่ `claim_giftbox` ด้วย:

```python
def claim_giftbox(cookie, pending=None):
    """receive/all, then mop up the kinds it skips (MINI_GACHA boxes) one by one.

    `pending` is the list survey_giftbox already fetched. Without it this function
    listed the box twice more per call - once to find the leftovers and once to
    confirm - on top of the listing the survey had just done.
    """
    status, _data = call(cookie, "/giftbox/gift/receive/all", "POST")
    done = status == 200
    leftovers = _pending_gifts(cookie) if pending is None else pending
    for gift_entry in leftovers:
        sub, _ = call(cookie, "/giftbox/gift/receive/%s" % gift_entry.get("giftSn"), "POST")
        done = done or sub == 200
    return done
```

แทนที่ `survey_giftbox` ให้ผูกรายการที่ดึงมาแล้วเข้ากับงาน:

```python
def survey_giftbox(cookie):
    pending = _pending_gifts(cookie)
    if not pending:
        return []
    names = ", ".join("%s x%s" % (g.get("giftName"), g.get("giftCount")) for g in pending[:3])
    if len(pending) > 3:
        names += ", ..."
    # ผูกรายการที่เพิ่งดึงมาเข้ากับงาน claim เลย ผู้เรียกจะได้ไม่ต้องไปถามซ้ำ
    return [("giftbox", lambda c: claim_giftbox(c, pending),
             "%d gift(s): %s" % (len(pending), names))]
```

- [ ] **Step 6: รันเทสต์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/test_rewards.py -q`
คาดผล: PASS ทั้ง 7 ตัว

- [ ] **Step 7: พิสูจน์ว่าเทสต์จับการถอยหลังได้**

ย้อน `claim_all` ให้ `sources = SOURCES` ทุกรอบชั่วคราว แล้วรันใหม่
คาดผล: `test_the_second_pass_only_rechecks_the_gift_box` ต้อง **แดง** แล้วย้อนกลับ

- [ ] **Step 8: Commit**

```bash
git add tools/rewards.py tools/tests/test_rewards.py
git commit -m "perf(rewards): stop re-asking six reward systems what pass one already answered"
```

---

## Task 6: ย้ายกาชาและคลัง ranger ออกจาก `botLineRanger` + cache `/gacha/info`

**Files:**
- Modify: `tools/gacha.py`
- Modify: `tools/pull_roster.py`
- Create: `tools/tests/test_gacha_cache.py`

**Interfaces:**
- Consumes: ไม่มี
- Produces:
  ```python
  # tools/gacha.py
  def gacha_info(cookie, uid, cache=None) -> dict
  def draw_with_ticket(cookie, uid, group=None, cycles=1,
                       stop_when_found=True, targets=None, cache=None) -> list[str]
  # tools/pull_roster.py
  def unit_names(units, ranger_config=None) -> str
  ```

**เหตุผลที่ต้องย้าย:** `flows.py` ต้องเรียกตรรกะกาชาและการสรุปชื่อ ranger แต่วันนี้มันอยู่ใน
`botLineRanger.apiGachaWithTicket` (บรรทัด 6789, 84 บรรทัด) กับ `botLineRanger.getTeanInfo`
ซึ่งทั้งคู่อ่าน global `GACHARANGERGROUP` `RANGERSCONFIG` `LASTGACHASTATUS` การให้ engine
import `botLineRanger` คือการลาก global ชุดเดิมกลับเข้ามาทั้งชุด

`tools/gacha.py` วันนี้มีแค่ `pick_ticket_group` · `cmd_roll` · `ticket_counts` ซึ่งเป็น
ชิ้นส่วนระดับ CLI ตัวที่ประกอบมันเป็น "สุ่มจนเจอตัวที่ต้องการ" อยู่ใน `botLineRanger`

> **แผนนี้จงใจไม่คัดลอกเนื้อ 84 บรรทัดนั้นลงมา** — มันเป็นโค้ดที่หักตั๋วจริงบนบัญชีจริง
> การพิมพ์ซ้ำในเอกสารเปิดช่องให้พลาดโดยไม่มีใครเห็น สิ่งที่ต้องทำคือ **ย้ายจากไฟล์จริง
> แบบคำต่อคำ** แล้วเปลี่ยนเฉพาะสามชื่อที่ระบุไว้ข้างล่าง ห้ามคิดสูตรกาชาใหม่ ห้ามปรับ
> ลำดับการยิง และห้าม "ปรับให้อ่านง่ายขึ้น" ระหว่างย้าย
>
> วิธีตรวจว่าย้ายครบ: `git show HEAD:bot/botLineRanger.py | sed -n '6789,6873p' > /tmp/before.py`
> แล้วเทียบกับของใหม่ด้วยตา ความต่างต้องมีเฉพาะสามชื่อนั้นกับ `return`

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `tools/tests/test_gacha_cache.py`:

```python
"""gacha: /gacha/info ถูกดึงสองครั้งต่อบัญชีทั้งที่เป็นข้อมูลชุดเดียวกัน"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, cookie, uid, path, method="GET", body=None):
        self.calls.append(path.split("?")[0])
        return 200, {"result": {}}

    def count(self, path):
        return self.calls.count(path)


def test_a_cache_dict_stops_the_second_fetch(monkeypatch):
    gacha = load("gacha")
    api = FakeApi()
    monkeypatch.setattr(gacha, "call", api)
    cache = {}
    gacha.gacha_info("c", "u", cache=cache)
    gacha.gacha_info("c", "u", cache=cache)
    assert api.count("/v12.3/gacha/info") == 1


def test_without_a_cache_every_call_still_goes_out(monkeypatch):
    """ไม่ส่ง cache มาต้องได้พฤติกรรมเดิมเป๊ะ - CLI ที่รันครั้งเดียวไม่ควรเปลี่ยน"""
    gacha = load("gacha")
    api = FakeApi()
    monkeypatch.setattr(gacha, "call", api)
    gacha.gacha_info("c", "u")
    gacha.gacha_info("c", "u")
    assert api.count("/v12.3/gacha/info") == 2


def test_two_accounts_do_not_share_one_cache(monkeypatch):
    """cache เป็นของ session ห้ามเป็นตัวแปรระดับโมดูล ไม่งั้นบัญชี B ได้ตู้ของบัญชี A"""
    gacha = load("gacha")
    api = FakeApi()
    monkeypatch.setattr(gacha, "call", api)
    gacha.gacha_info("a", "1", cache={})
    gacha.gacha_info("b", "2", cache={})
    assert api.count("/v12.3/gacha/info") == 2
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/test_gacha_cache.py -q`
คาดผล: FAIL — `module 'gacha' has no attribute 'gacha_info'`

- [ ] **Step 3: เพิ่ม `gacha_info` แล้วให้ผู้เรียกภายในใช้มัน**

เพิ่มใน `tools/gacha.py` เหนือฟังก์ชันแรกที่เรียก `/v12.3/gacha/info`:

```python
def gacha_info(cookie, uid, cache=None):
    """ข้อมูลตู้กาชาของบัญชีนี้ ใช้ cache ที่ผู้เรียกถือมาถ้ามี

    cache ต้องมาจากผู้เรียก ห้ามเป็นตัวแปรระดับโมดูล - engine รันหลายบัญชีพร้อมกัน
    ในโปรเซสเดียว cache ที่แชร์กันจะทำให้บัญชีหนึ่งเห็นตู้ของอีกบัญชี
    """
    if cache is not None and "info" in cache:
        return cache["info"]
    _status, info = call(cookie, uid, "/v12.3/gacha/info")
    if cache is not None:
        cache["info"] = info
    return info
```

จากนั้นแทนที่ทุกจุดในไฟล์ที่เขียนว่า `call(cookie, uid, "/v12.3/gacha/info")` ด้วย
`gacha_info(cookie, uid, cache)` และเพิ่มพารามิเตอร์ `cache=None` ให้ฟังก์ชันที่ครอบมัน
— ปัจจุบันมี 2 จุด: ใน `pick_ticket_group` (บรรทัด 160) และ `cmd_list` (บรรทัด 202)
ตรวจด้วย `grep -n 'gacha/info' tools/gacha.py`

- [ ] **Step 4: ย้าย `apiGachaWithTicket` มาเป็น `gacha.draw_with_ticket`**

เปิด `bot/botLineRanger.py:6789-6873` แล้วย้ายเนื้อในมาเป็นฟังก์ชันใหม่ท้าย `tools/gacha.py`
โดยเปลี่ยนเฉพาะสามอย่าง **ห้ามแตะตรรกะการสุ่ม**:

- `GACHARANGERGROUP` → พารามิเตอร์ `group`
- `RANGERSCONFIG` → พารามิเตอร์ `targets` (dict เดิมที่ `matchGachaName` ใช้)
- `LASTGACHASTATUS` → คืนค่าออกมาแทนการเขียน global

```python
def draw_with_ticket(cookie, uid, group=None, cycles=1,
                     stop_when_found=True, targets=None, cache=None):
    """สุ่มกาชาด้วยตั๋ว คืนรายชื่อ unitCode ที่ได้

    ย้ายมาจาก botLineRanger.apiGachaWithTicket() แบบคำต่อคำ ต่างกันแค่ค่าที่เคยอ่านจาก
    global (GACHARANGERGROUP, RANGERSCONFIG, LASTGACHASTATUS) กลายเป็นพารามิเตอร์และค่าคืน
    - engine รันหลายบัญชีในโปรเซสเดียว global จะทำให้บัญชีหนึ่งใช้ค่าตั้งของอีกบัญชี

    ฟังก์ชันนี้หักตั๋วจริงบนบัญชีจริง ทุกบรรทัดที่ต่างจากต้นฉบับคือความเสี่ยงที่จะเสียตั๋วฟรี
    """
    ...   # เนื้อจากต้นฉบับ
```

ผู้ลงมือ: ต้องย้าย `matchGachaName` และ `add_ranger_name` ที่ `apiGachaWithTicket` เรียกใช้
มาด้วย (หาใน `botLineRanger` ด้วย `grep -n 'def matchGachaName\|def add_ranger_name'`)

- [ ] **Step 5: ย้ายการสรุปชื่อ ranger มาเป็น `pull_roster.unit_names`**

เปิด `bot/botLineRanger.py::getTeanInfo` แล้วย้ายเฉพาะส่วนที่ *แปลง* `playerUnits` เป็น
ข้อความสรุป (ส่วนที่ยิง API ไม่ต้องย้าย — `flows._account_info` ยิงเอง) ไปเป็น:

```python
def unit_names(units, ranger_config=None):
    """สรุปคลัง ranger เป็นข้อความสำหรับตั้งชื่อไฟล์ที่ export

    ย้ายมาจาก botLineRanger.getTeanInfo() ตัวที่ยิง API ไม่ได้ย้ายมาด้วยเพราะผู้เรียก
    ฝั่ง engine ยิงเองแล้วส่งผลลัพธ์เข้ามา - จะได้ไม่ยิงซ้ำ

    ขั้นร่างอ่านจากท้ายตัวเลขใน unitCode (u1630e-sally -> evolved) ด้วยตารางเดียวกับ
    ที่ไฟล์นี้ใช้อยู่แล้ว เพื่อให้ชื่อขั้นตรงกันทั้งโปรเจกต์
    """
    ...   # เนื้อจากต้นฉบับ
```

- [ ] **Step 6: รันเทสต์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest tools/tests/ -q`
คาดผล: PASS ทั้งหมด

ตรวจว่าของที่ย้ายมาเรียกได้จริง:
```bash
PYTHONUTF8=1 python -c "import sys;sys.path.insert(0,'tools');import gacha,pull_roster;print(gacha.draw_with_ticket, gacha.gacha_info, pull_roster.unit_names)"
```
คาดผล: พิมพ์ชื่อฟังก์ชันทั้งสามโดยไม่มี error

- [ ] **Step 7: Commit**

```bash
git add tools/gacha.py tools/pull_roster.py tools/tests/test_gacha_cache.py
git commit -m "refactor(gacha): the draw and the roster summary move to tools, off the module globals"
```

---

## Task 7: `AccountSession` และ flow `login`

**Files:**
- Create: `bot/engine/session.py`
- Create: `bot/engine/flows.py`
- Create: `bot/tests/test_flows_login.py`

**Interfaces:**
- Consumes: `WorkQueue` (1) · `ProxyLane` (3) · `rangers_api.use_lane` (4) ·
  `rewards.claim_all(..., home=)` (5) · `gacha.gacha_info(..., cache=)` (6)
- Produces:
  ```python
  @dataclass
  class AccountSession:
      src: str; lane: object
      cookie: str = ""; rsn: str = ""; home: dict | None = None
      gacha_units: list = ...; gacha_status: str = "-"
      level: int = 0; ruby: str = "NA"; ticket: str = "NA"
      rangers: str = ""; error: str = ""; attempts: int = 0
      cache: dict = ...
      def reset_token(self) -> None
  @dataclass
  class Outcome:
      dest: str; name: str = ""; status: str = "OK"; error: str = ""
  MODES = {"ranger_api_Login": run_login, ...}
  def run(mode: str, s: AccountSession, cfg: dict) -> Outcome
  ```

**นี่คือ task ที่ยากที่สุดของแผน** — เป็นการย้าย `startBotLogin_API_headless` ออกจาก
global ทั้งหมด อ่านต้นฉบับที่ `bot/botLineRanger.py:7990-8127` (flow) ·
`6429-6476` (`getLFACHeadless`) · `6509-6542` (`apiGetPlayer` `apiAcceptAllRewards`) ·
`7832-7860` (`getAccoutInfo`) ก่อนเขียน **ห้ามคิดเส้นทางใหม่เอง — ย้ายของเดิม**

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `bot/tests/test_flows_login.py`:

```python
"""flow Login: state ทุกตัวอยู่ใน session ไม่ใช่ใน global

บั๊กที่ชุดนี้กันไว้: บอทเดิมเก็บ LFACCACHE/GAMEID/FILENAME ไว้ระดับโมดูล สองบัญชีใน
โปรเซสเดียวกันจึงเขียนทับกัน - เป็นเหตุผลเดียวที่บอทต้องใช้ 128 โปรเซสและ 5.5 GB
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine import flows                       # noqa: E402
from engine.session import AccountSession      # noqa: E402


class Lane:
    name, parts = "L", None
    def acquire(self): pass
    def note_ok(self): pass
    def note_fail(self): return False


CFG = {"gacharanger": False, "rewardpasses": 3, "gachacycles": 1}


def make(tmp_path, name="a.xml"):
    (tmp_path / "execute").mkdir(exist_ok=True)
    path = tmp_path / "execute" / name
    path.write_text("<map/>", encoding="utf-8")
    return AccountSession(src=str(path), lane=Lane())


def stub(monkeypatch, calls, rsn="ID1", level=3):
    """ตัวปลอมที่ *ไม่* เก็บ token ให้เอง - สิ่งที่พิสูจน์คือ session เป็นคนถือ"""
    monkeypatch.setattr(flows, "_relogin", lambda s: (
        calls.append("relogin"), setattr(s, "cookie", "LF_AC=t-" + os.path.basename(s.src)),
        setattr(s, "rsn", rsn))[0])
    monkeypatch.setattr(flows, "_fetch_home", lambda s: (
        calls.append("home"),
        setattr(s, "home", {"player": {"rsn": rsn, "level": level},
                            "rubyBalance": {"total": 10}}))[0])
    monkeypatch.setattr(flows, "_claim_rewards", lambda s, cfg: calls.append("claim"))
    monkeypatch.setattr(flows, "_gacha", lambda s, cfg: calls.append("gacha"))
    monkeypatch.setattr(flows, "_account_info", lambda s: calls.append("info"))


def test_the_token_lives_on_the_session_not_on_the_module(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    a, b = make(tmp_path, "a.xml"), make(tmp_path, "b.xml")
    flows.run("ranger_api_Login", a, CFG)
    flows.run("ranger_api_Login", b, CFG)
    assert a.cookie == "LF_AC=t-a.xml"
    assert b.cookie == "LF_AC=t-b.xml"
    assert a.cookie != b.cookie


def test_two_threads_running_two_accounts_do_not_cross_tokens(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    sessions = [make(tmp_path, "%03d.xml" % i) for i in range(32)]
    ts = [threading.Thread(target=flows.run, args=("ranger_api_Login", s, CFG))
          for s in sessions]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len({s.cookie for s in sessions}) == 32
    for s in sessions:
        assert s.cookie == "LF_AC=t-" + os.path.basename(s.src)


def test_home_is_fetched_once_per_account(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    flows.run("ranger_api_Login", make(tmp_path), CFG)
    assert calls.count("home") == 1


def test_a_successful_run_sends_the_file_to_output(tmp_path, monkeypatch):
    stub(monkeypatch, [])
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)
    assert out.dest == "output"
    assert out.status == "OK"


def test_a_relogin_failure_sends_the_file_to_login_failed(tmp_path, monkeypatch):
    stub(monkeypatch, [])

    def boom(s):
        raise RuntimeError("HTTP 401")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)
    assert out.dest == "login failed"
    assert "401" in out.error


def test_gacha_is_skipped_when_the_config_says_so(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    flows.run("ranger_api_Login", make(tmp_path), dict(CFG, gacharanger=False))
    assert "gacha" not in calls


def test_the_exported_name_carries_the_account_facts(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    s = make(tmp_path)

    def info(sess):
        sess.rangers, sess.ruby, sess.ticket, sess.level = "brown", "10", "2", 3

    monkeypatch.setattr(flows, "_account_info", info)
    out = flows.run("ranger_api_Login", s, CFG)
    assert out.name == "brown_Rb10_Tk2_ID1_Lv3"


def test_an_unknown_mode_is_refused_loudly(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        flows.run("ranger_api_Nope", make(tmp_path), CFG)
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_flows_login.py -q`
คาดผล: FAIL ด้วย `ModuleNotFoundError: No module named 'engine.session'`

- [ ] **Step 3: เขียน `bot/engine/session.py`**

```python
"""state ของบัญชีหนึ่งใบระหว่างที่กำลังถูกทำงาน

ทุกฟิลด์ในนี้เคยเป็นตัวแปรระดับโมดูลใน botLineRanger (LFACCACHE, GAMEID, FILENAME,
LASTGACHASTATUS) ซึ่งแปลว่าสองบัญชีในโปรเซสเดียวกันเขียนทับกัน บอทจึงต้องแยกโปรเซส
ต่อหนึ่ง worker และจ่ายแรม 5.5 GB เพื่อได้ 128 ช่องพร้อมกัน
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AccountSession:
    src: str                       # path ของไฟล์ใน execute/
    lane: object                   # ProxyLane ที่บัญชีนี้ใช้ตลอด session
    cookie: str = ""               # "LF_AC=..."
    rsn: str = ""                  # GAME_ID
    home: dict | None = None       # /home ดึงครั้งเดียว ใช้ซ้ำทั้ง session
    gacha_units: list = field(default_factory=list)
    gacha_status: str = "-"
    level: int = 0
    ruby: str = "NA"
    ticket: str = "NA"
    rangers: str = ""
    error: str = ""
    attempts: int = 0
    cache: dict = field(default_factory=dict)   # ที่เก็บของที่ยิงครั้งเดียวต่อบัญชี เช่น gacha/info

    def reset_token(self) -> None:
        """บังคับให้ relogin ใหม่ในความพยายามรอบถัดไป

        แทน force_stop_LINE_Rangers() ของโหมด headless เดิม ซึ่งไม่ได้ปิดเกมอะไรเลย
        มันแค่ล้าง LFACCACHE
        """
        self.cookie = ""
        self.home = None
        self.cache.clear()


@dataclass
class Outcome:
    dest: str                      # "output" | "backup" | "login failed"
    name: str = ""                 # ชื่อใหม่ของไฟล์ ไม่ใส่ = ใช้ชื่อเดิม
    status: str = "OK"
    error: str = ""
```

- [ ] **Step 4: เขียน `bot/engine/flows.py` (โหมด Login)**

```python
"""flow ของแต่ละ play mode - ฟังก์ชันล้วนที่รับ AccountSession เป็นตัวแรก

ห้ามฟังก์ชันไหนในไฟล์นี้อ่านหรือเขียนตัวแปรระดับโมดูลที่เปลี่ยนค่าได้ ทั้งไฟล์ถูกเรียก
จากหลายเธรดพร้อมกันบนคนละบัญชี
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))

import rangers_api          # noqa: E402
import relogin             # noqa: E402
import rewards             # noqa: E402
from device_session import decrypt_lfac   # noqa: E402

from .session import AccountSession, Outcome   # noqa: E402

MAX_ATTEMPTS = 3


# --- ขั้นตอนย่อย (เทสต์ replace ตัวพวกนี้ทีละตัว) ---

def _relogin(s: AccountSession) -> None:
    """ขอ LF_AC สดจากไฟล์ผ่าน /v12.3/login - ย้ายมาจาก getLFACHeadless()

    cc ของ guest มาจาก pool ที่ engine mint ไว้ให้ก่อนสปอว์นเธรด (โควตา /auth คือ
    2 ครั้งต่อ IP ต่อนาที การให้ทุกเธรด mint เองจะชนโควตาทันทีที่เกิน 2 เธรด)
    """
    acct = relogin.read_account(s.src)
    guest_cookie = decrypt_lfac(acct["udid"], acct["enc"])
    pool = relogin.CcPool(share_file=os.environ.get("LGRGS_CC_FILE") or None)
    cc = pool.get()
    status, result, lf_ac = relogin.login(
        cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
    if status == 401 and not result:
        cc = pool.renew(cc)
        status, result, lf_ac = relogin.login(
            cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
    if not result or not lf_ac:
        raise RuntimeError("relogin failed (HTTP %s)" % status)
    pool.mark_proven()
    try:
        relogin.atomic_write(s.src, relogin.replace_enc(acct["text"], acct["udid"], lf_ac))
    except OSError as err:
        # เขียนโทเค็นกลับไฟล์ไม่ได้ก็ยังยิง API ต่อได้ ไฟล์ที่ export จะมีโทเค็นเก่าเท่านั้น
        s.error = "token write failed: %s" % err
    s.cookie = "LF_AC=" + lf_ac
    s.rsn = result.get("rsn") or ""
    s.level = int(result.get("level") or 0)


def _fetch_home(s: AccountSession) -> None:
    """ดึง /home ครั้งเดียวต่อบัญชี แล้วให้ทุกคนที่ต้องใช้อ่านจาก s.home

    เดิมก้อนนี้ถูกดึงสี่ครั้ง: check_session, survey_attendance_package, currentLevel
    และ getRubyAndTicket
    """
    status, data = rangers_api.call(s.cookie, "/home")
    if status != 200 or not isinstance(data, dict) or "result" not in data:
        raise RuntimeError("home rejected (HTTP %s)" % status)
    s.home = data["result"]
    player = s.home.get("player") or {}
    s.rsn = player.get("rsn") or s.rsn
    s.level = int(player.get("level") or s.level)


def _claim_rewards(s: AccountSession, cfg: dict) -> None:
    rewards.claim_all(s.cookie, confirm=True,
                      passes=int(cfg.get("rewardpasses") or 3), home=s.home)


def _gacha(s: AccountSession, cfg: dict) -> None:
    """สุ่มกาชาด้วยตั๋วของบัญชีนี้

    draw_with_ticket คืน (granted_codes, status) - ต้องแกะเป็นสองค่า ไม่ใช่เก็บทั้ง tuple
    ลง gacha_units ซึ่งเป็น list ไม่งั้น len(s.gacha_units) จะได้ 2 เสมอไม่ว่าสุ่มได้กี่ตัว
    """
    import gacha as gacha_mod
    s.gacha_units, s.gacha_status = gacha_mod.draw_with_ticket(
        s.cookie, s.rsn,
        group=cfg.get("gacharangergroup"),
        cycles=int(cfg.get("gachacycles") or 1),
        stop_when_found=bool(cfg.get("stopwhenfound", True)),
        targets=cfg.get("_rangers_config"),
        cache=s.cache,
        gacha_mode=cfg.get("gachamode") or "NumberOfCycles",
        use_ruby=bool(cfg.get("useruby", False)))


def _account_info(s: AccountSession) -> None:
    """เติม rangers / ruby / ticket / level จากของที่ดึงมาแล้วให้มากที่สุด

    ruby อยู่ใน s.home ที่ดึงไปแล้ว เหลือแค่คลัง ranger กับจำนวนตั๋วที่ต้องยิงเพิ่ม
    เดิมขั้นนี้ยิง /home ซ้ำอีกสองครั้งผ่าน currentLevel() และ getRubyAndTicket()
    """
    import gacha as gacha_mod
    import pull_roster

    ruby = (s.home or {}).get("rubyBalance") or {}
    s.ruby = str(ruby.get("total", "NA"))
    premium, _event = gacha_mod.ticket_counts(s.cookie, s.rsn)
    s.ticket = str(premium)
    status, data = rangers_api.call(
        s.cookie, "/player/units/equip?inven=true&team=false&deck=false")
    if status == 200 and isinstance(data, dict):
        units = (data.get("result") or {}).get("playerUnits") or []
        s.rangers = pull_roster.unit_names(units, cfg.get("_rangers_config"))


def _export_name(s: AccountSession) -> str:
    return "%s_Rb%s_Tk%s_%s_Lv%s" % (s.rangers, s.ruby, s.ticket, s.rsn, s.level)


# --- flow ต่อโหมด ---

def run_login(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            s.reset_token()
            _relogin(s)
            _fetch_home(s)
            _claim_rewards(s, cfg)
            if cfg.get("gacharanger"):
                _gacha(s, cfg)   # ตั้ง s.gacha_status เองจากผลจริง ห้ามเขียนทับ
            _account_info(s)
            return Outcome(dest="output", name=_export_name(s), status="OK")
        except Exception as err:        # ทุกความพลาดคือ "ลองใหม่ได้" จนกว่าจะครบ MAX_ATTEMPTS
            last = str(err)
    return Outcome(dest="login failed", status="FAIL", error=last)


MODES = {
    "ranger_api_Login": run_login,
}


def run(mode: str, s: AccountSession, cfg: dict) -> Outcome:
    flow = MODES.get(mode)
    if flow is None:
        # สะกดผิดต้องดังออกมา ไม่ใช่ตกไปใช้โหมดปริยายแล้วผู้ใช้ได้ผลผิดโดยไม่รู้ตัว
        raise ValueError("unknown mode %r (expected one of %r)" % (mode, sorted(MODES)))
    return flow(s, cfg)
```

`gacha.draw_with_ticket` · `gacha.gacha_info` · `pull_roster.unit_names` มาจาก Task 6
ถ้ายังไม่มีแปลว่า Task 6 ยังไม่เสร็จ — **อย่าเขียนขึ้นใหม่ในไฟล์นี้** ให้กลับไปทำ Task 6 ก่อน

`cfg["_rangers_config"]` คือ dict ที่ `botLineRanger.RANGERSCONFIG` เคยถือ (มาจาก
`src/configRangers.ini`) `engine_main.load_config` เป็นคนโหลดมาใส่ให้ — ดู Task 9 step 5

- [ ] **Step 5: รันเทสต์ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_flows_login.py -q`
คาดผล: PASS ทั้ง 8 ตัว

- [ ] **Step 6: Commit**

```bash
git add bot/engine/session.py bot/engine/flows.py bot/tests/test_flows_login.py
git commit -m "feat(engine): an account's token lives on its session, so two can share a process"
```

---

## Task 8: flow `level3`, `genid`, `stage`

**Files:**
- Modify: `bot/engine/flows.py`
- Create: `bot/tests/test_flows_modes.py`

**Interfaces:**
- Consumes: ทุกอย่างจาก task 7
- Produces: `MODES` ครบ 4 คีย์ · `run_level3` · `run_genid` · `run_stage`

**ต้นฉบับที่ต้องย้าย:** `startBotLevel3_API_headless` (`bot/botLineRanger.py:8436`, 136 บรรทัด)
· `startBotGenID_API_headless` (`:8618`, 106 บรรทัด) · `startBotStage_API_headless`
(`:8295`, 100 บรรทัด) · `_headlessCreateAccount` (`:8572`, 46 บรรทัด) ·
`apiLevelUpByStage1` (`:8264`) · `apiForceStage` (`:8224`)

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `bot/tests/test_flows_modes.py` — ลอกโครง stub จาก `test_flows_login.py` แล้วเพิ่ม:

```python
def test_level3_skips_the_stage_replay_when_the_account_is_already_there(tmp_path, monkeypatch):
    """ถึงเป้าอยู่แล้วให้ login เฉย ๆ - เล่นซ้ำคือการจ่ายค่า request ฟรี"""
    calls = []
    stub(monkeypatch, calls, level=3)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: calls.append("levelup"))
    flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, leveltarget=3))
    assert "levelup" not in calls


def test_level3_replays_stage_one_when_the_account_is_below_target(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls, level=1)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: (
        calls.append("levelup"), setattr(s, "level", 3))[0])
    out = flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, leveltarget=3))
    assert "levelup" in calls
    assert out.dest == "output"


def test_level3_sends_an_account_that_never_reached_target_to_login_failed(tmp_path, monkeypatch):
    """จุดประสงค์ของโหมดคือได้ไอดีเลเวล 3 ปล่อยเลเวลต่ำปนลง output คือทำลายความหมายของโฟลเดอร์"""
    stub(monkeypatch, [], level=1)
    monkeypatch.setattr(flows, "_level_up", lambda s, cfg: None)
    out = flows.run("ranger_api_Level3", make(tmp_path), dict(CFG, leveltarget=3))
    assert out.dest == "login failed"


def test_genid_does_not_claim_a_file_from_the_queue(tmp_path, monkeypatch):
    """GenID สร้างบัญชีใหม่ มันไม่มีไฟล์ต้นทาง - src ต้องว่างได้"""
    calls = []
    stub(monkeypatch, calls)
    monkeypatch.setattr(flows, "_create_account", lambda s, cfg: calls.append("create"))
    s = AccountSession(src="", lane=Lane())
    out = flows.run("ranger_api_GenID", s, dict(CFG, genidlevel3=False))
    assert "create" in calls
    assert out.dest in ("output", "backup")


def test_every_mode_in_the_gui_has_a_flow():
    """โหมดที่ dropdown เสนอแต่ engine ไม่รู้จัก = ผู้ใช้กดแล้วไม่เกิดอะไรขึ้น"""
    assert set(flows.MODES) == {
        "ranger_api_Login", "ranger_api_Level3", "ranger_api_GenID", "ranger_api_Stage"}


def test_adding_a_fifth_mode_needs_nothing_but_a_new_entry(tmp_path, monkeypatch):
    """spec ข้อ 1.5: โหมด Quest ต้อง port กลับเข้ามาได้โดยไม่แก้ pool.py หรือ queue.py"""
    stub(monkeypatch, [])
    flows.MODES["ranger_api_Fake"] = lambda s, cfg: flows.Outcome(dest="output", name="x")
    try:
        assert flows.run("ranger_api_Fake", make(tmp_path), CFG).name == "x"
    finally:
        del flows.MODES["ranger_api_Fake"]
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_flows_modes.py -q`
คาดผล: FAIL — `unknown mode 'ranger_api_Level3'`

- [ ] **Step 3: เพิ่มสามโหมดลง `bot/engine/flows.py`**

เพิ่มขั้นตอนย่อยและ flow (ย้ายตรรกะจากต้นฉบับที่ระบุไว้ข้างบน ห้ามคิดใหม่):

```python
def _level_up(s: AccountSession, cfg: dict) -> None:
    """เล่น st01 ซ้ำจนถึง leveltarget - ย้ายมาจาก apiLevelUpByStage1()

    วัดจริง: st01 จ่าย 600 exp ทุกรอบ เลเวล 1 -> 3 ใช้สองรอบ และการเลเวลอัพเติม heart
    ให้เอง (5 -> 9 -> 13) จึงไม่มีทาง heart หมดก่อนถึงเป้า
    """
    import stage_forge
    target = int(cfg.get("leveltarget") or 3)
    level, _plays, _why = stage_forge.level_up(s.cookie, s.rsn, target)
    s.level = int(level or s.level)


def _create_account(s: AccountSession, cfg: dict) -> None:
    """สร้าง guest ใหม่ผ่าน /v12.3/signup/platform - ย้ายมาจาก _headlessCreateAccount()

    make_account เขียนไฟล์ .xml ให้เองเมื่อได้ write_xml_dir และคืน dict ที่มี lf_ac/rsn
    แต่ไม่คืน path ของไฟล์ จึงประกอบเองจากกฎตั้งชื่อของ write_account_xml
    (ผู้ลงมือ: เปิด tools/new_account.py::write_account_xml แล้วใช้กฎจริง ไม่ใช่เดา)

    status == "pending-login" แปลว่าสร้างเครดิทเชียลได้แต่ล็อกอินไม่ผ่าน - เครดิทยังถูก
    เก็บไว้แล้วกู้ได้ด้วย --resume ห้ามถือว่าเป็นความสำเร็จ
    """
    import new_account
    execute_dir = os.path.join(os.getcwd(), "execute")
    acct = new_account.make_account(write_xml_dir=execute_dir, skip_tut=True)
    if acct.get("status") != "ready" or not acct.get("lf_ac"):
        raise RuntimeError("signup incomplete (status=%s)" % acct.get("status"))
    s.src = new_account.write_account_xml(acct, execute_dir)
    s.cookie = "LF_AC=" + acct["lf_ac"]
    s.rsn = acct.get("rsn") or acct.get("gameId") or ""
    s.level = 1


def _force_stage(s: AccountSession, cfg: dict) -> None:
    """ดันด่านถึง settings.stageend - ย้ายมาจาก apiForceStage()

    clear_range รับ first และ last เป็นเลขด่าน (ไม่ใช่ stageCode) จุดเริ่มมาจาก
    start_stage() ซึ่งอ่านด่านล่าสุดของบัญชีจาก /stage/last - เริ่มที่ 1 เสมอคือการ
    เล่นซ้ำด่านที่ผ่านแล้วทั้งหมดโดยจ่าย heart จริงทุกด่าน
    """
    import stage_forge
    player = stage_forge.player_info(s.cookie)
    first = stage_forge.start_stage(s.cookie, player)
    last = int(cfg.get("stageend") or 150)
    if first > last:
        return          # ผ่านเป้าไปแล้ว ไม่มีอะไรต้องทำ
    stage_forge.clear_range(s.cookie, s.rsn, first, last)


def run_level3(s: AccountSession, cfg: dict) -> Outcome:
    target = int(cfg.get("leveltarget") or 3)
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            s.reset_token()
            _relogin(s)
            _fetch_home(s)
            if s.level < target:
                _level_up(s, cfg)
            if s.level < target:
                # ไม่ถึงเป้า = โหมดนี้ยังทำงานไม่สำเร็จ ส่งลง output ไม่ได้
                return Outcome(dest="login failed", status="LOWLV",
                               error="level %s < target %s" % (s.level, target))
            _claim_rewards(s, cfg)
            if cfg.get("gacharanger"):
                _gacha(s, cfg)   # ตั้ง s.gacha_status เองจากผลจริง ห้ามเขียนทับ
            _account_info(s)
            return Outcome(dest="output", name=_export_name(s), status="OK")
        except Exception as err:
            last = str(err)
    return Outcome(dest="login failed", status="FAIL", error=last)


def run_genid(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            _create_account(s, cfg)
            _fetch_home(s)
            if cfg.get("genidlevel3"):
                target = int(cfg.get("leveltarget") or 3)
                if s.level < target:
                    _level_up(s, cfg)
                if s.level < target:
                    return Outcome(dest="login failed", status="LOWLV",
                                   error="level %s < target %s" % (s.level, target))
            _claim_rewards(s, cfg)
            if cfg.get("gacharanger"):
                _gacha(s, cfg)   # ตั้ง s.gacha_status เองจากผลจริง ห้ามเขียนทับ
            _account_info(s)
            return Outcome(dest="output", name=_export_name(s), status="OK")
        except Exception as err:
            last = str(err)
    return Outcome(dest="login failed", status="FAIL", error=last)


def run_stage(s: AccountSession, cfg: dict) -> Outcome:
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s.attempts = attempt
        try:
            s.reset_token()
            _relogin(s)
            _fetch_home(s)
            _force_stage(s, cfg)
            _claim_rewards(s, cfg)
            _account_info(s)
            return Outcome(dest="output", name=_export_name(s), status="OK")
        except Exception as err:
            last = str(err)
    return Outcome(dest="login failed", status="FAIL", error=last)


MODES = {
    "ranger_api_Login": run_login,
    "ranger_api_Level3": run_level3,
    "ranger_api_GenID": run_genid,
    "ranger_api_Stage": run_stage,
}
```

ลายเซ็นที่ยืนยันแล้วจากไฟล์จริง (ตรวจตอนเขียนแผน 2026-09-23) — ถ้าต่างจากนี้แปลว่ามีคนแก้
หลังจากนั้น ให้ใช้ของจริงและรายงาน:

```python
stage_forge.level_up(cookie, rsn, target_level, stc="st01", pt=1, ...)     # :367
stage_forge.clear_range(cookie, rsn, first, last, pt=1, retries=2, ...)    # :301
stage_forge.start_stage(cookie, player) -> int                            # :284
stage_forge.player_info(cookie) -> dict                                   # :172
new_account.make_account(write_xml_dir=None, skip_tut=True) -> dict       # :537
new_account.write_account_xml(account, xml_dir) -> str                    # :480
gacha.ticket_counts(cookie, uid=None) -> (premium, event)                 # :140
```

- [ ] **Step 4: รันเทสต์ทั้ง bot/tests ให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/ -q`
คาดผล: PASS ทั้งหมด

- [ ] **Step 5: Commit**

```bash
git add bot/engine/flows.py bot/tests/test_flows_modes.py
git commit -m "feat(engine): level3, genid and stage flows, each one session-scoped"
```

---

## Task 9: ThreadPool · Reporter · entry ของ engine

**Files:**
- Create: `bot/engine/report.py`
- Create: `bot/engine/pool.py`
- Create: `bot/engine_main.py`
- Create: `bot/tests/test_pool.py`
- Create: `bot/tests/bench_engine.py`

**Interfaces:**
- Consumes: `WorkQueue` (1) · `ProxyPool` (3) · `flows.run` (7, 8)
- Produces:
  ```python
  class Reporter:
      def __init__(self, stream=sys.stdout)
      def account(self, **kw); def stat(self, **kw); def lane(self, **kw); def note(self, msg)
  class EnginePool:
      def __init__(self, mode, cfg, queue, proxies, reporter, flow=None)
      def run(self) -> dict          # คืนยอดสรุป
      def request_stop(self) -> None
  STOP_FLAG = "stop.flag"
  ```

- [ ] **Step 1: เขียนเทสต์ที่ยังล้มเหลว**

สร้าง `bot/tests/test_pool.py`:

```python
"""EnginePool: เธรดทุกตัวดึงงานจากคิวเดียว แล้วรายงานผลเป็น JSONL

บั๊กที่ชุดนี้กันไว้: supervisor ที่ terminate() ทันที ทำให้ยอดสุดท้ายของลูกหาย -
รอบ mint จริงเคยขาดไป 1,427 ใบ ของไม่ได้หายแต่ตัวเลขผิด
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine.pool import EnginePool       # noqa: E402
from engine.queue import WorkQueue       # noqa: E402
from engine.report import Reporter       # noqa: E402
from engine.session import Outcome       # noqa: E402


def build(tmp_path, n):
    for sub in ("input", "execute", "output", "backup", "login failed", "log"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (tmp_path / "input" / ("%03d.xml" % i)).write_text("<map/>", encoding="utf-8")
    return WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))


def rows(buf):
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


def test_every_file_in_the_queue_is_processed_exactly_once(tmp_path):
    q = build(tmp_path, 60)
    seen = []
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 8}, q, [], Reporter(buf),
                      flow=lambda mode, s, cfg: (seen.append(os.path.basename(s.src)),
                                                 Outcome(dest="output"))[1])
    pool.run()
    assert len(seen) == 60
    assert len(set(seen)) == 60
    assert len(os.listdir(tmp_path / "output")) == 60
    assert os.listdir(tmp_path / "execute") == []


def test_a_flow_that_raises_sends_its_file_to_login_failed_and_the_pool_keeps_going(tmp_path):
    q = build(tmp_path, 10)
    buf = io.StringIO()

    def flow(mode, s, cfg):
        if s.src.endswith("005.xml"):
            raise RuntimeError("boom")
        return Outcome(dest="output")

    EnginePool("ranger_api_Login", {"threadsperproxy": 4}, q, [], Reporter(buf), flow=flow).run()
    assert len(os.listdir(tmp_path / "output")) == 9
    assert os.listdir(tmp_path / "login failed") == ["005.xml"]


def test_each_finished_account_is_reported_once(tmp_path):
    q = build(tmp_path, 12)
    buf = io.StringIO()
    EnginePool("ranger_api_Login", {"threadsperproxy": 4}, q, [], Reporter(buf),
               flow=lambda m, s, c: Outcome(dest="output")).run()
    assert len([r for r in rows(buf) if r["t"] == "acct"]) == 12


def test_the_final_stat_line_matches_what_landed_on_disk(tmp_path):
    """ตรวจจากดิสก์ ไม่ใช่จากตัวเลขที่รายงาน - ยอดที่ขาดไปเงียบ ๆ คือบั๊กที่แพงที่สุด"""
    q = build(tmp_path, 25)
    buf = io.StringIO()
    summary = EnginePool("ranger_api_Login", {"threadsperproxy": 5}, q, [], Reporter(buf),
                         flow=lambda m, s, c: Outcome(dest="output")).run()
    assert summary["done"] == len(os.listdir(tmp_path / "output")) == 25


def test_a_stop_request_lets_running_accounts_finish(tmp_path):
    """ฆ่าทันทีคือการทิ้งงานที่ทำไปแล้วครึ่งทาง พร้อมยอดสุดท้ายของมัน"""
    import threading
    q = build(tmp_path, 200)
    buf = io.StringIO()
    started = threading.Event()

    def flow(mode, s, cfg):
        started.set()
        return Outcome(dest="output")

    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 4}, q, [], Reporter(buf), flow=flow)
    stopper = threading.Thread(target=lambda: (started.wait(2), pool.request_stop()))
    stopper.start()
    summary = pool.run()
    stopper.join()
    assert os.listdir(tmp_path / "execute") == []
    assert summary["done"] == len(os.listdir(tmp_path / "output"))


def test_the_reporter_writes_one_json_object_per_line(tmp_path):
    buf = io.StringIO()
    r = Reporter(buf)
    r.account(status="OK", rsn="ID1")
    r.stat(done=1, left=2)
    r.lane(name="1.1.1.1:8000", state="dead")
    got = rows(buf)
    assert [x["t"] for x in got] == ["acct", "stat", "lane"]


def test_a_capped_thread_count_is_announced_not_swallowed(tmp_path):
    """ตัดได้ แต่ต้องบอก - หน้าเว็บที่โกหกเรื่องเพดานเคยอยู่มาหลายวัน"""
    q = build(tmp_path, 1)
    buf = io.StringIO()
    EnginePool("ranger_api_Login",
               {"threadsperproxy": 96, "maxthreads": 8},
               q, ["%d.1.1.1:8000" % i for i in range(4)], Reporter(buf),
               flow=lambda m, s, c: Outcome(dest="output")).run()
    assert any(r["t"] == "note" and "capped" in r["msg"] for r in rows(buf))


def test_a_worker_on_a_dead_lane_stops_taking_work(tmp_path):
    """งานที่ยังไม่ถูก claim ต้องอยู่ในคิวให้ lane อื่นทำ ไม่ใช่ถูก lane ที่ตายแล้วดูดไปทิ้ง"""
    q = build(tmp_path, 40)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 2, "apirps": 1000},
                      q, ["1.1.1.1:8000", "2.2.2.2:8000"], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    for _ in range(3):
        pool.pool.lanes[0].note_fail()
    pool.run()
    assert len(os.listdir(tmp_path / "output")) == 40      # lane ที่เหลือทำครบ


def test_the_engine_stops_when_every_proxy_is_down(tmp_path):
    """ไม่มี proxy เหลือแล้ววิ่งต่อ = ยิงออก IP ของผู้ใช้เอง ซึ่งคือสิ่งที่เขาตั้ง proxy ไว้เลี่ยง"""
    import engine.pool as pool_mod
    q = build(tmp_path, 500)
    buf = io.StringIO()
    pool = EnginePool("ranger_api_Login", {"threadsperproxy": 2, "apirps": 1000},
                      q, ["1.1.1.1:8000"], Reporter(buf),
                      flow=lambda m, s, c: Outcome(dest="output"))
    monkey = pool_mod.STAT_EVERY
    pool_mod.STAT_EVERY = 0.05
    try:
        for lane in pool.pool.lanes:
            for _ in range(3):
                lane.note_fail()
        pool.run()
    finally:
        pool_mod.STAT_EVERY = monkey
    assert any(r["t"] == "note" and "every proxy is down" in r["msg"] for r in rows(buf))
    assert q.remaining() > 0        # คิวยังเหลือ ไม่ได้ถูกกินทิ้ง
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_pool.py -q`
คาดผล: FAIL ด้วย `ModuleNotFoundError: No module named 'engine.pool'`

- [ ] **Step 3: เขียน `bot/engine/report.py`**

```python
"""รายงานความคืบหน้าเป็น JSONL หนึ่งบรรทัดหนึ่งเหตุการณ์บน stdout

GUI อ่านฝั่งตรงข้ามแล้วสะสมไว้อัปเดตจอทุกหนึ่งวินาที ไม่ใช่ทุกบรรทัด - แผงคุมที่วาดกราฟ
ใหม่ทุก log line ช้าลงเรื่อย ๆ ตลอดเวลาที่บอทรัน
"""
from __future__ import annotations

import json
import sys
import threading


class Reporter:
    def __init__(self, stream=None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self._lock = threading.Lock()

    def _emit(self, kind: str, **row) -> None:
        row["t"] = kind
        with self._lock:
            self.stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.stream.flush()

    def account(self, **kw):
        self._emit("acct", **kw)

    def stat(self, **kw):
        self._emit("stat", **kw)

    def lane(self, **kw):
        self._emit("lane", **kw)

    def note(self, msg: str):
        self._emit("note", msg=msg)
```

- [ ] **Step 4: เขียน `bot/engine/pool.py`**

```python
"""thread pool ที่แทนฝูง 128 โปรเซส

เธรดหนึ่งตัว = หนึ่งบัญชีที่กำลังทำอยู่ เธรดทุกตัวของ lane เดียวกันใช้งบ request
ก้อนเดียวกัน และทุกตัวดึงงานจากคิวกลางตัวเดียว ไม่มีการแบ่งงานล่วงหน้า - แบ่งล่วงหน้า
แปลว่า worker ที่เจอบัญชีพังรัว ๆ จบก่อนแล้วนั่งว่างขณะที่ตัวอื่นยังมีคิวยาว
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools"))
import rangers_api   # noqa: E402

from . import flows as flows_mod   # noqa: E402
from .proxy import ProxyPool       # noqa: E402
from .session import AccountSession, Outcome   # noqa: E402

STAT_EVERY = 2.0       # วินาที - ผูกกับเวลา ไม่ใช่จำนวนบัญชี คิวที่เดินช้าก็ยังมีสัญญาณชีพ
DRAIN_LIMIT = 60.0     # ให้เวลาบัญชีที่ค้างอยู่จบก่อนเลิก
LANE_RETRY = 300.0     # วินาที - proxy ที่ล่มชั่วคราวได้กลับมาเอง ไม่ต้องรีสตาร์ททั้ง engine


class EnginePool:
    def __init__(self, mode, cfg, queue, proxies, reporter, flow=None) -> None:
        self.mode = mode
        self.cfg = cfg
        self.queue = queue
        self.reporter = reporter
        self.flow = flow if flow is not None else flows_mod.run
        self.pool = ProxyPool(
            proxies,
            rps=float(cfg.get("apirps") or 90),
            threads_per=int(cfg.get("threadsperproxy") or 96),
            max_threads=int(cfg.get("maxthreads") or 4096))
        if self.pool.capped:
            self.reporter.note(
                "threads capped: %d requested, %d running (ceiling %s)"
                % (self.pool.capped + self.pool.total_threads(),
                   self.pool.total_threads(), cfg.get("maxthreads") or 4096))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._done = 0
        self._fail = 0

    def request_stop(self) -> None:
        """หยุดรับงานใหม่ บัญชีที่ค้างอยู่ทำต่อจนจบ

        ตรงข้ามกับ terminate() ทันที ซึ่งทิ้งทั้งงานครึ่งทางและยอดสุดท้ายของมัน
        """
        self._stop.set()

    def _worker(self, lane) -> None:
        rangers_api.use_lane(lane)
        while not self._stop.is_set():
            if not lane.alive:
                # proxy ของเธรดนี้ตาย - ออกไปเลย งานที่ยังไม่ถูก claim ยังอยู่ในคิวให้ lane
                # อื่นหยิบต่อ ไม่มีอะไรหาย
                return
            src = self.queue.claim()
            if src is None:
                return
            started = time.time()
            session = AccountSession(src=src, lane=lane)
            try:
                out = self.flow(self.mode, session, self.cfg)
            except Exception as err:
                out = Outcome(dest="login failed", status="FAIL", error=str(err)[:200])
            try:
                if out.dest == "login failed":
                    self.queue.fail(src, out.error or out.status)
                else:
                    self.queue.finish(src, out.dest, out.name)
            except OSError as err:
                self.reporter.note("could not move %s: %s" % (os.path.basename(src), err))
            with self._lock:
                if out.status == "OK":
                    self._done += 1
                else:
                    self._fail += 1
            self.reporter.account(status=out.status, rsn=session.rsn, lv=session.level,
                                  ms=int((time.time() - started) * 1000), dest=out.dest,
                                  lane=lane.name, err=out.error[:120])

    def run(self) -> dict:
        started = time.time()
        threads = []
        for lane in self.pool.alive_lanes():
            for i in range(lane.threads):
                t = threading.Thread(target=self._worker, args=(lane,),
                                     name="%s-%d" % (lane.name, i), daemon=True)
                t.start()
                threads.append(t)

        announced = set()
        last_retry = time.time()
        while any(t.is_alive() for t in threads):
            time.sleep(STAT_EVERY)
            with self._lock:
                done, fail = self._done, self._fail
            elapsed = max(0.001, time.time() - started)
            alive = self.pool.alive_lanes()

            for lane in self.pool.lanes:
                if not lane.alive and lane.name not in announced:
                    announced.add(lane.name)
                    self.reporter.lane(name=lane.name, state="dead",
                                       reason="connect failed 3x in a row")

            if not alive:
                # วิ่งต่อโดยไม่มี proxy เลย = ทุก request ออก IP ของเครื่องผู้ใช้เอง
                # ซึ่งเป็นสิ่งที่ผู้ใช้ตั้ง proxy ไว้เพื่อหลีกเลี่ยงพอดี หยุดดีกว่า
                self.reporter.note("every proxy is down - stopping")
                self._stop.set()
                break

            if time.time() - last_retry >= LANE_RETRY:
                last_retry = time.time()
                for lane in self.pool.lanes:
                    if not lane.alive:
                        lane.revive()
                        announced.discard(lane.name)
                        self.reporter.lane(name=lane.name, state="retry")
                        for i in range(lane.threads):
                            t = threading.Thread(target=self._worker, args=(lane,),
                                                 name="%s-r%d" % (lane.name, i), daemon=True)
                            t.start()
                            threads.append(t)

            self.reporter.stat(done=done, fail=fail, left=self.queue.remaining(),
                               rate=round(done / elapsed, 2),
                               threads=sum(1 for t in threads if t.is_alive()),
                               lanes=len(alive))
            if self._stop.is_set() and time.time() - started > DRAIN_LIMIT:
                break

        for t in threads:
            t.join(timeout=DRAIN_LIMIT)
        with self._lock:
            done, fail = self._done, self._fail
        elapsed = max(0.001, time.time() - started)
        summary = {"done": done, "fail": fail, "left": self.queue.remaining(),
                   "seconds": round(elapsed, 1), "rate": round(done / elapsed, 2)}
        self.reporter.stat(**dict(summary, final=True))
        return summary
```

- [ ] **Step 5: เขียน `bot/engine_main.py`**

```python
"""entry ของ engine - รันโหมด headless หนึ่งโหมดจนคิวหมด แล้วออก

ไม่ import GUI: ไฟล์นี้คือ __main__ ของโปรเซส engine การให้มันเป็น main.py แปลว่า
customtkinter ถูกโหลดในทุกโปรเซสที่สปอว์น
"""
import configparser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

from engine.pool import EnginePool       # noqa: E402
from engine.queue import WorkQueue       # noqa: E402
from engine.report import Reporter       # noqa: E402

import ratelimit    # noqa: E402

BOOLS = ("gacharanger", "genidlevel3", "stopwhenfound")
INTS = ("leveltarget", "stageend", "rewardpasses", "threadsperproxy", "maxthreads",
        "gachacycles")


def load_config(path, rangers_path=None):
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    cfg = dict(parser["settings"]) if parser.has_section("settings") else {}
    for key in BOOLS:
        if key in cfg:
            cfg[key] = str(cfg[key]).strip().lower() in ("true", "1", "yes")
    for key in INTS:
        if key in cfg:
            try:
                cfg[key] = int(cfg[key])
            except ValueError:
                del cfg[key]        # ค่าเสีย = ใช้ค่าปริยาย ไม่ใช่ล้มทั้ง engine
    # รายชื่อ ranger เป้าหมาย - เคยเป็น global RANGERSCONFIG ใน botLineRanger ตอนนี้เดินทาง
    # ไปกับ cfg เพื่อให้ flows ไม่ต้องอ่านอะไรจากระดับโมดูล
    if rangers_path and os.path.isfile(rangers_path):
        rparser = configparser.ConfigParser()
        rparser.read(rangers_path, encoding="utf-8")
        cfg["_rangers_config"] = {
            k.lower(): str(v).strip().lower() in ("true", "1", "yes")
            for section in rparser.sections()
            for k, v in rparser[section].items()}
    else:
        cfg["_rangers_config"] = {}
    return cfg


def main(argv):
    # stdout เป็นช่องรายงาน JSONL ข้อความไทยต้องไม่ตายที่ cp1252
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    mode = argv[1] if len(argv) > 1 else "ranger_api_Login"
    root = os.getcwd()
    cfg = load_config(os.path.join(root, "src", "config.ini"),
                      os.path.join(root, "src", "configRangers.ini"))
    reporter = Reporter()

    queue = WorkQueue(root, os.path.join(root, "src", "log", "run.jsonl"))
    rescued = queue.recover()
    if rescued:
        reporter.note("recovered %d file(s) left in execute/ by an earlier run" % rescued)

    proxies = ratelimit.parse_proxies(cfg.get("apiproxies", ""))
    pool = EnginePool(mode, cfg, queue, proxies, reporter)

    stop_flag = os.path.join(root, "src", "log", "stop.flag")
    if os.path.exists(stop_flag):
        os.remove(stop_flag)

    import threading

    def watch():
        import time
        while not os.path.exists(stop_flag):
            time.sleep(1.0)
        pool.request_stop()

    threading.Thread(target=watch, daemon=True).start()

    try:
        pool.run()
    finally:
        queue.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 6: เขียน bench ที่ไม่แตะเน็ต**

สร้าง `bot/tests/bench_engine.py`:

```python
"""วัดเพดาน *ฝั่งเรา* โดยไม่ยิงเซิร์ฟเวอร์เกมสักครั้ง

รัน: PYTHONUTF8=1 python bot/tests/bench_engine.py 500 128
ตัวเลขที่ได้ตอบคำถามว่า "ถ้าเกมเร็วเป็นอนันต์ เราจะระบายคิวได้เร็วแค่ไหน" - รอบที่
ของจริงช้ากว่านี้มากแปลว่าคอขวดอยู่ที่ปลายทาง ไม่ใช่ที่เรา
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
from engine.pool import EnginePool       # noqa: E402
from engine.queue import WorkQueue       # noqa: E402
from engine.report import Reporter       # noqa: E402
from engine.session import Outcome       # noqa: E402

LATENCY = 0.05      # วินาทีต่อบัญชี แทนเวลารอเน็ต


def main(count, threads):
    root = tempfile.mkdtemp(prefix="bench-")
    try:
        for sub in ("input", "execute", "output", "backup", "login failed", "log"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        for i in range(count):
            with open(os.path.join(root, "input", "%06d.xml" % i), "w", encoding="utf-8") as fh:
                fh.write("<map/>")
        queue = WorkQueue(root, os.path.join(root, "log", "run.jsonl"))

        def flow(mode, s, cfg):
            time.sleep(LATENCY)
            return Outcome(dest="output", name="")

        started = time.time()
        summary = EnginePool("ranger_api_Login", {"threadsperproxy": threads},
                             queue, [], Reporter(io.StringIO()), flow=flow).run()
        queue.close()
        elapsed = time.time() - started
        print("%d accounts - %d threads - %.1fs - %.1f accounts/s (ideal %.1f)"
              % (count, threads, elapsed, count / elapsed, threads / LATENCY))
        return summary
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500,
         int(sys.argv[2]) if len(sys.argv) > 2 else 128)
```

- [ ] **Step 7: รันเทสต์และ bench**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_pool.py -q`
คาดผล: PASS ทั้ง 9 ตัว

รัน: `PYTHONUTF8=1 python bot/tests/bench_engine.py 2000 256`
คาดผล: พิมพ์อัตราออกมา และตัวเลขที่ได้ต้องอยู่ในระดับเดียวกับ `ideal` (ภายใน ~30%)
ถ้าต่ำกว่านั้นมากแปลว่าคิวหรือ journal เป็นคอขวด **ให้รายงาน ไม่ใช่ปล่อยผ่าน**

- [ ] **Step 8: Commit**

```bash
git add bot/engine/report.py bot/engine/pool.py bot/engine_main.py bot/tests/test_pool.py bot/tests/bench_engine.py
git commit -m "feat(engine): one process, one thread per in-flight account, JSONL out"
```

---

## Task 10: GUI สปอว์น engine ตัวเดียว

**Files:**
- Modify: `bot/main.py`
- Modify: `bot/default_config/config.ini`

**Interfaces:**
- Consumes: `bot/engine_main.py` (9)
- Produces: GUI ที่สปอว์น engine หนึ่งตัวและอ่าน JSONL จาก stdout ของมัน

- [ ] **Step 1: เพิ่มคีย์ใหม่ใน `bot/default_config/config.ini`**

เพิ่มใต้ `apiproxies =` ในหมวด `[settings]`:

```ini
rewardpasses = 3
threadsperproxy = 96
maxthreads = 4096
```

`apirps` เปลี่ยนค่าเริ่มต้นจาก `80` เป็น `90` — งบเดิมตั้งไว้ต่ำเพราะแต่ละบัญชีจ่าย
26 request พอเหลือ ~15 ก็ขยับเข้าใกล้เพดานจริงของเกม (~100) ได้โดยไม่ชน

**ห้ามเปลี่ยนชื่อคีย์เดิม** ผู้ใช้มี `src/config.ini` ของตัวเองอยู่แล้ว คีย์ใหม่ที่ไม่มี
ในไฟล์เขาต้องมี fallback ในโค้ดเสมอ

- [ ] **Step 2: แทนที่การสปอว์น worker ด้วยการสปอว์น engine**

ใน `bot/main.py` แทนที่ `_spawn_worker` (บรรทัด ~1807) ด้วย:

```python
    def _spawn_engine(self, mode="ranger_api_Login"):
        """สปอว์น engine หนึ่งตัว - ไม่ใช่ N worker อีกแล้ว

        เดิม N worker คูณทุกอย่าง: 128 โปรเซส x 44 MB และเมื่อ frozen ยังคูณการแตก
        บันเดิล onefile 87 MB ลง %TEMP% ของแต่ละตัวอีกชั้น ตอนนี้เธรดอยู่ในโปรเซสเดียว
        และ engine เป็นคนแบ่งเธรดตาม proxy เอง
        """
        botdir = self._app_root()
        no_window = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--engine", mode]
        else:
            args = [sys.executable, os.path.join(botdir, "engine_main.py"), mode]
        err_path = os.path.join(botdir, "src", "log", "engine.err")
        os.makedirs(os.path.dirname(err_path), exist_ok=True)
        # stderr ลงไฟล์ ไม่ใช่ DEVNULL: traceback ของลูกที่ตายเงียบคือหลักฐานชิ้นเดียวที่มี
        self._engine_err = open(err_path, "w", encoding="utf-8")
        return subprocess.Popen(
            args, cwd=botdir, creationflags=no_window, env=self._worker_env(),
            stdout=subprocess.PIPE, stderr=self._engine_err,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
```

- [ ] **Step 3: อ่าน JSONL ด้วยเธรดเดียว อัปเดตจอทุก 1 วินาที**

เพิ่มเมธอดใน `bot/main.py`:

```python
    def _read_engine(self, proc):
        """อ่าน JSONL จาก engine สะสมไว้ แล้วให้ตัวจับเวลาของ GUI ไปวาดทีเดียว

        วาดทุกบรรทัดคือการวาดหลายร้อยครั้งต่อวินาทีตอนฝูงเต็มกำลัง แผงคุมจะช้าลง
        เรื่อย ๆ ตลอดเวลาที่บอทรัน
        """
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            with self._engine_lock:
                self._engine_rows.append(row)

    def _drain_engine_rows(self):
        """เรียกจาก self.after(1000, ...) ของ GUI"""
        with self._engine_lock:
            rows, self._engine_rows = self._engine_rows, []
        for row in rows:
            kind = row.get("t")
            if kind == "stat":
                self._updateEngineStats(row)
            elif kind == "acct":
                self._appendSessionRow(row)
            elif kind == "lane":
                self._updateLane(row)
            elif kind == "note":
                self.log(row.get("msg", ""))
        if self.worker_procs:
            self.after(1000, self._drain_engine_rows)
```

- [ ] **Step 4: เปลี่ยนปุ่มหยุดให้ใช้ธง ไม่ใช่ terminate**

แทนที่เนื้อในของตัวหยุด Login worker (บรรทัด ~1040) ด้วย:

```python
        # ขอให้ engine หยุดรับงานใหม่แล้วปล่อยให้บัญชีที่ค้างอยู่จบ - terminate() ทันที
        # ทิ้งทั้งงานครึ่งทางและยอดสุดท้ายของมัน (เคยขาดไป 1,427 ใบในรอบ mint จริง)
        flag = os.path.join(self._app_root(), "src", "log", "stop.flag")
        try:
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            open(flag, "w").close()
        except OSError as err:
            self.log("stop flag failed: %s" % err)
        for proc in list(self.worker_procs.values()):
            try:
                proc.wait(timeout=90)       # ให้เวลาระบายงานที่ค้าง
            except subprocess.TimeoutExpired:
                proc.terminate()            # ไม่ยอมจบใน 90 วิถึงค่อยบังคับ
```

- [ ] **Step 5: เพิ่มโหมด `--engine` ใน `__main__`**

ใน `bot/main.py` แทนที่บล็อก `--worker` (บรรทัด ~2605) ด้วย:

```python
    # โหมด engine (เฉพาะ frozen exe ที่รันสคริปต์ .py ไม่ได้) - รันคิวจนหมดแล้วออก ไม่เปิด GUI
    # dev รันผ่าน engine_main.py โดยตรง จึงไม่เข้าเงื่อนไขนี้
    if len(sys.argv) > 1 and sys.argv[1] == "--engine":
        from engine_main import main as engine_main
        sys.exit(engine_main(["engine"] + sys.argv[2:]))
```

- [ ] **Step 6: ตรวจว่า GUI เปิดได้และเริ่มงานได้**

รัน: `PYTHONUTF8=1 python bot/main.py`
คาดผล: หน้าต่างเปิดได้ · เลือกโหมด Login แล้วกดเริ่ม · log แสดงบรรทัดจาก engine ·
ไฟล์ `bot/src/log/engine.err` ถูกสร้าง (ว่างได้) · กดหยุดแล้ว `execute/` ว่างภายใน 90 วินาที

ถ้าไม่มีไฟล์บัญชีทดสอบ ให้ copy จาก `bot/input/` มาสัก 5 ไฟล์ใส่โฟลเดอร์ทดลองแยก
**ห้ามรันกับ `bot/input/` ตัวจริง**

- [ ] **Step 7: Commit**

```bash
git add bot/main.py bot/default_config/config.ini
git commit -m "feat(gui): the panel starts one engine and reads its progress, instead of 128 workers"
```

---

## Task 11: ลบระบบ ADB

**Files:**
- Delete: `bot/ADB.py` · `bot/nemu_capture.py` · `bot/bot_worker.py`
- Modify: `bot/botLineRanger.py` · `bot/main.py` · `bot/requirements.txt`
- Create: `bot/tests/test_no_adb.py`

**Interfaces:**
- Consumes: ทุก task ก่อนหน้า (flow ใหม่ต้องใช้งานได้แล้วก่อนลบของเก่า)
- Produces: ไม่มีชื่อใหม่ มีแต่ของที่หายไป

- [ ] **Step 1: เขียนเทสต์ที่ห้ามให้ ADB กลับมา**

สร้าง `bot/tests/test_no_adb.py`:

```python
"""ยามกันไม่ให้ ADB คืนชีพ

บั๊กที่กันไว้: การลบของที่ตายแล้วโดยไม่ไล่หาผู้เรียก - โปรเจกต์พี่น้องเคยลบตัวสร้าง
โฟลเดอร์ทิ้งโดยที่ยังมีปุ่ม 15 ปุ่มเรียกมันอยู่ ทั้งคู่พังเงียบ
"""
import os
import re

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("ADB.py", "nemu_capture.py", "bot_worker.py")
BANNED = ("ppadb", "uiautomator2", "adbutils", "cv2", "pytesseract",
          "pure-python-adb", "opencv")


def sources():
    for root, dirs, files in os.walk(BOT):
        dirs[:] = [d for d in dirs
                   if d not in ("build", "dist", "dist_pyarmor", "Version", "__pycache__",
                                "src", "input", "output", "backup", "execute", "tests")]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_the_adb_modules_are_gone():
    for name in GONE:
        assert not os.path.exists(os.path.join(BOT, name)), name


def test_nothing_imports_a_device_library_any_more():
    """ยืนยันตัวตนของไฟล์ที่ผิด ไม่ใช่แค่นับ - รายงานจะได้บอกว่าไปแก้ที่ไหน"""
    guilty = []
    for path in sources():
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for word in BANNED:
            if re.search(r"^\s*(import|from)\s+%s\b" % re.escape(word.replace("-", "_")),
                         text, re.M):
                guilty.append("%s imports %s" % (os.path.relpath(path, BOT), word))
    assert guilty == [], guilty


def test_requirements_no_longer_pull_the_device_stack():
    with open(os.path.join(BOT, "requirements.txt"), encoding="utf-8") as fh:
        text = fh.read().lower()
    for word in BANNED:
        assert word not in text, word
```

- [ ] **Step 2: รันเทสต์ให้เห็นว่ามันล้มเหลว**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/test_no_adb.py -q`
คาดผล: FAIL ทั้ง 3 ตัว

- [ ] **Step 3: ลบไฟล์และ dependency**

```bash
git rm bot/ADB.py bot/nemu_capture.py bot/bot_worker.py
```

แทนที่ `bot/requirements.txt` ทั้งไฟล์ด้วย:

```
# GUI
customtkinter
pillow

# Network / updater
requests
psutil

# Security / config encryption
cryptography
```

- [ ] **Step 4: ตัดส่วน ADB ออกจาก `botLineRanger.py`**

ลบ `from ppadb.client import Client as AdbClient` (บรรทัด 12) และ
`from ADB import setup_emulators` (บรรทัด 8713)

จากนั้นลบทุกฟังก์ชันที่แตะ device/vision/OCR **ทีละตัว โดยตรวจผู้เรียกก่อนลบเสมอ**:

```bash
# ก่อนลบฟังก์ชันชื่อ X ทุกครั้ง:
grep -rn "\bX\b" bot/ tools/ --include=*.py
# เจอแค่บรรทัด def ของตัวมันเอง = ลบได้ · เจอผู้เรียกอื่น = ต้องจัดการผู้เรียกก่อน
```

ของที่ต้อง **เก็บไว้** คือผิวที่ engine ยังเรียกอยู่ ตรวจด้วย:

```bash
grep -rn "botLineRanger\." bot/engine/ bot/main.py
```

ทุกอย่างที่ไม่โผล่ในผลลัพธ์นั้นและไม่มีผู้เรียกอื่น = ลบได้

- [ ] **Step 4b: ลบโค้ดกาชาและ roster ที่ Task 6 ย้ายไป `tools/` แล้ว**

Task 6 ย้าย `apiGachaWithTicket` และลูปสรุปชื่อ ranger ของ `getAccoutInfo` ไปเป็น
`tools/gacha.draw_with_ticket` กับ `tools/pull_roster.unit_names` แต่**ไม่ได้ลบต้นฉบับ** เพราะตอนนั้น
ยังมีผู้เรียกอยู่ ตอนนี้ engine ใช้ตัวใน `tools/` แล้ว ต้นฉบับจึงเป็นโค้ดซ้ำที่ไม่มีใครเรียก

ตัวที่ต้องตรวจแล้วลบ (ไม่ได้อยู่ในรายการ ADB/vision จึงตกสำรวจถ้าไม่เขียนไว้ตรงนี้):

```
apiGachaWithTicket · _gachaGroupPull · matchGachaName · add_ranger_name
getTeanInfo · getRubyAndTicket · getAccoutInfo · currentLevel · apiGetPlayer
```

ใช้วิธีเดียวกับ Step 4: `grep -rn "X" bot/ tools/ --include=*.py` ก่อนลบทุกตัว เจอแค่บรรทัด
`def` ของตัวเอง = ลบได้ **ห้ามลบตามรายการนี้โดยไม่ตรวจ** — ถ้าตัวไหนยังมีผู้เรียกที่มีชีวิต
ให้เก็บไว้แล้วรายงานว่าตัวไหนและใครเรียก

> เหตุผลที่ต้องเขียนขั้นนี้ไว้ชัด ๆ: reviewer ของ Task 6 ไล่อ่าน brief ครบทั้ง 12 ใบแล้วพบว่า
> **ไม่มี task ไหนเลยที่ปลดระวางต้นฉบับพวกนี้** Step 4 ของ task นี้ระบุขอบเขตเป็น "ฟังก์ชันที่แตะ
> device/vision/OCR" ซึ่งกาชากับ roster ไม่เข้าข่าย โค้ดซ้ำ ~180 บรรทัดจึงจะค้างอยู่ตลอดไป


- [ ] **Step 5: ตัดส่วน ADB ออกจาก `main.py`**

ลบ: การเลือก device/emulator ทั้งชุด · การเรียก `setup_emulators` · ตัวเลือก
`"🛠 Auto Setup"` ที่คอมเมนต์ไว้ · `_spawn_worker` ตัวเก่า (ถ้ายังเหลือ) ·
`multiprocessing.set_executable` ทั้งสามจุด (ไม่ได้ใช้ multiprocessing แล้ว)

คำที่ใช้ค้นหา: `grep -n 'DEVICE\|device\|adb\|emulator\|uiautomator\|screencap' bot/main.py`

- [ ] **Step 6: รันเทสต์ทั้งหมดให้ผ่าน**

รัน: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q`
คาดผล: PASS ทั้งหมด

รัน: `PYTHONUTF8=1 python -c "import sys; sys.path.insert(0,'bot'); import botLineRanger"`
คาดผล: ไม่มี error และไม่กินเวลาเกิน 1 วินาที (เดิม ppadb อย่างเดียวกิน 202 ms)

- [ ] **Step 7: Commit**

```bash
git add -u bot/ && git add bot/tests/test_no_adb.py
git commit -m "refactor(bot): delete the ADB, vision and OCR stack no play mode has used since AutoSetup"
```

---

## Task 12: build เป็น onedir

**Files:**
- Modify: `bot/BotLineRanger.spec`
- Modify: `bot/build.bat`

**Interfaces:**
- Consumes: ทุก task ก่อนหน้า
- Produces: `dist/BotLineRanger/` ที่รันได้และเล็กลง

- [ ] **Step 1: ตัด binaries/datas/hiddenimports ที่ไม่ใช้แล้ว**

ใน `bot/BotLineRanger.spec`:

ลบ `_safe_collect_all('uiautomator2')` · `_safe_collect_all('adbutils')` และทุกที่ที่อ้าง
`_u2_datas` `_u2_bins` `_adb_datas` `_adb_bins`

ลบจาก `binaries`: `*collect_dynamic_libs('cv2')`
ลบจาก `datas`: บรรทัด `ppadb` และ `pytesseract`
ลบจาก `hiddenimports`: `'ADB'` และชื่อที่เกี่ยวกับ cv2/numpy/uiautomator2 ทั้งหมด

เพิ่มใน `excludes` (ลดขนาดโดยบังคับ ไม่ใช่หวังว่าจะไม่ถูกลาก):

```python
    excludes=[
        'unittest',
        'pydoc',
        # ไม่มีโหมดไหนใช้แล้วตั้งแต่ลบ ADB - ใส่ไว้กันการถูกลากเข้ามาทางอ้อม
        'cv2', 'numpy', 'pytesseract', 'uiautomator2', 'adbutils', 'ppadb',
    ],
```

- [ ] **Step 2: เปลี่ยนเป็น onedir**

แทนที่บล็อก `exe = EXE(...)` ท้ายไฟล์ด้วย:

```python
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir: binaries/datas ไปอยู่ใน COLLECT ไม่ใช่ในตัว exe
    name='BotLineRanger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # onefile+UPX ต้องแตกตัวเองลง %TEMP% ทุกครั้งที่โปรเซสเริ่ม
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\image\\home\\BotLineRanger_128.ico'],
)

# onedir: ไฟล์ทั้งหมดวางข้าง exe ไม่ต้องแตกบันเดิล 87 MB ลง %TEMP% ตอนสตาร์ท
# และโปรแกรมป้องกันไวรัสไม่หวาดระแวงเท่า onefile ที่ถูกบีบด้วย UPX
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BotLineRanger',
)
```

เพิ่ม `COLLECT` เข้า import ท้าย `from PyInstaller...` ถ้า spec ยังไม่มี (PyInstaller
ใส่ `COLLECT` ให้ใน namespace ของ spec อยู่แล้ว ไม่ต้อง import — ตรวจด้วยการ build)

- [ ] **Step 3: แก้ `build.bat`**

ลบ `ADB.py` และ `nemu_capture.py` ออกจากบรรทัด `pyarmor gen` แล้วเพิ่ม `engine_main.py`:

```bat
pyarmor gen --output dist_pyarmor ^
    main.py botLineRanger.py engine_main.py config_secure.py hwid.py protection.py
```

> **ผู้ลงมือต้องตรวจ:** pyarmor กับไฟล์ในโฟลเดอร์ย่อย (`engine/*.py`) — ถ้า `pyarmor gen`
> ไม่รับ package ให้ obfuscate เฉพาะไฟล์ระดับบนแล้วปล่อย `engine/` เป็น plain
> แล้ว **รายงานว่าทำแบบไหน** อย่าเงียบ

เปลี่ยนส่วนย้ายไฟล์ (onedir ให้ผลเป็นโฟลเดอร์อยู่แล้ว ไม่ต้อง move exe):

```bat
REM onedir: PyInstaller วาง dist\BotLineRanger\ ให้ครบแล้ว ไม่ต้องย้าย exe เอง
if exist "dist\updater.exe" (
    move /Y "dist\updater.exe" "dist\BotLineRanger\updater.exe" >nul
)
```

เปลี่ยนการ copy `src` ให้ข้าม Tesseract และ adb:

```bat
xcopy "src" "dist\BotLineRanger\src" /E /H /C /I /Y /EXCLUDE:exclude_dist.txt >nul
```

สร้าง `bot/exclude_dist.txt`:

```
\Tesseract-OCR\
\adb\
\image\
\log\
\split-ID\
```

- [ ] **Step 4: build จริงแล้ววัดขนาด**

รัน: `cd bot && build.bat`
คาดผล: build ผ่าน · `dist/BotLineRanger/BotLineRanger.exe` มีอยู่

รัน: `PYTHONUTF8=1 python -c "import os;p='bot/dist/BotLineRanger';print(sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(p) for f in fs)//1048576,'MB')"`
คาดผล: **ไม่เกิน 60 MB** (เดิม zip อย่างเดียว 150 MB) ถ้าเกินให้หาว่าอะไรยังถูกลากมา
ด้วย `dist/BotLineRanger/` แล้วเรียงตามขนาด **แล้วรายงาน อย่าปล่อยผ่าน**

- [ ] **Step 5: ทดสอบ .exe จริง**

เปิด `dist/BotLineRanger/BotLineRanger.exe` แล้ว:
- หน้าต่างเปิดได้
- ใส่ไฟล์บัญชีทดสอบ 5 ไฟล์ใน `dist/BotLineRanger/input/` (**คัดลอกมา ห้ามย้ายของจริง**)
- เลือกโหมด Login กดเริ่ม → ไฟล์เดินไปที่ `output/`
- ปิดโปรแกรมกลางคัน แล้วเปิดใหม่ → ไฟล์ที่ค้างใน `execute/` ต้องกลับไป `input/`
- ตรวจว่า **ไม่มี** โฟลเดอร์ `_MEI*` ใหม่เกิดใน `%TEMP%` (ยืนยันว่าเป็น onedir จริง)

- [ ] **Step 6: Commit**

```bash
git add bot/BotLineRanger.spec bot/build.bat bot/exclude_dist.txt
git commit -m "build: ship a folder instead of a self-extracting 87 MB exe"
```

---

## หลังจบทุก task

1. รันเทสต์ทั้งหมด: `PYTHONUTF8=1 python -m pytest bot/tests/ tools/tests/ -q`
2. รัน bench: `PYTHONUTF8=1 python bot/tests/bench_engine.py 5000 512`
3. **รอบจริงกับบัญชีจริง** — คัดลอกไฟล์จาก `bot/input/` ไปโฟลเดอร์ทดสอบแยก
   (ห้ามรันกับของจริงในรอบแรก) แล้ววัดสี่ค่าตามตารางในข้อ 13 ของ spec:
   RAM · request/บัญชี · บัญชี/นาที · ไฟล์ค้างหลังฆ่าโปรเซส
   **จับเวลาที่ใช้ระบายคิวจนหมด ไม่ใช่ขนาดคิวหารเวลา** และอย่าวัดตอนเครื่องไม่ว่าง
4. เทียบผลกับตัวเลขที่ spec คาดไว้ **ถ้าไม่ตรงให้รายงานตัวเลขจริง ไม่ใช่แก้ spec ให้เข้ากับผล**
5. อัปเดต `README.md` ให้ตรงกับของที่ทำงานจริง
6. ใช้ skill `superpowers:finishing-a-development-branch` ตัดสินว่าจะ merge อย่างไร
