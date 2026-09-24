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
import sys
import threading
import time

DESTS = ("output", "backup", "login failed")

# Windows can hold a rename target open for a moment - AV scan, indexer, another
# thread mid-read (global constraint #13). Retrying turns that transient block into
# an ordinary success instead of a file silently dropped from a moved/claimed count
# (global constraint #10: "resource busy" must retry, not be treated as "impossible").
# This is a millisecond-scale rename, so the whole retry budget is kept small.
_REPLACE_MAX_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.05


def _walk_relative_xml(base: str) -> list[str]:
    """เดินทุกโฟลเดอร์ย่อยของ base หาไฟล์ .xml คืน path สัมพัทธ์ (เทียบกับ base)

    C1 (final review): _scan()/recover() เคยใช้ os.listdir แบนราบ ชั้นบนสุดอย่างเดียว -
    ผู้ใช้เก็บบัญชีไว้ในโฟลเดอร์ย่อยจริง เช่น "input/ฝากล็อกอิน 7วัน/" (90 ไฟล์ ระดับบนสุด
    ว่างเปล่า) engine เห็นคิวว่างทั้งที่มีงาน 90 บัญชี บอทเดิมเดิน os.walk("input") ตั้งใจไว้
    แล้ว (af264b0:bot/botLineRanger.py:3313-3320, "ลองใช้ relative path ตรงๆ ก่อน
    (รองรับ subfolder)") - เดินซ้ำที่นี่แทนของเดิม
    """
    found = []
    for dirpath, _dirs, files in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        for name in files:
            if name.endswith(".xml"):
                found.append(name if rel_dir in (".", "") else os.path.join(rel_dir, name))
    return found


def _rename_no_overwrite_with_retry(src: str, dst_dir: str, base_name: str) -> str | None:
    """ย้าย src ไปเป็น dst_dir/base_name - ถ้าชื่อนั้นถูกใช้แล้วให้ลองต่อท้าย _2.._999 แทน

    C3 (final review): os.replace() เขียนทับปลายทางเงียบ ๆ บน Windows ไฟล์ input/ สองใบเป็น
    บัญชีเดียวกันได้จริง (flows.py's AccountClaimRegistry docstring อ้างเคสที่เจอจริง:
    a0bfb087 สองไฟล์) และชื่อ export มาจากข้อมูลในบัญชี ไม่ใช่ชื่อไฟล์ต้นทาง ไฟล์ต้นทางสอง
    ไฟล์ที่ต่างกันจึงคำนวณชื่อ export ชนกันได้จริง os.rename() บน Windows ไม่เขียนทับ (ต่าง
    จาก os.replace()/shutil.move()) - ใช้ FileExistsError นั้นเป็นสัญญาณให้ลองเลขถัดไปแทนการ
    ทำลายไฟล์ที่ไปถึงก่อน (คอมเมนต์เดิมชี้เคสนี้ตรง ๆ ที่ af264b0:bot/botLineRanger.py:
    3073-3081, 3136-3144)

    แต่ละชื่อที่ลองยังผ่าน retry เดียวกับ _replace_with_retry (constraint #13): handle ค้าง
    ชั่วคราวบนชื่อหนึ่ง ต้อง retry ชื่อเดิม ไม่ใช่ถูกอ่านผิดว่า "ชื่อนี้ถูกจองตลอดไป" แล้วข้ามไป
    เลขถัดไปทั้งที่ยังไม่มีใครใช้จริง

    คืน path เต็มของปลายทาง หรือ None ถ้า src หายไปเองก่อนจะย้ายสำเร็จ (FileNotFoundError)
    """
    stem, ext = os.path.splitext(base_name)
    n = 1
    while n < 1000:
        candidate = base_name if n == 1 else "%s_%d%s" % (stem, n, ext)
        dst = os.path.join(dst_dir, candidate)
        attempt = 1
        while True:
            try:
                os.rename(src, dst)
                return dst
            except FileNotFoundError:
                return None
            except FileExistsError:
                n += 1
                break            # ชื่อนี้ถูกไฟล์อื่นจองแล้วจริง ๆ - ลองเลขถัดไป ไม่ retry ชื่อเดิม
            except OSError:
                if attempt == _REPLACE_MAX_ATTEMPTS:
                    raise
                attempt += 1
                time.sleep(_REPLACE_RETRY_DELAY_S)
    raise FileExistsError("too many files named %r in %r" % (base_name, dst_dir))


def _replace_with_retry(src: str, dst: str) -> bool:
    """os.replace(src, dst), retrying a transient OSError up to _REPLACE_MAX_ATTEMPTS times.

    Returns True on success. Returns False only for FileNotFoundError: the source is
    genuinely gone (something else already removed it) - a different case from
    "blocked", and callers skip it quietly. Any other OSError that survives every
    retry is re-raised, so the caller can record and report it instead of the file
    quietly vanishing from a moved/claimed count.
    """
    for attempt in range(1, _REPLACE_MAX_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            if attempt == _REPLACE_MAX_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)
    return False  # unreachable: the loop above always returns or raises


class WorkQueue:
    def __init__(self, root: str, journal_path: str) -> None:
        self.root = root
        self.journal_path = journal_path
        self._lock = threading.Lock()
        self._pending: collections.deque[str] = collections.deque()
        self._scanned = False
        # Set True the first time claim() hands out a file; guards recover()'s
        # precondition (a queue that has already issued work cannot be recovered).
        self._claim_issued = False
        # Permanently-failed renames from the most recent recover() call, so a
        # caller can find out even though recover()'s return value stays the
        # "moved" count for backward compatibility.
        self.recover_failures = 0
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

        Must run exactly once, at startup, before any worker thread calls claim().
        It moves every .xml file sitting in execute/ back to input/ unconditionally;
        if a claim were already active when it ran, that claimed file would be
        pulled back and then handed to a second thread by a later claim(), so two
        threads would process the same account. To make that precondition
        structural rather than just documented, recover() refuses to run once this
        instance has issued a claim.

        Raises:
            RuntimeError: if claim() has already handed a file to a caller on this
                WorkQueue instance.
        """
        with self._lock:
            if self._claim_issued:
                raise RuntimeError(
                    "recover() must run once at startup, before any claim(): this "
                    "WorkQueue has already issued a claim, so recovering now could "
                    "steal a file an active worker still holds")
            execute = os.path.join(self.root, "execute")
            stale = self._open_claims()
            moved = 0
            self.recover_failures = 0
            # C1: walk execute/ recursively too - a crash mid-run strands a claimed file at
            # execute/<sub>/name.xml exactly as easily as at the top level, and it must come
            # back to the SAME subfolder under input/, not get flattened into input/'s top
            # level (which would silently merge unrelated batches together on the next scan).
            for name in sorted(_walk_relative_xml(execute)):
                src = os.path.join(execute, name)
                dst = os.path.join(self.root, "input", name)
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                try:
                    moved_ok = _replace_with_retry(src, dst)
                except OSError as exc:
                    # Otherwise this file drops out of `moved` with no trace and
                    # stays stuck in execute/ for the rest of the run - the exact
                    # bug this class exists to prevent.
                    self._write(t="recover_failed", f=name, why=str(exc)[:200])
                    self.recover_failures += 1
                    continue
                if not moved_ok:
                    continue  # genuinely gone (FileNotFoundError) - nothing to recover
                self._write(t="recover", f=name, known=name in stale)
                moved += 1
            return moved

    def _scan(self) -> None:
        # C1: recurse into subfolders of input/ - see _walk_relative_xml's own docstring.
        folder = os.path.join(self.root, "input")
        self._pending.extend(sorted(_walk_relative_xml(folder)))
        self._scanned = True

    def claim(self) -> str | None:
        with self._lock:
            if not self._scanned:
                self._scan()
            while self._pending:
                name = self._pending.popleft()
                src = os.path.join(self.root, "input", name)
                dst = os.path.join(self.root, "execute", name)
                # name can carry a subfolder (C1) - execute/<sub>/ may not exist yet.
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                try:
                    moved_ok = _replace_with_retry(src, dst)
                except OSError as exc:
                    # Survived every retry - move on to the next file, but log it
                    # instead of dropping it from the queue with no trace.
                    self._write(t="claim_failed", f=name, why=str(exc)[:200])
                    continue
                if not moved_ok:
                    continue      # ไฟล์หายไประหว่างทาง (คนลบเอง) - ข้ามไปตัวถัดไป
                self._write(t="claim", f=name)
                self._claim_issued = True
                return dst
            return None

    def _close(self, src: str, dest: str, new_name: str, **extra) -> str:
        if dest not in DESTS:
            raise ValueError("unknown destination %r (expected one of %r)" % (dest, DESTS))
        name = os.path.basename(src)
        # C1: preserve the account's subfolder across execute/ -> a destination - the old
        # bot's exportFileFromExecuteTo{Output,Backup} both rebuild `sub_dir` under the
        # destination (af264b0:bot/botLineRanger.py:3068-3070, 3131-3134); a claim from
        # input/<sub>/x.xml must land in <dest>/<sub>/, not flatten every subfolder into the
        # destination's top level. GenID's own minted files sit directly in execute/ (no
        # subfolder - see flows.EXECUTE_DIR), so rel_dir is "." there and this is a no-op.
        execute_dir = os.path.join(self.root, "execute")
        rel_dir = os.path.relpath(os.path.dirname(src), execute_dir)
        sub_dir = "" if rel_dir in (".", "") else rel_dir
        out_dir = os.path.join(self.root, dest, sub_dir) if sub_dir else os.path.join(self.root, dest)
        # The journal key has to be the same string claim() wrote, or the two lines never
        # pair up. claim() logs the path relative to input/, which for a subfolder account
        # is "<sub>\x.xml" - logging the bare basename here left every one of those claims
        # open forever in _open_claims(), and every one of the user's accounts lives in a
        # subfolder. recover() only reads that set for an informational flag today, so
        # nothing broke, but the journal's one job is answering "what is still in flight".
        journal_key = os.path.join(sub_dir, name) if sub_dir else name

        # I3 (final review): this rename used to run OUTSIDE self._lock while claim()'s own
        # rename (input/ -> execute/, above) runs INSIDE it - two directions of
        # unsynchronized concurrent renames landing on the SAME execute/ directory (every
        # claim() writes into it, every _close() reads out of it). Measured on this
        # machine: 147.5 accounts/s as shipped (this rename outside the lock) vs 1,193
        # accounts/s with it moved under the same lock claim() already uses, against a
        # 1,236 accounts/s ceiling for a fake queue that touches no files at all - i.e. the
        # unsynchronized renames were fighting each other for the SAME directory's metadata
        # lock, not "moving files" itself being slow (see bot/tests/bench_engine.py and
        # docs/superpowers/specs/2026-09-23-engine-rewrite-design.md limit 6, both updated
        # alongside this fix). The move is microseconds against the ~13s per account spent
        # waiting on the network (this file's own opening docstring) - constraint #13's
        # retry budget on a transient failure is capped at ~0.25s worst case, negligible
        # even serialized behind one lock with thousands of threads sharing it.
        with self._lock:
            os.makedirs(out_dir, exist_ok=True)
            # Finding 1a (review round 1): this is finish()/fail()'s only move, called once
            # per account - 44,000 times over a full run - and it used to be a bare
            # os.replace(), the one rename in this file that skipped the retry claim() and
            # recover() already get. Same Windows transient-handle case as those two
            # (constraint #13): without the retry, the commonest kind of momentary block
            # (AV scan, indexer, another thread mid-read) looked identical to a permanent
            # failure.
            if new_name:
                # C3: a computed export name can collide across two DIFFERENT source files
                # (see _rename_no_overwrite_with_retry's own docstring) - number instead of
                # overwriting. The original-name path below (fail(), which never renames)
                # can't collide this way: two claims can never share one input/ path, and
                # C1 already keeps their subfolders apart, so it keeps plain
                # overwrite-tolerant semantics, matching the old bot's unconditional
                # shutil.move() on that same path.
                out = _rename_no_overwrite_with_retry(src, out_dir, new_name + ".xml")
                moved_ok = out is not None
            else:
                out = os.path.join(out_dir, name)
                moved_ok = _replace_with_retry(src, out)
            if not moved_ok:
                # Both helpers above return/signal False-equivalent only on
                # FileNotFoundError. claim() and recover() can shrug that off and move on
                # to the next file in their own loop - there is no "next file" here: src
                # was this account's alone from claim() to this call, so it vanishing is
                # not a race to skip quietly, it means the move already failed. Raise
                # instead of writing a "done"/"fail" journal line for an `out` path that
                # was never created - EnginePool._run_one already treats any OSError out of
                # finish()/fail() as a failed move, never a silent success.
                raise FileNotFoundError(
                    "cannot move %r into %r/: source vanished before the move completed"
                    % (name, dest))
            self._write(f=journal_key, dest=dest, **extra)
        return out

    def finish(self, src: str, dest: str, new_name: str = "") -> str:
        return self._close(src, dest, new_name, t="done")

    def fail(self, src: str, reason: str) -> str:
        return self._close(src, "login failed", "", t="fail", why=str(reason)[:200])

    def release(self, src: str) -> str:
        """คืนไฟล์ที่หยิบไปแล้วแต่ยังทำไม่จบ (ผู้ใช้กด Stop กลางไอดี) กลับเข้า input/ โฟลเดอร์ย่อยเดิม

        งานเดียวกับที่ recover() ทำตอนเริ่มรอบหน้า แต่ทำทันทีตอนหยุด ตัวนับ input/execute ใน GUI
        จึงถูกต้องตั้งแต่กด Stop ไม่ใช่ค้าง execute: N จนกว่าจะกด Start อีกครั้ง บรรทัด "release"
        ใน journal ปิด claim ของไฟล์นี้ (_open_claims นับทุกแถวที่ไม่ใช่ claim เป็นการปิด)
        """
        execute = os.path.join(self.root, "execute")
        rel = os.path.relpath(src, execute)
        dst = os.path.join(self.root, "input", rel)
        with self._lock:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            if not _replace_with_retry(src, dst):
                raise FileNotFoundError("cannot release %r: it is no longer in execute/" % rel)
            self._write(t="release", f=rel)
        return dst

    def remaining(self) -> int:
        with self._lock:
            if not self._scanned:
                self._scan()
            return len(self._pending)

    def close(self) -> None:
        try:
            self._journal.close()
        except Exception as exc:
            # Teardown must not raise, but a swallowed close/flush error (e.g. a
            # full disk) needs somewhere to land instead of vanishing (constraint #9).
            print(f"WorkQueue.close: journal close failed: {exc!r}", file=sys.stderr)
