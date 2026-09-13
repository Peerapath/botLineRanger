# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_all

# ===============================================
# Enhanced Security Configuration for PyInstaller
# ===============================================

block_cipher = None


def _safe_collect_all(pkg):
    """แพ็กเกจที่ไม่ได้ติดตั้งจะได้ tuple ว่างแทนที่จะทำให้ build ล้ม"""
    try:
        return collect_all(pkg)
    except Exception:
        return [], [], []


# u2 มี asset ฝังในแพ็กเกจ (apk ของ server) ใส่แค่ hiddenimports ไม่พอ ต้อง collect datas ด้วย
_u2_datas, _u2_bins, _u2_hidden = _safe_collect_all('uiautomator2')
_adb_datas, _adb_bins, _adb_hidden = _safe_collect_all('adbutils')

a = Analysis(
    ['main.py'],                    # entry point จริง (apply_pyarmor_patch จะ swap เป็น obfuscated)
    pathex=['.', 'dist_pyarmor'],   # ค้นหา modules จาก dist_pyarmor ด้วย
    binaries=[
        # cv2 DLLs (collect automatically)
        *collect_dynamic_libs('cv2'),
        # uiautomator2 + adbutils: DLL ที่แพ็กเกจฝังมา (AdbWinApi.dll, AdbWinUsbApi.dll)
        # adb.exe ไม่ได้อยู่ตรงนี้ — collect_all จัดมันเป็น datas ไปแล้ว
        # u2 ตอนนี้ยัง 0 binaries แต่คง *_u2_bins ไว้ให้สมมาตร เผื่อเวอร์ชันหน้ามี native ext
        *_u2_bins, *_adb_bins,
        # tkinter DLLs (จำเป็นสำหรับ GUI)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\DLLs\_tkinter.pyd', '.'),
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\DLLs\tcl86t.dll', '.'),
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\DLLs\tk86t.dll', '.'),
    ],
    datas=[
        # PyArmor runtime ถูก inject โดย apply_pyarmor_patch() แล้ว ไม่ต้องใส่ที่นี่
        # tcl/tk data folders (จำเป็นสำหรับ GUI rendering)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\tcl\tcl8.6', 'tcl/tcl8.6'),
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\tcl\tk8.6', 'tcl/tk8.6'),
        # customtkinter themes/fonts (ขาดแล้ว UI จะ crash)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\Lib\site-packages\customtkinter', 'customtkinter'),
        # ppadb (pure Python package)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\Lib\site-packages\ppadb', 'ppadb'),
        # PIL/Pillow (customtkinter ต้องการ)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\Lib\site-packages\PIL', 'PIL'),
        # pytesseract
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\Lib\site-packages\pytesseract', 'pytesseract'),
        # uiautomator2 + adbutils: resource files ที่แพ็กเกจฝังมา (apk/jar/sh)
        *_u2_datas, *_adb_datas,
    ],
    hiddenimports=[
        # Obfuscated local modules (pathex=dist_pyarmor ทำให้ PyInstaller หาเจอ)
        'config_secure',
        'hwid',
        'protection',
        'botLineRanger',
        'ADB',
        'pyarmor_runtime_009939',
        # GUI
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'customtkinter',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        # Android ADB
        'ppadb',
        'ppadb.client',
        'ppadb.client_async',
        'ppadb.connection',
        'uiautomator2',
        'adbutils',
        *_u2_hidden, *_adb_hidden,
        # Computer Vision / OCR
        'cv2',
        'numpy',
        'numpy.core',
        'numpy.core._multiarray_umath',
        'pytesseract',
        # Network
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.exceptions',
        # System / Security
        'ctypes',
        'ctypes.wintypes',
        'winreg',   # nemu_capture: หา install path ของ MuMu จาก registry
        'atexit',   # nemu_capture: ปล่อย handle ตอนปิดโปรแกรม
        'psutil',
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.default_backend',
        # Standard library (dynamic import ใน protection.py)
        'platform',
        'subprocess',
        'configparser',
        'uuid',
        'hashlib',
        'hmac',
        'base64',
        'multiprocessing',
        'threading',
        'webbrowser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ลบ modules ที่ไม่จำเป็นเพื่อลดขนาด
        'unittest',
        'pydoc',
    ],
    noarchive=False,
    optimize=0,  # ต้องเป็น 0 เพราะ numpy ต้องการ docstrings (add_docstring error)
)

# Pyarmor patch start:

def apply_pyarmor_patch():
    import os

    srcpath = [os.path.abspath('.')]
    obfpath = os.path.abspath('dist_pyarmor')
    pkgname = 'pyarmor_runtime_009939'
    pkgpath = os.path.join(obfpath, pkgname)

    import glob
    extfiles = glob.glob(os.path.join(pkgpath, 'pyarmor_runtime*.pyd')) + \
               glob.glob(os.path.join(pkgpath, 'pyarmor_runtime*.so'))
    if not extfiles:
        raise RuntimeError('no found extension pyarmor_runtime in ' + pkgpath)
    extname = os.path.join(pkgname, os.path.basename(extfiles[0]))

    if hasattr(a.pure, '_code_cache'):
        code_cache = a.pure._code_cache
    else:
        from PyInstaller.config import CONF
        code_cache = CONF['code_cache'].get(id(a.pure))

    srclist = [os.path.normcase(x) for x in srcpath]

    def match_obfuscated_script(orgpath):
        for x in srclist:
            if os.path.normcase(orgpath).startswith(x):
                return os.path.join(obfpath, orgpath[len(x)+1:])

    count = 0
    for i in range(len(a.scripts)):
        x = match_obfuscated_script(a.scripts[i][1])
        if x and os.path.exists(x):
            a.scripts[i] = a.scripts[i][0], x, a.scripts[i][2]
            count += 1
    if count == 0:
        raise RuntimeError('No obfuscated script found in ' + obfpath)

    for i in range(len(a.pure)):
        x = match_obfuscated_script(a.pure[i][1])
        if x and os.path.exists(x):
            code_cache.pop(a.pure[i][0], None)
            a.pure[i] = a.pure[i][0], x, a.pure[i][2]

    a.pure.append((pkgname, os.path.join(pkgpath, '__init__.py'), 'PYMODULE'))
    a.binaries.append((extname, os.path.join(obfpath, extname), 'EXTENSION'))

apply_pyarmor_patch()

# Pyarmor patch end.

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BotLineRanger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # ปิดเนื่องจาก strip ไม่มีใน Windows (ใช้ UPX แทน)
    upx=True,     # Compress ด้วย UPX
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,  # ปิด traceback เพื่อความปลอดภัย
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\image\\home\\BotLineRanger_128.ico'],
)
