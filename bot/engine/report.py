"""รายงานความคืบหน้าเป็น JSONL หนึ่งบรรทัดหนึ่งเหตุการณ์บน stdout

GUI อ่านฝั่งตรงข้ามแล้วสะสมไว้อัปเดตจอทุกหนึ่งวินาที ไม่ใช่ทุกบรรทัด - แผงคุมที่วาดกราฟ
ใหม่ทุก log line ช้าลงเรื่อย ๆ ตลอดเวลาที่บอทรัน
"""
from __future__ import annotations

import json
import sys
import threading
import time

# แถวที่เก็บลงไฟล์ด้วย (log_path): ยอดรวม/สถานะ autoscaler/proxy/ข้อความ - พอให้ย้อนดูได้ว่ารันที่แล้ว
# เธรดกับงบ req/s ขยับยังไง GUI ไม่ได้เก็บอะไรลงดิสก์ และ run.jsonl ของคิวรู้แค่ไฟล์เข้า-ออก
# (acct มีใน run.jsonl แล้ว, active ใหญ่และเปลี่ยนทุกวินาที - ไม่เก็บ)
LOGGED_KINDS = ("stat", "lane", "note")


class Reporter:
    def __init__(self, stream=None, log_path=None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self._log = open(log_path, "w", encoding="utf-8", buffering=1) if log_path else None
        # Many worker threads call account()/stat()/lane() concurrently; without this lock
        # two threads' json.dumps() + write() calls can interleave mid-line, handing the GUI
        # a line that is not valid JSON on either side of the split.
        self._lock = threading.Lock()

    def _emit(self, kind: str, **row) -> None:
        row["t"] = kind
        with self._lock:
            self.stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.stream.flush()
            if self._log is not None and kind in LOGGED_KINDS:
                self._log.write(json.dumps(dict(row, ts=round(time.time(), 1)),
                                           ensure_ascii=False) + "\n")

    def account(self, **kw):
        self._emit("acct", **kw)

    def stat(self, **kw):
        self._emit("stat", **kw)

    def lane(self, **kw):
        self._emit("lane", **kw)

    def active(self, **kw):
        """ภาพรวมบัญชีที่กำลังทำทั้งหมดในบรรทัดเดียว (ทุกวินาที) - ไม่ใช่หนึ่งบรรทัดต่อการขยับขั้น
        ซึ่งตอนเธรดเป็นร้อยคือหลายร้อยบรรทัดต่อวินาที"""
        self._emit("active", **kw)

    def note(self, msg: str):
        self._emit("note", msg=msg)
