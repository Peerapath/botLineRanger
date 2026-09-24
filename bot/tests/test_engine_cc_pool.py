"""attach_cc_pools must not register a guest account just by starting the engine.

The bug this guards: relogin.CcPool.__init__ ends in self._mint() when the shared file
holds nothing fresh, so CONSTRUCTING one creates a real account on game-api.line.me. The
first attach_cc_pools built one per lane at startup, for every mode - so an engine that
started, found an empty input/ and exited had still minted one throwaway LINE account per
lane. At 50 proxies that is 50 accounts per start, against a 2-per-IP-per-minute quota.
Caught when a build smoke test with an empty input/ made two real calls to the live
endpoint.
"""
import importlib.util
import os
import sys
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

_spec = importlib.util.spec_from_file_location(
    "engine_main_cc_under_test", os.path.join(HERE, "engine_main.py"))
engine_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_main)


class _Lane:
    """A stand-in with no cc_pool of its own - the thing being proven is that
    attach_cc_pools puts one there without it costing a mint."""

    def __init__(self, name):
        self.name = name


class _CountingPool:
    """Counts constructions, which is what a real mint costs."""
    built = 0

    def __init__(self, share_file=None, max_age=None):
        type(self).built += 1
        self._cc = "cc-%d" % type(self).built

    def get(self):
        return self._cc

    def renew(self, cc):
        return self._cc

    def mark_proven(self):
        pass


def _patched(monkeypatch):
    _CountingPool.built = 0
    monkeypatch.setattr(engine_main.relogin, "CcPool", _CountingPool)
    return _CountingPool


def test_attaching_a_pool_to_every_lane_mints_nothing(monkeypatch):
    pool_cls = _patched(monkeypatch)
    lanes = [_Lane("p%d" % i) for i in range(50)]

    engine_main.attach_cc_pools(lanes)

    assert pool_cls.built == 0, (
        "starting the engine must not register a guest account - this is 50 real LINE "
        "accounts per start against a 2-per-IP-per-minute quota")
    assert all(lane.cc_pool is not None for lane in lanes)


def test_the_pool_is_built_on_first_use_and_only_once(monkeypatch):
    pool_cls = _patched(monkeypatch)
    lane = _Lane("p0")
    engine_main.attach_cc_pools([lane])

    first = lane.cc_pool.get()
    second = lane.cc_pool.get()
    lane.cc_pool.mark_proven()

    assert pool_cls.built == 1, "one mint per lane, however many accounts it serves"
    assert first == second == "cc-1"


def test_two_lanes_do_not_share_one_pool(monkeypatch):
    pool_cls = _patched(monkeypatch)
    a, b = _Lane("p0"), _Lane("p1")
    engine_main.attach_cc_pools([a, b])

    assert a.cc_pool.get() == "cc-1"
    assert b.cc_pool.get() == "cc-2", (
        "the mint quota is per IP, so each lane needs its own cc from its own proxy")
    assert pool_cls.built == 2


def test_threads_racing_the_first_use_build_one_pool_between_them(monkeypatch):
    """Every thread on a lane shares this object. Without the lock they would each see
    an unbuilt pool and mint - the per-account minting this exists to stop, narrowed to
    a startup race."""
    pool_cls = _patched(monkeypatch)
    lane = _Lane("p0")
    engine_main.attach_cc_pools([lane])
    start = threading.Barrier(24)
    seen = []
    seen_lock = threading.Lock()

    def worker():
        start.wait(timeout=5)
        cc = lane.cc_pool.get()
        with seen_lock:
            seen.append(cc)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not any(t.is_alive() for t in threads), "a deadlock here must fail, not hang"
    assert pool_cls.built == 1, "24 threads, one mint"
    assert set(seen) == {"cc-1"}
