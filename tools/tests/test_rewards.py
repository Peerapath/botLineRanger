"""rewards: เลิกถามซ้ำสิ่งที่รู้คำตอบแล้ว โดยไม่เก็บของได้น้อยลง

บั๊กที่ชุดนี้กันไว้: การ "ประหยัด request" ที่ทำให้ของที่เคยเก็บได้หายไปเงียบ ๆ
เทสต์จึงตรวจสองอย่างคู่กันเสมอ - จำนวน request *และ* รายการที่เก็บได้
"""
import importlib.util
import inspect
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

    Gifts carry a kind. receive/all only sweeps NORMAL ones; MINI_GACHA ones stay in
    the box for the per-gift receive/<giftSn> mop-up loop to collect - this mirrors
    what the real endpoint does (see claim_giftbox) and is what makes that loop
    something a fake can actually exercise, instead of it always finding an empty box.
    `fail_sns` makes one specific individual claim fail, for testing that a stuck
    leftover is not hidden behind an earlier success.
    """

    def __init__(self, gifts=1, mini_gacha_sns=(), fail_sns=()):
        self.calls = []
        self.fail_sns = set(fail_sns)
        mini_gacha_sns = set(mini_gacha_sns)
        self.gift_state = {i: ("MINI_GACHA" if i in mini_gacha_sns else "NORMAL")
                            for i in range(gifts)}
        self.claimed_individually = []

    @property
    def gifts(self):
        return len(self.gift_state)

    def __call__(self, cookie, path, method="GET", body=None, api=None):
        self.calls.append((method, path.split("?")[0]))
        if path.startswith("/giftbox/list"):
            pending = [{"giftSn": sn, "giftName": "g%d" % sn, "giftCount": 1, "receive": False}
                       for sn in sorted(self.gift_state)]
            return 200, {"result": {"giftBox": {"gift": {"playerGifts": pending}}}}
        if path.startswith("/giftbox/gift/receive/all"):
            # only NORMAL gifts get swept in bulk - MINI_GACHA ones are left for the
            # per-gift endpoint below, same as the real API (see claim_giftbox)
            self.gift_state = {sn: kind for sn, kind in self.gift_state.items()
                                if kind == "MINI_GACHA"}
            return 200, {"result": {}}
        if path.startswith("/giftbox/gift/receive/"):
            sn = int(path.rsplit("/", 1)[-1])
            if sn in self.fail_sns:
                return 400, {"result": {}}
            if sn in self.gift_state:
                del self.gift_state[sn]
                self.claimed_individually.append(sn)
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


def test_claim_all_defaults_to_three_passes():
    """This default silently dropped from 3 to 2 once already (finding 1) - pin it so
    a future change has to do that on purpose."""
    rewards = load("rewards")
    assert inspect.signature(rewards.claim_all).parameters["passes"].default == 3


def test_an_account_with_nothing_to_claim_costs_exactly_six_calls(monkeypatch):
    """Pass 1 surveys 6 sources (attendance reuses the handed-in home, no call of its
    own) and finds nothing, so it stops before pass 2 ever runs - this number does not
    move with `passes`."""
    rewards = load("rewards")
    api = FakeApi(gifts=0)
    monkeypatch.setattr(rewards, "call", api)
    rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert len(api.calls) == 6, api.calls


def test_the_gifts_are_still_all_claimed(monkeypatch):
    """ตัวเลขที่ลดลงต้องไม่แลกมาด้วยของที่เก็บไม่ครบ"""
    rewards = load("rewards")
    # sn 0 and 1 are MINI_GACHA: receive/all must skip them, so only the per-gift
    # mop-up loop in claim_giftbox can still collect them.
    api = FakeApi(gifts=3, mini_gacha_sns={0, 1})
    monkeypatch.setattr(rewards, "call", api)
    total = rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert total >= 1
    assert api.gifts == 0
    # Identity, not just a count reaching zero: proves the mop-up loop, not a
    # coincidence in the fake, is what collected these two.
    assert api.claimed_individually == [0, 1]


def test_claim_giftbox_reports_failure_when_a_leftover_post_fails(monkeypatch):
    """done used to be an OR chain, so one rejected leftover could still read as ok."""
    rewards = load("rewards")
    api = FakeApi(gifts=2, mini_gacha_sns={0, 1}, fail_sns={1})
    monkeypatch.setattr(rewards, "call", api)
    pending = [{"giftSn": 0}, {"giftSn": 1}]
    assert rewards.claim_giftbox("c", pending) is False
