"""
Build helper: check/register/update exe versions on the license server.

Usage (called from build.bat):
    python server_version.py check <version>
        exit 0 = version exists on server
        exit 1 = version does not exist
        exit 2 = network/auth error

    python server_version.py register <version> <exe_hash>
        exit 0 = created (201)
        exit 1 = version already exists on server (409)
        exit 2 = other error

    python server_version.py update <version> <exe_hash>
        exit 0 = updated (200)
        exit 2 = error
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import requests


SERVER_URL = "http://173.254.236.138.bot.linerangers.sslip.io"
REQUEST_TIMEOUT = 15


def _load_build_api_key() -> str:
    key = os.environ.get("BUILD_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).parent / ".build_env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "BUILD_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""


def _headers(api_key: str) -> dict:
    return {
        "X-Build-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _auto_notes() -> str:
    return f"Built on {datetime.now():%Y-%m-%d %H:%M} via build.bat"


def _require_key(api_key: str) -> None:
    if not api_key:
        print("[ERROR] BUILD_API_KEY not set. Put it in .build_env or environment.")
        sys.exit(2)


def cmd_check(version: str) -> int:
    api_key = _load_build_api_key()
    _require_key(api_key)
    url = f"{SERVER_URL}/api/exe-versions/{version}"
    try:
        r = requests.get(url, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"[ERROR] Cannot reach server: {e}")
        return 2

    if r.status_code == 200:
        print(f"[INFO] Version {version} exists on server.")
        return 0
    if r.status_code == 404:
        print(f"[INFO] Version {version} not found on server.")
        return 1
    if r.status_code == 401:
        print("[ERROR] Invalid BUILD_API_KEY.")
        return 2
    print(f"[ERROR] Unexpected response: {r.status_code} {r.text[:200]}")
    return 2


def cmd_register(version: str, exe_hash: str) -> int:
    api_key = _load_build_api_key()
    _require_key(api_key)
    payload = {
        "version": version,
        "exe_hash": exe_hash,
        "notes": _auto_notes(),
    }
    url = f"{SERVER_URL}/api/exe-versions"
    try:
        r = requests.post(url, json=payload, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"[ERROR] Cannot reach server: {e}")
        return 2

    if r.status_code == 201:
        print(f"[OK] Registered version {version} on server.")
        return 0
    if r.status_code == 409:
        print(f"[INFO] Version {version} already exists on server.")
        return 1
    if r.status_code == 401:
        print("[ERROR] Invalid BUILD_API_KEY.")
        return 2
    print(f"[ERROR] Register failed: {r.status_code} {r.text[:200]}")
    return 2


def cmd_update(version: str, exe_hash: str) -> int:
    api_key = _load_build_api_key()
    _require_key(api_key)
    payload = {
        "exe_hash": exe_hash,
        "notes": _auto_notes(),
    }
    url = f"{SERVER_URL}/api/exe-versions/{version}"
    try:
        r = requests.put(url, json=payload, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"[ERROR] Cannot reach server: {e}")
        return 2

    if r.status_code == 200:
        print(f"[OK] Updated exe_hash for version {version}.")
        return 0
    if r.status_code == 404:
        print(f"[ERROR] Version {version} not found on server.")
        return 2
    if r.status_code == 401:
        print("[ERROR] Invalid BUILD_API_KEY.")
        return 2
    print(f"[ERROR] Update failed: {r.status_code} {r.text[:200]}")
    return 2


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1].lower()
    if cmd == "check" and len(sys.argv) == 3:
        return cmd_check(sys.argv[2].strip())
    if cmd == "register" and len(sys.argv) == 4:
        return cmd_register(sys.argv[2].strip(), sys.argv[3].strip())
    if cmd == "update" and len(sys.argv) == 4:
        return cmd_update(sys.argv[2].strip(), sys.argv[3].strip())
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
