"""engine_main.load_config: a hand-edited config file must not stop the engine.

The bug this guards: `bot/src/configRangers.ini` has `u1206e-moon` listed twice, and a
strict configparser answers that with DuplicateOptionError. load_config had no
strict=False, so `python bot/engine_main.py ranger_api_Login` died at startup against
the user's real config - before one account was touched, over a duplicated ranger name.

The bot being replaced hit this and fixed it, with a comment saying exactly why. Porting
the loader dropped the flag and brought the bug back, and nothing noticed because every
test until this one supplied its own tidy config.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

_spec = importlib.util.spec_from_file_location(
    "engine_main_under_test", os.path.join(HERE, "engine_main.py"))
engine_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_main)


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_repeated_ranger_line_does_not_stop_the_engine(tmp_path):
    settings = _write(tmp_path / "config.ini", "[settings]\napirps = 90\n")
    rangers = _write(tmp_path / "configRangers.ini",
                     "[rangers]\nu1206e-moon = มูน\nu1206e-moon = มูนสอง\n")

    cfg = engine_main.load_config(settings, rangers)

    assert cfg["_rangers_config"]["u1206e-moon"] == "มูนสอง", (
        "the last line wins - retyping a line is how a user corrects it")


def test_a_repeated_settings_line_does_not_stop_the_engine(tmp_path):
    settings = _write(tmp_path / "config.ini",
                      "[settings]\napirps = 80\napirps = 90\n")

    cfg = engine_main.load_config(settings)

    assert cfg["apirps"] == "90"


def test_the_users_own_config_files_load(tmp_path):
    """Against the real files on this machine, not a fixture. Skips where they are
    absent so the suite still runs on a clean checkout - these are gitignored because
    they carry the user's licence email."""
    import pytest
    settings = os.path.join(HERE, "src", "config.ini")
    rangers = os.path.join(HERE, "src", "configRangers.ini")
    if not (os.path.isfile(settings) and os.path.isfile(rangers)):
        pytest.skip("no local src/config.ini + src/configRangers.ini on this machine")

    cfg = engine_main.load_config(settings, rangers)

    assert cfg["_rangers_config"], "the real configRangers.ini must yield ranger targets"


def test_useruby_is_coerced_to_a_real_bool_not_left_as_the_string_false(tmp_path):
    """C4 (final review): BOOLS omitted "useruby", so flows.py's bool(cfg.get("useruby",
    False)) saw the raw STRING "False" - and bool("False") is True in Python (any
    non-empty string is truthy). Reproduced against the pre-fix code: useruby -> 'False'
    | bool() = True. default_config/config.ini ships useruby = False - every fresh
    install hit this and drew gacha with ruby too, silently, on every account.
    """
    settings = _write(tmp_path / "config.ini", "[settings]\nuseruby = False\n")
    cfg = engine_main.load_config(settings)
    assert cfg["useruby"] is False
    assert bool(cfg["useruby"]) is False


def test_login_mode_reads_the_r_prefixed_gacha_settings(tmp_path):
    """I1 (final review): the engine read stopwhenfound/gachacycles/gachamode/useruby -
    names neither the GUI nor the user's real config ever writes. bot/src/config.ini has
    only the per-mode split: rstopwhenfound/gstopwhenfound, rgachacycles/ggachacycles,
    rgachamode/ggachamode, ruseruby/guse200ruby (r = Login-family, g = GenID - af264b0:
    bot/botLineRanger.py:353-356,368-371 is the old reader that did this split). Every
    gacha setting in the GUI was disconnected from the engine.
    """
    settings = _write(tmp_path / "config.ini", "\n".join([
        "[settings]",
        "rstopwhenfound = False", "gstopwhenfound = True",
        "rgachamode = NumberOfCycles", "ggachamode = LimitOfRuby",
        "rgachacycles = 1", "ggachacycles = 200",
        "ruseruby = False", "guse200ruby = True",
        "",
    ]))
    login_cfg = engine_main.load_config(settings, mode="ranger_api_Login")
    level3_cfg = engine_main.load_config(settings, mode="ranger_api_Level3")
    genid_cfg = engine_main.load_config(settings, mode="ranger_api_GenID")

    assert (login_cfg["stopwhenfound"], login_cfg["gachamode"], login_cfg["gachacycles"],
            login_cfg["useruby"]) == (False, "NumberOfCycles", 1, False)
    # Level3 shares Login's "r" globals in the original (startBotLevel3_API_headless -
    # af264b0:bot/botLineRanger.py:8366 reads RGACHACYCLES, not a level3-specific pair).
    assert (level3_cfg["stopwhenfound"], level3_cfg["gachamode"], level3_cfg["gachacycles"],
            level3_cfg["useruby"]) == (False, "NumberOfCycles", 1, False)
    assert (genid_cfg["stopwhenfound"], genid_cfg["gachamode"], genid_cfg["gachacycles"],
            genid_cfg["useruby"]) == (True, "LimitOfRuby", 200, True)


def test_a_config_without_the_per_mode_split_still_works(tmp_path):
    """I1's own "add the fallbacks" ask: a config that predates the r/g split
    (default_config/config.ini's actual shape - no rstopwhenfound/gstopwhenfound at all,
    just stopwhenfound) must still produce a working, coerced value - not a KeyError and
    not a raw string handed to flows.py.
    """
    settings = _write(tmp_path / "config.ini",
                      "[settings]\nstopwhenfound = True\ngachacycles = 5\nuseruby = False\n")
    cfg = engine_main.load_config(settings, mode="ranger_api_Login")
    assert cfg["stopwhenfound"] is True
    assert cfg["gachacycles"] == 5
    assert cfg["useruby"] is False


def test_ranger_targets_stay_strings_not_booleans(tmp_path):
    """Coercing these to bool turns every display name into False, so no draw ever stops
    on a target, nothing routes to backup, and the exported filename loses its ranger
    part - all silently."""
    settings = _write(tmp_path / "config.ini", "[settings]\n")
    rangers = _write(tmp_path / "configRangers.ini", "[rangers]\nu1617e-ka = คาฟก้า\n")

    cfg = engine_main.load_config(settings, rangers)

    assert cfg["_rangers_config"]["u1617e-ka"] == "คาฟก้า"
