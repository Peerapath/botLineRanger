"""Worker entry แยกต่างหาก - รันโหมด headless (Login/GenID) โดยไม่โหลด GUI (customtkinter) / uiautomator2

รันเป็น subprocess:  python bot_worker.py <deviceSerial> [mode]
  mode = ranger_api_Login (ดีฟอลต์) = relogin จากไฟล์ input | ranger_api_GenID = mint บัญชีใหม่

ทำไมต้องแยกไฟล์: multiprocessing บน Windows ใช้ spawn = child re-import __main__ (main.py)
ซึ่ง main.py นิยาม `class EmulatorManager(ctk.CTk)` ที่ระดับ module -> โหลด customtkinter (16.7MB)
+ botLineRanger เดิมโหลด uiautomator2 (24MB) ทุกโปรเซส -> ~59MB/worker -> 1024 ตัวเกิน RAM
รันเป็น subprocess ของไฟล์นี้แทน: __main__ คือไฟล์นี้ (เบา) import แค่ botLineRanger ที่ทำ
u2/cv2/numpy/main เป็น lazy แล้ว -> ~30-45MB/worker -> รันเป็นพันตัวได้
"""
import os

# จำกัด OpenBLAS/OMP ก่อน import อะไรที่อาจลาก numpy (เผื่อ device flow) - เหมือน main/botLineRanger
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_MAIN_FREE"):
    os.environ.setdefault(_v, "1")

import sys


def run_worker(device, mode="ranger_api_Login"):
    """รันลูป headless ของ 1 worker ตามโหมด (ไม่เขียน log: กลบ stdout/stderr ทิ้ง)

    mode == 'ranger_api_GenID' -> startBotGenID_API_headless (mint บัญชีใหม่ผ่าน /signup/platform)
    mode == 'ranger_api_Stage' -> startBotStage_API_headless (relogin จากไฟล์ แล้วดันด่านผ่าน API)
    อื่น ๆ                     -> startBotLogin_API_headless (relogin จากไฟล์ใน input/)
    """
    try:
        devnull = open(os.devnull, "w")
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        pass
    import botLineRanger
    try:
        if mode == "ranger_api_GenID":
            botLineRanger.startBotGenID_API_headless(device)
        elif mode == "ranger_api_Stage":
            botLineRanger.startBotStage_API_headless(device)
        else:
            botLineRanger.startBotLogin_API_headless(device)
    except Exception:
        pass


def run_login_worker(device):
    """คงชื่อเดิมไว้เผื่อโค้ดอื่นเรียก - เท่ากับ run_worker โหมด Login"""
    run_worker(device, "ranger_api_Login")


if __name__ == "__main__":
    _device = sys.argv[1] if len(sys.argv) > 1 else ""
    _mode = sys.argv[2] if len(sys.argv) > 2 else "ranger_api_Login"
    run_worker(_device, _mode)
