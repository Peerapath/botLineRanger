"""WorkQueue: คิวไฟล์บัญชี + journal ที่ทำให้งานค้างกลับมาได้

บั๊กที่เทสต์ชุดนี้กันไว้: รอบทดสอบที่ถูกฆ่ากลางทางทิ้งไฟล์ค้างใน execute/ ไว้ 128 ไฟล์
โดยไม่มีอะไรพากลับมา ไฟล์พวกนั้นหายจากทุกรอบถัดไปโดยไม่มีใครรู้
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

    # daemon=True: a deadlocked worker (see below) must not also keep the whole
    # pytest process alive after the test itself has already reported failure.
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(16)]
    for t in threads:
        t.start()
    # A deadlocking claim() (e.g. a peek instead of a pop) must fail this test fast,
    # not hang the whole run forever - bound the total wait instead of joining with
    # no timeout.
    deadline = time.monotonic() + 10
    for t in threads:
        t.join(timeout=max(0.0, deadline - time.monotonic()))
    assert not any(t.is_alive() for t in threads), "a claim() regression deadlocked a worker thread"
    assert len(got) == 200
    assert len(set(got)) == 200


def test_claim_retries_a_transient_replace_failure_and_still_succeeds(tmp_path, monkeypatch):
    """os.replace ได้ PermissionError ชั่วคราว (มี handle ค้าง) ต้อง retry แล้วสำเร็จ ไม่ใช่ข้ามไฟล์ทิ้ง"""
    q = build(tmp_path, ["a.xml"])
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("[WinError 32] the process cannot access the file")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    got = q.claim()
    assert got == str(tmp_path / "execute" / "a.xml")
    assert os.path.isfile(got)
    assert calls["n"] == 3


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


def test_recover_raises_after_a_claim_has_been_issued(tmp_path):
    """recover() ที่รันหลัง claim() จะดึงไฟล์ที่เธรดอื่นถือ claim อยู่กลับ input/ แล้วแจกซ้ำ - ต้องเด้งแทน"""
    q = build(tmp_path, ["a.xml", "b.xml"])
    claimed = q.claim()
    with pytest.raises(RuntimeError):
        q.recover()
    # the claim must survive the refused recover() untouched
    assert os.path.isfile(claimed)
    assert sorted(os.listdir(tmp_path / "execute")) == ["a.xml"]
    assert os.listdir(tmp_path / "input") == ["b.xml"]


def test_recover_retries_a_transient_replace_failure_and_still_succeeds(tmp_path, monkeypatch):
    """เหมือน claim() - PermissionError ชั่วคราวตอนกู้ไฟล์ต้อง retry แล้วสำเร็จ ไม่ใช่ทิ้งไฟล์ไว้ใน execute/"""
    q = build(tmp_path, ["a.xml"])
    q.claim()
    q.close()

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("[WinError 32] the process cannot access the file")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    q2 = WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))
    assert q2.recover() == 1
    assert sorted(os.listdir(tmp_path / "input")) == ["a.xml"]
    assert os.listdir(tmp_path / "execute") == []
    assert calls["n"] == 3
    assert q2.recover_failures == 0


def test_recover_reports_a_permanently_failing_replace_instead_of_dropping_it(tmp_path, monkeypatch):
    """os.replace ที่พังตลอด (ไม่ใช่ชั่วคราว) ต้องถูกบันทึกใน journal และนับ ไม่ใช่หายไปเงียบ ๆ"""
    q = build(tmp_path, ["a.xml", "b.xml"])
    q.claim()
    q.claim()
    q.close()

    real_replace = os.replace

    def flaky(src, dst):
        if os.path.basename(src) == "a.xml":
            raise PermissionError("[WinError 32] the process cannot access the file")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    q2 = WorkQueue(str(tmp_path), str(tmp_path / "log" / "run.jsonl"))
    assert q2.recover() == 1                      # only b.xml made it back
    assert os.path.isfile(tmp_path / "execute" / "a.xml")   # a.xml stayed put, not lost
    assert q2.recover_failures == 1

    lines = [json.loads(x) for x in (tmp_path / "log" / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = [x for x in lines if x.get("t") == "recover_failed"]
    assert len(failed) == 1
    assert failed[0]["f"] == "a.xml"


def test_remaining_counts_down_as_files_are_claimed(tmp_path):
    q = build(tmp_path, ["a.xml", "b.xml", "c.xml"])
    assert q.remaining() == 3
    q.claim()
    assert q.remaining() == 2


class _BrokenJournal:
    """Stand-in for a file whose close() always fails, and nothing more - unlike a
    real TextIOWrapper it has no __del__ finalizer, so swapping it in doesn't leave
    a broken close() for the garbage collector to call again later."""

    def close(self):
        raise OSError("disk full")


def test_close_reports_a_failure_to_stderr_instead_of_swallowing_it_silently(tmp_path, capsys):
    """ปิด journal ไม่สำเร็จ (เช่นดิสก์เต็ม) ต้องไม่ raise แต่ต้องมีร่องรอยใน stderr ไม่ใช่หายเงียบ"""
    q = build(tmp_path, [])
    q._journal.close()        # release the real file handle before swapping it out
    q._journal = _BrokenJournal()
    q.close()                 # must not raise even though the underlying close() failed
    assert "disk full" in capsys.readouterr().err
