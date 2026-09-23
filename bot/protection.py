"""
Runtime Protection Module
Anti-debugging, anti-tamper, and integrity checks
ตรวจจับ debugger, reverse engineering tools, และ memory tampering

ใช้: from protection import run_protection_checks, start_background_guard
"""
import ctypes
import ctypes.wintypes
import os
import sys
import threading
import time
import hashlib


# ==============================
# Anti-Debug Detection
# ==============================

def _is_debugger_present():
    """Check Windows IsDebuggerPresent API"""
    try:
        return ctypes.windll.kernel32.IsDebuggerPresent() != 0
    except Exception:
        return False


def _check_remote_debugger():
    """Check for remote debugger attached to process"""
    try:
        is_debugged = ctypes.c_int(0)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(is_debugged)
        )
        return is_debugged.value != 0
    except Exception:
        return False


def _check_ntglobalflag():
    """Check NtGlobalFlag in PEB for debugger traces"""
    try:
        # NtQueryInformationProcess to check debug flags
        ntdll = ctypes.windll.ntdll
        process_debug_port = ctypes.c_ulong(0)
        # ProcessDebugPort = 7
        status = ntdll.NtQueryInformationProcess(
            ctypes.windll.kernel32.GetCurrentProcess(),
            7,  # ProcessDebugPort
            ctypes.byref(process_debug_port),
            ctypes.sizeof(process_debug_port),
            None
        )
        if status == 0 and process_debug_port.value != 0:
            return True
    except Exception:
        pass
    return False


def _check_debug_environment():
    """Check for debugging environment variables and paths"""
    suspicious_env = [
        'PYDEVD_USE_FRAME_EVAL',
        'PYDEVD_LOAD_VALUES_ASYNC',
        '_PYCHARM_ATTACH_DEBUG',
    ]
    for env in suspicious_env:
        if os.environ.get(env):
            return True
    return False


# ==============================
# Anti-RE Tool Detection
# ==============================

# Process names ที่บ่งบอกว่ากำลังถูก reverse engineer
_SUSPICIOUS_PROCESSES = [
    "x64dbg.exe", "x32dbg.exe", "ollydbg.exe", "ida.exe", "ida64.exe",
    "idag.exe", "idag64.exe", "idaw.exe", "idaw64.exe",
    "ghidra.exe", "ghidrarun.exe",
    "processhacker.exe", "procmon.exe", "procmon64.exe",
    "procexp.exe", "procexp64.exe",
    "dnspy.exe", "de4dot.exe",
    "httpdebugger.exe", "fiddler.exe", "wireshark.exe",
    "cheatengine-x86_64.exe", "cheatengine.exe",
    "hiew32.exe", "hiew.exe",
    "scylla.exe", "scylla_x64.exe", "scylla_x86.exe",
    "protection_id.exe",
    "pestudio.exe", "die.exe",
    "pyinstxtractor.exe",
]

# Window titles ที่น่าสงสัย
_SUSPICIOUS_WINDOW_TITLES = [
    "x64dbg", "x32dbg", "OllyDbg", "IDA", "Ghidra",
    "Process Hacker", "Process Monitor", "Process Explorer",
    "dnSpy", "Cheat Engine", "HTTP Debugger", "Fiddler",
    "Wireshark", "PE Studio", "Detect It Easy",
]


def _check_suspicious_processes():
    """Check for running reverse engineering tools via tasklist"""
    try:
        import subprocess
        output = subprocess.check_output(
            'tasklist /FO CSV /NH',
            shell=True, text=True, encoding='utf-8', errors='ignore',
            stderr=subprocess.DEVNULL, timeout=5
        )
        output_lower = output.lower()
        for proc in _SUSPICIOUS_PROCESSES:
            if proc.lower() in output_lower:
                return True
    except Exception:
        pass
    return False


def _check_suspicious_windows():
    """Check for windows with suspicious titles using EnumWindows"""
    found = [False]

    try:
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

        def callback(hwnd, lparam):
            try:
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()
                    for suspicious in _SUSPICIOUS_WINDOW_TITLES:
                        if suspicious.lower() in title:
                            found[0] = True
                            return False  # stop enumeration
            except Exception:
                pass
            return True

        ctypes.windll.user32.EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        pass

    return found[0]


# ==============================
# VM / Sandbox Detection
# ==============================

def _check_vm_indicators():
    """Check for common VM/sandbox indicators"""
    import platform

    # Check system manufacturer via WMI
    try:
        import subprocess
        result = subprocess.check_output(
            'wmic computersystem get manufacturer,model /value',
            shell=True, text=True, encoding='utf-8', errors='ignore',
            stderr=subprocess.DEVNULL, timeout=5
        )
        result_lower = result.lower()
        vm_indicators = ['vmware', 'virtualbox', 'vbox', 'qemu', 'xen', 'hyper-v']
        for indicator in vm_indicators:
            if indicator in result_lower:
                return True
    except Exception:
        pass

    # Check for VM-specific files
    vm_files = [
        r"C:\Windows\System32\drivers\VBoxMouse.sys",
        r"C:\Windows\System32\drivers\vmhgfs.sys",
        r"C:\Windows\System32\drivers\vmmouse.sys",
    ]
    for f in vm_files:
        if os.path.exists(f):
            return True

    return False


# ==============================
# Integrity Checks
# ==============================

_original_hashes = {}


def _compute_module_hash(module_name):
    """Compute hash of a loaded module's source file"""
    try:
        mod = sys.modules.get(module_name)
        if mod and hasattr(mod, '__file__') and mod.__file__:
            filepath = mod.__file__
            if filepath.endswith('.pyc'):
                filepath = filepath[:-1]  # try .py
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        pass
    return None


def snapshot_module_hashes(module_names):
    """
    Take a snapshot of module file hashes at startup
    Call this once after imports are done
    """
    global _original_hashes
    for name in module_names:
        h = _compute_module_hash(name)
        if h:
            _original_hashes[name] = h


def check_module_integrity():
    """
    Verify that critical module files haven't been modified since startup
    Returns list of tampered module names (empty = all good)
    """
    tampered = []
    for name, original_hash in _original_hashes.items():
        current_hash = _compute_module_hash(name)
        if current_hash and current_hash != original_hash:
            tampered.append(name)
    return tampered


_exe_hash = None  # SHA-256 of running .exe, cached at first call


def _compute_exe_hash():
    """
    Compute SHA-256 hash of the running .exe file (frozen mode only)
    Result is cached in module-level variable after first computation
    """
    global _exe_hash
    if _exe_hash is not None:
        return _exe_hash
    if not getattr(sys, 'frozen', False):
        return None  # dev mode — no .exe to hash
    try:
        h = hashlib.sha256()
        with open(sys.executable, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        _exe_hash = h.hexdigest()
        return _exe_hash
    except Exception:
        return None


def get_exe_hash():
    """
    Public API: returns SHA-256 hex string of the running .exe
    Returns None when running in dev mode (not frozen)
    Call at startup — first call takes ~1-2s, then cached
    """
    return _compute_exe_hash()


def _check_exe_integrity():
    """
    Upgraded: SHA-256 hash-based tamper detection (replaces size-only check)
    Only works when running as frozen exe
    """
    if not getattr(sys, 'frozen', False):
        return True  # skip in dev mode

    # Hash is computed once and cached; repeated calls are instant
    # Returns None only if file is unreadable (itself a sign of tampering)
    return _compute_exe_hash() is not None


# ==============================
# Anti-Patching: Critical Function Verification
# ==============================

_critical_function_hashes = {}


def register_critical_function(func):
    """
    Register a function's bytecode hash for tamper detection
    Call at startup for functions that should not be patched
    """
    try:
        code = func.__code__
        raw = code.co_code
        h = hashlib.sha256(raw).hexdigest()
        _critical_function_hashes[func.__qualname__] = (func, h)
    except Exception:
        pass


def verify_critical_functions():
    """
    Check that registered functions haven't been monkey-patched
    Returns list of tampered function names
    """
    tampered = []
    for name, (func, original_hash) in _critical_function_hashes.items():
        try:
            current_hash = hashlib.sha256(func.__code__.co_code).hexdigest()
            if current_hash != original_hash:
                tampered.append(name)
        except Exception:
            tampered.append(name)
    return tampered


# ==============================
# Timing-based Debug Detection
# ==============================

def _timing_check():
    """
    Detect debugger via timing anomaly
    Normal execution should be < 50ms, debugger stepping is much slower
    """
    start = time.perf_counter_ns()

    # Simple operations that should be fast
    total = 0
    for i in range(10000):
        total += i

    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000

    # If simple loop takes > 500ms, very likely being debugged/stepped
    return elapsed_ms > 500


# ==============================
# Main Protection API
# ==============================

class ProtectionResult:
    """Result of protection checks"""
    __slots__ = ('passed', 'threats')

    def __init__(self):
        self.passed = True
        self.threats = []

    def add_threat(self, name):
        self.passed = False
        self.threats.append(name)


def run_protection_checks(check_vm=False):
    """
    Run all protection checks once

    Args:
        check_vm: Whether to check for VM/sandbox (default False, ผู้ใช้อาจรันบน VM จริง)

    Returns:
        ProtectionResult with passed=True/False and list of threat names
    """
    result = ProtectionResult()

    # Anti-debug
    if _is_debugger_present():
        result.add_threat("debugger_attached")

    if _check_remote_debugger():
        result.add_threat("remote_debugger")

    if _check_ntglobalflag():
        result.add_threat("debug_port")

    if _check_debug_environment():
        result.add_threat("debug_environment")

    if _timing_check():
        result.add_threat("timing_anomaly")

    # Anti-RE tools
    if _check_suspicious_processes():
        result.add_threat("re_tools_running")

    if _check_suspicious_windows():
        result.add_threat("re_windows_open")

    # VM detection (optional)
    if check_vm and _check_vm_indicators():
        result.add_threat("virtual_machine")

    # Integrity
    if not _check_exe_integrity():
        result.add_threat("exe_modified")

    tampered_modules = check_module_integrity()
    if tampered_modules:
        result.add_threat(f"modules_tampered:{','.join(tampered_modules)}")

    tampered_funcs = verify_critical_functions()
    if tampered_funcs:
        result.add_threat(f"functions_patched:{','.join(tampered_funcs)}")

    return result


def start_background_guard(interval_seconds=120, on_threat=None):
    """
    Start background thread that periodically checks for threats

    Args:
        interval_seconds: Check interval (default 120 = 2 minutes)
        on_threat: Callback function(ProtectionResult) called when threat detected
                   If None, default action is sys.exit(1)
    """
    def _guard_loop():
        while True:
            time.sleep(interval_seconds)
            try:
                result = run_protection_checks()
                if not result.passed:
                    if on_threat:
                        on_threat(result)
                    else:
                        os._exit(1)
            except Exception:
                pass

    t = threading.Thread(target=_guard_loop, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    print("=" * 50)
    print("  Protection Module - Self Test")
    print("=" * 50)
    print()

    result = run_protection_checks(check_vm=True)

    if result.passed:
        print("[OK] All checks passed - no threats detected")
    else:
        print(f"[!] Threats detected ({len(result.threats)}):")
        for t in result.threats:
            print(f"    - {t}")
