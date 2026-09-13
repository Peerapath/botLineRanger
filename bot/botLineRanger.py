# botLineRanger.py
from datetime import datetime
from ppadb.client import Client as AdbClient
import cv2
import numpy as np
import os
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
import pytesseract
import difflib
import uiautomator2 as u2
import atexit
import nemu_capture
import main as mai
pytesseract.pytesseract.tesseract_cmd = r"src\Tesseract-OCR\tesseract.exe"


####################################################### function ########################################################
####################################################### function ########################################################
####################################################### function ########################################################


# connect ไปยัง adb server (ปกติ 127.0.0.1:5037)
client = AdbClient(host="127.0.0.1", port=5037)
DEVICESERIAL = ""
DEVICE = None
U2DEVICE = None  # uiautomator2 device (ใช้ minitouch ส่ง touch event เลียนแบบ touch จริง)
TAP_DURATION = 0.1  # วินาที — tap() กดค้างนานเท่านี้ก่อนปล่อย ให้แน่ใจว่าเกมรับ event

########## config ##########
STAGEEND = 150
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


def setUp(deviceSerial):
    print(f"========= Setup And Config v{mai.CURRENT_VERSION} =========")
    global GACHARANGER, GACHARANGERGROUP, TAP_DURATION, RBTKPOSITION, UPDATERBTK, RBTK, DEVICE, DEVICESERIAL, STAGEEND, AUTOUSEITEM, \
        CHANGEID, AUTOMODE, LOSTCOUNT, GIFTBOX, BUYFRIEND, HIGHERSTAGE, RANGERSCONFIG, GEARS, \
        RANGERINTEAM, MAXMINERALCOST, CLOSEPOPUP, RSELCTIONEVENT, AUTOTEAM, ACCEPTPASS, \
        ACCEPT7DAY, RGACHACYCLES, RGACHAMODE, RSTOPWHENFOUND, TIMEINTERVAL, RUSERUBY, EXCHANGEGACHATICKET, \
        GSELECTIONEVENT, GSTOPWHENFOUND, GUSE200RUBY, GGACHAMODE, GGACHACYCLES, \
        BUYLEONARD9, BUYRUBY, BUYTICKET, cooldowncapturescreen, timeoutopengame, current_gacha_cycles, \
        usenemu, _nemu_next_try, U2DEVICE
    HIGHERSTAGE = 0
    RBTK = ""
    devices = client.devices()
    for dev in devices:
        if dev.serial[-4:] == deviceSerial[-4:]:
            DEVICE = dev
            break
    DEVICESERIAL = DEVICE.serial.replace(":", "_")

    # เชื่อม uiautomator2 (ใช้ minitouch ส่ง touch event ที่เกมยอมรับ)
    # u2.connect() เรียก start_uiautomator() ทันที ซึ่ง push jar แล้วรอ server ได้ถึง 30 วิ
    # และโยน LaunchUiAutomationError / HTTPError ได้ — error พวกนี้ไม่เข้าเงื่อนไข
    # _isInjectPermissionError และไม่ได้เกิดใน _u2Inject ด้วย ปล่อยให้ throw ตรงนี้
    # เท่ากับฆ่ารันทิ้ง ทั้งที่ไฟล์นี้เดิมเป็น adb ล้วนและไม่เคยพังเพราะ u2 มาก่อน
    try:
        U2DEVICE = u2.connect(DEVICE.serial)
        log(f"Connected uiautomator2: {DEVICE.serial}")
    except Exception as e:
        U2DEVICE = None
        log(f"เชื่อม uiautomator2 ไม่ได้ ({e.__class__.__name__}: {e}) -> tap() ถอยไปใช้ adb input swipe")

    config = configparser.ConfigParser()
    with open("src\config.ini", "r", encoding="utf-8") as f:
        config.read_file(f)

    STAGEEND = config.getint("settings", "stageend")
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

    configRanger = configparser.ConfigParser()
    configRanger.read("src\configRangers.ini", encoding="utf-8")
    RANGERSCONFIG = dict(configRanger["rangers"])

    configGear = configparser.ConfigParser()
    configGear.read("src\configGears.ini", encoding="utf-8")
    GEARS = dict(configGear["gears"])
    

def captureScreenAndSave(filename):
    result = DEVICE.screencap()
    with open(filename, "wb") as f:
        f.write(result)


def captureScreenError(error):
    return
    formatted_datetime = datetime.now().strftime("%H-%M-%S")
    # ลบตัวอักษรที่ใช้ไม่ได้บน Windows
    safe_error = re.sub(r'[^a-zA-Z0-9._-]', '_', error)
    file = f"{formatted_datetime}_{DEVICESERIAL}_{safe_error}"
    filename = rf"src\image\screen\{file}.png"
    result = DEVICE.screencap()
    with open(filename, "wb") as f:
        f.write(result)


def _screencapFrame():
    """ทางเดิม: ให้ emulator encode PNG แล้วส่งผ่าน ADB (~213 ms, กิน CPU emulator ~229 ms)"""
    result = DEVICE.screencap()
    nparr = np.frombuffer(result, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def _closeNemu():
    global _nemu
    if _nemu is not None:
        _nemu.close()
        _nemu = None


atexit.register(_closeNemu)


def _grabFrame():
    """คืนภาพ BGR 1 เฟรม -- ใช้ MuMu native capture ถ้าต่อได้ ไม่งั้นถอยไป screencap เดิม

    nemu อ่าน framebuffer ผ่าน shared memory ตรง ๆ ได้ภาพเหมือน screencap ทุก pixel
    (วัดแล้ว absdiff = 0) แต่เร็วกว่า ~92 เท่าและแทบไม่กิน CPU ของ emulator
    ถอยกลับได้ 3 จังหวะ: ต่อไม่ได้ตั้งแต่แรก, ล้มกลางทาง (ผู้ใช้ปิด/รีสตาร์ต MuMu),
    และกรณีเงียบที่สุดคือต่อติดแต่ไม่ render จริง -- ดูคอมเมนต์ตรงที่นับเฟรมดำ
    """
    global _nemu, _nemu_next_try, _nemu_black_streak

    # ยังไม่มี handle และยังไม่เลิกลอง -> ลองต่อ โดยยืมภาพ screencap เป็นขนาดอ้างอิง
    if _nemu is None and _nemu_next_try is not None and time.time() >= _nemu_next_try:
        frame = _screencapFrame()
        _nemu = nemu_capture.create_for_serial(DEVICE.serial, frame.shape, log)
        if _nemu is None:
            _nemu_next_try = None       # ใช้ไม่ได้ตั้งแต่แรก (ไม่ใช่ MuMu ฯลฯ) -> ไม่ลองซ้ำ
        _nemu_black_streak = 0
        return frame                    # ถ่ายมาแล้วก็ใช้เฟรมนี้เลย ไม่ต้องถ่ายซ้ำ

    if _nemu is not None:
        try:
            frame = _nemu.grab()
        except Exception as e:
            log(f"[nemu] อ่านภาพไม่สำเร็จ ({e}) -> กลับไปใช้ screencap")
            _closeNemu()
            _nemu_next_try = time.time() + NEMU_RETRY_SEC   # MuMu อาจแค่รีสตาร์ต ลองใหม่ทีหลัง
            return _screencapFrame()

        # ถ้า nemu ต่อติดแต่ไม่ render จริง มันจะคืนภาพดำเรื่อย ๆ โดยไม่มี error
        # ซึ่งจะกลายเป็นบอทค้างแบบไม่มีสาเหตุให้ดู แต่จอดำจริง ๆ ก็เกิดได้ตลอด
        # (ตอนเปิดเกม, ตอนโหลด) จึงแยกสองกรณีนี้ด้วย screencap ก็ต่อเมื่อดำติดกันนานผิดปกติ
        if float(frame.std()) >= 3.0:
            _nemu_black_streak = 0
        else:
            _nemu_black_streak += 1
            if _nemu_black_streak >= NEMU_BLACK_STREAK:
                _nemu_black_streak = 0
                ref = _screencapFrame()
                if float(ref.std()) >= 3.0:     # screencap เห็นภาพ แต่ nemu ไม่เห็น = nemu เสีย
                    log("[nemu] คืนภาพดำติดกันแต่ screencap เห็นภาพ -> กลับไปใช้ screencap")
                    _closeNemu()
                    _nemu_next_try = None
                    return ref
                # ดำทั้งคู่ = จอดำจริง ไม่ใช่ความผิด nemu ใช้ต่อได้
        return frame

    return _screencapFrame()


def captureScreen(cooldowncaptures:int=None):
    """ดึงภาพจาก device 1 ครั้ง แล้วเก็บไว้ใน buffer"""
    global current_screen, current_screen_gray, _last_capture_time
    # รอเฉพาะเวลาที่เหลือตั้งแต่ capture ล่าสุด (ไม่รอเต็ม cooldown ถ้า logic ใช้เวลาไปแล้ว)
    cooldown = cooldowncapturescreen
    if cooldowncaptures is not None:
        cooldown = cooldowncaptures
    # nemu ถ่ายเร็วกว่า screencap ~90 เท่า ลูป poll ถี่ (waitLoading ตั้ง cooldown 0.001)
    # จึงหมุนเร็วขึ้น 5 เท่าและดัน CPU host จาก 14% เป็น 112% ของ 1 core ต่อ 1 บอท
    # -- ที่กินคือ matchTemplate ไม่ใช่การถ่าย ใส่เพดานให้ยังไวกว่า screencap เท่าตัว
    # แต่ไม่กินคอร์ทั้งใบ ตั้ง NEMU_MIN_INTERVAL = 0 ถ้าอยากปล่อยเต็มสปีด
    if _nemu is not None and cooldown < NEMU_MIN_INTERVAL:
        cooldown = NEMU_MIN_INTERVAL
    elapsed = time.time() - _last_capture_time
    remaining = cooldown - elapsed
    if remaining > 0:
        sleep(remaining)
    current_screen = _grabFrame()
    current_screen_gray = cv2.cvtColor(current_screen, cv2.COLOR_BGR2GRAY)
    _last_capture_time = time.time()
    return current_screen


def readImage(color=0):
    """อ่านจาก buffer ถ้าไม่มีภาพให้ถ่ายใหม่"""
    global current_screen, current_screen_gray
    if current_screen is None:
        captureScreen()
    if color == 0:
        return current_screen_gray
    else:
        return current_screen


def find(template_path, similarity=0.8, capture=True):
    """หา template ในภาพทั้งหน้าจอ"""
    if capture:
        captureScreen()
    img = readImage(0)
    # cv2.imshow("img", img)
    # cv2.waitKey()
    if template_path not in _template_cache:
        _template_cache[template_path] = cv2.imread(template_path, 0)
    template = _template_cache[template_path]

    if img is None or template is None:
        raise Exception(f"❌ ไม่พบภาพหรือเทมเพลต: {template_path}")

    result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    # เคสส่วนใหญ่ของการ poll คือ "หาไม่เจอ" คัดทิ้งด้วย minMaxLoc ก่อน (ไม่ต้องสร้าง
    # bool mask + index array ทั้งก้อน) แล้วค่อย np.where เฉพาะตอนเจอจริง
    # ห้ามใช้ maxLoc แทน: np.where คืน match แรกตามลำดับ raster ส่วน maxLoc คืน match
    # คะแนนสูงสุด ซึ่งคนละจุดกันได้เมื่อมีหลาย match
    if cv2.minMaxLoc(result)[1] < similarity:
        return None
    loc = np.where(result >= similarity)
    if len(loc[0]) > 0:
        y, x = loc[0][0], loc[1][0]
        h, w = template.shape
        return Region(int(x), int(y), w, h)
    return None


def regionFind(region:Region, template_path:str, similarity=0.8, capture=True):
    if capture:
        captureScreen()
    # crop เฉพาะส่วนของ region
    img = readImage()[region.y:region.y+region.h, region.x:region.x+region.w]
    if template_path not in _template_cache:
        _template_cache[template_path] = cv2.imread(template_path, 0)
    template = _template_cache[template_path]

    if img is None or template is None:
        raise Exception(f"❌ ไม่พบภาพหรือเทมเพลต: {template_path}")

    result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    if cv2.minMaxLoc(result)[1] < similarity:   # fast reject เหมือน find() ดูคอมเมนต์ที่นั่น
        return None
    loc = np.where(result >= similarity)
    if len(loc[0]) > 0:
        y, x = loc[0][0], loc[1][0]
        h, w = template.shape
        return Region(int(x+region.x), int(y+region.y), w, h)
    else:
        return None

def regionFindAll(region: Region, template_path, similarity=0.8, capture=True):
    """ค้นหารูปทั้งหมดในพื้นที่ Region เดียว (คล้าย findAll แต่ crop เฉพาะ region)"""
    if capture:
        captureScreen()

    # crop เฉพาะพื้นที่ที่กำหนด
    img = readImage()[region.y:region.y + region.h,
                      region.x:region.x + region.w]

    if template_path not in _template_cache:
        _template_cache[template_path] = cv2.imread(template_path, 0)
    template = _template_cache[template_path]
    if img is None or template is None:
        raise Exception(f"❌ ไม่พบภาพหรือเทมเพลต: {template_path}")

    result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(result >= similarity)

    h, w = template.shape
    matches = []
    seen_cells = set()
    cell_w = max(1, w // 2)
    cell_h = max(1, h // 2)

    for y, x in zip(*loc):
        cell = (int(x) // cell_w, int(y) // cell_h)
        if cell not in seen_cells:
            seen_cells.add(cell)
            # แปลงเป็นตำแหน่ง absolute บนหน้าจอ
            abs_x = region.x + int(x)
            abs_y = region.y + int(y)
            matches.append(Region(abs_x, abs_y, w, h))

    return matches


def _findAll(img, template_path, similarity=0.8):
    if template_path not in _template_cache:
        _template_cache[template_path] = cv2.imread(template_path, 0)
    template = _template_cache[template_path]
    if img is None or template is None:
        raise Exception(f"❌ ไม่พบภาพหรือเทมเพลต: {template_path}")

    result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(result >= similarity)

    h, w = template.shape
    matches = []
    seen_cells = set()
    cell_w = max(1, w // 2)
    cell_h = max(1, h // 2)

    for y, x in zip(*loc):
        cell = (int(x) // cell_w, int(y) // cell_h)
        if cell not in seen_cells:
            seen_cells.add(cell)
            matches.append(Region(int(x), int(y), w, h))

    return matches


def findAll(template_path, similarity=0.8):
    captureScreen()
    img = readImage()
    return _findAll(img, template_path, similarity)


def center(region=tuple):
    x, y, w, h = region
    return x + w//2, y + h//2


# ลูปเดิมวนซ้ำจนหมด timeout โดย capture ได้แค่ครั้งแรกครั้งเดียว (รอบถัดไป capture=False)
# ภาพที่ match จึงเป็นเฟรมเดิมทุกรอบ -> ผลลัพธ์รอบที่ 2 เป็นต้นไปเหมือนรอบแรกเสมอ
# (วัดแล้ว timeout=1 วน matchTemplate ~149 ครั้งได้คำตอบเดียวกันหมด กินเต็ม 1 คอร์)
# match ครั้งเดียวจึงให้ผลเท่ากันเป๊ะ ส่วนการ poll ซ้ำเป็นหน้าที่ของลูปข้างนอก
# (wait/waitVanish/waitLoading) ซึ่งเรียก capture ใหม่จริง ๆ และถูกกั้นด้วย cooldown อยู่แล้ว
def exists(template_path:str, similarity=0.8, timeout=1, capture=True):
    if timeout <= 0:            # ของเดิม while ไม่ทำงานเลย -> ไม่ capture และคืน None
        return None
    return find(template_path, similarity, capture)


def regionExists(region:Region, template_path:str, similarity=0.8, timeout=1, capture=True):
    if timeout <= 0:
        return None
    return regionFind(region, template_path, similarity, capture)


def _isInjectPermissionError(e: Exception) -> bool:
    """SecurityException: Injecting to another application requires INJECT_EVENTS permission"""
    msg = str(e)
    return "INJECT_EVENTS" in msg or "SecurityException" in msg


def _restartUiautomator():
    """UiAutomation ของ u2 หลุดสิทธิ์ inject เป็นครั้งคราว พอหลุดแล้วพังยาวจนกว่าจะรีสตาร์ต service"""
    global U2DEVICE
    try:
        U2DEVICE.stop_uiautomator()
    except Exception as e:
        log(f"stop uiautomator failed: {e}")
    sleep(1)
    try:
        U2DEVICE = u2.connect(DEVICE.serial)
        U2DEVICE.start_uiautomator()
        log("Restarted uiautomator service")
        return True
    except Exception as e:
        log(f"restart uiautomator failed: {e}")
        return False


def _u2Inject(action, shellFallback: str, retries: int = 2):
    for attempt in range(1, retries + 1):
        try:
            return action()
        except Exception as e:
            if not _isInjectPermissionError(e):
                raise
            log(f"u2 inject error ({attempt}/{retries}): {e.__class__.__name__} -> restart uiautomator")
            _restartUiautomator()
    log(f"u2 inject ใช้ไม่ได้ -> fallback shell: {shellFallback}")
    return DEVICE.shell(shellFallback)


def tap(x, y, duration=None):
    """กดค้าง duration วินาทีแล้วปล่อย (default TAP_DURATION)

    ใช้ long_click เพราะการกดค้างเกิดฝั่ง device (ส่ง ms ไปกับ jsonrpc)
    ไม่ใช่ touch.down + sleep + touch.up ที่กิน round-trip 2 รอบและเพี้ยนตามความหน่วงของ adb

    fallback ใช้ input swipe ที่ start=end (กดค้างอยู่กับที่) เพราะ input tap กดค้างไม่ได้
    """
    d = TAP_DURATION if duration is None else duration
    shellFallback = f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(d * 1000)}"

    # u2 ต่อไม่ติดตั้งแต่ setUp -> ไม่ต้องรอให้ _u2Inject ไปพังที่ None ก่อน
    # ไฟล์นี้เดิมขับ device ด้วย adb ล้วน การถอยกลับไปทางเดิมยังได้กดค้างเหมือนกัน
    if U2DEVICE is None:
        return DEVICE.shell(shellFallback)

    return _u2Inject(lambda: U2DEVICE.long_click(x, y, d), shellFallback)


def existsClick(template_path, similarity=0.8, timeout=1, capture=True):
    if timeout <= 0:
        return False
    template = find(template_path, similarity, capture)
    if template:
        point = template.getCenter()        # ไม่ตั้งชื่อ center จะไปบัง function center() ข้างบน
        tap(point.x, point.y)
        return Location(point.x, point.y)
    return False


def click(PSMRL, similarity=0.8, waitTime=0, duration=None):
    """duration=None ใช้ TAP_DURATION (0.1) ตามปกติ

    ส่งค่าต่ำ ๆ มาเฉพาะจุดที่กดรัวแล้วรับความหน่วงระดับ TAP_DURATION/ครั้งไม่ไหว
    เช่นลูปรบที่ยิง 10 tap ต่อรอบ ถ้าปล่อยให้กิน default รอบจะยืดจาก ~0.3 วิ
    เป็นหลักวินาที
    """
    target = None

    if isinstance(PSMRL, str) and os.path.exists(PSMRL):  
        reg = find(PSMRL, similarity)
        reg = reg.getCenter()
        target = reg.x, reg.y
    elif isinstance(PSMRL, Location):
        target = PSMRL.x, PSMRL.y
    elif isinstance(PSMRL, Region):
        reg = PSMRL.getCenter()
        target = reg.x, reg.y
    elif isinstance(PSMRL, tuple) and len(PSMRL) == 2:
        target = PSMRL
    elif isinstance(PSMRL, tuple) and len(PSMRL) == 4:
        target = center(PSMRL)

    if target:
        x, y = target
        # print("Click x:",x, "y:",y ," PSMRL:",PSMRL)
        tap(x, y, duration)
        wait(waitTime)
        return f"input tap {x} {y}"
    else:
        raise Exception(f"❌ ไม่พบภาพหรือเทมเพลต: {PSMRL}")


def getColor(PSMRL, similarity=0.8, capture=True):
    target = None
    if capture:
        captureScreen()
    image = readImage(cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("No image set in Region")
    
    
    if isinstance(PSMRL, str) and os.path.exists(PSMRL):
        # capture=False: ใช้เฟรมเดียวกับ image ด้านบน ของเดิม find() ถ่ายเฟรมใหม่
        # ทำให้เสีย cooldown ฟรีอีกรอบ และอ่านสีจากเฟรมเก่าด้วยพิกัดของเฟรมใหม่
        reg = find(PSMRL, similarity, capture=False)
        reg = reg.getCenter()
        target = reg.x, reg.y
    elif isinstance(PSMRL, Location):
        target = PSMRL.x, PSMRL.y
    elif isinstance(PSMRL, Region):
        reg = PSMRL.getCenter()
        target = reg.x, reg.y
    elif isinstance(PSMRL, tuple) and len(PSMRL) == 2:
        target = PSMRL
    elif isinstance(PSMRL, tuple) and len(PSMRL) == 4:
        target = center(PSMRL)

    x, y = target
    b, g, r = image[y, x]
    return Color(int(r), int(g), int(b))


def swipe(start_x, start_y, end_x, end_y, duration_ms=300):
    DEVICE.shell(f"input swipe {start_x} {start_y} {end_x} {end_y} {duration_ms}")

 # รอจอนเก่าจะหาไป

def wait(PS, similarity=0.8, timeout=300):
    if isinstance(PS, str) and os.path.exists(PS):
        start_time = time.time()
        while time.time() - start_time < timeout:
            waitLoading()                
            if exists(PS, similarity):
                return True
    elif isinstance(PS, float) or isinstance(PS, int):
        sleep(PS)
        return True
    return False

 # รอจอนเก่าจะเจอ

def waitVanish(path:str, similarity=0.8, timeout=120):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not exists(path, similarity):
            return 1
    raise TimeoutError(f"waitVanish timeout: {path} still visible after {timeout}s")


def numberOCR(region:Region, imagePrefix:str, similarity=0.8, min_dist=3):
    # crop เฉพาะส่วนของ region
    img = readImage(0)[region.y:region.y+region.h, region.x:region.x+region.w]
    digits_templates = {}
    for d in range(10):
        path = os.path.join(f"{imagePrefix}{d}.png")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Template not found: {path}")
        if path not in _template_cache:
            _template_cache[path] = cv2.imread(path, 0)
        digits_templates[d] = _template_cache[path]

    found_digits = []

    for digit, template in digits_templates.items():
        h, w = template.shape[:2]
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= similarity)
        for pt in zip(*loc[::-1]):
            x = pt[0]
            # ตรวจสอบว่าไม่มีตัวเลขอื่นใกล้กัน (min_dist)
            if all(abs(x - fd[0]) > min_dist for fd in found_digits):
                found_digits.append((x, digit))

    if not found_digits:
        # raise RuntimeError("No number found in region.")
        return None

    found_digits.sort(key=lambda x: x[0])
    number_str = "".join(str(d[1]) for d in found_digits)
    return number_str


def charOCR(region:Region, charTable, imagePrefix, similarity=0.8, min_dist=3):
    # crop เฉพาะส่วนของ region
    img = readImage(0)[region.y:region.y+region.h, region.x:region.x+region.w]

    # โหลด template จาก charTable
    templates = []
    for entry in charTable:
        p = entry["target"]
        char = entry["char"]
        path = os.path.join(f"{imagePrefix}\{p}")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Template not found: {path}")
        if path not in _template_cache:
            _template_cache[path] = cv2.imread(path, 0)
        templates.append((char, _template_cache[path]))

    found_chars = []

    # หาแต่ละตัวอักษรจาก template
    for char, template in templates:
        h, w = template.shape[:2]
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= similarity)

        for pt in zip(*loc[::-1]):  # (x, y) coordinate
            x = pt[0]
            # กันไม่ให้เจอซ้ำในระยะใกล้ ๆ กัน
            if all(abs(x - fc[0]) > min_dist for fc in found_chars):
                found_chars.append((x, char))

    if not found_chars:
        raise RuntimeError("❌ No character found in region.")

    # เรียงจากซ้ายไปขวา
    found_chars.sort(key=lambda x: x[0])
    result = "".join(fc[1] for fc in found_chars)

    return result

def textOCR(region:Region, crop=True, psm=7, imageProcessing=True):
    # อ่านภาพภายใน region (BGR)
    img = readImage(1)[region.y:region.y+region.h, region.x:region.x+region.w]

    # -----------------------------
    # 1. แปลงภาพ + ทำ Threshold
    # -----------------------------
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if imageProcessing:
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_LINEAR)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        thresh = gray
    # -----------------------------
    # 2. หา xOffset (จุดตัวอักษรแรกด้านขวา)
    # -----------------------------
    xOffset = findColorReverse(thresh, Color(0, 0, 0), tol=5)

    if xOffset is None:
        return ""  # ไม่พบตัวอักษรเลย

    h, w = thresh.shape
    if crop:
        crop_img = thresh[:, xOffset.x-2:w-xOffset.x+2]
    else:
        crop_img = thresh

    # -----------------------------
    # Debug (ดูผลการ crop)
    # -----------------------------
    # cv2.imshow("thresh", thresh)
    # cv2.imshow("crop", crop_img)
    # cv2.waitKey()

    # -----------------------------
    # 4. OCR ด้วย Tesseract
    # -----------------------------
    config = (
        f"--psm {psm} "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]'-. "
        "-c load_system_dawg=0 -c load_freq_dawg=0 "
    )

    text = pytesseract.image_to_string(crop_img, lang="eng", config=config)
    return text.strip()


def colorMatch(color: Color, colorRef: Color, tol=10):
    return (
        abs(color.r - colorRef.r) <= tol
        and abs(color.g - colorRef.g) <= tol
        and abs(color.b - colorRef.b) <= tol
    )

def regionFindColor(region: Region, colorRef: Color, tol=10, binary=False, capture=True):
    if not isinstance(region, Region):
        return None

    if capture:
        captureScreen()
    img = readImage(1)

    # ---------------------------------------------------------
    # แปลงภาพเป็น Binary ถ้าผู้ใช้ระบุ binary=True
    # ---------------------------------------------------------
    if binary:
        # ถ้าเป็น BGR → แปลงเป็น grayscale ก่อน
        if len(img.shape) == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        # Otsu Threshold -- ต้องคิดจาก histogram ทั้งเฟรม ห้าม crop ก่อนหน้านี้
        # ไม่งั้นได้ค่า threshold คนละค่าและผลลัพธ์เปลี่ยน
        _, img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # ไม่ต้อง cvtColor กลับเป็น 3 ช่อง: หลัง threshold แล้วทุก channel เท่ากัน
        # เทียบบน plane เดียวได้ mask เดิมเป๊ะ โดยไม่ต้องขยาย array ทั้งเฟรม

    crop = img[region.y:region.y+region.h, region.x:region.x+region.w]

    # ---------------------------------------------------------
    # Vectorized numpy scan แทน Python pixel loop
    # ---------------------------------------------------------
    if crop.ndim == 2:      # ภาพ 1 ช่อง (binary=True) -- ค่าเดียวใช้เทียบได้ทั้ง r/g/b
        v = crop.astype(np.int16)
        mask = (
            (np.abs(v - colorRef.r) <= tol) &
            (np.abs(v - colorRef.g) <= tol) &
            (np.abs(v - colorRef.b) <= tol)
        )
    else:
        b_ch = crop[:, :, 0].astype(np.int16)
        g_ch = crop[:, :, 1].astype(np.int16)
        r_ch = crop[:, :, 2].astype(np.int16)
        mask = (
            (np.abs(r_ch - colorRef.r) <= tol) &
            (np.abs(g_ch - colorRef.g) <= tol) &
            (np.abs(b_ch - colorRef.b) <= tol)
        )
    locs = np.argwhere(mask)
    if len(locs) > 0:
        y, x = locs[0]
        return Location(region.x + int(x), region.y + int(y))

    return None


def findColorReverse(img, colorRef: Color, tol=10):
    h, w = img.shape[:2]

    # Vectorized: pre-compute boolean mask ทั้ง array แล้วหา rightmost column
    if len(img.shape) == 2:
        # Grayscale — ทุก channel เท่ากัน
        val = img.astype(np.int16)
        r_ch = g_ch = b_ch = val
    else:
        b_ch = img[:, :, 0].astype(np.int16)
        g_ch = img[:, :, 1].astype(np.int16)
        r_ch = img[:, :, 2].astype(np.int16)

    mask = (
        (np.abs(r_ch - colorRef.r) <= tol) &
        (np.abs(g_ch - colorRef.g) <= tol) &
        (np.abs(b_ch - colorRef.b) <= tol)
    )

    # หา columns ที่มี match แล้วเลือก rightmost
    cols_with_match = np.where(mask.any(axis=0))[0]
    if len(cols_with_match) == 0:
        return None

    x = int(cols_with_match[-1])
    y = int(np.where(mask[:, x])[0][0])
    return Location(w - x, y)  # return semantics เดิมไม่เปลี่ยน (distance from right)


def pressBack():
    DEVICE.shell("input keyevent 4")


def pressHome():
    DEVICE.shell("input keyevent 3")



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


def getGachaRangerName():
    try:
        topLine = Region(405, 160, 373, 36)
        middleLine = Region(405, 184, 373, 36)
        bottomLine = Region(405, 189, 373, 36)
        text = ""

        # if regionFindColor(Region(541, 140, 100, 3), Color(255, 255, 10), 50) or regionFindColor(Region(541, 140, 100, 3), Color(140, 255, 255), 50):
        if isinstance(regionFindColor(Region(541, 128, 100, 3), Color(0, 0, 0), 10, binary=True), Location):
            topLineText = textOCR(topLine)
            bottomLineText = textOCR(bottomLine)
            text = extract_clean_text(topLineText, bottomLineText)
        else:
            text = extract_clean_text(textOCR(middleLine))

        return text
    except Exception:
        return ""


def gachaSelctionEvent(numEvent:int):
    if numEvent == 1:
        return
    elif numEvent == 2:
        click(Location(748, 307))
    else:
        for _ in range(numEvent-2):
            swipe(748, 307, 748, 183, 1000)
            click(Location(748, 307))


def fuzzy_match(ocr_text, target_text, threshold=1):
    # ลบช่องว่าง และทำเป็น lower case เพื่อลดความผิดพลาด
    o = re.sub(r"\s+", "", ocr_text).lower()
    t = re.sub(r"\s+", "", target_text).lower()

    ratio = difflib.SequenceMatcher(None, o, t).ratio()
    return ratio >= threshold, ratio

######################################################### logic #########################################################
######################################################### logic #########################################################
######################################################### logic #########################################################


def playMainStage(end=150, exportID=True):
    global STAGENUMBER, cooldowncapturescreen
    end = STAGEEND
    try:
        print("=========================", flush=True)
        log(f"Start Main Stage: End={end}")
        STAGENUMBER = 0
        quest7day = 0

        timeNow = time.time()  # เวลาปัจจุบัน
        currentLostCount = 0
        win = True

        waitLoading()
        if not exists(r"src\image\main_stage\main stage.png", 0.7, 0.25):
            waitLoading()
            goTo(r"src\image\go_to\main stage.png")


        while STAGENUMBER <= end:
            
            foundSkip = False
            levelNumber = 1
            useItemstorm = True
            useItemIce = True
            useItemShield = True

            waitLoading()
            sleep(0.2)
            while True:
                waitLoading()
                stage30 = exists(r"src\image\main_stage\stage30.png", similarity=0.8, timeout=0.1)
                iconProfile = exists(r"src\image\main_stage\profile.png", similarity=0.8, timeout=0.1)
                if stage30:
                    click(stage30.getBottomRight())
                    click(stage30.getBottomRight().offset(5, 5))
                    click(stage30.getBottomRight().offset(10, 10))
                    break
                elif iconProfile:
                    click(iconProfile.getBottomRight())
                    click(iconProfile.getBottomRight().offset(5, 5))
                    click(iconProfile.getBottomRight().offset(10, 10))
                    break
                else:
                    goTo(r"src\image\go_to\main stage.png")
                    wait(1)
                    if not exists(r"src\image\main_stage\profile.png", similarity=0.8):
                        while True:
                            if exists(r"src\image\main_stage\profile.png", similarity=0.8, timeout=0.1):
                                break
                            findProfile()

            waitLoading()
            if existsClick(r"src\image\main_stage\ANewAuto.png", timeout=0.01):
                for _ in range(10):
                    click(Location(480+random.randint(-400, 400), 90+random.randint(-10, 10)))
            startTine = time.time()
            while True:
                if exists(r"src\image\main_stage\stage.png", timeout=0.01, capture=True) and not exists(r"src\image\main_stage\profile.png", similarity=0.8, timeout=0.01, capture=False):
                    log("found stage.png")
                    break
                elif time.time() - startTine > 10:
                    log("Cust screen > 10 sec")
                    raise Exception(f"Cust screen > 10 sec")
                waitLoading()
                log(click(Location(480+random.randint(-400, 400), 90+random.randint(-10, 10))))

            if exists(r"src\image\main_stage\tutorial leonard loop.png", timeout=0.01):
                tutorialClickLoop(backButton=False)

            # wait(r"src\image\main_stage\stage.png")
            try:
                STAGENUMBER = int(numberOCR(Region(x=160, y=8, w=80, h=41), r"src\image\main_stage\numS", 0.85))
            except:
                pass
            print("=========================", flush=True)
            log(f"Stage: {STAGENUMBER}")
            if exportID:
                # เซฟ ID ก่อนเล่นด่าน
                updateFileWithStage()
            if STAGENUMBER > end:
                goTo(r"src\image\go_to\main stage.png")
                break

            autoOn = None
            if AUTOMODE == "bot":
                existsClick(r"src\image\main_stage\auto on.png", timeout=0.1)
            elif AUTOMODE == "game":
                existsClick(r"src\image\main_stage\auto.png", timeout=0.1)
            existsClick(r"src\image\main_stage\x2.png", timeout=0.1)

            if existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01):
                existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)
                existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)
                existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)

            startButton = exists(r"src\image\main_stage\start.png")
            nextButton = None
            if startButton:
                click(startButton)
            else:
                nextButton = exists(r"src\image\main_stage\next.png")
                if nextButton:
                    click(nextButton)

                if STAGENUMBER == 30:
                    waitLoading(timeOut=0.1)
                    skip()
                    for _ in range(10):
                        click((345, 380), waitTime=0.2) # เลือกเพื่อน

            if not waitLoading(timeOut=0.1):  # << ถ้าโหลดเกิน 1.5 นาที
                raise TimeoutError("Loading stuck > 90 sec")
            
            if STAGENUMBER > 30:
                if BUYFRIEND == "everyTime":
                    buyFriend()
                elif BUYFRIEND == "justLost" and not win:
                    buyFriend()

            existsClick(r"src\image\main_stage\start.png")

            _cooldowncapturescreen = cooldowncapturescreen
            cooldowncapturescreen = 0.001
            if not waitLoading(timeOut=0.01, cooldowncaptures=0.001):  # << ถ้าโหลดเกิน 2 นาที
                raise TimeoutError("Loading stuck > 180 sec")
            cooldowncapturescreen = _cooldowncapturescreen

            log(f"PLaying", end="")
            timer = time.time()
            startPlayTime = datetime.now()
            rangerCycle = 0
            _buy_every = BUYFRIEND == "everyTime"
            _buy_lost  = BUYFRIEND == "justLost"
            _auto_bot  = AUTOMODE == "bot"
            while True:
                rangerCycle += 1

                click((275, 515), waitTime=0.01, duration=0.05) # ranger 1
                click((375, 515), waitTime=0.01, duration=0.05) # ranger 2
                click((475, 515), waitTime=0.01, duration=0.05) # ranger 3
                click((575, 515), waitTime=0.01, duration=0.05) # ranger 4
                click((675, 515), waitTime=0.01, duration=0.05) # ranger 5

                captureScreen()
                if regionExists(Region(149, 33, 73, 31), r"src\image\main_stage\win.png", 0.8, timeout=0.02, capture=False):
                    win = True
                    currentLostCount = 0
                    stopPLayerTime = datetime.now()
                    playTime = stopPLayerTime - startPlayTime
                    minutes, seconds = divmod(playTime.seconds, 60)
                    print()
                    log(f"Win {minutes:02d}:{seconds:02d}")
                    break
                if regionExists(Region(480, 327, 199, 74), r"src\image\main_stage\lose cancel.png", timeout=0.02, capture=False):
                    win = False
                    currentLostCount += 1
                    stopPLayerTime = datetime.now()
                    playTime = stopPLayerTime - startPlayTime
                    minutes, seconds = divmod(playTime.seconds, 60)
                    print()
                    log(f"Lose {minutes:02d}:{seconds:02d}")
                    break

                timeNow = time.time()  # เวลาปัจจุบัน
                if STAGENUMBER == 30:
                    click((345, 380), waitTime=0.001, duration=0.05) # เลือกเพื่อน
                    click(slotItem1, waitTime=0.15, duration=0.05) # เพื่อน
                    click(slotItem1, waitTime=0.15, duration=0.05) # เพื่อน

                click(slotItem1, duration=0.05)
                click(slotItem2, duration=0.05)
                click(slotItem3, duration=0.05)
                click(slotItem4, duration=0.05)
                click(slotItem5, duration=0.05)

                if not autoOn and _auto_bot:
                    if 10 <= timeNow - timer:
                        autoOn = existsClick(r"src\image\main_stage\auto in game.png", timeout=0.1, capture=False)
                    if rangerCycle % 6 == 0:
                        click((150, 510), waitTime=0.05) # missile
                        click((775, 510), waitTime=0.05) # costs
                
                if datetime.now().second % 2 == 0:
                    print(".",end="", flush=True)
                
                waitLoading()
                
                if timeNow - timer > 300:  # << ถ้าเล่นเกิน 5 นาที
                    raise TimeoutError("PLaying stuck > 300 sec")

            # waitLoading
            if exists(r"src\image\home\UnKnown error.png", timeout=0.02):
                existsClick(r"src\image\main_stage\skip ok.png", timeout=0.02)
            existsClick(r"src\image\home\retry.png", timeout=0.02)


            levelUp = True
            timer = time.time()
            while True:
                timeNow = time.time()  # เวลาปัจจุบัน
                if timeNow - timer > 60:  # << ถ้าเล่นเกิน 1 นาที
                    raise TimeoutError("End PLayed stuck > 60 sec")
                
                waitLoading()
                captureScreen()
                if exists(r"src\image\main_stage\main stage.png", 0.7, timeout=0.1, capture=False):
                    waitLoading()
                    log(f"Break: Found main stage")
                    break

                if exists(r"src\image\tutorial\skip.png", 0.7, timeout=0.1, capture=False):
                    waitLoading()
                    log(f"Break: Found skip tutorial")
                    # if exists(r"src\image\main_stage\tutorial james.png", timeout=0.1):
                    foundSkip = True
                    break

                if exists(r"src\image\main_stage\lose cancel.png", timeout=0.1, capture=False) and exists(r"src\image\main_stage\resume for free.png", timeout=0.25, capture=False):
                    log(f"Break: Found lose")
                    break

                if exists(r"src\image\main_stage\tutorial leonard retry ok next.png", 0.7, timeout=0.1, capture=False):
                    if STAGENUMBER == 31 :
                        log(f"Break: Found tutorial retry ok next")
                        break
                    if colorMatch(getColor(Location(324, 440), capture=False), Color(140, 44, 231)):
                        existsClick(r"src\image\main_stage\clear bonus retry.png", timeout=0.1)
                    if colorMatch(getColor(Location(630, 440), capture=False), Color(8, 190, 206)):
                        existsClick(r"src\image\main_stage\clear bonus next.png", timeout=0.1)

                _level17 = exists(r"src\image\main_stage\level17.png", 0.6, 0.25, capture=False)
                if _level17 and levelUp:
                    levelUp = False
                    r = _level17
                    levelNumber = int(numberOCR(r, r"src\image\main_stage\level"))
                    log(f"LevelUp: {levelNumber}")
                    if levelNumber in [17, 18, 20, 40]:
                        for _ in range(7):
                            captureScreen()
                            if exists(r"src\image\home\skip.png", timeout=0.1, capture=False):
                                skip()
                            existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7, capture=False)
                            if exists(r"src\image\home\close.png", timeout=0.1, capture=False) or exists(r"src\image\home\back.png", timeout=0.1, capture=False):
                                break
                            if (nextButton):
                                click(nextButton, waitTime=0.1)
                            elif (startButton):
                                click(startButton, waitTime=0.1)
                        waitLoading()
                        log(f"Break: Found level: {levelNumber} to tutorial")
                        break
                
                if (nextButton):
                    click(nextButton)
                elif (startButton):
                    click(startButton)

                existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7)

            if exists(r"src\image\main_stage\lose cancel.png", timeout=0.5):
                if currentLostCount >= LOSTCOUNT:
                    print("========= Lost ==========")
                    log(f"CurrentLostCount:{currentLostCount} = LostCount:{LOSTCOUNT}")
                    return "lost"
                else:
                    upgradeCrystal()

            if levelNumber in [17, 18]:
                tutorialLevel17()

            if levelNumber == 40:
                goToHome()
                # tutorialTrain()

            if foundSkip and win:
                if STAGENUMBER == 2:
                    tutorial2()
                else:
                    tutorialInHomeScreen()

            if STAGENUMBER == 5 and win:
                tutorial5()

            if STAGENUMBER == 10 and win:
                if exists(r"src\image\home\choose a new ranger.png", timeout=0.001):
                    tutorial10()

            if STAGENUMBER == 12 and win:
                tutorial12()

            if STAGENUMBER == 15 and win:
                tutorial15()

            if STAGENUMBER == 29 and win:
                tutorial29()

            if STAGENUMBER == 31 and win:
                retryNextOk()

            if 3 < STAGENUMBER <= 12 and win:
                if quest7day <= 1:
                    # waitLoading()
                    # click((30, 25), waitTime=0.1) # ปุ่มย้อนกลับ
                    # waitLoading()
                    # tutorial7DayAndQuest()
                    goToHome()
                    click((480, 165), waitTime=0.5) # main stage
                    waitLoading()
                    quest7day += 1

            if levelNumber == 20:
                goToHome()
                # tutorialLevel20()

            if STAGENUMBER > end:
                print("========== End ==========")
                return "end"
        print("=========================")
        if exportID:
            updateFileWithStage()
        log(f"End Main Stage At Stage:{STAGENUMBER}")
        return "end"
    except Exception as e:
        print("========= Error =========")
        updateFileWithStage()
        log(f"Exception in play main stage:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")


def playMainStageAtNumber(number:int, loop=0, closeGame=False):
    global GAMEID, STAGENUMBER, HIGHERSTAGE, cooldowncapturescreen
    try:
        print("=========================", flush=True)
        log(f"Start Main Stage At: {number}")
        STAGENUMBER = 0
        quest7day = 0

        rangerCycle = 0
        timeNow = time.time()  # เวลาปัจจุบัน
        currentLostCount = 0

        foundSkip = False
        levelNumber = 1
        win = False
        useItemstorm = True
        useItemIce = True
        useItemShield = True

        waitLoading()
        if not exists(r"src\image\main_stage\main stage.png", 0.7, 0.25):
            waitLoading()
            goTo(r"src\image\go_to\main stage.png")
        waitLoading()
        waitLoading()

        stage30 = exists(r"src\image\main_stage\stage30.png", similarity=0.8, timeout=0.3)
        if stage30:
            click(stage30.getBottomRight())
            click(stage30.getBottomRight().offset(5, 5))
            click(stage30.getBottomRight().offset(10, 10))
        else:
            if HIGHERSTAGE == 0:
                waitLoading()
                HIGHERSTAGE = findStageHigher()   
            if HIGHERSTAGE < 150 and not number in [1, 2]:
                return "lost"
            
            # ด่าน 2 มีทางเดินพิเศษ (stage change -> stage 1 -> stage2) สำหรับบัญชีตอนทำ
            # บทสอน ซึ่งอยู่หน้า main stage แบบโลก A/B แต่บัญชีที่ผ่านบทสอนแล้วพอเข้า main
            # stage จะเด้งไปหน้าแผนที่ย่อย (เช่น Valley of Wind) ที่ไม่มีปุ่ม stage change แบบนั้น
            # แล้ว click ตาย ทำให้เล่นด่าน 2 ซ้ำในเซสชันเดิมไม่ได้ จึงเช็คก่อน: มีปุ่มบทสอนไหม
            # ถ้ามีใช้ทางเดิม ถ้าไม่มีถือเป็นบัญชีปกติ ตกไปคลิกโหนดด่านตรง ๆ เหมือนด่านอื่น
            if number == 2 and exists(r"src\image\main_stage\stage change.png", timeout=2):
                click(r"src\image\main_stage\stage change.png")
                waitLoading()
                click(r"src\image\main_stage\stage 1.png")
                waitLoading()
                click(r"src\image\main_stage\stage2.png", similarity=0.9)
            else:
                stageLocation = findStageAtNumber(number)
                log(f"Stage {stageLocation}")
                click(stageLocation) # Play MainStage At Location

        waitLoading()
        startTine = time.time()
        while True:
            if exists(r"src\image\main_stage\stage.png", timeout=0.1, capture=False):
                log("found stage.png")
                break
            elif time.time() - startTine > 10:
                log("Cust screen > 10 sec")
                raise Exception(f"Cust screen > 10 sec")
            waitLoading()
            log(click(Location(480+random.randint(-400, 400), 90+random.randint(-10, 10))))

        if exists(r"src\image\main_stage\tutorial leonard loop.png", timeout=0.1):
            tutorialClickLoop(backButton=False)


        # wait(r"src\image\main_stage\stage.png")
        try:
            waitLoading()
            STAGENUMBER = int(numberOCR(Region(x=160, y=8, w=80, h=41), r"src\image\main_stage\numS", 0.85))
        except:
            traceback.print_exc()

        print("=========================", flush=True)
        log(f"Stage: {STAGENUMBER}")
        
        autoOn = None
        if AUTOMODE == "bot":
            existsClick(r"src\image\main_stage\auto on.png", timeout=0.1)
        elif AUTOMODE == "game":
            existsClick(r"src\image\main_stage\auto.png", timeout=0.1)
        existsClick(r"src\image\main_stage\x2.png", timeout=0.1)

        if loop != 0:
            click(r"src\image\special_stage\loop.png")
            waitLoading()
            for _ in range(loop-1):
                # click(Location(475, 225), waitTime=0.5) # +
                existsClick(r"src\image\main_stage\add.png") # +
            click(Location(551, 406)) # ok
            existsClick(r"src\image\main_stage\skip ok.png") # ok

        if existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01):
            existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)
            existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)
            existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)

        startButton = exists(r"src\image\main_stage\start.png")
        nextButton = None
        if startButton:
            click(startButton)
        nextButton = exists(r"src\image\main_stage\next.png")
        if nextButton:
            click(nextButton)
            if STAGENUMBER == 30 and number != 30:
                waitLoading(timeOut=0.1)
                skip()
                for _ in range(10):
                    click((345, 380), waitTime=0.2) # เลือกเพื่อน                

            waitLoading()
            if STAGENUMBER >= 30:
                if BUYFRIEND == "everyTime":
                    buyFriend()
                elif BUYFRIEND == "justLost" and not win:
                    buyFriend()

        existsClick(r"src\image\main_stage\start.png")

        _cooldowncapturescreen = cooldowncapturescreen
        cooldowncapturescreen = 0.001
        if not waitLoading(timeOut=0.01, cooldowncaptures=0.001):  # << ถ้าโหลดเกิน 2 นาที
            raise TimeoutError("Loading stuck > 180 sec")
        cooldowncapturescreen = _cooldowncapturescreen
        
        log(f"PLaying", end="")
        timer = time.time()
        startPlayTime = datetime.now()
        _buy_every = BUYFRIEND == "everyTime"
        _buy_lost  = BUYFRIEND == "justLost"
        _auto_bot  = AUTOMODE == "bot"
        while True:
            rangerCycle += 1

            click((275, 515), waitTime=0.01, duration=0.05) # ranger 1
            click((375, 515), waitTime=0.01, duration=0.05) # ranger 2
            click((475, 515), waitTime=0.01, duration=0.05) # ranger 3
            click((575, 515), waitTime=0.01, duration=0.05) # ranger 4
            click((675, 515), waitTime=0.01, duration=0.05) # ranger 5

            captureScreen()
            if regionExists(Region(149, 33, 73, 31), r"src\image\main_stage\win.png", 0.8, timeout=0.02, capture=False):
                win = True
                currentLostCount = 0
                stopPLayerTime = datetime.now()
                playTime = stopPLayerTime - startPlayTime
                minutes, seconds = divmod(playTime.seconds, 60)
                print()
                log(f"Win {minutes:02d}:{seconds:02d}")
                break
            if regionExists(Region(480, 327, 199, 74), r"src\image\main_stage\lose cancel.png", timeout=0.02, capture=False):
                win = False
                currentLostCount += 1
                stopPLayerTime = datetime.now()
                playTime = stopPLayerTime - startPlayTime
                minutes, seconds = divmod(playTime.seconds, 60)
                print()
                log(f"Lose {minutes:02d}:{seconds:02d}")
                break

            timeNow = time.time()  # เวลาปัจจุบัน
            if STAGENUMBER == 30:
                click((345, 380), waitTime=0.001, duration=0.05) # เลือกเพื่อน
                click(slotItem1, waitTime=0.15, duration=0.05) # เพื่อน
                click(slotItem1, waitTime=0.15, duration=0.05) # เพื่อน

            click(slotItem1, duration=0.05)
            click(slotItem2, duration=0.05)
            click(slotItem3, duration=0.05)
            click(slotItem4, duration=0.05)
            click(slotItem5, duration=0.05)

            if not autoOn and _auto_bot:
                if 15 <= timeNow - timer and AUTOUSEITEM:
                    autoOn = existsClick(r"src\image\main_stage\auto in game.png", timeout=0.1, capture=False)
                if rangerCycle % 6 == 0:
                    click((150, 510), waitTime=0.05) # missile
                    click((775, 510), waitTime=0.05) # costs

            waitLoading(timeOut=0.1)

            if rangerCycle % 2 == 0:
                print(".",end="", flush=True)
        
            if timeNow - timer > 180:  # << ถ้าเล่นเกิน 3 นาที
                raise TimeoutError("PLaying stuck > 180 sec")
            
        if closeGame:
            return


        # waitLoading
        if exists(r"src\image\home\UnKnown error.png", timeout=0.02):
            existsClick(r"src\image\main_stage\skip ok.png", timeout=0.02)
        existsClick(r"src\image\home\retry.png", timeout=0.02)


        levelUp = True
        while True:
            waitLoading()
            captureScreen()
            if exists(r"src\image\main_stage\main stage.png", 0.7, timeout=0.1, capture=False):
                waitLoading()
                log(f"Break: Found main stage")
                break

            if exists(r"src\image\tutorial\skip.png", 0.7, timeout=0.1, capture=False):
                waitLoading()
                log(f"Break: Found skip tutorial")
                if exists(r"src\image\main_stage\tutorial james.png", timeout=0.1):
                    foundSkip = True
                break

            if exists(r"src\image\main_stage\lose cancel.png", timeout=0.1, capture=False) and exists(r"src\image\main_stage\resume for free.png", timeout=0.25, capture=False):
                log(f"Break: Found lose")
                break

            if exists(r"src\image\main_stage\tutorial leonard retry ok next.png", 0.7, timeout=0.1, capture=False):
                if STAGENUMBER == 31 :
                    log(f"Break: Found tutorial retry ok next")
                    break
                if colorMatch(getColor(Location(324, 440)), Color(140, 44, 231)):
                    existsClick(r"src\image\main_stage\clear bonus retry.png", timeout=0.1)
                if colorMatch(getColor(Location(630, 440)), Color(8, 190, 206)):
                    existsClick(r"src\image\main_stage\clear bonus next.png", timeout=0.1)  

            if exists(r"src\image\main_stage\level17.png", 0.6, 0.25, capture=False) and levelUp:
                levelUp = False
                r = find(r"src\image\main_stage\level17.png", 0.6)
                levelNumber = int(numberOCR(r, r"src\image\main_stage\level"))
                log(f"LevelUp: {levelNumber}")
                if levelNumber in [17, 18, 20, 40]:
                    for _ in range(7):
                        captureScreen()
                        if exists(r"src\image\home\skip.png", timeout=0.1, capture=False):
                            skip()
                        existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7, capture=False)
                        if exists(r"src\image\home\close.png", timeout=0.1, capture=False)  or exists(r"src\image\home\back.png", timeout=0.1, capture=False):
                            break
                        if (nextButton):
                            click(nextButton, waitTime=0.1)
                        elif (startButton):
                            click(startButton, waitTime=0.1)
                    waitLoading()
                    log(f"Break: Found level: {levelNumber} to tutorial")
                    break
            
            if (nextButton):
                click(nextButton)
            elif (startButton):
                click(startButton)

            existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7)

        if exists(r"src\image\main_stage\lose cancel.png", timeout=0.5):
            if currentLostCount >= LOSTCOUNT:
                print("========= Lost ==========")
                log(f"CurrentLostCount:{currentLostCount} = LostCount:{LOSTCOUNT}")
                return "lost"
            else:
                upgradeCrystal()

        if levelNumber in [17, 18]:
            tutorialLevel17()

        if levelNumber == 40:
            goToHome()
            # tutorialTrain()

        if (foundSkip or STAGENUMBER == 2) and win and number != 2:
            tutorial2()

        if STAGENUMBER == 5 and win:
            tutorial5()

        if STAGENUMBER == 10 and win:
            if exists(r"src\image\home\choose a new ranger.png", timeout=0.001):
                tutorial10()

        if STAGENUMBER == 12 and win:
            tutorial12()

        if STAGENUMBER == 15 and win:
            tutorial15()

        if STAGENUMBER == 29 and win:
            tutorial29()

        if STAGENUMBER == 31 and win:
            retryNextOk()

        if 3 < STAGENUMBER <= 12 and win:
            if quest7day <= 1:
                # waitLoading()
                # click((30, 25), waitTime=0.1) # ปุ่มย้อนกลับ
                # waitLoading()
                # tutorial7DayAndQuest()
                goToHome()
                click((480, 165), waitTime=0.5) # main stage
                waitLoading()
                quest7day += 1

        if levelNumber == 20:
            goToHome()
            # tutorialLevel20()

        waitLoading()
        updateFileInExecute()
        log(f"End Main Stage At Stage:{STAGENUMBER}")
        print("=========================")
        return "end"
    except Exception as e:
        print("========= Error =========")
        updateFileInExecute()
        log(f"Exception in play main stage:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")

def _getMissions():
    while True:
        if existsClick(r"src\image\mission\get.png"):
            waitLoading()
            existsClick(r"src\image\mission\ok.png", timeout=0.5)
            existsClick(r"src\image\mission\exp up ok.png", timeout=0.5)
            waitLoading()
        else:
            break

def getMissions(goHome=True):
    log(f"Get Missions")
    goTo(r"src\image\go_to\mission.png")
    waitLoading(timeOut=0.1)
    existsClick(r"src\image\mission\close ranger pass ok.png", timeout=0.01)
    waitLoading(timeOut=0.1)
    
    if existsClick(r"src\image\mission\weekly mission.png", timeout=0.01):
        waitLoading()
        _getMissions()
    
    if existsClick(r"src\image\mission\special mission.png", timeout=0.01):
        slot1 = Region(300, 125, 550, 100)
        slot2 = Region(300, 243, 550, 100)
        waitLoading()

        while True:
            get = None
            if not regionExists(slot1, r"src\image\mission\sticker.png"):
                get = regionExists(slot1, r"src\image\mission\get.png")
            elif not regionExists(slot2, r"src\image\mission\sticker.png"):
                get = regionExists(slot2, r"src\image\mission\get.png")
                
            if get:
                click(get)
                waitLoading()
                existsClick(r"src\image\mission\ok.png", timeout=0.5)
                existsClick(r"src\image\mission\exp up ok.png", timeout=0.5)
                waitLoading()
            else:
                break



    if exists(r"src\image\mission\mission_lv_1.png", timeout=0.01):
        if existsClick(r"src\image\mission\pass.png", timeout=0.01):
            waitLoading()
            if existsClick(r"src\image\mission\ticket_6.png", timeout=0.01):
                waitLoading()
                existsClick(r"src\image\mission\exp up ok.png")
                waitLoading()
                closePopUp()
        
    if goHome:
        goToHome()


def force_stop_LINE_Rangers():
    global LFACCACHE
    LFACCACHE = None   # token ตายพร้อมกับ session ทุกทางที่เปิดเกมใหม่ต้องผ่านตรงนี้
    DEVICE.shell(f"am force-stop com.linecorp.LGRGS")
    wait(0.5)


def log(values:object, end="\n", flush=True):
    formatted_datetime = datetime.now().strftime("%H:%M:%S")
    # print(f"{formatted_datetime} {device_serial}: {values}", end=end, flush=flush)
    print(f"{formatted_datetime} {values}", end=end, flush=flush)


def getGameID():
    global GAMEID
    log("Get Game ID")
    char = ""
    try:
        tmp_remote = "/sdcard/Cocos2dxPrefsFile.xml"
        tmp_local = os.path.join("backup", f"_tmp_gameid_{DEVICESERIAL}.xml")
        DEVICE.shell(f"su -c 'cp /data/data/com.linecorp.LGRGS/shared_prefs/Cocos2dxPrefsFile.xml {tmp_remote}'")
        DEVICE.pull(tmp_remote, tmp_local)
        DEVICE.shell(f"rm {tmp_remote}")
        with open(tmp_local, "r", encoding="utf-8") as f:
            content = f.read()
        os.remove(tmp_local)
        match = re.search(r'<string name="[^"]*GAME_ID[^"]*">([^<]+)</string>', content)
        if match:
            char = match.group(1).strip()
    except Exception as e:
        log(f"Read Game ID error: {e}")
    if char:
        GAMEID = char
        log(f"Game ID: {GAMEID}")
        return GAMEID
    else:
        GAMEID = f"{DEVICESERIAL}"
        log(f"Game ID: {GAMEID}")
        return GAMEID


def waitLoading(timeOut=1, cooldowncaptures=None):
    starTime = time.time()
    retry = 0
    while True:
        captureScreen(cooldowncaptures=cooldowncaptures)
        existsClick(r"src\image\home\accept iniquitions tool(s).png", timeout=0.01, capture=False, similarity=0.75)
        if exists(r"src\image\home\UnKnown error.png", timeout=0.02, capture=False):
            existsClick(r"src\image\main_stage\skip ok.png", timeout=0.02, capture=False)
        if existsClick(r"src\image\home\retry.png", timeout=0.02, capture=False):
            retry += 1

        if not exists(r"src\image\home\loading.png", 0.5, timeout=timeOut, capture=False):
            return True
        if time.time() - starTime > 240 or exists(r"src\image\home\error 300001.png", similarity=0.7, timeout=0.02, capture=False) or retry >= 5:  # ถ้าโหลดเกิน 3 นาที
            existsClick(r"src\image\home\ok.png", timeout=0.1)
            log("Loading time out > 240 sec")
            raise TimeoutError(f"Loading time out > 240 sec")
            # return False   # << ส่งสัญญาณ timeout
        sleep(0.2)


def waitLoadingScreen():
    log(f"Wait Loading Screen")
    while True:
        waitLoading()
        existsClick(r"src\image\home\ok.png", timeout=0.01, capture=False)
        if not regionFind(Region(700, 481, 60, 20), r"src\image\home\percent.png", 0.75):
            return 1


def goTo(path: str):
    waitLoading()
    if path == r"src\image\go_to\main stage.png" and exists(r"src\image\main_stage\go main stage.png", timeout=0.1):
        existsClick(r"src\image\main_stage\go main stage.png")
        waitLoading()
        return
    if path == r"src\image\go_to\gacha.png" and exists(r"src\image\gacha\gacha icon.png", timeout=0.1, capture=False):
        existsClick(r"src\image\gacha\gacha icon.png")
        waitLoading()
        waitLoading()
        return
    
    if existsClick(r"src\image\home\mission icon.png", timeout=0.1, capture=False):
        waitLoading()
        waitLoading()
        if existsClick(r"src\image\mission\close ranger pass ok.png", 0.8, 0.1):
            for _ in range(15):
                click((480, 500), waitTime=0.5)
            waitLoading()
            existsClick(r"src\image\home\cancel.png", timeout=0.1)
            if path == r"src\image\go_to\mission.png":
                return
            goToHome()
            existsClick(r"src\image\home\cancel.png", timeout=0.1)
            waitLoading()
            existsClick(r"src\image\home\cancel.png", timeout=0.1)
            click(r"src\image\home\mission icon.png", 0.7)

    if path == r"src\image\go_to\mission.png" and exists(r"src\image\mission\mission.png", timeout=0.1, capture=False):
        return

    waitLoading()
    existsClick(r"src\image\go_to\more.png", 0.7, 3)
    waitLoading()
    wait(1)
    click(path, 0.7)
    waitLoading()


def goToHome():
    if exists(r"src\image\home\mission icon.png"):
        return
    # closePopUp()
    # tutorialInHomeScreen()
    goTo(r"src\image\go_to\home.png")
    existsClick(r"src\image\home\close lab.png", 0.7, timeout=0.1)
    existsClick(r"src\image\home\close lab 2.png", 0.7, timeout=0.1)
    if colorMatch(getColor((652, 20)), Color(74, 73, 16), 20):
        click((10, 10), waitTime=0.5)
    existsClick(r"src\image\home\cancel.png", timeout=0.1)
    closePopUp()
    tutorialInHomeScreen()


def skip():
    waitLoading()
    # existsClick(r"src\image\home\skip.png", timeout=0.1) # skip
    # existsClick(r"src\image\home\ok.png", timeout=0.1) # skip ok
    click((770, 30), waitTime=0.5)
    click((550, 350), waitTime=0.5)


def retryNextOk():
    log(f"retryNextOk")
    waitLoading()
    existsClick(r"src\image\main_stage\clear bonus retry.png", 0.7)
    wait(0.3)
    existsClick(r"src\image\main_stage\clear bonus next.png", 0.7)
    wait(0.3)
    existsClick(r"src\image\main_stage\clear bonus retry.png", 0.7)
    waitLoading()
    tutorialClickLoop(backButton=True)


def tutorial30():
    log(f"Tutorial Stage 30")
    skip()
    existsClick(r"src\image\main_stage\go main stage.png", timeout=0.1)
    existsClick(r"src\image\main_stage\go main stage.png", timeout=0.1)
    waitLoading()
    waitLoading()
    if exists(r"src\image\main_stage\stage30.png", similarity=0.8, timeout=2):
        playMainStageAtNumber(30)
        waitLoading()
        goToHome()
        waitLoading()


def tutorialClickLoop(backButton=False):
    log(f"Tutorial Click Loop")
    waitLoading()
    click((676, 475), waitTime=0.4, duration=0.1) # loop
    click((676, 475), waitTime=0.4, duration=0.1) # loop
    click((875, 475), waitTime=0.4, duration=0.1) # พื้นที่ว่าง
    click((775, 475), waitTime=0.4, duration=0.1) # mutiplier
    click((775, 475), waitTime=0.4, duration=0.1) # mutiplier
    click((875, 475), waitTime=0.4, duration=0.1) # พื้นที่ว่าง
    click((875, 475), waitTime=0.4, duration=0.1) # พื้นที่ว่าง
    click((875, 475), waitTime=0.4, duration=0.1) # พื้นที่ว่าง
    click((400, 435), waitTime=0.4, duration=0.1) # ปุ่มยกเลิก
    if backButton:
        click((30, 25)) # ปุ่มย้อนกลับ
        waitLoading()
        wait(4)


def tutorialLevel17():
    log(f"Tutorial Level 17")
    waitLoading()
    click((30, 25)) # ปุ่มย้อนกลับ
    click((30, 25)) # ปุ่มย้อนกลับ
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    click((825, 45), waitTime=0.5) # ปุ่มปิด เพคมาขาย
    click((825, 45), waitTime=0.5) # ปุ่มปิด เพคมาขาย
    waitLoading()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()


def tutorialLevel20():
    log(f"Tutorial Level 20")
    waitLoading()
    start_time = time.time()
    while True:
        waitLoading()
        if not existsClick(r"src\image\home\skip1.png"):
            break
        if exists(r"src\image\home\skip2.png"):
            raise Exception("Tutorial Level 20: Found skip2.png")
        if time.time() - start_time > 60:
            raise TimeoutError("Tutorial Level 20: skip1.png loop timeout after 60s")
    waitLoading()
    wait(1)
    click((245, 245)) # สเตจพิศษ
    click((245, 245)) # สเตจพิศษ
    wait(1)
    waitLoading()
    waitLoading()
    wait(1)
    pressBack()
    pressBack()
    waitLoading()
    # wait(5)
    # while True:
    #     click((480, 520))
    #     captureScreen()
    #     if exists(r"src\image\home\back.png", timeout=0.1, capture=False) or exists(r"src\image\home\mission icon.png", similarity=0.7, timeout=0.1, capture=False):
    #         break
    # goToHome()


def tutorialBingo():
    log(f"Tutorial Bingo")
    if existsClick(r"src\image\bingo\bingo tutorial.png", similarity=0.7):
        waitLoading()
        wait(0.3)
        pressBack()
        pressBack()
        waitLoading()


def tutorialTrain():
    log(f"Tutorial Train")
    if existsClick(r"src\image\train\sos signal.png", timeout=0.1) or existsClick(r"src\image\train\enter train.png", timeout=0.1, similarity=0.7):
        skip()
        wait(2)
        existsClick(r"src\image\train\enter train.png", timeout=0.1, similarity=0.7)
        waitLoading()
        waitLoading()
        wait(1)
        pressBack()
        pressBack()
        waitLoading()

def tutorial7DayAndQuest():
    log(f"Tutorial 7Day And Quest")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    if exists(r"src\image\home\skip.png", timeout=0.1):
        skip()
        skip()
    waitLoading()
    if colorMatch(getColor((652, 20)), Color(74, 73, 16), 20):
        if regionFindColor(exists(r"src\image\home\quest.png", timeout=0.1), Color(255, 239, 66), 20):
        # if colorMatch(getColor((930, 185)), Color(255, 239, 66), 20):
            click((910, 160), waitTime=0.5) # เควสพิเศษ
            waitLoading()
            click((820, 50), waitTime=0.5) # ปิดเควสพิเศษ
        if regionFindColor(exists(r"src\image\home\7D.png", timeout=0.1), Color(255, 251, 255), 20):
        # if colorMatch(getColor((926, 245)), Color(255, 251, 255), 20):
            click((915, 235), waitTime=0.5) # เควสผูเล่นใหม่ 7day
            waitLoading()
            skip()
            click((745, 75), waitTime=0.5) # ปุ่ม ? สีแดง
            click((745, 75), waitTime=0.5) # ปุ่ม ? สีแดง
            click((820, 50), waitTime=0.5) # ปิดเควสผูเล่นใหม่ 7dday
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()
    wait(3)

def tutorialQuest(mainStage = True):
    log(f"Tutorial Quest")
    quest = False
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    skip()
    if not regionFindColor(Region(639, 15, 26, 26), Color(255, 239, 66), capture=False) and regionFindColor(exists(r"src\image\home\quest.png", timeout=0.1), Color(255, 239, 66), 20, capture=False):
        existsClick(r"src\image\home\quest.png", timeout=0.1) # เควสพิเศษ
        waitLoading()
        click((820, 50), waitTime=0.5) # ปิดเควสพิเศษ
        quest = True
    if mainStage:
        click((480, 165), waitTime=0.5) # main stage
        waitLoading()
        wait(3)
    return quest


def tutorial7Day(mainStage = True):
    log(f"Tutorial 7Day")
    quest7D = False
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    skip()
    if not regionFindColor(Region(639, 15, 26, 26), Color(255, 239, 66), capture=False) and regionFindColor(exists(r"src\image\home\7D.png", timeout=0.1), Color(255, 251, 255), 20, capture=False):
        existsClick(r"src\image\home\7D.png", timeout=0.1) # เควสผูเล่นใหม่ 7d
        waitLoading()
        skip()
        click((745, 75), waitTime=0.5) # ปุ่ม ? สีแดง
        click((745, 75), waitTime=0.5) # ปุ่ม ? สีแดง
        click((820, 50), waitTime=0.5) # ปิดเควสผูเล่นใหม่ 7d
        quest7D = True
    if mainStage:
        click((480, 165), waitTime=0.5) # main stage
        waitLoading()
        wait(3)
    return quest7D


def tutorial2():
    log(f"Tutorial Stage 2")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    skip()
    click((480, 455), waitTime=0.25)
    click((480, 455), waitTime=0.25)
    click((480, 455), waitTime=0.25)
    click((480, 455), waitTime=0.25)
    waitLoading()
    closePopUp()
    skip()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()
    waitLoading()
    existsClick(r"src\image\main_stage\chest1.png")
    waitLoading()
    click((440, 140), waitTime=0.5)
    waitLoading()
    waitLoading()
    skip()
    waitLoading()

    while True:
        popUp = findAll(r"src\image\main_stage\close pop up.png")
        if popUp :
            for r in popUp:
                click(r)
                waitLoading()
        else:
            break

    if exists(r"src\image\go_to\more.png", 0.7, 0.3):
        goToHome()


def tutorial5():
    log(f"Tutorial Stage 5")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    waitLoading()
    skip()
    click((353, 230), waitTime=0.1) # กดตัวอัพ ฐาน10
    click((353, 230), waitTime=0.1) # กดตัวอัพ ฐาน10
    click((475, 315), waitTime=0.1) # กดตัวอัพ ฐาน5
    click((475, 315), waitTime=0.1) # กดตัวอัพ ฐาน5
    waitLoading()
    click((275, 450), waitTime=0.5) # ปุมอัพตัว แดง
    waitLoading()
    swipe(200, 500, 355, 240) # ลากตัวอัพ
    click((785, 230), waitTime=0.5) # ปุมอัพตัว เขียว
    waitLoading()
    wait(4)
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    skip()    
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()    
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    waitLoading()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    tutorialInHomeScreen()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()


def tutorial10():
    log(f"Tutorial Stage 10")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    waitLoading()
    skip()
    waitLoading()
    click((475, 315), waitTime=0.5) # กดตัวอัพ
    click((471, 312), waitTime=0.5) # กดตัวอัพ
    click((471, 312), waitTime=0.5) # กดตัวอัพ
    waitLoading()
    click(r"src\image\team\level up button.png", similarity=0.7) # กดตัวอัพ
    click((275, 450), waitTime=0.5) # ปุมอัพตัว แดง
    waitLoading()
    swipe(200, 500, 355, 240) # ลากตัวอัพ
    click((785, 230), waitTime=0.5) # ปุมอัพตัว เขียว
    waitLoading()
    wait(4)
    waitLoading()
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()


def tutorial12():
    log(f"Tutorial Stage 12")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    waitLoading()
    skip()
    click((660, 100), waitTime=0.5) # กาชา
    waitLoading()
    existsClick(r"src\image\home\ok.png")
    skip()
    click((800, 80), waitTime=0.5) # เกียร์
    waitLoading()
    click((355, 450), waitTime=0.5) # สุ่มเกียร์
    waitLoading()
    click((400, 465), waitTime=0.5) # ok
    click((400, 465), waitTime=0.5) # ok
    click((400, 465), waitTime=0.5) # ok
    waitLoading()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    skip()
    click((475, 315), waitTime=0.25) # กดตัวอัพ
    click((475, 315), waitTime=0.25) # กดตัวอัพ
    waitLoading()
    skip()
    skip()
    click((380, 380), waitTime=0.5) # เปิดใส่เกียร์
    waitLoading()
    skip()
    click((490, 200), waitTime=0.5) # เกียร์
    click((490, 200), waitTime=0.5) # เกียร์
    click((490, 200), waitTime=0.5) # เกียร์
    waitLoading()
    click((758, 460), waitTime=0.5) # สวมใส่
    click((763, 462), waitTime=0.5) # สวมใส่
    waitLoading()
    skip()
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()


def tutorial15():
    log(f"Tutorial Stage 15")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    waitLoading()
    skip()
    click((475, 315), waitTime=0.5) # กดตัวอัพ
    click((475, 315), waitTime=0.5) # กดตัวอัพ
    waitLoading()
    click((380, 380), waitTime=0.5) # เปิดใส่เกียร์
    waitLoading()
    skip()
    click((490, 200), waitTime=0.5) # เกียร์
    skip()
    click((800, 150), waitTime=0.25) # enhance เหลือง
    click((800, 150), waitTime=0.25) # enhance เหลือง
    waitLoading()
    skip()
    click((820, 185), waitTime=0.5) # เลือกเกียร์
    click((227, 345), waitTime=0.25) # enhance แดง
    click((225, 347), waitTime=0.25) # enhance แดง
    waitLoading()
    wait(4)
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    skip()
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()


def tutorial29():
    log(f"Tutorial Stage 29")
    waitLoading()
    existsClick(r"src\image\main_stage\purchase cancel.png", timeout=0.25)
    waitLoading()
    skip()
    click((480, 165), waitTime=0.5) # main stage
    waitLoading()


def tutorialRandomDice():
    log(f"Tutorial Random Dice")
    if not exists(r"src\image\random dice\random dice event now open.png"):
        return
    click(r"src\image\random dice\random dice.png", similarity=0.7)
    waitLoading()
    waitLoading()
    wait(1)
    pressBack()
    pressBack()
    # while True:
    #     click((480+random.randint(-10, 10), 270+random.randint(-10, 10)))
    #     if exists(r"src\image\random dice\roll the dice .png", timeout=0.1):
    #         break
    # goToHome()
    waitLoading()


def upgradeRanger():
    log(f"Upgrade Ranger")
    click((890, 330), waitTime=0.5) # filter
    click((390, 490), waitTime=0.5) # reset
    click((456, 333), waitTime=0.5) # filter leonard
    click((330, 95), waitTime=0.5) # star 1
    click((455, 95), waitTime=0.5) # star 2
    click((585, 95), waitTime=0.5) # star 3
    click((715, 95), waitTime=0.5) # star 4
    click((330, 135), waitTime=0.5) # star 5
    # click((455, 135), waitTime=0.5) # star 6
    # click((585, 135), waitTime=0.5) # star 7
    # click((715, 135), waitTime=0.5) # star 8
    click((560, 490), waitTime=0.5) # ok

    swipe(249, 524, 340, 240, 500) # leonard 1
    wait(0.3)
    swipe(401, 465, 401, 165, 500) # leonard 2
    wait(0.3)
    swipe(587, 465, 526, 165, 500) # leonard 3
    wait(0.3)
    swipe(570, 465, 70, 465, 1000) # เลื่อน <-
    wait(0.3)
    swipe(465, 465, 465, 240, 500) # leonard 4
    wait(0.3)
    swipe(587, 465, 587, 240, 500) # leonard 5


def upgradeCrystal():
    log(f"Upgrade Crystal")
    waitLoading()
    click(r"src\image\main_stage\lose cancel.png")
    waitLoading()
    existsClick(r"src\image\main_stage\lose x.png")
    waitLoading()
    click(r"src\image\main_stage\upgrade.png")
    waitLoading()

    if not regionFind(Region(424, 370, 200, 58), r"src\image\home\lock.png"):
        click((570, 405), waitTime=0.5) # max limit
        waitLoading()
        for i in range(9):
            if not regionFindColor(Region(400, 312, 160, 1), Color(255, 0, 0)):
                click((537, 251))
            else:
                click((355, 251), waitTime=0.5)
                click((355, 251), waitTime=0.5)
                click((355, 251), waitTime=0.5)
                if regionFindColor(Region(400, 312, 160, 1), Color(255, 0, 0)):
                    click((405, 405), waitTime=0.5) # cancel
                    return
                break
        waitLoading()
        click((555, 405), waitTime=0.1)
        click((555, 405), waitTime=0.1)
        waitLoading()
        click((555, 405), waitTime=0.1)
        click((555, 405), waitTime=0.1)
        waitLoading()

    if not regionFind(Region(70, 370, 200, 58), r"src\image\home\lock.png"):
        click((215, 405), waitTime=0.5) # production rate
        waitLoading()
        for i in range(9):
            if not regionFindColor(Region(400, 312, 160, 1), Color(255, 0, 0)):
                click((537, 251))
            else:
                click((355, 251), waitTime=0.5)
                click((355, 251), waitTime=0.5)
                click((355, 251), waitTime=0.5)
                if regionFindColor(Region(400, 312, 160, 1), Color(255, 0, 0)):
                    click((405, 405), waitTime=0.5) # cancel
                    return
                break
        waitLoading()
        click((555, 405), waitTime=0.1)
        click((555, 405), waitTime=0.1)
        waitLoading()
        click((555, 405), waitTime=0.1)
        click((555, 405), waitTime=0.1)
        waitLoading()


def findStageAtNumber(number=0):
    boss = []
    stages = []
    waitLoading()
    wait(1)
    results = findAll(r"src\image\main_stage\stage55.png", 0.4)
    for r in results:
        color = getColor(r, capture=False)
        if not colorMatch(color, Color(130, 130, 130), 35) and not colorMatch(color, Color(198, 158, 0), 20):
            noOCR = numberOCR(r, r"src\image\main_stage\num")
            if noOCR:
                stages.append([int(noOCR), r.getBottomCenter()])
        if colorMatch(color, Color(198, 158, 0), 20):
            boss = [0, r.getBottomCenter()]
    stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข

    if boss != [] and ((stages[0][0]+1) % 12) == 0:
        stages.append([stages[0][0]+1, boss[1]])
        stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข

    index = min(range(len(stages)), key=lambda i: abs(stages[i][0] - number))
    if stages[index][0] == number:
        return stages[index][1]

    click(r"src\image\main_stage\stage change.png")
    waitLoading()
    start_time = time.time()
    if number == 30:
        click(r"src\image\main_stage\stage 1.png")
        waitLoading()
        swipe(130, 270, 830, 270, 1500) # 
        while True:
            swipe(100, 160, 100, 380, 1500) # up
            if exists(r"src\image\main_stage\sign stage 30.png", timeout=0.1, similarity=0.9):
                break
            if time.time() - start_time > 13:
                click(r"src\image\main_stage\stage change.png")
                waitLoading()
                click(r"src\image\main_stage\stage 1.png")
                start_time = time.time()
    elif number == 100:
        click(r"src\image\main_stage\stage 100.png")
        waitLoading()
    elif number == 150:
        if not existsClick(r"src\image\main_stage\145.png", timeout=0.01):
            click(r"src\image\main_stage\stage 100.png")
            waitLoading()
        swipe(130, 270, 830, 270, 1500) # 
        while True:
            swipe(100, 160, 100, 380, 1500) # up
            if exists(r"src\image\main_stage\sign stage 150.png", timeout=0.1, similarity=0.9):
                break
            if time.time() - start_time > 23:
                click(r"src\image\main_stage\stage change.png")
                waitLoading()
                click(r"src\image\main_stage\stage 100.png")
                start_time = time.time()
    waitLoading()
    while True:
        results = findAll(r"src\image\main_stage\stage55.png", 0.4)
        for r in results:
            color = getColor(r, capture=False)
            if not colorMatch(color, Color(130, 130, 130), 35) and not colorMatch(color, Color(198, 158, 0), 20):
                noOCR = numberOCR(r, r"src\image\main_stage\num")
                if noOCR:
                    stages.append([int(noOCR), r.getBottomCenter()])
            if colorMatch(color, Color(198, 158, 0), 20):
                boss = [0, r.getBottomCenter()]
        stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข

        if boss != [] and ((stages[0][0]+1) % 12) == 0:
            stages.append([stages[0][0]+1, boss[1]])
            stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข

        index = min(range(len(stages)), key=lambda i: abs(stages[i][0] - number))
        log(f"Found Stage {stages[index]}")
        if stages[index][0] == number:
            return stages[index][1]
        
        click(stages[index][1])
        waitLoading()
        if not exists(r"src\image\main_stage\stage.png", timeout=3):
            click((480,100), waitTime=0.25)
            click((480,100), waitTime=0.25)
            click((480,100), waitTime=0.25)
        waitLoading()
        if exists(r"src\image\main_stage\tutorial leonard loop.png", timeout=0.1):
            tutorialClickLoop(backButton=False)

        click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
        waitLoading()


def findStageHigher():
    results = findAll(r"src\image\main_stage\stage100.png", 0.5)
    stages = []
    for r in results:
        color = getColor(r, capture=False)
        if not colorMatch(color, Color(130, 130, 130), 30) and not colorMatch(color, Color(247, 227, 0), 20):
            number = numberOCR(r, r"src\image\main_stage\num")
            if number:
                stages.append([int(number), r.getCenter()])
            # print([int(number), r.getCenter()])
    stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข
    return stages[0][0]


def findProfile():
    boss = []
    stages = []
    results = findAll(r"src\image\main_stage\stage55.png", 0.4)
    for r in results:
        color = getColor(r, capture=False)
        if not colorMatch(color, Color(130, 130, 130), 35) and not colorMatch(color, Color(198, 158, 0), 20):
            number = numberOCR(r, r"src\image\main_stage\num")
            if number:
                stages.append([int(number), r.getBottomCenter()])
        if colorMatch(color, Color(198, 158, 0), 20):
            boss = [0, r.getBottomCenter()]
    stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข

    if boss != [] and ((stages[0][0]+1) % 12) == 0:
        stages.append([stages[0][0]+1, boss[1]])
        stages.sort(key=lambda x: x[0], reverse=True)  # เรียงตามหมายเลข

    log(f"Find Stage {stages[0]}")
    click(stages[0][1])
    waitLoading()
    if not exists(r"src\image\main_stage\stage.png", timeout=3):
        click((480,100), waitTime=0.25)
        click((480,100), waitTime=0.25)
        click((480,100), waitTime=0.25)
    if exists(r"src\image\main_stage\tutorial leonard loop.png", timeout=0.1):
        tutorialClickLoop(backButton=False)

    click((30, 25), waitTime=0.5) # ปุ่มย้อนกลับ
    waitLoading()


def buyFriend():
    log(f"Buy Friend")
    if not existsClick(r"src\image\main_stage\sidekick.png", timeout=0.5):
        click(Location(555, 105)) # เพื่อนสนิด
    existsClick(r"src\image\main_stage\buy sidekick.png", timeout=0.5)
    existsClick(r"src\image\main_stage\buy item cancel.png", timeout=0.25)



def compareMineralCost(region:Region, maxMineralCost=1300):
    while True:
        # 9 Star
        if regionFindColor(Region(184, 498, 46, 1), Color(255, 251, 255)):
            mineralCost = numberOCR(region, r"src\image\mineral cost\b", 0.85)
        # Hyper
        elif regionFindColor(Region(184, 498, 46, 1), Color(255, 125, 239)):
            mineralCost = numberOCR(region, r"src\image\mineral cost\h", 0.85)
        # Ultar
        elif regionFindColor(Region(184, 498, 46, 1), Color(148, 178, 231)):
            mineralCost = numberOCR(region, r"src\image\mineral cost\u", 0.85)
        # Normal
        elif regionFindColor(Region(184, 498, 46, 1), Color(255, 199, 255)):
            mineralCost = numberOCR(region, r"src\image\mineral cost\n", 0.85)
        # Normal-yellow
        elif regionFindColor(Region(184, 498, 46, 1), Color(123, 60, 0)):
            mineralCost = numberOCR(region, r"src\image\mineral cost\r", 0.85)
        if int(mineralCost) <= int(maxMineralCost):
            break
        else:
            swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
            waitLoading()


def autoChangeTeam(slot=5, maxMineralCost=1300):
    if slot < 1:
        slot = 1
    elif slot > 5:
        slot = 5
    waitLoading()
    if not exists(r"src\image\team\team.png"):
        goTo(r"src\image\go_to\my team.png")
    log(f"Auto Team")
    waitLoading()

    # skip tutorial
    if (colorMatch(getColor(Location(480, 10)), Color(74, 69, 57), 10)):
        if colorMatch(getColor(r"src\image\team\teamA.png", 0.65), Color(165, 89, 0), 10):
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
        if colorMatch(getColor((680, 80)), Color(247, 223, 173), 10):
            click((680, 80), waitTime=0.5)
            click((680, 80), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)

    # off set ฐาน 10
    if exists(r"src\image\team\tower skin.png", timeout=0.3):
        X = 80
    else:
        X = 0

    # drop ranger
    swipe(X + 195, 180, 195, 350) # slot 1
    swipe(X + 338, 180, 338, 350) # slot 2
    swipe(X + 482, 180, 482, 350) # slot 3
    swipe(X + 626, 180, 626, 350) # slot 4
    swipe(X + 768, 180, 768, 350) # slot 5

    # filter
    click((786, 327), waitTime=0.5) # filter
    click((393, 484), waitTime=0.5) # reset
    click((327, 331), waitTime=0.5) # ranger
    click((558, 483), waitTime=0.5) # ok
    click((656, 326), waitTime=0.5) # sort by
    click((247, 383), waitTime=0.5) # grade

    # drag ranger
    if slot >= 1:
        wait(0.2)
        compareMineralCost(Region(180, 487, 60, 21), maxMineralCost)
        swipe(195, 450, X + 195, 180) # ranger 1
        waitLoading()
    if slot >= 2:
        wait(0.2)
        while True:
            compareMineralCost(Region(438, 487, 60, 21), maxMineralCost)
            swipe(338, 450, X + 338, 180) # ranger 2
            waitLoading()
            if not existsClick(r"src\image\home\ok.png", timeout=0.1):
                break
            waitLoading()
            swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
            waitLoading()
            waitLoading()
    swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
    wait(1)
    if slot >= 3:
        wait(0.2)
        while True:
            compareMineralCost(Region(438, 487, 60, 21), maxMineralCost)
            swipe(480, 450, X + 482, 180) # ranger 3
            waitLoading()
            if not existsClick(r"src\image\home\ok.png", timeout=0.1):
                break
            waitLoading()
            swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
            waitLoading()
            waitLoading()
    if slot >= 4:
        wait(0.2)
        while True:
            compareMineralCost(Region(696, 487, 60, 21), maxMineralCost)
            swipe(626, 450, X + 626, 180) # ranger 4
            waitLoading()
            if not existsClick(r"src\image\home\ok.png", timeout=0.1):
                break
            waitLoading()
            swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
            waitLoading()
            waitLoading()
    swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
    wait(1)
    if slot >= 5:
        wait(0.2)
        while True:
            compareMineralCost(Region(696, 487, 60, 21), maxMineralCost)
            swipe(750, 450, X + 768, 180) # ranger 5
            waitLoading()
            if not existsClick(r"src\image\home\ok.png", timeout=0.1):
                break
            waitLoading()
            swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
            waitLoading()
            waitLoading()

    # save team
    waitLoading()
    existsClick(r"src\image\home\ok.png", timeout=0.1)
    waitLoading()
    existsClick(r"src\image\go_to\more.png", 0.7, timeout=3)
    waitLoading()
    existsClick(r"src\image\go_to\main stage.png", timeout=3)
    waitLoading()
    existsClick(r"src\image\team\save.png", timeout=3)
    waitLoading()

def acceptGiftBox():
    log(f"Accept Gift Box")
    found_0_200 = False
    goToHome()
    click(r"src\image\home\giftbox.png", similarity=0.7)
    waitLoading()
    if existsClick(r"src\image\home\acceptAll.png"):
        waitLoading()
        click(r"src\image\home\ok.png")
        waitLoading()
        click(r"src\image\home\ok.png")
        waitLoading()

    if exists(r"src\image\gift\0_200.png", timeout=0.1, similarity=0.9):
        found_0_200 = True
    closePopUp()
    tutorialInHomeScreen()

    # if not found_0_200:
    #     click(r"src\image\home\giftbox.png", similarity=0.7)
    #     waitLoading()

    #     if existsClick(r"src\image\home\acceptAll.png"):
    #         waitLoading()
    #         click(r"src\image\home\ok.png")
    #         waitLoading()
    #         click(r"src\image\home\ok.png")
    #         waitLoading()

    #     foundExpBooster = False
    #     swipeCounter = 0
    #     while True:
    #         accepts = findAll(r"src\image\gift\accept.png")
    #         for accept in accepts:
    #             acceptPosY = accept.y
    #             expPos = exists(r"src\image\gift\exp booster.png")
    #             if expPos:
    #                 expPosY = expPos.y
    #                 print(f"acceptPosY: {acceptPosY}, expPosY: {expPosY}")

    #                 if abs(acceptPosY - expPosY) > 20:
    #                     click(accept)
    #                 else:
    #                     log("Reached EXP Booster, stopping acceptance.")
    #                     foundExpBooster = True
    #             else:
    #                 click(accept)

    #         waitLoading()
    #         for _ in range(5):
    #             click(Location(900, 280))
    #         while True:
    #             existsClick(r"src\image\home\ok.png",timeout=0.01)
    #             if not existsClick(r"src\image\gift\ok .png", similarity=0.7) and exists(r"src\image\gift\gift box.png", timeout=0.1, similarity=0.95, capture=False):
    #                 break
    #             click(Location(470, 460))
    #             waitLoading()
            
    #         if  foundExpBooster or accepts == [] and swipeCounter >= 1:
    #             break
    #         elif foundExpBooster or accepts == [] and swipeCounter == 0:
    #             swipe(550, 290, 550, 200, 500) # swipe up
    #             swipeCounter += 1
    #     closePopUp()


def accept7Day(close=True):
    log(f"Accept 7 Day")
    if not exists(r"src\image\home\7D.png"):
        log("Dont Found 7 Day Icon")
        return
    click(r"src\image\home\7D.png")
    waitLoading()

    # day1 = colorMatch(getColor(Location(313, 446), capture=False), Color(255, 255, 239), 25) # day1
    # day2 = colorMatch(getColor(Location(393, 446), capture=False), Color(255, 255, 239), 25) # day2
    # day3 = colorMatch(getColor(Location(472, 446), capture=False), Color(255, 255, 239), 25) # day3
    # day4 = colorMatch(getColor(Location(551, 446), capture=False), Color(255, 255, 239), 25) # day4
    # day5 = colorMatch(getColor(Location(631, 446), capture=False), Color(255, 255, 239), 25) # day5
    # day6 = colorMatch(getColor(Location(710, 446), capture=False), Color(255, 255, 239), 25) # day6
    # day7 = colorMatch(getColor(Location(789, 446), capture=False), Color(255, 255, 239), 25) # day7

    day1 = Location(313, 446)
    day2 = Location(393, 446)
    day3 = Location(472, 446)
    day4 = Location(551, 446)
    day5 = Location(631, 446)
    day6 = Location(710, 446)
    day7 = Location(789, 446)


    if not exists(r"src\image\7day\1.png",timeout=0.01):
        if day1:
            for _ in range(2):
                click(Location(313, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        if day2:
            for _ in range(2):
                click(Location(393, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        if day3:
            for _ in range(2):
                click(Location(472, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        if day4:
            for _ in range(2):
                click(Location(551, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        if day5:
            for _ in range(2):
                click(Location(631, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        if day6:
            for _ in range(2):
                click(Location(710, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        if day7:
            for _ in range(2):
                click(Location(789, 446))
                if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                    waitLoading()
                    break
        
        if colorMatch(getColor(Location(894, 269)), Color(255, 239, 66)) or colorMatch(getColor(Location(66, 269)), Color(255, 239, 66)):
            if colorMatch(getColor(Location(894, 269)), Color(255, 239, 66)):
                click(Location(894, 269))
            elif colorMatch(getColor(Location(66, 269)), Color(255, 239, 66)):
                click(Location(66, 269))
            waitLoading()
            if day1:
                for _ in range(3):
                    click(Location(313, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break
            if day2:
                for _ in range(2):
                    click(Location(393, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break
            if day3:
                for _ in range(2):
                    click(Location(472, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break
            if day4:
                for _ in range(2):
                    click(Location(551, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break
            if day5:
                for _ in range(2):
                    click(Location(631, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break
            if day6:
                for _ in range(2):
                    click(Location(710, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break
            if day7:
                for _ in range(2):
                    click(Location(789, 446))
                    if existsClick(r"src\image\7day\ok.png", timeout=0.001):
                        waitLoading()
                        break

    if not exists(r"src\image\7day\1.png",timeout=0.01) and exists(r"src\image\7day\gacha ticket.png", similarity=0.975, timeout=0.001):
        click(Location(310, 444), waitTime=0.01) # ticket day1
        click(Location(310, 444), waitTime=0.01) # ticket day1
        click(Location(310, 444), waitTime=0.01) # ticket day1
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(390, 444), waitTime=0.01) # ticket day2
        click(Location(390, 444), waitTime=0.01) # ticket day2
        click(Location(390, 444), waitTime=0.01) # ticket day2
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(470, 444), waitTime=0.01) # ticket day3
        click(Location(470, 444), waitTime=0.01) # ticket day3
        click(Location(470, 444), waitTime=0.01) # ticket day3
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(550, 444), waitTime=0.01) # ticket day4
        click(Location(550, 444), waitTime=0.01) # ticket day4
        click(Location(550, 444), waitTime=0.01) # ticket day4
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(630, 444), waitTime=0.01) # ticket day5
        click(Location(630, 444), waitTime=0.01) # ticket day5
        click(Location(630, 444), waitTime=0.01) # ticket day5
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(710, 444), waitTime=0.01) # ticket day6
        click(Location(710, 444), waitTime=0.01) # ticket day6
        click(Location(710, 444), waitTime=0.01) # ticket day6
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(790, 444), waitTime=0.01) # ticket day7
        click(Location(790, 444), waitTime=0.01) # ticket day7
        click(Location(790, 444), waitTime=0.01) # ticket day7
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()

    elif exists(r"src\image\7day\1.png",timeout=0.01):
        click(Location(333, 444), waitTime=0.01) # ticket day1
        click(Location(333, 444), waitTime=0.01) # ticket day1
        click(Location(333, 444), waitTime=0.01) # ticket day1
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(484, 444), waitTime=0.01) # ticket day3
        click(Location(484, 444), waitTime=0.01) # ticket day3
        click(Location(484, 444), waitTime=0.01) # ticket day3
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(630, 440), waitTime=0.01) # ticket day5
        click(Location(630, 440), waitTime=0.01) # ticket day5
        click(Location(634, 444), waitTime=0.01) # ticket day5
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()
        click(Location(784, 444), waitTime=0.01) # ticket day7
        click(Location(784, 444), waitTime=0.01) # ticket day7
        click(Location(784, 444), waitTime=0.01) # ticket day7
        if existsClick(r"src\image\7day\ok.png"):
            waitLoading()

    if close:
        closePopUp()
        waitLoading()


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


def exportFileFromGameToBackup(text:str=""):
    if GAMEID == "":
        getGameID()
    # path ปลายทาง
    if text != "":
        filename = f"{GAMEID}_{text}.xml"
    else:
        filename = f"{GAMEID}.xml"
    path = os.path.join("backup", filename)
    # copy ด้วยสิทธิ์ root ไปโฟลเดอร์ sdcard (ที่ adb ดึงได้)
    DEVICE.shell("su -c 'cp /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml /sdcard/_LINE_COCOS_PREF_KEY.xml'")
    # ค่อยดึงออกมาที่เครื่อง
    DEVICE.pull("/sdcard/_LINE_COCOS_PREF_KEY.xml", path)
    # ลบไฟล์ชั่วคราวใน sdcard ได้
    DEVICE.shell("rm /sdcard/_LINE_COCOS_PREF_KEY.xml")

    log(f"Export File: {path}")
    return path


def exportFileFromGameWithGameIDToOutput(text:str=""):
    if GAMEID == "":
        getGameID()
    # path ปลายทาง
    if text != "":
        filename = f"{GAMEID}_{text}.xml"
    else:
        filename = f"{GAMEID}.xml"
    path = os.path.join("output", filename)
    # copy ด้วยสิทธิ์ root ไปโฟลเดอร์ sdcard (ที่ adb ดึงได้)
    DEVICE.shell("su -c 'cp /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml /sdcard/_LINE_COCOS_PREF_KEY.xml'")
    # ค่อยดึงออกมาที่เครื่อง
    DEVICE.pull("/sdcard/_LINE_COCOS_PREF_KEY.xml", path)
    # ลบไฟล์ชั่วคราวใน sdcard ได้
    DEVICE.shell("rm /sdcard/_LINE_COCOS_PREF_KEY.xml")

    log(f"Export File: {path}")
    return path


def exportFileFromGameToOutput(text:str=""):
    # path ปลายทาง
    if text != "":
        filename = f"{text}.xml"
    else:
        filename = f"{GAMEID}.xml"
    path = os.path.join("output", filename)
    # copy ด้วยสิทธิ์ root ไปโฟลเดอร์ sdcard (ที่ adb ดึงได้)
    DEVICE.shell("su -c 'cp /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml /sdcard/_LINE_COCOS_PREF_KEY.xml'")
    # ค่อยดึงออกมาที่เครื่อง
    DEVICE.pull("/sdcard/_LINE_COCOS_PREF_KEY.xml", path)
    # ลบไฟล์ชั่วคราวใน sdcard ได้
    DEVICE.shell("rm /sdcard/_LINE_COCOS_PREF_KEY.xml")

    log(f"Export File: {path}")
    return path


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


def tutorialWheel():
    log(f"Tutorial Wheel")
    click(r"src\image\tutorial\wheel icon.png",similarity=0.75)
    waitLoading()
    wait(0.2)
    goToHome()


def tutorialEventRaid():
    log(f"tutorial Event Raid")
    if not exists(r"src\image\event_raid\event_raid_dialog.png", timeout=2):
        return
    click(Location(172, 138))
    click(Location(172, 138))
    waitLoading()
    while True:
        click(Location(900, 280))
        existsClick(r"src\image\event_raid\rank_reward.png", timeout=0.01, capture=False)
        existsClick(r"src\image\event_raid\reward.png", timeout=0.01, capture=False)
        existsClick(r"src\image\event_raid\ranking.png", timeout=0.01, capture=False)
        existsClick(r"src\image\event_raid\ranking1.png", timeout=0.01, capture=False)
        existsClick(r"src\image\home\close.png")
        waitLoading()
        try:
            _attack = exists(r"src\image\event_raid\attack.png")
            if _attack and colorMatch(getColor(_attack, capture=False), Color(0, 174, 41), 5) or exists(r"src\image\event_raid\event_raid.png", similarity=0.955, timeout=0.001):
                break
        except:
            pass
    click(Location(29, 29))
    waitLoading()


def tutorialInHomeScreen():
    starTime = time.time()
    log("Tutorial In Home Screen")
    tutorialCycle = 1
    while True:
        log(f"tutorialCycle: {tutorialCycle}")
        waitLoading(0.001)
        captureScreen()
        existsClick(r"src\image\home\close.png", timeout=0.001, capture=False)
        existsClick(r"src\image\home\ok.png", timeout=0.001, capture=False)
        existsClick(r"src\image\home\cancel.png", timeout=0.001, capture=False)
        if exists(r"src\image\main_stage\treasure.png", timeout=0.001, capture=False):
            tutorial2()
        if exists(r"src\image\event_raid\event_raid_dialog.png", timeout=0.001, capture=False):
            tutorialEventRaid()
        if exists(r"src\image\tutorial\wheel icon.png", timeout=0.001, capture=False):
            tutorialWheel()
        if exists(r"src\image\bingo\bingo tutorial.png", similarity=0.7, timeout=0.001, capture=False):
            tutorialBingo()
        if exists(r"src\image\train\sos signal.png", timeout=0.001, capture=False) or exists(r"src\image\train\enter train.png", similarity=0.7, timeout=0.1, capture=False):
            tutorialTrain()
        if exists(r"src\image\home\understood.png", timeout=0.001, capture=False):
            tutorial5()
        if exists(r"src\image\home\choose a new ranger.png", timeout=0.001, capture=False):
            tutorial10()
        if exists(r"src\image\go_to\more.png", timeout=0.001, capture=False):
            goToHome()
        if exists(r"src\image\home\skip1.png", timeout=0.001, capture=False, similarity=0.7):
            tutorialLevel20()
        if exists(r"src\image\home\hey brown.png", timeout=0.001, capture=False):
            tutorial15()
        if exists(r"src\image\home\skip.png", timeout=0.001, capture=False) and exists(r"src\image\home\tutorial dialog good.png", timeout=0.001, capture=False):
            tutorial30()
        if exists(r"src\image\random dice\random dice event now open.png", timeout=0.001, capture=False):
            tutorialRandomDice()

        existsClick(r"src\image\home\close lab 2.png", 0.7, timeout=0.001, capture=False)
        if exists(r"src\image\home\skip.png", timeout=0.001, capture=False):
            skip()

        if not regionFindColor(Region(639, 15, 26, 26), Color(255, 239, 66), capture=False):
            if colorMatch(getColor((686, 149), capture=False), Color(255, 255, 255)): # 12 ให้สุ่มกาชาเกียร์ ใส่เกีบร์
                tutorial12()
            if regionFindColor(exists(r"src\image\home\7D.png", timeout=0.001), Color(255, 251, 255), 20, capture=False):
                tutorial7Day(mainStage=False)
            if regionFindColor(exists(r"src\image\home\quest.png", timeout=0.001), Color(255, 239, 66), 20, capture=False) or exists(r"src\image\home\dialog tutorialQuest.png", timeout=0.001, capture=False):
                tutorialQuest(mainStage=False)
            if tutorialCycle > 1:
                click((10, 10), waitTime=0.25)

        if exists(r"src\image\main_stage\go main stage.png", timeout=0.001, capture=True, similarity=0.9) and not exists(r"src\image\home\loading.png", 0.5, timeout=0.001, capture=False):
            _go_main = find(r"src\image\main_stage\go main stage.png", capture=False)
            if _go_main and regionFindColor(_go_main, Color(225, 223, 0), 20, capture=False):
                _night_color = colorMatch(getColor((652, 20), capture=False), Color(74, 73, 16), 20)
                if not _night_color:
                    break
                else:
                    existsClick(r"src\image\main_stage\go main stage.png", timeout=0.001)
                    waitLoading()
        if (time.time() - starTime > 180) or exists(r"src\image\home\LINE.png", timeout=0.001, capture=False) or tutorialCycle > 5:
            raise TimeoutError("Timeout in tutorial home > 180 sec or Cycle >= 5")
        tutorialCycle += 1


def tutorialGenID():
    log(f"Tutorial Gen ID")
    log(f"Loop Click", end="")
    counter = 0
    while True:
        counter += 1
        if counter % 8 == 0:
            print(".",end="", flush=True)
        click(Location(512, 392), waitTime=0.2) #  1
        click(Location(511, 341), waitTime=0.2) #  2
        click(Location(479, 93), waitTime=0.2) #  3
        click(Location(760, 450), waitTime=0.2) #  4
        click(Location(278, 446), waitTime=0.2) #  5
        click(Location(160, 436), waitTime=0.2) #  6
        click(Location(680, 447), waitTime=0.2) #  7
        click(Location(472, 485), waitTime=0.2) #  8
        click(Location(45, 39), waitTime=0.2) #  9
        click(Location(663, 120), waitTime=0.2) #  10
        swipe(359, 186, 212, 485) # 11
        swipe(212, 485, 159, 172) # 12
        click(Location(179, 340), waitTime=0.2) #  13
        click(Location(578, 467), waitTime=0.2) #  14
        click(Location(377, 461), waitTime=0.2) #  15
        click(Location(470, 430), waitTime=0.2) #  16
        click(Location(682, 359), waitTime=0.2) #  17
        if regionFind(Region(700, 481, 60, 20), r"src\image\home\percent.png"):
            log(f"Tutorial Gen ID Done")
            break
        if exists(r"src\image\home\agree.png", timeout=0.1, capture=False) or counter > 200:
            return "error login"
    print()
    waitLoadingScreen()
    skip()
    closePopUp()
    playMainStageAtNumber(1, closeGame=True)
    return True


def matchGachaName(allNames:dict, name:str):
    for key in allNames.keys():
        is_match, score = fuzzy_match(key, name)
        # print(is_match, f"{score:.2f}", "||", key, "=", name)
        if is_match:
            return True, allNames[key].replace(" ", "")
    return False, name.replace(" ", "")


def add_ranger_name(rangerNames: str, rangerName: str) -> str:

    if rangerNames == "":
        return rangerName

    names = rangerNames.split("_")

    def split_name_number(name):
        m = re.match(r"^(.*?)(\d+)$", name)
        if m:
            return m.group(1), int(m.group(2))
        return name, None

    base_matches = []
    for i, name in enumerate(names):
        base, num = split_name_number(name)
        if base == rangerName:
            base_matches.append((i, base, num))

    if not base_matches:
        return rangerNames + "_" + rangerName

    # ให้ update ชื่อเก่าตัวแรกที่เจอ (index ต่ำสุด)
    idx, base, num = base_matches[0]

    # ถ้าไม่มีเลข เช่น Cony → Cony2
    if num is None:
        new_name = f"{base}2"
    else:
        new_name = f"{base}{num + 1}"

    names[idx] = new_name

    return "_".join(names)

def tutorialGacha():
    if existsClick(r"src\image\gacha\ok.png", timeout=0.1):
        waitLoading()
    if not exists(r"src\image\gacha\learn more about the gachas.png", timeout=0.1, similarity=0.7):
        return
    log(f"Tutorial Gacha")
    for _ in range(15):
        click(Location(806, 81), waitTime=0.3)
    for _ in range(10):
        click(Location(754, 439), waitTime=0.3)
    click(Location(858, 35), waitTime=0.3)
    for _ in range(10):
        click(Location(763, 28), waitTime=0.3)
    click(Location(25, 25), waitTime=0.3)
    click(Location(25, 100), waitTime=0.3)

def randomGachaRanger(selction_event:int=1, stop_when_found:bool=True, gacha_mode:str="giveItAll", gacha_cycles:int=5, use_ruby:bool=False):
    global current_gacha_cycles
    rangerNames = ""
    log(f"RandomGacha selction_event:{selction_event} stop_when_found:{stop_when_found} gacha_mode:{gacha_mode} gacha_cycles:{gacha_cycles} use_ruby:{use_ruby}")

    while not exists(r"src\image\gacha\gacha.png", similarity=0.7, timeout=0.1):
        goTo(r"src\image\go_to\gacha.png")
        tutorialGacha()

    waitLoading(timeOut=0.1)
    if existsClick(r"src\image\gacha\ok.png"):
        waitLoading()
    log(f"gachaSelctionEvent: {selction_event}")
    gachaSelctionEvent(selction_event)
    
    while True:
        captureScreen()
        if (gacha_mode == "NumberOfCycles" and current_gacha_cycles >= gacha_cycles):
            break
        if exists(r"src\image\gacha\1 time 50 ruby.png", timeout=0.1, capture=False):
            if use_ruby:
                existsClick(r"src\image\gacha\1 time 50 ruby.png", timeout=0.1, capture=False)
                if exists(r"src\image\gacha\you neet more rubies.png", timeout=0.1):
                    click(r"src\image\gacha\cancel.png")
                    break
            else:
                break
        existsClick(r"src\image\gacha\5 gacha ticket.png", timeout=0.1, capture=False)
        existsClick(r"src\image\gacha\once more.png",timeout=0.1, capture=False)
        waitLoading()
        if (exists(r"src\image\gacha\20 ruby.png", timeout=0.1, similarity=0.7) and not use_ruby) or exists(r"src\image\gacha\you neet more rubies.png", timeout=0.1):
            click(r"src\image\gacha\cancel.png")
            waitLoading()
            existsClick(r"src\image\gacha\ok.png")
            waitLoading()
            waitLoading()
            break
        existsClick(r"src\image\gacha\ok.png")
        waitLoading()
        wait(1)
        click(Location(900, 270))
        click(Location(900, 270))
        # wait(3)
        wait(r"src\image\gacha\ok.png", timeout=5)
        rangerNameOCR = getGachaRangerName()
        log(f"RangerName: {rangerNameOCR}")
        is_match, rangerName = matchGachaName(RANGERSCONFIG, rangerNameOCR)
        if is_match:
            rangerNames = add_ranger_name(rangerNames, rangerName)

            if stop_when_found:
                break
        current_gacha_cycles += 1
    return rangerNames

def ExchangeGachaTickets():
    if not exists(r"src\image\gacha\gacha.png"):
        goTo(r"src\image\go_to\gacha.png")
        waitLoading()
    m_point = 0
    try:
        m_point = int(textRBTKOCR(Region(667, 18, 67, 20), psm=13, imageProcessing=True))
    except Exception:
        log(f"Can't read M point")
        return 0
    log(f"M point: {m_point}")
    cycles = m_point // 1000
    if cycles == 0:
        log(f"M point not enough")
        return 0
    click(r"src\image\gacha\shop.png")
    waitLoading()
    count = 0
    for _ in range(cycles):
        if not existsClick(r"src\image\gacha\gacha tickets.png", timeout=0.1):
            log(f"Not found gacha tickets.png")
            goTo(r"src\image\go_to\gacha.png")
            break
        existsClick(r"src\image\gacha\buy.png")
        if exists(r"src\image\gacha\you dont have m point.png"):
            click(r"src\image\gacha\ok.png")
            closePopUp()
            break
        existsClick(r"src\image\gacha\ok.png")
        waitLoading()
        existsClick(r"src\image\gacha\ok.png")
        waitLoading()
        count += 1
    log(f"Exchange {count} Tickets")
    return count


def closePopUp(dontShowToday=False, showLog=True):
    starTime = time.time()
    if showLog:
        log("Close Pop Up")
    while True:
        closes = findAll(r"src\image\home\close.png")
        if closes == []:
            break
        if dontShowToday:
            existsClick(r"src\image\home\dont show today.png", timeout=0.01, capture=False)
        for r in closes:
            # if colorMatch(getColor(r.getTopCenter(), capture=False), Color(255, 239, 66)):
            click((r.x, r.y+3))
            break
        existsClick(r"src\image\home\cancel.png", timeout=0.01, capture=False)
        existsClick(r"src\image\home\ok.png", timeout=0.01, capture=False)

        if time.time() - starTime > 60:  # ถ้าทำงานเกิน 1 นาที
            raise TimeoutError(f"Close PopUp time out > 60 sec")


def openLineRangers(fast=False, dontShowToday=False, genid=False, skipLoadingScreen=False):
    global CHANGEID
    maintimeoutopengame = 300
    starttimeoutopengame = time.time()
    authentication_failed = False
    try_login_count = 0
    try:
        while True:
            # ตรวจสอบ timeout หลัก 5 นาที
            if time.time() - starttimeoutopengame >= maintimeoutopengame:
                log(f"openLineRangers timeout > {maintimeoutopengame} sec (5 minutes)")
                raise TimeoutError(f"openLineRangers exceeded {maintimeoutopengame} seconds")

            force_stop_LINE_Rangers()
            DEVICE.shell("monkey -p com.linecorp.LGRGS -c android.intent.category.LAUNCHER 1")
            log(f"Opening LINE Rangers")
            startTime = time.time()
            while True:
                waitLoading()
                nowTime = time.time()
                if exists(r"src\image\home\LINE studio.png", timeout=0.1, capture=False):
                    waitVanish(r"src\image\home\LINE studio.png")
                    waitLoading()
                    break
                elif exists(r"src\image\home\percent.png", timeout=0.1, capture=False) or exists(r"src\image\home\LINE.png", timeout=0.1, capture=False):
                    break
                elif nowTime - startTime >= timeoutopengame or existsClick(r"src\image\home\not responding Close app.png", timeout=0.25, capture=False):
                    log(f"Open LINE Rangers time out > {timeoutopengame} sec")
                    force_stop_LINE_Rangers()
                    DEVICE.shell("monkey -p com.linecorp.LGRGS -c android.intent.category.LAUNCHER 1")
                    startTime = time.time()
            waitLoading(timeOut=0.1)
            existsClick(r"src\image\home\ok.png", timeout=0.01)
            existsClick(r"src\image\home\play.png", timeout=0.01, capture=False)

            if exists(r"src\image\home\API Hooking.png", timeout=0.01, capture=False):
                existsClick(r"src\image\home\API Hooking ok.png")
                log(f"Error API Hooking")
                continue

            if exists(r"src\image\home\login_fail.png", timeout=0.01):
                log(f"Login Failed Detected")
                authentication_failed = True
            
            if not genid:
                if exists(r"src\image\home\reload.png", similarity=0.7, timeout=0.1):
                    click(exists(r"src\image\home\reload.png", similarity=0.7, timeout=0.1))
                    log(f"Check Internal Resource")
                    waitLoading()
                    click(r"src\image\home\check.png")
                    wait(1)
                    waitLoading()
                    if exists(r"src\image\home\login_fail.png", timeout=0.01):
                        log(f"Login Failed Detected")
                        authentication_failed = True
                    elif not existsClick(r"src\image\home\ok.png"): # select language
                        if wait(r"src\image\home\agree.png", timeout=8):
                            for _ in range(5):
                                if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                                    break
                                sleep(0.3)
                            wait(1)
                            click(r"src\image\home\agree.png")
                            wait(1)
                            waitLoading()
                            existsClick(r"src\image\home\ok.png", timeout=5) # select language
                            waitLoading()


            elif exists(r"src\image\home\sing in with apple.png", timeout=0.1):
                if not exists(r"src\image\home\guest login.png", 0.7, timeout=0.1):
                    log(f"Sing In With Apple")
                    click(r"src\image\home\sing in with apple.png")
                    wait(2)
                    wait(r"src\image\home\agree.png", timeout=8)
                    for _ in range(5):
                        if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                            break
                        sleep(0.3)
                    wait(1)
                    click(r"src\image\home\agree.png")
                    wait(5)
                    pressBack()
                    wait(2)

                if exists(r"src\image\home\guest login.png", 0.7, timeout=5):
                    log(f"Guest Login")
                    click(r"src\image\home\guest login.png", 0.7)
                    wait(1)
                    existsClick(r"src\image\home\login.png", timeout=4)
                    wait(2)
                    wait(r"src\image\home\agree.png", timeout=8)
                    for _ in range(5):
                        if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                            break
                        sleep(0.3)
                    wait(1)
                    click(r"src\image\home\agree.png")
                    wait(2)

                if exists(r"src\image\home\ok.png", timeout=5):
                    existsClick(r"src\image\home\ok.png")
                    if exists(r"src\image\home\guest login.png", 0.7):
                        click(r"src\image\home\guest login.png", 0.7)
                        wait(1)
                        existsClick(r"src\image\home\login.png", timeout=4)
                        wait(2)
                        wait(r"src\image\home\agree.png", timeout=8)
                        for _ in range(5):
                            if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                                break
                            sleep(0.3)
                        wait(1)
                        click(r"src\image\home\agree.png")
                        wait(2)

                existsClick(r"src\image\home\ok.png", timeout=5) # select language
                waitLoading()

            if skipLoadingScreen:
                log("skip loading screen")
                if authentication_failed:
                    return "authentication_failed"
                return

            waitLoadingScreen()
            try_login_count += 1

            if (try_login_count > 3 or authentication_failed or exists(r"src\image\home\set nickname.png") or exists(r"src\image\home\100% HP Tower.png", capture=False) or exists(r"src\image\home\1880-1880.png", capture=False)):
                log(f"Found Set Nickname")
                # updateFileInExecute("เข้าไม่ได้")
                try:
                    if REIMPORTFILE != FILENAME:
                        reImportFileInExecute()
                        # exportFileFromExecuteToLoginFailed()
                    elif REIMPORTFILE == FILENAME:
                        exportFileFromExecuteToLoginFailed()
                        return "set nickname"
                except Exception as e:
                    log(f"Exception exportFileFromExecuteToLoginFailed:\n{e}")
                CHANGEID = True
                # return "set nickname"
            else:
                break
        if not fast:
            maintimeoutopengame += 60
            while True:
                # ตรวจสอบ timeout หลัก 6 นาที
                if time.time() - starttimeoutopengame >= maintimeoutopengame:
                    log(f"openLineRangers timeout > {maintimeoutopengame} sec (6 minutes)")
                    raise TimeoutError(f"openLineRangers exceeded {maintimeoutopengame} seconds")

                closePopUp(dontShowToday)
                tutorialInHomeScreen()
                if exists(r"src\image\main_stage\go main stage.png"):
                    break

        log(f"Successfully Open LINE Rangers")
    except Exception as e:
        print("========= Error =========")
        log(f"Exception in Open Line Rangers:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")


def autoSetUp(deviceSerial):
    print("======= Auto SetUp ======", flush=True)
    setUp(deviceSerial)
    try:
        while True:
            force_stop_LINE_Rangers()
            removeAllFiles(showLog=True)
            DEVICE.shell("monkey -p com.linecorp.LGRGS -c android.intent.category.LAUNCHER 1")
            log(f"Opening LINE Rangers")
            startTime = time.time()
            while True:
                captureScreen()
                nowTime = time.time()
                if exists(r"src\image\home\LINE studio.png", timeout=0.25, capture=False):
                    waitVanish(r"src\image\home\LINE studio.png")
                    wait(1)
                    waitLoading()
                    wait(1)
                    break
                elif exists(r"src\image\home\percent.png", timeout=0.25, capture=False) or exists(r"src\image\home\LINE.png", timeout=0.25, capture=False):
                    break
                elif nowTime - startTime >= timeoutopengame or existsClick(r"src\image\home\not responding Close app.png", timeout=0.25, capture=False):
                    log(f"Open LINE Rangers time out > {timeoutopengame}] sec")
                    force_stop_LINE_Rangers()
                    DEVICE.shell("monkey -p com.linecorp.LGRGS -c android.intent.category.LAUNCHER 1")
                    startTime = time.time()
            waitLoading()
            existsClick(r"src\image\home\ok.png")
            existsClick(r"src\image\home\play.png")

            if exists(r"src\image\home\API Hooking.png"):
                existsClick(r"src\image\home\API Hooking ok.png")
                log(f"Error API Hooking")
                continue

            if exists(r"src\image\home\sing in with apple.png"):
                if not exists(r"src\image\home\guest login.png", 0.7):
                    log(f"Sing In With Apple")
                    click(r"src\image\home\sing in with apple.png")
                    wait(2)
                    wait(r"src\image\home\agree.png", timeout=8)
                    for _ in range(5):
                        if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                            break
                        sleep(0.3)
                    wait(1)
                    click(r"src\image\home\agree.png")
                    wait(5)
                    pressBack()
                    wait(2)

                if exists(r"src\image\home\guest login.png", 0.7, timeout=5):
                    log(f"Guest Login")
                    click(r"src\image\home\guest login.png", 0.7)
                    wait(1)
                    existsClick(r"src\image\home\login.png", timeout=4)
                    wait(2)
                    wait(r"src\image\home\agree.png", timeout=8)
                    for _ in range(5):
                        if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                            break
                        sleep(0.3)
                    wait(1)
                    click(r"src\image\home\agree.png")
                    wait(2)

                if exists(r"src\image\home\ok.png", timeout=5):
                    existsClick(r"src\image\home\ok.png")
                    if exists(r"src\image\home\guest login.png", 0.7):
                        click(r"src\image\home\guest login.png", 0.7)
                        wait(1)
                        existsClick(r"src\image\home\login.png", timeout=4)
                        wait(2)
                        wait(r"src\image\home\agree.png", timeout=8)
                        for _ in range(5):
                            if not existsClick(r"src\image\home\checkbox.png", similarity=0.85):
                                break
                            sleep(0.3)
                        wait(1)
                        click(r"src\image\home\agree.png")
                        wait(2)

                existsClick(r"src\image\home\ok.png", timeout=5) # select language
                waitLoading()

            waitLoading()
            waitLoading()
            log(f"Found Set Nickname")
            force_stop_LINE_Rangers()
            print("========== End ==========", flush=True)
            return "set nickname"
    except Exception as e:
        print("========= Error =========")
        log(f"Exception in Open Line Rangers:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")


def startBotPlayMainStage30_100_150(deviceSerial):
    global STAGENUMBER, GIFTBOX, CHANGEID, AUTOTEAM
    fileGameId = "0123456789"  # เซ็ตค่าเริ่มต้น
    while fileGameId != "":
        CHANGEID = True
        STAGENUMBER = 0
        print("========= Start =========", flush=True)
        print(">>> startBotPlayMainStage30_100_150 <<<", flush=True)
        # ลูนเล่นสเตจหลัก
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")
        while STAGENUMBER < 150:
            try:
                if CHANGEID:
                    force_stop_LINE_Rangers()
                    importFileFromInputToExecute()
                    CHANGEID = False

                open_line_ranger = openLineRangers() # ออกเกม / เข้าเกม
                if open_line_ranger == "set nickname":
                    break   # << ออกจาก while stageNumber <= stageEnd

                if GIFTBOX:
                    acceptGiftBox()
                    GIFTBOX = False

                playstage30_100_150()
                
                if UPDATERBTK:
                    updateFileWithRBTK()

                break
            except TimeoutError as e:
                captureScreenError(str(e))
                log(f"Restart bot due to timeout: {e}")
                continue   # << วน while True ใหม่
            except Exception as e:
                captureScreenError(str(e))
                log(f"Unexpected error: {e}")
                traceback.print_exc()

        try:
            if not open_line_ranger == "set nickname":
                exportFileFromExecuteToOutput()
        except Exception as e:
            captureScreenError(str(e))
            log(f"In exportFile error: {e}")
            traceback.print_exc()

        fileGameId = in_current_file()
        if not fileGameId:
            # ถ้าไม่เจอไฟล์ไหนเลยที่ลงท้ายด้วย .xml
            fileGameId = ""   # ทำให้ while หลุด
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break
        print("========== End ==========", flush=True)
    
    force_stop_LINE_Rangers()
    print("========== End ==========", flush=True)



def startBotGenID(deviceSerial):
    global CHANGEID, GAMEID
    fileGameId = "0123456789"  # เซ็ตค่าเริ่มต้น

    while fileGameId != "":
        GAMEID = ""
        _tutorialGenID = False
        print("========= Start =========", flush=True)
        print(">>> startBotGenID <<<", flush=True)
        # ลูนเล่นสเตจหลัก
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")

        force_stop_LINE_Rangers()
        removeAllFiles(showLog=False)
        while True:
            try:
                if GAMEID == "":
                    openLineRangers(genid=True)
                    while True:
                        if exists(r"src\image\home\setup complete.png"):
                            break
                        existsClick(r"src\image\home\ok.png", timeout=0.1)
                        waitLoading()
                    # GAMEID = textOCR(Region(334, 239, 289, 58), psm=13, crop=False)
                    GAMEID = getGameID()

                if _tutorialGenID == False:
                    _tutorialGenID = tutorialGenID()
                if _tutorialGenID == "error login":
                    break
                
                asd
                
                exportFileFromGameWithGameIDToOutput()
                force_stop_LINE_Rangers()
                break
            except TimeoutError as e:
                captureScreenError(str(e))
                log(f"Restart bot due to timeout: {e}")
                continue   # << วน while True ใหม่
            except Exception as e:
                captureScreenError(str(e))
                log(f"Unexpected error: {e}")
                traceback.print_exc()

        print("========== End ==========", flush=True)
    
    force_stop_LINE_Rangers()
    print("========== End ==========", flush=True)

def clearSpecialQuest():
    log(f"Clear Special Quest")
    goToHome()
    try:
        level = int(numberOCR(Region(30, 45, 54, 29), r"src\image\home\level", similarity=0.85))
        log(f"Current Level: {level}")
        if level < 77:
            log(f"Level must be at least 77 to play Special Quest")
            return
    except:
        log(f"Can't Read Current Level")
        return

    while True:
        _sally = exists(r"src\image\quest\sally clear all mission.png", timeout=0.1, similarity=0.7)
        if not _sally:
            closePopUp()
            goToHome()
            if not exists(r"src\image\quest\quest icon.png", timeout=0.1, similarity=0.7):
                return
        else:
            if not exists(r"src\image\quest\quest icon.png", timeout=0.1, similarity=0.7, capture=False):
                return
        existsClick(r"src\image\quest\quest icon.png", similarity=0.7) # เควสพิเศษ
        waitLoading()

        while True:
            if existsClick(r"src\image\mission\get.png"):
                waitLoading()
                existsClick(r"src\image\mission\ok.png", timeout=0.5)
                existsClick(r"src\image\mission\exp up ok.png", timeout=0.5)
                waitLoading()
                click(Location(900, 500)) # close popup
            elif not existsClick(r"src\image\mission\exp up ok.png"):
                break

        try:
            quest_number = int(numberOCR(Region(133, 210, 56, 100), r"src\image\quest\n", similarity=0.85))
        except:
            quest_number = 0
            _q28 = Region(30, 45, 54, 29)
            _q28 = exists(r"src\image\quest\quest 28.png", similarity=0.75)
            if regionFind(_q28, r"src\image\quest\go.png", similarity=0.9, capture=False):
                existsClick(r"src\image\home\close.png")
                return
            elif regionFind(_q28, r"src\image\quest\get.png", similarity=0.9, capture=False):
                quest_number = 28
            else:
                _q29 = Region(30, 45, 54, 29)
                _q29 = exists(r"src\image\quest\quest 29.png", similarity=0.75)
                if regionFind(_q29, r"src\image\quest\go.png", similarity=0.9, capture=False):
                    quest_number = 29

        log(f">>> quest_number: {quest_number} <<<")
        if quest_number != 0:
            click(Location(765, 263)) # go
            existsClick(r"src\image\quest\go.png", similarity=0.9, timeout=0.1)
        click(Location(900, 500)) # close popup
        waitLoading()
        if existsClick(r"src\image\quest\ok.png"):
            continue

        waitLoading()
        if quest_number == 0:
            if not exists(r"src\image\quest\go.png"):
                playSpecialQuest0()
                return
        elif quest_number == 1:
            log(f"quest {quest_number} Clear Main Stage 3 Time")
            pass
        elif quest_number == 2:
            log(f"quest {quest_number} Clear Main Stage 2 Time")
            playSpecialQuest2()
        elif quest_number == 3:
            log(f"quest {quest_number} Combine Rangers 1 Time")
            playSpecialQuest3()
        elif quest_number == 4:
            log(f"quest {quest_number} Achieve 1 Time(s)")
            playSpecialQuest4()
        elif quest_number == 5:
            log(f"quest {quest_number} Achieve 100% of Treasure 'Valley of Wind'")
            pass
        elif quest_number == 6:
            log(f"quest {quest_number} Complete Special Quese 5 Time(s)")
            pass
        elif quest_number == 7:
            log(f"quest {quest_number} Combine Rangers 1 Time")
            playSpecialQuest3()
        elif quest_number == 8:
            log(f"quest {quest_number} Clear Main Stage 3 Time")
            playSpecialQuest8()
        elif quest_number == 9:
            log(f"quest {quest_number} Equip Ranger whih 1 Piece(s) of Gear")
            playSpecialQuest9()
        elif quest_number == 10:
            log(f"quest {quest_number} Achieve 1 Time(s)")
            playSpecialQuest4()
        elif quest_number == 11:
            log(f"quest {quest_number} Achieve 100% of Treasure 'Mysterious Forest'")
            pass
        elif quest_number == 12:
            log(f"quest {quest_number} Complete Special Quese 11 Time(s)")
            pass
        elif quest_number == 13:
            log(f"quest {quest_number} Combine Rangers 1 Time")
            playSpecialQuest3()
        elif quest_number == 14:
            log(f"quest {quest_number} Clear Special Stage 3 Time")
            playSpecialQuest14()
        elif quest_number == 15:
            log(f"quest {quest_number} PLay PVP 1 Time")
            playSpecialQuest15()
        elif quest_number == 16:
            log(f"quest {quest_number} Achieve 100% of Treasure 'dark Theme Park'")
            pass
        elif quest_number == 17:
            log(f"quest {quest_number} Clear Main Stage 3 Time")
            playSpecialQuest8()
        elif quest_number == 18:
            log(f"quest {quest_number} Complete Special Quese 17 Time(s)")
            pass
        elif quest_number == 19:
            log(f"quest {quest_number} Use EXP Booster 1 Time(s)")
            playSpecialQuest19()
        elif quest_number == 20:
            log(f"quest {quest_number} Selsect a Guild to Join")
            q = playSpecialQuest20()
            if q == "24_hour":
                return
        elif quest_number == 21:
            log(f"quest {quest_number} Help 1 Guild Member(s)")
            playSpecialQuest21()
        elif quest_number == 22:
            log(f"quest {quest_number} Achieve 100% of Treasure 'Rainbow Waterfall'")
            pass
        elif quest_number == 23:
            log(f"quest {quest_number} Win in PVP 3 Time(s)")
            playSpecialQuest15()
            playSpecialQuest15()
            playSpecialQuest15()
        elif quest_number == 24:
            log(f"quest {quest_number} Complete Special Quese 23 Time(s)")
            pass
        elif quest_number == 25:
            log(f"quest {quest_number} Participate in 1 Guild Raid(s)")
            playSpecialQuest25()
        elif quest_number == 26:
            log(f"quest {quest_number} +1 Enchance Gear")
            playSpecialQuest26()
        elif quest_number == 27:
            log(f"quest {quest_number} Train 1 time(s) in the Training Center")
            playSpecialQuest27()
        elif quest_number == 28:
            log(f"quest {quest_number} Log in to LINE Rangers 3 times")
            return
        elif quest_number == 29:
            log(f"quest {quest_number} Create 1 Hi Str. Posion (s)")
            playSpecialQuest29()

def playSpecialQuest0():
    click(Location(720, 150)) # ruby pack icon
    click(Location(720, 150)) # ruby pack icon
    waitLoading()
    while True:
        click(Location(480, 300)) # tap
        existsClick(r"src\image\quest\ok.png")
        waitLoading()
        try:
            _go_main = exists(r"src\image\main_stage\go main stage.png", timeout=0.001, capture=True, similarity=0.9)
            if _go_main and regionFindColor(_go_main, Color(225, 223, 0), 20, capture=False) and not colorMatch(getColor((652, 20), capture=False), Color(74, 73, 16), 20):
                break
        except:
            pass


def playSpecialQuest2():
    global HIGHERSTAGE
    HIGHERSTAGE = 151
    playMainStageAtNumber(number=2, loop=2)
    goToHome()

def playSpecialQuest3():
    # skip tutorial
    closePopUp()
    captureScreen()
    if (colorMatch(getColor(Location(480, 10), capture=False), Color(74, 69, 57), 10)):
        if colorMatch(getColor(r"src\image\team\teamA.png", 0.65, capture=False), Color(165, 89, 0), 10):
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
        if colorMatch(getColor((680, 80), capture=False), Color(247, 223, 173), 10):
            click((680, 80), waitTime=0.5)
            click((680, 80), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)

    closePopUp()

    X = 80
    swipe(X + 195, 180, 195, 350) # slot 1
    swipe(X + 338, 180, 338, 350) # slot 2
    swipe(X + 482, 180, 482, 350) # slot 3
    swipe(X + 626, 180, 626, 350) # slot 4
    swipe(X + 768, 180, 768, 350) # slot 5
    wait(0.5)

    click(r"src\image\team\filter.png") # filter
    click(r"src\image\team\reset.png") # reset
    click(r"src\image\team\6_star.png") # 6 star
    click(r"src\image\team\normal_ranger.png") # normal ranger
    click(r"src\image\team\ranger.png") # ranger
    click(r"src\image\team\ok.png") # ok
    click(r"src\image\team\sort by.png") # sort by
    click(r"src\image\team\sort by level.png", similarity=0.9) # level ▲
    sleep(0.3)
    swipe(238, 450, 270, 180) # 1 ranger 
    sleep(0.3)

    click((786, 327), waitTime=0.5) # filter
    click((393, 484), waitTime=0.5) # reset
    click((327, 331), waitTime=0.5) # ranger
    click((558, 483), waitTime=0.5) # ok
    click((656, 326), waitTime=0.5) # sort by
    click((247, 383), waitTime=0.5) # grade

    wait(0.2)
    while True:
        compareMineralCost(Region(438, 487, 60, 21), 1300)
        swipe(338, 450, X + 338, 180) # ranger 2
        waitLoading()
        if not existsClick(r"src\image\home\ok.png", timeout=0.1):
            break
        waitLoading()
        swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
        waitLoading()
        waitLoading()
    swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
    wait(1)
    while True:
        compareMineralCost(Region(438, 487, 60, 21), 1300)
        swipe(480, 450, X + 482, 180) # ranger 3
        waitLoading()
        if not existsClick(r"src\image\home\ok.png", timeout=0.1):
            break
        waitLoading()
        swipe(500, 450, 460, 450) # เลื่อน 1 ตัว
        waitLoading()
        waitLoading()


    click(Location(29, 29), waitTime=0.5) # level up
    existsClick(r"src\image\team\save.png")
    waitLoading()
    tutorialInHomeScreen()

    click(r"src\image\team\6_star_s.png") # 6 star
    waitLoading()
    click(r"src\image\team\level up button.png") # level up
    waitLoading()
    click(r"src\image\team\sort by.png") # sort by
    click(r"src\image\team\sort_by_grade.png", similarity=0.9) # grade ▲
    sleep(0.3)
    swipe(330, 458, 340, 240, 600) # swip ranger
    click(r"src\image\team\level up button green.png") # level up
    waitLoading()
    click(r"src\image\team\ok.png") # ok
    waitLoading()
    existsClick(r"src\image\team\ok.png") # ok
    waitLoading()
    wait(2)
    click(Location(783, 230), waitTime=0.5) # level up
    click(Location(783, 230), waitTime=0.5) # level up
    waitLoading()
    goToHome()


def playSpecialQuest4():
    click(Location(886, 397)) # gold icon
    waitLoading()
    click(Location(555, 405)) # ok
    waitLoading()
    wait(2)
    click(Location(480, 270)) # 
    click(Location(480, 270)) # 
    goToHome()

def playSpecialQuest5():
    waitLoading()
    wait(4)
    goToHome()

def playSpecialQuest6():
    while True:
        if existsClick(r"src\image\mission\get.png"):
            waitLoading()
            existsClick(r"src\image\mission\ok.png", timeout=0.5)
            existsClick(r"src\image\mission\exp up ok.png", timeout=0.5)
            waitLoading()
        else:
            break


def playSpecialQuest8():
    global HIGHERSTAGE
    HIGHERSTAGE = 151
    playMainStageAtNumber(number=2, loop=3)
    goToHome()


def playSpecialQuest9():
    click(Location(233, 276), waitTime=0.5)
    waitLoading()
    click(r"src\image\quest\slot.png")
    waitLoading()
    click(r"src\image\quest\gear info.png")
    click(Location(756, 468), waitTime=0.5)
    waitLoading()
    click(Location(555, 409), waitTime=0.5)
    waitLoading()
    goToHome()


def findEvolutionMineFrist():
    L = 0
    dairation = "R"
    evolution_mine_frist = None
    while True:
        evolution_mine_frist = exists(r"src\image\special_stage\evolution mine frist.png", similarity=0.7)
        if evolution_mine_frist != None:
            break
        elif dairation == "R":
            swipe(610, 370, 260, 370, 1500)
            if exists(r"src\image\special_stage\skull stone first.png", similarity=0.7):
                dairation = "L"
        elif dairation == "L":
            swipe(260, 370, 610, 370, 1500)
            if L >= 10:
                dairation == "R"
                L = 0
            L += 1
    waitLoading()
    click(regionFind(evolution_mine_frist, r"src\image\special_stage\num1.png", similarity=0.9))
    waitLoading()


def playSpecialQuest14():
    findEvolutionMineFrist()

    if exists(r"src\image\special_stage\frist.png"):
        click(r"src\image\special_stage\enter.png") # enter
        waitLoading()
        existsClick(r"src\image\special_stage\auto.png")
        existsClick(r"src\image\special_stage\x2.png")
        click(Location(477, 488), waitTime=0.5) # next
        click(Location(477, 488), waitTime=0.5) # next
        waitLoading()
        click(Location(550, 104), waitTime=0.5) # sidkick
        click(Location(404, 377), waitTime=0.5) # friend
        click(Location(696, 480), waitTime=0.5) # start
        waitLoading()
        while True:
            click(Location(815, 415))
            waitLoading()
            click(slotItem1, waitTime=0.5)
            click(slotItem5, waitTime=0.5)
            click(slotItem3, waitTime=0.5)
            wait(5)
            click(slotItem4, waitTime=0.5)
            click(slotItem2, waitTime=0.5)
            if exists(r"src\image\main_stage\win.png", similarity=0.7):
                break
            if exists(r"src\image\home\close.png", timeout=0.1, capture=False):
                raise Exception(f"Failed to clear Special Quest 14")

        for _ in range(20):
            click(Location(480, 445), waitTime=0.1)

        if not exists(r"src\image\special_stage\enter.png"):
            goTo(r"src\image\go_to\special stage.png")
            findEvolutionMineFrist()

    
    click(r"src\image\special_stage\enter.png") # enter
    waitLoading()
    waitLoading()
    click(r"src\image\special_stage\loop.png")
    waitLoading()
    click(Location(475, 225), waitTime=0.5) # +
    click(Location(552, 405), waitTime=0.5) # ok
    click(Location(477, 488), waitTime=0.5) # next
    waitLoading()
    click(Location(696, 480), waitTime=0.5) # start
    waitLoading()
    wait(r"src\image\main_stage\congrat.png")
    click(r"src\image\main_stage\congrat ok.png")
    waitLoading()
    goToHome()


def playSpecialQuest15():
    for _ in range(10):
        click(Location(925, 30), waitTime=0.05)
        click(Location(480, 430))
    click(Location(925, 500), waitTime=0.1)
    click(Location(925, 500), waitTime=0.1)

    if not exists(r"src\image\pvp\pvp.png",timeout=0.2):
        goTo(r"src\image\go_to\pvp.png")

    click(r"src\image\pvp\friend battle full.png")
    waitLoading()
    wait(0.75)
    swipe(800, 370, 200, 370)
    wait(1)
    click(r"src\image\pvp\brown.png")
    click(r"src\image\pvp\next.png")
    waitLoading()
    captureScreen()
    existsClick(r"src\image\pvp\auto 1.png", similarity=0.9, timeout=0.3, capture=False)
    existsClick(r"src\image\pvp\x2 1.png", similarity=0.9, timeout=0.3, capture=False)
    existsClick(r"src\image\pvp\next.png", timeout=0.3, capture=False)
    waitLoading()
    existsClick(r"src\image\pvp\start.png")
    waitLoading()
    existsClick(r"src\image\pvp\ok.png")
    waitLoading()
    while True:
        captureScreen()
        click(Location(280, 435))
        click(Location(380, 435))
        click(Location(480, 435))
        click(Location(500, 370))
        click(Location(150, 450))
        existsClick(r"src\image\pvp\next.png", timeout=0.01, capture=False)
        existsClick(r"src\image\pvp\start.png", timeout=0.01, capture=False)
        existsClick(r"src\image\pvp\ok.png", timeout=0.01, capture=False)
        if exists(r"src\image\pvp\friend battle and battle.png", capture=False):
            break


def playSpecialQuest19():
    waitLoading()
    click(r"src\image\buy booster\buy 3 ruby.png")
    waitLoading()
    click(r"src\image\buy booster\buy 3 ruby ok.png")
    waitLoading()
    click(r"src\image\buy booster\ok.png")
    waitLoading()
    closePopUp()


def playSpecialQuest20():
    is_join = False
    while True:
        log("Tutorial guild")
        click(Location(480, 400))
        existsClick(r"src\image\guild\i agree 1.png")
        existsClick(r"src\image\guild\i agree 2.png")
        existsClick(r"src\image\guild\ok.png")
        if exists(r"src\image\guild\icon guild.png", similarity=0.9, timeout=0.01) and (exists(r"src\image\guild\find.png", timeout=0.01, capture=False) or exists(r"src\image\guild\find1.png", timeout=0.01, capture=False)):
            break

    waitLoading()
    if not exists(r"src\image\guild\refresh.png"):
        return

    while True:
        log("Find guild to join")
        existsClick(r"src\image\guild\ok.png")
        waitLoading()
        but_joins = findAll(r"src\image\guild\join.png", similarity=0.95)
        for join in but_joins:
            if regionExists(Region(480, join.y-5, 350, join.h+5), r"src\image\guild\lock.png"):
                log("lock")
                continue
            click(join)
            waitLoading()
            click(r"src\image\guild\join ok.png")
            waitLoading()
            if exists(r"src\image\guild\24_hour.png", timeout=0.1):
                log(f"can't join guild with 24 hour restriction")
                existsClick(r"src\image\guild\join ok.png")
                return "24_hour"
            elif not existsClick(r"src\image\guild\join ok.png"):
                is_join = True
                break
        if is_join:
            break
        click(r"src\image\guild\refresh.png")
        waitLoading()

    for _ in range(10):
        click(Location(480, 270), waitTime=0.5)
    goToHome()


def playSpecialQuest21():
    waitLoading()
    for _ in range(100):
        click(Location(900, 500)) # close popup
        if exists(r"src\image\guild\find1.png", timeout=0.1):
            break
    click(Location(692, 131), waitTime=0.5) # member
    waitLoading()
    swipe(589, 419, 589, 175, 400)
    swipe(589, 419, 589, 175, 400)
    wait(2)
    click(r"src\image\guild\support.png", similarity=0.95)
    waitLoading()
    click(r"src\image\guild\join ok.png")
    waitLoading()
    goToHome()


def playSpecialQuest25():
    waitLoading()
    for _ in range(10):
        click(Location(480, 270), waitTime=0.1)
    if not existsClick(r"src\image\guild\enter.png"):
        playSpecialQuest20()
        existsClick(r"src\image\quest\quest icon.png", similarity=0.7) # เควสพิเศษ
        waitLoading()
        click(r"src\image\quest\go.png")
        waitLoading()

    existsClick(r"src\image\guild\enter.png")
    waitLoading()
    for _ in range(5):
        click(Location(50, 270), waitTime=0.1)
    waitLoading()
    existsClick(r"src\image\guild\auto.png")
    existsClick(r"src\image\guild\x2.png")
    click(r"src\image\guild\attack.png")
    waitLoading()
    sleep(1)
    waitLoading()
    click(r"src\image\guild\stop.png", similarity=0.7)
    sleep(1)
    click(r"src\image\guild\exit.png")
    waitLoading()
    while True:
        if exists(r"src\image\guild\attack.png", timeout=0.1):
            break
        click(Location(480, 270)) # close popup
        existsClick(r"src\image\guild\congrat ok.png", timeout=0.1)
    goToHome()


def playSpecialQuest26():
    gear = exists(r"src\image\gear\gear.png", 0.1)
    while True:
        if gear == None:
            gear = exists(r"src\image\gear\gear.png")
        else:
            break

    if not exists(r"src\image\gear\grade low button.png", 0.1):
        if exists(r"src\image\gear\high.png", 0.1):
            click(r"src\image\gear\high.png")
        elif exists(r"src\image\gear\low.png", 0.1):
            click(r"src\image\gear\low.png")

        click(r"src\image\gear\grade low.png")

    click(r"src\image\gear\info.png")
    waitLoading()
    click(r"src\image\gear\enhance button.png")
    waitLoading()    
    click(r"src\image\gear\check box.png")
    click(r"src\image\gear\enhance button red.png")
    waitLoading()
    click(r"src\image\gear\ok.png")
    waitLoading()
    wait(3)
    while True:
        if not exists(r"src\image\gear\enhance congrat.png"):
            break
        click(Location(480, 500))

    waitLoading()
    goToHome()


def playSpecialQuest27():
    waitLoading()
    # playSpecialQuest29_pre()
    # waitLoading()
    click(r"src\image\expedition\expedition.png", similarity=0.7)
    waitLoading()
    while True:
        click(Location(90, 250)) # close tutorial
        click(Location(211, 232)) # close tutorial
        if existsClick(r"src\image\expedition\auto.png", similarity=0.95, timeout=0.01):
            existsClick(r"src\image\expedition\auto.png", similarity=0.95, timeout=0.01)
            break
    click(r"src\image\expedition\start.png")
    click(r"src\image\expedition\ok.png")
    waitLoading()
    waitLoading()
    click(r"src\image\expedition\room01.png")
    wait(r"src\image\expedition\completeNow.png")
    click(r"src\image\expedition\completeNow.png")
    click(r"src\image\expedition\ok.png")
    waitLoading()
    while True:
        click(Location(480, 470)) # close tutorial
        if exists(r"src\image\expedition\redeploy.png", similarity=0.95, timeout=0.01):
            break
    goToHome()


def playSpecialQuest27_old():
    waitLoading()
    playSpecialQuest29_pre()
    waitLoading()
    click(r"src\image\lab\training_center.png", similarity=0.7)
    waitLoading()
    for _ in range(10):
        click(Location(900, 100)) # close tutorial
    click(Location(173, 270), waitTime=0.5) # GO
    waitLoading()
    sleep(1)
    swipe(245, 390, 245, 210, 1000)
    swipe(360, 390, 360, 175, 1000)
    swipe(475, 390, 475, 210, 1000)
    swipe(595, 390, 595, 175, 1000)
    swipe(710, 390, 710, 210, 1000)
    click(Location(475, 500), waitTime=0.5) # traning
    waitLoading()
    click(Location(475, 500), waitTime=0.5) # noe complete
    click(Location(555, 405), waitTime=0.5) # ok
    waitLoading()
    waitLoading()
    for _ in range(10):
        click(Location(480, 260), waitTime=0.1)
    waitLoading()
    goToHome()


def playSpecialQuest29_pre(back=True):
    log(f"playSpecialQuest29_pre : Craft Hi STR Posion")
    waitLoading()
    click(r"src\image\lab\crystal_lab.png", similarity=0.7)
    waitLoading()
    for _ in range(20):
        click(Location(480, 460)) # close tutorial
    if exists(r"src\image\lab\how_to_play.png", similarity=0.7):
        pressBack()
    existsClick(r"src\image\lab\close.png", similarity=0.7)
    click(Location(350, 80), waitTime=0.5) # Material
    click(Location(371, 180), waitTime=0.5) # ✔
    swipe(485, 250, 350, 250, 500) # swip to right
    click(Location(555, 405), waitTime=0.5) # OK
    click(Location(650, 400), waitTime=0.5) # extract
    click(Location(555, 375), waitTime=0.5) # OK
    wait(4)
    waitLoading()
    click(Location(480, 466), waitTime=0.5) # ok
    click(Location(29, 29), waitTime=0.5) # back
    waitLoading()

    click(r"src\image\lab\material_lab.png", similarity=0.7)
    waitLoading()
    while True:
        click(Location(900, 270))
        if exists(r"src\image\lab\material_lab_slot.png", similarity=0.95, timeout=0.01) and colorMatch(getColor(Location(40, 20), capture=False), Color(255, 239, 66), 5):
            break
    if exists(r"src\image\lab\material_lab_void_slot.png", similarity=0.9, timeout=0.1):
        click(Location(321, 78), waitTime=0.5) # Regular
        click(Location(371, 180), waitTime=0.5) # Hi STR Posion
        click(Location(555, 405), waitTime=0.5) # Crafting
        click(Location(555, 365), waitTime=0.5) # OK
        waitLoading()
    if back:
        click(Location(29, 29), waitTime=0.5) # back
        waitLoading()


def playSpecialQuest29():
    waitLoading()
    click(r"src\image\lab\material_lab.png", similarity=0.7)
    waitLoading()
    while True:
        click(Location(900, 270))
        existsClick(r"src\image\lab\close.png", similarity=0.7)
        if exists(r"src\image\lab\material_lab_slot.png", similarity=0.95, timeout=0.01) and colorMatch(getColor(Location(40, 20), capture=False), Color(255, 239, 66), 5):
            break
    waitLoading()
    
    if existsClick(r"src\image\lab\material_done.png", similarity=0.75):
        sleep(2)
        waitLoading()
        click(r"src\image\lab\ok.png")
        waitLoading()
    else:
        click(Location(29, 29), waitTime=0.5) # back
        waitLoading()
        playSpecialQuest29_pre(back=False)
        click(Location(505, 150), waitTime=0.25) # open slot
        click(r"src\image\lab\complete_now.png")
        waitLoading()
        click(r"src\image\lab\2ruby.png")
        click(r"src\image\lab\ok1.png")
        waitLoading()
        click(r"src\image\lab\ok.png")
    goToHome()


def startBotClearSpecialQuest(deviceSerial):
    global CHANGEID
    fileGameId = "0123456789"  # เซ็ตค่าเริ่มต้น
    while fileGameId != "":
        CHANGEID = True
        print("========= Start =========", flush=True)
        print(">>> startBotClearSpecialQuest <<<", flush=True)
        # ลูนเล่นสเตจหลัก
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")
        while True:
            try:
                if CHANGEID:
                    force_stop_LINE_Rangers()
                    importFileFromInputToExecute()
                    CHANGEID = False

                open_line_ranger = openLineRangers(fast=False, dontShowToday=True)

                if open_line_ranger == "set nickname":
                    break   # << ออกจาก while stageNumber <= stageEnd
                
                clearSpecialQuest()

                if UPDATERBTK:
                    updateFileWithRBTK()

                force_stop_LINE_Rangers()

                break
            except TimeoutError as e:
                captureScreenError(str(e))
                log(f"Restart bot due to timeout: {e}")
                continue   # << วน while True ใหม่
            except Exception as e:
                captureScreenError(str(e))
                log(f"Unexpected error: {e}")
                traceback.print_exc()

        try:
            if not open_line_ranger == "set nickname":
                exportFileFromExecuteToOutput()
        except Exception as e:
            captureScreenError(str(e))
            log(f"In exportFile error: {e}")
            traceback.print_exc()


        fileGameId = in_current_file()
        if not fileGameId:
            # ถ้าไม่เจอไฟล์ไหนเลยที่ลงท้ายด้วย .xml
            fileGameId = ""   # ทำให้ while หลุด
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break
        print("========== End ==========", flush=True)
    
    force_stop_LINE_Rangers()
    print("========== End ==========", flush=True)


def randomGachaEvent():
    rangerNames = ""
    log(f"RandomGacha Event")
    goTo(r"src\image\go_to\gacha.png")
    tutorialGacha()
    waitLoading(timeOut=0.1)
    if existsClick(r"src\image\gacha\ok.png"):
        waitLoading()
    log(f"gachaSelctionEvent")
    for _ in range(5):
        swipe(748, 307, 748, 183, 1000)
        if existsClick(r"src\image\gacha\gacha event.png"):
            waitLoading()
            break

    if existsClick(r"src\image\gacha\10 time 10 ticket.png", timeout=0.1, capture=False):
        waitLoading(0.1)
        if existsClick(r"src\image\gacha\ok.png"):
            waitLoading()
            wait(2)
            if exists(r"src\image\gacha\10 time 10 ticket.png", timeout=0.1):
                log(f"No Gacha Ticket")
                return rangerNames


    while True:
        click(Location(900, 270))

        if exists(r"src\image\gacha\once more.png", timeout=0.1, similarity=0.7):
            waitLoading()
            break


        rangerNameOCR = getGachaRangerName()
        log(f"Ranger Name: {rangerNameOCR}")
        is_match, rangerName = matchGachaName(RANGERSCONFIG, rangerNameOCR)
        if is_match:
            rangerNames = add_ranger_name(rangerNames, rangerName)

    return rangerNames

def startBotClearStage150(deviceSerial):
    global STAGENUMBER, GIFTBOX, CHANGEID, AUTOTEAM
    fileGameId = "0123456789"  # เซ็ตค่าเริ่มต้น
    while fileGameId != "":
        print("========= startBotClearStage150 =========", flush=True)
        STAGENUMBER = 0
        # ลูนเล่นสเตจหลัก
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")
        while STAGENUMBER <= STAGEEND:
            try:
                if CHANGEID:
                    force_stop_LINE_Rangers()
                    importFileFromInputToExecute()
                    CHANGEID = False

                open_line_ranger = openLineRangers() # ออกเกม / เข้าเกม

                if open_line_ranger == "set nickname":
                    break   # << ออกจาก while stageNumber <= stageEnd

                if GIFTBOX:
                    acceptGiftBox()
                    GIFTBOX = False

                if AUTOTEAM:
                    autoChangeTeam(RANGERINTEAM, MAXMINERALCOST)
                    AUTOTEAM = False

                if STAGEEND != 0:
                    play = playMainStage() # เล่นด่าน
                    # play = playMainStage(31) # เล่นด่าน
                    # play = playMainStageUp31(end=STAGEEND)
                    getMissions()

                    if UPDATERBTK:
                        updateFileWithRBTK()

                    if play == "lost":
                        break   # << ออกจาก while stageNumber <= stageEnd
                else:
                    break
            except TimeoutError as e:
                captureScreenError(str(e))
                log(f"Restart bot due to timeout: {e}")
                continue   # << วน while True ใหม่
            except Exception as e:
                captureScreenError(str(e))
                log(f"Unexpected error: {e}")
                traceback.print_exc()

        try:
            if not open_line_ranger == "set nickname":
                exportFileFromExecuteToOutput()
        except Exception as e:
            captureScreenError(str(e))
            log(f"In exportFile error: {e}")
            traceback.print_exc()

        fileGameId = in_current_file()
        if not fileGameId:
            # ถ้าไม่เจอไฟล์ไหนเลยที่ลงท้ายด้วย .xml
            fileGameId = ""   # ทำให้ while หลุด
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break
        print("========== End ==========", flush=True)
    
    force_stop_LINE_Rangers()
    print("========== End ==========", flush=True)

def startBotClearStage150AndQuest(deviceSerial):
    global STAGENUMBER, GIFTBOX, CHANGEID, AUTOTEAM
    fileGameId = "0123456789"  # เซ็ตค่าเริ่มต้น
    while fileGameId != "":
        print("========= startBotClearStage150AndQuest =========", flush=True)
        STAGENUMBER = 0
        # ลูนเล่นสเตจหลัก
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")
        while STAGENUMBER <= STAGEEND:
            try:
                if CHANGEID:
                    force_stop_LINE_Rangers()
                    importFileFromInputToExecute()
                    CHANGEID = False

                open_line_ranger = openLineRangers() # ออกเกม / เข้าเกม

                if open_line_ranger == "set nickname":
                    break   # << ออกจาก while stageNumber <= stageEnd

                if GIFTBOX:
                    acceptGiftBox()
                    GIFTBOX = False

                if AUTOTEAM:
                    autoChangeTeam(RANGERINTEAM, MAXMINERALCOST)
                    AUTOTEAM = False

                if STAGEEND != 0:
                    play = playMainStage() # เล่นด่าน
                    # play = playMainStage(31) # เล่นด่าน
                    # play = playMainStageUp31(end=STAGEEND)
                    getMissions()

                    clearSpecialQuest()

                    if UPDATERBTK:
                        updateFileWithRBTK()

                    if play == "lost":
                        break   # << ออกจาก while stageNumber <= stageEnd
                else:
                    break
            except TimeoutError as e:
                captureScreenError(str(e))
                log(f"Restart bot due to timeout: {e}")
                continue   # << วน while True ใหม่
            except Exception as e:
                captureScreenError(str(e))
                log(f"Unexpected error: {e}")
                traceback.print_exc()

        try:
            if not open_line_ranger == "set nickname":
                exportFileFromExecuteToOutput()
        except Exception as e:
            captureScreenError(str(e))
            log(f"In exportFile error: {e}")
            traceback.print_exc()

        fileGameId = in_current_file()
        if not fileGameId:
            # ถ้าไม่เจอไฟล์ไหนเลยที่ลงท้ายด้วย .xml
            fileGameId = ""   # ทำให้ while หลุด
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break
        print("========== End ==========", flush=True)
    
    force_stop_LINE_Rangers()
    print("========== End ==========", flush=True)


def startBotClearStage150AndQuestAnd7Day(deviceSerial):
    global STAGENUMBER, GIFTBOX, CHANGEID, AUTOTEAM
    fileGameId = "0123456789"  # เซ็ตค่าเริ่มต้น
    while fileGameId != "":
        print("========= startBotClearStage150AndQuestAnd7Day =========", flush=True)
        STAGENUMBER = 0
        # ลูนเล่นสเตจหลัก
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")
        while STAGENUMBER <= STAGEEND:
            try:
                if CHANGEID:
                    force_stop_LINE_Rangers()
                    importFileFromInputToExecute()
                    CHANGEID = False

                open_line_ranger = openLineRangers() # ออกเกม / เข้าเกม

                if open_line_ranger == "set nickname":
                    break   # << ออกจาก while stageNumber <= stageEnd

                if GIFTBOX:
                    acceptGiftBox()
                    GIFTBOX = False

                if AUTOTEAM:
                    autoChangeTeam(RANGERINTEAM, MAXMINERALCOST)
                    AUTOTEAM = False

                if STAGEEND != 0:
                    play = playMainStage() # เล่นด่าน
                    # play = playMainStage(31) # เล่นด่าน
                    # play = playMainStageUp31(end=STAGEEND)
                    getMissions()

                    clearSpecialQuest()

                    clear7DayQuest()
                    acceptGiftBox()

                    if UPDATERBTK:
                        updateFileWithRBTK()

                    if play == "lost":
                        break   # << ออกจาก while stageNumber <= stageEnd
                else:
                    break
            except TimeoutError as e:
                captureScreenError(str(e))
                log(f"Restart bot due to timeout: {e}")
                continue   # << วน while True ใหม่
            except Exception as e:
                captureScreenError(str(e))
                log(f"Unexpected error: {e}")
                traceback.print_exc()

        try:
            if not open_line_ranger == "set nickname":
                exportFileFromExecuteToOutput()
        except Exception as e:
            captureScreenError(str(e))
            log(f"In exportFile error: {e}")
            traceback.print_exc()

        fileGameId = in_current_file()
        if not fileGameId:
            # ถ้าไม่เจอไฟล์ไหนเลยที่ลงท้ายด้วย .xml
            fileGameId = ""   # ทำให้ while หลุด
            print("========== End ==========", flush=True)
            log(f"Not Found File ID")
            break
        print("========== End ==========", flush=True)
    
    force_stop_LINE_Rangers()
    print("========== End ==========", flush=True)


def buyItemInSwapShop(leonard_9=False, ruby=False, ticket=False):
    log(f"Buy Item In Swap Shop")
    goToHome()
    if existsClick(r"src\image\shop\shop icon.png", similarity=0.75):
        waitLoading()
        wait(0.3)
        for _ in range(10):
            click(Location(950, 280), waitTime=0.02)
        if existsClick(r"src\image\shop\event.png",timeout=0.1, similarity=0.85):
            waitLoading()
        
        if leonard_9 and exists(r"src\image\shop\leonard9.png", similarity=0.9, timeout=0.1):
            existsClick(r"src\image\shop\leonard9.png", similarity=0.9)
            existsClick(r"src\image\shop\buy.png")
            if exists(r"src\image\shop\cancel.png", timeout=0.1):
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                log(f"Buy Leonard 9⭐")
            else:
                existsClick(r"src\image\shop\ok.png")
                existsClick(r"src\image\home\close.png", timeout=0.1)


        if ruby and exists(r"src\image\shop\ruby.png", similarity=0.9, timeout=0.1):
            existsClick(r"src\image\shop\ruby.png", similarity=0.9)
            existsClick(r"src\image\shop\buy.png")
            if exists(r"src\image\shop\cancel.png", timeout=0.1):
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                log(f"Buy Ruby 100💎")
            else:
                existsClick(r"src\image\shop\ok.png")
                existsClick(r"src\image\home\close.png", timeout=0.1)


        if ticket and exists(r"src\image\shop\gacha ticket.png", similarity=0.9, timeout=0.1):
            existsClick(r"src\image\shop\gacha ticket.png", similarity=0.9)
            existsClick(r"src\image\shop\buy.png")
            if exists(r"src\image\shop\cancel.png", timeout=0.1):
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                log(f"Buy Gacha Ticket 5🎫")
            else:
                existsClick(r"src\image\shop\ok.png")
                existsClick(r"src\image\home\close.png", timeout=0.1)


        if ticket and exists(r"src\image\shop\gacha ticket.png", similarity=0.9, timeout=0.1):
            existsClick(r"src\image\shop\gacha ticket.png", similarity=0.9)
            existsClick(r"src\image\shop\buy.png")
            if exists(r"src\image\shop\cancel.png", timeout=0.1):
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                existsClick(r"src\image\shop\ok.png")
                waitLoading()
                log(f"Buy Gacha Ticket 5🎫")
            else:
                existsClick(r"src\image\shop\ok.png")
                existsClick(r"src\image\home\close.png", timeout=0.1)

        goToHome()


def textRBTKOCR(region:Region, psm=7, imageProcessing=True):
    pytesseract.pytesseract.tesseract_cmd = r"src\Tesseract-OCR\tesseract.exe"

    # อ่านภาพภายใน region (BGR)
    img = readImage(1)[region.y:region.y+region.h, region.x:region.x+region.w]

    # Scale ขึ้น 4x ก่อน (ช่วยมากสำหรับตัวเลขเล็ก)
    img = cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    # -----------------------------
    # 1. แปลงภาพ + ทำ Threshold
    # -----------------------------
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if imageProcessing:
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    else:
        thresh = gray

    # -----------------------------
    # Debug (ดูผลการ crop)
    # -----------------------------
    # cv2.imshow("thresh", thresh)
    # cv2.waitKey()

    # -----------------------------
    # 4. OCR ด้วย Tesseract
    # -----------------------------
    config = (
        f"--psm {psm} "
        "-c tessedit_char_whitelist=0123456789, "
        "-c load_system_dawg=0 -c load_freq_dawg=0 "
    )

    text = pytesseract.image_to_string(thresh, lang="eng", config=config)
    text = text.replace("\n", " ").strip()
    # ลบข้อความที่อยู่ใน [] ออก เช่น "[SPY]Anya" -> "Anya"
    text = re.sub(r'\[.*?\]', '', text).strip()
    # ลบ , ออก เช่น "2,203" -> "2203"
    text = text.replace(",", "")
    if not text:
        return "0"
    return text

def updateFileWithRBTK(text=""):
    global FILENAME, RBTK, RBTKPOSITION

    read_RB_TK()

    if FILENAME == "":
        log("Unable to update file. FILENAME not found.")
        return

    gameId = FILENAME.replace(".xml", "")
    old_files = glob.glob(os.path.join("execute", f"*{gameId}*.xml"))

    for old_path in old_files:
        dirname, old_name = os.path.split(old_path)
        # ลบ RB_TK เดิมออกก่อน (ถ้ามี)
        clean_name = re.sub(r'RB\d+_TK\d+_?', '', old_name, flags=re.IGNORECASE)

        if text != "":
            new_name = f'{text}_{clean_name}'
        elif RBTKPOSITION == "front":
            # front: RB_TK_prefix_ID.xml
            new_name = f'{RBTK}{clean_name}'
        elif RBTKPOSITION == "middle":
            # middle: prefix_RB_TK_ID.xml
            # หา ID pattern (hex 8+ ตัว) แล้ววาง RBTK ไว้ข้างหน้า
            match = re.search(r'[0-9a-f]{8,}', clean_name, flags=re.IGNORECASE)
            if match:
                idx = match.start()
                # ลบ _ หรือ - ที่อยู่หน้า ID ออกก่อน แล้วใส่ RBTK แทน
                prefix = clean_name[:idx]
                suffix = clean_name[idx:]
                new_name = f'{prefix}{RBTK}{suffix}'
            else:
                new_name = f'{RBTK}{clean_name}'
        elif RBTKPOSITION == "back":
            # back: prefix_ID_RBTK.xml
            base, ext = os.path.splitext(clean_name)
            # ลบ _ ท้ายสุดถ้ามี
            base = base.rstrip('_')
            new_name = f'{base}_{RBTK.rstrip("_")}{ext}'
        else:
            new_name = f'{RBTK}{clean_name}'

        new_path = os.path.join(dirname, new_name)
        if old_path == new_path or old_name == new_name:
            continue
        if os.path.exists(new_path):
            os.remove(new_path)
        FILENAME = new_name
        os.rename(old_path, new_path)
        log(f"Update File: {new_path}")


def read_RB_TK():
    global RBTK, FILENAME
    rb = 0
    tk = 0
    closePopUp()
    waitLoading()
    tutorialInHomeScreen()
    while not exists(r"src\image\gacha\gacha.png", similarity=0.7, timeout=0.1):
        goTo(r"src\image\go_to\gacha.png")
        tutorialGacha()
    # rb = textRBTKOCR(Region(426,17,50,22), psm=13, imageProcessing=True)
    # tk = textRBTKOCR(Region(566,17,50,22), psm=13, imageProcessing=True)
    rb = numberOCR(Region(426,17,50,22), "src\image\gacha\RbTk\\", 0.85)
    tk = numberOCR(Region(566,17,50,22), "src\image\gacha\RbTk\\", 0.85)
    RBTK = f"RB{rb}_TK{tk}_"
    # FILENAME = RBTK + FILENAME
    log(f"RB={rb}, TK={tk}")
    return RBTK




def textGearsOCR(region:Region, psm=7, imageProcessing=True):
    pytesseract.pytesseract.tesseract_cmd = r"src\Tesseract-OCR\tesseract.exe"

    # อ่านภาพภายใน region (BGR)
    img = readImage(1)[region.y:region.y+region.h, region.x:region.x+region.w]

    # -----------------------------
    # 1. แปลงภาพ + ทำ Threshold
    # -----------------------------
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if imageProcessing:
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    else:
        thresh = gray

    # -----------------------------
    # Debug (ดูผลการ crop)
    # -----------------------------
    # cv2.imshow("thresh", thresh)
    # cv2.waitKey()

    # -----------------------------
    # 4. OCR ด้วย Tesseract
    # -----------------------------
    config = (
        f"--psm {psm} "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]'-. "
        "-c load_system_dawg=0 -c load_freq_dawg=0 "
    )

    text = pytesseract.image_to_string(thresh, lang="eng", config=config)
    text = text.replace("\n", " ").strip()
    # ลบข้อความที่อยู่ใน [] ออก เช่น "[SPY]Anya" -> "Anya"
    text = re.sub(r'\[.*?\]', '', text).strip()
    return text


def randomGachaGear(selction_event:int=1, stop_when_found:bool=True, gacha_mode:str="giveItAll", limit_ruby:int=200, use_200ruby=True):
    global current_use_ruby
    limit_ruby = (limit_ruby//40)*40
    GearNames = ""
    log(f"RandomGacha selction_event:{selction_event} stop_when_found:{stop_when_found} gacha_mode:{gacha_mode} limit_ruby:{limit_ruby}")

    while not exists(r"src\image\gacha\gacha.png", similarity=0.7, timeout=0.1):
        goTo(r"src\image\go_to\gacha.png")
        tutorialGacha()

    waitLoading(timeOut=0.1)
    if existsClick(r"src\image\gacha\ok.png"):
        waitLoading()
    log(f"gachaSelctionEvent: {selction_event}")
    if existsClick(r"src\image\gacha\gear.png"):
        waitLoading()
        wait(r"src\image\gacha\5+1_time_200_ruby.png")
        wait(0.5)
    gachaSelctionEvent(selction_event)

    if use_200ruby:
        while True:
            captureScreen()
            if (gacha_mode == "LimitOfRuby" and current_use_ruby >= limit_ruby):
                break
            existsClick(r"src\image\gacha\5+1_time_200_ruby.png", timeout=0.1, capture=False)
            existsClick(r"src\image\gacha\once more.png",timeout=0.1, capture=False)
            waitLoading()
            if exists(r"src\image\gacha\you neet more rubies.png", timeout=0.1):
                click(r"src\image\gacha\cancel.png")
                waitLoading()
                existsClick(r"src\image\gacha\ok.png")
                waitLoading()
                waitLoading()
                break
            if existsClick(r"src\image\gacha\ok.png"):
                waitLoading()
                wait(1)
            current_is_match = False
            for i in range(6):
                i += 1
                click(Location(900, 270))
                wait(1.5)
                captureScreen()
                gearNameOCR = textGearsOCR(Region(173,333,300,60), psm=6, imageProcessing=True)
                log(f"GearName{i}: {gearNameOCR}")
                is_match, gearName = matchGachaName(GEARS, gearNameOCR)
                if is_match:
                    GearNames = add_ranger_name(GearNames, gearName)
                    if stop_when_found:
                        current_is_match = True
            click(Location(900, 270))
            current_use_ruby += 200

            if current_is_match:
                existsClick(r"src\image\gacha\ok.png")
                break
        if (gacha_mode == "LimitOfRuby" and current_use_ruby < limit_ruby):
            while True:
                captureScreen()
                if (gacha_mode == "LimitOfRuby" and current_use_ruby >= limit_ruby):
                    break
                existsClick(r"src\image\gacha\1_time_40_ruby.png", timeout=0.1, capture=False)
                existsClick(r"src\image\gacha\once more.png",timeout=0.1, capture=False)
                waitLoading()
                if exists(r"src\image\gacha\you neet more rubies.png", timeout=0.1):
                    click(r"src\image\gacha\cancel.png")
                    waitLoading()
                    existsClick(r"src\image\gacha\ok.png")
                    waitLoading()
                    waitLoading()
                    break
                if existsClick(r"src\image\gacha\ok.png"):
                    waitLoading()
                    wait(1)

                click(Location(900, 270))
                wait(1.5)
                captureScreen()
                gearNameOCR = textGearsOCR(Region(173,333,300,60), psm=6, imageProcessing=True)
                log(f"GearName: {gearNameOCR}")
                is_match, gearName = matchGachaName(GEARS, gearNameOCR)
                if is_match:
                    GearNames = add_ranger_name(GearNames, gearName)
                    if stop_when_found:
                        existsClick(r"src\image\gacha\ok.png")
                        break
                current_use_ruby += 40
    else:
        while True:
            captureScreen()
            if (gacha_mode == "LimitOfRuby" and current_use_ruby >= limit_ruby):
                break
            existsClick(r"src\image\gacha\1_time_40_ruby.png", timeout=0.1, capture=False)
            existsClick(r"src\image\gacha\once more.png",timeout=0.1, capture=False)
            waitLoading()
            if exists(r"src\image\gacha\you neet more rubies.png", timeout=0.1):
                click(r"src\image\gacha\cancel.png")
                waitLoading()
                existsClick(r"src\image\gacha\ok.png")
                waitLoading()
                waitLoading()
                break
            if existsClick(r"src\image\gacha\ok.png"):
                waitLoading()
                wait(1)

            click(Location(900, 270))
            wait(1.5)
            captureScreen()
            gearNameOCR = textGearsOCR(Region(173,333,300,60), psm=6, imageProcessing=True)
            log(f"GearName: {gearNameOCR}")
            is_match, gearName = matchGachaName(GEARS, gearNameOCR)
            if is_match:
                GearNames = add_ranger_name(GearNames, gearName)
                if stop_when_found:
                    existsClick(r"src\image\gacha\ok.png")
                    break
            current_use_ruby += 40

    existsClick(r"src\image\gacha\ok.png")
    waitLoading()
    wait(1)
    return GearNames

def clear7DayQuest():
    log("Clear 7Day Quest")
    goToHome()
    try:
        if not exists(r"src\image\7day\7D.png", timeout=0.1):
            log("Not found 7Day icon")
            return
        level = int(numberOCR(Region(30, 45, 54, 29), r"src\image\home\level", similarity=0.85))
        log(f"Current Level: {level}")
        if level < 80:
            log(f"Level must be at least 80 to play Special Quest")
            return
    except:
        log(f"Can't Read Current Level")
        return
    
    click(r"src\image\7day\7D.png")
    waitLoading()
    accept7Day(close=False)
    Quest1d()
    Quest2d()
    Quest3d()
    Quest4d()
    closePopUp()
    

def Quest1d():
    if existsClick(r"src\image\7day\7D.png", timeout=0.01):
        waitLoading()
    existsClick(r"src\image\7day\1d.png", timeout=0.1, similarity=0.9)
    while True:
        if existsClick(r"src\image\7day\get.png", timeout=0.1):
            waitLoading()
            click(r"src\image\7day\ok.png")
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Achieve_Production_Rate_10.png", similarity=0.9):
            AchieveProductionRate(80)
            Quest1d()
        else:
            log("Completed Quest 1Day")
            return


def Quest2d():
    if existsClick(r"src\image\7day\7D.png", timeout=0.01):
        waitLoading()
    existsClick(r"src\image\7day\2d.png", timeout=0.1, similarity=0.9)
    while True:
        if existsClick(r"src\image\7day\get.png", timeout=0.1):
            waitLoading()
            click(r"src\image\7day\ok.png")
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Exp_Booster.png", similarity=0.9):
            closePopUp()
            click(r"src\image\7day\buy_Exp_Booster.png", similarity=0.75)
            waitLoading()
            click(r"src\image\7day\buy_Exp_Booster_3Ruby.png")
            waitLoading()
            click(r"src\image\7day\ok_3Ruby.png")
            waitLoading()
            closePopUp()
            Quest2d()
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Achieve_Production_Rate_30.png", similarity=0.9):
            AchieveProductionRate(80)
            Quest2d()
        else:
            log("Completed Quest 2Day")
            return


def Quest3d():
    if existsClick(r"src\image\7day\7D.png", timeout=0.01):
        waitLoading()
    existsClick(r"src\image\7day\3d.png", timeout=0.1, similarity=0.92)
    while True:
        if existsClick(r"src\image\7day\get.png", timeout=0.1):
            waitLoading()
            click(r"src\image\7day\ok.png")
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Achieve_Production_Rate_50.png", similarity=0.9):
            AchieveProductionRate(80)
            Quest3d()
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Low_Int_Potion.png", similarity=0.8):
            click(r"src\image\7day\go.png")
            waitLoading()
            Quest3dLowInt()
            Quest3d()
        else:
            log("Completed Quest 3Day")
            return

def Quest4d():
    if existsClick(r"src\image\7day\7D.png", timeout=0.01):
        waitLoading()
    existsClick(r"src\image\7day\4d.png", timeout=0.1, similarity=0.92)
    while True:
        if existsClick(r"src\image\7day\get.png", timeout=0.1):
            waitLoading()
            click(r"src\image\7day\ok.png")
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Clear_Special_Satge.png", similarity=0.9):
            click(r"src\image\7day\go.png")
            waitLoading()
            playSpecialQuest14()
            Quest4d()
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Equip_Gear.png", similarity=0.9):
            click(r"src\image\7day\go.png")
            waitLoading()
            playSpecialQuest9()
            Quest4d()
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Achieve_Level_140.png", similarity=0.9):
            click(r"src\image\7day\go.png")
            waitLoading()
            AchieveLevel140()
            Quest4d()
        elif regionExists(Region(122, 268, 540, 85), r"src\image\7day\Achieve_Production_Rate_80.png", similarity=0.9):
            AchieveProductionRate(80)
            Quest4d()
        else:
            log("Completed Quest 4Day")
            return


def AchieveLevel140():
    # skip tutorial
    if (colorMatch(getColor(Location(480, 10)), Color(74, 69, 57), 10)):
        if colorMatch(getColor(r"src\image\team\teamA.png", 0.65), Color(165, 89, 0), 10):
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)
        if colorMatch(getColor((680, 80)), Color(247, 223, 173), 10):
            click((680, 80), waitTime=0.5)
            click((680, 80), waitTime=0.5)
            click((930, 270), waitTime=0.5)
            click((930, 270), waitTime=0.5)

    if len(findAll(r"src\image\7day\cony_inTeam.png")) < 3:
        goTo(r"src\image\go_to\guild.png")

        if exists(r"src\image\guild\youHaveBeen.png"):
            return

        click(r"src\image\7day\swap_shop.png")
        waitLoading()
        for _ in range(5):
            click(Location(564, 108))
        click(r"src\image\7day\GEM.png")
        waitLoading()

        for _ in range(3):
            click(r"src\image\7day\free.png")
            waitLoading()
            click(r"src\image\7day\Buy.png")
            waitLoading()
            click(r"src\image\7day\ok.png")
            waitLoading()
            click(Location(480, 270))
            wait(2.5)
            click(find(r"src\image\7day\cony.png").getBottomCenter())
            click(r"src\image\7day\ok_60.png")
            waitLoading()
            click(r"src\image\7day\ok.png")
            waitLoading()
            click(r"src\image\7day\ok_60.png")
            waitLoading()

        goTo(r"src\image\go_to\my team.png")
        # skip tutorial
        if (colorMatch(getColor(Location(480, 10)), Color(74, 69, 57), 10)):
            if colorMatch(getColor(r"src\image\team\teamA.png", 0.65), Color(165, 89, 0), 10):
                click((930, 270), waitTime=0.5)
                click((930, 270), waitTime=0.5)
                click((930, 270), waitTime=0.5)
                click((930, 270), waitTime=0.5)
            if colorMatch(getColor((680, 80)), Color(247, 223, 173), 10):
                click((680, 80), waitTime=0.5)
                click((680, 80), waitTime=0.5)
                click((930, 270), waitTime=0.5)
                click((930, 270), waitTime=0.5)
    
    click(r"src\image\7day\cony_inTeam.png")
    waitLoading()
    click(r"src\image\team\level up button.png") # level up
    waitLoading()
    click(r"src\image\team\Same_Ranger.png") # sort by
    sleep(0.3)
    swipe(236, 400, 340, 240, 500) # swip ranger1
    swipe(450, 400, 400, 164, 500) # swip ranger2
    swipe(555, 400, 464, 240, 500) # swip ranger3
    swipe(500, 450, 400, 450, 500) # เลื่อน 1 ตัว
    wait(0.5)
    swipe(555, 400, 586, 240, 500) # swip ranger4
    click(r"src\image\team\level up button green.png") # level up
    waitLoading()
    click(r"src\image\team\ok.png") # ok
    waitLoading()
    existsClick(r"src\image\team\ok.png") # ok
    waitLoading()
    wait(2)
    click(Location(783, 230), waitTime=0.5) # level up
    click(Location(783, 230), waitTime=0.5) # level up
    waitLoading()
    goToHome()


def AchieveProductionRate(level=80):
    closePopUp()
    click(r"src\image\home\upgrade.png")
    waitLoading()
    click(Location(225, 400))
    click(Location(225, 400))
    while True:
        for _ in range(10):
            click(Location(537, 251), waitTime=0.05)
        captureScreen()
        if int(textRBTKOCR(Region(444,195,80,30), psm=13, imageProcessing=False)) >= level:
            break
    click(r"src\image\7day\ok.png")
    waitLoading()
    waitLoading()
    click(Location(537, 500))
    goToHome()


def Quest3dLowInt_pre(back=True):
    log(f"playSpecialQuest29_pre : Craft Hi STR Posion")
    waitLoading()
    click(r"src\image\lab\crystal_lab.png", similarity=0.7)
    waitLoading()
    for _ in range(20):
        click(Location(480, 460)) # close tutorial
    if exists(r"src\image\lab\how_to_play.png", similarity=0.7):
        pressBack()
    existsClick(r"src\image\lab\close.png", similarity=0.7)
    click(Location(350, 80), waitTime=0.5) # Material
    click(Location(371, 180), waitTime=0.5) # ✔
    swipe(485, 250, 350, 250, 500) # swip to right
    click(Location(555, 405), waitTime=0.5) # OK
    click(Location(650, 400), waitTime=0.5) # extract
    click(Location(555, 375), waitTime=0.5) # OK
    wait(4)
    waitLoading()
    click(Location(480, 466), waitTime=0.5) # ok
    click(Location(29, 29), waitTime=0.5) # back
    waitLoading()

    click(r"src\image\lab\material_lab.png", similarity=0.7)
    waitLoading()
    while True:
        click(Location(900, 270))
        if exists(r"src\image\lab\material_lab_slot.png", similarity=0.95, timeout=0.01) and colorMatch(getColor(Location(40, 20), capture=False), Color(255, 239, 66), 5):
            break
    if exists(r"src\image\lab\material_lab_void_slot.png", similarity=0.9, timeout=0.1):
        click(Location(321, 78), waitTime=0.5) # Regular
        click(Location(384, 129), waitTime=0.5) # Grade
        click(Location(371, 331), waitTime=0.5) # Low Int Posion
        click(Location(555, 405), waitTime=0.5) # Crafting
        click(Location(555, 365), waitTime=0.5) # OK
        waitLoading()
    if back:
        click(Location(29, 29), waitTime=0.5) # back
        waitLoading()


def Quest3dLowInt():
    waitLoading()
    click(r"src\image\lab\material_lab.png", similarity=0.7)
    waitLoading()
    while True:
        click(Location(900, 270))
        existsClick(r"src\image\lab\close.png", similarity=0.7)
        if exists(r"src\image\lab\material_lab_slot.png", similarity=0.95, timeout=0.01) and colorMatch(getColor(Location(40, 20), capture=False), Color(255, 239, 66), 5):
            break
    waitLoading()
    
    if existsClick(r"src\image\lab\material_done.png", similarity=0.75):
        sleep(2)
        waitLoading()
        click(r"src\image\lab\ok.png")
        waitLoading()
    else:
        click(Location(29, 29), waitTime=0.5) # back
        waitLoading()
        Quest3dLowInt_pre(back=False)
        click(Location(505, 150), waitTime=0.25) # open slot
        click(r"src\image\lab\complete_now.png")
        waitLoading()
        click(r"src\image\lab\2ruby.png")
        click(r"src\image\lab\ok1.png")
        waitLoading()
        click(r"src\image\lab\ok.png")
    goToHome()


def playstage30_100_150():
    missionSlots = [Region(300, 125, 550, 94), Region(300, 243, 550, 94), Region(300, 361, 550, 94)]
    missionClearMainStage = None

    for _ in range(3):
        waitLoading()
        getMissions(goHome=False)
        existsClick(r"src\image\mission\special mission.png", timeout=0.01)

        missionClearMainStage = None
        captureScreen()
        for mission in missionSlots:
            if regionExists(mission, r"src\image\mission\clearMainStage.png"):
                missionClearMainStage = mission
                log(f"Found Mission Clear Main Stage {missionClearMainStage}")
                break

        if missionClearMainStage:
            captureScreen()
            s150 = regionExists(missionClearMainStage, r"src\image\main_stage\mission_stage_150.png", similarity=0.96, timeout=0.01, capture=False)
            s100 = regionExists(missionClearMainStage, r"src\image\main_stage\mission_stage_100.png", similarity=0.96, timeout=0.01, capture=False)
            s30 = regionExists(missionClearMainStage, r"src\image\main_stage\mission_stage_30.png", similarity=0.96, timeout=0.01, capture=False)
            
            click(regionExists(missionClearMainStage, r"src\image\mission\GO.png", timeout=0.01, capture=False))
            waitLoading()
            print("=========================")
            if s30:
                log(f"Current Mission Stage 30")
                if not existsClick(r"src\image\main_stage\30.png"):
                    return
            elif s100:
                log(f"Current Mission Stage 100")
                if not existsClick(r"src\image\main_stage\100.png"):
                    return
            elif s150:
                log(f"Current Mission Stage 150")
                if existsClick(r"src\image\main_stage\150.png", timeout=0.01):
                    pass
                else:
                    findStageAtNumber(150)
                    if not existsClick(r"src\image\main_stage\150.png"):
                        return

            waitLoading()
            playMissionMainStage()
        else:
            break
    getMissions(goHome=False)


def playMissionMainStage():
    global cooldowncapturescreen
    quest7day = 0

    rangerCycle = 0
    timeNow = time.time()  # เวลาปัจจุบัน
    currentLostCount = 0

    foundSkip = False
    levelNumber = 1
    win = False
    try:
        if exists(r"src\image\main_stage\tutorial leonard loop.png", timeout=0.1):
            tutorialClickLoop(backButton=False)

        existsClick(r"src\image\main_stage\auto.png", timeout=0.01)
        existsClick(r"src\image\main_stage\x2.png", timeout=0.01, capture=False)

        if existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01):
            existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)
            existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)
            existsClick(r"src\image\main_stage\item checkbox.png", timeout=0.01)

        startButton = exists(r"src\image\main_stage\start.png")
        nextButton = None
        if startButton:
            click(startButton)
        nextButton = exists(r"src\image\main_stage\next.png")
        if nextButton:
            click(nextButton)
            waitLoading()
            buyFriend()

        existsClick(r"src\image\main_stage\start.png")

        _cooldowncapturescreen = cooldowncapturescreen
        cooldowncapturescreen = 0.001
        if not waitLoading(timeOut=0.01, cooldowncaptures=0.001):  # << ถ้าโหลดเกิน 2 นาที
            raise TimeoutError("Loading stuck > 180 sec")
        cooldowncapturescreen = _cooldowncapturescreen
        
        log(f"PLaying", end="")
        timer = time.time()
        startPlayTime = datetime.now()
        while True:
            rangerCycle += 1

            click((275, 515), waitTime=0.01, duration=0.05) # ranger 1
            click((375, 515), waitTime=0.01, duration=0.05) # ranger 2
            click((475, 515), waitTime=0.01, duration=0.05) # ranger 3
            click((575, 515), waitTime=0.01, duration=0.05) # ranger 4
            click((675, 515), waitTime=0.01, duration=0.05) # ranger 5

            captureScreen()
            if regionExists(Region(149, 33, 73, 31), r"src\image\main_stage\win.png", 0.8, timeout=0.02, capture=False):
                win = True
                currentLostCount = 0
                stopPLayerTime = datetime.now()
                playTime = stopPLayerTime - startPlayTime
                minutes, seconds = divmod(playTime.seconds, 60)
                print()
                log(f"Win {minutes:02d}:{seconds:02d}")
                break
            if regionExists(Region(480, 327, 199, 74), r"src\image\main_stage\lose cancel.png", timeout=0.02, capture=False):
                win = False
                currentLostCount += 1
                stopPLayerTime = datetime.now()
                playTime = stopPLayerTime - startPlayTime
                minutes, seconds = divmod(playTime.seconds, 60)
                print()
                log(f"Lose {minutes:02d}:{seconds:02d}")
                break

            timeNow = time.time()  # เวลาปัจจุบัน
            click(slotItem1, duration=0.05)
            click(slotItem2, duration=0.05)
            click(slotItem3, duration=0.05)
            click(slotItem4, duration=0.05)
            click(slotItem5, duration=0.05)

            waitLoading(timeOut=0.1)

            if rangerCycle % 2 == 0:
                print(".",end="", flush=True)
        
            if timeNow - timer > 180:  # << ถ้าเล่นเกิน 3 นาที
                raise TimeoutError("PLaying stuck > 180 sec")

        # waitLoading
        if exists(r"src\image\home\UnKnown error.png", timeout=0.02):
            existsClick(r"src\image\main_stage\skip ok.png", timeout=0.02)
        existsClick(r"src\image\home\retry.png", timeout=0.02)

        levelUp = True
        while True:
            waitLoading()
            captureScreen()
            if exists(r"src\image\main_stage\main stage.png", 0.7, timeout=0.1, capture=False):
                waitLoading()
                log(f"Break: Found main stage")
                break

            if exists(r"src\image\tutorial\skip.png", 0.7, timeout=0.1, capture=False):
                waitLoading()
                log(f"Break: Found skip tutorial")
                if exists(r"src\image\main_stage\tutorial james.png", timeout=0.1):
                    foundSkip = True
                break

            if exists(r"src\image\main_stage\lose cancel.png", timeout=0.1, capture=False) and exists(r"src\image\main_stage\resume for free.png", timeout=0.25, capture=False):
                log(f"Break: Found lose")
                break

            if exists(r"src\image\main_stage\tutorial leonard retry ok next.png", 0.7, timeout=0.1, capture=False):
                if STAGENUMBER == 31 :
                    log(f"Break: Found tutorial retry ok next")
                    break
                if colorMatch(getColor(Location(324, 440)), Color(140, 44, 231)):
                    existsClick(r"src\image\main_stage\clear bonus retry.png", timeout=0.1)
                if colorMatch(getColor(Location(630, 440)), Color(8, 190, 206)):
                    existsClick(r"src\image\main_stage\clear bonus next.png", timeout=0.1)  

            if exists(r"src\image\main_stage\level17.png", 0.6, 0.25, capture=False) and levelUp:
                levelUp = False
                r = find(r"src\image\main_stage\level17.png", 0.6)
                levelNumber = int(numberOCR(r, r"src\image\main_stage\level"))
                log(f"LevelUp: {levelNumber}")
                if levelNumber in [17, 18, 20, 40]:
                    for _ in range(7):
                        captureScreen()
                        if exists(r"src\image\home\skip.png", timeout=0.1, capture=False):
                            skip()
                        existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7, capture=False)
                        if exists(r"src\image\home\close.png", timeout=0.1, capture=False)  or exists(r"src\image\home\back.png", timeout=0.1, capture=False):
                            break
                        if (nextButton):
                            click(nextButton, waitTime=0.1)
                        elif (startButton):
                            click(startButton, waitTime=0.1)
                    waitLoading()
                    log(f"Break: Found level: {levelNumber} to tutorial")
                    break
            
            if (nextButton):
                click(nextButton)
            elif (startButton):
                click(startButton)

            existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7)
            closePopUp(showLog=False)

        if exists(r"src\image\main_stage\lose cancel.png", timeout=0.5):
            if currentLostCount >= LOSTCOUNT:
                print("========= Lost ==========")
                log(f"CurrentLostCount:{currentLostCount} = LostCount:{LOSTCOUNT}")
                return "lost"
            else:
                upgradeCrystal()

        if levelNumber in [17, 18]:
            tutorialLevel17()

        if levelNumber == 40:
            goToHome()
            # tutorialTrain()

        if (foundSkip or STAGENUMBER == 2) and win:
            tutorial2()

        if STAGENUMBER == 5 and win:
            tutorial5()

        if STAGENUMBER == 10 and win:
            if exists(r"src\image\home\choose a new ranger.png", timeout=0.001):
                tutorial10()

        if STAGENUMBER == 12 and win:
            tutorial12()

        if STAGENUMBER == 15 and win:
            tutorial15()

        if STAGENUMBER == 29 and win:
            tutorial29()

        if STAGENUMBER == 31 and win:
            retryNextOk()

        if 3 < STAGENUMBER <= 12 and win:
            if quest7day <= 1:
                # waitLoading()
                # click((30, 25), waitTime=0.1) # ปุ่มย้อนกลับ
                # waitLoading()
                # tutorial7DayAndQuest()
                goToHome()
                click((480, 165), waitTime=0.5) # main stage
                waitLoading()
                quest7day += 1

        if levelNumber == 20:
            goToHome()
            # tutorialLevel20()

        waitLoading()
        updateFileInExecute()
        log(f"End Main Stage At Stage:{STAGENUMBER}")
        print("=========================")
        return "end"
    except Exception as e:
        print("========= Error =========")
        updateFileInExecute()
        log(f"Exception in play main stage:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")


def playMainStageUp31(end=150, exportID=True):
    global STAGENUMBER, cooldowncapturescreen
    try:
        print("=========================", flush=True)
        log(f"Start Main Stage: End={end}")
        STAGENUMBER = 0
        quest7day = 0

        timeNow = time.time()  # เวลาปัจจุบัน
        currentLostCount = 0
        win = True

        while True:
            waitLoading()
            stage30 = exists(r"src\image\main_stage\stage30.png", similarity=0.8, timeout=0.1)
            iconProfile = exists(r"src\image\main_stage\profile.png", similarity=0.8, timeout=0.1)
            if stage30:
                click(stage30.getBottomRight())
                click(stage30.getBottomRight().offset(5, 5))
                click(stage30.getBottomRight().offset(10, 10))
                break
            elif iconProfile:
                click(iconProfile.getBottomRight())
                click(iconProfile.getBottomRight().offset(5, 5))
                click(iconProfile.getBottomRight().offset(10, 10))
                break
            else:
                goTo(r"src\image\go_to\main stage.png")
                wait(1)
                if not exists(r"src\image\main_stage\profile.png", similarity=0.8):
                    while True:
                        if exists(r"src\image\main_stage\profile.png", similarity=0.8, timeout=0.1):
                            break
                        findProfile()

        waitLoading()
        if existsClick(r"src\image\main_stage\ANewAuto.png", timeout=0.01):
            for _ in range(10):
                click(Location(480+random.randint(-400, 400), 90+random.randint(-10, 10)))

        existsClick(r"src\image\main_stage\auto.png", similarity=0.8, timeout=0.1)
        existsClick(r"src\image\main_stage\x2.png", similarity=0.8, timeout=0.1)

        while STAGENUMBER <= end:
            startTine = time.time()
            while True:
                if exists(r"src\image\main_stage\stage.png", timeout=0.01, capture=True):
                    log("found stage.png")
                    break
                elif time.time() - startTine > 10:
                    log("Cust screen > 10 sec")
                    raise Exception(f"Cust screen > 10 sec")
                waitLoading()
                log(click(Location(480+random.randint(-400, 400), 90+random.randint(-10, 10))))

            if exists(r"src\image\main_stage\tutorial leonard loop.png", timeout=0.1):
                tutorialClickLoop(backButton=False)

            # wait(r"src\image\main_stage\stage.png")
            try:
                STAGENUMBER = int(numberOCR(Region(x=160, y=8, w=80, h=41), r"src\image\main_stage\numS", 0.85))
            except:
                pass
            
            print("=========================", flush=True)
            log(f"Stage: {STAGENUMBER}")
            if exportID:
                # เซฟ ID ก่อนเล่นด่าน
                updateFileWithStage()
            if STAGENUMBER > end:
                goTo(r"src\image\go_to\main stage.png")
                break


            startButton = exists(r"src\image\main_stage\start.png")
            nextButton = None
            if startButton:
                click(startButton)
            else:
                nextButton = exists(r"src\image\main_stage\next.png")
                if nextButton:
                    click(nextButton)

                if STAGENUMBER == 30:
                    waitLoading(timeOut=0.1)
                    skip()
                    for _ in range(10):
                        click((345, 380), waitTime=0.2) # เลือกเพื่อน

            if not waitLoading(timeOut=0.1):  # << ถ้าโหลดเกิน 1.5 นาที
                raise TimeoutError("Loading stuck > 90 sec")
            
            if STAGENUMBER > 30:
                if BUYFRIEND == "everyTime":
                    buyFriend()
                elif BUYFRIEND == "justLost" and not win:
                    buyFriend()

            existsClick(r"src\image\main_stage\start.png")

            _cooldowncapturescreen = cooldowncapturescreen
            cooldowncapturescreen = 0.001
            if not waitLoading(timeOut=0.01, cooldowncaptures=0.001):  # << ถ้าโหลดเกิน 2 นาที
                raise TimeoutError("Loading stuck > 180 sec")
            cooldowncapturescreen = _cooldowncapturescreen

            log(f"PLaying", end="")
            timer = time.time()
            startPlayTime = datetime.now()
            rangerCycle = 0
            while True:
                rangerCycle += 1

                click((275, 515), waitTime=0.01, duration=0.05) # ranger 1
                click((375, 515), waitTime=0.01, duration=0.05) # ranger 2
                click((475, 515), waitTime=0.01, duration=0.05) # ranger 3
                click((575, 515), waitTime=0.01, duration=0.05) # ranger 4
                click((675, 515), waitTime=0.01, duration=0.05) # ranger 5

                captureScreen()
                if regionExists(Region(149, 33, 73, 31), r"src\image\main_stage\win.png", 0.8, timeout=0.02, capture=False):
                    win = True
                    currentLostCount = 0
                    stopPLayerTime = datetime.now()
                    playTime = stopPLayerTime - startPlayTime
                    minutes, seconds = divmod(playTime.seconds, 60)
                    print()
                    log(f"Win {minutes:02d}:{seconds:02d}")
                    break
                if regionExists(Region(480, 327, 199, 74), r"src\image\main_stage\lose cancel.png", timeout=0.02, capture=False):
                    win = False
                    currentLostCount += 1
                    stopPLayerTime = datetime.now()
                    playTime = stopPLayerTime - startPlayTime
                    minutes, seconds = divmod(playTime.seconds, 60)
                    print()
                    log(f"Lose {minutes:02d}:{seconds:02d}")
                    break

                timeNow = time.time()  # เวลาปัจจุบัน
                if STAGENUMBER == 30:
                    click((345, 380), waitTime=0.001, duration=0.05) # เลือกเพื่อน
                    click(slotItem1, waitTime=0.15, duration=0.05) # เพื่อน
                    click(slotItem1, waitTime=0.15, duration=0.05) # เพื่อน

                click(slotItem1, duration=0.05)
                click(slotItem2, duration=0.05)
                click(slotItem3, duration=0.05)
                click(slotItem4, duration=0.05)
                click(slotItem5, duration=0.05)

                if rangerCycle % 5 == 0:
                    click((150, 510), waitTime=0.05) # missile
                    click((775, 510), waitTime=0.05) # costs
                
                if datetime.now().second % 2 == 0:
                    print(".",end="", flush=True)
                
                waitLoading()
                
                if timeNow - timer > 300:  # << ถ้าเล่นเกิน 5 นาที
                    raise TimeoutError("PLaying stuck > 300 sec")

            # waitLoading
            if exists(r"src\image\home\UnKnown error.png", timeout=0.02):
                existsClick(r"src\image\main_stage\skip ok.png", timeout=0.02)
            existsClick(r"src\image\home\retry.png", timeout=0.02)


            levelUp = True
            timer = time.time()
            while True:
                if time.time() - timer > 30:  # << ถ้าเล่นเกิน 30 วิ
                    raise TimeoutError("PLaying stuck > 30 sec")
                waitLoading()
                captureScreen()
                if exists(r"src\image\main_stage\main stage.png", 0.7, timeout=0.1, capture=False):
                    waitLoading()
                    log(f"Break: Found main stage")
                    break

                if exists(r"src\image\tutorial\skip.png", 0.7, timeout=0.1, capture=False):
                    waitLoading()
                    log(f"Break: Found skip tutorial")
                    if exists(r"src\image\main_stage\tutorial james.png", timeout=0.1):
                        foundSkip = True
                    break

                if exists(r"src\image\main_stage\lose cancel.png", timeout=0.1, capture=False) and exists(r"src\image\main_stage\resume for free.png", timeout=0.25, capture=False):
                    log(f"Break: Found lose")
                    break

                if exists(r"src\image\main_stage\tutorial leonard retry ok next.png", 0.7, timeout=0.1, capture=False):
                    if STAGENUMBER == 31 :
                        log(f"Break: Found tutorial retry ok next")
                        break
                    if colorMatch(getColor(Location(324, 440)), Color(140, 44, 231)):
                        existsClick(r"src\image\main_stage\clear bonus retry.png", timeout=0.1)
                    if colorMatch(getColor(Location(630, 440)), Color(8, 190, 206)):
                        existsClick(r"src\image\main_stage\clear bonus next.png", timeout=0.1)  

                if exists(r"src\image\main_stage\level17.png", 0.6, 0.25, capture=False) and levelUp:
                    levelUp = False
                    r = find(r"src\image\main_stage\level17.png", 0.6)
                    levelNumber = int(numberOCR(r, r"src\image\main_stage\level"))
                    log(f"LevelUp: {levelNumber}")
                    if levelNumber in [17, 18, 20, 40]:
                        for _ in range(7):
                            captureScreen()
                            if exists(r"src\image\home\skip.png", timeout=0.1, capture=False):
                                skip()
                            existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7, capture=False)
                            if exists(r"src\image\home\close.png", timeout=0.1, capture=False)  or exists(r"src\image\home\back.png", timeout=0.1, capture=False):
                                break
                            if (nextButton):
                                click(nextButton, waitTime=0.1)
                            elif (startButton):
                                click(startButton, waitTime=0.1)
                        waitLoading()
                        log(f"Break: Found level: {levelNumber} to tutorial")
                        break
                
                if (nextButton):
                    click(nextButton)
                elif (startButton):
                    click(startButton)

                existsClick(r"src\image\main_stage\puzzle ok.png", timeout=0.1, similarity=0.7)

            if exists(r"src\image\main_stage\lose cancel.png", timeout=0.5):
                if currentLostCount >= LOSTCOUNT:
                    print("========= Lost ==========")
                    log(f"CurrentLostCount:{currentLostCount} = LostCount:{LOSTCOUNT}")
                    return "lost"
                else:
                    upgradeCrystal()

            if STAGENUMBER > end:
                print("========== End ==========")
                return "end"
        print("=========================")
        if exportID:
            updateFileWithStage()
        log(f"End Main Stage At Stage:{STAGENUMBER}")
        return "end"
    except Exception as e:
        print("========= Error =========")
        updateFileWithStage()
        log(f"Exception in play main stage:\n{e}")
        captureScreenError(str(e))
        exc = traceback.print_exc()
        log(f"traceback:{exc}")


######################################################### game api #########################################################
######################################################### game api #########################################################
######################################################### game api #########################################################

# เครื่องมือ API อยู่ที่ ../tools (rangers_api / rewards / gacha / device_session)
# ยิงตรงไปที่ rangers-api.line-apps.com ด้วย LF_AC ที่อ่านจาก shared_prefs บนเครื่อง
# ไม่ต้องใช้ proxy และไม่ต้องเปิดเกมค้างไว้ ดู tools/device_session.py สำหรับที่มาของอัลกอริทึม
TOOLSDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")

# {unitCode: {"grade": ..., "summonEnergy": ...}} - ข้อมูลกลางของเกม ไม่ใช่ของบัญชีใคร
# ตัวเดียวกันคนละบัญชีค่าเท่ากันเสมอ จึงไม่ต้องล้างตอนสลับ ID (ต่างจาก LFACCACHE)
# เก็บลงไฟล์ด้วยเพราะการอ่านสเปกต้องเอาตัวไปวางในทีมทีละ 5 (ดู apiUnitSpecs) บัญชี 227 ตัว
# ใช้เวลาเกือบ 2 นาที ถ้าไม่เก็บไว้ข้ามโปรเซส ทุกครั้งที่เปิดบอทใหม่จะต้องไล่วางใหม่หมด
UNITSPECCACHE = {}
UNITSPECPATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "roster", "unit_specs.json")


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


def getLFAC(timeout=60):
    """คืน cookie 'LF_AC=...' สดจากเครื่อง รอจนกว่าเกมจะเขียน token ลง shared_prefs

    ลำดับการเขียนไม่ได้เกิดพร้อมกัน: _DEVICE_UUID_KEY กับ _LF_UT_KEY โผล่ตั้งแต่
    guest login ผ่าน แต่ _ENC_LF_AC_KEY โผล่ทีหลังตอน "ล๊อกอินเข้าเกม" สำเร็จแล้ว
    เท่านั้น ถ้าอ่านตอนยังอยู่หน้า terms/บทสอน จะเจอไฟล์ที่มี uuid แต่ไม่มี LF_AC
    จึงต้องรอ ไม่ใช่พังทันที

    อ่านผ่าน DEVICE.shell ของบอทเอง ไม่ใช้ device_session.get_lfac_from_device()
    เพราะ setUp() เก็บ DEVICESERIAL เป็น '127.0.0.1_16480' (แปลง ':' เป็น '_' ไว้
    ตั้งชื่อไฟล์) พอส่งให้ adb -s มันหาอุปกรณ์ไม่เจอ แล้วรายงานผิดเป็น "ไม่ได้ล๊อกอิน"

    LF_AC หมุนใหม่ทุกครั้งที่เปิดเกม จึง cache ได้แค่ภายใน session เดียว
    force_stop_LINE_Rangers() เป็นตัวล้าง cache และทุกทางที่เปิดเกมใหม่ต้องผ่านมัน
    (openLineRangers() เรียก force_stop ก่อนเสมอ) จึงไม่มีทางได้ token เก่ามาใช้

    flow ที่ import ไฟล์เข้ามา (startBotLogin_API) prefs ไม่ได้ว่างเปล่าแบบ flow genid
    ที่ removeAllFiles() ล้างไว้ก่อน แต่มี _ENC_LF_AC_KEY ของ session ตอน export ติดมา
    ครบตั้งแต่วินาทีแรก ถ้าเชื่อแค่ "มีค่าแล้ว = ล๊อกอินเสร็จ" จะคว้า token ตายไปยิง API
    ทันที (401) จึงต้องเทียบกับ IMPORTEDENCLFAC แล้วรอจนกว่าเกมจะเขียนค่าใหม่ทับ
    """
    global LFACCACHE
    if LFACCACHE:
        return LFACCACHE

    device_session, _rewards, _gacha = _importApiTools()
    startTime = time.time()
    while True:
        waited = time.time() - startTime
        
        xml = DEVICE.shell(f"su -c 'cat {LGRGSPREF}'") or ""
        deviceUuid = _prefValue(xml, "_DEVICE_UUID_KEY")
        encLFAC = _prefValue(xml, "_ENC_LF_AC_KEY")
        # ค่าเดิมเป๊ะ ๆ กับไฟล์ที่ import = เกมยังไม่ได้เขียนอะไรทับ ยังไม่ใช่ token สด
        # (ทุกครั้งที่เกมเขียนจะสุ่ม IV ใหม่ ค่า base64 จึงไม่มีทางซ้ำเดิม)
        isStale = encLFAC is not None and encLFAC == IMPORTEDENCLFAC
        if deviceUuid and encLFAC and not isStale:
            LFACCACHE = "LF_AC=" + device_session.decrypt_lfac(deviceUuid, encLFAC)
            return LFACCACHE
        else:
            log(f"Waiting LF_AC {'(stale from imported file)' if isStale else ''}... {int(waited)}s")
            force_stop_LINE_Rangers()
            openLineRangers(skipLoadingScreen=True)

        if waited >= timeout:
            if isStale:
                raise Exception(
                    f"LF_AC in shared_prefs after {int(waited)}s is still the one from "
                    f"the imported file (stale) - เกมยังไม่ได้ล๊อกอินใหม่ ห้ามเอา token "
                    f"นี้ไปยิง API เพราะเซิร์ฟเวอร์จะตอบ 401")
            raise Exception(
                f"no LF_AC in shared_prefs after {int(waited)}s "
                f"(_DEVICE_UUID_KEY={'มี' if deviceUuid else 'ไม่มี'}) - "
                f"เกมยังล๊อกอินเข้าเกมไม่สำเร็จ ต้องให้ถึงหน้าโฮมก่อน")
        sleep(3)


def apiGetPlayer():
    """ข้อมูลผู้เล่นจาก API (rsn, level, ...) ใช้เช็คว่า token ยังใช้ได้ด้วย"""
    _device_session, rewards, _gacha = _importApiTools()
    return _apiCall(rewards.check_session, getLFAC())


def currentLevel():
    """เลเวลปัจจุบันจาก API คืน 0 เมื่ออ่านไม่ได้

    ห้าม raise เด็ดขาด เพราะถูกเรียกใน f-string ตอนตั้งชื่อไฟล์ที่ export
    ถ้าโยน exception ออกไปจะไม่ได้ไฟล์เลยทั้งที่ ID สร้างเสร็จแล้ว
    Lv0 แปลว่าอ่านเลเวลไม่ได้ ยังดีกว่าเสีย ID ทิ้ง
    """
    try:
        return int(apiGetPlayer().get("level") or 0)
    except Exception as e:
        log(f"currentLevel failed: {e}")
        return 0


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


def _gachaGroupPull(cookie, groupId):
    """คืน (rubyPrice, ticketPrice, gachaName) ของตัวเลือกสุ่มเดี่ยว (gachaIndex=1) ของตู้ groupId

    อ่านจาก /gacha/info (ตัวเดียวกับ getGachaBanner) ตู้ CLASSIC ตั้งราคา index 1 เป็นรูบี้อย่าง
    เดียว ticketPrice จะเป็น 0 ไม่เจอตู้/ตัวเลือกคืน (0, 0, None)
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    status, info = _apiCall(rangers_api.call, cookie, "/gacha/info")
    if status != 200 or not isinstance(info, dict):
        return 0, 0, None
    for group in (info.get("result") or {}).get("gachaGroupResponseList") or []:
        gg = group.get("gachaGroup") or {}
        if gg.get("groupId") == groupId:
            for opt in gg.get("gachaGroupInfos") or []:
                if opt.get("gachaIndex") == 1:
                    return (opt.get("displayRubyPrice") or 0,
                            opt.get("displayTicketPrice") or 0, gg.get("gachaName"))
    return 0, 0, None


def apiGachaWithTicket(gacharangergroup=None, stop_when_found=True,
                       gacha_mode="NumberOfCycles", gacha_cycles=5, use_ruby=False):
    """สุ่มกาชาหาเรนเจอร์ผ่าน API (เวอร์ชัน API ของ randomGachaRanger ที่เดิมลาก UI + OCR)

    วนสุ่มทีละครั้งจนเข้าเงื่อนไขหยุด คืน list ของ unitCode ที่ได้ทั้งหมด (ผู้เรียกเอาไปเทียบ
    RANGERSCONFIG เองต่อเพื่อตั้งชื่อไฟล์) เดิมสุ่มครั้งเดียว ตอนนี้รับพารามิเตอร์เพิ่มให้เหมือน UI
    การเปลี่ยนคืน list เหมือนเดิม ผู้เรียกทั้งสองจุด (reroll flow) จึงไม่ต้องแก้

    gacharangergroup: groupId ตู้ที่จะสุ่ม (เช่น 'grp_gacha_33' ที่เลือกจาก dropdown ใน main.py)
      None = ให้เลือกตู้ที่รับตั๋วอัตโนมัติ (pick_ticket_group) เหมือนพฤติกรรมเดิม
    stop_when_found: เจอเรนเจอร์ที่อยู่ใน RANGERSCONFIG แล้วหยุดทันที (ดีฟอลต์ True)
    gacha_mode: 'giveItAll' สุ่มจนตั๋ว/รูบี้หมด | 'NumberOfCycles' สุ่มครบ gacha_cycles รอบแล้วหยุด
    gacha_cycles: จำนวนรอบเมื่อ gacha_mode='NumberOfCycles'
    use_ruby: ตั๋วหมดแล้วยอมจ่ายรูบี้ต่อ (ดีฟอลต์ False = จ่ายเฉพาะตั๋ว ตั๋วหมดก็หยุด)

    จ่ายตั๋วก่อนเสมอ (คุ้มกว่า) ตั๋วไม่พอค่อยใช้รูบี้ถ้า use_ruby=True index 1 = สุ่มเดี่ยว
    เทียบเรนเจอร์แบบตรงตัว (RANGERSCONFIG.get(code.lower())) ไม่ใช่ matchGachaName fuzzy เพราะ
    ได้ unitCode เป๊ะจาก API ไม่มีความเพี้ยนของ OCR ให้ต้องกลบ (โค้ดต่างตัวเดียวจะจับผิดตัว)
    unitCode คืนเต็มไม่ตัด prefix (RANGERSCONFIG เก็บ key เป็น code เต็ม u1630e-sally)
    """
    global LASTGACHASTATUS
    _device_session, _rewards, gacha = _importApiTools()
    cookie = getLFAC()

    # หาตู้เป้าหมาย + ราคาสุ่มเดี่ยว (ตั๋ว/รูบี้)
    if gacharangergroup:
        groupId = gacharangergroup
        rubyPrice, ticketPrice, name = _gachaGroupPull(cookie, groupId)
    else:
        groupId, ticketPrice, name = _apiCall(gacha.pick_ticket_group, cookie)
        rubyPrice = _gachaGroupPull(cookie, groupId)[0] if groupId else 0
    if not groupId:
        LASTGACHASTATUS = "no-machine"
        log("No open gacha machine - skip gacha")
        return []
    log(f"Gacha target {groupId} ({name}) - ticket {ticketPrice}/pull, ruby {rubyPrice}/pull")

    granted_codes = []
    cycles = 0
    while True:
        if gacha_mode == "NumberOfCycles" and cycles >= gacha_cycles:
            break

        # LASTGACHASTATUS บอกเหตุผลไว้ให้ log สรุป session เพราะ list ว่างบอกไม่ได้ว่าไม่มีตู้
        # ตั๋วหมด หรือสุ่มแล้วไม่ได้อะไร ซึ่งคนละเรื่องกันตอน monitor
        info = getRubyAndTicket(summary=False)
        premium, ruby = info["ticket"], info["ruby"]
        # เลือกวิธีจ่าย: ตั๋วก่อน ไม่พอค่อยรูบี้ (เมื่อ use_ruby) ไม่พอทั้งคู่ = จบ
        if ticketPrice and premium >= ticketPrice:
            payType = "TICKET"
        elif use_ruby and rubyPrice and ruby >= rubyPrice:
            payType = "RUBY"
        else:
            LASTGACHASTATUS = f"no-resource:tk{premium}/rb{ruby}"
            log(f"Gacha stop: ตั๋ว {premium} รูบี้ {ruby} ไม่พอ "
                f"(ตั๋ว/รอบ {ticketPrice}, รูบี้/รอบ {rubyPrice}, use_ruby={use_ruby})")
            break

        try:
            granted = _apiCall(gacha.cmd_roll, cookie, None, groupId, 1, payType, True) or []
        except Exception as e:
            LASTGACHASTATUS = f"roll-error:{e}"
            log(f"Gacha roll ล้มเหลว หยุด: {e}")
            break
        codes = [unit.get("unitCode", "") for unit in granted if unit.get("unitCode")]
        granted_codes.extend(codes)
        cycles += 1
        log(f"Gacha {groupId} pull #{cycles} ({payType}): {', '.join(codes) or 'none'}")

        # เจอเรนเจอร์ที่ตั้งไว้ใน config แล้วหยุด
        if stop_when_found and any(RANGERSCONFIG.get(c.lower()) for c in codes):
            log(f"Gacha พบเรนเจอร์เป้าหมาย หยุดสุ่ม")
            break

    LASTGACHASTATUS = ",".join(granted_codes) if granted_codes else "empty"
    log(f"Gacha granted รวม: {', '.join(granted_codes) if granted_codes else 'none'}")
    return granted_codes


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


def startBotGenIDLevel1(deviceSerial=""):
    """สร้าง ID ใหม่ เล่นด่าน 1 จนถึง minLevel แล้วรับของ + สุ่มกาชาผ่าน API

    โครงเดิมมาจาก startBotGenID(): ล้าง shared_prefs แล้วเปิดเกมโหมด genid ให้ได้
    guest ใหม่ จากนั้น tutorialGenID() กด Loop Click ผ่านบทสอนและเล่นด่าน 1 หนึ่งรอบ
    ต่างจากของเดิมตรงที่ตอนรับของ/กาชาใช้ API แทนการจิ้มหน้าจอ (accept7Day,
    acceptGiftBox, randomGachaRanger) เร็วกว่าและไม่มี OCR ให้พลาด

    minLevel=3 เพราะ popup ของแจกตอนล๊อกอินจะยังไม่โผล่จนกว่าบัญชีจะถึงเลเวล 3
    ตั้ง minLevel=0 ถ้าต้องการแค่เล่นด่าน 1 รอบเดียวตามที่ tutorialGenID ทำ
    """
    global GAMEID
    
    while True:
        GAMEID = ""
        _tutorialGenID = False
        # ตั้งค่าเริ่มต้นไว้ก่อนเข้า for เพราะ log สรุปท้าย session ต้องพิมพ์ได้เสมอ
        # แม้ครบ 3 attempt แล้วพังหมด ถ้าปล่อยให้ประกาศในกลาง try จะได้ NameError
        # ตอนพังจริง แล้ว while True ข้างนอกจะตายทั้งลูป
        sessionStart = time.time()
        sessionStatus = "FAIL"
        currentLevelValue = 0
        rangerNames = ""
        gachaStatus = "-"
        exportedFile = ""
        lastError = ""
        usedAttempts = 0
        print("========= Start =========", flush=True)
        print(">>> genIDLevel1 <<<", flush=True)
        
        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")
        
        force_stop_LINE_Rangers()
        removeAllFiles(showLog=False)

        # ของเดิมใน startBotGenID() วน while True ไม่จำกัดรอบ ถ้าพังถาวรจะวนไม่จบ
        # ตรงนี้จำกัดจำนวนรอบไว้ ให้ error ชั่วคราวยังรีทรายได้แต่ error ถาวรหยุดเอง
        for attempt in range(1, 4):
            usedAttempts = attempt
            try:
                openLineRangers(genid=True, skipLoadingScreen=True)
                GAMEID = getGameID()
                if openLineRangers(skipLoadingScreen=True) == "authentication_failed":
                    raise Exception("Authentication failed - cannot open game with this ID")
                force_stop_LINE_Rangers()
                # ---------- ส่วน API ----------
                # ถึงตรงนี้ ID เกิดแล้ว ห้ามให้อะไรพังจนไม่ได้ export ไฟล์ ครอบ try ไว้ทั้งก้อน
                gachaUnits = []
                try:
                    apiAcceptAllRewards()                   # ใช้ api รับของแจกทั้งหมด
                    gachaUnits = apiGachaWithTicket()       # ใช้ api ใช้ตั๋วสุ่มกาชา 1 ครั้ง
                    gachaStatus = LASTGACHASTATUS
                except Exception as e:
                    gachaStatus = "error"
                    lastError = str(e)
                    log(f"API step failed (ID ยังใช้ได้ ส่งออกต่อ): {e}")
                    traceback.print_exc()

                # unit code จาก API ตรงกับ key ใน src\configRangers.ini อยู่แล้ว จึงเทียบ
                # แบบตรงตัว ไม่ใช้ matchGachaName() ที่ fuzzy 0.8 เพราะอันนั้นมีไว้กลบ
                # ความเพี้ยนของ OCR ซึ่งที่นี่ไม่มี และ code ที่ต่างกันแค่ตัวเดียว
                # (u1630e-sally กับ u1630f-sally) จะได้ ratio ~0.92 แล้วจับผิดตัว
                # วนทุกตัวเผื่อวันหลังเปลี่ยนไปสุ่มแบบ 6+1 (index 2) จะได้ไม่ตกหล่น
                rangerNames = ""
                for unitCode in gachaUnits:
                    rangerName = RANGERSCONFIG.get(unitCode.lower())   # configparser พับ key เป็นตัวเล็ก
                    if rangerName:
                        rangerNames = add_ranger_name(rangerNames, rangerName.replace(" ", ""))

                currentLevelValue = currentLevel()
                if rangerNames:
                    exportedFile = exportFileFromGameToBackup(f"Lv{currentLevelValue}_{rangerNames}")
                else:
                    exportedFile = exportFileFromGameWithGameIDToOutput(f"Lv{currentLevelValue}")
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

        logSession(sessionStart, sessionStatus, GAMEID, currentLevelValue, rangerNames,
                   gachaStatus, usedAttempts, exportedFile, lastError)
        print("========== End ==========", flush=True)



def startBotLogin_API(deviceSerial=""):
    global GAMEID
    MAXATTEMPTS = 3

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
        print(">>> startBotLogin <<<", flush=True)

        setUp(deviceSerial)
        log(f"Bot running on {deviceSerial}")

        for attempt in range(1, MAXATTEMPTS + 1):
            usedAttempts = attempt
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


def getTeanInfo(summary=False, top=None):
    """คืนข้อมูลคลัง rangers ทั้งหมดจาก API เป็น list ของ dict (unitCode, level, rarity)

    เอาทั้งคลัง ไม่เกี่ยวกับทีม: inven=true คือของทั้งหมดที่มี ส่วน team/deck ปิดไว้
    เพราะไม่ได้ใช้ ตัวซ้ำจะมาเป็นคนละ record (คนละ invenId) ตามจริง เช่นมี moon 3 ตัว
    ก็จะได้ 3 แถว การนับจำนวนต่อตัวละครจึงใช้ชื่อ (base_name) ไม่ใช่ unitCode เพราะ
    คนละร่างของตัวเดียวกัน (u32-brown กับ u32e-brown) ต้องนับรวมเป็น brown

    API ไม่ส่ง rarity มาเลย ตัว unit มีแค่ unitCode/unitLevel/maxLevel/talentGrade
    เคยลองเดาเป็น N/R/SR/SSR จาก maxLevel แล้วพบว่าผิด เพราะของจริงมี 15 ค่า (20-180)
    และผูกกับขั้นร่างไม่ใช่ความหายากเดี่ยว ๆ (evolved 80-140, ultra 120-180, special
    20-160) จึงไม่แปลงเป็นตัวอักษร ปล่อย maxLevel ดิบไว้ ใครจะจัดกลุ่มค่อยว่ากัน

    ขั้นร่างอ่านจากท้ายตัวเลขใน unitCode (u1630e-sally -> evolved) ด้วยตารางเดียวกับ
    pull_roster เพื่อให้ชื่อขั้นตรงกันทั้งโปรเจกต์

    summary=False ถ้าจะเอาไปใช้ต่อในโค้ดเฉย ๆ ไม่ต้องพ่นสรุปลง log
    top=None คือโชว์ครบทุกตัวละคร ใส่ตัวเลขถ้าบัญชีใหญ่แล้วอยากเห็นแค่อันดับต้น ๆ
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api
    import pull_roster

    status, data = _apiCall(rangers_api.call, getLFAC(),
                            "/player/units/equip?inven=true&team=false&deck=false")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"getTeanInfo failed (HTTP {status}): {str(data)[:200]}")

    units = (data.get("result") or {}).get("playerUnits") or []
    rows = []
    for unit in units:
        code = unit.get("unitCode", "")
        maxLevel = unit.get("playerUnitMaxLevel") or unit.get("maxLevel")
        rows.append({
            "invenId": unit.get("invenId"),
            "unitCode": code,
            "name": pull_roster.base_name(code),
            "level": unit.get("unitLevel"),
            "maxLevel": maxLevel,
            "evolution": pull_roster.evolution_of(code),
            "talentGrade": unit.get("talentGrade"),
            "locked": unit.get("lockYn"),
        })

    if summary:
        printRosterSummary(rows, top)
    return rows


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


def getRubyAndTicket(summary=True):
    """คืนจำนวนรูบี้และตั๋วสุ่มกาชาจาก API เป็น dict

    รูบี้อยู่ใน rubyBalance ของ /home แยกเป็น free (แจก/ฟาร์มมา) กับ paid (เติมเงิน)
    ยอดที่ใช้ได้จริงคือ total = free + paid เวลาเทียบกับราคาตู้กาชาให้ดู total พอ

    ตั๋วนับผ่าน gacha.ticket_counts() ซึ่งรวม amount (= freeAmount + paidAmount) ของ
    แต่ละไอเทม ห้ามอ่าน rewardAmount เพราะนั่นคือขนาดต่อการได้รับหนึ่งครั้ง ไม่ใช่
    จำนวนที่ถืออยู่ (อ่านผิดจะได้ 0 ตลอด)

    ticket = ตั๋วกาชาปกติ (ni-06) ตัวที่ apiGachaWithTicket() เอาไปใช้สุ่ม
    eventTicket = ตั๋วอีเวนต์ (ni-16) ใช้ได้เฉพาะตู้อีเวนต์ สุ่มตู้ปกติไม่ได้
    ส่วนตั๋ว Classic (ni-33) อยู่คนละระบบ endpoint นี้ไม่เคยส่งมา จึงไม่ได้นับให้
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    _device_session, _rewards, gacha = _importApiTools()
    cookie = getLFAC()

    status, data = _apiCall(rangers_api.call, cookie, "/home")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"getRubyAndTicket failed (HTTP {status}): {str(data)[:200]}")
    ruby = (data.get("result") or {}).get("rubyBalance") or {}

    premium, event = _apiCall(gacha.ticket_counts, cookie)

    info = {
        "ruby": ruby.get("total", 0),
        "rubyFree": ruby.get("free", 0),
        "rubyPaid": ruby.get("paid", 0),
        "ticket": premium,
        "eventTicket": event,
    }
    if summary:
        log(f"Ruby {info['ruby']} (free {info['rubyFree']} / paid {info['rubyPaid']})"
            f" | Ticket {info['ticket']} | Event ticket {info['eventTicket']}")
    return info


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


def playStageHybrid(number=2, rounds=1, setupTeam=False, claimRewards=True, precheck=True):
    """ลูปเล่นด่านแบบไฮบริด: API ทำส่วนที่เร็ว+ชัวร์ / UI ทำเฉพาะการรบ (ดีฟอลต์ด่าน 2)

    ด่าน 2 เบาและเร็ว เหมาะเทสต์ pipeline ฟาร์ม จบด่านมีรางวัลให้รับ แบ่งงานตามที่แต่ละ
    ฝั่งทำได้จริง:
      - API: ตั้งทีม (setUpTeamA1), เช็ค heart/enterable, รับรางวัล (apiAcceptAllRewards)
      - UI : การรบจริง (playMainStageAtNumber) — ฝั่งเดียวที่สร้าง battle log ที่ผ่านได้
        เพราะ save ต้องมี log ที่เซิร์ฟเวอร์จำลองซ้ำ ปลอมผ่าน API ไม่ได้

    ต้องเปิดเกมค้างและล๊อกอินอยู่ก่อนเรียก (เหมือน bot ตัวอื่น) เพราะ playMainStageAtNumber
    เดินผ่าน UI จากหน้าโฮม ส่วน API อ่าน token จาก shared_prefs ไม่สนหน้าจอ

    setupTeam=True ตั้งทีมดีสุดผ่าน API รอบแรก (client ดึงทีมใหม่ตอน UI เข้าด่าน จึงต้องตั้ง
      ก่อนเข้าเล่น) ดีฟอลต์ False เพราะด่าน 2 ทีมไหนก็ผ่าน ไม่อยากไปยุ่งทีมจริงเวลาแค่เทสต์
    precheck=True เช็ค enterable ผ่าน API ก่อนเสียเวลา UI ถ้าเข้าไม่ได้ (เช่น heart หมด) หยุด
    claimRewards=True รับรางวัลผ่าน API หลังจบแต่ละรอบ

    คืน list ผลแต่ละรอบ ('end'/'lost'/'error'/None ตามที่ playMainStageAtNumber คืน)
    """
    results = []
    for i in range(rounds):
        log(f"===== Hybrid stage {number} รอบ {i + 1}/{rounds} =====")
        try:
            # 1. API: เช็คสถานะบัญชี (เป็นการเช็ค token ยังใช้ได้ไปในตัว)
            player = apiGetPlayer()
            hearts = (player.get("hearts") or {}).get("total")
            log(f"API level={player.get('level')} hearts={hearts}")

            # 2. API: ตั้งทีมดีสุด (รอบแรกพอ ทีมอยู่ที่เซิร์ฟเวอร์ UI จะดึงตอนเข้าด่าน)
            if setupTeam and i == 0:
                setUpTeamA1()

            # 3. API: เช็ค enterable ก่อนเสียเวลา UI (enter+cancel ไม่กิน heart)
            if precheck:
                ctx = apiEnterStage(number)
                if not ctx["enterable"]:
                    log(f"ด่าน {number} เข้าไม่ได้: {ctx.get('reason')} - หยุดลูป")
                    break
                log(f"enemyTowerHp={ctx['enemyTowerHp']} team={ctx['teamUnits']}")

            # 4. UI: การรบจริง (ตัวเดียวที่สร้าง battle log ที่เซิร์ฟเวอร์ยอมรับ)
            goToHome()
            result = playMainStageAtNumber(number)
            log(f"play result: {result}")
            results.append(result)

            # 5. API: รับรางวัลที่จบด่านแล้วได้
            if claimRewards:
                apiAcceptAllRewards()
        except Exception as e:
            log(f"Hybrid รอบ {i + 1} error: {e}")
            traceback.print_exc()
            results.append("error")
    log(f"Hybrid loop done: {results}")
    return results


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

def getAccoutInfo():
    teanInfo = []
    level = 0
    RbTk = None
    gameID = ""
    rangerNames = ""
    try:
        teanInfo = getTeanInfo()
        level = currentLevel()
        RbTk = getRubyAndTicket()
        gameID = getGameID()
    except Exception as e:
        gachaStatus = "error"
        lastError = str(e)
        log(f"API step failed (ID ยังใช้ได้ ส่งออกต่อ): {e}")
        traceback.print_exc()

    for i in teanInfo:
        unitCode = i["unitCode"]
        is_match, rangerName = matchGachaName(RANGERSCONFIG, unitCode)
        if is_match:
            rangerNames = add_ranger_name(rangerNames, rangerName)

    # attempt สุดท้ายแล้ว API ยังไม่ได้ ก็ส่งออกไปพร้อม NA ดีกว่าไฟล์ค้าง
    ruby = RbTk["ruby"] if RbTk else "NA"
    ticket = RbTk["ticket"] if RbTk else "NA"

    return rangerNames, level, ruby, ticket, gameID

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


GACHABANNERTYPES = ("ULTRA_RARE", "")


def getGachaBanner(summary=True, includeClosed=False, types=GACHABANNERTYPES, eventOnly=True):
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

    status, data = _apiCall(rangers_api.call, getLFAC(), "/gacha/info")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"getGachaBanner failed (HTTP {status}): {str(data)[:200]}")

    now = int(time.time() * 1000)
    groups = sorted((data.get("result") or {}).get("gachaGroupResponseList") or [],
                    key=lambda g: (g.get("gachaGroup") or {}).get("sortOrder", 999))
    rows = []
    for group in groups:
        gg = group.get("gachaGroup") or {}
        if types is not None and gg.get("gachaDisplayType") not in types:
            continue
        if eventOnly and "[EVENT-" not in (gg.get("gachaName") or ""):
            continue
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


from ADB import setup_emulators
if __name__ == "__main__":
    try:
        setUp("127.0.0.1:16384")
    except:
        setup_emulators()
        setUp("127.0.0.1:16384")


    startBotLogin_API
    startBotCheckGameInfo_API
    getGachaBanner()
    randomGachaRanger


# /storag/emulated/0/Android/data/com.linecorp.LGRGS/files/.res/u1630e-sally/u1630e-sally.png
# u1630e-sally
