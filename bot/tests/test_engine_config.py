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


def test_ranger_targets_stay_strings_not_booleans(tmp_path):
    """Coercing these to bool turns every display name into False, so no draw ever stops
    on a target, nothing routes to backup, and the exported filename loses its ranger
    part - all silently."""
    settings = _write(tmp_path / "config.ini", "[settings]\n")
    rangers = _write(tmp_path / "configRangers.ini", "[rangers]\nu1617e-ka = คาฟก้า\n")

    cfg = engine_main.load_config(settings, rangers)

    assert cfg["_rangers_config"]["u1617e-ka"] == "คาฟก้า"
