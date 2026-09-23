"""pull_roster.unit_names / matchGachaName / add_ranger_name: pins the roster-name-summary
behaviour moved from botLineRanger (see task-6-report.md for exactly which function each
one moved from, and a correction to the brief's "all three came from getTeanInfo" framing).

Not in the task-6 brief's own checklist (it only wrote a test for gacha_info's cache). The
task instructions require moved code to be pinned by tests too, not just proven importable.
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


def test_a_unit_matching_the_config_is_named():
    pull_roster = load("pull_roster")
    units = [{"unitCode": "u1-cony"}]
    assert pull_roster.unit_names(units, {"u1-cony": "Cony"}) == "Cony"


def test_a_unit_not_in_the_config_is_dropped_silently():
    pull_roster = load("pull_roster")
    units = [{"unitCode": "u2-brown"}]
    assert pull_roster.unit_names(units, {"u1-cony": "Cony"}) == ""


def test_ranger_config_none_is_treated_as_no_targets_not_a_crash():
    pull_roster = load("pull_roster")
    units = [{"unitCode": "u1-cony"}]
    assert pull_roster.unit_names(units, ranger_config=None) == ""
    assert pull_roster.unit_names(units) == ""


def test_owning_two_copies_increments_the_suffix_instead_of_repeating_the_name():
    """Pins add_ranger_name's real dedupe rule: two Conys collapse to "Cony2", they do not
    become "Cony_Cony2" - easy to get wrong if unit_names were rewritten instead of moved.
    """
    pull_roster = load("pull_roster")
    units = [{"unitCode": "u1-cony"}, {"unitCode": "u1-cony"}]
    assert pull_roster.unit_names(units, {"u1-cony": "Cony"}) == "Cony2"


def test_distinct_matches_join_with_underscore_in_roster_order():
    pull_roster = load("pull_roster")
    units = [{"unitCode": "u1-cony"}, {"unitCode": "u2-brown"}]
    config = {"u1-cony": "Cony", "u2-brown": "Brown"}
    assert pull_roster.unit_names(units, config) == "Cony_Brown"


def test_match_is_case_insensitive_like_the_original_fuzzy_match():
    """matchGachaName's threshold defaults to 1.0 (SequenceMatcher ratio), which after the
    lower()+whitespace-strip in fuzzy_match is an exact match - but still case/space
    insensitive, unlike a bare dict-key lookup. Pin that this survived the move.
    """
    pull_roster = load("pull_roster")
    units = [{"unitCode": "U1-CONY"}]
    assert pull_roster.unit_names(units, {"u1-cony": "Cony"}) == "Cony"


def test_unit_names_accepts_raw_playerunits_shaped_dicts():
    """The engine's flows.py fires the roster API itself and hands the raw playerUnits list
    straight in (see this function's docstring) - not botLineRanger.getTeanInfo's
    already-transformed rows. Only "unitCode" is read, so both shapes must work; this
    pins the raw-API shape specifically (extra fields it doesn't touch, no "name" key).
    """
    pull_roster = load("pull_roster")
    raw_units = [{"invenId": 1, "unitCode": "u1-cony", "playerUnitMaxLevel": 80}]
    assert pull_roster.unit_names(raw_units, {"u1-cony": "Cony"}) == "Cony"


def test_matchgachaname_returns_the_configured_display_name_not_the_key():
    pull_roster = load("pull_roster")
    is_match, name = pull_roster.matchGachaName({"u1-cony": "Cony Display"}, "u1-cony")
    assert is_match is True
    assert name == "ConyDisplay"   # matchGachaName strips spaces from the display name too


def test_matchgachaname_reports_no_match_for_an_unconfigured_code():
    pull_roster = load("pull_roster")
    is_match, _ = pull_roster.matchGachaName({"u1-cony": "Cony"}, "u2-brown")
    assert is_match is False


def test_add_ranger_name_starts_a_fresh_string():
    pull_roster = load("pull_roster")
    assert pull_roster.add_ranger_name("", "Cony") == "Cony"


def test_add_ranger_name_appends_a_distinct_name_with_underscore():
    pull_roster = load("pull_roster")
    assert pull_roster.add_ranger_name("Cony", "Brown") == "Cony_Brown"


def test_add_ranger_name_increments_a_repeat_in_place_not_at_the_end():
    """Cony_Brown seeing another Cony must become Cony2_Brown, keeping position - not
    Cony_Brown_Cony2. Pins add_ranger_name's index-preserving update.
    """
    pull_roster = load("pull_roster")
    assert pull_roster.add_ranger_name("Cony_Brown", "Cony") == "Cony2_Brown"
