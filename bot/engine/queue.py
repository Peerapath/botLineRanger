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
            for name in sorted(os.listdir(execute)):
                if not name.endswith(".xml"):
                    continue
                src = os.path.join(execute, name)
                dst = os.path.join(self.root, "input", name)
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
        out_name = (new_name + ".xml") if new_name else name
        out = os.path.join(self.root, dest, out_name)
        # Finding 1a (review round 1): this is finish()/fail()'s only move, called once per
        # account - 44,000 times over a full run - and it used to be a bare os.replace(),
        # the one rename in this file that skipped the retry claim() and recover() already
        # get. Same Windows transient-handle case as those two (constraint #13): without
        # the retry, the commonest kind of momentary block (AV scan, indexer, another
        # thread mid-read) looked identical to a permanent failure.
        if not _replace_with_retry(src, out):
            # _replace_with_retry only returns False on FileNotFoundError. claim() and
            # recover() can shrug that off and move on to the next file in their own loop -
            # there is no "next file" here: src was this account's alone from claim() to
            # this call, so it vanishing is not a race to skip quietly, it means the move
            # already failed. Raise instead of writing a "done"/"fail" journal line for an
            # `out` path that was never created - EnginePool._run_one already treats any
            # OSError out of finish()/fail() as a failed move, never a silent success.
            raise FileNotFoundError(
                "cannot move %r into %r/: source vanished before the move completed"
                % (name, dest))
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
        except Exception as exc:
            # Teardown must not raise, but a swallowed close/flush error (e.g. a
            # full disk) needs somewhere to land instead of vanishing (constraint #9).
            print(f"WorkQueue.close: journal close failed: {exc!r}", file=sys.stderr)
