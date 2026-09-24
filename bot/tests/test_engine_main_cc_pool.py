"""engine_main.attach_cc_pools: Change 2 (Round 2) - give each proxy lane its own
relogin.CcPool, built once here (before any worker thread starts) instead of once per
_relogin() call.

bot/engine/flows.py's _relogin() already reads getattr(s.lane, "cc_pool", None) and only
falls back to a private, per-call CcPool() when that is absent - but nothing before this
change ever set lane.cc_pool, so the fallback was the only path ever taken. Measured effect
(.superpowers/sdd/final-fixes-report.md, "What was not fixed"): with LGRGS_CC_FILE unset -
what `python bot/engine_main.py ranger_api_Login` does from a shell, with no GUI to
pre-mint one - four accounts caused four real guest mints, one per account, against a
2-per-lane-per-minute quota.

Never calls the real game server: relogin.CcPool is monkeypatched out with a fake that
records what it was asked to do instead of hitting /auth (global constraint 4/5).
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import pytest  # noqa: E402
import rangers_api as ra  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "engine_main_under_test_cc_pool", os.path.join(HERE, "engine_main.py"))
engine_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_main)


@pytest.fixture(autouse=True)
def _no_stale_lane_binding():
    """lane is thread-local (tools/rangers_api.py:72) and pytest reuses one worker thread
    across every test in a run - the same reason tools/tests/test_new_account_do.py clears
    it before/after every test. Without this, a lane this file binds on the test thread
    would still be "current" for an unrelated test that runs next on the same thread."""
    ra.use_lane(None)
    yield
    ra.use_lane(None)


class FakeLane:
    """No bucket/auth_quota/parts - attach_cc_pools must not need them, only
    rangers_api.use_lane() and somewhere to set .cc_pool."""

    def __init__(self, name):
        self.name = name


class FakeCcPool:
    """Records the bound lane (rangers_api.current_lane()) and the share_file it was
    built with AT CONSTRUCTION TIME - a fake that only recorded these AFTER __init__
    returned would pass even if attach_cc_pools bound the lane too late (or not at all),
    which is exactly the bug this file exists to catch (global constraint 5: the fake
    must lack what is being proven)."""

    instances = []

    def __init__(self, share_file=None):
        self.share_file = share_file
        self.bound_lane = ra.current_lane()
        FakeCcPool.instances.append(self)

    # The real CcPool's surface, as flows._relogin uses it. Needed now that the pool is
    # built on first use rather than at attach time: these tests have to reach through
    # _LazyCcPool to trigger the build, and a fake that only records construction would
    # fail on the very call that does the triggering.
    def get(self):
        return "cc-%d" % FakeCcPool.instances.index(self)

    def renew(self, cc):
        return self.get()

    def mark_proven(self):
        pass


def test_each_lane_gets_its_own_pool_built_while_that_lane_is_bound(monkeypatch):
    """The mint must happen while ITS OWN lane is the thread-local current_lane(), or it
    goes out through the no-lane CLI fallback instead of that lane's proxy and spends the
    wrong quota.

    attach_cc_pools used to guarantee this by binding each lane itself and minting on the
    spot. It no longer mints at startup at all - constructing a CcPool registers a real
    guest account, so doing that per lane cost one throwaway LINE account per lane on every
    engine start, including a run that found an empty input/ and did nothing. The guarantee
    now comes from where the first use happens: a worker thread calls use_lane(lane) as its
    first statement (bot/engine/pool.py's _worker) and only then reaches _relogin. This
    test plays that worker.
    """
    monkeypatch.setattr(engine_main.relogin, "CcPool", FakeCcPool)
    monkeypatch.delenv("LGRGS_CC_FILE", raising=False)
    FakeCcPool.instances = []
    lanes = [FakeLane("1.2.3.4:8000"), FakeLane("5.6.7.8:9000"), FakeLane("direct")]

    engine_main.attach_cc_pools(lanes)
    assert FakeCcPool.instances == [], "attaching alone must not mint"

    for lane in lanes:                      # what a worker thread does, in its own order
        ra.use_lane(lane)
        lane.cc_pool.get()

    assert [inst.bound_lane for inst in FakeCcPool.instances] == lanes
    assert len({id(inst) for inst in FakeCcPool.instances}) == 3, (
        "three lanes must get three distinct pool objects, not one shared instance")


def test_attach_cc_pools_passes_lgrgs_cc_file_through_like_the_per_call_fallback(monkeypatch):
    """flows._relogin's existing per-call fallback (used whenever a lane has no cc_pool)
    reads os.environ.get("LGRGS_CC_FILE") - the env var bot/main.py's _prepare_shared_cc()
    pre-populates before spawning the engine, for exactly this reason: a GUI run must cost
    zero extra mints. The per-lane pool has to honour the same env var the same way, or a
    GUI run regresses from the zero mints already measured to one mint per lane."""
    monkeypatch.setattr(engine_main.relogin, "CcPool", FakeCcPool)
    monkeypatch.setenv("LGRGS_CC_FILE", r"C:\fake\cc.txt")
    FakeCcPool.instances = []
    lanes = [FakeLane("only")]

    engine_main.attach_cc_pools(lanes)
    lanes[0].cc_pool.get()          # the env var is read when the pool is really built

    assert FakeCcPool.instances[0].share_file == r"C:\fake\cc.txt"


def test_attach_cc_pools_treats_a_blank_lgrgs_cc_file_as_unset(monkeypatch):
    """Mirrors flows._relogin's own `os.environ.get("LGRGS_CC_FILE") or None` - an env
    var exported but left blank (a launcher quirk noted elsewhere in this project) must
    not be handed to CcPool as a literal empty-string path."""
    monkeypatch.setattr(engine_main.relogin, "CcPool", FakeCcPool)
    monkeypatch.setenv("LGRGS_CC_FILE", "")
    FakeCcPool.instances = []
    lanes = [FakeLane("only")]

    engine_main.attach_cc_pools(lanes)
    lanes[0].cc_pool.get()          # the env var is read when the pool is really built

    assert FakeCcPool.instances[0].share_file is None
