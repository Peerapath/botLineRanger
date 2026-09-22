# จำกัด thread pool ของ OpenBLAS/OMP ก่อน import อะไรที่ลาก numpy/cv2 (botLineRanger)
# บน Windows multiprocessing ใช้ spawn = child re-run ไฟล์นี้จากบนสุด บรรทัดนี้จึงรันก่อน numpy โหลด
# ในทุก worker ด้วย กัน OpenBLAS จอง thread เท่าจำนวน core ต่อทุกโปรเซส (ดู botLineRanger.py)
import os as _os
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_MAIN_FREE"):
    _os.environ.setdefault(_v, "1")

from tkinter import filedialog, messagebox
import subprocess
from multiprocessing import Process
import multiprocessing
from botLineRanger import *
import customtkinter as ctk
import os
import shutil
import sys
import requests
import webbrowser
from datetime import datetime
from ADB import *
import time
import threading
import re
import configparser


# ------------------------
# CONFIG
# ------------------------
import hmac as hmac_module
import hashlib
import uuid

try:
    from config_secure import SecureConfig
    VERSION_URL = SecureConfig.get_version_url()
    API_URL = SecureConfig.get_api_url()
except ImportError:
    print("CRITICAL: Security module (config_secure.py) missing!")
    print("Please reinstall the application.")
    sys.exit(1)


# Security: HWID for hardware binding
try:
    from hwid import get_hwid
    MACHINE_HWID = get_hwid()
except ImportError:
    MACHINE_HWID = ""

# Security: Runtime protection (anti-debug, anti-tamper)
try:
    from protection import (
        run_protection_checks, start_background_guard,
        snapshot_module_hashes, register_critical_function,
        get_exe_hash
    )
    _HAS_PROTECTION = True
    EXE_HASH = get_exe_hash() or ""  # SHA-256 of .exe (empty in dev mode)
except ImportError:
    _HAS_PROTECTION = False
    EXE_HASH = ""

# All available play modes (will be filtered based on subscription)
ALL_PLAY_MODE_OPTIONS = {
    "🎮 Login": "ranger_api_Login",
    "🎯 GenID": "ranger_api_GenID",
    "🎯 Stage": "ranger_api_Stage",
    # "🛠 Auto Setup": "AutoSetup",
}

# Composite modes ที่ต้องการหลาย mode เป็น prerequisite
COMPOSITE_MODE_REQUIREMENTS = {
    "test": ["test1", "test2"],
}


WHITELIST_EMAILS = []

CURRENT_VERSION = "a.0.0.1"
USERNAME = ""
DEVICE_ID = ""
CONFIG_PATH = r"src\config.ini"
CONFIGRANGER_PATH = r"src\configRangers.ini"
CONFIGGEAR_PATH = r"src\configGears.ini"
CHOICE = ""
RGACHAMODE = ""
GGACHAMODE = ""


# Colors
dark = "#242424"
whiteblue = "#3FB2FF"
blue = "#0099FF"
darkblue = "#007DD1"
grey = "#696969"
darkgrey = "#3B3B3B"

Authorized = False
AuthorizedFailed = 0
AllowedModes = []  # โหมดที่ user มีสิทธิ์ใช้งาน (จาก subscriptions)
ActiveServices = []  # รายการ services ที่ user สมัครอยู่

timeInterval = 0  # default ms

# ==============================
# Security: Session State
# ==============================
_session_token = None  # JWT token (in-memory only)
_user_secret = None    # HMAC secret key (in-memory only)

# SSE listener state (for near-realtime kick notifications)
_sse_thread = None
_sse_stop = threading.Event()


def sign_request(username, user_secret):
    """
    Create HMAC signature for API request

    Returns:
        dict: timestamp, nonce, signature fields to include in request
    """
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    sign_data = f"{username}|{timestamp}|{nonce}"
    signature = hmac_module.new(
        user_secret.encode('utf-8'),
        sign_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return {
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature,
    }


def get_auth_headers():
    """Get Authorization header with JWT token"""
    if _session_token:
        return {"Authorization": f"Bearer {_session_token}"}
    return {}


def fetch_user_secret(username):
    """
    Fetch user secret from server via challenge endpoint

    Returns:
        str: User secret key or None
    """
    try:
        res = requests.post(API_URL + "/auth/challenge", json={
            "username": username
        }, timeout=30)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "ok":
                return data.get("user_secret")
    except Exception as e:
        print(f"⚠️ Failed to fetch user secret: {e}")
    return None


def refresh_session_token():
    """
    Refresh JWT token in background

    Returns:
        bool: True if refresh successful
    """
    global _session_token
    if not _session_token:
        return False
    try:
        res = requests.post(API_URL + "/auth/refresh",
            json={"hwid": MACHINE_HWID},
            headers=get_auth_headers(),
            timeout=30
        )
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "ok" and data.get("token"):
                _session_token = data["token"]
                return True
        # Token expired or invalid
        _session_token = None
        return False
    except Exception as e:
        print(f"⚠️ Token refresh failed: {e}")
        return False


def _sse_listener_loop(app_instance):
    """
    Background thread: stream kick events from /events/session.
    Auto-reconnect with exponential backoff. Exit when _sse_stop is set.
    """
    import json as _json
    backoff = 5
    max_backoff = 120
    while not _sse_stop.is_set():
        if not _session_token:
            # ไม่มี token แล้ว — หยุด
            time.sleep(5)
            continue
        try:
            url = f"{API_URL}/events/session?device_id={DEVICE_ID}"
            print(f"{datetime.now().strftime('%H:%M:%S')} 📡 SSE connecting {url[:60]}...")
            with requests.get(
                url,
                headers=get_auth_headers(),
                stream=True,
                timeout=(10, None),  # connect timeout 10s, read timeout none
            ) as res:
                if res.status_code == 401:
                    # token หมดอายุ / ไม่ผ่าน verify — ลอง refresh ก่อน reconnect
                    print(f"⚠️ SSE 401 — refreshing token...")
                    if refresh_session_token():
                        print(f"🔐 Token refreshed, reconnecting immediately")
                        backoff = 5
                        continue
                    # refresh ไม่ผ่าน — รอแล้ว backoff
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue
                if res.status_code != 200:
                    print(f"⚠️ SSE HTTP {res.status_code}: {res.text[:200]}")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue

                backoff = 5  # connected → reset
                event_name = None
                data_lines = []
                for raw in res.iter_lines(decode_unicode=True):
                    if _sse_stop.is_set():
                        return
                    if raw is None:
                        continue
                    if raw == "":
                        # dispatch event
                        if event_name and data_lines:
                            payload_str = "\n".join(data_lines)
                            try:
                                payload = _json.loads(payload_str)
                            except Exception:
                                payload = {"raw": payload_str}
                            if event_name == "kicked":
                                print(f"{datetime.now().strftime('%H:%M:%S')} ⛔ SSE kicked: {payload}")
                                try:
                                    app_instance.after(0, lambda p=payload: app_instance._handle_kicked(p))
                                except Exception as ex:
                                    print(f"⚠️ schedule kick handler failed: {ex}")
                                return  # หยุด listener ทันที
                            elif event_name == "close":
                                print(f"{datetime.now().strftime('%H:%M:%S')} 📡 SSE server closed stream")
                                break
                            elif event_name == "connected":
                                print(f"{datetime.now().strftime('%H:%M:%S')} 📡 SSE connected")
                        event_name = None
                        data_lines = []
                        continue
                    if raw.startswith(":"):
                        continue  # comment / heartbeat
                    if raw.startswith("event:"):
                        event_name = raw[6:].strip()
                    elif raw.startswith("data:"):
                        data_lines.append(raw[5:].lstrip())
        except requests.exceptions.RequestException as e:
            if _sse_stop.is_set():
                return
            print(f"⚠️ SSE connection error: {e}; reconnect in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except Exception as e:
            if _sse_stop.is_set():
                return
            print(f"⚠️ SSE unexpected error: {e}; reconnect in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


def _start_sse_listener(app_instance):
    """Start the SSE listener thread (idempotent)."""
    global _sse_thread
    if _sse_thread is not None and _sse_thread.is_alive():
        return
    _sse_stop.clear()
    _sse_thread = threading.Thread(
        target=_sse_listener_loop,
        args=(app_instance,),
        daemon=True,
        name="sse-listener",
    )
    _sse_thread.start()


def _stop_sse_listener():
    """Signal the SSE listener to stop."""
    _sse_stop.set()


class EmulatorManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("BotLineRanger")
        self.geometry("640x360+640+360")
        self.configure(bg=dark)
        try:
            self.iconbitmap(r"src\image\home\BotLineRanger_128.ico")
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._closing = False  # ป้องกันการเรียก on_close หลายครั้ง

        self.check_vars = []
        self.all_selected = False
        self.bot_processes = {}
        self.worker_procs = {}            # Login headless workers (subprocess.Popen ของ bot_worker.py)
        self.status_labels = {}
        self.control_buttons = {}
        self._worker_monitor_job = None   # ตัวจับเวลาตัวเดียวคุมทุก worker ในโหมด Login (headless)

        # Config
        self.config = configparser.ConfigParser()
        self.load_config()

        # จำนวน thread สำหรับโหมด Login (headless) - แต่ละ thread = 1 โปรเซสที่หยิบไฟล์จาก input/ แบ่งกันเอง
        try:
            self.thread_count = self.config.getint("settings", "threadcount", fallback=4)
        except Exception:
            self.thread_count = 4
        self.thread_count = max(1, min(self.thread_count, 1024))
        self._worker_seq = 0   # ลำดับ worker ที่สปอว์น ใช้แจก proxy วน (ดู _worker_env)
        self._warned_api_config = False   # เตือน config rate limit ผิดรูปแบบครั้งเดียวต่อรอบ

        self._save_job = None  # สำหรับ debounce

        # For playmode specific UI
        self.mode_specific_frame = None

        # -------------------------
        # ส่วนบน: ปุ่มควบคุมหลัก
        # -------------------------
        top_frame = ctk.CTkFrame(self)
        top_frame.pack(fill="x", padx=10, pady=(5, 0))

        self.btn_select_all = ctk.CTkButton(
            top_frame, text="✅Select All", width=90, command=self.toggle_select)
        self.btn_select_all.pack(side="left", padx=4, pady=6)

        # play mode options - เริ่มต้นด้วยทุกโหมด จะถูก filter หลังจาก verify subscription
        self.play_mode_options = ALL_PLAY_MODE_OPTIONS.copy()
        self.play_mode_var = ctk.StringVar()
        self.top_frame = top_frame  # เก็บ reference เพื่อใช้อัปเดต dropdown
        self.play_mode = ctk.CTkOptionMenu(
            top_frame,
            variable=self.play_mode_var,
            width=0,
            fg_color="#444444",
            button_color="#444444",
            button_hover_color="#555555",
            text_color="white",
            values=list(self.play_mode_options.keys()),
            command=lambda _: [self.debounce_save(), self.update_playmode_settings(), self.render_left_panel()]
        )

        # reverse map and set default
        current_value = self.config["mode"].get("playmode", "AutoSetup")
        reverse_options = {v: k for k, v in self.play_mode_options.items()}
        default_key = list(self.play_mode_options.keys())[0]
        self.play_mode_var.set(reverse_options.get(current_value, default_key))
        self.play_mode.pack(side="left", padx=4)

        self.btn_start_bot = ctk.CTkButton(top_frame, text="▶ Start Bot", width=90,
                                           fg_color="#008744", hover_color="#00a65a", command=self.start_bot_for_selected)
        self.btn_start_bot.pack(side="left", padx=4)

        self.btn_stop_bot = ctk.CTkButton(
            top_frame, text="⏸ Stop", width=90, fg_color="#e51c23", hover_color="#ff4444", command=self.stop_bot_for_selected)
        self.btn_stop_bot.pack(side="left", padx=4)

        self.sub_button = ctk.CTkButton(
            top_frame, text="⏱ XX วัน", width=60, command=lambda: open_facebook())
        self.sub_button.pack(side="right", padx=4)

        self.btn_log_out = ctk.CTkButton(top_frame, text="🔑", width=30, text_color="#999999",
                                          fg_color="#333333", hover_color="#444444", command=self.logout)
        self.btn_log_out.pack(side="right", padx=5)
        # -------------------------
        # กลาง: Emulator + Settings
        # -------------------------
        middle_frame = ctk.CTkFrame(self, fg_color="#2b2b2b")
        middle_frame.pack(fill="both", expand=True, padx=10, pady=(5, 0))

        # ซ้าย: Emulator list
        self.left_frame = ctk.CTkScrollableFrame(middle_frame, width=330)
        self.left_frame.pack(side="left", fill="both",
                             expand=True, padx=(10, 5), pady=10)

        ctk.CTkLabel(self.left_frame, text="❌ ไม่พบอุปกรณ์ ADB", text_color="gray").pack(pady=10)

        # ขวา: Settings และ PlayMode-specific UI
        self.right_frame = ctk.CTkScrollableFrame(middle_frame)
        self.right_frame.pack(side="right", fill="both",
                         expand=True, padx=(5, 10), pady=10)

        # ----------- SETTINGS (สร้างครั้งเดียว) -----------
        # create initial playmode UI
        self.update_playmode_settings()

        # -------------------------
        # ล่าง: ADB Controls
        # -------------------------
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.pack(fill="x", padx=10, pady=(5, 5))

        self.btn_start_adb = ctk.CTkButton(self.bottom_frame, text="⭕ Start ADB", width=90,
                                           text_color="#40bd46", fg_color="#333333", hover_color="#444444", command=self.start_adb)
        self.btn_start_adb.pack(side="left", padx=5, pady=6)

        self.btn_kill_adb = ctk.CTkButton(self.bottom_frame, text="❌ Kill ADB", width=90, text_color="#dd5555",
                                          fg_color="#333333", hover_color="#444444", command=self.kill_server_adb)
        self.btn_kill_adb.pack(side="left", padx=5)

        # --- current file (กดเพื่อเปิดโฟลเดอร์) ---
        self.label_input_files = ctk.CTkLabel(self.bottom_frame, text="input: 0",
                     text_color="#3E97D3", cursor="hand2")
        self.label_input_files.pack(side="left", padx=(25, 5))
        self.label_input_files.bind("<Button-1>", lambda e: self.open_folder_input())

        self.label_output_files = ctk.CTkLabel(self.bottom_frame, text="output: 0",
                     text_color="#2DAAA0", cursor="hand2")
        self.label_output_files.pack(side="left", padx=(10, 5))
        self.label_output_files.bind("<Button-1>", lambda e: self.open_folder_output())

        self.label_execute_files = ctk.CTkLabel(self.bottom_frame, text="execute: 0",
                     text_color="gray", cursor="hand2")
        self.label_execute_files.pack(side="left", padx=(10, 5))
        self.label_execute_files.bind("<Button-1>", lambda e: self.open_folder_execute())

        self.label_backup_files = ctk.CTkLabel(self.bottom_frame, text="backup: 0",
                     text_color="#3e9e42", cursor="hand2")
        self.label_backup_files.pack(side="left", padx=(10, 25))
        self.label_backup_files.bind("<Button-1>", lambda e: self.open_folder_backup())

        # เริ่ม watch โฟลเดอร์
        self.update_file_counts()
        self._start_folder_watcher()

        # --- current version ---

        self.label_current_version = ctk.CTkLabel(self.bottom_frame, text=f"v{CURRENT_VERSION}",
                     text_color="gray")
        self.label_current_version.pack(side="right", padx=(5, 10))

        # Force paint window ก่อน เพื่อให้ UI โผล่ทันที
        try:
            self.update_idletasks()
        except Exception:
            pass
        # ทุก task ด้านล่างเป็น non-blocking (spawn background thread ภายใน)
        # โหมด Login = แผงตั้งจำนวน thread (headless ไม่ต้องสแกน adb) โหมดอื่น = สแกน device
        self.after(0, self.render_left_panel)
        self.after(0, self.check_for_update)
        self.after(0, self.start_server_render)
        self.after(1800000, self.verify_subscription)  # ตรวจสอบทุก 30 นาที (1800000 ms)


    # -----------------------------
    # ฟังก์ชันโหลดและบันทึก config
    # -----------------------------

    def debounce_save(self, event=None):
        if self._save_job:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass

        # event can be None or a tkinter event
        self._save_job = self.after(500, self.save_config)

    def refresh_gacha_banners(self, autoConnect=False):
        """ดึงรายการตู้กาชาจาก API มาใส่ dropdown ตู้กาชา

        ทำใน thread แยกเสมอ เพราะ getGachaBanner() เรียก getLFAC() ที่รอ token จากเครื่อง
        ได้นานถึง 30 วิ ถ้าทำบน UI thread จอจะค้าง อัปเดต widget ผ่าน self.after(0, ...)
        ตามแพทเทิร์นเดียวกับที่สแกน emulator ในไฟล์นี้

        headless: ไม่ต้องมี emulator/เกม - ยืม token จากไฟล์บัญชีในโฟลเดอร์ input/ ด้วย
        reloginFromInput() (relogin สร้าง LF_AC สดจากไฟล์) แล้วเอาไปยิง /gacha/info
        autoConnect=False (ตอนเปิดแท็บ) = ถ้าโหลดไม่ได้ก็เงียบ, True (กดปุ่ม 🔄) = log error
        """
        def work():
            try:
                cookie = reloginFromInput()          # LF_AC สดจากไฟล์ใน input/ (ไม่แตะ device)
                rows = getGachaBanner(summary=False, cookie=cookie)
            except Exception as e:
                if autoConnect:
                    try:
                        log(f"refresh_gacha_banners: โหลดไม่ได้ {e}")
                    except Exception:
                        pass
                return
            mapping = {"%s" % (", ".join(r["featured"])): r["groupId"]
                       for r in rows}
            try:
                saved = self.config.get("settings", "gacharangergroup")
            except Exception:
                saved = ""

            def apply():
                if not mapping:
                    return
                self.gacha_group_map = mapping
                labels = list(mapping.keys())
                self.gacha_group.configure(values=labels)
                # เลือก label ที่ groupId ตรงกับที่เซฟไว้ ไม่มีก็เอาตัวแรก
                cur = next((l for l, g in mapping.items() if g == saved), labels[0])
                self.gacha_group_var.set(cur)
            self.after(0, apply)
        threading.Thread(target=work, daemon=True).start()

    def load_config(self):
        # ensure file exists
        if not os.path.exists(CONFIG_PATH):
            messagebox.showerror("Error", "config.ini not found")
            self.destroy()
            return
        self.config.read(CONFIG_PATH, encoding="utf-8")

    def save_config(self):
        global CHOICE
        # Read current settings from widgets (created once)
        try:
            self.config.setdefault("settings", {})
            self.config.setdefault("mode", {})
            self.config.setdefault("login", {})
            try:
                # โหมด Stage อ่านค่านี้เป็น int (botLineRanger._loadBotConfig ใช้ getint) ถ้าผู้ใช้
                # พิมพ์ตัวอักษร/ว่าง ต้องไม่เขียนลงไฟล์ ไม่งั้น worker พังตั้งแต่โหลด config
                stage_end = int(str(self.stage_end.get()).strip())
                self.config["settings"]["stageend"] = str(max(1, min(stage_end, 500)))
            except Exception:
                pass
            try:
                self.config["settings"]["autouseitem"] = str(self.auto_use_item.get())
            except Exception:
                pass
            try:
                self.config["settings"]["giftbox"] = str(self.gift_box.get())
            except Exception:
                pass
            try:
                self.config["settings"]["autoteam"] = str(self.auto_team.get())
            except Exception:
                pass
            try:
                self.config["settings"]["timeinterval"] = str(self.time_interval.get())
            except Exception:
                pass
            try:
                self.config["settings"]["closepoup"] = str(self.close_poup.get())
            except Exception:
                pass
            try:
                self.config["settings"]["rselctionevent"] = str(self.rselction_event.get())
            except Exception:
                pass
            try:
                self.config["settings"]["gselctionevent"] = str(self.gselction_event.get())
            except Exception:
                pass
            try:
                self.config["settings"]["rangerinteam"] = str(self.ranger_in_team.get())
            except Exception:
                pass
            try:
                self.config["settings"]["maxmineralcost"] = str(self.max_mineral_cost.get())
            except Exception:
                pass
            try:
                self.config["settings"]["rstopwhenfound"] = str(self.rstop_when_found.get())
            except Exception:
                pass
            try:
                self.config["settings"]["gstopwhenfound"] = str(self.gstop_when_found.get())
            except Exception:
                pass
            try:
                self.config["settings"]["rgachacycles"] = str(self.rgacha_cycles.get())
            except Exception:
                pass
            try:
                self.config["settings"]["ggachacycles"] = str(self.ggacha_cycles.get())
            except Exception:
                pass
            try:
                self.config["settings"]["accept7day"] = str(self.accept_7_day.get())
            except Exception:
                pass
            try:
                self.config["settings"]["acceptpass"] = str(self.accept_pass.get())
            except Exception:
                pass
            try:
                self.config["settings"]["ruseruby"] = str(self.ruse_ruby.get())
            except Exception:
                pass
            try:
                self.config["settings"]["guse200ruby"] = str(self.guse_200ruby.get())
            except Exception:
                pass
            try:
                self.config["settings"]["exchangegachatickets"] = str(self.exchange_gacha_tickets.get())
            except Exception:
                pass
            try:
                self.config["settings"]["buyleonard9"] = str(self.buy_leonard_9.get())
            except Exception:
                pass
            try:
                self.config["settings"]["buyruby"] = str(self.buy_ruby.get())
            except Exception:
                pass
            try:
                self.config["settings"]["buyticket"] = str(self.buy_ticket.get())
            except Exception:
                pass
            try:
                self.config["settings"]["readRBTK"] = str(self.read_RBTK.get())
            except Exception:
                pass
            try:
                self.config["settings"]["gacharanger"] = str(self.gacha_ranger.get())
            except Exception:
                pass
            try:
                rbtk_position_options = { "หน้า": "front", "กลาง": "middle", "หลัง": "back" }
                self.config["settings"]["rbtkposition"] = rbtk_position_options.get(self.rbtk_position_var.get(), "everyTime")
            except Exception:
                pass
            try:
                buy_friend_options = { "ซื้อทุกครั้ง": "everyTime", "ซื้อเมื่อแพ้": "justLost", "ไม่ซื้อเลย": "dontBuy" }
                self.config["settings"]["buyfriend"] = buy_friend_options.get(self.buy_friend_var.get(), "everyTime")
            except Exception:
                pass
            try:
                auto_mode_options = { "ของบอท": "bot", "ตัวเกม": "game" }
                self.config["settings"]["automode"] = auto_mode_options.get(self.auto_mode_var.get(), "bot")
            except Exception:
                pass
            try:
                # เซฟ groupId ของตู้ที่เลือก (map จาก label "groupId : featured")
                self.config["settings"]["gacharangergroup"] = self.gacha_group_map.get(
                    self.gacha_group_var.get(), "")
            except Exception:
                pass
            try:
                rgacha_mode_options = {"ตั๋วทั้งหมด": "giveItAll", "จำนวนรอบ": "NumberOfCycles" }
                self.config["settings"]["rgachamode"] = rgacha_mode_options.get(self.rgacha_mode_var.get(), "giveItAll")
            except Exception:
                pass
            try:
                rgacha_mode_options = {"ตั๋วทั้งหมด": "giveItAll", "จำนวนรูบี้": "LimitOfRuby" }
                self.config["settings"]["ggachamode"] = rgacha_mode_options.get(self.ggacha_mode_var.get(), "giveItAll")
            except Exception:
                pass
            CHOICE = self.play_mode_options.get(self.play_mode_var.get(), "PlayStage30-100-150")
            self.config["mode"]["playmode"] = CHOICE

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                self.config.write(f)

        except Exception as e:
            print("Error saving config:", e)


    # -----------------------------
    # Playmode-specific UI (สร้าง/ลบ เฉพาะส่วนพิเศษ)
    # -----------------------------
    def create_playmode_frame(self, mode_key):
        global RGACHAMODE
        # clear previous mode-specific frame (only)
        if self.mode_specific_frame and self.mode_specific_frame.winfo_exists():
            self.mode_specific_frame.destroy()
        self.mode_specific_frame = ctk.CTkFrame(self.right_frame)
        self.mode_specific_frame.pack(fill="both", expand=True, padx=10, pady=(5, 3))

        # Mode specific
        if mode_key == "ranger_api_Login":
            ctk.CTkLabel(self.mode_specific_frame, text="🎮 ล๊อกอินไอดีเกม").pack(pady=3)
        elif mode_key == "ranger_api_GenID":
            ctk.CTkLabel(self.mode_specific_frame, text="🎯 สร้างไอดีใหม่เลเวล1").pack(pady=3)
        elif mode_key == "ranger_api_Stage":
            ctk.CTkLabel(self.mode_specific_frame, text="🎯 ดันด่านไอดีจาก input/").pack(pady=3)
        elif mode_key == "AutoSetup":
            ctk.CTkLabel(self.mode_specific_frame, text="🛠 Auto Setup").pack(pady=3)
        else:
            ctk.CTkLabel(self.mode_specific_frame, text="ตั้งค่าโหมดนี้ยังไม่ถูกกำหนด").pack(pady=10)

        # shared controls for mode frame
        btn_input_output_frame = ctk.CTkFrame(self.mode_specific_frame)
        btn_input_output_frame.pack(fill="x", padx=0, pady=(5, 3))
        self.btn_input = ctk.CTkButton(btn_input_output_frame, text="⬇ Input", width=80, command=self.open_folder_input)
        self.btn_input.pack(side="left", padx=(0, 5))
        self.btn_output = ctk.CTkButton(btn_input_output_frame, text="⬆ Output", width=80, command=self.open_folder_output)
        self.btn_output.pack(side="left", padx=5)

        btn_execute_frame = ctk.CTkFrame(self.mode_specific_frame)
        btn_execute_frame.pack(fill="x", padx=0, pady=(5, 3))
        self.btn_execute = ctk.CTkButton(btn_execute_frame, text="♻ Execute", fg_color="#333333", hover_color="#444444", width=80, command=self.open_folder_execute)
        self.btn_execute.pack(side="left", padx=(0, 5))

        ctk.CTkFrame(self.mode_specific_frame, height=1, fg_color="#333333").pack(fill="x", padx=5, pady=5)

        # Mode specific
        if mode_key == "ranger_api_Login":
            # gacha_ranger
            btn_gacharanger_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_gacharanger_frame.pack(fill="x", pady=3)
            self.gacha_ranger = ctk.CTkCheckBox(
                btn_gacharanger_frame,
                text="กาชาเรนเจอร์",
                onvalue=True, offvalue=False,
                command=self.debounce_save
            )
            try:
                if self.config.getboolean("settings", "gacharanger"):
                    self.gacha_ranger.select()
                else:
                    self.gacha_ranger.deselect()
            except Exception:
                self.gacha_ranger.deselect()
            self.gacha_ranger.pack(side="left", padx=(0, 5), pady=3)

            # dropdown เลือกตู้กาชา (ต่อท้ายกาชาเรนเจอร์) รายการมาจาก getGachaBanner()
            # label = "groupId : featured1, featured2" ค่าที่เซฟคือ groupId ล้วน ๆ
            btn_gachagroup_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_gachagroup_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(btn_gachagroup_frame, text="ตู้กาชา").pack(side="left", padx=(0, 5))
            try:
                saved_group = self.config.get("settings", "gacharangergroup")
            except Exception:
                saved_group = ""
            # เริ่มด้วยค่าที่เซฟไว้ (หรือ placeholder) ยังไม่ยิง API ตรงนี้ เพราะ getGachaBanner()
            # เรียก getLFAC() ที่รอ token จากเครื่องได้นานถึง 30 วิ ถ้าทำบน UI thread จอจะค้าง
            init_label = saved_group or "(กดรีเฟรช 🔄)"
            self.gacha_group_map = {init_label: saved_group}
            self.gacha_group_var = ctk.StringVar(value=init_label)
            self.gacha_group = ctk.CTkOptionMenu(
                btn_gachagroup_frame, variable=self.gacha_group_var, width=0, height=22,
                values=[init_label], command=lambda _: self.debounce_save())
            self.gacha_group.pack(side="left", padx=(0, 5))
            ctk.CTkButton(btn_gachagroup_frame, text="🔄", width=28, height=22,
                          command=lambda: self.refresh_gacha_banners(autoConnect=True)).pack(side="left", padx=(0, 5))
            # โหลดรายการตู้ครั้งแรกแบบ background (ไม่บล็อก UI) เผื่อเครื่องพร้อมแล้ว
            self.refresh_gacha_banners()


            # rgacha_cycles
            btn_rgachacycles_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_rgachacycles_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(btn_rgachacycles_frame, text="จำนวนรอบ").pack(side="left", padx=(0, 5))
            self.rgacha_cycles = ctk.CTkEntry(btn_rgachacycles_frame, placeholder_text="1", width=50, height=20)
            try:
                self.rgacha_cycles.insert(0, self.config.get("settings", "rgachacycles"))
            except Exception:
                self.rgacha_cycles.insert(0, "1")
            self.rgacha_cycles.pack(side="left")
            self.rgacha_cycles.bind("<KeyRelease>", self.debounce_save)


        elif mode_key == "ranger_api_GenID":
            # gacha_ranger
            btn_gacharanger_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_gacharanger_frame.pack(fill="x", pady=3)
            self.gacha_ranger = ctk.CTkCheckBox(
                btn_gacharanger_frame,
                text="กาชาเรนเจอร์",
                onvalue=True, offvalue=False,
                command=self.debounce_save
            )
            try:
                if self.config.getboolean("settings", "gacharanger"):
                    self.gacha_ranger.select()
                else:
                    self.gacha_ranger.deselect()
            except Exception:
                self.gacha_ranger.deselect()
            self.gacha_ranger.pack(side="left", padx=(0, 5), pady=3)

            # dropdown เลือกตู้กาชา (ต่อท้ายกาชาเรนเจอร์) รายการมาจาก getGachaBanner()
            # label = "groupId : featured1, featured2" ค่าที่เซฟคือ groupId ล้วน ๆ
            btn_gachagroup_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_gachagroup_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(btn_gachagroup_frame, text="ตู้กาชา").pack(side="left", padx=(0, 5))
            try:
                saved_group = self.config.get("settings", "gacharangergroup")
            except Exception:
                saved_group = ""
            # เริ่มด้วยค่าที่เซฟไว้ (หรือ placeholder) ยังไม่ยิง API ตรงนี้ เพราะ getGachaBanner()
            # เรียก getLFAC() ที่รอ token จากเครื่องได้นานถึง 30 วิ ถ้าทำบน UI thread จอจะค้าง
            init_label = saved_group or "(กดรีเฟรช 🔄)"
            self.gacha_group_map = {init_label: saved_group}
            self.gacha_group_var = ctk.StringVar(value=init_label)
            self.gacha_group = ctk.CTkOptionMenu(
                btn_gachagroup_frame, variable=self.gacha_group_var, width=0, height=22,
                values=[init_label], command=lambda _: self.debounce_save())
            self.gacha_group.pack(side="left", padx=(0, 5))
            ctk.CTkButton(btn_gachagroup_frame, text="🔄", width=28, height=22,
                          command=lambda: self.refresh_gacha_banners(autoConnect=True)).pack(side="left", padx=(0, 5))
            # โหลดรายการตู้ครั้งแรกแบบ background (ไม่บล็อก UI) เผื่อเครื่องพร้อมแล้ว
            self.refresh_gacha_banners()


            # rgacha_cycles
            btn_rgachacycles_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_rgachacycles_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(btn_rgachacycles_frame, text="จำนวนรอบ").pack(side="left", padx=(0, 5))
            self.rgacha_cycles = ctk.CTkEntry(btn_rgachacycles_frame, placeholder_text="1", width=50, height=20)
            try:
                self.rgacha_cycles.insert(0, self.config.get("settings", "rgachacycles"))
            except Exception:
                self.rgacha_cycles.insert(0, "1")
            self.rgacha_cycles.pack(side="left")
            self.rgacha_cycles.bind("<KeyRelease>", self.debounce_save)

        elif mode_key == "ranger_api_Stage":
            # ด่านเป้าหมาย: ดันจากด่านที่ไอดีนั้นค้างอยู่ ไปจนถึงเลขนี้ (เซฟลง settings.stageend)
            btn_stageend_frame = ctk.CTkFrame(self.mode_specific_frame)
            btn_stageend_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(btn_stageend_frame, text="เล่นถึงด่าน").pack(side="left", padx=(0, 5))
            self.stage_end = ctk.CTkEntry(btn_stageend_frame, placeholder_text="150", width=50, height=20)
            try:
                self.stage_end.insert(0, self.config.get("settings", "stageend"))
            except Exception:
                self.stage_end.insert(0, "150")
            self.stage_end.pack(side="left")
            self.stage_end.bind("<KeyRelease>", self.debounce_save)
            ctk.CTkLabel(self.mode_specific_frame,
                         text="ดันด่านผ่าน API ล้วน (ไม่เปิดเกม) เริ่มจากด่านที่ไอดีนั้นค้างอยู่\n"
                              "จบแล้วส่งไฟล์ออก output/ พร้อมเลเวลใหม่ในชื่อไฟล์",
                         text_color="gray", anchor="w", justify="left", wraplength=300).pack(fill="x", padx=5, pady=(2, 3))

        elif mode_key == "AutoSetup":
            ctk.CTkLabel(self.mode_specific_frame, text="🛠 Auto Setup").pack(pady=3)

        else:
            ctk.CTkLabel(self.mode_specific_frame, text="ตั้งค่าโหมดนี้ยังไม่ถูกกำหนด").pack(pady=10)


        ctk.CTkFrame(self.mode_specific_frame, height=1, fg_color="#333333").pack(fill="x", padx=5, pady=5)


        # time_interval
        btn_timeinterval_frame = ctk.CTkFrame(self.mode_specific_frame)
        btn_timeinterval_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(btn_timeinterval_frame, text="หน่วงเวลาการเริ่มรันบอท").pack(side="left", padx=(0, 5))
        self.time_interval = ctk.CTkEntry(btn_timeinterval_frame, placeholder_text="5", width=50, height=20)
        try:
            self.time_interval.insert(0, self.config.get("settings", "timeinterval"))
        except Exception:
            self.time_interval.insert(0, "5")
        self.time_interval.pack(side="left")
        self.time_interval.bind("<KeyRelease>", self.debounce_save)










    def update_playmode_settings(self):
        playmode_key = self.play_mode_options.get(self.play_mode_var.get(), "PlayStage30-100-150")
        self.create_playmode_frame(playmode_key)

    def update_play_mode_dropdown(self, allowed_modes: list):
        """อัปเดต dropdown ของ play mode ตาม allowed_modes ที่ได้จาก subscription"""
        global AllowedModes
        AllowedModes = allowed_modes
        
        # Filter play_mode_options based on allowed_modes
        self.play_mode_options = {
            k: v for k, v in ALL_PLAY_MODE_OPTIONS.items()
            if v in allowed_modes
            or (v in COMPOSITE_MODE_REQUIREMENTS and all(req in allowed_modes for req in COMPOSITE_MODE_REQUIREMENTS[v]))
        }
        
        if not self.play_mode_options:
            # ถ้าไม่มี mode ที่อนุญาตเลย ให้แสดง AutoSetup เป็น default
            self.play_mode_options = {"🛠 Auto Setup": "AutoSetup"}
        
        # สร้าง dropdown ใหม่
        current_value = self.play_mode_var.get()
        new_values = list(self.play_mode_options.keys())
        
        # อัปเดต values ใน dropdown
        self.play_mode.configure(values=new_values)
        
        # ถ้า current value ไม่อยู่ใน allowed modes ให้เลือก mode แรก
        if current_value not in new_values:
            self.play_mode_var.set(new_values[0])
            self.update_playmode_settings()
        
        print(f"✅ อัปเดต play modes: {len(self.play_mode_options)} โหมด")

    # -----------------------------
    # The rest of the methods are mostly unchanged, minimal cleanups
    # -----------------------------
    def add_emulator(self, idx, port, status="Stop"):
        frame = ctk.CTkFrame(self.left_frame, fg_color="#303030")
        frame.pack(fill="x", padx=4, pady=3)
        var = ctk.BooleanVar()
        chk = ctk.CTkCheckBox(frame, text=f"#{idx+1}", variable=var, width=60)
        chk.pack(side="left", padx=4)
        self.check_vars.append(var)
        ctk.CTkLabel(frame, text=port, width=105, anchor="w").pack(side="left", padx=4)
        status_label = ctk.CTkLabel(frame, text=status, text_color="gray")
        status_label.pack(side="left", padx=4)
        self.status_labels[port] = status_label

        options = ["🛠 Auto Setup", "⬇ Import ID", "⬆ Export ID", "📄 Log File", "🖼 Screen"]
        menu_var = ctk.StringVar(value="⁝")

        def on_menu_select(choice, dev):
            self.handle_menu_choice(choice, dev)
            menu_var.set("⁝")

        menu = ctk.CTkOptionMenu(frame, values=options, variable=menu_var, width=0,
                                 fg_color="#444444", button_color="#444444", button_hover_color="#555555",
                                 text_color="white", command=lambda choice, dev=port: on_menu_select(choice, dev))
        menu.pack(side="right", padx=(0, 4))

        btnStartStop = ctk.CTkButton(frame, text="▶", width=30, fg_color="#444444", hover_color="#555555")
        btnStartStop.pack(side="right", padx=(0, 4))
        btnStartStop.configure(command=lambda b=btnStartStop, dev=port: self.start_bot(dev, b))
        self.control_buttons[port] = btnStartStop

        if not hasattr(self, "emulators"):
            self.emulators = []
        self.emulators.append(frame)

    def handle_menu_choice(self, choice, dev):
        log_file = f"src/log/bot_{re.sub(r'[^a-zA-Z0-9._-]', '_', dev)}.log"
        if choice == "🛠 Auto Setup":
            self.start_auto_setup(dev, self.control_buttons[dev])
        elif choice == "⬇ Import ID":
            self.importID(dev)
        elif choice == "⬆ Export ID":
            self.exportID(dev)
        elif choice == "📄 Log File":
            self.open_log_file(log_file)
        elif choice == "🖼 Screen":
            self.open_screen_file(dev)

    def stop_bot_processes(self):
        for dev, p in list(self.bot_processes.items()):
            if p.is_alive():
                p.terminate()
                p.join(timeout=2)
        self.bot_processes.clear()
        # หยุด Login workers (subprocess.Popen) ด้วย
        for dev, p in list(getattr(self, "worker_procs", {}).items()):
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        if hasattr(self, "worker_procs"):
            self.worker_procs.clear()

    def _handle_kicked(self, payload):
        """
        เครื่องนี้ถูก login ซ้อนจากเครื่องอื่น — หยุดบอทและปิดแอปพร้อมแจ้งเตือน
        payload: {"reason": "new_login", "new_device_id": "...", "at": <ts>}
        """
        if hasattr(self, '_kicked_shown') and self._kicked_shown:
            return
        self._kicked_shown = True
        print(f"{datetime.now().strftime('%H:%M:%S')} ⛔ Kicked by new login: {payload}")
        _stop_sse_listener()
        try:
            self.stop_bot_processes()
        except Exception:
            pass
        try:
            self.kill_server_adb()
        except Exception:
            pass
        messagebox.showwarning(
            "บัญชีถูกใช้งานซ้อน",
            "⚠️ บัญชีของคุณเพิ่งถูก login จากเครื่องอื่น\n\n"
            "เครื่องนี้จะถูกออกจากระบบ กรุณาเปิดโปรแกรมใหม่หากต้องการใช้งานต่อจากเครื่องนี้"
        )
        self.on_close()

    def on_close(self):
        # ป้องกันการเรียก on_close หลายครั้ง
        if hasattr(self, '_closing') and self._closing:
            return
        self._closing = True

        # หยุด SSE listener ก่อน (ไม่บล็อค เพราะ daemon thread)
        _stop_sse_listener()

        # Checkout เพื่อปลดล็อค device_id
        self.checkout_subscription()

        self.stop_bot_processes()

        # ลบโฟลเดอร์ย่อยที่ว่างเปล่า
        for folder in ["input", "output", "execute", "backup"]:
            self._cleanup_empty_subdirs(folder)

        try:
            subprocess.check_output(r"src\adb\adb kill-server", shell=True)
        except Exception:
            pass
        for p in multiprocessing.active_children():
            try:
                p.terminate()
                p.join(timeout=2)
            except Exception:
                pass
        try:
            self.destroy()
        except Exception:
            pass
        sys.exit(0)
    
    def checkout_subscription(self):
        """เรียก API เพื่อเคลียร์ device_id เมื่อปิดโปรแกรม"""
        global USERNAME, DEVICE_ID
        try:
            if not USERNAME or not DEVICE_ID:
                readConfigFile()

            if not USERNAME or USERNAME.strip().lower() in ["email", "gmail", ""]:
                return

            payload = {
                "username": USERNAME,
                "device_id": DEVICE_ID
            }
            print(f"📤 Checkout: {payload}")

            res = requests.post(API_URL + "/checkout", json=payload, timeout=30)
            data = res.json()

            if data.get("status") == "ok":
                print(f"✅ Checkout สำเร็จ: เคลียร์ {data.get('cleared_count', 0)} subscriptions")
            else:
                print(f"⚠️ Checkout: {data.get('message', 'Unknown error')}")
        except Exception as e:
            print(f"⚠️ Checkout error: {e}")

    def logout(self):
        """Logout: รีเซ็ตอีเมลใน config, เคลียร์ device_id, และปิดโปรแกรม"""
        global USERNAME, DEVICE_ID

        # ป้องกันการเรียก logout หลายครั้ง
        if hasattr(self, '_logging_out') and self._logging_out:
            return
        self._logging_out = True

        try:
            # 1. Checkout subscription เพื่อปลดล็อค device_id
            print("🔒 กำลัง Logout...")
            self.checkout_subscription()

            # 2. รีเซ็ตอีเมลใน config.ini กลับเป็น "email"
            config = configparser.ConfigParser()
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config.read_file(f)

                if "login" not in config:
                    config.add_section("login")

                config.set("login", "email", "email")

                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    config.write(f)

                print("✅ รีเซ็ตอีเมลใน config.ini เรียบร้อย")

            # 3. รีเซ็ต global variables
            USERNAME = ""
            DEVICE_ID = ""

            print("✅ Logout สำเร็จ - กำลังปิดโปรแกรม...")

            # 4. หยุด bot processes
            self.stop_bot_processes()

            # 5. แสดงข้อความและปิดโปรแกรม
            messagebox.showinfo("Logout สำเร็จ", "คุณได้ทำการ Logout เรียบร้อยแล้ว\nโปรแกรมจะปิด")

            # 6. Kill ADB server
            try:
                subprocess.check_output(r"src\adb\adb kill-server", shell=True)
            except Exception:
                pass

            # 7. ปิด multiprocessing
            for p in multiprocessing.active_children():
                try:
                    p.terminate()
                    p.join(timeout=2)
                except Exception:
                    pass

            # 8. ทำลาย GUI และปิดโปรแกรมทันที
            try:
                self.destroy()
            except Exception:
                pass

            # 9. บังคับปิดโปรแกรม
            os._exit(0)

        except Exception as e:
            print(f"❌ Logout error: {e}")
            # ถ้าเกิด error ให้บังคับปิดโปรแกรมเลย
            os._exit(1)

    def aad_update_indicator(self):
        ctk.CTkLabel(self.bottom_frame, text=f"!", text_color="salmon",
                     font=("Segoe UI", 18, "bold"), anchor="e").pack(side="right")

    def importID(self, port):
        path = filedialog.askopenfilename(initialdir="input", title="เลือกไฟล์ ID", filetypes=[("XML files", "*.xml")])
        if not path:
            return
        filename = os.path.basename(path)
        gameId = filename.replace("_LINE_COCOS_PREF_KEY.xml", "")
        try:
            device = None
            devices = client.devices()
            for dev in devices:
                if dev.serial[-4:] == port[-4:]:
                    device = dev
                    break
            if not os.path.exists(path):
                raise FileNotFoundError(f"Template not found: {path}")
            device.push(path, "/sdcard/Download/_LINE_COCOS_PREF_KEY.xml")
            device.shell("su -c 'chmod 666 /sdcard/Download/_LINE_COCOS_PREF_KEY.xml'")
            device.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
            device.shell("su -c 'cp /sdcard/Download/_LINE_COCOS_PREF_KEY.xml /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
            device.shell("rm /sdcard/Download/_LINE_COCOS_PREF_KEY.xml")
            filename = os.path.join("input", filename)
            if os.path.isfile(filename):
                output_dir = "output"
                os.makedirs(output_dir, exist_ok=True)
                shutil.move(filename, os.path.join(output_dir, os.path.basename(filename)))
            messagebox.showinfo("Import สำเร็จ", f"{port} นำเข้า ID: {gameId}")
        except Exception as e:
            messagebox.showerror("Error", f"Import ล้มเหลว: {e}")

    def exportID(self, port):
        device = None
        devices = client.devices()
        for dev in devices:
            if dev.serial[-4:] == port[-4:]:
                device = dev
                break
        if device is None:
            messagebox.showerror("Error", f"ไม่พบอุปกรณ์ {port}")
            return
        setUp(port)
        default_filename = f"{getGameID()}"
        path = filedialog.asksaveasfilename(initialdir="output", initialfile=default_filename, title="บันทึกไฟล์ ID", defaultextension=".xml", filetypes=[("XML files", "*.xml")])
        if not path:
            return
        try:
            device.shell("su -c 'cp /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml /sdcard/_LINE_COCOS_PREF_KEY.xml'")
            device.pull("/sdcard/_LINE_COCOS_PREF_KEY.xml", path)
            device.shell("rm /sdcard/_LINE_COCOS_PREF_KEY.xml")
            messagebox.showinfo("Export สำเร็จ", f"{port} บันทึก ID ไปที่:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Export ล้มเหลว: {e}")

    def start_bot(self, dev, btn):
        self.save_config()

        # Verify subscription before starting bot
        if not self.verify_subscription_sync():
            return
        
        status_label = self.status_labels.get(dev)
        if dev in self.bot_processes and self.bot_processes[dev].is_alive():
            p = self.bot_processes[dev]
            p.terminate()
            p.join(timeout=2)
            del self.bot_processes[dev]
            btn.configure(text="▶")
            if status_label:
                status_label.configure(text="Stop", text_color="gray")
        else:
            if getattr(sys, 'frozen', False):
                multiprocessing.set_executable(sys.executable)
            p = Process(target=run_bot, args=(dev, CHOICE))
            p.start()
            self.bot_processes[dev] = p
            self.monitor_bot(dev, p)
            btn.configure(text="∣∣")
            if status_label:
                status_label.configure(text="Running", text_color=whiteblue)
        time.sleep(0.5)

    def start_auto_setup(self, dev, btn):
        status_label = self.status_labels.get(dev)
        if dev in self.bot_processes and self.bot_processes[dev].is_alive():
            p = self.bot_processes[dev]
            p.terminate()
            p.join(timeout=2)
            del self.bot_processes[dev]
            btn.configure(text="▶")
            if status_label:
                status_label.configure(text="Stop", text_color="gray")
        else:
            log_file = f"src/log/bot_{re.sub(r'[^a-zA-Z0-9._-]', '_', dev)}.log"
            if getattr(sys, 'frozen', False):
                multiprocessing.set_executable(sys.executable)
            p = Process(target=run_auto_setup_with_log, args=(dev, log_file))
            p.start()
            self.bot_processes[dev] = p
            self.monitor_bot(dev, p)
            btn.configure(text="∣∣")
            if status_label:
                status_label.configure(text="Running", text_color=whiteblue)
        time.sleep(0.5)

    def start_bot_for_selected(self):
        # โหมด Login/GenID = headless: สปอว์นตามจำนวน thread ไม่ใช้ device
        if self._isHeadlessThreadMode():
            self._start_workers()
            return

        self.save_config()
        # Verify subscription before starting bot
        if not self.verify_subscription_sync():
            return

        readConfigFile()
        selected_devices = []
        for i, var in enumerate(self.check_vars):
            if var.get():
                if i < len(self.status_labels):
                    dev = list(self.status_labels.keys())[i]
                    selected_devices.append(dev)
        if not selected_devices:
            print("No emulator selected!")
            return

        note_file_in_folder(selected_devices)

        def start_with_delay(i):
            if i >= len(selected_devices):
                return
            dev = selected_devices[i]
            if dev in self.bot_processes:
                p = self.bot_processes[dev]
                if p.is_alive():
                    self.after(1000, lambda: start_with_delay(i+1))
                    return
                else:
                    del self.bot_processes[dev]
            if getattr(sys, 'frozen', False):
                multiprocessing.set_executable(sys.executable)
            p = Process(target=run_bot, args=(dev, CHOICE))
            p.start()
            self.bot_processes[dev] = p
            self.monitor_bot(dev, p)
            if dev in self.control_buttons:
                self.control_buttons[dev].configure(text="∣∣")
            if dev in self.status_labels:
                self.status_labels[dev].configure(text="Running", text_color=whiteblue)
            self.after(int(timeInterval), lambda: start_with_delay(i+1))

        start_with_delay(0)


    def stop_bot_for_selected(self):
        # โหมด Login/GenID = headless: หยุดทุก worker
        if self._isHeadlessThreadMode():
            self._stop_workers()
            return

        stopped = []
        selected_devices = []
        for idx, var in enumerate(self.check_vars):
            if var.get():
                if idx < len(self.status_labels):
                    dev = list(self.status_labels.keys())[idx]
                    selected_devices.append(dev)
        for dev in selected_devices:
            if dev in self.bot_processes:
                p = self.bot_processes[dev]
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=2)
                    stopped.append(dev)
                del self.bot_processes[dev]
                if dev in self.control_buttons:
                    self.control_buttons[dev].configure(text="▶")
                if dev in self.status_labels:
                    self.status_labels[dev].configure(text="Stop", text_color="gray")
        if not stopped:
            print("No running bots selected to stop.")
        else:
            print("Stopped bots:", stopped)
        self.after(500, lambda: None)

    def toggle_select(self):
        if not self.all_selected:
            for var in self.check_vars:
                var.set(1)
            self.btn_select_all.configure(text="❎Unselect All")
            self.all_selected = True
        else:
            for var in self.check_vars:
                var.set(0)
            self.btn_select_all.configure(text="✅Select All")
            self.all_selected = False

    def open_screen_file(self, port):
        device = None
        devices = client.devices()
        for dev in devices:
            if dev.serial[-4:] == port[-4:]:
                device = dev
                break
        result = device.screencap()
        port_safe = re.sub(r'[^a-zA-Z0-9._-]', '-', port)
        filename = rf"src\image\screen\screen-{port_safe}.png"
        with open(filename, "wb") as f:
            f.write(result)
        if os.name == "nt":
            try:
                os.startfile(filename)
            except Exception as e:
                print(f"Failed to open screen: {e}")

    def open_log_file(self, log_file):
        if not os.path.exists(log_file):
            print(f"Log file not found: {log_file}")
            return
        try:
            subprocess.Popen(["notepad.exe", log_file])
        except Exception as e:
            print(f"Failed to open log: {e}")

    def open_config_file(self):
        if not os.path.exists(CONFIG_PATH):
            print(f"Config file not found: {CONFIG_PATH}")
            return
        try:
            subprocess.Popen(["notepad.exe", CONFIG_PATH])
        except Exception as e:
            print(f"Failed to open log: {e}")

    def open_config_ranger_file(self):
        if not os.path.exists(CONFIGRANGER_PATH):
            print(f"Config file not found: {CONFIGRANGER_PATH}")
            return
        try:
            subprocess.Popen(["notepad.exe", CONFIGRANGER_PATH])
        except Exception as e:
            print(f"Failed to open log: {e}")

    def open_config_gear_file(self):
        if not os.path.exists(CONFIGGEAR_PATH):
            print(f"Config file not found: {CONFIGGEAR_PATH}")
            return
        try:
            subprocess.Popen(["notepad.exe", CONFIGGEAR_PATH])
        except Exception as e:
            print(f"Failed to open log: {e}")

    def _count_files(self, folder):
        """นับจำนวนไฟล์ในโฟลเดอร์ (รวมโฟลเดอร์ย่อย)"""
        if not os.path.isdir(folder):
            return 0
        count = 0
        for _, _, files in os.walk(folder):
            count += len(files)
        return count

    def update_file_counts(self):
        """อัพเดทจำนวนไฟล์ที่แสดงใน bottom bar"""
        self.label_input_files.configure(text=f"input: {self._count_files('input')}")
        self.label_output_files.configure(text=f"output: {self._count_files('output')}")
        self.label_execute_files.configure(text=f"execute: {self._count_files('execute')}")
        self.label_backup_files.configure(text=f"backup: {self._count_files('backup')}")

    def _cleanup_empty_subdirs(self, folder):
        """ลบโฟลเดอร์ย่อยที่ว่างเปล่า (bottom-up)"""
        for root, dirs, files in os.walk(folder, topdown=False):
            # ไม่ลบโฟลเดอร์หลัก (input, output, execute, backup)
            if root == folder:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    def _start_folder_watcher(self):
        """เริ่ม thread สำหรับ watch การเปลี่ยนแปลงของโฟลเดอร์ (รวม subfolder)"""
        folders = ["input", "output", "execute", "backup"]
        for folder in folders:
            os.makedirs(folder, exist_ok=True)
        self._folder_counts = {folder: self._count_files(folder) for folder in folders}

        def watch():
            while not self._closing:
                changed = False
                for folder in folders:
                    count = self._count_files(folder)
                    if count != self._folder_counts.get(folder):
                        self._folder_counts[folder] = count
                        changed = True
                if changed:
                    try:
                        self.after(0, self.update_file_counts)
                    except Exception:
                        break
                time.sleep(2)

        watcher_thread = threading.Thread(target=watch, daemon=True)
        watcher_thread.start()

    def open_folder_input(self):
        path = "input"
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception as e:
            print(f"Failed to open {path}: {e}")

    def open_folder_output(self):
        path = "output"
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception as e:
            print(f"Failed to open {path}: {e}")

    def open_folder_execute(self):
        path = "execute"
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception as e:
            print(f"Failed to open {path}: {e}")

    def open_folder_backup(self):
        path = "backup"
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception as e:
            print(f"Failed to open {path}: {e}")

    def start_adb(self):
        self.stop_bot_processes()
        for widget in self.left_frame.winfo_children():
            widget.destroy()
        loading_frame = ctk.CTkFrame(self.left_frame, fg_color="#303030")
        loading_frame.pack(fill="x", padx=4, pady=3)
        loading_label = ctk.CTkLabel(loading_frame, text="🔍    กำลังค้นหา ADB...", width=200, anchor="w")
        loading_label.pack(side="left", padx=4)

        def background_scan():
            try:
                subprocess.run(r"src\adb\adb kill-server", shell=True, capture_output=True)
                time.sleep(0.3)
                devices = setup_emulators()
            except Exception as e:
                devices = []
                print(f"ADB scan error: {e}")
            self.after(0, lambda: self._update_emulator_ui(devices, loading_frame))

        threading.Thread(target=background_scan, daemon=True).start()

    def _update_emulator_ui(self, devices, loading_frame):
        for widget in self.left_frame.winfo_children():
            widget.destroy()
        if not devices:
            ctk.CTkLabel(self.left_frame, text="❌ ไม่พบอุปกรณ์ ADB", text_color="gray").pack(pady=10)
            return
        for i, dev in enumerate(devices):
            self.add_emulator(i, dev)
            if dev in self.bot_processes and self.bot_processes[dev].is_alive():
                if dev in self.status_labels:
                    self.status_labels[dev].configure(text="Running", text_color=whiteblue)
                if dev in self.control_buttons:
                    self.control_buttons[dev].configure(text="∣∣")
            else:
                if dev in self.status_labels:
                    self.status_labels[dev].configure(text="Stop", text_color="gray")
                if dev in self.control_buttons:
                    self.control_buttons[dev].configure(text="▶")

    def kill_server_adb(self):
        self.check_vars.clear()
        for widget in self.left_frame.winfo_children():
            widget.destroy()
        try:
            subprocess.check_output(r"src\adb\adb kill-server", shell=True)
        except Exception as e:
            print("Kill ADB failed:", e)
        ctk.CTkLabel(self.left_frame, text="❌ ไม่พบอุปกรณ์ ADB", text_color="gray").pack(pady=10)

    # -----------------------------
    # โหมด Login แบบ headless: แผงตั้งจำนวน thread + สปอว์น worker หลายโปรเซส
    # -----------------------------
    def _currentModeKey(self):
        return self.play_mode_options.get(self.play_mode_var.get())

    def _isLoginMode(self):
        return self._currentModeKey() == "ranger_api_Login"

    def _isGenIDMode(self):
        return self._currentModeKey() == "ranger_api_GenID"

    def _isStageMode(self):
        return self._currentModeKey() == "ranger_api_Stage"

    def _isHeadlessThreadMode(self):
        """โหมดที่รันแบบ headless หลาย thread (ไม่ผูก device): Login + GenID + Stage

        ทุกโหมดนี้ไม่แตะ adb/เกม: Login relogin จากไฟล์ input, GenID mint บัญชีใหม่เอง,
        Stage relogin จากไฟล์ input แล้วดันด่านผ่าน API จึงใช้แผงตั้งจำนวน thread +
        สปอว์น worker ชุดเดียวกัน (ต่างกันแค่ฟังก์ชันที่ worker เรียก)
        """
        return self._currentModeKey() in ("ranger_api_Login", "ranger_api_GenID", "ranger_api_Stage")

    def render_left_panel(self):
        """เลือกเนื้อหาแผงซ้ายตามโหมด: Login/GenID/Stage = ตั้งจำนวน thread (ไม่แตะ adb) อื่น ๆ = รายการ device"""
        if self._isHeadlessThreadMode():
            self._build_thread_panel()
        else:
            self.start_adb()

    def _build_thread_panel(self):
        # ล้างแผงซ้าย (ทั้ง device rows เดิมและ worker rows) แล้ววาดตัวตั้งจำนวน thread ใหม่
        self.check_vars.clear()
        for widget in self.left_frame.winfo_children():
            widget.destroy()

        isGen = self._isGenIDMode()
        isStage = self._isStageMode()
        header = ctk.CTkFrame(self.left_frame, fg_color="#303030")
        header.pack(fill="x", padx=4, pady=(6, 3))
        header_text = "⚙ จำนวน Thread (headless)"
        if isGen:
            header_text = "🎯 จำนวน Thread สร้างไอดี"
        elif isStage:
            header_text = "🎯 จำนวน Thread ดันด่าน"
        ctk.CTkLabel(header, text=header_text, anchor="w").pack(side="left", padx=6)

        ctrl = ctk.CTkFrame(self.left_frame, fg_color="#303030")
        ctrl.pack(fill="x", padx=4, pady=3)
        ctk.CTkButton(ctrl, text="−", width=34, fg_color="#444444", hover_color="#555555",
                      command=lambda: self._change_thread_count(-1)).pack(side="left", padx=(6, 4), pady=4)
        # ช่องพิมพ์เลขได้ (สูงสุด 1024) พิมพ์แล้ว Enter/คลิกออก = ปรับค่า ปุ่ม +/− ไว้ขยับทีละหน่วย
        self.thread_count_entry = ctk.CTkEntry(ctrl, width=64, height=28, justify="center",
                                               font=("Segoe UI", 16, "bold"))
        self.thread_count_entry.insert(0, str(self.thread_count))
        self.thread_count_entry.pack(side="left", padx=4)
        self.thread_count_entry.bind("<Return>", lambda e: self._apply_thread_count_from_entry())
        self.thread_count_entry.bind("<FocusOut>", lambda e: self._apply_thread_count_from_entry())
        ctk.CTkButton(ctrl, text="+", width=34, fg_color="#444444", hover_color="#555555",
                      command=lambda: self._change_thread_count(1)).pack(side="left", padx=4)
        ctk.CTkLabel(ctrl, text="thread (สูงสุด 1024)", text_color="gray").pack(side="left", padx=4)

        hint = "แต่ละ thread หยิบไฟล์จาก input/ แบ่งกันอัตโนมัติ"
        if isGen:
            hint = "แต่ละ thread สร้างบัญชีใหม่เอง (mint + signup) ส่งออกลง output/ ไม่กินไฟล์ input"
        elif isStage:
            hint = "แต่ละ thread หยิบไฟล์จาก input/ แบ่งกันเอง แล้วดันด่านผ่าน API (ไม่เปิดเกม)"
        ctk.CTkLabel(self.left_frame, text=hint,
                     text_color="gray", anchor="w", justify="left", wraplength=300).pack(fill="x", padx=8, pady=(2, 6))

        # สรุปสถานะ worker เป็นแถวเดียว (อัปเดตเบา ไม่วาดทีละ worker แม้มีเป็นพันตัว = ลื่น)
        self.worker_summary_label = ctk.CTkLabel(self.left_frame, text="", anchor="w",
                                                 justify="left", wraplength=300,
                                                 font=("Segoe UI", 14))
        self.worker_summary_label.pack(fill="x", padx=8, pady=(4, 6))
        self._update_worker_summary()

    def _set_thread_count(self, n):
        """ตั้งค่า thread_count (clamp 1..1024) อัปเดตช่องพิมพ์ แล้วเซฟลง config"""
        self.thread_count = max(1, min(int(n), 1024))
        if hasattr(self, "thread_count_entry") and self.thread_count_entry.winfo_exists():
            self.thread_count_entry.delete(0, "end")
            self.thread_count_entry.insert(0, str(self.thread_count))
        try:
            self.config.setdefault("settings", {})
            self.config["settings"]["threadcount"] = str(self.thread_count)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                self.config.write(f)
        except Exception as e:
            print("save threadcount failed:", e)

    def _change_thread_count(self, delta):
        self._set_thread_count(self.thread_count + delta)

    def _apply_thread_count_from_entry(self):
        """อ่านเลขจากช่องพิมพ์ ถ้าไม่ใช่ตัวเลขให้คืนค่าเดิม"""
        try:
            raw = self.thread_count_entry.get().strip()
            n = int(raw) if raw else self.thread_count
        except (ValueError, Exception):
            n = self.thread_count
        self._set_thread_count(n)

    def _worker_serials(self):
        return [f"worker-{i+1}" for i in range(self.thread_count)]

    def _safe_worker_cap(self, requested):
        """จำกัดจำนวนโปรเซสจริงตาม RAM ที่ว่าง (แต่ละ worker ~90MB) กัน OOM แม้ตั้งเลขไว้สูง

        ใช้ available physical RAM * 0.6 หาร 90MB ถ้าอ่าน RAM ไม่ได้ถอยไปเพดานปลอดภัย 64
        คืน (จำนวนที่จะรันจริง, เพดานที่คำนวณได้) เพื่อเตือนผู้ใช้เมื่อถูกจำกัด
        """
        PER_MB = 55   # worker headless (subprocess bot_worker.py) ~45MB + เผื่อโตตอนรัน
        cap = 64
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                            ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                            ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                            ("ullAvailExtendedVirtual", ctypes.c_uint64)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(ms)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                cap = max(1, int(ms.ullAvailPhys / 1048576 * 0.6 / PER_MB))
        except Exception:
            pass
        return min(requested, cap), cap

    def _update_worker_summary(self):
        """อัปเดตสรุปสถานะ worker แบบเบา (นับตัวที่ยังรัน) - ถูกกว่าวาดทีละแถว"""
        if not hasattr(self, "worker_summary_label") or not self.worker_summary_label.winfo_exists():
            return
        total = len(self.worker_procs)
        alive = sum(1 for p in self.worker_procs.values() if p.poll() is None)
        if total:
            self.worker_summary_label.configure(
                text=f"▶ กำลังรัน {alive}/{total} thread",
                text_color=whiteblue if alive else "gray")
        else:
            self.worker_summary_label.configure(text="กด ▶ Start เพื่อเริ่ม", text_color="gray")

    def _worker_env(self):
        """env ให้ worker คุม rate limit ร่วมกันทั้งเครื่อง (ดู tools/ratelimit.py):
        งบ req/s ต่อ IP, proxy แจกวนตามลำดับ worker, และโฟลเดอร์ lock file ที่ทุก worker ใช้ร่วมกัน"""
        if TOOLSDIR not in sys.path:
            sys.path.insert(0, TOOLSDIR)
        import ratelimit
        rps = self.config.get("settings", "apirps", fallback="80").strip() or "80"
        proxies = ratelimit.parse_proxies(self.config.get("settings", "apiproxies", fallback=""))
        # ตรวจค่าตรงนี้ ไม่งั้น worker (CREATE_NO_WINDOW) จะตายเงียบตอน import ratelimit
        # และผู้ใช้เห็นแค่ "0/N thread" โดยไม่รู้สาเหตุ -> ใช้ค่าเริ่มต้นแทนแล้วเตือนครั้งเดียว
        bad = []
        try:
            float(rps)
        except ValueError:
            bad.append("apirps = %r (ต้องเป็นตัวเลข เช่น 80)" % rps)
            rps = "80"
        good_proxies = []
        for proxy in proxies:
            try:
                ratelimit.proxy_parts(proxy)
                good_proxies.append(proxy)
            except ValueError:
                bad.append("apiproxies: %r (ต้องเป็น host:port หรือ host:port:user:pass)" % proxy)
        if bad and not self._warned_api_config:
            self._warned_api_config = True
            messagebox.showwarning("config.ini", "ค่าตั้ง rate limit ผิดรูปแบบ ใช้ค่าเริ่มต้นแทน:\n" + "\n".join(bad))
        index = self._worker_seq
        self._worker_seq += 1
        # _APP_ROOT/.ratelimit (TOOLSDIR = _APP_ROOT/tools): รากของ repo ตอนรันจากซอร์ส, ข้าง exe ตอน
        # frozen. ใช้ __file__ ไม่ได้เพราะ PyInstaller onefile ชี้ไป temp ต่อการเปิด -> GUI สองตัว
        # ไม่แชร์ bucket และโฟลเดอร์หายตอนโปรแกรมปิด
        rl_dir = self._rl_dir()
        env = ratelimit.spawn_env(os.environ, rps, good_proxies, index, rl_dir)
        env["LGRGS_CC_FILE"] = os.path.join(rl_dir, "cc.txt")   # cc ร่วมที่ GUI mint ไว้ (ดู _prepare_shared_cc)
        return env

    @staticmethod
    def _rl_dir():
        return os.path.join(os.path.dirname(TOOLSDIR), ".ratelimit")

    def _prepare_shared_cc(self):
        """mint guest cc หนึ่งตัวใน GUI แล้วเก็บลงไฟล์ร่วม ให้ worker ทุกตัวใช้แทนการ mint เอง

        game-api.line.me ให้ mint ได้แค่ 2 ครั้ง/นาที/IP (วัด 2026-09-23) ถ้า worker 16 ตัว mint พร้อมกัน
        จะล้มเกือบหมด ("guest mint failed") cc ตัวเดียวใช้ได้กับทุกบัญชี จึง mint ที่นี่ครั้งเดียว
        (ใช้ของเดิมในไฟล์ถ้าอายุไม่เกิน 10 นาที) worker renew ผ่านไฟล์เดียวกันเมื่อโดน 401
        """
        if TOOLSDIR not in sys.path:
            sys.path.insert(0, TOOLSDIR)
        import relogin
        try:
            relogin.CcPool(share_file=os.path.join(self._rl_dir(), "cc.txt"), max_age=600)
            return True
        except Exception as e:
            messagebox.showerror("mint guest ไม่สำเร็จ",
                                 f"ขอ cc จาก LINE ไม่ได้: {e}\n\n"
                                 "ถ้าเป็น HTTP 429 ให้รอ 1 นาทีแล้วกดเริ่มใหม่ (โควตา 2 ครั้ง/นาที/IP)")
            return False

    def _spawn_worker(self, device, mode="ranger_api_Login"):
        """สปอว์น 1 worker เป็น subprocess ของ bot_worker.py (ไม่ re-import main = ไม่โหลด GUI)

        subprocess แทน multiprocessing เพราะบน Windows multiprocessing spawn จะ re-import main.py
        (มี class EmulatorManager(ctk.CTk) ระดับ module) ทำให้ทุก worker โหลด customtkinter+u2 (~59MB)
        subprocess ของไฟล์เบา bot_worker.py -> ~30-45MB/worker -> รันเป็นพันตัวได้

        mode บอก worker ว่าจะรัน Login (relogin จากไฟล์) หรือ GenID (mint บัญชีใหม่) headless
        """
        botdir = os.path.dirname(os.path.abspath(__file__))
        no_window = 0x08000000  # CREATE_NO_WINDOW: ไม่เด้ง console ต่อ worker (สำคัญตอนมีพันตัว)
        if getattr(sys, 'frozen', False):
            # frozen: exe รันสคริปต์ .py ไม่ได้ -> re-exec exe ในโหมด --worker (main.py __main__ จัดการ)
            args = [sys.executable, "--worker", device, mode]
        else:
            args = [sys.executable, os.path.join(botdir, "bot_worker.py"), device, mode]
        return subprocess.Popen(args, cwd=botdir, creationflags=no_window, env=self._worker_env())

    def _monitor_workers(self):
        """ตัวจับเวลาตัวเดียวคุมทุก worker (แทน monitor ต่อโปรเซส) - ลื่นแม้มีเป็นพันตัว"""
        for dev in [d for d, p in list(self.worker_procs.items()) if p.poll() is not None]:
            self.worker_procs.pop(dev, None)
        self._update_worker_summary()
        if self.worker_procs:
            self._worker_monitor_job = self.after(1000, self._monitor_workers)
        else:
            self._worker_monitor_job = None

    def _start_workers(self):
        self.save_config()
        if not self.verify_subscription_sync():
            return
        readConfigFile()

        # หยุด worker เก่าก่อน (กัน spawn ซ้อน)
        self._stop_workers(silent=True)

        # โหมดปัจจุบัน (Login = relogin จาก input, GenID = mint บัญชีใหม่) worker ใช้ค่านี้เลือกฟังก์ชัน
        mode_key = self._currentModeKey() or "ranger_api_Login"
        # Login/Stage ใช้ cc ร่วมตัวเดียว (mint ที่นี่) GenID mint ต่อบัญชีเองผ่านคิวโควตาใน tools/
        if mode_key != "ranger_api_GenID" and not self._prepare_shared_cc():
            return

        # รันตามจำนวนที่ตั้งไว้เต็ม ๆ (ปลด cap ตาม RAM แล้ว) - แค่เตือนถ้าเกินที่ RAM น่าจะรับไหว
        run_count = self.thread_count
        _fit, cap = self._safe_worker_cap(self.thread_count)
        if run_count > cap:
            print(f"เตือน: รัน {run_count} thread แต่ RAM น่าจะรับไหวราว ~{cap} "
                  f"(แต่ละ worker ~45MB) เสี่ยงหน่วยความจำหมด/ช้า", flush=True)
        serials = [f"worker-{i+1}" for i in range(run_count)]
        # Login แบ่งไฟล์ input/ ให้แต่ละ worker + ล้าง lock ค้าง; GenID สร้างบัญชีใหม่เอง ไม่กินไฟล์ input
        if mode_key != "ranger_api_GenID":
            note_file_in_folder(serials)
        self._update_worker_summary()

        def start_with_delay(i):
            if i >= len(serials):
                return
            dev = serials[i]
            try:
                self.worker_procs[dev] = self._spawn_worker(dev, mode_key)
            except Exception as e:
                print(f"spawn worker {dev} failed: {e}", flush=True)
            self._update_worker_summary()
            # stagger การเริ่ม เพื่อไม่ให้ยิง login พร้อมกันทั้งหมด (กันเซิร์ฟเวอร์ rate-limit)
            self.after(int(timeInterval) if timeInterval else 300, lambda: start_with_delay(i + 1))

        start_with_delay(0)
        # ตัวจับเวลาตัวเดียวคุมทุก worker
        if getattr(self, "_worker_monitor_job", None) is None:
            self._monitor_workers()

    def _stop_workers(self, silent=False):
        stopped = []
        for dev, p in list(self.worker_procs.items()):
            if p.poll() is None:
                try:
                    p.terminate()
                    stopped.append(dev)
                except Exception:
                    pass
            self.worker_procs.pop(dev, None)
        job = getattr(self, "_worker_monitor_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._worker_monitor_job = None
        self._update_worker_summary()
        if not silent and not stopped:
            print("No running workers to stop.")

    def monitor_bot(self, dev, p):
        if p.is_alive():
            self.after(1000, lambda: self.monitor_bot(dev, p))
        else:
            if dev in self.bot_processes:
                del self.bot_processes[dev]
            if dev in self.control_buttons:
                self.control_buttons[dev].configure(text="▶")
            if dev in self.status_labels:
                self.status_labels[dev].configure(text="Stop", text_color="gray")

    def check_for_update(self):
        """Kickoff เช็คเวอร์ชันใน background thread (non-blocking)"""
        threading.Thread(target=self._check_for_update_worker, daemon=True).start()

    def _check_for_update_worker(self):
        try:
            res = requests.get(VERSION_URL, timeout=30)
            res.raise_for_status()
            data = res.json()
            latest_version = data.get("version")
        except Exception as e:
            print(f"Error checking update: {e}")
            return
        self.after(0, lambda: self._on_update_check_result(latest_version))

    def _on_update_check_result(self, latest_version):
        if not latest_version or latest_version == CURRENT_VERSION:
            return
        self.aad_update_indicator()
        msg = f"มีเวอร์ชันใหม่ {latest_version}\n\nคุณต้องการอัปเดตหรือไม่?"
        if messagebox.askyesno("🔔 Update Available", msg):
            messagebox.showinfo("Updater", "กรุณาปิดโปรแกรม และไปรัน updater.exe เพื่อติดตั้งอัปเดต")
            self.on_close()

    def start_server_render(self):
        """Kickoff verify subscription ใน background thread (non-blocking UI)"""
        try:
            self.sub_button.configure(text="⏱ ...")
        except Exception:
            pass
        threading.Thread(target=self._server_render_worker, daemon=True).start()

    def _server_render_worker(self):
        """
        ทำงาน network บน background thread ห้ามแตะ widget โดยตรง
        คืนผลเป็น dict action ให้ main thread ผ่าน self.after(0, ...)
        """
        global _user_secret
        try:
            readConfigFile()

            if USERNAME in WHITELIST_EMAILS:
                self.after(0, lambda: self._on_server_render_result({"action": "whitelist"}))
                return

            try:
                requests.get(API_URL, timeout=30)
            except Exception:
                self.after(0, lambda: self._on_server_render_result({"action": "api_down"}))
                return

            _user_secret = fetch_user_secret(USERNAME)

            payload = {
                "username": USERNAME,
                "device_id": DEVICE_ID,
                "hwid": MACHINE_HWID,
                "bot_version": CURRENT_VERSION,
                "exe_hash": EXE_HASH,
                "update_device": True,
            }
            if _user_secret:
                payload.update(sign_request(USERNAME, _user_secret))

            print(f"📤 Sending to {API_URL}/check-subscription")
            res = requests.post(API_URL + "/check-subscription", json=payload, timeout=30)
            print(f"📥 Response status: {res.status_code}")
            print(f"📥 Response text: {res.text[:200]}")
            data = res.json()
            self.after(0, lambda d=data: self._on_server_render_result({"action": "response", "data": d}))
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Network error: {e}")
            self.after(0, lambda em=str(e): self._on_server_render_result({"action": "network_error", "msg": em}))
        except Exception as e:
            print(f"⚠️ Error in _server_render_worker: {e}")
            self.after(0, lambda em=str(e): self._on_server_render_result({"action": "error", "msg": em}))

    def _on_server_render_result(self, result):
        """Run on main thread — update UI / show dialogs / kick off token refresh + SSE"""
        global Authorized, AuthorizedFailed, AllowedModes, ActiveServices
        global _session_token

        action = result.get("action")

        if action == "whitelist":
            print(f"✅ Whitelist email detected: {USERNAME}")
            Authorized = True
            AuthorizedFailed = 0
            AllowedModes = list(ALL_PLAY_MODE_OPTIONS.values())
            ActiveServices = [{
                "service_id": "whitelist",
                "service_name": "Full Access (Whitelist)",
                "allowed_modes": AllowedModes,
            }]
            self.update_play_mode_dropdown(AllowedModes)
            self.sub_button.configure(text="⏱ VIP")
            return

        if action == "api_down":
            print("⚠️ ไม่สามารถเชื่อมต่อ API ได้ - กำลังเปิดหน้าเว็บ...")
            webbrowser.open(API_URL)
            messagebox.showwarning(
                "Server กำลังเริ่มต้น",
                "🌐 Server กำลังเริ่มต้นระบบ\n\n"
                "กรุณารอสักครู่แล้วกดปุ่ม Start Bot อีกครั้ง\n\n"
                "(หน้าเว็บจะเปิดขึ้นมาเพื่อปลุก Server)"
            )
            return

        if action in ("network_error", "error"):
            return

        if action != "response":
            return

        data = result.get("data") or {}
        if data.get("status") != "ok":
            error_msg = data.get('message', 'Unknown error')
            status = data.get('status', 'error')
            print(f"⚠️ Subscription check: {error_msg}")

            if error_msg in ["ไม่พบอีเมลผู้ใช้นี้", "อีเมลผู้ใช้นี้โดนแบน"]:
                reset_config_email()
                messagebox.showwarning("Verify", f"❌ {error_msg}")
                self.on_close()
                return

            if status == "locked":
                self.sub_button.configure(text="⏱ 🔒")
                messagebox.showwarning("Device Locked", f"🔒 {error_msg}\n\nกรุณาปิดโปรแกรมบนอุปกรณ์อื่นก่อน")
                return

            if status == "kicked_by_new_login":
                self._handle_kicked({"reason": "new_login", "via": "startup_check", "message": error_msg})
                return

            if error_msg in ["ไม่มีข้อมูลการเช่า", "ข้อมูลไม่ครบ"]:
                self.sub_button.configure(text="⏱ ไม่มี")
                print(f"⚠️ {error_msg} - กรุณาติดต่อแอดมินเพื่อสมัครใช้งาน")
            return

        Authorized = True
        AuthorizedFailed = 0

        if data.get("token"):
            _session_token = data["token"]
            print(f"🔐 JWT token received")
            self._start_token_refresh()
            _start_sse_listener(self)

        AllowedModes = data.get("allowed_modes", [])
        ActiveServices = data.get("active_services", [])

        if AllowedModes:
            self.update_play_mode_dropdown(AllowedModes)

        service_names = [s.get("service_name", s.get("service_id")) for s in ActiveServices]
        if service_names:
            print(f"✅ Services ที่สมัคร: {', '.join(service_names)}")

        self.update_subscription_button(data.get("remaining", ""))

    def verify_subscription_sync(self):
        """ตรวจสอบ subscription แบบ synchronous สำหรับการกดปุ่ม Start Bot"""
        global Authorized, AuthorizedFailed, AllowedModes, ActiveServices, CHOICE
        global _session_token, _user_secret
        try:
            readConfigFile()

            # ✅ เช็ค whitelist - ไม่ต้อง verify subscription
            if USERNAME in WHITELIST_EMAILS:
                selected_mode = self.play_mode_options.get(self.play_mode_var.get(), "AutoSetup")
                CHOICE = selected_mode
                print(f"✅ Whitelist email: {USERNAME} - Full access granted")
                Authorized = True
                AuthorizedFailed = 0
                return True

            # ดึงโหมดที่เลือกอยู่
            selected_mode = self.play_mode_options.get(self.play_mode_var.get(), "AutoSetup")
            CHOICE = selected_mode

            # สำหรับ composite mode: ส่ง prerequisite ตัวแรกไป verify กับ server แทน
            # เพราะ server ยังไม่รู้จัก composite mode (user ถือ subscription แยกกัน)
            verify_mode = selected_mode
            if selected_mode in COMPOSITE_MODE_REQUIREMENTS:
                prereqs = COMPOSITE_MODE_REQUIREMENTS[selected_mode]
                # เลือก prerequisite ตัวแรกที่อยู่ใน AllowedModes
                for req in prereqs:
                    if req in AllowedModes:
                        verify_mode = req
                        break

            payload = {
                "username": USERNAME,
                "device_id": DEVICE_ID,
                "hwid": MACHINE_HWID,
                "mode": verify_mode,
                "bot_version": CURRENT_VERSION,
                "exe_hash": EXE_HASH,
            }

            # 🔐 Add HMAC signature
            if _user_secret:
                payload.update(sign_request(USERNAME, _user_secret))

            res = requests.post(API_URL + "/check-subscription",
                json=payload,
                headers=get_auth_headers(),
                timeout=30)
            data = res.json()

            # ตรวจสอบกรณี mode ไม่ได้รับอนุญาต
            if data["status"] == "mode_not_allowed":
                allowed = data.get("allowed_modes", [])
                self.update_play_mode_dropdown(allowed)
                messagebox.showwarning("โหมดไม่ได้รับอนุญาต",
                    f"❌ {data['message']}\n\nกรุณาเลือกโหมดอื่นที่อนุญาต")
                return False

            # ตรวจสอบกรณีมีการใช้งานอยู่บนอุปกรณ์อื่น
            if data["status"] == "locked":
                self.sub_button.configure(text="⏱ 🔒")
                messagebox.showwarning("Device Locked",
                    f"🔒 {data['message']}\n\nกรุณาปิดโปรแกรมบนอุปกรณ์อื่นก่อน")
                return False

            # กรณีถูกเครื่องใหม่ login ซ้อน (fallback เมื่อ SSE ไม่ได้แจ้งก่อน)
            if data["status"] == "kicked_by_new_login":
                self._handle_kicked({
                    "reason": "new_login",
                    "via": "start_bot_check",
                    "message": data.get("message", ""),
                })
                return False

            # ตรวจสอบ auth errors (HMAC/JWT)
            if data["status"] in ["auth_error", "token_expired"]:
                print(f"🔐 Auth error: {data.get('message')}")
                _session_token = None
                messagebox.showwarning("Auth Error", f"❌ {data.get('message', 'Authentication failed')}\n\nกรุณาเปิดโปรแกรมใหม่")
                self.on_close()
                return False

            if data["status"] != "ok":
                error_msg = data.get('message', 'Unknown error')
                print(f"❌ {error_msg}")

                # รีเซ็ต email และปิดแอปเฉพาะกรณี user ไม่มีในระบบหรือโดนแบน
                if error_msg in ["ไม่พบอีเมลผู้ใช้นี้", "อีเมลผู้ใช้นี้โดนแบน"]:
                    reset_config_email()
                    messagebox.showwarning("Verify", f"❌ {error_msg}")
                    self.on_close()
                    return False

                # กรณีอื่นๆ แค่แจ้งเตือน ไม่ปิดแอป
                messagebox.showwarning("Verify", f"❌ {error_msg}")
                return False

            print(f"{datetime.now().strftime('%H:%M:%S')} ✅ Authorized")
            Authorized = True
            AuthorizedFailed = 0

            # 🔐 Update JWT token if provided
            if data.get("token"):
                _session_token = data["token"]

            # อัปเดต allowed modes และ active services
            AllowedModes = data.get("allowed_modes", [])
            ActiveServices = data.get("active_services", [])

            # อัปเดต dropdown ถ้ามีการเปลี่ยนแปลง
            if AllowedModes:
                self.update_play_mode_dropdown(AllowedModes)

            # ✅ อัปเดตข้อความปุ่ม subscription
            self.update_subscription_button(data.get("remaining", ""))
            return True
        except Exception as e:
            print("⚠️ Network error:", e)
            # ถ้าเคย Authorized แล้ว ให้ผ่านได้
            if Authorized:
                return True
            messagebox.showwarning("Network error", f"❌ ไม่สามารถเชื่อมต่อเซิฟเวอร์ได้\nตรวจสอบอินเตอร์เน็ต และ ลองอีกครั้ง")
            return False

    def verify_subscription(self):
        """ตรวจสอบ subscription แบบ periodic ทุก 5 นาที (เข้มงวดขึ้น)"""
        global Authorized, AuthorizedFailed, AllowedModes, ActiveServices
        global _session_token
        try:
            readConfigFile()

            # ✅ เช็ค whitelist - ไม่ต้อง verify subscription
            if USERNAME in WHITELIST_EMAILS:
                print(f"{datetime.now().strftime('%H:%M:%S')} ✅ Whitelist email: {USERNAME}")
                Authorized = True
                AuthorizedFailed = 0
                self.after(1800000, self.verify_subscription)  # ตรวจสอบทุกๆ 30 นาที
                return

            payload = {
                "username": USERNAME,
                "device_id": DEVICE_ID,
                "hwid": MACHINE_HWID,
                "bot_version": CURRENT_VERSION,
                "exe_hash": EXE_HASH,
                "update_device": False  # ✅ การตรวจสอบ periodic ไม่อัปเดต device_id
            }

            # 🔐 Add HMAC signature
            if _user_secret:
                payload.update(sign_request(USERNAME, _user_secret))

            res = requests.post(API_URL + "/check-subscription",
                json=payload,
                headers=get_auth_headers(),
                timeout=30)
            data = res.json()

            if data["status"] == "kicked_by_new_login":
                # polling fallback กรณี SSE หลุด — ปฏิบัติเหมือนได้ event kicked
                self._handle_kicked({
                    "reason": "new_login",
                    "via": "polling_fallback",
                    "message": data.get("message", ""),
                })
                return

            if data["status"] in ["auth_error", "token_expired"]:
                print(f"🔐 Auth error in heartbeat: {data.get('message')}")
                _session_token = None
                self.stop_bot_processes()
                self.kill_server_adb()
                self.after(10000, self.on_close)
                messagebox.showwarning("Auth Error", f"❌ {data.get('message', 'Session expired')}\n\nกรุณาเปิดโปรแกรมใหม่")
                self.on_close()
                return

            if data["status"] != "ok":
                if data['message'] in ["ข้อมูลไม่ครบ", "ไม่พบอีเมลผู้ใช้นี้", "อีเมลผู้ใช้นี้โดนแบน", "ไม่มีข้อมูลการเช่า"]:
                    reset_config_email()

                print(f"❌ {data.get('message', 'Unknown error')}")
                self.stop_bot_processes()
                self.kill_server_adb()
                self.after(10000, self.on_close)
                messagebox.showwarning("Verify", f"❌ {data.get('message', 'Unknown error')}")
                self.on_close()
                return

            print(f"{datetime.now().strftime('%H:%M:%S')} ✅ Authorized")
            Authorized = True
            AuthorizedFailed = 0

            # 🔐 Update JWT token if provided
            if data.get("token"):
                _session_token = data["token"]

            # อัปเดต allowed modes และ active services
            AllowedModes = data.get("allowed_modes", [])
            ActiveServices = data.get("active_services", [])

            # ✅ อัปเดตข้อความปุ่ม subscription
            self.update_subscription_button(data.get("remaining", ""))

            # ตรวจสอบทุกๆ 30 นาที (1800000 ms)
            self.after(1800000, self.verify_subscription)
        except Exception as e:
            # 🔐 เข้มงวดขึ้น: fail 2 ครั้ง = หยุด (จากเดิม 8 ครั้ง)
            if (not Authorized and AuthorizedFailed >= 6) or AuthorizedFailed >= 7:
                print("⚠️ Network error:", e)
                self.stop_bot_processes()
                self.kill_server_adb()
                self.after(10000, self.on_close)
                messagebox.showwarning("Network error", f"❌ ไม่สามารถเชื่อมต่อเซิฟเวอร์ได้\nตรวจสอบอินเตอร์เน็ต และ ลองอีกครั้ง")
                self.on_close()
            AuthorizedFailed += 1
            print(
                f"{datetime.now().strftime('%H:%M:%S')} AuthorizedFailed:", AuthorizedFailed)
            # ตรวจสอบทุกๆ 30 นาที
            self.after(1800000, self.verify_subscription)

    def _start_token_refresh(self):
        """Start background JWT token refresh (every 60 minutes)"""
        def _refresh():
            if refresh_session_token():
                print(f"{datetime.now().strftime('%H:%M:%S')} 🔐 Token refreshed")
            else:
                print(f"{datetime.now().strftime('%H:%M:%S')} ⚠️ Token refresh failed")
            # Schedule next refresh in 60 minutes (3600000 ms)
            self.after(3600000, _refresh)
        # First refresh in 60 minutes
        self.after(3600000, _refresh)

    def update_subscription_button(self, remaining_text: str):
        """อัปเดตข้อความบนปุ่ม ⏱ ให้แสดงจำนวนวัน / ชั่วโมง / นาที"""
        days, hours, minutes = 0, 0, 0
        try:
            if "วัน" in remaining_text:
                days = int(remaining_text.split("วัน")[0].strip())
            if "ชม." in remaining_text:
                hours_part = remaining_text.split("วัน")[-1]
                hours = int(hours_part.split("ชม.")[0].strip())
            if "นาที" in remaining_text:
                minutes_part = remaining_text.split(
                    "ชม.")[-1] if "ชม." in remaining_text else remaining_text.split("วัน")[-1]
                minutes = int(minutes_part.replace("นาที", "").strip())
        except ValueError:
            pass

        # ✅ เงื่อนไขการแสดงผล
        if days > 999:
            display = "⏱ 999 วัน"
        elif days >= 1:
            display = f"⏱ {days} วัน"
        elif hours >= 1:
            display = f"⏱ {hours} ชม."
        else:
            display = f"⏱ {minutes} นาที"

        self.sub_button.configure(text=display)


def open_facebook():
    url = "https://www.facebook.com/profile.php?id=100052636535265"
    # url = API_URL
    webbrowser.open(url)

def open_rangers_book():
    url = "https://rangers.lerico.net/en/rangers-book"
    webbrowser.open(url)

def open_gear_book():
    url = "https://rangers.lerico.net/en/equipments-book"
    webbrowser.open(url)


def run_bot(device, choice):
    """target ของ worker process - ไม่เขียน log ไฟล์แล้ว

    กลบ stdout/stderr ทิ้งลง devnull: รันหลายร้อยโปรเซสพร้อมกัน ถ้าปล่อยพ่นเข้า console เดียว
    จะรกและปนกัน (แบบ error OpenBLAS ที่เห็นก่อนหน้า) ไม่มี console ก็ยังพังตอน print
    """
    try:
        # errors="replace": devnull ใช้ encoding พื้นฐาน (cp1252 บน Windows) พอ print ไทย/emoji
        # จะโยน UnicodeEncodeError กลาง flow (แม้จะทิ้งลง devnull) แล้ว worker พังเงียบ ๆ
        devnull = open(os.devnull, "w", encoding="utf-8", errors="replace")
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        pass
    try:
        if choice == "ranger_api_Login":
            startBotLogin_API_headless(device)   # headless แท้: mint LF_AC เองจากไฟล์ ไม่เปิดเกม/ไม่ต่อ adb
        elif choice == "ranger_api_GenID":
            startBotGenID_API_headless(device)   # headless แท้: mint บัญชีใหม่ผ่าน signup ไม่เปิดเกม/ไม่ต่อ adb
        elif choice == "ranger_api_Stage":
            startBotStage_API_headless(device)   # headless แท้: relogin จากไฟล์ แล้วดันด่านผ่าน API
        elif choice == "AutoSetup":
            startBotCheckGameInfo_API(device)
    except Exception:
        pass



def run_auto_setup_with_log(device, log_file):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    f = open(log_file, "w", buffering=1, encoding="utf-8")
    sys.stdout = f
    sys.stderr = f
    try:
        autoSetUp(device)
    except Exception as e:
        print("Error:", e, flush=True)
    finally:
        f.close()

def get_device_ID():
    global DEVICE_ID
    if DEVICE_ID == "":
        device_ID = ""
        device_ID += os.getenv("COMPUTERNAME") + "-"
        # Get Device ID (different methods for different OS)
        try:
            # For Linux - use machine-id
            if os.path.exists("/etc/machine-id"):
                with open("/etc/machine-id", "r") as f:
                    device_ID +=  f.read().strip()
            elif os.path.exists("/var/lib/dbus/machine-id"):
                with open("/var/lib/dbus/machine-id", "r") as f:
                    device_ID +=  f.read().strip()
            else:
                # Windows alternative using wmic
                result = subprocess.run(["wmic", "csproduct", "get", "UUID"], capture_output=True, text=True,
                                        encoding="utf-8", errors="ignore")
                device_ID += result.stdout.strip().replace("\n", "").replace(" ", "").replace("UUID", "")
        except Exception as e:
            print("Error getting Device ID:", e)
        DEVICE_ID = device_ID
        print("DEVICE_ID:", DEVICE_ID)
        return device_ID

def readConfigFile():
    global USERNAME, timeInterval, CHOICE
    get_device_ID()  # ตั้งค่า DEVICE_ID ก่อนใช้งาน
    config = configparser.ConfigParser()

    # อ่านไฟล์ config
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config.read_file(f)

    timeInterval = config.getfloat("settings", "timeInterval") * 1000
    USERNAME = config.get("login", "email")
    CHOICE = config.get("mode", "playmode")

    # ถ้า gmail ยังเป็นค่า default "email" ให้ถามแล้วบันทึก
    if USERNAME.strip().lower() == "email" or USERNAME.strip().lower() == "gmail" or USERNAME.strip() == "":
        email = ask_for_email()
        if email:
            USERNAME = email
            config.set("login", "email", USERNAME)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                config.write(f)
            print(f"✅ บันทึก email ลง config.ini เรียบร้อย: {USERNAME}")
            return True
        else:
            print("❌ ผู้ใช้ยกเลิกการกรอกอีเมล")
            return False
    else:
        return True


def reset_config_email():
    """รีเซ็ตค่า email ใน config.ini กลับเป็นค่าเริ่มต้น ('email')"""
    config = configparser.ConfigParser()

    # ตรวจสอบว่ามีไฟล์ config หรือไม่
    if not os.path.exists(CONFIG_PATH):
        print("⚠️ ไม่พบไฟล์ config.ini — กำลังสร้างไฟล์ใหม่...")
        config["login"] = {"email": "email"}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            config.write(f)
        print("✅ สร้าง config.ini ใหม่สำเร็จ")
        return True

    try:
        # อ่านไฟล์ config ที่มีอยู่
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config.read_file(f)

        # ถ้าไม่มี section [login] ให้สร้างใหม่
        if "login" not in config:
            config.add_section("login")

        # ตั้งค่า email เป็นค่าเริ่มต้น
        config.set("login", "email", "email")

        # เขียนกลับลงไฟล์
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            config.write(f)

        print("✅ รีเซ็ตอีเมลใน config.ini เรียบร้อย")
        return True

    except Exception as e:
        print(f"❌ รีเซ็ต config ล้มเหลว: {e}")
        return False


def ask_for_email():
    class EmailDialog(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.title("เข้าสู่ระบบ")
            self.geometry("400x200+800+400")
            self.configure(fg_color=dark)
            self.resizable(False, False)
            self.email = None

            ctk.CTkLabel(self, text="กรุณากรอกอีเมลของคุณ:",
                         text_color=whiteblue, font=("Segoe UI", 14)).pack(pady=20)

            self.entry = ctk.CTkEntry(self, width=300, font=("Segoe UI", 12))
            self.entry.pack(pady=10)
            self.entry.focus()

            btn_frame = ctk.CTkFrame(self, fg_color="transparent")
            btn_frame.pack(pady=10)

            ctk.CTkButton(btn_frame, text="✅ ตกลง", width=90,
                          command=self.on_ok, fg_color=blue, hover_color=darkblue).pack(side="left", padx=10)

            ctk.CTkButton(btn_frame, text="❌ ยกเลิก", width=90,
                          command=self.on_cancel, fg_color=grey, hover_color=darkgrey).pack(side="left", padx=10)

            self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        def on_ok(self):
            value = self.entry.get().strip()
            if not value:
                messagebox.showwarning("คำเตือน", "กรุณากรอกอีเมลก่อนเข้าใช้งาน!")
                return
            if "@" not in value or "." not in value:
                messagebox.showwarning("รูปแบบอีเมลไม่ถูกต้อง", "โปรดกรอกอีเมลให้ถูกต้อง เช่น example@gmail.com")
                return
            self.email = value
            self.destroy()

        def on_cancel(self):
            self.destroy()
            sys.exit(0)

    dialog = EmailDialog()
    dialog.mainloop()
    return dialog.email


def ensure_required_folders():
    """ตรวจสอบและสร้างโฟลเดอร์ที่จำเป็น"""
    required_folders = [
        "input",
        "output",
        "execute",
        "backup",
        "login failed"
    ]
    for folder in required_folders:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
            print(f"✅ สร้างโฟลเดอร์: {folder}")



def note_file_in_folder(selected_devices: list):
    if not selected_devices:
        print("No emulator selected!")
        return

    split_ID_folder = "src\\split-ID"
    if not os.path.exists(split_ID_folder):
        os.makedirs(split_ID_folder, exist_ok=True)
    else:
        # ลบไฟล์เก่าในโฟลเดอร์ก่อน
        for old_file in os.listdir(split_ID_folder):
            old_filepath = os.path.join(split_ID_folder, old_file)
            if os.path.isfile(old_filepath):
                os.remove(old_filepath)

    # รวบรวมไฟล์ .xml ทั้งหมดจากโฟลเดอร์ input (รวมโฟลเดอร์ย่อย)
    xml_files = []
    for root, dirs, files in os.walk("input"):
        for file in files:
            if file.endswith(".xml"):
                # เก็บ relative path จาก input/ เช่น "subfolder/file.xml"
                rel_path = os.path.relpath(os.path.join(root, file), "input")
                xml_files.append(rel_path)
    
    # คำนวณการแบ่งไฟล์ให้แต่ละ device
    num_devices = len(selected_devices)
    num_files = len(xml_files)
    
    if num_devices == 0:
        print("ไม่มี device ที่เลือก")
        return
    
    # คำนวณจำนวนไฟล์ต่อ device
    base_count = num_files // num_devices  # จำนวนพื้นฐานต่อ device
    extra = num_files % num_devices  # จำนวนที่เหลือต้องแจกเพิ่ม
    
    # แบ่งไฟล์และเขียนลงในแต่ละ device file
    start_idx = 0
    for i, device in enumerate(selected_devices):
        # device แรกๆ จะได้รับไฟล์เพิ่ม 1 ไฟล์ (ถ้ามีเศษ)
        count = base_count + (1 if i < extra else 0)
        device_xml_files = xml_files[start_idx:start_idx + count]
        start_idx += count
        
        # แปลง : เป็น _ สำหรับชื่อไฟล์
        filename = device.replace(":", "_") + ".txt"
        filepath = os.path.join(split_ID_folder, filename)
        
        # เขียนชื่อไฟล์ .xml ลงในไฟล์ device
        with open(filepath, "w", encoding="utf-8") as f:
            for xml_file in device_xml_files:
                f.write(xml_file + "\n")
        
        print(f"{device} = {count} ไฟล์")

if __name__ == "__main__":
    # โหมด worker (เฉพาะ frozen exe ที่รันสคริปต์ .py ไม่ได้): รัน Login headless แล้วออก ไม่เปิด GUI
    # dev รันผ่าน bot_worker.py โดยตรง จึงไม่เข้าเงื่อนไขนี้
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        try:
            from bot_worker import run_worker
            _mode = sys.argv[3] if len(sys.argv) > 3 else "ranger_api_Login"
            run_worker(sys.argv[2], _mode)
        finally:
            sys.exit(0)

    # ===== Runtime Protection Checks =====
    if _HAS_PROTECTION:
        # Snapshot module hashes for integrity monitoring
        snapshot_module_hashes([
            'config_secure', 'hwid', 'protection',
            'botLineRanger', 'ADB',
        ])

        # Register critical functions for tamper detection
        register_critical_function(sign_request)
        register_critical_function(fetch_user_secret)
        register_critical_function(refresh_session_token)

        # Run initial protection checks (only when running as .exe)
        if getattr(sys, 'frozen', False):
            _prot_result = run_protection_checks()
            if not _prot_result.passed:
                # Silent exit - don't reveal what was detected
                sys.exit(0)

            # Start background guard (checks every 2 minutes)
            def _on_protection_threat(result):
                """Handle threat detected during runtime"""
                os._exit(0)

            start_background_guard(
                interval_seconds=120,
                on_threat=_on_protection_threat
            )

    # ===== เรียกถามอีเมลก่อนเปิดโปรแกรม =====
    if readConfigFile():
        # ===== ตรวจสอบและสร้างโฟลเดอร์ที่จำเป็น =====
        ensure_required_folders()

        multiprocessing.freeze_support()
        multiprocessing.set_start_method("spawn", force=True)
        if getattr(sys, 'frozen', False):  # ✅ รันจาก exe
            multiprocessing.set_executable(sys.executable)

        app = EmulatorManager()
        app.mainloop()
    

