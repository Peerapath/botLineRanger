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
    assert [os.path.relpath(p, str(root)).replace("\\", "/") for p in got] == ["c.xml", "sub/b.xml"]        # a.xml (ok) ถูกข้าม, assert actual order
    got_force = relogin.iter_targets(str(root), done, force=True, limit=None)
    assert len(got_force) == 3
    got_limit = relogin.iter_targets(str(root), {}, force=False, limit=2)
    assert [os.path.relpath(p, str(root)).replace("\\", "/") for p in got_limit] == ["a.xml", "c.xml"]  # sorted order, limit 2 → earliest 2


def test_parse_log_missing_file_returns_empty(tmp_path):
    missing = str(tmp_path / "nope.csv")
    assert relogin.parse_log(missing) == {}


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


def test_process_file_write_failure_returns_error_not_raise(tmp_path, monkeypatch):
    import account_file
    udid = account_file.new_udid()
    src = tmp_path / "acc" / "d.xml"
    src.parent.mkdir()
    _write_guest_xml(src, udid, "OLD")
    monkeypatch.setattr(relogin, "login", lambda *a, **k: (200, {"rsn": "9", "level": 1}, "FRESH"))

    def boom(*a, **k):
        raise OSError("simulated file lock")

    monkeypatch.setattr(relogin, "atomic_write", boom)

    class Pool:
        def get(self): return "cc"
        def is_proven(self): return True
        def mark_proven(self): pass
        def renew(self, old): return "cc2"

    res = relogin.process_file(str(src), str(tmp_path / "acc"), Pool(), str(tmp_path / "bk"))
    assert res["status"] == "error"   # returned, not raised


def test_backup_once_never_overwrites_existing(tmp_path):
    root = tmp_path / "acc"
    root.mkdir()
    f = root / "e.xml"
    f.write_text("NEW-CONTENT", encoding="utf-8")
    backup = tmp_path / "bk"
    backup.mkdir()
    (backup / "e.xml").write_text("ORIGINAL-FIRST-BACKUP", encoding="utf-8")
    relogin.backup_once(str(f), str(root), str(backup))
    assert (backup / "e.xml").read_text(encoding="utf-8") == "ORIGINAL-FIRST-BACKUP"


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


def test_run_logs_error_when_process_file_raises(tmp_path, monkeypatch):
    root = tmp_path / "acc"
    root.mkdir()
    (root / "a.xml").write_text("x", encoding="utf-8")

    class DummyPool:
        def get(self): return "cc"
        def is_proven(self): return True
        def mark_proven(self): pass
        def renew(self, old): return "cc2"

    monkeypatch.setattr(relogin, "CcPool", lambda: DummyPool())

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(relogin, "process_file", boom)
    counts = relogin.run(str(root), workers=1, limit=None, force=False)
    assert counts.get("error") == 1
    import csv as _csv
    with open(str(root) + ".relogin.csv", encoding="utf-8", newline="") as fh:
        rows = list(_csv.DictReader(fh))
    assert rows and rows[0]["status"] == "error"


def test_ccpool_mint_failure_raises_transient(monkeypatch):
    import pytest

    def boom(dev):
        raise SystemExit("trident down")

    monkeypatch.setattr(relogin.na, "register_guest", boom)
    with pytest.raises(relogin.Transient):
        relogin.CcPool()


def test_process_file_error_when_renew_fails(tmp_path, monkeypatch):
    import account_file
    udid = account_file.new_udid()
    src = tmp_path / "acc" / "f.xml"
    src.parent.mkdir()
    _write_guest_xml(src, udid, "OLD")
    monkeypatch.setattr(relogin, "login", lambda *a, **k: (401, None, None))

    class Pool:
        def get(self): return "cc"
        def is_proven(self): return False   # force the renew path
        def renew(self, old): raise relogin.Transient("mint failed")
        def mark_proven(self): pass

    res = relogin.process_file(str(src), str(tmp_path / "acc"), Pool(), str(tmp_path / "bk"))
    assert res["status"] == "error"   # renew failure surfaced, not swallowed


def test_login_app_429_after_retries_is_transient(monkeypatch):
    monkeypatch.setattr(relogin.na, "_do",
                        lambda req: (400, {"errorCode": 429, "extras": {"current": 2, "previous": 1}}, []))
    monkeypatch.setattr(relogin.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(relogin.Transient):
        relogin.login("CC", "U", "OLD", "TH")


def test_login_network_error_is_transient_immediately(monkeypatch):
    sleeps = []
    monkeypatch.setattr(relogin.time, "sleep", lambda s: sleeps.append(s))

    def fake_do(req):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(relogin.na, "_do", fake_do)
    import pytest
    with pytest.raises(relogin.Transient):
        relogin.login("CC", "U", "OLD", "TH")
    assert sleeps == []                      # no second retry loop on top of na._do's own
