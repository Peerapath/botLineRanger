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
