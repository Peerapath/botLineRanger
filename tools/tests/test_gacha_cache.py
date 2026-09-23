"""gacha: /gacha/info ถูกดึงสองครั้งต่อบัญชีทั้งที่เป็นข้อมูลชุดเดียวกัน"""
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
    def __init__(self):
        self.calls = []

    def __call__(self, cookie, uid, path, method="GET", body=None):
        self.calls.append(path.split("?")[0])
        return 200, {"result": {}}

    def count(self, path):
        return self.calls.count(path)


def test_a_cache_dict_stops_the_second_fetch(monkeypatch):
    gacha = load("gacha")
    api = FakeApi()
    monkeypatch.setattr(gacha, "call", api)
    cache = {}
    gacha.gacha_info("c", "u", cache=cache)
    gacha.gacha_info("c", "u", cache=cache)
    assert api.count("/v12.3/gacha/info") == 1


def test_without_a_cache_every_call_still_goes_out(monkeypatch):
    """ไม่ส่ง cache มาต้องได้พฤติกรรมเดิมเป๊ะ - CLI ที่รันครั้งเดียวไม่ควรเปลี่ยน"""
    gacha = load("gacha")
    api = FakeApi()
    monkeypatch.setattr(gacha, "call", api)
    gacha.gacha_info("c", "u")
    gacha.gacha_info("c", "u")
    assert api.count("/v12.3/gacha/info") == 2


def test_two_accounts_do_not_share_one_cache(monkeypatch):
    """cache เป็นของ session ห้ามเป็นตัวแปรระดับโมดูล ไม่งั้นบัญชี B ได้ตู้ของบัญชี A"""
    gacha = load("gacha")
    api = FakeApi()
    monkeypatch.setattr(gacha, "call", api)
    gacha.gacha_info("a", "1", cache={})
    gacha.gacha_info("b", "2", cache={})
    assert api.count("/v12.3/gacha/info") == 2
