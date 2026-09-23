"""
Hardware ID (HWID) Generator
สร้าง hardware fingerprint จาก hardware info หลายแหล่ง
ใช้สำหรับผูก subscription กับเครื่องคอมพิวเตอร์
"""
import hashlib
import uuid
import platform
import subprocess
import sys


def _run_wmic(command):
    """Run wmic command and return output"""
    try:
        result = subprocess.check_output(
            command, shell=True, text=True,
            encoding='utf-8', errors='ignore',
            stderr=subprocess.DEVNULL, timeout=5
        )
        lines = result.strip().split('\n')
        # Skip header line, get value
        if len(lines) >= 2:
            return lines[-1].strip()
        return ""
    except Exception:
        return ""


def _get_bios_serial():
    """Get BIOS serial number"""
    if sys.platform != 'win32':
        return ""
    return _run_wmic('wmic bios get serialnumber')


def _get_board_serial():
    """Get motherboard serial number"""
    if sys.platform != 'win32':
        return ""
    return _run_wmic('wmic baseboard get serialnumber')


def _get_disk_serial():
    """Get primary disk serial number"""
    if sys.platform != 'win32':
        return ""
    return _run_wmic('wmic diskdrive get serialnumber')


def _get_mac_address():
    """Get MAC address"""
    return str(uuid.getnode())


def _get_cpu_id():
    """Get CPU identifier"""
    return platform.processor()


def _get_machine_name():
    """Get machine name"""
    return platform.node()


def generate_hwid():
    """
    Generate hardware fingerprint from multiple sources

    Returns:
        str: 32-character hex string (SHA-256 truncated)
    """
    components = [
        _get_bios_serial(),
        _get_board_serial(),
        _get_disk_serial(),
        _get_mac_address(),
        _get_cpu_id(),
        _get_machine_name(),
    ]

    # Filter empty values and join
    raw = '|'.join(c for c in components if c)

    # Hash to fixed-length fingerprint
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


# Cache HWID in memory (generate once per session)
_cached_hwid = None


def get_hwid():
    """
    Get cached HWID (generates once, returns cached value after)

    Returns:
        str: 32-character hex HWID
    """
    global _cached_hwid
    if _cached_hwid is None:
        _cached_hwid = generate_hwid()
    return _cached_hwid


if __name__ == "__main__":
    hwid = generate_hwid()
    print(f"HWID: {hwid}")
    print(f"Length: {len(hwid)}")
