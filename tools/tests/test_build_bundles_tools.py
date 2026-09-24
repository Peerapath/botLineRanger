"""Every tools module the build obfuscates must also be a PyInstaller hidden import.

The engine imports tools/ modules by bare name after a sys.path insert that means nothing once
frozen, so a module pyarmor encrypts but the spec does not list is silently left out of the exe
- and client_version is imported by rangers_api, i.e. by every mode.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pyarmor_tools():
    text = open(os.path.join(ROOT, "bot", "build.bat"), encoding="utf-8", errors="replace").read()
    command = []
    for line in text.split("pyarmor gen --output dist_pyarmor", 1)[1].splitlines():
        command.append(line)
        if line.strip() and not line.rstrip().endswith("^"):
            break
    return set(re.findall(r"\.\.\\tools\\(\w+)\.py", "\n".join(command)))


def _hidden_imports():
    text = open(os.path.join(ROOT, "bot", "BotLineRanger.spec"), encoding="utf-8").read()
    block = text.split("hiddenimports=[", 1)[1].split("\n    ],", 1)[0]
    return set(re.findall(r"^\s*'(\w+)',", block, re.M))


def test_client_version_is_obfuscated_and_bundled():
    assert "client_version" in _pyarmor_tools()
    assert "client_version" in _hidden_imports()


def test_every_obfuscated_tool_is_a_hidden_import():
    assert _pyarmor_tools() - _hidden_imports() == set()
