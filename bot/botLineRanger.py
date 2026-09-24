# botLineRanger.py
# จำกัด thread pool ของ OpenBLAS/OMP ก่อน import numpy/cv2 (ทั้งคู่ลิงก์ OpenBLAS)
# สำคัญมากตอนรัน headless หลายร้อย/พันโปรเซส: ดีฟอลต์ OpenBLAS จอง thread = จำนวน core (เช่น 28)
# ต่อทุกโปรเซส -> 1024 โปรเซส x 28 thread = หมื่นกว่า thread + buffer -> OOM
# ("OpenBLAS error: Memory allocation still failed"). งาน headless ไม่ใช้ BLAS เลย 1 thread พอ
import os
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_MAIN_FREE"):
    os.environ.setdefault(_v, "1")

from datetime import datetime
from time import sleep
import time
import configparser
import csv
import traceback
import glob
import shutil
import re
import sys
import html
import json
import random
import difflib
import atexit
import importlib
from bot_version import CURRENT_VERSION   # แทน 'import main as mai' เดิม (เลี่ยง customtkinter ใน worker)

# Windows console/พื้นฐานเป็น cp1252: พอ print ข้อความไทย/emoji (เช่น log [SESSION], ชื่อ ranger,
# ข้อความ error) ลง console จะโยน UnicodeEncodeError ('charmap' codec can't encode characters ...)
# แล้ว worker พังทั้ง session (เห็นใน src/log/genid-sessions.csv เป็น FAIL). บังคับ UTF-8 ที่
# stdout/stderr เหมือนที่ tools/*.py ทุกไฟล์ทำ. guard ไว้เผื่อ stream ถูก redirect เป็น devnull/
# object ที่ไม่มี reconfigure(). ต้องทำก่อนมี print แรกของบอท
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

####################################################### function ########################################################
####################################################### function ########################################################
####################################################### function ########################################################


# DEVICE/U2DEVICE อยู่ที่ None เสมอ (setUp/adb ถูกลบไปแล้ว - Task 11) เหลือไว้เพราะ setUpHeadless()
# และโค้ด headless เดิมยังอ้างชื่อ DEVICE/DEVICESERIAL อยู่ (เช่นตั้งชื่อไฟล์ split-ID)
DEVICESERIAL = ""
DEVICE = None
U2DEVICE = None

########## config ##########
STAGEEND = 150
LEVELTARGET = 3        # โหมด Level3/GenID: เล่น st01 ซ้ำผ่าน API จนเลเวลถึงค่านี้ (config: leveltarget)
CHANGEID = True
AUTOUSEITEM = True
RANGERINTEAM = 5
MAXMINERALCOST = 1300
LOSTCOUNT = 3
GIFTBOX = True
TIMEINTERVAL = 5
BUYFRIEND = "everyTime"
AUTOTEAM = False
CLOSEPOPUP = True
AUTOMODE = "bot"

GACHARANGERGROUP = ""
GACHARANGER = False
RSELCTIONEVENT = 1
RSTOPWHENFOUND = True
RGACHAMODE = "giveItAll"
RGACHACYCLES = 5
RUSERUBY = False
EXCHANGEGACHATICKET = True

ACCEPT7DAY = True
ACCEPTPASS = True
BUYLEONARD9 = True
BUYRUBY = True
BUYTICKET = True
UPDATERBTK = False

GSELECTIONEVENT = 1
GSTOPWHENFOUND = True
GUSE200RUBY = True
GGACHAMODE = "giveItAll"
GGACHACYCLES = 200

########## game ##########
GAMEID = ""
FILENAME = ""
RBTK = ""
RBTKPOSITION= "front"
STAGENUMBER = 0
HIGHERSTAGE = 0
RANGERSCONFIG = {}
LFACCACHE = None            # LF_AC ของ session ปัจจุบัน ล้างทิ้งใน force_stop_LINE_Rangers()
IMPORTEDENCLFAC = None      # _ENC_LF_AC_KEY ของไฟล์ที่ import เข้าเครื่อง = token เก่า ห้ามเอาไปยิง API
HEADLESS = False            # True = โหมด headless แท้: mint LF_AC เองจากไฟล์ ไม่แตะ device/เกม
_HEADLESSCCPOOL = None      # guest cc (relogin.CcPool) mint ครั้งเดียวใช้ทั้งรอบ renew ตอนโดน 401
LASTGACHASTATUS = ""        # ผลกาชารอบล่าสุด ใช้เขียนลง log สรุป session
GEARS = {}

REIMPORTFILE = ""

slotItem1 = (45, 50)
slotItem2 = (115, 50)
slotItem3 = (185,50)
slotItem4 = (255, 50)
slotItem5 = (295, 50)

current_screen = None       # เก็บภาพล่าสุดจาก ADB (BGR)
current_screen_gray = None  # เก็บภาพ grayscale ของ current_screen
_last_capture_time = 0.0    # เวลาที่ capture ล่าสุด (ใช้คำนวณ cooldown)
_template_cache = {}        # cache cv2.imread() templates keyed by path
current_gacha_cycles = 0
current_use_ruby = 0
########## system settings ##########
cooldowncapturescreen = 0.5
timeoutopengame = 60
usenemu = True              # ให้ลองใช้ MuMu native capture ก่อน (False = บังคับใช้ screencap)

########## nemu capture ##########
# _nemu       : NemuCapture เมื่อต่อได้ / None เมื่อกำลังใช้ screencap
# _nemu_next_try : เวลาที่จะลองต่อ nemu ครั้งถัดไป, None = เลิกลองถาวรในโปรเซสนี้
_nemu = None
_nemu_next_try = 0.0
_nemu_black_streak = 0      # นับเฟรมดำติดกัน ใช้จับกรณี nemu ต่อติดแต่ไม่ render จริง
NEMU_RETRY_SEC = 60         # nemu ล้มกลางทาง (เช่น MuMu restart) รอเท่านี้ก่อนลองใหม่
NEMU_BLACK_STREAK = 30      # ดำติดกันเท่านี้เฟรมค่อยเสีย screencap 1 ครั้งไปตรวจสอบ
NEMU_MIN_INTERVAL = 0.05    # เพดานอัตรา capture ตอนใช้ nemu = 20 ครั้ง/วิ (0 = ไม่จำกัด)



class  Color:
    def __init__(self, r, g, b):
        self.r = int(r)
        self.g = int(g)
        self.b = int(b)

    def getR(self) -> float:
        return float(self.r)
    
    def getG(self) -> float:
        return float(self.g)
    
    def getB(self) -> float:
        return float(self.b)

    def setColor(self, r, g, b):
        self.r = int(r)
        self.g = int(g)
        self.b = int(b)

    def __repr__(self):
        return f"Color(r={self.r}, g={self.g}, b={self.b})"

class Location:
    def __init__(self, x: int, y: int):
        self.x = int(x)
        self.y = int(y)

    def getX(self) -> float:
        return float(self.x)

    def getY(self) -> float:
        return float(self.y)

    def setLocation(self, x: int, y: int):
        self.x = int(x)
        self.y = int(y)

    def offset(self, dx: int, dy: int):
        return Location(self.x + dx, self.y + dy)

    def above(self, dy: int):
        return Location(self.x, self.y - dy)

    def below(self, dy: int):
        return Location(self.x, self.y + dy)

    def left(self, dx: int):
        return Location(self.x - dx, self.y)

    def right(self, dx: int):
        return Location(self.x + dx, self.y)

    def __repr__(self):
        return f"Location(x={self.x}, y={self.y})"

class Region:
    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    # ---- Getters ----
    def getX(self): return self.x
    def getY(self): return self.y
    def getW(self): return self.w
    def getH(self): return self.h

    def getTopLeft(self): return Location(self.x, self.y)
    def getTopRight(self): return Location(self.x + self.w, self.y)
    def getBottomLeft(self): return Location(self.x, self.y + self.h)
    def getBottomRight(self): return Location(self.x + self.w, self.y + self.h)
    def getCenter(self): return Location(self.x + self.w // 2, self.y + self.h // 2)
    def getTopCenter(self): return Location(self.x + self.w // 2, self.y)
    def getBottomCenter(self): return Location(self.x + self.w // 2, self.y + self.h)
    def getLeftCenter(self): return Location(self.x, self.y + self.h // 2)
    def getRightCenter(self): return Location(self.x + self.w, self.y + self.h // 2)

    # ---- Setters ----
    def setX(self, number: int): self.x = int(number)
    def setY(self, number: int): self.y = int(number)
    def setW(self, number: int): self.w = int(number)
    def setH(self, number: int): self.h = int(number)

    def __repr__(self):
        return f"Region(x={self.x}, y={self.y}, w={self.w}, h={self.h})"




def setUpHeadless(deviceSerial):
    """เตรียมโหมด headless แท้: โหลด config แล้วตั้ง DEVICESERIAL จาก argument โดยไม่แตะ adb

    ใช้แทน setUp() ตอนรัน headless — flow นี้ไม่เปิดเกม ไม่อ่านโทเค็นจากเครื่อง จึงไม่ต้องมี
    emulator เลย DEVICESERIAL ยังจำเป็นสำหรับตั้งชื่อไฟล์ split-ID ต่อเครื่อง (src/split-ID/<serial>.txt)
    จึงแปลง ':' เป็น '_' ให้ตรงรูปแบบเดิมที่ setUp() ใช้ (DEVICE.serial.replace(":", "_"))
    """
    global DEVICE, DEVICESERIAL, U2DEVICE, HEADLESS, HIGHERSTAGE, RBTK
    HEADLESS = True
    DEVICE = None
    U2DEVICE = None
    HIGHERSTAGE = 0
    RBTK = ""
    DEVICESERIAL = deviceSerial.replace(":", "_")
    print(f"========= Setup Headless v{CURRENT_VERSION} ({DEVICESERIAL}) =========")
    _loadBotConfig()


def _loadBotConfig():
    """โหลดค่าจาก src/config.ini + configRangers.ini + configGears.ini ลง globals

    แยกออกจาก setUp() เพื่อให้ setUpHeadless() เรียกใช้ได้โดยไม่ต้องต่อ device (โหมด headless
    ยังต้องใช้ค่าพวก GACHARANGER/GACHARANGERGROUP/RGACHACYCLES/RANGERSCONFIG ในขั้นกาชา)
    """
    global GACHARANGER, GACHARANGERGROUP, TAP_DURATION, RBTKPOSITION, UPDATERBTK, STAGEEND, LEVELTARGET, AUTOUSEITEM, \
        CHANGEID, AUTOMODE, LOSTCOUNT, GIFTBOX, BUYFRIEND, HIGHERSTAGE, RANGERSCONFIG, GEARS, \
        RANGERINTEAM, MAXMINERALCOST, CLOSEPOPUP, RSELCTIONEVENT, AUTOTEAM, ACCEPTPASS, \
        ACCEPT7DAY, RGACHACYCLES, RGACHAMODE, RSTOPWHENFOUND, TIMEINTERVAL, RUSERUBY, EXCHANGEGACHATICKET, \
        GSELECTIONEVENT, GSTOPWHENFOUND, GUSE200RUBY, GGACHAMODE, GGACHACYCLES, \
        BUYLEONARD9, BUYRUBY, BUYTICKET, cooldowncapturescreen, timeoutopengame, current_gacha_cycles, \
        usenemu, _nemu_next_try

    config = configparser.ConfigParser()
    with open("src\config.ini", "r", encoding="utf-8") as f:
        config.read_file(f)

    STAGEEND = config.getint("settings", "stageend")
    LEVELTARGET = config.getint("settings", "leveltarget", fallback=3)
    CHANGEID = config.getboolean("settings", "changeID")
    AUTOUSEITEM = config.getboolean("settings", "autoUseItem")
    RANGERINTEAM = config.getint("settings", "rangerInTeam")
    MAXMINERALCOST = config.getint("settings", "maxmineralcost")
    LOSTCOUNT = config.getint("settings", "lostCount")
    GIFTBOX = config.getboolean("settings", "giftBox")
    TIMEINTERVAL = config.getfloat("settings", "timeinterval")
    BUYFRIEND = config.get("settings", "buyFriend")
    AUTOTEAM = config.getboolean("settings", "autoteam")
    CLOSEPOPUP = config.getboolean("settings", "closepoup")
    AUTOMODE = config.get("settings", "autoMode")

    GACHARANGERGROUP = config.get("settings", "gacharangergroup")
    GACHARANGER = config.getboolean("settings", "gacharanger")
    RSELCTIONEVENT = config.getint("settings", "rselctionevent")
    RSTOPWHENFOUND = config.getboolean("settings", "rstopwhenfound")
    RUSERUBY = config.getboolean("settings", "ruseruby")
    RGACHAMODE = config.get("settings", "rgachamode")
    RGACHACYCLES = config.getint("settings", "rgachacycles")

    ACCEPT7DAY = config.getboolean("settings", "accept7day")
    ACCEPTPASS = config.getboolean("settings", "acceptpass")
    EXCHANGEGACHATICKET = config.getboolean("settings", "exchangegachatickets")
    BUYLEONARD9 = config.getboolean("settings", "buyleonard9")
    BUYRUBY = config.getboolean("settings", "buyruby")
    BUYTICKET = config.getboolean("settings", "buyticket")
    UPDATERBTK = config.getboolean("settings", "readRBTK")
    RBTKPOSITION = config.get("settings", "rbtkposition")

    GSELECTIONEVENT = config.getint("settings", "gselctionevent")
    GSTOPWHENFOUND = config.getboolean("settings", "gstopwhenfound")
    GUSE200RUBY = config.getboolean("settings", "guse200ruby")
    GGACHAMODE = config.get("settings", "ggachamode")
    GGACHACYCLES = config.getint("settings", "ggachacycles")

    TAP_DURATION = config.getfloat("systemsettings", "tapduration")
    cooldowncapturescreen = config.getfloat("systemsettings", "cooldowncapturescreen")
    timeoutopengame = config.getfloat("systemsettings", "timeoutopengame")

    # fallback=True เพราะโปรเจกต์นี้อ่าน config ตรง ๆ ไม่มีตัว auto-fill key ที่ขาด
    # config.ini ของผู้ใช้เดิมจึงยังไม่มี usenemu
    usenemu = config.getboolean("systemsettings", "usenemu", fallback=True)
    if not usenemu:
        _nemu_next_try = None       # ปิดจาก config -> ไม่ต้องเสียเวลาลองต่อเลย
        log("[nemu] ปิดจาก config (usenemu=False) -> ใช้ screencap")

    current_gacha_cycles = 0

    # strict=False: ทนต่อ key ซ้ำในไฟล์ (เอาค่าท้ายสุด) แทนที่จะ crash ทั้ง worker
    # การเพิ่มเรนเจอร์/เกียร์ผ่าน GUI อาจได้ code ซ้ำ (เช่น u1206e-moon สองชื่อ) ถ้า strict
    # จะโยน DuplicateOptionError ทำให้ setUpHeadless พังตั้งแต่ต้น worker เลยไม่รันสักตัว
    configRanger = configparser.ConfigParser(strict=False)
    configRanger.read("src\configRangers.ini", encoding="utf-8")
    RANGERSCONFIG = dict(configRanger["rangers"])

    configGear = configparser.ConfigParser(strict=False)
    configGear.read("src\configGears.ini", encoding="utf-8")
    GEARS = dict(configGear["gears"])
    

def extract_clean_text(*texts):
    parts = []
    try:
        for text in texts:
            # แยกคำด้วย space
            words = text.split()

            # ถ้ามีแค่ 1 คำ ใช้เลย, ถ้ามีมากกว่า 1 คำ ลบ noise (คำสั้นๆ ที่ยาว <= 1 ตัวอักษร) ออก
            if len(words) >= 1:
                cleaned = [w for w in words if len(w) > 1]
                parts.extend(cleaned if cleaned else words)
        # ต่อข้อความทั้งหมดเข้าด้วยกัน
        return "".join(parts)
    except Exception:
        return "".join(parts)






def fuzzy_match(ocr_text, target_text, threshold=1):
    # ลบช่องว่าง และทำเป็น lower case เพื่อลดความผิดพลาด
    o = re.sub(r"\s+", "", ocr_text).lower()
    t = re.sub(r"\s+", "", target_text).lower()

    ratio = difflib.SequenceMatcher(None, o, t).ratio()
    return ratio >= threshold, ratio

######################################################### logic #########################################################
######################################################### logic #########################################################
######################################################### logic #########################################################










def log(values:object, end="\n", flush=True):
    formatted_datetime = datetime.now().strftime("%H:%M:%S")
    # print(f"{formatted_datetime} {device_serial}: {values}", end=end, flush=flush)
    print(f"{formatted_datetime} {values}", end=end, flush=flush)


def updateFileInExecute(text=""):
    global FILENAME
    if FILENAME == "":
        log("Unable to update file. FILENAME not found.")
        return
    # ใช้ basename เพื่อหา gameId (รองรับ subfolder)
    base_name = os.path.basename(FILENAME)
    sub_dir = os.path.dirname(FILENAME)
    gameId = base_name.replace(".xml", "")
    search_dir = os.path.join("execute", sub_dir) if sub_dir else "execute"
    old_files = glob.glob(os.path.join(search_dir, f"*{gameId}*.xml"))

    for old_path in old_files:
        dirname, old_name = os.path.split(old_path)
        if text != "":
            new_name = f'{text}_{old_name}'
        else:
            new_name = old_name

        FILENAME = os.path.join(sub_dir, new_name) if sub_dir else new_name
        new_path = os.path.join(dirname, new_name)
        os.rename(old_path, new_path)
        log(f"Update File: {new_name}")


def updateFileWithStage(text=""):
    global FILENAME
    if FILENAME == "":
        log("Unable to update file. FILENAME not found.")
        return
    # ใช้ basename เพื่อหา gameId (รองรับ subfolder)
    base_name = os.path.basename(FILENAME)
    sub_dir = os.path.dirname(FILENAME)
    gameId = base_name.replace(".xml", "")
    search_dir = os.path.join("execute", sub_dir) if sub_dir else "execute"
    old_files = glob.glob(os.path.join(search_dir, f"*{gameId}*.xml"))

    for old_path in old_files:
        dirname, old_name = os.path.split(old_path)
        if text != "":
            new_name = f'{text}_{old_name}'
        elif re.search(r'stage\d+', old_name, flags=re.IGNORECASE):
            # ถ้ามีคำว่า stage อยู่แล้ว → แทนที่เลข
            new_name = re.sub(r'stage\d+', f'stage{STAGENUMBER}', old_name, flags=re.IGNORECASE)
        else:
            # ถ้าไม่มี stage ให้เพิ่มไว้หน้าชื่อไฟล์
            new_name = f'stage{STAGENUMBER}_{old_name}'

        FILENAME = os.path.join(sub_dir, new_name) if sub_dir else new_name
        new_path = os.path.join(dirname, new_name)
        os.rename(old_path, new_path)
        log(f"Update File: {new_name}")





def exportFileFromExecuteToBackup(text:str="", newName:str=""):
    """ย้ายไฟล์จาก execute ไป backup คง subfolder เดิม คืน path ปลายทาง

    text    = เติม text_ หน้าชื่อเดิม
    newName = ตั้งชื่อใหม่ทั้งชื่อ (ไม่ต้องใส่ .xml) ใช้กับไฟล์ที่วนกลับมารันซ้ำ ไม่งั้นชื่อจะยาวขึ้นทุกรอบ
              ถ้าชื่อซ้ำ (เช่นสองไฟล์เป็นบัญชีเดียวกัน) จะต่อท้าย _2, _3 แทนการเขียนทับ
    """
    if not FILENAME:
        # path จะกลายเป็นโฟลเดอร์ execute เอง exists ผ่านแต่ไม่ได้ย้ายอะไร เลยเงียบว่าสำเร็จ
        raise FileNotFoundError("No imported file to export (FILENAME is empty)")
    path = os.path.join("execute", FILENAME)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    sub_dir = os.path.dirname(FILENAME)
    base_name = os.path.basename(FILENAME)
    out_dir = os.path.join("backup", sub_dir) if sub_dir else "backup"
    os.makedirs(out_dir, exist_ok=True)

    if newName:
        # os.rename บน Windows ไม่เขียนทับไฟล์ที่มีอยู่ (shutil.move เขียนทับ) ชื่อชนก็ลองเลขถัดไป
        for n in range(1, 1000):
            dest_path = os.path.join(out_dir, f"{newName}.xml" if n == 1 else f"{newName}_{n}.xml")
            try:
                os.rename(path, dest_path)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError(f"Too many files named {newName} in {out_dir}")
        log(f"Export File: {dest_path}")
        return dest_path

    # สร้างชื่อไฟล์ปลายทาง (เพิ่ม text_ หน้า basename แต่คง subfolder)
    dest_name = f"{text}_{base_name}" if text != "" else base_name
    dest_path = os.path.join(out_dir, dest_name)
    log(f"Export File: {dest_path}")
    shutil.move(path, dest_path)
    return dest_path



def exportFileFromExecuteToInput(text:str=""):
    path = os.path.join("execute", FILENAME)

    # สร้างชื่อไฟล์ปลายทาง (เพิ่ม text_ หน้า basename แต่คง subfolder)
    sub_dir = os.path.dirname(FILENAME)
    base_name = os.path.basename(FILENAME)
    if text != "":
        dest_name = f"{text}_{base_name}"
    else:
        dest_name = base_name

    dest_path = os.path.join("input", sub_dir, dest_name) if sub_dir else os.path.join("input", dest_name)
    log(f"Export File: {dest_path}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    if os.path.isfile(path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(path, dest_path)


def exportFileFromExecuteToOutput(text:str="", newName:str=""):
    """ย้ายไฟล์จาก execute ไป output คง subfolder เดิม คืน path ปลายทาง

    text    = เติม text_ หน้าชื่อเดิม
    newName = ตั้งชื่อใหม่ทั้งชื่อ (ไม่ต้องใส่ .xml) ใช้กับไฟล์ที่วนกลับมารันซ้ำ ไม่งั้นชื่อจะยาวขึ้นทุกรอบ
              ถ้าชื่อซ้ำ (เช่นสองไฟล์เป็นบัญชีเดียวกัน) จะต่อท้าย _2, _3 แทนการเขียนทับ
    """
    if not FILENAME:
        # path จะกลายเป็นโฟลเดอร์ execute เอง exists ผ่านแต่ไม่ได้ย้ายอะไร เลยเงียบว่าสำเร็จ
        raise FileNotFoundError("No imported file to export (FILENAME is empty)")
    path = os.path.join("execute", FILENAME)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    sub_dir = os.path.dirname(FILENAME)
    base_name = os.path.basename(FILENAME)
    out_dir = os.path.join("output", sub_dir) if sub_dir else "output"
    os.makedirs(out_dir, exist_ok=True)

    if newName:
        # os.rename บน Windows ไม่เขียนทับไฟล์ที่มีอยู่ (shutil.move เขียนทับ) ชื่อชนก็ลองเลขถัดไป
        for n in range(1, 1000):
            dest_path = os.path.join(out_dir, f"{newName}.xml" if n == 1 else f"{newName}_{n}.xml")
            try:
                os.rename(path, dest_path)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError(f"Too many files named {newName} in {out_dir}")
        log(f"Export File: {dest_path}")
        return dest_path

    # สร้างชื่อไฟล์ปลายทาง (เพิ่ม text_ หน้า basename แต่คง subfolder)
    dest_name = f"{text}_{base_name}" if text != "" else base_name
    dest_path = os.path.join(out_dir, dest_name)
    log(f"Export File: {dest_path}")
    shutil.move(path, dest_path)
    return dest_path


def removeFileInExecute():
    """ลบไฟล์ที่ import เข้ามาใน execute ทิ้งไปเลย (ไม่ย้ายไปไหน)"""
    if not FILENAME:
        raise FileNotFoundError("No imported file to remove (FILENAME is empty)")
    path = os.path.join("execute", FILENAME)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    log(f"Remove File: {path}")
    os.remove(path)
    return f"Remove File: {path}"


def exportFileFromExecuteToLoginFailed():
    path = os.path.join("execute", FILENAME)
    dest_path = os.path.join("login failed", FILENAME)
    log(f"Export File: {dest_path}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    if os.path.isfile(path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(path, dest_path)


def reImportFileInExecute():
    global REIMPORTFILE
    if FILENAME == "":
        log(f"Not Found File ID")
        return 0

    path = os.path.join(f"execute", FILENAME)
    REIMPORTFILE = FILENAME
    log(f"Re Import File: {path}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    if HEADLESS:
        return   # headless: ไฟล์อยู่ใน execute อยู่แล้ว ไม่ต้อง push ลง device (getLFAC จะ relogin เอง)

    # push ไฟล์ไปยัง tmp ก่อน
    tmp_path = "/data/local/tmp/_LINE_COCOS_PREF_KEY.xml"
    DEVICE.push(path, tmp_path)

    # ตั้ง permission rw-rw-rw- (666)
    DEVICE.shell(f"su -c 'chmod 666 {tmp_path}'")

    # ลบไฟล์เดิมถ้ามี
    DEVICE.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")

    # copy ไฟล์จาก tmp กลับไป shared_prefs
    DEVICE.shell(f"su -c 'cp {tmp_path} /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")

    # ลบไฟล์ tmp ทิ้ง
    DEVICE.shell(f"su -c 'rm {tmp_path}'")



def _claimInputFile(rel_path):
    """ย้าย input/<rel_path> ไป execute/ เป็นการจองไฟล์ คืน True ถ้าเครื่องนี้ได้ไฟล์ไป

    ทุก emulator ใช้โฟลเดอร์ input ร่วมกัน ถ้าเช็ค isfile แล้วค่อย push/move ทีหลัง
    สองเครื่องจะหยิบไฟล์เดียวกันได้ (เคยเกิด: 70824fa8 ถูกสองเครื่องล๊อกอินพร้อมกัน
    เครื่องหนึ่งโดน 401 แล้ว export ไฟล์เปล่า)

    ใช้ os.replace ตรงๆ เป็นตัวจองไม่ได้ บน Windows มัน rename ผ่าน handle ถ้าอีก
    process เปิด handle ไว้ก่อนเราย้าย มันก็ย้ายซ้ำไปชื่อเดิมได้ "สำเร็จ" ทั้งคู่
    จึงจองด้วยไฟล์ .lock ที่สร้างแบบ O_EXCL (atomic จริง) ใครสร้างได้คนนั้นได้ย้าย
    lock อยู่ใน src/split-ID ถ้าบอทตายกลางทาง note_file_in_folder จะล้างให้ตอนแบ่งไฟล์รอบใหม่
    """
    src = os.path.join("input", rel_path)
    dst = os.path.join("execute", rel_path)
    lockName = rel_path.replace(os.sep, "__").replace("/", "__") + ".lock"
    lockPath = os.path.join("src", "split-ID", lockName)
    for _ in range(40):
        try:
            os.close(os.open(lockPath, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            return False   # เครื่องอื่นกำลังย้ายไฟล์นี้อยู่
        except PermissionError:
            time.sleep(0.05)   # Windows: lock ของคนก่อนกำลังถูกลบ (delete pending) รอแล้วลองใหม่
    else:
        return False
    try:
        os.makedirs(os.path.dirname(dst) or "execute", exist_ok=True)
        shutil.move(src, dst)
        return True
    except OSError:
        return False   # ย้ายไปแล้วโดยเครื่องที่ถือ lock ก่อนหน้าเรา
    finally:
        try:
            os.remove(lockPath)
        except OSError:
            pass


def _claimAccountThisRun(accountId):
    """คืน True ถ้า session นี้เป็นคนแรกของรอบที่ได้ทำบัญชีนี้

    input มีหลายไฟล์ที่เป็นบัญชีเดียวกันได้ (เคยเกิด: a0bfb087 สองไฟล์ สุ่มกาชาไป 10 ครั้ง
    ออก backup สองไฟล์) ชื่อไฟล์บอกไม่ได้เสมอว่าเป็นบัญชีไหน จึงเช็คจาก GAME_ID หลังล๊อกอิน
    marker อยู่ใน src/split-ID ซึ่ง note_file_in_folder ล้างทุกครั้งที่กด Start จึงมีผลแค่รอบเดียว
    """
    if not accountId:
        return True   # ระบุบัญชีไม่ได้ ก็ทำตามปกติ ดีกว่าข้ามไปเฉยๆ
    markerPath = os.path.join("src", "split-ID", f"{accountId}.account")
    for _ in range(40):
        try:
            os.close(os.open(markerPath, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            return False
        except PermissionError:
            time.sleep(0.05)   # Windows: marker กำลังถูกลบ (delete pending) รอแล้วลองใหม่
    return False


def _releaseAccountThisRun(accountId):
    """คืนสิทธิ์บัญชี ใช้ตอน session ที่จองไว้ไม่ได้สุ่มกาชาจริง ไฟล์ซ้ำอีกไฟล์จะได้ทำแทน"""
    if not accountId:
        return
    try:
        os.remove(os.path.join("src", "split-ID", f"{accountId}.account"))
    except OSError:
        pass


def importFileFromInputToExecute():
    """หยิบไฟล์ถัดไปของเครื่องนี้ ย้ายไป execute แล้ว push ลงเครื่อง

    คืนชื่อไฟล์ (relative path) ถ้าสำเร็จ หรือ 0 ถ้าไม่มีไฟล์เหลือ ซึ่ง FILENAME จะเป็น ""
    """
    global FILENAME, IMPORTEDENCLFAC
    FILENAME = ""   # กันค่าจากรอบก่อนค้าง แล้วไป export/เปิดเกมด้วยไฟล์เก่า

    # อ่านไฟล์ split-ID ที่ตรงกับ device
    split_id_file = os.path.join("src", "split-ID", f"{DEVICESERIAL}.txt")
    if not os.path.exists(split_id_file):
        log(f"Not Found split-ID file: {split_id_file}")
        return 0

    # อ่านทุกบรรทัดจากไฟล์ split-ID
    with open(split_id_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    claimed = ""
    if lines:
        # วนลูปหาไฟล์ที่มีอยู่จริงใน input
        while lines and not claimed:
            # ลบบรรทัดบนสุดไม่ว่าจะเจอหรือไม่
            target_rel_path = lines.pop(0).strip()
            if not target_rel_path:
                continue

            # ลองใช้ relative path ตรงๆ ก่อน (รองรับ subfolder)
            rel_path = target_rel_path if os.path.isfile(os.path.join("input", target_rel_path)) else ""

            if not rel_path:
                # fallback: ค้นหาด้วยชื่อไฟล์อย่างเดียว (กรณี split-ID เป็นชื่อไฟล์เฉยๆ)
                target_basename = os.path.basename(target_rel_path)
                for root, dirs, files in os.walk("input"):
                    if target_basename in files:
                        rel_path = os.path.relpath(os.path.join(root, target_basename), "input")
                        break

            if rel_path and _claimInputFile(rel_path):
                claimed = rel_path
            else:
                # ไม่เจอไฟล์ (หรือเครื่องอื่นหยิบไปแล้ว) บันทึก log แล้วค้นหาต่อ
                log(f"⚠️ Not Found File ID: {target_rel_path} - Skipping...")

        # อัปเดตไฟล์ split-ID ด้วยรายการที่เหลือ
        with open(split_id_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
    else:
        log(f"No more files in split-ID: {split_id_file}")

    if not claimed:
        # split-ID หมดแล้ว ช่วยเก็บไฟล์ที่ยังค้างใน input จองแบบ atomic กันชนกับเครื่องอื่น
        import random
        leftovers = []
        for root, dirs, files in os.walk("input"):
            for file in files:
                if file.endswith(".xml"):
                    leftovers.append(os.path.relpath(os.path.join(root, file), "input"))
        random.shuffle(leftovers)
        for rel_path in leftovers:
            if _claimInputFile(rel_path):
                claimed = rel_path
                break

    if not claimed:
        log(f"No valid files remaining in split-ID")
        return 0

    FILENAME = claimed
    file_path = os.path.join("execute", FILENAME)
    log(f"Import File: {os.path.join('input', FILENAME)}")

    # ไฟล์ใน input คือ _LINE_COCOS_PREF_KEY.xml ทั้งดุ้น มี _ENC_LF_AC_KEY ของ session
    # ตอน export ติดมาด้วยเสมอ พอ push ทับลงเครื่อง getLFAC() จะอ่านเจอทันทีตั้งแต่ยัง
    # ไม่ทันล๊อกอิน แล้วนึกว่าเป็น token สด ยิง API ไปได้ 401 stale token
    # จำค่าไว้เป็นเส้นฐาน getLFAC() จะได้รอจนกว่าเกมจะเขียนค่าใหม่ทับจริง ๆ
    with open(file_path, encoding="utf-8", errors="replace") as importedPref:
        IMPORTEDENCLFAC = _prefValue(importedPref.read(), "_ENC_LF_AC_KEY")

    if not HEADLESS:
        # push ไฟล์ไปยัง tmp ก่อน
        tmp_path = "/data/local/tmp/_LINE_COCOS_PREF_KEY.xml"
        DEVICE.push(file_path, tmp_path)

        # ตั้ง permission rw-rw-rw- (666)
        DEVICE.shell(f"su -c 'chmod 666 {tmp_path}'")

        # ลบไฟล์เดิมถ้ามี
        DEVICE.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")

        # copy ไฟล์จาก tmp กลับไป shared_prefs
        DEVICE.shell(f"su -c 'cp {tmp_path} /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")

        # ลบไฟล์ tmp ทิ้ง
        DEVICE.shell(f"su -c 'rm {tmp_path}'")

    return FILENAME


def in_current_file():
    # ตรวจสอบว่ายังมีไฟล์ .xml ในโฟลเดอร์ input หรือไม่ (รวมโฟลเดอร์ย่อย)
    import random

    input_folder = "input"
    xml_files = []
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            if file.endswith(".xml"):
                # เก็บ relative path จาก input/
                rel_path = os.path.relpath(os.path.join(root, file), input_folder)
                xml_files.append(rel_path)

    if xml_files:
        # สุ่มเลือกไฟล์ .xml หนึ่งไฟล์
        random_xml_file = random.choice(xml_files)
        log(f"Found {len(xml_files)} XML files in input folder, selected: {random_xml_file}")
        return random_xml_file

    # อ่านไฟล์ split-ID ที่ตรงกับ device
    split_id_file = os.path.join("src", "split-ID", f"{DEVICESERIAL}.txt")
    if not os.path.exists(split_id_file):
        log(f"Not Found split-ID file: {split_id_file}")
        return ""

    # อ่านบรรทัดบนสุดจากไฟล์ split-ID
    with open(split_id_file, "r", encoding="utf-8") as f:
        target_filename = f.readline().strip()

    if not target_filename:
        log(f"No more files in split-ID: {split_id_file}")
        return ""
    return target_filename

def removeAllFiles(keep_files=[], showLog=False):
    global IMPORTEDENCLFAC
    if "_LINE_COCOS_PREF_KEY.xml" not in keep_files:
        IMPORTEDENCLFAC = None   # prefs โดนล้าง ไม่เหลือ token เก่าให้ต้องกันแล้ว
    try:
        log("Removing files in shared_prefs ...")

        # ดึงรายการไฟล์ทั้งหมดใน shared_prefs
        result = DEVICE.shell("su -c 'ls /data/data/com.linecorp.LGRGS/shared_prefs'")
        files = result.strip().splitlines()

        if not files:
            log("No files found in shared_prefs.")
            return

        for f in files:
            if f in keep_files:
                log(f"Keep file: {f}")
                continue

            # ลบไฟล์ที่ไม่ได้อยู่ใน keep_files
            DEVICE.shell(f"su -c 'rm -f /data/data/com.linecorp.LGRGS/shared_prefs/{f}'")
            if showLog:
                log(f"Removed file: {f}")


        log("Remove process completed.")

    except Exception as e:
        print("========= Error =========")
        log(f"Exception in removeAllFiles:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")



















































































    






















######################################################### game api #########################################################
######################################################### game api #########################################################
######################################################### game api #########################################################

# เครื่องมือ API อยู่ที่ ../tools (rangers_api / rewards / gacha / device_session)
# ยิงตรงไปที่ rangers-api.line-apps.com ด้วย LF_AC ที่อ่านจาก shared_prefs บนเครื่อง
# ไม่ต้องใช้ proxy และไม่ต้องเปิดเกมค้างไว้ ดู tools/device_session.py สำหรับที่มาของอัลกอริทึม
#
# ราก path ของ tools/ และ roster/: เมื่อ frozen (PyInstaller) โมดูลถูกฝังใน _internal/_MEIPASS
# แต่ build.bat วาง tools/ และเขียน roster/ ไว้ข้าง exe จึงต้องอิง sys.executable ไม่ใช่ __file__
if getattr(sys, "frozen", False):
    _APP_ROOT = os.path.dirname(sys.executable)
else:
    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLSDIR = os.path.join(_APP_ROOT, "tools")

# {unitCode: {"grade": ..., "summonEnergy": ...}} - ข้อมูลกลางของเกม ไม่ใช่ของบัญชีใคร
# ตัวเดียวกันคนละบัญชีค่าเท่ากันเสมอ จึงไม่ต้องล้างตอนสลับ ID (ต่างจาก LFACCACHE)
# เก็บลงไฟล์ด้วยเพราะการอ่านสเปกต้องเอาตัวไปวางในทีมทีละ 5 (ดู apiUnitSpecs) บัญชี 227 ตัว
# ใช้เวลาเกือบ 2 นาที ถ้าไม่เก็บไว้ข้ามโปรเซส ทุกครั้งที่เปิดบอทใหม่จะต้องไล่วางใหม่หมด
UNITSPECCACHE = {}
UNITSPECPATH = os.path.join(_APP_ROOT, "roster", "unit_specs.json")


UNITSPECLOADED = False


def _loadUnitSpecs():
    """โหลด cache สเปกจากไฟล์ครั้งเดียวตอนใช้ครั้งแรก ไฟล์เสีย/ไม่มี = เริ่มจากว่าง ห้าม raise

    สเปกเป็นแค่ตัวช่วยจัดอันดับ ไม่มีก็แค่ต้องไปอ่านใหม่ ไม่คุ้มที่จะทำให้บอททั้งตัวล้ม
    กันอ่านซ้ำด้วย flag ไม่ใช่ "cache ว่าง = ยังไม่ได้โหลด" เพราะรอบแรกสุดไฟล์ยังไม่มี
    จะกลายเป็นเตือนเรื่องเดิมทุกครั้งที่เรียก
    """
    global UNITSPECLOADED
    if UNITSPECLOADED:
        return UNITSPECCACHE
    UNITSPECLOADED = True
    try:
        with open(UNITSPECPATH, encoding="utf-8") as f:
            UNITSPECCACHE.update(json.load(f))
    except Exception as e:
        log(f"unit spec cache: เริ่มจากว่าง ({e})")
    return UNITSPECCACHE


def _saveUnitSpecs():
    """เขียน cache กลับลงไฟล์ เขียนไม่ได้ก็แค่เสียเวลาอ่านใหม่รอบหน้า ไม่ใช่เรื่องคอขาดบาดตาย"""
    try:
        os.makedirs(os.path.dirname(UNITSPECPATH), exist_ok=True)
        with open(UNITSPECPATH, "w", encoding="utf-8") as f:
            json.dump(UNITSPECCACHE, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:
        log(f"unit spec cache: เซฟไม่ได้ ({e})")


def _importApiTools():
    """import โมดูลใน ../tools แบบ lazy บอทเดิมจะได้รันได้ต่อแม้ไม่มีโฟลเดอร์ tools"""
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import device_session
    import rewards
    import gacha
    return device_session, rewards, gacha


def _apiCall(function, *args, **kwargs):
    """เรียกฟังก์ชันฝั่ง tools/ แล้วแปลง SystemExit เป็น Exception ธรรมดา

    tools/ เขียนมาเป็น CLI เวลา token ตายหรือ adb หาไม่เจอมันจะ raise SystemExit
    ซึ่งไม่ได้สืบทอดจาก Exception บอทจะ catch ไม่ติดแล้วดับทั้งโปรเซส
    """
    try:
        return function(*args, **kwargs)
    except SystemExit as e:
        raise Exception(f"api: {e}")


LGRGSPREF = "/data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml"


def _prefValue(xml: str, key: str):
    match = re.search(r'name="%s">(.*?)</string>' % re.escape(key), xml, re.S)
    return html.unescape(match.group(1)).strip() if match else None




def getLFACHeadless():
    """โหมด headless: mint LF_AC สดจากไฟล์ execute/FILENAME ผ่าน /v12.3/login โดยไม่แตะ device/เกม

    ระบุตัวผู้เล่นจากโทเค็นเก่าที่ฝังในไฟล์ (guestCookie) + cc ของ guest ที่ mint จาก API แล้ว
    ขอ LF_AC ใหม่กลับมา จากนั้น:
      - cache ลง LFACCACHE (ทุก API ที่วิ่งผ่าน getLFAC จึงทำงานต่อได้ทันที)
      - ตั้ง GAMEID จาก rsn ที่ /login คืนมา (getGameID โหมด headless อ่านจากตรงนี้)
      - เขียนโทเค็นสดกลับลง execute/FILENAME เพื่อให้ไฟล์ที่ export ออกมามีโทเค็นใช้งานได้จริง
    cc mint ครั้งเดียวใช้ทั้งรอบ (_HEADLESSCCPOOL) renew เมื่อโดน 401 ตรรกะเดียวกับ tools/relogin.py
    """
    global LFACCACHE, GAMEID, _HEADLESSCCPOOL
    if LFACCACHE:
        return LFACCACHE
    if not FILENAME:
        raise Exception("headless: ยังไม่มีไฟล์ที่ import (FILENAME ว่าง)")

    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import relogin
    from device_session import decrypt_lfac

    file_path = os.path.join("execute", FILENAME)
    acct = relogin.read_account(file_path)
    guestCookie = decrypt_lfac(acct["udid"], acct["enc"])

    if _HEADLESSCCPOOL is None:
        _HEADLESSCCPOOL = relogin.CcPool()   # mint guest cc ตัวแรก (ยิง /auth ครั้งเดียวต่อรอบ)
    cc = _HEADLESSCCPOOL.get()
    status, result, lfAc = relogin.login(cc, acct["udid"], guestCookie, acct["nation"], acct["language"])
    if status == 401 and not result:
        cc = _HEADLESSCCPOOL.renew(cc)       # cc อาจหมดอายุ ลองสร้างใหม่แล้วยิงซ้ำครั้งเดียว
        status, result, lfAc = relogin.login(cc, acct["udid"], guestCookie, acct["nation"], acct["language"])
    if not result or not lfAc:
        raise Exception(
            f"headless relogin ล้มเหลว (HTTP {status}) - ไฟล์นี้ล๊อกอินไม่ผ่าน "
            f"(บัญชีอาจถูกแบน/ไฟล์เสีย หรือเซิร์ฟเวอร์ปิดปรับปรุง)")

    _HEADLESSCCPOOL.mark_proven()
    # เขียนโทเค็นสดกลับลงไฟล์ (แทนที่เฉพาะค่า _ENC_LF_AC_KEY คงไบต์อื่นไว้) ไฟล์ที่ export จะใช้ได้จริง
    try:
        relogin.atomic_write(file_path, relogin.replace_enc(acct["text"], acct["udid"], lfAc))
    except Exception as e:
        log(f"headless: เขียนโทเค็นกลับไฟล์ไม่ได้ (ยังส่ง API ต่อได้): {e}")

    LFACCACHE = "LF_AC=" + lfAc
    GAMEID = result.get("rsn") or GAMEID
    log(f"headless LF_AC ready (rsn={GAMEID}, lv={result.get('level')})")
    return LFACCACHE


def getLFACFromFile(rel_path=""):
    """คืน cookie 'LF_AC=...' ถอดจากไฟล์ _LINE_COCOS_PREF_KEY.xml ใน input โดยไม่แตะเครื่อง

    rel_path คือ path relative กับ input (รองรับ subfolder) ไม่ส่งมา = หยิบ .xml ไฟล์แรกที่เจอ
    token ในไฟล์คือของ session ตอน export ถ้าเกมถูกเปิดใหม่หลังจากนั้นแล้วจะตาย (401)
    จึงไม่เก็บลง LFACCACHE กันไปปนกับ token สดของ getLFAC()
    """
    if not rel_path:
        for root, dirs, files in os.walk("input"):
            xmlFiles = sorted(file for file in files if file.endswith(".xml"))
            if xmlFiles:
                rel_path = os.path.relpath(os.path.join(root, xmlFiles[0]), "input")
                break
        else:
            raise Exception("no .xml file in input")

    file_path = os.path.join("input", rel_path)
    with open(file_path, encoding="utf-8", errors="replace") as prefFile:
        xml = prefFile.read()
    deviceUuid = _prefValue(xml, "_DEVICE_UUID_KEY")
    encLFAC = _prefValue(xml, "_ENC_LF_AC_KEY")
    if not deviceUuid or not encLFAC:
        raise Exception(
            f"{file_path}: ไม่มี {'_DEVICE_UUID_KEY' if not deviceUuid else '_ENC_LF_AC_KEY'} "
            f"- ไฟล์นี้ยังไม่เคยล๊อกอินเข้าเกม")

    device_session, _rewards, _gacha = _importApiTools()
    return "LF_AC=" + device_session.decrypt_lfac(deviceUuid, encLFAC)






def apiAcceptAllRewards():
    """รับของแจกทั้งหมดผ่าน API

    กวาดครบทุกระบบที่เกมแจกของ: popup ตอนล๊อกอิน (Maintenance / Surprise Login),
    กล่องของขวัญ, อีเวนต์ 7 วัน, เควสรายวัน, มิชชั่น, แพ็กเกจเข้าเกม และ Rangers Pass
    ของส่วนใหญ่ตกลงกล่องของขวัญก่อน claim_all() จึงกวาดซ้ำจนไม่เหลือ
    """
    _device_session, rewards, _gacha = _importApiTools()
    cookie = getLFAC()
    player = _apiCall(rewards.check_session, cookie)
    log(f"API account rsn={player.get('rsn')} level={player.get('level')}")
    total = _apiCall(rewards.claim_all, cookie, confirm=True)
    log(f"API accept all rewards: claimed {total}")
    return total


def stageCodeOf(stage):
    """แปลงเลขด่านเป็นรหัส stageCode ของ API เช่น 2 -> 'st02', 151 -> 'st151'

    รับรหัสที่เป็น string อยู่แล้ว (ขึ้นต้น st) ส่งผ่านตรง ๆ จะเรียกด้วยเลขหรือรหัสก็ได้
    %02d เติมศูนย์ให้อย่างน้อย 2 หลัก ด่าน 3 หลักขึ้นไปไม่โดนตัด (st151 ก็ได้ st151)
    """
    if isinstance(stage, str):
        return stage if stage.startswith("st") else "st" + stage
    return "st%02d" % int(stage)


def apiEnterStage(stage, teamType="team1", cancel=True):
    """เข้าด่านผ่าน API เพื่ออ่านบริบทการรบ คืน dict (enterable, enemyTowerHp, teamUnits, ...)

    body ถอดจาก libgame.so (ตัวสร้างที่ 0xb6c6a0) ครบ 8 ฟิลด์ teamType เป็นชื่อ "กลุ่มทีม"
    ('team1' สำหรับด่านปกติ ดู [[lgrgs-team-save-api]]) ไม่ใช่ชนิดทีม ต้องส่งไม่งั้นได้ 500

    ⚠️ enter เปิด battle session จริง (ได้ battleSn) ไม่ใช่ read เฉย ๆ — แต่ทดสอบกับเซิร์ฟเวอร์
    แล้วว่า (ก) ไม่กิน heart จนกว่าจะ save สำเร็จ (ข) เปิดซ้อนกันได้ ไม่ชนกับ enter ของ UI
    default cancel=True จึงยิง /stage/cancel/{battleSn}/{stageCode} ปิด session ทันทีหลังอ่าน
    ค่า ไม่ให้ค้างบนเซิร์ฟเวอร์ (ปิดไม่ได้ก็ไม่เป็นไร session หมดอายุเอง ไม่มี heart ค้าง)

    ฟังก์ชันนี้ "อ่านบริบท/เช็คก่อนเล่น" เท่านั้น — ตัวการรบจริงต้องเล่นผ่าน UI
    (playMainStageAtNumber) เพราะ save ต้องมี battle log ที่เซิร์ฟเวอร์เอาไปจำลองซ้ำเพื่อ
    กันโกง ปลอมไม่ได้ (มี rsaKeyBase ต่อการรบ ดู [[lgrgs-stage-battle-api]])

    enterable=False เมื่อ enter ไม่ผ่าน (เช่น heart หมด/ด่านยังไม่ปลด) ดูเหตุผลใน reason
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    code = stageCodeOf(stage)
    cookie = getLFAC()
    body = {
        "stageCode": code, "itemCodes": [], "friendUid": "", "mercenaryUid": "",
        "guildMemberUid": "", "mercenaryLevel": 0, "multiplePlayCount": 1, "teamType": teamType,
    }
    status, data = _apiCall(rangers_api.call, cookie, "/stage/enter/%s" % code, "POST", body)
    if status != 200 or not isinstance(data, dict) or "result" not in data:
        return {"enterable": False, "stageCode": code, "battleSn": None,
                "reason": f"enter failed (HTTP {status}): {str(data)[:140]}"}

    r = data["result"]
    battleSn = r.get("battleSn")
    if cancel and battleSn is not None:
        try:
            _apiCall(rangers_api.call, cookie,
                     "/stage/cancel/%s/%s" % (battleSn, code), "POST", {})
        except Exception as e:
            log(f"apiEnterStage: cancel ไม่สำเร็จ (ปล่อยหมดอายุเอง): {e}")

    return {
        "enterable": bool(r.get("isEnterable", True)),
        "stageCode": code,
        "battleSn": battleSn,
        "enemyTowerHp": r.get("enemyTowerHp"),
        "needEnergy": r.get("needEnergy"),
        "maxEnergy": r.get("maxEnergy"),
        "machine": r.get("machine"),
        "battleItems": [it.get("itemCode") for it in (r.get("battleGameItem") or [])],
        "teamUnits": [u.get("unitCode") for u in ((r.get("playerUnitTeams") or {}).get("1") or [])],
        "reason": "",
    }


# reinforceType (ชื่อที่ส่งเข้า API) -> ชื่อ field เลเวลใน playerUpgradeLevelStatus
# ถอดชื่อ enum จาก libgame.so แล้วยืนยันกับเซิร์ฟเวอร์จริง (ส่ง level=0 ได้ 102010=ชื่อถูก,
# 500=ชื่อผิด) ชื่อ enum ไม่ตรงกับชื่อ field เป๊ะ ๆ (energyLimitLevel <-> ENERGY_MAX_LIMIT)
# ตัวที่ยังไม่ได้ยืนยัน live (UNIT_*/TOWER_RESIST) ใส่ไว้ตาม string ในไบนารี ถ้า type ผิดจะ
# ได้ 500 แล้วฟังก์ชันโยน error ออกเอง ไม่เงียบ
MACHINE_UPGRADE_TYPES = {
    "ENERGY_MAX_LIMIT": "energyLimitLevel",        # UI "max limit" (พลังงานสูงสุด) - คิด coin
    "ENERGY_PRODUCTION": "energyProductionLevel",  # UI "production rate" (อัตราผลิต) - คิด coin
    "MACHINE_ATTACK": "machineAttackLevel",
    "MACHINE_ATTACK_SCOPE": "machineAttackScopeLevel",
    "MACHINE_CHARGE": "machineChargeSpeedLevel",
    "MACHINE_HP": "machineHpLevel",
    "ACQUIRE_ENERGY": "acquireEnergyLevel",
    "UNIT_HP": "unitHpLevel",
    "UNIT_ATTACK": "unitAttackLevel",
    "TOWER_RESIST": "towerResistRateLevel",
}


def apiUpgradeStatus():
    """คืนระดับอัปเกรดปัจจุบันทั้งหมด (dict ชื่อ field -> level) จาก /player/upgrade/status"""
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    status, data = _apiCall(rangers_api.call, getLFAC(), "/player/upgrade/status")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiUpgradeStatus failed (HTTP {status}): {str(data)[:200]}")
    return (data.get("result") or {}).get("playerUpgradeLevelStatus") or {}


def _apiBalance(cookie):
    """อ่านยอด coin/gem/crystal ปัจจุบัน ไว้วัด delta หลังอัปเกรด (คนละแหล่งแล้วแต่ type)"""
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api
    _s, d = _apiCall(rangers_api.call, cookie, "/home")
    p = (d.get("result") or {}).get("player") or {}
    return {"coin": (p.get("coin") or {}).get("total", 0), "gem": p.get("gem", 0),
            "crystal": dict(p.get("crystal") or {})}


def _balanceDelta(before, after):
    """ผลต่างที่ใช้ไป (before - after) เฉพาะตัวที่ลด แสดงเป็น dict สั้น ๆ"""
    spent = {}
    if before["coin"] - after["coin"]:
        spent["coin"] = before["coin"] - after["coin"]
    if before["gem"] - after["gem"]:
        spent["gem"] = before["gem"] - after["gem"]
    for k in before["crystal"]:
        diff = before["crystal"].get(k, 0) - after["crystal"].get(k, 0)
        if diff:
            spent[k] = diff
    return spent


def apiUpgradeMachine(reinforceType, target=None, steps=1, toMax=False, confirm=False):
    """อัปเกรดค่าหอ/machine ผ่าน API หลักการเดียวกับ upgradeCrystal() แต่ยิง API ตรง

    body ถอดจาก libgame.so (ตัวสร้าง 0xe5db90): POST /player/upgrade/
        {"reinforceType": "<ENUM>", "reinforceLevel": <target>}
    reinforceLevel = "เลเวลปลายทาง" ที่อยากไปถึง ต้อง > เลเวลปัจจุบัน เซิร์ฟเวอร์คิดค่าใช้จ่าย
    สะสมจาก current+1 ถึง target ในครั้งเดียวแบบ atomic (ทดสอบแล้ว 88->91 หัก coin 85,800
    = ผลรวม 3 เลเวล) ถ้าจ่ายไม่ไหว/ยังไม่ปลดจะไม่ขยับเลย ไม่ใช่อัปเกรดครึ่ง ๆ

    ค่าใช้จ่ายแล้วแต่ type: ENERGY_* หัก coin, MACHINE_*/UNIT_* หัก crystal ฟังก์ชันวัดจาก
    ยอดจริงก่อน-หลัง (_apiBalance) ไม่เดา รหัส error: 102010=target<=ปัจจุบัน,
    102009=ยังไม่ปลด (extras บอก minRequiredLevel เช่นต้อง level 100), 500=ชื่อ type ผิด

    เลือกเป้าหมายได้ 3 แบบ:
      target=<n>  ไปเลเวล n ตรง ๆ (jump ทีเดียว เร็ว ใช้เมื่อรู้ว่าจ่ายไหว)
      steps=<n>   ขึ้นทีละ 1 จนครบ n เลเวล (หยุดทันทีถ้าเจอ error - ปลอดภัยกับงบ)
      toMax=True  ขึ้นทีละ 1 จนกว่าจะอัปไม่ได้ (จ่ายไม่ไหว/ตันแม็กซ์) เหมือน UI กด +max

    confirm=False (ดีฟอลต์) = dry-run บอกแค่จะทำอะไร ไม่ยิงจริง ตามคอนเวนชันโปรเจกต์ว่า
    mutation ต้อง confirm ก่อน กันเผลอถลุง coin/crystal
    คืน dict: {type, field, before, after, spent, steps, ok, reason}
    """
    if reinforceType not in MACHINE_UPGRADE_TYPES:
        raise Exception(f"apiUpgradeMachine: ไม่รู้จัก reinforceType {reinforceType!r} "
                        f"(ใช้ได้: {', '.join(MACHINE_UPGRADE_TYPES)})")
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    field = MACHINE_UPGRADE_TYPES[reinforceType]
    cookie = getLFAC()
    before = apiUpgradeStatus().get(field, 0)
    plan = target if target is not None else (10 ** 9 if toMax else before + steps)

    if not confirm:
        howto = ("ถึงแม็กซ์ที่จ่ายไหว" if toMax else f"ถึงเลเวล {plan}")
        log(f"[dry-run] apiUpgradeMachine {reinforceType}: ตอนนี้ {before} -> จะอัป{howto} "
            f"(ใส่ confirm=True เพื่อทำจริง)")
        return {"type": reinforceType, "field": field, "before": before, "after": before,
                "spent": {}, "steps": 0, "ok": False, "reason": "dry-run"}

    bal0 = _apiBalance(cookie)
    current = before
    done = 0
    reason = "ok"
    # jump ตรงถ้าระบุ target ชัด ไม่ใช่ toMax - ยิงครั้งเดียวเซิร์ฟเวอร์คิดสะสมให้
    if target is not None and not toMax:
        status, data = _apiCall(rangers_api.call, cookie, "/player/upgrade/", "POST",
                                {"reinforceType": reinforceType, "reinforceLevel": target})
        if status != 200:
            reason = f"HTTP {status}: {str(data)[:150]}"
        else:
            current = (data.get("result") or {}).get("playerUpgradeLevelStatus", {}).get(field, current)
            done = current - before
    else:
        # ขึ้นทีละ 1 (steps หรือ toMax) หยุดทันทีที่ยิงไม่ผ่าน - กันถลุงงบ
        cap = 500 if toMax else steps
        for _ in range(cap):
            status, data = _apiCall(rangers_api.call, cookie, "/player/upgrade/", "POST",
                                    {"reinforceType": reinforceType, "reinforceLevel": current + 1})
            if status != 200:
                reason = f"หยุดที่เลเวล {current} (HTTP {status}: {str(data)[:120]})"
                break
            current = (data.get("result") or {}).get("playerUpgradeLevelStatus", {}).get(field, current + 1)
            done += 1

    bal1 = _apiBalance(cookie)
    spent = _balanceDelta(bal0, bal1)
    ok = current > before
    log(f"apiUpgradeMachine {reinforceType}: {before} -> {current} (+{done}) ใช้ {spent or 'ฟรี'} | {reason}")
    return {"type": reinforceType, "field": field, "before": before, "after": current,
            "spent": spent, "steps": done, "ok": ok, "reason": reason}


def apiUpgradeEnergy(toMax=True, steps=1, confirm=False):
    """อัปเกรดพลังงานทั้งสองตัวเหมือน upgradeCrystal() ใน UI: max limit + production rate

    ยิงผ่าน API ตรงแทนการลาก UI + OCR สองตัวคือ ENERGY_MAX_LIMIT กับ ENERGY_PRODUCTION
    (คิดเป็น coin) toMax=True อัปจนงบหมดเหมือนกด +max ทั้งคู่ ใส่ steps แทนถ้าอยากขึ้นทีละนิด
    confirm=False = dry-run ตามเดิม คืน dict ผลของแต่ละตัว
    """
    out = {}
    for t in ("ENERGY_MAX_LIMIT", "ENERGY_PRODUCTION"):
        out[t] = apiUpgradeMachine(t, steps=steps, toMax=toMax, confirm=confirm)
    return out






SESSIONCSV = os.path.join("src", "log", "genid-sessions.csv")
SESSIONFIELDS = ["timestamp", "device", "status", "seconds", "attempts",
                 "gameId", "level", "rangers", "gacha", "file", "error"]


def logSession(startTime, status, gameId, level, rangerNames, gachaStatus,
               attempts=1, fileName="", error=""):
    """สรุปผล 1 session ทั้งให้คนอ่านและให้เครื่องอ่าน

    บรรทัดบนจอจัดคอลัมน์ให้กวาดตาดูรวดเดียวจบ ส่วน src/log/genid-sessions.csv เอาไป
    ต่อ monitoring ได้เลย (Excel เปิดได้ tail/grep/pandas อ่านได้) เขียนแบบ append
    ทีละบรรทัด บอทจึงถูกฆ่ากลางคันได้โดยไม่เสียบรรทัดที่เขียนไปแล้ว

    ใช้โมดูล csv ไม่ใช่ต่อ string เอง เพราะข้อความ error มีลูกน้ำและ newline ได้
    ซึ่งจะทำให้คอลัมน์เลื่อนทั้งไฟล์ และ header จะเขียนให้เองครั้งแรกครั้งเดียว

    การเขียน log ห้ามทำให้บอทหยุด error ตรงนี้จึงกลืนไว้แล้วแค่แจ้ง
    """
    elapsed = int(time.time() - startTime)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    errorText = " ".join(str(error).split())[:200]   # ยุบ newline ให้เหลือบรรทัดเดียว
    row = [timestamp, DEVICESERIAL, status, elapsed, attempts, gameId or "-",
           level, rangerNames or "-", gachaStatus or "-", fileName or "-", errorText]

    print("[SESSION] %s  %-4s %4ds x%d  %-10s Lv%-3s %-16s %-22s %s"
          % (timestamp, status, elapsed, attempts, gameId or "-", level,
             rangerNames or "-", gachaStatus or "-", fileName or "-"), flush=True)
    if errorText:
        print("[SESSION] error: %s" % errorText, flush=True)

    # ทุก emulator เขียนไฟล์เดียวกัน append บน Windows คือ seek ไปท้ายแล้วค่อยเขียน ไม่ atomic
    # เขียนพร้อมกันแถวทับกันหาย/header ซ้ำ จึงต่อคิวด้วย lock file (O_EXCL)
    lockPath = SESSIONCSV + ".lock"
    locked = False
    try:
        directory = os.path.dirname(SESSIONCSV)
        if directory:
            os.makedirs(directory, exist_ok=True)
        for _ in range(100):
            try:
                os.close(os.open(lockPath, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                locked = True
                break
            except (FileExistsError, PermissionError):
                # PermissionError = Windows ยังลบ lock ของคนก่อนไม่เสร็จ (delete pending) ก็รอเหมือนกัน
                time.sleep(0.05)
        else:
            locked = True   # รอ 5 วิแล้วยังไม่ปล่อย ถือว่าเป็น lock ค้างจากบอทที่ตายไป เขียนต่อแล้วล้างทิ้ง
        isNew = not os.path.exists(SESSIONCSV) or os.path.getsize(SESSIONCSV) == 0
        # utf-8-sig เพื่อให้ Excel เปิดแล้วไม่เพี้ยน, newline="" กัน csv ขึ้นบรรทัดคู่บน Windows
        with open(SESSIONCSV, "a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            if isNew:
                writer.writerow(SESSIONFIELDS)
            writer.writerow(row)
    except Exception as e:
        log(f"write session log failed: {e}")
    finally:
        if locked:
            try:
                os.remove(lockPath)
            except OSError:
                pass









def printRosterSummary(rows, top=None):
    """พิมพ์สรุปคลังแบบเดียวกับ tools/pull_roster.py

    ใช้ print ไม่ใช่ log() เพราะเป็นบล็อกหลายบรรทัด ถ้าผ่าน log() จะมี timestamp
    แปะหัวทุกบรรทัดจนอ่านเป็นตารางไม่ออก
    """
    from collections import Counter

    if not rows:
        log("คลังว่าง (ยังไม่มี rangers)")
        return

    print("\nTotal owned rangers: %d" % len(rows))
    print("Distinct characters:  %d" % len(set(r["name"] for r in rows)))
    print("Distinct unit codes:  %d" % len(set(r["unitCode"] for r in rows)))
    print("\nBy evolution tier:")
    for tier, count in Counter(r["evolution"] for r in rows).most_common():
        print("  %-8s %d" % (tier, count))

    # นับสองชั้น: ชื่อคือตัวละคร (leonard) ส่วน unitCode คือร่างนั้น ๆ (u1401s-leonard)
    # ตัวเดียวกันคนละร่างถือเป็นคนละของในเกม เลยต้องเห็นแยกด้วย ไม่ใช่แค่ยอดรวมชื่อ
    print("\nMost-owned characters:")
    for name, count in Counter(r["name"] for r in rows).most_common(top):
        print("  %-16s x%d" % (name, count))

    print("\nBy unit code:")
    byCode = Counter(r["unitCode"] for r in rows)
    # เรียงตามชื่อตัวละครก่อน แล้วค่อยจำนวนมาก->น้อย ร่างของตัวเดียวกันจะได้อยู่ติดกัน
    codeName = {r["unitCode"]: r["name"] for r in rows}
    codeEvo = {r["unitCode"]: r["evolution"] for r in rows}
    codeMax = {r["unitCode"]: r["maxLevel"] for r in rows}
    for code, count in sorted(byCode.items(), key=lambda kv: (codeName[kv[0]], -kv[1]))[:top]:
        print("  %-18s x%-4d %-8s max%s" % (code, count, codeEvo[code], codeMax[code]))




# ชื่อ group ใน URL ไม่ใช่ "ทีมที่ 1..5" แต่เป็น "ชุดทีม" คนละระบบกัน ในหนึ่ง group มีหลายทีม
# ย่อย (teamNo 1,2,3...) ซึ่งก็คือ A1/A2/A3 ที่เห็นในเกม ส่วนตัวเลขท้าย group คือชุด A/B/C/D/E
# player มีฟิลด์บอกว่า "ทีมย่อยไหนของ group นั้นเป็นตัวแทน" แยกกันคนละฟิลด์ ต้องอ่านให้ถูกตัว
# ไม่งั้นส่ง representalTeamNo ผิดแล้วโดน 102113 (ดู apiSaveTeamGroup)
# ตัวละครที่อยู่ในคลังแต่ลงทีมไม่ได้ (เป็นของไว้ป้อน/อัปเกรด ไม่ใช่ ranger) UI เดิมกันด้วยการ
# กดฟิลเตอร์ "ranger" ก่อนเลือก ฝั่ง API ไม่มีฟิลด์ไหนแยกได้เลย - record หน้าตาเหมือน ranger
# ทุกอย่าง รู้ได้ตอนเซฟแล้วโดน 102124 เท่านั้น อันนี้แค่ seed ไว้กันเสียรอบ ที่เหลือให้
# เซิร์ฟเวอร์สอนเอาผ่าน extras.unitCode (ดู setUpTeamA1)
NONDEPLOYABLENAMES = ("leonard",)

TEAMGROUPREPFIELD = {
    "team1": "useTeamNo",
    "team2": "useSecondTeamNo",
    "team3": "useThirdTeamNo",
    "team4": "useFourthTeamNo",
    "team5": "useFifthTeamNo",
    "pvpteam": "usePvPTeamNo",
    "labyrinth": "useLabyrinthTeamNo",
}


class TeamUnitRejected(Exception):
    """เซิร์ฟเวอร์ไม่ยอมให้ตัวนี้ลงทีม (errorCode 102124)

    แยกเป็น exception ของตัวเองเพราะคนเรียกต้องรู้ว่า "ตัวไหน" ถึงจะคัดออกแล้วลองใหม่ได้
    ถ้าโยน Exception เปล่า ๆ จะเหลือแค่ข้อความ ต้องมา parse string เอาซึ่งเปราะ
    """

    def __init__(self, unitCode, message):
        super().__init__(message)
        self.unitCode = unitCode


def apiReadTeamGroup(group="team1"):
    """คืนทุกทีมย่อยใน group เป็น {"<teamNo>": {"<slot>": "<invenId>"}}

    ต้องเก็บ slot จริงไว้ ไม่ใช่แค่ลำดับ เพราะทีมมีช่องว่างกลาง ๆ ได้ (ของจริงเคยเจอ
    ทีมที่มีแค่ slot 2 กับ 3) ถ้าอ่านเป็น list แล้วเซฟกลับด้วย enumerate จะกลายเป็น
    slot 0,1 = ย้ายตำแหน่งตัวละครโดยไม่ได้ตั้งใจ

    คืนเป็น string ทั้ง key และ value ให้ตรงกับรูปร่างที่ apiSaveTeamGroup ต้องส่ง
    จะได้เอาผลลัพธ์วนกลับไปเซฟต่อได้เลยโดยไม่ต้องแปลงชนิดซ้ำ
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    status, data = _apiCall(rangers_api.call, getLFAC(),
                            "/player/units/equip?inven=false&team=true&deck=false")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiReadTeamGroup failed (HTTP {status}): {str(data)[:200]}")
    groups = (data.get("result") or {}).get("playerUnitTeamGroupMap") or {}
    return {str(teamNo): {str(u["slot"]): str(u["invenId"]) for u in (units or [])}
            for teamNo, units in (groups.get(group) or {}).items()}


def apiReadTeam(group="team1", teamNo=1):
    """คืนทีมย่อยเดียวเป็น list ของ invenId (int) เรียงตาม slot - ไว้เช็คผลแบบอ่านง่าย ๆ"""
    deck = apiReadTeamGroup(group).get(str(teamNo)) or {}
    return [int(deck[slot]) for slot in sorted(deck, key=int)]


def apiSaveTeamGroup(decks, group="team1"):
    """เซฟทั้ง group ทีเดียว decks = {"<teamNo>": {"<slot>": "<invenId>"}}

    รูปร่าง body ถอดมาจาก libgame.so (ฟังก์ชันที่ 0xf96288) ไม่ได้เดา เพราะเซิร์ฟเวอร์
    ตอบ errorCode เดียวกันหมดเวลาคีย์ผิด เดาเองไม่มีทางรู้ว่าใกล้หรือไกล ตัวจริงคือ
    CCDictionary แล้วค่อยแปลงเป็น JSON:
        {"deck<teamNo>": {"<slot>": "<invenId>", ...}, ..., "representalTeamNo": <n>}
    ข้อควรระวังที่ทดสอบกับเซิร์ฟเวอร์จริงแล้ว:
      - invenId ต้องเป็น "string" ส่ง unitCode แทนจะได้ 500
      - คีย์สะกดว่า representalTeamNo (ตกตัว i) ไม่ใช่ representative ไม่ส่ง = 102113
      - ชื่อ deck ต้องต่อท้ายด้วยเลขทีมย่อย (deck1/deck2) ไม่ใช่ deck เฉย ๆ

    **การเซฟคือ "แทนที่ทั้ง group"** ไม่ใช่แก้เฉพาะทีมที่ส่งไป ทีมย่อยไหนไม่อยู่ใน body
    จะถูกลบทิ้ง (เจอของจริงมาแล้ว: ส่งแค่ deck2 ไป ทีม 1 หายเกลี้ยง) จึงต้องอ่าน
    apiReadTeamGroup() มาก่อนเสมอ แก้เฉพาะทีมที่ต้องการ แล้วส่งกลับไปทั้งชุด

    representalTeamNo ต้องชี้ไปที่ teamNo ที่ "มีอยู่ใน body นี้" ไม่ใช่แค่ค่าเดิมของ player
    บัญชีที่ useTeamNo=2 แล้วส่งไปแค่ deck1 พร้อม representalTeamNo=2 จะโดน 102113
    (extras บอก representativeTeamNo กลับมาให้ด้วย) เพราะทีมตัวแทนจะกลายเป็นทีมว่าง

    ส่งไม่ครบ 5 ตัวได้ (ทดสอบแล้ว 3 ตัวและ 1 ตัวก็ 200) ช่องที่เหลือจะว่าง
    แต่ห้ามมีตัวละครซ้ำในทีมย่อยเดียวกัน เซิร์ฟเวอร์ตอบ 400 errorCode 102110 แล้วไม่แก้อะไรเลย
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    if not decks:
        raise Exception("apiSaveTeamGroup: decks ว่าง จะลบทีมทิ้งทั้ง group")

    cookie = getLFAC()
    status, data = _apiCall(rangers_api.call, cookie, "/home")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiSaveTeamGroup failed to read player (HTTP {status}): {str(data)[:200]}")
    player = (data.get("result") or {}).get("player") or {}
    repNo = player.get(TEAMGROUPREPFIELD.get(group, "useTeamNo")) or 1

    if str(repNo) not in decks:
        # ทีมตัวแทนเดิมไม่มีตัวละครอยู่เลย (ไม่มีใน group) เก็บไว้ไม่ได้ ต้องย้ายไปทีมที่มีจริง
        # ไม่งั้นเซิร์ฟเวอร์ตีกลับ 102113 ทั้ง request บอกไว้ใน log เพราะเป็นการเปลี่ยน state
        repNo = min(decks, key=int)
        log(f"apiSaveTeamGroup: ทีมตัวแทนเดิมของ {group} ว่าง ย้ายไปทีม {repNo}")

    body = {"deck%s" % teamNo: dict(deck) for teamNo, deck in decks.items()}
    body["representalTeamNo"] = int(repNo)
    status, data = _apiCall(rangers_api.call, cookie,
                            "/player/units/save/%s" % group, "POST", body)
    if status != 200:
        extras = (data.get("extras") or {}) if isinstance(data, dict) else {}
        if isinstance(data, dict) and data.get("errorCode") == 102124 and extras.get("unitCode"):
            raise TeamUnitRejected(extras["unitCode"],
                                   f"unit {extras['unitCode']} ลงทีมไม่ได้: {str(data)[:200]}")
        raise Exception(f"apiSaveTeamGroup failed (HTTP {status}): {str(data)[:200]}")
    return True


def apiSaveTeam(invenIds, group="team1", teamNo=1):
    """เซฟทีมย่อยเดียว invenIds = list ของ invenId เรียงตาม slot 0..4

    เป็นตัวห่อ apiSaveTeamGroup() ที่อ่าน group เดิมมาก่อนแล้วแก้แค่ teamNo ที่ระบุ
    ห้ามยิง endpoint ตรง ๆ ด้วยทีมเดียว เพราะการเซฟคือแทนที่ทั้ง group ทีมอื่นจะหาย
    """
    decks = apiReadTeamGroup(group)
    decks[str(teamNo)] = {str(slot): str(invenId) for slot, invenId in enumerate(invenIds)}
    return apiSaveTeamGroup(decks, group)


def apiUnitSpecs():
    """คืน {unitCode: {"grade": ..., "summonEnergy": ...}} ของตัวที่ "อยู่ในทีม" ตอนนี้

    endpoint คลังปกติไม่เคยส่ง grade/summonEnergy มาเลย มีแต่ unitCode/unitLevel/maxLevel
    ตัวที่ส่งสเปกเต็มคือ /player/units/team/battle/uid/<uid> (อันเดียวกับที่เกมใช้ตอน
    จะเข้าฉาก) แต่มันส่งมาเฉพาะตัวที่ถูกจัดอยู่ในทีมใดทีมหนึ่ง ไม่ใช่ทั้งคลัง
    setUpTeamA1() จึงต้องเอาตัวที่ยังไม่รู้สเปกไปวางในทีมก่อนแล้วค่อยอ่าน

    grade = ดาว/ความหายาก (มากคือดี) summonEnergy = ค่า mineral ที่ต้องจ่ายตอนเรียกลงสนาม
    (น้อยคือดี) สองค่านี้ผูกกับ unitCode ไม่ผูกกับ invenId ตัวซ้ำจึงใช้ค่าเดียวกันได้
    และไม่ขึ้นกับเลเวล (sally lv1 ก็ 1310 เท่าเดิม) จึงเก็บลง UNITSPECCACHE ข้าม ID ได้
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    cookie = getLFAC()
    status, data = _apiCall(rangers_api.call, cookie, "/home")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiUnitSpecs failed to read player (HTTP {status}): {str(data)[:200]}")
    uid = ((data.get("result") or {}).get("player") or {}).get("uid")
    if not uid:
        raise Exception("apiUnitSpecs: no uid in /home")

    status, data = _apiCall(rangers_api.call, cookie,
                            "/player/units/team/battle/uid/%s" % uid)
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiUnitSpecs failed (HTTP {status}): {str(data)[:200]}")

    specs = {}
    groups = (data.get("result") or {}).get("playerUnitTeamGroupMap") or {}
    for teams in groups.values():
        for units in (teams or {}).values():
            for unit in units or []:
                if "summonEnergy" in unit:
                    specs[unit["unitCode"]] = {
                        "grade": unit.get("grade"),
                        "summonEnergy": unit.get("summonEnergy"),
                    }
    _loadUnitSpecs()
    new = {code: spec for code, spec in specs.items() if UNITSPECCACHE.get(code) != spec}
    if new:
        UNITSPECCACHE.update(new)
        _saveUnitSpecs()
    return specs


def setUpTeamA1(slot=5, maxMineralCost=1300, group="team1", teamNo=1):
    """จัดทีม A1 จากตัวที่มีในคลัง เอา rarity สูงสุด ใช้ mineral น้อยสุด

    แทน autoChangeTeam() ที่ลาก UI ทีละตัวแล้ว OCR ค่า mineral จากจอ อันนี้ยิง API ตรง
    ผลลัพธ์เป้าหมายเดียวกัน: เรียงตาม grade มาก->น้อย ตัด grade เท่ากันด้วย mineral น้อย->มาก

    A1 = group "team1" (ชุด A) ทีมย่อยที่ 1 อยากได้ A2 ก็ teamNo=2 อยากได้ชุด B ก็ group="team2"

    maxMineralCost คือเพดานเดียวกับ autoChangeTeam (ดีฟอลต์ 1300) กันไม่ให้ได้ทีมที่
    แพงจนเรียกลงสนามไม่ทัน ถ้ากรองแล้วเหลือไม่ครบ slot จะเติมด้วยตัวที่ถูกที่สุดที่เหลือ
    เพราะทีมขาดคนแย่กว่าทีมแพง ใส่ None ถ้าอยากได้ grade สูงสุดล้วน ๆ ไม่สนราคา
    (เพดาน 1300 ตัด u1630e-sally ที่ grade 8 ทิ้งได้ เพราะมันกิน 1310)

    เลือกได้ตัวละครละ 1 ตัวต่อทีม กันด้วย base_name (u32-brown กับ u32e-brown = brown)
    ที่ยืนยันกับเซิร์ฟเวอร์แล้วคือ unitCode เดียวกันซ้ำในทีม = 102110 ส่วนคนละร่างของ
    ตัวเดียวกันยังไม่ได้ลอง เลือกทางที่ปลอดภัยกว่าไว้ก่อนเพราะในเกมก็ลงซ้ำตัวไม่ได้อยู่แล้ว

    สเปก (grade/summonEnergy) อ่านได้เฉพาะตัวที่อยู่ในทีม (ดู apiUnitSpecs) ตัวที่ยังไม่รู้
    จึงต้องเอาไปวางในทีมเป้าหมายเป็นรอบ ๆ รอบละ 5 ตัวเพื่ออ่านสเปก ระหว่างนี้ทีมนั้นจะถูก
    เขียนทับ ซึ่งไม่เสียหายเพราะปลายทางคือเขียนทับอยู่แล้ว ถ้าพังกลางทางจะคืนทีมเดิมให้
    บัญชี 227 ตัวใช้เวลาไล่อ่านราว 2 นาทีรอบแรก รอบต่อ ๆ ไปอ่านจาก UNITSPECPATH เหลือ ~7 วิ

    ทีมอื่นใน group จะถูกส่งกลับไปด้วยเสมอ (endpoint เซฟแบบแทนที่ทั้ง group ส่งทีมเดียว
    ทีมที่เหลือหายหมด) แต่ถ้าตัวที่เลือกไปจอดอยู่ทีมอื่น จะถูก "ย้าย" มา ทีมนั้นจึงเปลี่ยนได้
    ซึ่งบอกไว้ใน log ทุกครั้ง ไม่ได้เงียบ ๆ
    """
    roster = getTeanInfo()
    if not roster:
        log("setUpTeamA1: คลังว่าง ไม่มีตัวให้จัดทีม")
        return []

    original = apiReadTeamGroup(group)
    specs = dict(_loadUnitSpecs())
    specs.update(apiUnitSpecs())

    # unitCode ที่ลงทีมไม่ได้ เริ่มจากที่รู้อยู่แล้ว ที่เหลือเรียนเอาจาก 102124 ระหว่างทาง
    blocked = {r["unitCode"] for r in roster if r["name"] in NONDEPLOYABLENAMES}

    def saveTeam(rows):
        """เซฟทีม ถ้าโดนปฏิเสธรายตัวให้ตัดตัวนั้นออกแล้วลองใหม่ คืน rows ที่เซฟได้จริง

        ลองใหม่ได้เรื่อย ๆ เพราะเซิร์ฟเวอร์บอกมาทีละตัว ทีมที่มีของแปลก 3 ตัวจะวนสามรอบ
        request ที่ถูกปฏิเสธไม่แก้อะไรเลย (เหมือน 102110) จึงวนซ้ำได้ไม่ต้องกลัวเขียนครึ่ง ๆ

        ตัวเดียวกัน (invenId เดียวกัน) อยู่สองทีมใน group เดียวกันไม่ได้ เซิร์ฟเวอร์ตอบ 102110
        ทดสอบแล้วว่าชนกันที่ invenId ไม่ใช่ตัวละคร (brown คนละตัวอยู่คนละทีมได้ 200)
        จึงย้ายออกจากทีมอื่นให้ ไม่ใช่ข้ามตัวนั้นทิ้ง เพราะตัวเก่ง ๆ มักถูกจอดไว้ที่ A2 อยู่แล้ว
        ถ้าข้ามจะได้ทีมที่แย่ลงโดยไม่จำเป็น (UI เดิมเจอ popup แล้วเลื่อนข้ามไปตัวถัดไป)
        """
        rows = [r for r in rows if r["unitCode"] not in blocked]
        while rows:
            moving = {str(r["invenId"]) for r in rows}
            decks = {}
            for no, deck in original.items():
                if no == str(teamNo):
                    continue
                kept = {slot: inven for slot, inven in deck.items() if inven not in moving}
                # ทีมที่ว่างเปล่าไม่ต้องส่ง คีย์ deck ที่ไม่มีตัวเลยไม่มีความหมาย
                # และถ้ามันเป็นทีมตัวแทน apiSaveTeamGroup จะย้ายตัวแทนให้พร้อม log
                if kept:
                    decks[no] = kept
            decks[str(teamNo)] = {str(i): str(r["invenId"]) for i, r in enumerate(rows)}
            try:
                apiSaveTeamGroup(decks, group)
                return rows
            except TeamUnitRejected as rejected:
                blocked.add(rejected.unitCode)
                log(f"setUpTeamA1: {rejected.unitCode} ลงทีมไม่ได้ ตัดออกแล้วลองใหม่")
                rows = [r for r in rows if r["unitCode"] != rejected.unitCode]
        return []

    # ตัวที่ยังไม่รู้สเปก เอาไปวางทีม 1 ทีละไม่เกิน 5 (ทีมมี 5 ช่อง) แล้วอ่านกลับ
    # ใช้ unitCode เป็น key เพราะสเปกผูกกับ unitCode ตัวซ้ำอ่านรอบเดียวพอ
    unknown = []
    for row in roster:
        if (row["unitCode"] not in specs and row["unitCode"] not in blocked
                and row["unitCode"] not in [u["unitCode"] for u in unknown]):
            unknown.append(row)
    try:
        while unknown:
            # ทีมเดียวห้ามมีตัวละครซ้ำ รอบนี้จึงหยิบได้เฉพาะคนละตัวละครกัน
            batch, seen = [], set()
            for row in list(unknown):
                if len(batch) >= 5:
                    break
                if row["name"] in seen:
                    continue
                seen.add(row["name"])
                batch.append(row)
                unknown.remove(row)
            log(f"setUpTeamA1: อ่านสเปก {len(batch)} ตัว ({', '.join(r['unitCode'] for r in batch)})")
            if saveTeam(batch):
                specs.update(apiUnitSpecs())
    except Exception:
        # คืนทีมเดิมแบบ best-effort ถ้าคืนไม่สำเร็จก็ห้ามกลบ error ต้นทาง ไม่งั้น traceback
        # จะชี้ไปที่ขั้นตอนคืนค่า แล้วหาสาเหตุจริงไม่เจอ
        log("setUpTeamA1: อ่านสเปกไม่สำเร็จ คืนทีมเดิมให้ก่อน")
        try:
            if original:
                apiSaveTeamGroup(original, group)
        except Exception as restoreError:
            log(f"setUpTeamA1: คืนทีมเดิมไม่สำเร็จด้วย: {restoreError}")
        raise

    candidates = [r for r in roster if r["unitCode"] not in blocked]
    for row in candidates:
        spec = specs.get(row["unitCode"]) or {}
        # ไม่รู้สเปก = ถือว่าแย่ที่สุด (grade -1, mineral มหาศาล) จะได้ไม่ถูกเลือกก่อนตัวที่รู้
        row["grade"] = spec.get("grade", -1)
        row["summonEnergy"] = spec.get("summonEnergy", 10 ** 9)

    # grade มาก->น้อย ก่อน แล้วค่อย mineral น้อย->มาก ตรงกับ autoChangeTeam ที่ sort by grade
    # แล้วค่อยข้ามตัวที่ mineral เกินเพดาน ท้ายสุดใช้ maxLevel/level กันลำดับแกว่งเวลาค่าเท่ากัน
    order = sorted(candidates, key=lambda r: (-r["grade"], r["summonEnergy"],
                                              -(r["maxLevel"] or 0), -(r["level"] or 0)))

    def pick(rows):
        chosen, used = [], set()
        for row in rows:
            if len(chosen) >= slot:
                break
            if row["name"] in used:
                continue
            used.add(row["name"])
            chosen.append(row)
        return chosen

    team = pick([r for r in order
                 if maxMineralCost is None or r["summonEnergy"] <= maxMineralCost])
    if len(team) < slot:
        # เพดานทำให้ได้ไม่ครบ เติมด้วยตัวที่ mineral ถูกสุดในบรรดาที่เหลือ (ทีมขาดคนแย่กว่า)
        names = {r["name"] for r in team}
        filler = sorted((r for r in order if r["name"] not in names),
                        key=lambda r: (r["summonEnergy"], -r["grade"]))
        team += pick(filler)[:slot - len(team)]

    team = saveTeam(team)
    if not team:
        raise Exception("setUpTeamA1: ไม่มีตัวไหนลงทีมได้เลย (โดนปฏิเสธหมด)")

    # เช็คด้วยการอ่านกลับ ไม่เชื่อ HTTP 200 อย่างเดียว เพราะเซิร์ฟเวอร์เมินคีย์ที่ไม่รู้จักเงียบ ๆ
    # เช็คทีมอื่นใน group ด้วย เพราะ endpoint นี้เซฟแบบแทนที่ทั้ง group ถ้าพลาดจะลบทีมอื่นทิ้ง
    after = apiReadTeamGroup(group)
    saved = [int(inven) for _, inven in sorted((after.get(str(teamNo)) or {}).items(), key=lambda kv: int(kv[0]))]
    if saved != [r["invenId"] for r in team]:
        raise Exception(f"setUpTeamA1: เซฟแล้วแต่อ่านกลับไม่ตรง (ต้องการ "
                        f"{[r['invenId'] for r in team]} แต่ได้ {saved})")
    # ทีมอื่นใน group อาจโดนดึงตัวไปจริง ๆ (ดู saveTeam) ไม่ใช่ error แต่ต้องเห็นใน log
    # ไม่งั้นคนใช้จะงงว่าทำไมทีม A2 หายไปเอง
    for no, deck in original.items():
        if no != str(teamNo) and (after.get(no) or {}) != deck:
            log(f"setUpTeamA1: ทีม {no} ของ {group} เปลี่ยนไปเพราะถูกดึงตัวมาเข้าทีม {teamNo}")

    log("Team A1: " + ", ".join("%s(g%s/m%s)" % (r["unitCode"], r["grade"], r["summonEnergy"])
                                for r in team))
    return team




def startBotCheckGameInfo_API(deviceSerial=None):
    global GAMEID
    MAXATTEMPTS = 3

    while True:
        GAMEID = ""
        sessionStart = time.time()
        sessionStatus = "FAIL"
        currentLevelValue = 0
        rangerNames = ""
        gachaStatus = "-"
        exportedFile = ""
        lastError = ""
        usedAttempts = 0
        # ไฟล์ของ session นี้ หยิบครั้งเดียวแล้ว retry ด้วยไฟล์เดิม ถ้า retry ไป import ใหม่
        # จะได้ไฟล์ถัดไปจาก split-ID แทน ไฟล์เดิมเลยค้างอยู่ใน execute ไม่มีใครย้ายออก
        sessionFile = ""
        noMoreFiles = False

        print("========= Start =========", flush=True)
        print(">>> startBotCheckGameInfo <<<", flush=True)

        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")

        for attempt in range(1, MAXATTEMPTS + 1):
            usedAttempts = attempt
            rangerNames = ""   # add_ranger_name ต่อท้ายเรื่อยๆ ต้องล้างทุก attempt

            try:
                force_stop_LINE_Rangers()
                if not sessionFile:
                    try:
                        importFileFromInputToExecute()
                    finally:
                        # จองไฟล์ได้แล้วแต่ push พัง ก็ยังต้อง retry ด้วยไฟล์นี้
                        sessionFile = FILENAME
                    if not sessionFile:
                        noMoreFiles = True
                        break
                else:
                    reImportFileInExecute()

                if openLineRangers(skipLoadingScreen=True) == "authentication_failed":
                    lastError = "Authentication failed - cannot open game with this ID"
                    log(lastError)
                    break   # ID ใช้ไม่ได้ retry ก็ไม่ช่วย ไปย้ายเข้า login failed ด้านล่าง

                lfacReady = False
                try:
                    getLFAC(timeout=60)
                    lfacReady = True
                except Exception as e:
                    gachaStatus = "error"
                    lastError = str(e)
                    log(f"LF_AC not ready (ID ยังใช้ได้ ส่งออกต่อ): {e}")

                force_stop_LINE_Rangers()

                if lfacReady:
                    rangerNames, level, ruby, ticket, gameID = getAccoutInfo()


                fileName = f"{rangerNames}_Rb{ruby}_Tk{ticket}_{gameID}_Lv{level}"
                # ตั้งชื่อใหม่ทั้งชื่อ ไม่เอาชื่อเดิมต่อท้าย ไฟล์ output ที่เอากลับมารันซ้ำชื่อจะได้ไม่ยาวขึ้นทุกรอบ
                exportedFile = os.path.basename(exportFileFromExecuteToOutput(newName=fileName))
                currentLevelValue = level
                force_stop_LINE_Rangers()
                sessionStatus = "OK"
                break

            except TimeoutError as e:
                lastError = f"timeout: {e}"
                captureScreenError(str(e))
                log(f"Restart bot due to timeout (attempt {attempt}): {e}")
                continue
            except Exception as e:
                lastError = str(e)
                captureScreenError(str(e))
                log(f"Unexpected error (attempt {attempt}): {e}")
                traceback.print_exc()
                continue

        if noMoreFiles:
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break

        if sessionStatus == "FAIL" and os.path.isfile(os.path.join("execute", sessionFile)):
            # retry ครบแล้วยังไม่ผ่าน ย้ายออกจาก execute ไม่ให้ไฟล์ค้าง
            try:
                exportFileFromExecuteToLoginFailed()
                exportedFile = os.path.join("login failed", sessionFile)
            except Exception as e:
                log(f"move to login failed error: {e}")

        # log ก่อนเช็คว่ามีไฟล์เหลือไหม เดิม break ก่อนถึงตรงนี้ session สุดท้ายของทุกเครื่องเลยหาย
        logSession(sessionStart, sessionStatus, GAMEID or gameID, currentLevelValue, rangerNames,
                   gachaStatus, usedAttempts, exportedFile, lastError)
        print("========== End ==========", flush=True)


def _remainText(ms):
    """แปลง ms ที่เหลือเป็นข้อความสั้น ๆ เช่น '3d 5h' / '2h 10m' / 'ถาวร/หมดแล้ว'"""
    if not ms or ms <= 0:
        return "ถาวร/หมดแล้ว"
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def printGachaBanners(rows):
    """พิมพ์รายการตู้กาชาแบบอ่านง่าย (ใช้ print เพราะเป็นบล็อกหลายบรรทัด ไม่ผ่าน log)"""
    if not rows:
        log("ไม่มีตู้กาชาที่เปิดอยู่")
        return
    print("\nGacha banners (%d):" % len(rows))
    for r in rows:
        end = datetime.fromtimestamp(r["end"] / 1000).strftime("%m/%d %H:%M") if r["end"] else "-"
        print("\n  %s  [%s]%s" % (r["groupId"], r["type"] or "-", "" if r["live"] else "  (CLOSED)"))
        print("    %s" % r["name"])
        if r["featured"]:
            print("    เด่น: %s" % ", ".join(r["featured"]))
        print("    เหลือ: %s (ถึง %s)" % (_remainText(r["remainMs"]), end))
        if r["banner"]:
            print("    banner: %s" % r["banner"])


GACHABANNERTYPES = ("ULTRA_RARE", "PICK_UP")


def reloginFromInput(rel_path=""):
    """relogin จากไฟล์บัญชีใน input/ แล้วคืน 'LF_AC=...' สด โดยไม่ต้องมี device/เกม

    ใช้ตอนต้องการ token สำหรับ "ดึงข้อมูลอย่างเดียว" (เช่นรายการตู้กาชา) แบบ headless
    rel_path = path เทียบกับ input/ ไม่ส่งมา = หยิบ .xml ไฟล์แรกที่เจอ (รวมโฟลเดอร์ย่อย)
    ไม่แก้ไฟล์ต้นฉบับและไม่แตะ session globals (LFACCACHE/GAMEID) เพราะเป็นการยืม token ชั่วคราว
    โทเค็นเก่าในไฟล์ตายแล้วก็ไม่เป็นไร relogin สร้างของสดให้ (โทเค็นเก่าใช้เป็น guestCookie)
    """
    global _HEADLESSCCPOOL
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import relogin
    from device_session import decrypt_lfac

    target = ""
    if rel_path and os.path.isfile(os.path.join("input", rel_path)):
        target = os.path.join("input", rel_path)
    else:
        for root, dirs, files in os.walk("input"):
            xmls = sorted(f for f in files if f.endswith(".xml"))
            if xmls:
                target = os.path.join(root, xmls[0])
                break
        if not target:
            raise Exception("ไม่พบไฟล์บัญชี .xml ในโฟลเดอร์ input")

    acct = relogin.read_account(target)
    guestCookie = decrypt_lfac(acct["udid"], acct["enc"])
    if _HEADLESSCCPOOL is None:
        _HEADLESSCCPOOL = relogin.CcPool()
    cc = _HEADLESSCCPOOL.get()
    status, result, lfAc = relogin.login(cc, acct["udid"], guestCookie, acct["nation"], acct["language"])
    if status == 401 and not result:
        cc = _HEADLESSCCPOOL.renew(cc)
        status, result, lfAc = relogin.login(cc, acct["udid"], guestCookie, acct["nation"], acct["language"])
    if not result or not lfAc:
        raise Exception(
            f"relogin จาก input ล้มเหลว (HTTP {status}) - ไฟล์ {os.path.basename(target)} ใช้ไม่ได้")
    _HEADLESSCCPOOL.mark_proven()
    return "LF_AC=" + lfAc


def getGachaBanner(summary=True, includeClosed=False, types=GACHABANNERTYPES, eventOnly=True, cookie=None):
    """คืนรายการตู้กาชาจาก API เป็น list ของ dict — ไอดีตู้/ชื่อ/แบนเนอร์/ตัวเด่น/เวลาที่เหลือ

    ทั้งหมดมาจาก /gacha/info -> result.gachaGroupResponseList[].gachaGroup (endpoint เดียว
    กับ tools/gacha.py list) ตู้กาชาหนึ่งตู้ = หนึ่ง groupId ส่วน gachaIndex เป็นแค่ตัวเลือก
    จำนวนสุ่มข้างในตู้ ไม่ใช่คนละตู้

    types = กรองเฉพาะ gachaDisplayType ที่อยากได้ ดีฟอลต์เอาแค่ ULTRA_RARE/PICK_UP/CLASSIC
    (ตัดพวก SPECIAL_GEAR ฯลฯ ทิ้ง) ใส่ None ถ้าอยากได้ทุกประเภท

    eventOnly=True เอาเฉพาะตู้อีเวนต์จริง คือชื่อมี "[EVENT-" ตัดตู้บทสอน/pity (PITY_GACHA_TUTO)
    และตู้ถาวรที่ไม่ใช่อีเวนต์ทิ้ง หมายเหตุ: ตู้ CLASSIC ชื่อไม่มี [EVENT-] จะโดนตัดด้วย
    ถ้าอยากได้ CLASSIC กลับมาใส่ eventOnly=False

    banner: bgUrl เป็น dict แยกภาษา เลือก th ก่อน ไม่มีค่อย en (รูปพื้นหลังตู้เต็มใบ) ส่วน
      listBgUrl คือรูปเล็กในลิสต์ ถ้าอยากได้เพิ่มดึงเองจาก raw ได้
    featured: titleRewardCodes = unitCode ตัวเด่นของตู้ (เช่น u1630e-sally) featuredNames
      ตัดเหลือชื่อตัวละคร (sally) ด้วย pull_roster.base_name เผื่อเอาไปโชว์
    เวลา: exposureEndDate (ms) - ตอนนี้ = remainMs ตู้ถาวรบางตัวไม่มี end (remainMs=0)

    includeClosed=False เอาเฉพาะตู้ที่เปิดอยู่ (อยู่ในช่วง exposure ตอนนี้) True = เอาหมด
    เรียงตาม sortOrder เหมือนที่เกมเรียงโชว์
    summary=False ถ้าจะเอาไปใช้ต่อในโค้ด ไม่ต้องพ่นสรุปลง log
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api
    import pull_roster

    status, data = _apiCall(rangers_api.call, cookie or getLFAC(), "/gacha/info")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"getGachaBanner failed (HTTP {status}): {str(data)[:200]}")

    now = int(time.time() * 1000)
    groups = sorted((data.get("result") or {}).get("gachaGroupResponseList") or [],
                    key=lambda g: (g.get("gachaGroup") or {}).get("sortOrder", 999))
    rows = []
    for group in groups:
        gg = group.get("gachaGroup") or {}
        # if types is not None and gg.get("gachaDisplayType") not in types:
        #     continue
        # if eventOnly and "[EVENT-" not in (gg.get("gachaName") or ""):
        #     continue
        start, end = gg.get("exposureStartDate"), gg.get("exposureEndDate")
        live = bool(start and end and start <= now <= end)
        if not includeClosed and not live:
            continue
        bg = gg.get("bgUrl") or {}
        featured = gg.get("titleRewardCodes") or []
        rows.append({
            "groupId": gg.get("groupId"),
            "name": gg.get("gachaName"),
            "banner": bg.get("th") or bg.get("en") or next(iter(bg.values()), None),
            "featured": featured,
            "featuredNames": [pull_roster.base_name(u) for u in featured],
            "type": gg.get("gachaDisplayType"),
            "resultType": gg.get("gachaResultType"),
            "start": start,
            "end": end,
            "remainMs": (end - now) if (end and end > now) else 0,
            "live": live,
        })

    if summary:
        printGachaBanners(rows)
    return rows




def startBotLogin_API_headless(deviceSerial=""):
    global GAMEID
    MAXATTEMPTS = 3

    # setUp ครั้งเดียวต่อ worker (โหลด config + ตั้ง HEADLESS/DEVICESERIAL) ไม่ใช่ทุกไฟล์
    # config ไม่เปลี่ยนระหว่างไฟล์ การอ่าน .ini 3 ไฟล์ซ้ำทุกรอบเป็นงานเปล่า
    setUpHeadless(deviceSerial)
    log(f"Bot running headless on {deviceSerial}")

    while True:
        GAMEID = ""
        sessionStart = time.time()
        sessionStatus = "FAIL"
        currentLevelValue = 0
        gachaStatus = "-"
        exportedFile = ""
        lastError = ""
        usedAttempts = 0
        # ไฟล์ของ session นี้ หยิบครั้งเดียวแล้ว retry ด้วยไฟล์เดิม ถ้า retry ไป import ใหม่
        # จะได้ไฟล์ถัดไปจาก split-ID แทน ไฟล์เดิมเลยไม่ถูกทำและไม่มีใครย้ายออกจาก execute
        sessionFile = ""
        noMoreFiles = False
        # กาชาหักตั๋วจริง ถ้าสุ่มไปแล้วแต่ขั้นหลังพัง (เช่น pull ไฟล์ไม่ได้) retry ห้ามสุ่มซ้ำ
        gachaDone = False
        gachaUnits = []
        rangerNames = ""          # logSession ใช้เสมอ แม้ login ไม่ผ่านตั้งแต่ attempt แรก
        accountId = ""            # GAME_ID ของไฟล์นี้ ใช้กันบัญชีเดียวกันสองไฟล์สุ่มกาชาซ้ำ
        duplicateAccount = False

        print("========= Start =========", flush=True)
        print(">>> startBotLogin (headless) <<<", flush=True)

        for attempt in range(1, MAXATTEMPTS + 1):
            usedAttempts = attempt
            try:
                force_stop_LINE_Rangers()   # headless: แค่ล้าง LFACCACHE บังคับ relogin ไฟล์นี้ใหม่
                if not sessionFile:
                    try:
                        importFileFromInputToExecute()
                    finally:
                        # จองไฟล์ได้แล้วแต่ push พัง ก็ยังต้อง retry ด้วยไฟล์นี้
                        sessionFile = FILENAME
                    if not sessionFile:
                        noMoreFiles = True
                        break
                else:
                    reImportFileInExecute()

                # headless ไม่เปิดเกม โทเค็นมาจาก getLFAC() ที่ relogin จากไฟล์เอง (ด้านล่าง)

                lfacReady = False
                try:
                    getLFAC(timeout=60)
                    lfacReady = True
                except Exception as e:
                    gachaStatus = "error"
                    lastError = str(e)
                    log(f"LF_AC not ready (ID ยังใช้ได้ ส่งออกต่อ): {e}")

                # headless: ไม่ต้อง force_stop ตรงนี้ (ไม่มีเกม) และห้ามล้าง LFACCACHE จะได้ relogin แค่ครั้งเดียวต่อไฟล์

                # บัญชีนี้มีไฟล์อื่นในรอบเดียวกันทำไปแล้ว ไม่ต้องสุ่มซ้ำ (retry ของ session ตัวเองไม่นับ)
                if lfacReady and not accountId:
                    accountId = GAMEID or getGameID()
                    if not _claimAccountThisRun(accountId):
                        duplicateAccount = True
                        gachaDone = True
                        gachaStatus = "dup-account"
                        log(f"Account {accountId} already done by another file this run - skip rewards/gacha")

                if lfacReady and not gachaDone:
                    try:
                        apiAcceptAllRewards()                   # ใช้ api รับของแจกทั้งหมด
                        if GACHARANGER:
                            gachaUnits = apiGachaWithTicket(gacharangergroup=GACHARANGERGROUP, gacha_cycles=RGACHACYCLES)       # ใช้ api ใช้ตั๋วสุ่มกาชา 1 ครั้ง
                        gachaDone = True
                        gachaStatus = LASTGACHASTATUS
                    except Exception as e:
                        gachaStatus = "error"
                        lastError = str(e)
                        log(f"API step failed (ID ยังใช้ได้ ส่งออกต่อ): {e}")
                        traceback.print_exc()
                elif gachaDone and not duplicateAccount:
                    log(f"Gacha already done this session ({gachaStatus}) - skip")

                # ค่าเริ่มต้นไว้ก่อน ถ้า LF_AC ไม่มา getAccoutInfo จะไม่ถูกเรียก ตัวแปรพวกนี้จะไม่มีค่า
                rangerNames, level, ruby, ticket, gameID = "", 0, "NA", "NA", GAMEID
                if lfacReady:
                    rangerNames, level, ruby, ticket, gameID = getAccoutInfo()
                currentLevelValue = level
                fileName = f"{rangerNames}_Rb{ruby}_Tk{ticket}_{gameID}_Lv{level}"

                # backup เฉพาะที่กาชารอบนี้ได้เรนเจอร์ใน configRangers.ini เดิมเช็คแค่ gachaUnits != []
                # สุ่มได้อะไรก็ตามก็ไป backup หมด (9 ไฟล์ มีได้ตัวเป้าหมายจริงแค่ 1)
                # เทียบตรงตัวเหมือนตอน stop_when_found ใน apiGachaWithTicket
                gotTarget = any(RANGERSCONFIG.get(code.lower()) for code in gachaUnits)
                if gotTarget:
                    exportedFile = exportFileFromExecuteToBackup(newName=fileName)
                else:
                    exportedFile = exportFileFromExecuteToOutput(newName=fileName)
                force_stop_LINE_Rangers()
                sessionStatus = "OK"
                break

            except TimeoutError as e:
                lastError = f"timeout: {e}"
                captureScreenError(str(e))
                log(f"Restart bot due to timeout (attempt {attempt}): {e}")
                continue
            except Exception as e:
                lastError = str(e)
                captureScreenError(str(e))
                log(f"Unexpected error (attempt {attempt}): {e}")
                traceback.print_exc()
                continue

        if noMoreFiles:
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break

        if sessionStatus == "FAIL" and sessionFile and os.path.isfile(os.path.join("execute", sessionFile)):
            # retry ครบแล้วยังไม่ผ่าน ย้ายไป login failed จะได้รู้ว่าไฟล์ไหนต้องเอากลับมาทำใหม่
            # (ถ้าสำเร็จไฟล์ต้นฉบับยังอยู่ใน execute เหมือนเดิม เพราะตัวที่ส่งออกดึงจากเกม)
            try:
                exportFileFromExecuteToLoginFailed()
                exportedFile = os.path.join("login failed", sessionFile)
            except Exception as e:
                log(f"move to login failed error: {e}")

        if accountId and not duplicateAccount and not gachaDone:
            # จองบัญชีไว้แต่สุ่มไม่สำเร็จ ปล่อยให้ไฟล์ซ้ำของบัญชีนี้ (ถ้ามี) ได้สุ่มแทน
            _releaseAccountThisRun(accountId)

        # log ก่อนเช็คว่ามีไฟล์เหลือไหม เดิม break ก่อนถึงตรงนี้ session สุดท้ายของทุกเครื่องเลยหาย
        logSession(sessionStart, sessionStatus, GAMEID, currentLevelValue, rangerNames,
                   gachaStatus, usedAttempts, exportedFile, lastError)
        print("========== End ==========", flush=True)


def apiForceStage(targetStage=None, fromStage=None):
    """ดันด่าน main stage ของบัญชีปัจจุบันผ่าน API ล้วน (ไม่เปิดเกม ไม่แตะ adb)

    ใช้ tools/stage_forge.py: /stage/enter -> ประกอบ battle log ที่เซิร์ฟเวอร์ยอมรับ
    (sn_e/win_e = RSA ของคีย์ที่ enter แจกมา, icu = AES ที่ผูกกับ rsn+battleSn) -> /stage/save
    เริ่มจากด่านถัดจากด่านที่เคลียร์ล่าสุด (อ่าน /stage/last เพราะ lastStageCode ขยับตอน "เข้า"
    ด่าน ไม่ใช่ตอนเคลียร์) ไปจนถึง targetStage (ดีฟอลต์ = STAGEEND จาก config)
    stage_forge เว้นจังหวะระหว่างด่านให้เอง (DEFAULT_DELAY) กัน rate limit ของเซิร์ฟเวอร์

    คืน dict {"cleared", "target", "stop", "levelAfter"} - stop คือเหตุที่หยุด
    (done/locked/hearts/auth/flagged/failed)
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import stage_forge

    cookie = getLFAC()
    player = stage_forge.player_info(cookie)
    rsn = player.get("rsn")
    if not rsn:
        raise Exception("force stage: อ่าน rsn ของบัญชีไม่ได้ (icu ผูกกับ rsn ถ้าผิดจะแพ้เงียบ ๆ)")

    target = int(targetStage or STAGEEND or stage_forge.LAST_STAGE)
    first = int(fromStage or stage_forge.start_stage(cookie, player))
    if first > target:
        log(f"force stage: ถึงด่าน {target} แล้ว (ด่านถัดไปคือ st{first:02d}) ข้าม")
        return {"cleared": first - 1, "target": target, "stop": "done",
                "levelAfter": player.get("level")}

    log(f"force stage: st{first:02d} -> st{target:02d} (level {player.get('level')})")
    cleared, reason = stage_forge.clear_range(cookie, rsn, first, target, progress=log)
    level = player.get("level")
    try:
        level = stage_forge.player_info(cookie).get("level", level)
    except Exception:
        pass    # อ่านเลเวลใหม่ไม่ได้ ไม่ใช่เหตุให้ทั้ง session พัง
    log(f"force stage: เคลียร์ถึง st{cleared:02d}/{target} (หยุดเพราะ {reason}) level -> {level}")
    return {"cleared": cleared, "target": target, "stop": reason, "levelAfter": level}


def apiLevelUpByStage1(targetLevel=None):
    """ดันเลเวลบัญชีปัจจุบันให้ถึง targetLevel (ดีฟอลต์ LEVELTARGET=3) ด้วยการเล่น st01 ซ้ำผ่าน API ล้วน

    วัดจริง 2026-09-23 กับ guest ใหม่: เคลียร์ st01 ได้ 600 exp ทุกรอบ (รอบแรกและรอบซ้ำเท่ากัน)
    เลเวล 1 -> 2 หลังรอบแรก และ -> 3 หลังรอบสอง เลเวลอัพเติม heart ให้ด้วย ไม่ต้องข้าม tutorial
    ถ้าเลเวลถึงอยู่แล้วไม่ยิงอะไรนอกจากอ่านข้อมูลผู้เล่น

    คืน dict {"level", "plays", "stop"} - stop: done/hearts/auth/flagged/locked/failed/maxplays
    (flagged = เซิร์ฟเวอร์ตีธง 102204 ห้ามเล่นต่อ)
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import stage_forge

    target = int(targetLevel or LEVELTARGET)
    cookie = getLFAC()
    player = stage_forge.player_info(cookie)
    level = int(player.get("level") or 0)
    if level >= target:
        log(f"level-up: เลเวล {level} ถึง {target} แล้ว ข้าม")
        return {"level": level, "plays": 0, "stop": "done"}
    rsn = player.get("rsn")
    if not rsn:
        raise Exception("level-up: อ่าน rsn ของบัญชีไม่ได้ (icu ผูกกับ rsn ถ้าผิดจะแพ้เงียบ ๆ)")

    log(f"level-up: เลเวล {level} -> {target} ด้วย st01 ซ้ำ")
    level, plays, reason = stage_forge.level_up(cookie, rsn, target, progress=log)
    log(f"level-up: จบที่เลเวล {level} หลังเล่น {plays} รอบ (หยุดเพราะ {reason})")
    return {"level": level, "plays": plays, "stop": reason}


def startBotStage_API_headless(deviceSerial=""):
    """โหมด Stage (headless แท้): หยิบไฟล์ ID จาก input/ -> relogin -> ดันด่าน -> export

    โครงเดียวกับ startBotLogin_API_headless ต่างกันที่ขั้นกลาง: แทนกาชา/รับของ จะเรียก
    apiForceStage() ดันด่าน main stage ถึงด่านที่ตั้งไว้ใน config (stageend) แล้วส่งไฟล์ออก
    output/ พร้อมเลเวลใหม่ในชื่อไฟล์ ไม่เปิดเกม ไม่ต่อ adb

    บัญชีที่เซิร์ฟเวอร์ตีธงโกง (stop=flagged) จะถูกย้ายไป 'login failed' แทนการส่งออก
    จะได้ไม่ปนกับไอดีที่ใช้ได้
    """
    global GAMEID
    MAXATTEMPTS = 3

    setUpHeadless(deviceSerial)
    log(f"Bot running headless (Stage -> st{STAGEEND}) on {deviceSerial}")

    while True:
        GAMEID = ""
        sessionStart = time.time()
        sessionStatus = "FAIL"
        currentLevelValue = 0
        stageStatus = "-"
        exportedFile = ""
        lastError = ""
        usedAttempts = 0
        sessionFile = ""
        noMoreFiles = False
        stageDone = False        # ดันด่านไปแล้ว: retry ขั้นหลังห้ามดันซ้ำ
        flagged = False
        rangerNames = ""

        print("========= Start =========", flush=True)
        print(">>> startBotStage (headless) <<<", flush=True)

        for attempt in range(1, MAXATTEMPTS + 1):
            usedAttempts = attempt
            try:
                force_stop_LINE_Rangers()   # headless: แค่ล้าง LFACCACHE บังคับ relogin ไฟล์นี้ใหม่
                if not sessionFile:
                    try:
                        importFileFromInputToExecute()
                    finally:
                        sessionFile = FILENAME
                    if not sessionFile:
                        noMoreFiles = True
                        break
                else:
                    reImportFileInExecute()

                getLFAC(timeout=60)         # relogin จากไฟล์ ได้ LF_AC สด

                if not stageDone:
                    result = apiForceStage()
                    stageDone = True
                    flagged = result["stop"] == "flagged"
                    stageStatus = "st%d/%s" % (result["cleared"], result["stop"])
                else:
                    log(f"Stage already pushed this session ({stageStatus}) - skip")

                rangerNames, level, ruby, ticket, gameID = getAccoutInfo()
                currentLevelValue = level
                fileName = f"{rangerNames}_Rb{ruby}_Tk{ticket}_{gameID}_Lv{level}"

                if flagged:
                    # เซิร์ฟเวอร์ตีธง 102204 = บัญชีนี้ถูกจับได้ อย่าเอาไปปนกับไอดีที่ขายได้
                    exportFileFromExecuteToLoginFailed()
                    exportedFile = os.path.join("login failed", sessionFile)
                else:
                    exportedFile = exportFileFromExecuteToOutput(newName=fileName)
                force_stop_LINE_Rangers()
                sessionStatus = "OK" if not flagged else "FLAG"
                break

            except TimeoutError as e:
                lastError = f"timeout: {e}"
                log(f"Restart bot due to timeout (attempt {attempt}): {e}")
                continue
            except Exception as e:
                lastError = str(e)
                log(f"Unexpected error (attempt {attempt}): {e}")
                traceback.print_exc()
                continue

        if noMoreFiles:
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break

        if sessionStatus == "FAIL" and sessionFile and os.path.isfile(os.path.join("execute", sessionFile)):
            try:
                exportFileFromExecuteToLoginFailed()
                exportedFile = os.path.join("login failed", sessionFile)
            except Exception as e:
                log(f"move to login failed error: {e}")

        logSession(sessionStart, sessionStatus, GAMEID, currentLevelValue, rangerNames,
                   stageStatus, usedAttempts, exportedFile, lastError)
        print("========== End ==========", flush=True)


def startBotLevel3_API_headless(deviceSerial=""):
    """โหมด Login Lv3 (headless แท้): เหมือน Login ทุกอย่าง แต่ก่อนรับของ/กาชาจะเช็คเลเวล
    ถ้ายังไม่ถึง LEVELTARGET (3) ให้เล่น st01 ซ้ำผ่าน API จนถึง แล้วค่อยทำขั้นที่เหลือเหมือน Login

    ไฟล์ที่ดันเลเวลไม่ถึง (heart หมด/เซิร์ฟเวอร์ปฏิเสธ) หรือโดนตีธง 102204 จะถูกย้ายไป 'login failed'
    แทนการส่งออก output/ จะได้ไม่มีไอดีเลเวลต่ำปนกับที่ใช้ได้ (เอากลับมาทำใหม่ทีหลังได้)
    """
    global GAMEID
    MAXATTEMPTS = 3

    setUpHeadless(deviceSerial)
    log(f"Bot running headless (Login Lv{LEVELTARGET}) on {deviceSerial}")

    while True:
        GAMEID = ""
        sessionStart = time.time()
        sessionStatus = "FAIL"
        currentLevelValue = 0
        gachaStatus = "-"
        exportedFile = ""
        lastError = ""
        usedAttempts = 0
        sessionFile = ""
        noMoreFiles = False
        gachaDone = False
        gachaUnits = []
        rangerNames = ""
        accountId = ""
        duplicateAccount = False
        levelDone = False        # ดันเลเวลไปแล้ว: retry ขั้นหลังห้ามเล่นซ้ำ
        levelStop = ""
        rejected = False         # flagged/ดันไม่ถึง -> login failed

        print("========= Start =========", flush=True)
        print(f">>> startBotLevel{LEVELTARGET} (headless) <<<", flush=True)

        for attempt in range(1, MAXATTEMPTS + 1):
            usedAttempts = attempt
            try:
                force_stop_LINE_Rangers()   # headless: แค่ล้าง LFACCACHE บังคับ relogin ไฟล์นี้ใหม่
                if not sessionFile:
                    try:
                        importFileFromInputToExecute()
                    finally:
                        sessionFile = FILENAME
                    if not sessionFile:
                        noMoreFiles = True
                        break
                else:
                    reImportFileInExecute()

                getLFAC(timeout=60)         # relogin จากไฟล์ ได้ LF_AC สด (ไม่ผ่าน = ไปที่ except ด้านล่าง)

                if not accountId:
                    accountId = GAMEID or getGameID()
                    if not _claimAccountThisRun(accountId):
                        duplicateAccount = True
                        gachaDone = True
                        gachaStatus = "dup-account"
                        log(f"Account {accountId} already done by another file this run - skip rewards/gacha")

                if not levelDone:
                    result = apiLevelUpByStage1()
                    levelDone = True
                    levelStop = result["stop"]
                    if result["stop"] == "flagged" or result["level"] < LEVELTARGET:
                        rejected = True
                        lastError = (f"level-up ไม่ถึง {LEVELTARGET}: ได้เลเวล {result['level']} "
                                     f"หลังเล่น {result['plays']} รอบ (หยุดเพราะ {result['stop']})")
                        log(lastError)
                else:
                    log(f"Level-up already done this session ({levelStop}) - skip")

                if not rejected and not gachaDone:
                    try:
                        apiAcceptAllRewards()                   # ใช้ api รับของแจกทั้งหมด
                        if GACHARANGER:
                            gachaUnits = apiGachaWithTicket(gacharangergroup=GACHARANGERGROUP, gacha_cycles=RGACHACYCLES)
                        gachaDone = True
                        gachaStatus = LASTGACHASTATUS
                    except Exception as e:
                        gachaStatus = "error"
                        lastError = str(e)
                        log(f"API step failed (ID ยังใช้ได้ ส่งออกต่อ): {e}")
                        traceback.print_exc()
                elif gachaDone and not duplicateAccount:
                    log(f"Gacha already done this session ({gachaStatus}) - skip")

                rangerNames, level, ruby, ticket, gameID = getAccoutInfo()
                currentLevelValue = level
                fileName = f"{rangerNames}_Rb{ruby}_Tk{ticket}_{gameID}_Lv{level}"

                if rejected:
                    exportFileFromExecuteToLoginFailed()
                    exportedFile = os.path.join("login failed", sessionFile)
                    sessionStatus = "FLAG" if levelStop == "flagged" else "LOWLV"
                else:
                    gotTarget = any(RANGERSCONFIG.get(code.lower()) for code in gachaUnits)
                    if gotTarget:
                        exportedFile = exportFileFromExecuteToBackup(newName=fileName)
                    else:
                        exportedFile = exportFileFromExecuteToOutput(newName=fileName)
                    sessionStatus = "OK"
                force_stop_LINE_Rangers()
                break

            except TimeoutError as e:
                lastError = f"timeout: {e}"
                log(f"Restart bot due to timeout (attempt {attempt}): {e}")
                continue
            except Exception as e:
                lastError = str(e)
                log(f"Unexpected error (attempt {attempt}): {e}")
                traceback.print_exc()
                continue

        if noMoreFiles:
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break

        if sessionStatus == "FAIL" and sessionFile and os.path.isfile(os.path.join("execute", sessionFile)):
            try:
                exportFileFromExecuteToLoginFailed()
                exportedFile = os.path.join("login failed", sessionFile)
            except Exception as e:
                log(f"move to login failed error: {e}")

        if accountId and not duplicateAccount and not gachaDone:
            _releaseAccountThisRun(accountId)

        logSession(sessionStart, sessionStatus, GAMEID, currentLevelValue, rangerNames,
                   gachaStatus, usedAttempts, exportedFile, lastError)
        print("========== End ==========", flush=True)


def _headlessCreateAccount():
    """สร้างบัญชี guest ใหม่แบบ headless แท้ (ไม่แตะ device/เกม) เขียนไฟล์ .xml ลง execute/

    ยิง Trident guest-mint -> refresh -> authorize -> GET /v12.3/signup/platform (สร้าง player
    ฝั่ง rangers) ได้ LF_AC สดกลับมา จุดสำคัญ: ข้อสรุปเก่าที่ว่า "first-login ของ guest ใหม่ต้อง
    เปิดเกม/ต้อง frida/ต้องมี appSecret" นั้นผิด — แค่ยิงผิด endpoint (เดิมยิง /v12.3/login ซึ่งไว้
    สำหรับคนเก่า 401 กับบัญชีใหม่) endpoint ที่สร้าง player จริงคือ /v12.3/signup/platform ซึ่ง
    ไม่ pinned และไม่ต้องมี appSecret ส่งแค่ cookie cc+udid เดียวกับตอน relogin (ดู tools/new_account.py)

    จากนั้นสร้างไฟล์ shared_prefs (_LINE_COCOS_PREF_KEY.xml) แบบเดียวกับที่เกมเขียน วางไว้ใน
    execute/ (ตั้ง FILENAME) เพื่อให้ exportFileFromExecuteTo* ย้ายออก output/backup ได้ตามปกติ
    คืน dict: gameId(mid, T0FF...), rsn, lf_ac, udid, level, ruby, coin
    """
    global FILENAME
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import new_account as na
    from account_file import build_pref_xml

    device_id = na.secrets.token_hex(16)   # Trident SDK DeviceId
    udid = na.secrets.token_hex(16)        # เกม uuid ของตัวเอง (_DEVICE_UUID_KEY = คีย์ AES ของโทเค็น)
    guest = na.register_guest(device_id)   # mint บัญชี LINE จริง (userKey/userToken/refreshUserToken)
    cc = na.refresh_token(device_id, guest["refreshUserToken"])
    na.authorize(device_id, cc)
    session = na.signup_platform(cc, udid)  # สร้าง player ฝั่ง rangers -> LF_AC + starter ruby/coin
    if not session or not session.get("lf_ac"):
        # แนบ HTTP status ของ signup ไว้ในข้อความ แยก 429 (rate-limit ชั่วคราว) จากเหตุจริงอื่น
        raise Exception(f"headless signup ล้มเหลว (HTTP {na.LAST_SIGNUP_HTTP}) - ไม่ได้ LF_AC "
                        f"(บัญชีถูก mint แล้ว รันซ้ำ/--resume ได้)")

    lf_ac = session["lf_ac"]
    gameId = session.get("mid") or guest.get("userKey")
    rsn = session.get("rsn") or ""

    # เขียนไฟล์บัญชีลง execute/ ตั้งชื่อจาก gameId (ไม่ชนกันข้าม worker เพราะแต่ละบัญชี mid ไม่ซ้ำ)
    os.makedirs("execute", exist_ok=True)
    FILENAME = f"{gameId}.xml"
    with open(os.path.join("execute", FILENAME), "w", encoding="utf-8") as f:
        f.write(build_pref_xml(lf_ac, udid, na.NATION, na.LANG))

    log(f"headless signup OK rsn={rsn} mid={gameId} level={session.get('level')} "
        f"ruby={session.get('ruby')} coin={session.get('coin')}")
    return {"gameId": gameId, "rsn": rsn, "lf_ac": lf_ac, "udid": udid,
            "level": session.get("level"), "ruby": session.get("ruby"), "coin": session.get("coin")}


def startBotGenID_API_headless(deviceSerial=""):
    """สร้างไอดีใหม่แบบ headless แท้ (ไม่แตะ device/เกม) ผ่าน /v12.3/signup/platform แล้วรับของ + กาชา

    โครงเทียบเท่า startBotLogin_API_headless แต่แทนที่จะ relogin จากไฟล์ input จะ MINT บัญชีใหม่เอง:
      mint guest -> signup สร้าง player -> รับของแจก + สุ่มกาชาผ่าน API -> export ไฟล์ .xml ออก output/backup

    บัญชีที่สร้างเริ่มที่ level 1 (ruby 20, ตั๋ว 0) จากนั้นดันเลเวลให้ถึง LEVELTARGET (3) ด้วยการเล่น
    st01 ซ้ำผ่าน API (apiLevelUpByStage1 - 2 รอบพอ) ก่อนรับของ/กาชา บัญชีที่ดันไม่ถึงหรือโดนตีธง
    จะถูกย้ายไป 'login failed' แล้วสร้างบัญชีใหม่แทน ผลลัพธ์ที่ออกจากโหมดนี้จึงเป็นเลเวล 3 เสมอ
    วน while True ไปเรื่อย ๆ (มีบัญชีให้สร้างไม่จำกัด) จนกว่าจะถูกสั่งหยุด (kill worker)
    """
    global GAMEID, LFACCACHE
    MAXATTEMPTS = 3

    setUpHeadless(deviceSerial)
    log(f"Bot running headless (GenID) on {deviceSerial}")

    while True:
        GAMEID = ""
        LFACCACHE = ""
        sessionStart = time.time()
        sessionStatus = "FAIL"
        currentLevelValue = 0
        gachaStatus = "-"
        exportedFile = ""
        lastError = ""
        usedAttempts = 0
        gachaDone = False
        gachaUnits = []
        rangerNames = ""
        accountId = ""

        print("========= Start =========", flush=True)
        print(f">>> genIDLevel{LEVELTARGET} (headless) <<<", flush=True)

        for attempt in range(1, MAXATTEMPTS + 1):
            usedAttempts = attempt
            try:
                # attempt ใหม่ = สร้างบัญชีใหม่สด (mint ก่อนหน้าถ้าพังหลัง signup ก็ปล่อยทิ้ง)
                LFACCACHE = ""
                account = _headlessCreateAccount()
                GAMEID = account["rsn"] or account["gameId"]
                accountId = account["gameId"]
                LFACCACHE = "LF_AC=" + account["lf_ac"]   # ทุก API ที่วิ่งผ่าน getLFAC ใช้โทเค็นนี้ทันที

                # ดันเลเวลให้ถึง LEVELTARGET ก่อนรับของ/กาชา: ผลลัพธ์ของโหมดนี้ต้องเป็นเลเวล 3 เท่านั้น
                levelUp = apiLevelUpByStage1()
                if levelUp["level"] < LEVELTARGET:
                    exportFileFromExecuteToLoginFailed()   # เก็บไฟล์ไว้ดู ไม่ปนกับ output
                    raise Exception(f"level-up ไม่ถึง {LEVELTARGET}: ได้เลเวล {levelUp['level']} "
                                    f"หลังเล่น {levelUp['plays']} รอบ (หยุดเพราะ {levelUp['stop']}) - สร้างบัญชีใหม่")

                if not gachaDone:
                    try:
                        apiAcceptAllRewards()                   # ใช้ api รับของแจกทั้งหมด
                        if GACHARANGER:
                            gachaUnits = apiGachaWithTicket(gacharangergroup=GACHARANGERGROUP, gacha_cycles=RGACHACYCLES)
                        gachaDone = True
                        gachaStatus = LASTGACHASTATUS
                    except Exception as e:
                        gachaStatus = "error"
                        lastError = str(e)
                        log(f"API step failed (ID ยังใช้ได้ ส่งออกต่อ): {e}")
                        traceback.print_exc()

                rangerNames, level, ruby, ticket, gameID = getAccoutInfo()
                currentLevelValue = level
                fileName = f"{rangerNames}_Rb{ruby}_Tk{ticket}_{gameID}_Lv{level}"

                # backup เฉพาะที่กาชารอบนี้ได้เรนเจอร์เป้าหมายใน configRangers.ini นอกนั้นลง output
                gotTarget = any(RANGERSCONFIG.get(code.lower()) for code in gachaUnits)
                if gotTarget:
                    exportedFile = exportFileFromExecuteToBackup(newName=fileName)
                else:
                    exportedFile = removeFileInExecute()
                sessionStatus = "OK"
                break

            except Exception as e:
                lastError = str(e)
                log(f"Unexpected error (attempt {attempt}): {e}")
                traceback.print_exc()
                continue

        # เก็บสรุป session ลง src/log/genid-sessions.csv (logSession พิมพ์ [SESSION] + error ให้ในตัว)
        logSession(sessionStart, sessionStatus, GAMEID, currentLevelValue, rangerNames,
                   gachaStatus, usedAttempts, exportedFile, lastError)
        print("========== End ==========", flush=True)










# <string name="_ENC_LF_AC_KEY">XlFUtmjasX4O0vMMM6Af9o5/2zDVVzXQK2bjNE+ZFXH3p/HdUJsHqam1BRwkQJlj/DNJ+DWwbBMp&#10;pba+UZZUHbFYW1hsiivxEAC8zT/SIUWsWu3yl0PDl8h/mMKo5jtNKExdeYoGSwBVzu1UuETTvBho&#10;qGPnZEdXHpwhK9pxHc0SJ+HcQNPS/qfGl/kawcyon9vvM3n0saMpjf6CT4yupsu6ppdYrSFxMHiB&#10;MPvB/wNEIEIBsH82VYYLgSSTUn+9kS0gvhKPTI3euoI4iQa0ENyH69NtLqfbdjICJ1WsEO3a/V/x&#10;oQo/1GmqCJuXnNCqDtj7llq3th49YNuA3UJk03JRzvjVgexjZYkY820sHfrYYczyTZT6PHd50X3n&#10;LPxpisIvgMWxxATs5SoFDsVYgQ==&#10;    </string>
