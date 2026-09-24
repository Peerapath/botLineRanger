"""Repo-wide pytest setup.

client_version keeps its state in a JSON file and, with learning on, re-sends a refused request
with other App-Versions and asks an "oracle" - a REAL GET /home - when the server says a
version or route is unknown. No test written before it existed expects any of that: a fake that
answers 401 would suddenly see extra calls, and a fake that answers 404 would reach the network.
So every test gets its own non-learning instance in its own tmp_path, and an oracle that fails
loudly if anything reaches it. client_version's own tests build their instances explicitly.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import client_version  # noqa: E402


def _no_network_oracle(prefix, app_version):
    raise AssertionError("a test reached the real version oracle (%s, %s)" % (prefix, app_version))


@pytest.fixture(autouse=True)
def _client_version_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(client_version, "_DEFAULT",
                        client_version.ClientVersion(str(tmp_path / "api_version.json"), learn=False))
    monkeypatch.setattr(client_version, "_ORACLE", _no_network_oracle)
    yield
