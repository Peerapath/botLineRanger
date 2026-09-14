import requests
import zipfile
import os
import sys
import time
import psutil
import configparser

# --------------------------
# Path ของโปรแกรม
# --------------------------
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)  # exe mode
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

TEMP_FILE = os.path.join(APP_DIR, "update.zip")

# 👉 URL Release zip จาก GitHub
DOWNLOAD_URL = "https://github.com/Peerapath/botLineRanger/releases/download/a0.0.1/BotLineRanger.zip"

CONFIG_URL = "https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/config.ini"
CONFIG_PATH = os.path.join(APP_DIR, "src", "config.ini")

CONFIGRANGER_URL = "https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/configRanger.ini"
CONFIGRANGER_PATH = os.path.join(APP_DIR, "src", "configRanger.ini")

# --------------------------
# รายชื่อโปรแกรมที่ต้องปิดก่อนอัปเดต
# --------------------------
TARGET_PROCESSES = [
    "BotLineRanger.exe",
    "adb.exe"
]



def download_default_configRanger():
    """โหลด configRanger.ini จาก GitHub (ตัวเต็มจากลิงก์)"""
    try:
        r = requests.get(CONFIGRANGER_URL, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"❌ Cannot download default configRanger.ini: {e}")
        return None


def repair_or_create_configRanger():
    print("======================")
    print("Checking configRanger.ini ...")

    # โหลด config ต้นฉบับจาก GitHub
    default_data = download_default_configRanger()
    if not default_data:
        print("⚠ Cannot repair configRanger.ini (download failed).")
        return

    # ถ้าไม่มีไฟล์ → สร้างใหม่ทั้งไฟล์
    if not os.path.exists(CONFIGRANGER_PATH):
        print("⚠ configRanger.ini not found → creating new file")
        os.makedirs(os.path.dirname(CONFIGRANGER_PATH), exist_ok=True)
        with open(CONFIGRANGER_PATH, "w", encoding="utf-8") as f:
            f.write(default_data)
        print("✅ New configRanger.ini created")
        return

    print("configRanger.ini found → checking for missing keys...")

    # โหลด config ผู้ใช้
    user_cfg = configparser.ConfigParser()
    user_cfg.read(CONFIGRANGER_PATH, encoding="utf-8")

    # โหลด config ต้นฉบับเพื่อตรวจสอบโครงสร้าง
    default_cfg = configparser.ConfigParser()
    default_cfg.read_string(default_data)

    modified = False

    # ตรวจสอบทุก section + key
    for section in default_cfg.sections():
        if section not in user_cfg.sections():
            print(f"➕ Adding missing section: [{section}]")
            user_cfg.add_section(section)
            modified = True

        for key, value in default_cfg[section].items():
            if key not in user_cfg[section]:
                print(f"➕ Key missing → Adding {section}.{key} = {value}")
                user_cfg[section][key] = value
                modified = True

    if modified:
        with open(CONFIGRANGER_PATH, "w", encoding="utf-8") as f:
            user_cfg.write(f)
        print("✅ configRanger.ini updated successfully")
    else:
        print("✔ configRanger.ini is already up to date")




def download_default_config():
    """โหลด config.ini จาก GitHub (ตัวเต็มจากลิงก์)"""
    try:
        r = requests.get(CONFIG_URL, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"❌ Cannot download default config.ini: {e}")
        return None


def repair_or_create_config():
    print("======================")
    print("Checking config.ini ...")

    # โหลด config ต้นฉบับจาก GitHub
    default_data = download_default_config()
    if not default_data:
        print("⚠ Cannot repair config.ini (download failed).")
        return

    # ถ้าไม่มีไฟล์ → สร้างใหม่ทั้งไฟล์
    if not os.path.exists(CONFIG_PATH):
        print("⚠ config.ini not found → creating new file")
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(default_data)
        print("✅ New config.ini created")
        return

    print("config.ini found → checking for missing keys...")

    # โหลด config ผู้ใช้
    user_cfg = configparser.ConfigParser()
    user_cfg.read(CONFIG_PATH, encoding="utf-8")

    # โหลด config ต้นฉบับเพื่อตรวจสอบโครงสร้าง
    default_cfg = configparser.ConfigParser()
    default_cfg.read_string(default_data)

    modified = False

    # ตรวจสอบทุก section + key
    for section in default_cfg.sections():
        if section not in user_cfg.sections():
            print(f"➕ Adding missing section: [{section}]")
            user_cfg.add_section(section)
            modified = True

        for key, value in default_cfg[section].items():
            if key not in user_cfg[section]:
                print(f"➕ Key missing → Adding {section}.{key} = {value}")
                user_cfg[section][key] = value
                modified = True

    if modified:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            user_cfg.write(f)
        print("✅ config.ini updated successfully")
    else:
        print("✔ config.ini is already up to date")


def extract_update():
    print("======================")
    print("Extracting files...")
    try:
        with zipfile.ZipFile(TEMP_FILE, "r") as zip_ref:
            members = zip_ref.infolist()
            total = len(members)

            for i, member in enumerate(members, 1):
                if os.path.basename(member.filename).lower() == "updater.exe":
                    print(f"Skipping {member.filename} (currently running)")
                    continue

                extracted_path = os.path.abspath(os.path.join(APP_DIR, member.filename))
                if not extracted_path.startswith(APP_DIR):
                    raise Exception("Invalid zip file (zip slip detected)")
                
                # ⛔ ไม่ extract src/config.ini ถ้ามีอยู่แล้ว
                if member.filename.replace("\\", "/").lower() == "src/config.ini":
                    config_path = os.path.join(APP_DIR, "src", "config.ini")
                    if os.path.exists(config_path):
                        print("Skipping existing src/config.ini (preserved)")
                        continue

                if member.filename.replace("\\", "/").lower() == "src/configRanger.ini":
                    configRanger_path = os.path.join(APP_DIR, "src", "configRanger.ini")
                    if os.path.exists(configRanger_path):
                        print("Skipping existing src/configRanger.ini (preserved)")
                        continue


                zip_ref.extract(member, APP_DIR)

                percent = int(i * 100 / total)
                sys.stdout.write(f"\rExtracting: [{'#' * (percent // 2):<50}] {percent}%")
                sys.stdout.flush()

        os.remove(TEMP_FILE)
        print("\n✅ Update completed!")
        print("🔧 Checking and repairing config.ini ...")

        # 👇 **เรียกตรวจสอบ config**
        repair_or_create_config()
        repair_or_create_configRanger()

        print("👉 Please run main.exe")

    except Exception as e:
        import traceback
        print(f"\n❌ Extraction failed: {e}")
        traceback.print_exc()


def close_related_processes():
    """ปิดทุกโปรแกรมที่เกี่ยวข้องกับบอทก่อนอัปเดต"""
    print("======================")
    print("Checking for running processes...")
    closed = False

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info["name"].lower()
            for target in TARGET_PROCESSES:
                if target.lower() in name:
                    print(f"🛑 Closing process: {name} (PID {proc.pid})")
                    proc.terminate()
                    closed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if closed:
        print("Waiting for processes to close...")
        time.sleep(2)  # รอให้ปิดจริง
    else:
        print("No related processes running.")


def download_update():
    print("======================")
    print("Downloading update...")
    try:
        r = requests.get(DOWNLOAD_URL, stream=True, timeout=30)
        r.raise_for_status()
        total_size = int(r.headers.get("content-length", 0))
        block_size = 8192
        downloaded = 0

        with open(TEMP_FILE, "wb") as f:
            for chunk in r.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = int(downloaded * 100 / total_size)
                        sys.stdout.write(f"\rProgress: [{'#' * (percent // 2):<50}] {percent}%")
                        sys.stdout.flush()
        print("\n✅ Download finished")
        return True
    except Exception as e:
        print(f"\n❌ Download failed: {e}")
        return False


def main():
    close_related_processes()
    if download_update():
        extract_update()


if __name__ == "__main__":
    print("======================")
    print("Update BotLineRanger")
    print("======================")
    print()
    main()
    print()
    print("======================")
    input("Press Enter to exit...")
