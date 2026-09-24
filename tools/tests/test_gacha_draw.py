"""gacha.draw_with_ticket: pins the ticket-spending behaviour moved from
botLineRanger.apiGachaWithTicket() (see task-6-report.md for the verbatim-move diff).

These are NOT in the task-6 brief's own checklist (it only wrote a test for gacha_info's
cache). The task instructions require moved code to be pinned by tests too, not just proven
importable, so this file and test_pull_roster_unit_names.py cover that gap.

Never calls the real game server - every test drives draw_with_ticket through FakeGachaApi,
monkeypatched in place of gacha.call. FakeGachaApi does no caching or state-hiding of its
own (every hit is counted, every /confirm actually decrements the fake's ticket count), so a
test that expects N calls or a spent ticket is only green if draw_with_ticket really did that,
not because the fake quietly supplied the answer already.
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeGachaApi:
    """A fake /gacha + /home + /player/item server, just accurate enough to drive one banner.

    reserve_fails makes the reserve step return a non-200 (cmd_roll turns that into a
    SystemExit) so a test can prove draw_with_ticket's except clause actually catches it -
    a real transient-vs-permanent distinction, not just "does it run".
    """

    def __init__(self, ruby=1000, tickets=10, ticket_price=5, ruby_price=50,
                 group_id="grp_gacha_1", granted_codes=(), reserve_fails=False,
                 machine_open=True):
        self.calls = []
        self.reserve_bodies = []
        self.ruby = ruby
        self.tickets = tickets
        self.ticket_price = ticket_price
        self.ruby_price = ruby_price
        self.group_id = group_id
        self.granted_codes = list(granted_codes)
        self.reserve_fails = reserve_fails
        self.machine_open = machine_open
        self._reserve_seq = 0

    def __call__(self, cookie, uid, path, method="GET", body=None):
        bare = path.split("?")[0]
        self.calls.append(bare)

        if bare == "/gacha/info":
            # pick_ticket_group filters on real time.time(), so the fixture's exposure
            # window has to bracket it too, not a baked-in timestamp that ages out.
            now_ms = int(time.time() * 1000)
            group = {
                "gachaGroup": {
                    "groupId": self.group_id,
                    "gachaName": "Test Banner",
                    "gachaResultType": "UNIT",
                    "exposureStartDate": now_ms - 1000,
                    "exposureEndDate": now_ms + 1000,
                    "gachaGroupInfos": [
                        {"gachaIndex": 1, "displayTicketPrice": self.ticket_price,
                         "displayRubyPrice": self.ruby_price},
                    ],
                }
            }
            return 200, {"result": {"gachaGroupResponseList": [group] if self.machine_open else []}}

        if bare == "/player/item":
            return 200, {"result": {
                "premiumGachaTicketItems": [{"amount": self.tickets}],
                "eventGachaTicketItems": [],
            }}

        if bare == "/home":
            return 200, {"result": {"rubyBalance": {"total": self.ruby}}}

        if bare == "/gacha/group/reserve":
            self.reserve_bodies.append(body)
            if self.reserve_fails:
                return 400, {"result": {}}
            self._reserve_seq += 1
            return 200, {"result": {"reserveSeq": self._reserve_seq}}

        if bare == "/gacha/group/confirm":
            use_ticket = body.get("useTicket")
            if use_ticket:
                self.tickets -= self.ticket_price
            else:
                self.ruby -= self.ruby_price
            code = self.granted_codes.pop(0) if self.granted_codes else "u9-nobody"
            return 200, {"result": {"gachaResults": [
                {"usedTickets": self.ticket_price if use_ticket else 0,
                 "usedRuby": {"total": self.ruby_price} if not use_ticket else {},
                 "rewards": [{"rewardUnit": {"unitCode": code}}]},
            ]}}

        return 200, {"result": {}}

    def count(self, bare_path):
        return self.calls.count(bare_path)


def test_pays_with_ticket_before_ruby_when_both_are_affordable(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(ruby=1000, tickets=10, ticket_price=5, ruby_price=50)
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket("c", "u", cycles=1, use_ruby=True, cache={})
    assert codes == ["u9-nobody"]
    assert api.reserve_bodies[0]["useTicket"] is True


def test_falls_back_to_ruby_only_when_tickets_are_out_and_use_ruby_is_true(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(ruby=1000, tickets=0, ticket_price=5, ruby_price=50)
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket("c", "u", cycles=1, use_ruby=True, cache={})
    assert codes == ["u9-nobody"]
    assert api.reserve_bodies[0]["useTicket"] is False


def test_stops_without_spending_when_tickets_are_out_and_use_ruby_is_false(monkeypatch):
    """use_ruby defaults to False - out of tickets must mean "stop", not "spend ruby anyway"."""
    gacha = load("gacha")
    api = FakeGachaApi(ruby=1000, tickets=0, ticket_price=5, ruby_price=50)
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket("c", "u", cycles=3, cache={})
    assert codes == []
    assert api.count("/gacha/group/confirm") == 0
    # Pre-existing quirk, preserved verbatim from apiGachaWithTicket: the specific
    # "no-resource:..." status set inside the loop is always overwritten by the
    # unconditional status line right before return, so the caller only ever sees
    # "empty" here, never the more informative string. See task-6-report.md.
    assert status == "empty"


def test_stops_as_soon_as_a_target_ranger_is_drawn(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(granted_codes=["u1-cony", "u2-brown", "u3-moon"])
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket(
        "c", "u", cycles=5, stop_when_found=True,
        targets={"u2-brown": "Brown"}, cache={},
    )
    assert codes == ["u1-cony", "u2-brown"]
    assert api.count("/gacha/group/confirm") == 2


def test_keeps_drawing_the_full_cycle_count_when_nothing_matches(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(tickets=15, granted_codes=["u1-cony", "u2-brown", "u3-moon"])
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket(
        "c", "u", cycles=3, stop_when_found=True, targets={"u9-nobody": "Nobody"}, cache={},
    )
    assert codes == ["u1-cony", "u2-brown", "u3-moon"]
    assert api.count("/gacha/group/confirm") == 3


def test_giveitall_mode_ignores_cycles_and_goes_until_resources_run_out(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(ruby=0, tickets=12, ticket_price=5,
                       granted_codes=["u1-a", "u1-b", "u1-c"])
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket(
        "c", "u", cycles=1, gacha_mode="giveItAll", cache={},
    )
    # 12 tickets / 5 per pull = 2 whole pulls, then stop - cycles=1 must NOT cap this.
    assert api.count("/gacha/group/confirm") == 2
    assert len(codes) == 2


def test_an_unrecognised_gacha_mode_is_bounded_by_cycles_not_unlimited(monkeypatch):
    """1b (Round 2): only "giveItAll" may mean unlimited. Before this fix the loop only
    ever bounded on the literal string "NumberOfCycles" - any OTHER value, including an
    unrecognised one (a typo, or bot/src/config.ini's own ggachamode = LimitOfRuby, which
    nothing in this file implements), fell through to the same unbounded loop as
    "giveItAll" and only stopped when tickets and ruby both ran out. An unimplemented mode
    must fail safe (spend capped at `cycles`) not fail open (drain the account) - see
    gacha.py's own _KNOWN_GACHA_MODES note.
    """
    gacha = load("gacha")
    api = FakeGachaApi(ruby=0, tickets=50, ticket_price=1, granted_codes=["u1-x"] * 50)
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket(
        "c", "u", cycles=3, gacha_mode="LimitOfRuby", cache={},
    )
    assert api.count("/gacha/group/confirm") == 3
    assert len(codes) == 3


def test_no_open_machine_returns_empty_list_with_no_machine_status_and_does_not_roll(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(machine_open=False)
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket("c", "u", cache={})
    assert codes == []
    assert status == "no-machine"
    assert api.count("/gacha/group/reserve") == 0


def test_a_failed_reserve_is_caught_not_raised(monkeypatch):
    """cmd_roll raises SystemExit on a failed reserve; draw_with_ticket must catch it (the
    original relied on botLineRanger._apiCall to convert SystemExit->Exception for this
    exact call - that wrapper doesn't exist here, so the except clause was broadened
    instead). A fake that could not fail the reserve step would never exercise this path.
    """
    gacha = load("gacha")
    api = FakeGachaApi(reserve_fails=True)
    monkeypatch.setattr(gacha, "call", api)
    codes, status = gacha.draw_with_ticket("c", "u", cycles=2, cache={})
    assert codes == []
    assert status == "empty"
    assert api.count("/gacha/group/confirm") == 0


def test_auto_pick_group_fetches_gacha_info_once_not_twice(monkeypatch):
    """Without group=, draw_with_ticket needs /gacha/info twice for two different reasons
    (pick_ticket_group to find the machine, then the ruby-price lookup for that same
    machine) - this is exactly the redundant fetch this task's cache exists to remove.
    """
    gacha = load("gacha")
    api = FakeGachaApi()
    monkeypatch.setattr(gacha, "call", api)
    cache = {}
    gacha.draw_with_ticket("c", "u", group=None, cycles=1, cache=cache)
    assert api.count("/gacha/info") == 1
    assert "info" in cache


def test_without_a_cache_auto_pick_still_fetches_gacha_info_twice(monkeypatch):
    """Mirrors gacha_info's own "no cache = old behaviour" guarantee at the draw level."""
    gacha = load("gacha")
    api = FakeGachaApi()
    monkeypatch.setattr(gacha, "call", api)
    gacha.draw_with_ticket("c", "u", group=None, cycles=1)
    assert api.count("/gacha/info") == 2


def test_explicit_group_also_shares_the_cache_for_its_price_lookup(monkeypatch):
    gacha = load("gacha")
    api = FakeGachaApi(group_id="grp_gacha_7")
    monkeypatch.setattr(gacha, "call", api)
    cache = {}
    gacha.draw_with_ticket("c", "u", group="grp_gacha_7", cycles=1, cache=cache)
    assert api.count("/gacha/info") == 1
