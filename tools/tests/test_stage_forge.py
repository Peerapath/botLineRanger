import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad

import stage_forge as sf

# ของจริงจาก battle_tempsave ของบัญชี rsn 40cf0a20 (st02, battleSn 1574978824) ที่เกมเขียนเอง
CAPTURED_ICU = "zUvGsOcGv57SfynB7DsigZBsvDpUYq9ewxwyHSBLjcL0OPvTLvSbMzUHqvaZl2UC"
CAPTURED_RSN = "40cf0a20"
CAPTURED_SN = 1574978824

KEY = RSA.generate(1024, e=65537)


def _decrypt_rsa(field):
    size = (KEY.n.bit_length() + 7) // 8
    return pow(int.from_bytes(base64.b64decode(field), "big"), KEY.d, KEY.n).to_bytes(size, "big")


def _decrypt_icu(icu, rsn, battle_sn):
    raw = base64.b64decode(icu)
    key = sf.HM16(sf.HM16(rsn) + sf.HM16(str(battle_sn))).encode()
    return unpad(AES.new(key, AES.MODE_CBC, raw[:16]).decrypt(raw[16:]), 16)


def _enter(tower=2000, battle_sn=1234567890):
    return {"battleSn": battle_sn, "enemyTowerHp": tower,
            "rsaKeyBase": {"modulus": str(KEY.n), "exponent": str(KEY.e)}}


def test_hm16_is_upper_md5_prefix():
    assert sf.HM16("abc") == "900150983CD24FB0"


def test_icu_key_derivation_opens_the_games_own_icu():
    # คีย์ที่ derive ได้ต้องถอด icu ที่เกมสร้างเองออก: padding ถูก + ได้ HM16 (hex ตัวใหญ่ 16 ตัว)
    plain = _decrypt_icu(CAPTURED_ICU, CAPTURED_RSN, CAPTURED_SN)
    assert len(plain) == 16
    assert all(c in b"0123456789ABCDEF" for c in plain)


def test_rsa_nopad_right_pads_with_spaces():
    block = _decrypt_rsa(sf.rsa_nopad("true", KEY.n, KEY.e))
    assert block == b"true" + b" " * (len(block) - 4)


def test_rsa_nopad_is_deterministic():
    assert sf.rsa_nopad("42", KEY.n, KEY.e) == sf.rsa_nopad("42", KEY.n, KEY.e)


def test_build_save_body_fields():
    enter = _enter(tower=3000, battle_sn=987654321)
    raw = sf.build_save_body(enter, "st07", "40d2cf61", pt=1)
    body = json.loads(raw)
    assert list(body) == sorted(body)
    assert b": " not in raw and b", " not in raw
    assert body["stc"] == "st07" and body["pt"] == 1
    assert int(body["atw"]) > 3000
    assert "i_e" not in body
    assert _decrypt_rsa(body["sn_e"]).rstrip(b" ") == b"987654321"
    assert _decrypt_rsa(body["win_e"]).rstrip(b" ") == b"true"
    assert _decrypt_icu(body["icu"], "40d2cf61", 987654321) == sf.HM16(str(KEY.n)).encode()
    for key in ("bm", "bt", "e", "enemies", "tt"):
        assert body[key] == sf.TEMPLATE[key]


def test_atw_always_beats_a_huge_tower():
    body = json.loads(sf.build_save_body(_enter(tower=5_000_000), "st150", "x"))
    assert int(body["atw"]) > 5_000_000


def test_template_is_not_mutated():
    before = json.dumps(sf.TEMPLATE, sort_keys=True)
    sf.build_save_body(_enter(), "st01", "x")
    assert json.dumps(sf.TEMPLATE, sort_keys=True) == before


def test_stage_codes():
    assert sf.stage_code(1) == "st01"
    assert sf.stage_code(150) == "st150"
    assert sf.stage_number("st09") == 9
    assert sf.stage_number("st150") == 150


# ---- control flow กับเซิร์ฟเวอร์ปลอม (ไม่ยิงเน็ตจริง) ----------------------------------------------

class FakeServer:
    """จำลอง enter/save/cancel/player: ผลของ save แต่ละครั้งสั่งผ่าน `saves` (ค่า หรือ callable)"""

    def __init__(self, cleared_upto=0, saves=None, hearts=5, enter_error=None):
        self.cleared_upto = cleared_upto
        self.saves = list(saves or [])
        self.hearts = hearts                 # int หรือ list ที่ pop ทีละ enter
        self.enter_error = enter_error       # (status, errorCode) บังคับให้ enter พัง
        self.log = []
        self.next_sn = 1000
        self.frontier = max(1, cleared_upto)   # stage ที่ enter ไกลสุด (lastStageCode ของจริงขยับตอน enter)

    def _hearts_now(self):
        if isinstance(self.hearts, list):
            return self.hearts.pop(0) if len(self.hearts) > 1 else self.hearts[0]
        return self.hearts

    def _player(self, hearts):
        return {"rsn": "40d2cf61", "level": 1, "lastStageCode": "st01",
                "hearts": {"total": hearts}, "nextHeartMills": 60000}

    def __call__(self, cookie, path, method="GET", body=None, api=None):
        bare = path.split("?")[0]
        self.log.append((method, bare))
        if bare.startswith("/player/units/equip"):
            return 200, {"result": {"player": self._player(self._hearts_now())}}
        if bare.startswith("/stage/cancel/"):
            return 200, {"result": {}}
        if bare == "/stage/last":
            return 200, {"result": {"lastStage": {"stageCode": sf.stage_code(self.frontier),
                                                  "complete": self.frontier <= self.cleared_upto}}}
        if bare.startswith("/stage/enter/") or bare.startswith("/tutorial/stage/enter/"):
            if self.enter_error:
                status, code = self.enter_error
                return status, {"errorCode": code}
            number = int(bare.split("/")[-1][2:])
            if number > self.cleared_upto + 1:
                return 400, {"errorCode": 102201}
            hearts = self._hearts_now()
            self.frontier = max(self.frontier, number)
            self.next_sn += 1
            return 200, {"result": {"battleSn": self.next_sn, "enemyTowerHp": 1000,
                                    "isEnterable": hearts > 0, "player": self._player(hearts),
                                    "rsaKeyBase": {"modulus": str(KEY.n), "exponent": str(KEY.e)}}}
        if bare.startswith("/stage/save/"):
            number = int(bare.split("/")[-1][2:])
            outcome = self.saves.pop(0) if self.saves else "win"
            if callable(outcome):
                return outcome()
            if outcome == "win":
                self.cleared_upto = max(self.cleared_upto, number)
                return 200, {"result": {"battleResult": {
                    "isCleared": True, "rewardExp": 1,
                    "afterRewardPlayer": {"level": 2, "hearts": {"total": 5}}}}}
            if outcome == "loss":
                return 200, {"result": {"battleResult": {"rewardExp": 0}}}
            return 400, {"errorCode": outcome}
        raise AssertionError("unexpected call %s %s" % (method, path))

    def calls(self, prefix):
        return [p for m, p in self.log if p.startswith(prefix)]


def _run(monkeypatch, server, first, last, retries=2, max_heart_wait=600, delay=0):
    sleeps = []
    monkeypatch.setattr(sf, "call", server)
    monkeypatch.setattr(sf.time, "sleep", sleeps.append)
    monkeypatch.setattr(sf.random, "uniform", lambda a, b: 0)
    result = sf.clear_range("LF_AC=x", "40d2cf61", first, last, retries=retries,
                            max_heart_wait=max_heart_wait, delay=delay, progress=lambda m: None)
    server.sleeps = sleeps
    return result


def test_clear_range_clears_in_order(monkeypatch):
    server = FakeServer()
    assert _run(monkeypatch, server, 1, 5) == (5, "done")
    assert len(server.calls("/stage/save/")) == 5


def test_delay_is_paused_between_stages_not_before_the_first(monkeypatch):
    server = FakeServer()
    assert _run(monkeypatch, server, 1, 4, delay=3) == (4, "done")
    assert server.sleeps.count(3) == 3          # 4 ด่าน = คั่น 3 ครั้ง ไม่หน่วงก่อนด่านแรก


def test_clear_range_stops_on_locked_stage(monkeypatch):
    server = FakeServer(cleared_upto=2)          # st03 เปิดอยู่ st05 ยังล็อก
    assert _run(monkeypatch, server, 5, 10) == (4, "locked")
    assert server.calls("/stage/save/") == []
    assert server.calls("/tutorial/") == []      # ด่านล็อกไม่ต้องลองเส้น tutorial


def test_clear_range_never_reforges_after_cheat_verdict(monkeypatch):
    server = FakeServer(saves=[102204])
    assert _run(monkeypatch, server, 1, 5) == (0, "flagged")
    assert len(server.calls("/stage/save/")) == 1


def test_cheat_verdict_on_enter_skips_tutorial_route(monkeypatch):
    server = FakeServer(enter_error=(400, 102204))
    assert _run(monkeypatch, server, 1, 5) == (0, "flagged")
    assert server.calls("/tutorial/") == []


def test_rejected_token_stops_as_auth(monkeypatch):
    server = FakeServer(enter_error=(401, 401))
    assert _run(monkeypatch, server, 1, 5) == (0, "auth")


def test_clear_range_stops_after_second_plain_loss(monkeypatch):
    server = FakeServer(saves=["loss", "loss", "win"])
    assert _run(monkeypatch, server, 1, 3) == (0, "failed")
    assert len(server.calls("/stage/save/")) == 2


def test_one_plain_loss_is_retried(monkeypatch):
    server = FakeServer(saves=["loss", "win"])
    assert _run(monkeypatch, server, 1, 1) == (1, "done")


def test_bad_battle_reject_reposts_same_battle(monkeypatch):
    server = FakeServer(saves=[102205, "win"])
    assert _run(monkeypatch, server, 1, 1) == (1, "done")
    saves = server.calls("/stage/save/")
    assert len(saves) == 2 and saves[0] == saves[1]          # battleSn เดิม ไม่ enter ใหม่
    assert len(server.calls("/stage/enter/")) == 1


def test_network_error_is_retried(monkeypatch):
    def boom():
        raise TimeoutError("blip")
    server = FakeServer(saves=[boom, "win"])
    assert _run(monkeypatch, server, 1, 1) == (1, "done")


def test_network_error_after_credit_is_not_replayed(monkeypatch):
    server = FakeServer()

    def credited_then_boom():
        server.cleared_upto = 1                # เซิร์ฟเวอร์รับไปแล้ว แต่ฝั่งเราเน็ตหลุด
        raise TimeoutError("lost response")
    server.saves = [credited_then_boom]
    assert _run(monkeypatch, server, 1, 1) == (1, "done")
    assert len(server.calls("/stage/save/")) == 1            # เช็ค /stage/last แล้วไม่เล่นซ้ำ


def test_out_of_hearts_waits_for_regen_then_clears(monkeypatch):
    server = FakeServer(hearts=[0, 1])
    assert _run(monkeypatch, server, 1, 1) == (1, "done")
    assert len(server.calls("/stage/save/")) == 1            # ไม่ save ตอน heart หมด
    assert len(server.calls("/stage/cancel/")) == 1
    assert server.sleeps and server.sleeps[0] >= 60          # รอ nextHeartMills (60s) + เผื่อ


def test_out_of_hearts_stops_when_regen_is_too_far(monkeypatch):
    server = FakeServer(hearts=0)
    assert _run(monkeypatch, server, 1, 3, max_heart_wait=30) == (0, "hearts")
    assert server.calls("/stage/save/") == []


def _start(monkeypatch, server, player=None):
    monkeypatch.setattr(sf, "call", server)
    return sf.start_stage("LF_AC=x", player or {"lastStageCode": sf.stage_code(server.frontier)})


def test_start_stage_fresh_account(monkeypatch):
    assert _start(monkeypatch, FakeServer(cleared_upto=0)) == 1


def test_start_stage_after_st01(monkeypatch):
    assert _start(monkeypatch, FakeServer(cleared_upto=1)) == 2


def test_start_stage_entered_but_not_cleared_frontier(monkeypatch):
    # บั๊กจริงที่เจอ: enter st152 (ไม่ได้ save) แล้ว lastStageCode กลายเป็น st152 -> ต้องเริ่มที่ 152 ไม่ใช่ 153
    server = FakeServer(cleared_upto=151)
    server.frontier = 152
    assert _start(monkeypatch, server) == 152


def test_start_stage_progressed_account_only_reads(monkeypatch):
    server = FakeServer(cleared_upto=40)
    assert _start(monkeypatch, server) == 41
    assert [p for m, p in server.log] == ["/stage/last"]      # ไม่ enter เพื่อ probe


def test_start_stage_falls_back_to_player_when_stage_last_fails(monkeypatch):
    monkeypatch.setattr(sf, "call", lambda *a, **k: (503, "busy"))
    assert sf.start_stage("LF_AC=x", {"lastStageCode": "st40"}) == 40   # เล่นซ้ำได้ ดีกว่าข้าม


def test_heart_wait_from_heart_ended(monkeypatch):
    monkeypatch.setattr(sf.time, "time", lambda: 1000.0)
    # เต็ม 5 ดวงอีก 5*420s -> ดวงแรกมาใน 420s
    player = {"heartEnded": 1000_000 + 5 * 420_000, "maxHeart": 5, "heartDuration": 420_000}
    assert abs(sf.heart_wait(player) - 420) < 1e-6


APP429 = {"errorCode": 429, "extras": {"current": 20, "previous": 10}}


def test_enter_app_429_is_transient_not_tutorial_fallback(monkeypatch):
    calls = []

    def fake_call(cookie, path, method="GET", body=None, api=None):
        calls.append(path)
        return 400, APP429
    monkeypatch.setattr(sf, "call", fake_call)
    status, result, error = sf.enter("LF_AC=t", "st05")
    assert (status, error) == (400, 429)
    assert calls == ["/stage/enter/st05"]          # no /tutorial/stage/enter fallback


def test_clear_stage_reposts_same_battlesn_after_app_429(monkeypatch):
    posted = []
    enter_result = dict(_enter(), player={"hearts": {"total": 5}}, isEnterable=True)
    script = [(400, APP429), (200, {"result": {"battleResult": {"isCleared": True, "rewardExp": 10,
                                                                   "afterRewardPlayer": {"level": 2}}}})]

    def fake_call(cookie, path, method="GET", body=None, api=None):
        if path.startswith("/stage/enter/"):
            return 200, {"result": enter_result}
        posted.append(path)
        return script.pop(0)
    monkeypatch.setattr(sf, "call", fake_call)
    monkeypatch.setattr(sf.time, "sleep", lambda s: None)
    cleared, info = sf.clear_stage("LF_AC=t", "st02", "40cf0a20", pt=1)
    assert cleared and info["step"] == "save" and len(posted) == 2
    assert posted[0].split("?")[0] == posted[1].split("?")[0]   # same /stage/save/<battleSn>/st02
