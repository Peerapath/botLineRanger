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
        # Many worker threads call account()/stat()/lane() concurrently; without this lock
        # two threads' json.dumps() + write() calls can interleave mid-line, handing the GUI
        # a line that is not valid JSON on either side of the split.
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
