# nemu_capture.py
"""จับภาพหน้าจอจาก MuMu Player โดยตรงผ่าน external_renderer_ipc.dll (shared memory)

ใช้แทน DEVICE.screencap() ที่ต้องให้ emulator encode PNG แล้วส่งผ่าน ADB ซึ่งแพงมาก
วัดจริงบนเครื่องนี้ (MuMu 12, 960x540, 40 grab/backend):

    screencap : wall 212.9 ms | CPU host 8.98 ms | CPU emulator 228.9 ms
    nemu      : wall   2.3 ms | CPU host 2.34 ms | CPU emulator   0.8 ms

คือเร็วขึ้น ~92 เท่า และประหยัด CPU รวม ~235 ms ต่อการถ่าย 1 ครั้ง โดย 229 ms ในนั้น
เป็น CPU ที่ emulator เผาไปกับการ encode PNG ซึ่งแย่ง CPU กับการ render เกมเองด้วย
ภาพที่ได้เทียบกับ screencap แล้ว absdiff = 0 ทุก pixel จึงใช้ template ชุดเดิมได้ทั้งหมด

โมดูลนี้ออกแบบให้ "พังแล้วต้องไม่ทำให้บอทตาย" -- create_for_serial() ไม่เคย raise
คืน None เมื่อใช้ไม่ได้ แล้วให้ฝั่งเรียกถอยไปใช้ screencap แบบเดิม
"""
import ctypes
import glob
import json
import os
import subprocess
import time
from ctypes import POINTER, byref, c_int, c_uint

import cv2
import numpy as np

# ปิดหน้าต่าง console ที่จะเด้งขึ้นมาตอนเรียก MuMuManager.exe (ตัว exe build แบบ console=False)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# path ที่พบบ่อย ใช้เมื่อหาใน registry ไม่เจอ
_COMMON_ROOTS = [
    r"C:\Program Files\Netease\MuMuPlayer",
    r"C:\Program Files\Netease\MuMuPlayerGlobal",
    r"C:\Program Files (x86)\Netease\MuMuPlayer",
    r"D:\Program Files\Netease\MuMuPlayer",
]


def _say(log, msg):
    """log() ที่ล้มไม่ได้ -- console บางเครื่องเป็น cp1252/cp874 แล้ว print ไทยจะโยน
    UnicodeEncodeError ซึ่งจะทะลุออกไปล้มบอททั้งตัว ทั้งที่เป็นแค่ข้อความสถานะ
    """
    try:
        log(msg)
    except Exception:
        try:
            log(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def _looks_like_root(path):
    """root ที่ใช้ได้ต้องมีทั้ง dll และ MuMuManager.exe"""
    return bool(path) and os.path.isdir(path) and find_dll(path) and find_manager(path)


def find_dll(root):
    """หา external_renderer_ipc.dll -- เลข version folder ต่างกันตามรุ่นจึงต้อง glob"""
    hits = glob.glob(os.path.join(root, "nx_device", "*", "shell", "sdk",
                                  "external_renderer_ipc.dll"))
    return hits[0] if hits else None


def find_manager(root):
    """หา MuMuManager.exe -- อยู่ใน nx_main (รุ่นใหม่) หรือ shell (รุ่นเก่า)"""
    for sub in ("nx_main", "shell", ""):
        p = os.path.join(root, sub, "MuMuManager.exe") if sub else \
            os.path.join(root, "MuMuManager.exe")
        if os.path.isfile(p):
            return p
    return None


def find_mumu_root():
    """หา install root ของ MuMu จาก env -> registry -> path ที่พบบ่อย คืน None ถ้าไม่เจอ"""
    env = os.environ.get("MUMU_ROOT", "").strip()
    if _looks_like_root(env):
        return env

    try:
        import winreg
        hives = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, base in hives:
            try:
                key = winreg.OpenKey(hive, base)
            except OSError:
                continue
            with key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        name = winreg.EnumKey(key, i)
                        if "mumu" not in name.lower():
                            continue
                        with winreg.OpenKey(key, name) as sub:
                            root = ""
                            try:
                                root = winreg.QueryValueEx(sub, "InstallLocation")[0]
                            except OSError:
                                pass
                            if not _looks_like_root(root):
                                # InstallLocation มักว่าง -- ถอย root จาก uninstall.exe แทน
                                try:
                                    unin = winreg.QueryValueEx(sub, "UninstallString")[0]
                                    root = os.path.dirname(unin.strip().strip('"'))
                                except OSError:
                                    root = ""
                            if _looks_like_root(root):
                                return root
                    except OSError:
                        continue
    except ImportError:
        pass

    for root in _COMMON_ROOTS:
        if _looks_like_root(root):
            return root
    return None


def resolve_index(root, serial):
    """map ADB serial -> instance index ผ่าน MuMuManager.exe

    บอทรู้จัก emulator แค่ในรูป "127.0.0.1:PORT" (ADB.py สแกนพอร์ตมา) แต่ nemu_connect
    ต้องการ instance index สูตร (port-16384)/32 ใช้ได้บางรุ่นเท่านั้น จึงถามจากตัว
    MuMuManager ตรง ๆ ซึ่งคืน JSON ที่มีทั้ง index และ adb_port อยู่ในก้อนเดียวกัน
    """
    mgr = find_manager(root)
    if not mgr:
        return None
    try:
        port = int(str(serial).rsplit(":", 1)[-1])
    except ValueError:
        return None

    out = subprocess.run([mgr, "info", "-v", "all"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace",
                         timeout=20, creationflags=_NO_WINDOW).stdout
    info = json.loads(out)
    if "index" in info:                 # instance เดียวจะคืน object เดี่ยว ไม่ใช่ dict ซ้อน
        info = {info["index"]: info}
    for item in info.values():
        if isinstance(item, dict) and item.get("adb_port") == port:
            return int(item["index"])
    return None


def frame_to_bgr(raw, w, h):
    """RGBA bottom-up bytes -> BGR ndarray (top-down) ฟังก์ชันบริสุทธิ์ ไม่มี I/O

    buffer จาก MuMu เป็น RGBA และกลับหัวแนวตั้ง (origin อยู่มุมล่างซ้ายตามแบบ OpenGL)
    """
    arr = np.frombuffer(raw, np.uint8, count=w * h * 4).reshape(h, w, 4)
    return cv2.cvtColor(np.flipud(arr), cv2.COLOR_RGBA2BGR)


class NemuCapture:
    """ต่อกับ MuMu 1 instance แล้วอ่าน framebuffer ซ้ำ ๆ ผ่าน buffer ก้อนเดิม

    ใช้ผ่าน create_for_serial() เป็นหลัก การสร้างตรง ๆ จะ raise เมื่อต่อไม่ได้
    """

    def __init__(self, root, index, display_id=0):
        self.index = index
        self.display_id = display_id
        self._handle = 0

        dll_path = find_dll(root)
        if not dll_path:
            raise RuntimeError(f"ไม่พบ external_renderer_ipc.dll ใต้ {root}")
        self._dll = ctypes.WinDLL(dll_path)
        self._dll.nemu_connect.argtypes = [ctypes.c_wchar_p, c_int]   # wchar_t* ไม่ใช่ char*
        self._dll.nemu_connect.restype = c_int
        self._dll.nemu_disconnect.argtypes = [c_int]
        self._dll.nemu_disconnect.restype = None
        self._dll.nemu_capture_display.argtypes = [
            c_int, c_uint, c_int, POINTER(c_int), POINTER(c_int), ctypes.c_void_p]
        self._dll.nemu_capture_display.restype = c_int

        self._handle = self._dll.nemu_connect(root, index)
        if not self._handle:
            raise RuntimeError(f"nemu_connect ล้มเหลว (root={root!r}, index={index})")

        # เรียกครั้งแรกด้วย buffer=NULL เพื่อถามขนาด แล้วจอง buffer ก้อนเดียวใช้ตลอด
        w, h = c_int(0), c_int(0)
        ok = self._dll.nemu_capture_display(self._handle, display_id, 0,
                                            byref(w), byref(h), None)
        if ok != 0 or w.value <= 0 or h.value <= 0:
            self.close()
            raise RuntimeError(f"ถามขนาด framebuffer ไม่สำเร็จ (ret={ok})")
        self.width, self.height = w.value, h.value
        self._size = self.width * self.height * 4
        self._buf = (ctypes.c_ubyte * self._size)()

    def grab(self):
        """คืนภาพ BGR ขนาด native ของ framebuffer -- raise เมื่ออ่านไม่ได้"""
        w, h = c_int(self.width), c_int(self.height)
        ret = self._dll.nemu_capture_display(self._handle, self.display_id, self._size,
                                             byref(w), byref(h), self._buf)
        if ret != 0:
            raise RuntimeError(f"nemu_capture_display คืนค่า {ret}")
        return frame_to_bgr(self._buf, self.width, self.height)

    def close(self):
        if getattr(self, "_handle", 0):
            try:
                self._dll.nemu_disconnect(self._handle)
            except Exception:
                pass
            self._handle = 0


def create_for_serial(serial, reference_shape=None, log=print):
    """สร้าง NemuCapture สำหรับ serial นี้ คืน None ถ้าใช้ไม่ได้ -- ไม่เคย raise

    reference_shape คือ .shape ของภาพจาก screencap ถ้าส่งมาจะบังคับให้ขนาดตรงกันเป๊ะ
    ไม่ตรงคืน None ไปเลย เพราะ template กับพิกัดคลิกทั้งหมดอยู่ใน space ของ screencap
    การ resize ให้เองเสี่ยงทำ matchTemplate ตกเกณฑ์แบบเงียบ ๆ ซึ่งดีบักยากมาก
    """
    try:
        root = find_mumu_root()
        if not root:
            _say(log, "[nemu] ไม่พบ MuMu Player ในเครื่อง -> ใช้ screencap")
            return None

        index = resolve_index(root, serial)
        if index is None:
            _say(log, f"[nemu] map {serial} เป็น instance index ไม่ได้ -> ใช้ screencap")
            return None

        cap = NemuCapture(root, index)
        frame = cap.grab()

        if reference_shape is not None and frame.shape != tuple(reference_shape):
            cap.close()
            _say(log, f"[nemu] ขนาดภาพไม่ตรงกับ screencap "
                      f"({frame.shape} vs {tuple(reference_shape)}) "
                      f"-> ใช้ screencap เพื่อไม่ให้ template เพี้ยน")
            return None

        # ไม่เช็คภาพดำตรงนี้ -- บอทเรียก capture ครั้งแรกทันทีหลัง launch เกม ซึ่งจอดำ
        # เป็นเรื่องปกติ การปฏิเสธตอนนั้นทำให้ทั้ง session ตกไปใช้ screencap ฟรี ๆ
        # ส่วนความเสี่ยง "ต่อผิด instance" ถูกกันไปแล้วที่ resolve_index() ซึ่งจับคู่
        # adb_port จาก MuMuManager โดยตรง ไม่ได้เดาจากสูตร
        _say(log, f"[nemu] ใช้ native capture: index={index} ขนาด {cap.width}x{cap.height} "
                  f"({os.path.basename(root)})")
        return cap
    except Exception as e:
        _say(log, f"[nemu] เริ่มต้นไม่สำเร็จ ({e}) -> ใช้ screencap")
        return None


if __name__ == "__main__":
    import sys

    serial = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:16416"
    root = find_mumu_root()
    print(f"root    : {root}")
    print(f"dll     : {find_dll(root) if root else None}")
    print(f"manager : {find_manager(root) if root else None}")
    print(f"index   : {resolve_index(root, serial) if root else None}  (serial={serial})")

    cap = create_for_serial(serial)
    if cap:
        t0 = time.perf_counter()
        for _ in range(30):
            img = cap.grab()
        print(f"grab    : {(time.perf_counter() - t0) / 30 * 1000:.2f} ms/frame  {img.shape}")
        cv2.imwrite("nemu_selftest.png", img)
        print("เขียนภาพทดสอบไว้ที่ nemu_selftest.png")
        cap.close()
