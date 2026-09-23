"""flow Login: state ทุกตัวอยู่ใน session ไม่ใช่ใน global

บั๊กที่ชุดนี้กันไว้: บอทเดิมเก็บ LFACCACHE/GAMEID/FILENAME ไว้ระดับโมดูล สองบัญชีใน
โปรเซสเดียวกันจึงเขียนทับกัน - เป็นเหตุผลเดียวที่บอทต้องใช้ 128 โปรเซสและ 5.5 GB
"""
import os
import sys
import threading

import pytest

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


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """run_login now sleeps between retries of a transient failure (Finding 1). Every
    test in this file that drives a retry would otherwise pay that real wall-clock delay
    - a test that wants to prove the wait happens replaces flows.time.sleep again inside
    itself, which overrides this for the rest of that one test.
    """
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: None)


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


# --- extra coverage beyond the brief's own 8 tests, added while implementing this task ---
#
# Every test above replaces _relogin/_fetch_home/_claim_rewards/_gacha/_account_info with
# stubs, per the brief. That proves run_login's wiring but nothing about the real bodies of
# those functions, and nothing that would fail if AccountSession's fields were reverted to
# botLineRanger's old module globals (a stub writes onto whatever `s` it is handed, global
# or not - see the task's own warning about this). The tests below exercise the REAL
# _relogin (faked only at relogin.py's network boundary) and the real _account_info, and
# pin three behaviours the brief's sketch got wrong that the 8 tests above cannot see
# because they stub those exact functions away: a shared CcPool built fresh per call, a
# missing gachaDone-equivalent guard, and _account_info's own NameError on `cfg`.


def test_real_relogin_does_not_share_a_cached_token_across_threads(tmp_path, monkeypatch):
    """Exercises the real flows._relogin (not the stub every test above uses), faked only
    at relogin.py's network boundary. This is the exact bug class Task 7 exists to kill:
    getLFACHeadless's `global LFACCACHE; if LFACCACHE: return LFACCACHE` early-return,
    ported naively, would make the first thread through cache a token that every other
    thread's _relogin then hands back unchanged - no matter which account it was actually
    asked to log in. Every one of 32 concurrent, real _relogin calls must come back with
    ITS OWN account's rsn/cookie, derived from ITS OWN fake udid, not a shared one.
    """
    import relogin as relogin_mod

    def fake_read_account(path):
        ident = os.path.basename(path).split(".")[0]
        return {"udid": "udid-%s" % ident, "enc": "enc-%s" % ident,
                "nation": "TH", "language": "en", "text": "<map/>"}

    def fake_login(cc, udid, guest_cookie, nation, language):
        # the real server identifies the account from guest_cookie/udid, never from
        # which thread or cache asked - so the fake keys its answer the same way
        return 200, {"rsn": "rsn-" + udid, "level": 5}, "lfac-" + udid

    class FakePool:
        def __init__(self, **kw): pass
        def get(self): return "cc"
        def renew(self, cc): return "cc"
        def mark_proven(self): pass

    monkeypatch.setattr(relogin_mod, "read_account", fake_read_account)
    monkeypatch.setattr(flows, "decrypt_lfac", lambda udid, enc: "guest-" + udid)
    monkeypatch.setattr(relogin_mod, "login", fake_login)
    monkeypatch.setattr(relogin_mod, "atomic_write", lambda *a, **k: None)
    monkeypatch.setattr(relogin_mod, "replace_enc", lambda *a, **k: "")
    monkeypatch.setattr(relogin_mod, "CcPool", FakePool)

    n = 32
    sessions = [make(tmp_path, "%03d.xml" % i) for i in range(n)]
    ts = [threading.Thread(target=flows._relogin, args=(s,)) for s in sessions]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    for i, s in enumerate(sessions):
        ident = "%03d" % i
        assert s.rsn == "rsn-udid-" + ident
        assert s.cookie == "LF_AC=lfac-udid-" + ident
    assert len({s.cookie for s in sessions}) == n


def test_relogin_reuses_a_pool_attached_to_the_lane_instead_of_building_its_own(
        tmp_path, monkeypatch):
    """The fix for the brief's `pool = relogin.CcPool(share_file=...)` built fresh inside
    _relogin on every call (see task-7-report.md): with hundreds of accounts and no
    LGRGS_CC_FILE, that line mints a real, unlocked guest cc on every single call against
    a 2-per-IP-per-minute quota. A pool the caller already attached to s.lane must be
    reused instead - this proves _relogin prefers it and never constructs its own when
    one is present.
    """
    import relogin as relogin_mod

    used = []

    class FakeSharedPool:
        def get(self):
            used.append("get")
            return "shared-cc"
        def renew(self, cc):
            return "shared-cc"
        def mark_proven(self):
            used.append("proven")

    class LaneWithPool(Lane):
        def __init__(self):
            self.cc_pool = FakeSharedPool()

    def exploding_ccpool(*a, **kw):
        raise AssertionError("must not build its own CcPool when lane.cc_pool exists")

    monkeypatch.setattr(relogin_mod, "read_account", lambda path: {
        "udid": "u", "enc": "e", "nation": "TH", "language": "en", "text": "<map/>"})
    monkeypatch.setattr(flows, "decrypt_lfac", lambda udid, enc: "guest")
    monkeypatch.setattr(relogin_mod, "login", lambda cc, *a, **kw: (
        200, {"rsn": "R", "level": 1}, "lfac-" + cc))
    monkeypatch.setattr(relogin_mod, "atomic_write", lambda *a, **k: None)
    monkeypatch.setattr(relogin_mod, "replace_enc", lambda *a, **k: "")
    monkeypatch.setattr(relogin_mod, "CcPool", exploding_ccpool)

    s = make(tmp_path)
    s.lane = LaneWithPool()
    flows._relogin(s)

    assert used == ["get", "proven"]
    assert s.cookie == "LF_AC=lfac-shared-cc"


def test_relogin_falls_back_to_its_own_pool_when_the_lane_has_none(tmp_path, monkeypatch):
    """The brief's original per-call construction stays as a fallback (e.g. for calling
    _relogin standalone, before a caller wires lane.cc_pool up) - this pins that the
    fallback still runs and still works, not just that the lane-attached path does.
    """
    import relogin as relogin_mod

    built = []

    class FakePool:
        def __init__(self, **kw):
            built.append(kw)
        def get(self): return "own-cc"
        def renew(self, cc): return "own-cc"
        def mark_proven(self): pass

    monkeypatch.setattr(relogin_mod, "read_account", lambda path: {
        "udid": "u", "enc": "e", "nation": "TH", "language": "en", "text": "<map/>"})
    monkeypatch.setattr(flows, "decrypt_lfac", lambda udid, enc: "guest")
    monkeypatch.setattr(relogin_mod, "login", lambda cc, *a, **kw: (
        200, {"rsn": "R", "level": 1}, "lfac-" + cc))
    monkeypatch.setattr(relogin_mod, "atomic_write", lambda *a, **k: None)
    monkeypatch.setattr(relogin_mod, "replace_enc", lambda *a, **k: "")
    monkeypatch.setattr(relogin_mod, "CcPool", FakePool)

    s = make(tmp_path)          # plain Lane() - no cc_pool attribute
    flows._relogin(s)

    assert len(built) == 1
    assert s.cookie == "LF_AC=lfac-own-cc"


def test_gacha_is_not_redrawn_on_a_retry_after_it_already_succeeded(tmp_path, monkeypatch):
    """Original (startBotLogin_API_headless) guarded gacha with a gachaDone flag that
    spanned every retry attempt, at this exact comment: "กาชาหักตั๋วจริง ถ้าสุ่มไปแล้วแต่
    ขั้นหลังพัง (เช่น pull ไฟล์ไม่ได้) retry ห้ามสุ่มซ้ำ" (gacha really spends tickets; if
    it already drew but a later step broke, a retry must not draw again). The brief's
    sketch dropped that flag - without it, attempt 2 would redraw (and re-spend real
    tickets) whenever attempt 1 got past gacha but failed on a later, unrelated step.
    """
    calls = []
    stub(monkeypatch, calls)

    def gacha_once(s, cfg):
        calls.append("gacha")
        s.gacha_units, s.gacha_status = ["u1630e-sally"], "u1630e-sally"

    monkeypatch.setattr(flows, "_gacha", gacha_once)

    attempts_seen = []

    def flaky_info(s):
        attempts_seen.append(s.attempts)
        if s.attempts == 1:
            raise RuntimeError("transient: units endpoint timed out")

    monkeypatch.setattr(flows, "_account_info", flaky_info)
    out = flows.run("ranger_api_Login", make(tmp_path), dict(CFG, gacharanger=True))

    assert calls.count("gacha") == 1
    assert attempts_seen == [1, 2]
    assert out.status == "OK"


def test_a_session_that_draws_a_target_ranger_is_routed_to_backup(tmp_path, monkeypatch):
    """Original: gotTarget = any(RANGERSCONFIG.get(code.lower()) for code in gachaUnits)
    sent the file to backup/ instead of output/. Outcome.dest documents "backup" as a
    valid destination, but nothing produces it without this check - confirmed against
    task-8-brief.md and task-9-brief.md, neither of which ever returns dest="backup" either
    (only "output" and "login failed"), so Login is the only flow that can ever reach it.
    """
    calls = []
    stub(monkeypatch, calls)

    def gacha_found_target(s, cfg):
        calls.append("gacha")
        s.gacha_units = ["u1630e-sally", "u9999e-other"]
        s.gacha_status = "u1630e-sally,u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_found_target)
    cfg = dict(CFG, gacharanger=True, _rangers_config={"u1630e-sally": "Sally"})
    out = flows.run("ranger_api_Login", make(tmp_path), cfg)

    assert out.dest == "backup"
    assert out.status == "OK"


def test_a_session_with_no_matching_gacha_target_still_goes_to_output(tmp_path, monkeypatch):
    calls = []
    stub(monkeypatch, calls)

    def gacha_no_target(s, cfg):
        calls.append("gacha")
        s.gacha_units, s.gacha_status = ["u9999e-other"], "u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_no_target)
    cfg = dict(CFG, gacharanger=True, _rangers_config={"u1630e-sally": "Sally"})
    out = flows.run("ranger_api_Login", make(tmp_path), cfg)

    assert out.dest == "output"


def test_account_info_reads_the_ranger_target_config_without_crashing(tmp_path, monkeypatch):
    """_account_info is the one step every test above replaces outright via stub(); a bug
    in its real body (the brief's own sketch read an undefined name `cfg` - see
    _account_info's docstring in flows.py) would never surface anywhere else in this file,
    since _account_info is never called for real elsewhere. This runs the real function
    against fakes at its own network boundary and checks it both survives and reproduces
    the original getAccoutInfo's target-ranger-name lookup.
    """
    import gacha as gacha_mod
    import rangers_api as rangers_api_mod

    calls = []

    def fake_relogin(s):
        calls.append("relogin")
        s.cookie, s.rsn = "LF_AC=t", "ID1"

    def fake_fetch_home(s):
        # mirrors what the real _fetch_home derives from /home - level included, since
        # the real _account_info never touches s.level itself (only ruby/ticket/rangers)
        calls.append("home")
        s.home = {"player": {"rsn": "ID1", "level": 3}, "rubyBalance": {"total": 10}}
        s.level = 3

    monkeypatch.setattr(flows, "_relogin", fake_relogin)
    monkeypatch.setattr(flows, "_fetch_home", fake_fetch_home)
    monkeypatch.setattr(flows, "_claim_rewards", lambda s, cfg: calls.append("claim"))
    monkeypatch.setattr(flows, "_gacha", lambda s, cfg: calls.append("gacha"))
    monkeypatch.setattr(gacha_mod, "ticket_counts", lambda cookie, uid=None: (7, 0))
    monkeypatch.setattr(rangers_api_mod, "call", lambda cookie, path, **kw: (
        200, {"result": {"playerUnits": [{"unitCode": "u1630e-sally"}]}}))

    cfg = dict(CFG, _rangers_config={"u1630e-sally": "Sally"})
    out = flows.run("ranger_api_Login", make(tmp_path), cfg)

    assert out.status == "OK", out.error   # the brief's NameError would surface here as FAIL
    assert out.name == "Sally_Rb10_Tk7_ID1_Lv3"


# --- Fix round 1: retry loop tells "the server said no" apart from "it hiccuped" ---
#
# Before this round, run_login's single `except Exception` retried EVERY failure up to
# MAX_ATTEMPTS times with no wait at all - including a 401, which tools/relogin.py:91
# already documents as the server's real (non-transient) answer about an account. The
# tests below pin the two halves of that fix: a PermanentFailure (raised by the real
# _relogin on a confirmed 401 - see its own test further down) ends the account in one
# attempt, while an ordinary exception still retries but now waits in between.


def test_a_permanent_failure_is_attempted_exactly_once(tmp_path, monkeypatch):
    """Constraint 10: แยก "รอคิว" ออกจาก "พัง" - a 401 is "พัง" (see PermanentFailure's
    docstring), so a second and third attempt must never happen. Asserting the attempt
    count (not just dest) is the point: dest=="login failed" alone would stay green even
    if this quietly retried twice more first, which is exactly Finding 1's complaint.
    """
    stub(monkeypatch, [])
    attempts_seen = []

    def boom(s):
        attempts_seen.append(s.attempts)
        raise flows.PermanentFailure("relogin rejected (HTTP 401)")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)

    assert attempts_seen == [1]
    assert out.dest == "login failed"
    assert out.status == "FAIL"


def test_a_transient_failure_retries_with_backoff_between_attempts(tmp_path, monkeypatch):
    """An ordinary exception (network hiccup, server-side-busy - anything that is not a
    PermanentFailure) still gets the full MAX_ATTEMPTS, but Finding 1 also requires a wait
    in between so a batch of these doesn't hammer /login back to back. This replaces the
    file's own autouse no-op sleep with a spy so the wait can be observed without the test
    actually pausing.
    """
    sleeps = []
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: sleeps.append(seconds))
    stub(monkeypatch, [])
    attempts_seen = []

    def boom(s):
        attempts_seen.append(s.attempts)
        raise RuntimeError("network hiccup")

    monkeypatch.setattr(flows, "_relogin", boom)
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)

    assert attempts_seen == [1, 2, 3]
    assert out.dest == "login failed"
    # one gap after each attempt but the last - never a trailing wait before giving up
    assert sleeps == list(flows.RETRY_BACKOFF_SECONDS)


def test_a_transient_failure_that_recovers_on_retry_still_succeeds(tmp_path, monkeypatch):
    """The other half of Finding 1's fix: retrying a transient failure must still be able
    to reach a normal successful Outcome, not just eventually land in "login failed".
    """
    calls = []
    stub(monkeypatch, calls)
    attempts_seen = []

    def flaky(s):
        attempts_seen.append(s.attempts)
        if s.attempts == 1:
            raise RuntimeError("network hiccup")
        calls.append("relogin")
        s.cookie, s.rsn = "LF_AC=t-" + os.path.basename(s.src), "ID1"

    monkeypatch.setattr(flows, "_relogin", flaky)
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)

    assert attempts_seen == [1, 2]
    assert out.status == "OK"
    assert out.dest == "output"


def test_real_relogin_raises_permanent_failure_on_a_confirmed_401(tmp_path, monkeypatch):
    """Exercises the real flows._relogin (not a stub) end to end against a fake
    relogin.login that always answers 401 with no result - the same shape process_file()
    in tools/relogin.py treats as "rejected" after its own renew-and-retry. Proves the
    classification lives in _relogin itself, not just in a test double standing in for it.
    """
    import relogin as relogin_mod

    renewed = []

    class FakePool:
        def get(self): return "cc"
        def renew(self, cc):
            renewed.append(cc)
            return "cc-renewed"
        def mark_proven(self):
            raise AssertionError("a rejected account must never be marked proven")

    monkeypatch.setattr(relogin_mod, "read_account", lambda path: {
        "udid": "u", "enc": "e", "nation": "TH", "language": "en", "text": "<map/>"})
    monkeypatch.setattr(flows, "decrypt_lfac", lambda udid, enc: "guest")
    monkeypatch.setattr(relogin_mod, "login", lambda cc, *a, **kw: (401, None, None))

    s = make(tmp_path)
    s.lane.cc_pool = FakePool()
    with pytest.raises(flows.PermanentFailure):
        flows._relogin(s)

    assert renewed == ["cc"]   # did renew-and-retry once, per tools/relogin.py's own bar


def test_reset_token_clears_a_stale_error_before_the_next_attempt(tmp_path, monkeypatch):
    """Finding 2: s.error is set by _relogin on a non-fatal write-back OSError, but
    nothing used to clear it. reset_token() runs first in every attempt (including the
    first), so a note left by a failed attempt must be gone by the time a LATER attempt
    - which never touched that code path at all - reports its own Outcome.
    """
    calls = []
    stub(monkeypatch, calls)
    attempts_seen = []

    def flaky_relogin(s):
        attempts_seen.append(s.attempts)
        if s.attempts == 1:
            s.error = "token write failed: stale from attempt 1"
            raise RuntimeError("network hiccup")
        calls.append("relogin")
        s.cookie, s.rsn = "LF_AC=t-" + os.path.basename(s.src), "ID1"

    monkeypatch.setattr(flows, "_relogin", flaky_relogin)
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)

    assert attempts_seen == [1, 2]
    assert out.status == "OK"
    assert out.error == ""     # attempt 2 never set s.error; attempt 1's note is gone


def test_a_token_write_back_note_reaches_the_outcome_on_success(tmp_path, monkeypatch):
    """Finding 2, the option this round picked: s.error was write-only before this fix -
    _relogin set it on a failed token write-back but run_login tracked its own local
    `last` and never read it, so the note vanished even though the run still reports OK.
    Wiring it onto the successful Outcome (see run_login) is what makes it reachable.
    """
    calls = []
    stub(monkeypatch, calls)

    def relogin_with_write_back_note(s):
        calls.append("relogin")
        s.error = "token write failed: [Errno 13] Permission denied"
        s.cookie, s.rsn = "LF_AC=t-" + os.path.basename(s.src), "ID1"

    monkeypatch.setattr(flows, "_relogin", relogin_with_write_back_note)
    out = flows.run("ranger_api_Login", make(tmp_path), CFG)

    assert out.status == "OK"
    assert "token write failed" in out.error


# --- Review findings, round 1 (Finding 2): duplicate-account guard ---
#
# bot/input/ has 24,279 files and two of them can be the same underlying game account
# (observed: a0bfb087, two files, gacha'd twice - see _claimAccountThisRun's own docstring,
# botLineRanger.py:3255). Without a guard, both files claim rewards and draw gacha on the
# same account, spending a second real ticket for nothing. The original
# (startBotLogin_API_headless:8042, startBotLevel3_API_headless:8344) skips the reward/
# gacha steps for the second file and marks it dup-account, while still exporting it. None
# of the four flows had this - the reviewer found it missing from run_login too, even
# though run_login was already approved. AccountClaimRegistry below is the thread-pool
# replacement for the original's os.O_CREAT|O_EXCL marker file under src/split-ID/.


def test_account_claim_registry_lets_only_one_thread_through_for_the_same_id():
    """Must be safe for many threads - a thread pool has no separate processes/filesystem
    races to coordinate, just one Lock over one in-memory set. Many threads racing to claim
    the SAME id must let exactly one through.
    """
    registry = flows.AccountClaimRegistry()
    results = []
    lock = threading.Lock()

    def go():
        ok = registry.claim("SAME-ID")
        with lock:
            results.append(ok)

    ts = [threading.Thread(target=go) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert results.count(True) == 1
    assert results.count(False) == 31


def test_account_claim_registry_falsy_id_never_blocks():
    """Original (_claimAccountThisRun): "ระบุบัญชีไม่ได้ ก็ทำตามปกติ ดีกว่าข้ามไปเฉยๆ" -
    an account this run can't identify must never be blocked by this guard.
    """
    registry = flows.AccountClaimRegistry()
    assert registry.claim("") is True
    assert registry.claim("") is True     # still True the second time - never "claimed"
    registry.release("")                  # must not raise


def test_account_claim_registry_release_lets_the_id_be_claimed_again():
    registry = flows.AccountClaimRegistry()
    assert registry.claim("ID1") is True
    assert registry.claim("ID1") is False
    registry.release("ID1")
    assert registry.claim("ID1") is True


def test_login_gachas_normally_when_account_claims_is_absent_from_cfg(tmp_path, monkeypatch):
    """The guard must be a pure no-op when cfg has no _account_claims key - CLI use today,
    and every test above this one in this file, never set it. Their behaviour must stay
    exactly what it was before this fix: no dedup, _gacha always runs when configured.
    """
    calls = []
    stub(monkeypatch, calls)

    def gacha_once(s, cfg):
        calls.append("gacha")
        s.gacha_units, s.gacha_status = ["u9999e-other"], "u9999e-other"

    monkeypatch.setattr(flows, "_gacha", gacha_once)
    out = flows.run("ranger_api_Login", make(tmp_path), dict(CFG, gacharanger=True))
    assert "gacha" in calls
    assert out.status == "OK"


def test_login_two_threads_with_the_same_game_id_only_gacha_once(tmp_path, monkeypatch):
    """Two DIFFERENT files (different src, like two different input/ entries) that both
    turn out to be the SAME underlying account must gacha exactly once between them - by
    identity (which session actually drew), not just by count, since a bare count could
    pass by coincidence even if the wrong one drew.
    """
    barrier = threading.Barrier(2)

    def fake_relogin(s):
        barrier.wait(timeout=5)     # both threads reach the claim race together
        s.cookie = "LF_AC=t-" + os.path.basename(s.src)
        s.rsn = "SAME-ID"           # both files resolve to the same underlying account

    def fake_fetch_home(s):
        s.home = {"player": {"rsn": "SAME-ID", "level": 3}, "rubyBalance": {"total": 10}}
        s.level = 3

    drew = []
    drew_lock = threading.Lock()

    def fake_gacha(s, cfg):
        with drew_lock:
            drew.append(s)
        s.gacha_units, s.gacha_status = ["u9999e-other"], "u9999e-other"

    monkeypatch.setattr(flows, "_relogin", fake_relogin)
    monkeypatch.setattr(flows, "_fetch_home", fake_fetch_home)
    monkeypatch.setattr(flows, "_claim_rewards", lambda s, cfg: None)
    monkeypatch.setattr(flows, "_gacha", fake_gacha)
    monkeypatch.setattr(flows, "_account_info", lambda s: None)

    registry = flows.AccountClaimRegistry()
    cfg = dict(CFG, gacharanger=True, _account_claims=registry)
    a, b = make(tmp_path, "a.xml"), make(tmp_path, "b.xml")
    outcomes = {}

    def run_one(name, s):
        outcomes[name] = flows.run("ranger_api_Login", s, cfg)

    ts = [threading.Thread(target=run_one, args=("a", a)),
          threading.Thread(target=run_one, args=("b", b))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(drew) == 1                     # exactly one of the two sessions drew
    assert outcomes["a"].status == "OK"        # both still exported...
    assert outcomes["b"].status == "OK"
    assert {outcomes["a"].dest, outcomes["b"].dest} <= {"output", "backup"}
    # ...and the loser is marked so nothing downstream mistakes it for "not yet handled"
    assert {a.gacha_status, b.gacha_status} == {"u9999e-other", "dup-account"}


def test_login_releases_the_claim_when_it_never_reaches_gacha(tmp_path, monkeypatch):
    """Original: "จองบัญชีไว้แต่สุ่มไม่สำเร็จ ปล่อยให้ไฟล์ซ้ำของบัญชีนี้ (ถ้ามี) ได้สุ่มแทน" - a
    session that claims an id but never gets past _claim_rewards (every attempt fails
    first) must give the claim back for a genuine duplicate file to use instead.
    """
    stub(monkeypatch, [])

    def always_fails(s, cfg):
        raise RuntimeError("units endpoint down")

    monkeypatch.setattr(flows, "_claim_rewards", always_fails)
    registry = flows.AccountClaimRegistry()
    out = flows.run("ranger_api_Login", make(tmp_path), dict(CFG, _account_claims=registry))

    assert out.dest == "login failed"
    assert registry.claim("ID1") is True    # released -> claimable again
