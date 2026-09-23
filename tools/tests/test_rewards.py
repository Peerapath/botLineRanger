"""rewards: เลิกถามซ้ำสิ่งที่รู้คำตอบแล้ว โดยไม่เก็บของได้น้อยลง

บั๊กที่ชุดนี้กันไว้: การ "ประหยัด request" ที่ทำให้ของที่เคยเก็บได้หายไปเงียบ ๆ
เทสต์จึงตรวจสองอย่างคู่กันเสมอ - จำนวน request *และ* รายการที่เก็บได้
"""
import importlib.util
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
    """

    def __init__(self, gifts=1):
        self.calls = []
        self.gifts = gifts

    def __call__(self, cookie, path, method="GET", body=None, api=None):
        self.calls.append((method, path.split("?")[0]))
        if path.startswith("/giftbox/list"):
            pending = [{"giftSn": i, "giftName": "g%d" % i, "giftCount": 1, "receive": False}
                       for i in range(self.gifts)]
            return 200, {"result": {"giftBox": {"gift": {"playerGifts": pending}}}}
        if path.startswith("/giftbox/gift/receive/all"):
            self.gifts = 0
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


def test_an_account_with_nothing_to_claim_costs_no_more_than_thirteen_calls(monkeypatch):
    rewards = load("rewards")
    api = FakeApi(gifts=0)
    monkeypatch.setattr(rewards, "call", api)
    rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert len(api.calls) <= 11, api.calls


def test_the_gifts_are_still_all_claimed(monkeypatch):
    """ตัวเลขที่ลดลงต้องไม่แลกมาด้วยของที่เก็บไม่ครบ"""
    rewards = load("rewards")
    api = FakeApi(gifts=3)
    monkeypatch.setattr(rewards, "call", api)
    total = rewards.claim_all("c", confirm=True, passes=2, home={"player": {}, "rubyBalance": {}})
    assert total >= 1
    assert api.gifts == 0
