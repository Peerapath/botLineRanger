import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import newbie_quest as nq


class FakeQuestServer:
    """จำลอง /dailyquest chain: quest แต่ละตัวมี type + condition; action ที่ถูกต้องขยับ currentQuest ทีละ 1."""

    def __init__(self, chain):
        # chain = list of (missionType, completionCount)
        self.contents = [{"index": i, "missionType": t, "missionCondition": c,
                          "currentCount": 0, "completionCount": c,
                          "currentQuest": i == 0, "availableProgress": i == 0,
                          "missionComplete": False, "receiveReward": False,
                          "missionRewards": []}
                         for i, (t, c) in enumerate(chain)]
        self.log = []

    def _cur(self):
        for m in self.contents:
            if m["currentQuest"]:
                return m
        return None

    def bump(self):
        """เลียนแบบ 'ทำ action ถูก 1 ครั้ง' -> currentCount ของ current +1"""
        m = self._cur()
        if not m:
            return
        m["currentCount"] = min(m["completionCount"], m["currentCount"] + 1)
        if m["currentCount"] >= m["completionCount"]:
            m["missionComplete"] = True

    def __call__(self, cookie, path, method="GET", body=None, api=None):
        self.log.append((method, path.split("?")[0]))
        if path == "/dailyquest":
            return 200, {"result": {"playerDailyQuest": {"questNo": 1, "questType": "NEWBI",
                                                         "contents": self.contents}}}
        if path.startswith("/dailyquest/receive/reward/NEWBI/"):
            idx = int(path.rsplit("/", 1)[1])
            m = self.contents[idx]
            if not m["missionComplete"]:
                return 400, {"errorCode": 119509}
            m["receiveReward"] = True
            m["currentQuest"] = False
            if idx + 1 < len(self.contents):
                self.contents[idx + 1]["currentQuest"] = True
                self.contents[idx + 1]["availableProgress"] = True
            return 200, {"result": {}}
        if path.startswith("/dailyquest/receive/special/reward/"):
            return 200, {"result": {}}
        raise AssertionError("unexpected path %s" % path)


def _patch(monkeypatch, server, actions=None):
    monkeypatch.setattr(nq, "call", server)
    # every forge action just bumps the mock's current-quest counter and reports success
    def make(name):
        def f(cookie, *a, **k):
            server.bump()
            return True, name
        return f
    for fn in ("forge_stage", "forge_reinforce", "forge_fort_upgrade", "forge_gear_equip"):
        monkeypatch.setattr(nq, fn, make(fn))


def test_walks_and_claims_a_forgeable_chain(monkeypatch):
    server = FakeQuestServer([("stage_main", 3), ("unit_reinforce", 1),
                              ("fort_upgrade_times", 1), ("treasure", 1)])
    _patch(monkeypatch, server)
    outcome, done = nq.walk("LF_AC=x", confirm=True, progress=lambda m: None)
    assert outcome == "done"
    assert done == [0, 1, 2, 3]
    assert all(m["receiveReward"] for m in server.contents)


def test_stops_at_unsupported_type(monkeypatch):
    server = FakeQuestServer([("stage_main", 1), ("guild_help", 1), ("stage_main", 1)])
    _patch(monkeypatch, server)
    outcome, done = nq.walk("LF_AC=x", confirm=True, progress=lambda m: None)
    assert outcome == "blocked:guild_help"
    assert done == [0]
    assert server.contents[0]["receiveReward"] and not server.contents[1]["receiveReward"]


def test_claims_an_already_complete_bonus_quest(monkeypatch):
    server = FakeQuestServer([("bonus_quest", 5), ("stage_main", 1)])
    server.contents[0]["currentCount"] = 5
    server.contents[0]["missionComplete"] = True     # milestone already satisfied by prior progress
    _patch(monkeypatch, server)
    outcome, done = nq.walk("LF_AC=x", confirm=True, progress=lambda m: None)
    assert outcome == "done"
    assert done == [0, 1]


def test_bonus_quest_not_yet_complete_blocks(monkeypatch):
    # a milestone that hasn't been reached has no forge action -> stop
    server = FakeQuestServer([("bonus_quest", 11), ("stage_main", 1)])
    _patch(monkeypatch, server)
    outcome, done = nq.walk("LF_AC=x", confirm=True, progress=lambda m: None)
    assert outcome == "blocked:bonus_quest"
    assert done == []


def test_dry_run_stops_before_acting(monkeypatch):
    server = FakeQuestServer([("stage_main", 1)])
    _patch(monkeypatch, server)
    outcome, done = nq.walk("LF_AC=x", confirm=False, progress=lambda m: None)
    assert outcome == "dryrun"
    assert done == []
    assert not server.contents[0]["receiveReward"]


def test_reinforce_material_excludes_team_and_locked(monkeypatch):
    units = [
        {"invenId": 1, "unitCode": "brown", "unitLevel": 20, "lockYn": False},   # keeper (highest)
        {"invenId": 2, "unitCode": "brown", "unitLevel": 1, "lockYn": False},    # feedable dup
        {"invenId": 3, "unitCode": "moon", "unitLevel": 1, "lockYn": False},     # on team -> excluded
        {"invenId": 4, "unitCode": "moon", "unitLevel": 1, "lockYn": True},      # locked -> excluded
        {"invenId": 5, "unitCode": "cony", "unitLevel": 1, "lockYn": False},     # only copy -> excluded
    ]

    def server(cookie, path, method="GET", body=None, api=None):
        if path.startswith("/player/units/equip"):
            return 200, {"result": {"playerUnits": units}}
        if path == "/home":
            return 200, {"result": {"playerUnitTeams": {"team1": [{"invenId": 3}]}}}
        raise AssertionError(path)
    monkeypatch.setattr(nq, "call", server)
    all_units, spares = nq._spare_units("LF_AC=x")
    ids = {u["invenId"] for u in spares}
    assert ids == {2}       # only the unlocked, non-team, non-best duplicate


def test_stalls_when_forge_cannot_advance(monkeypatch):
    # a treasure quest whose area was pre-cleared: forge_stage "succeeds" but the count never moves
    server = FakeQuestServer([("treasure", 1), ("stage_main", 1)])
    monkeypatch.setattr(nq, "call", server)
    monkeypatch.setattr(nq, "forge_stage", lambda cookie, *a, **k: (True, "cleared (no progress)"))  # never bumps
    outcome, done = nq.walk("LF_AC=x", confirm=True, max_stall=3, progress=lambda m: None)
    assert outcome == "stalled:treasure"
    assert done == []
