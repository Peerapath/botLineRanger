# ADB.py
import os
import sys
import subprocess
import time
import threading
import socket

# อิงตำแหน่งของ exe เมื่อรันแบบ frozen (PyInstaller วาง src/ ไว้ข้าง exe ไม่ใช่ใน _internal/_MEIPASS)
# มิฉะนั้นอิงตำแหน่งของไฟล์นี้ จะได้รันจากโฟลเดอร์ไหนก็ได้ ไม่ใช่ cwd
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADB_PATH = os.path.join(BASE_DIR, "src", "adb", "adb.exe")

PORT_SCAN_RANGE = (16000, 19000)

SCAN_THREADS = 200

found_ports = []
lock = threading.Lock()

def run_adb_command(command):
    """รันคำสั่ง ADB และคืนค่าผลลัพธ์"""
    if not os.path.isfile(ADB_PATH):
        print(f"ADB Error: ไม่พบ adb.exe ที่ {ADB_PATH}")
        return ""
    full_command = f'"{ADB_PATH}" {command}'
    try:
        result = subprocess.run(
            full_command, 
            shell=True, 
            check=True, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='ignore'
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if "connect" not in command and "root" not in command: 
            print(f"ADB Error: {e.stderr.strip()}")
        return ""

def check_port(port):
    """ฟังก์ชันสำหรับ Worker Thread เพื่อตรวจสอบว่า Port เปิดอยู่หรือไม่"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            with lock:
                found_ports.append(port)

def setup_emulators():
    """
    ฟังก์ชันหลักที่ทำหน้าที่: สแกนพอร์ต > เชื่อมต่อ > กรองอุปกรณ์ > ขอสิทธิ์ Root
    """
    global found_ports
    found_ports = []

    print(f"--- 1. Scanning ports from {PORT_SCAN_RANGE[0]} to {PORT_SCAN_RANGE[1]} using {SCAN_THREADS} threads ---")
    threads = []
    for port in range(PORT_SCAN_RANGE[0], PORT_SCAN_RANGE[1] + 1):
        thread = threading.Thread(target=check_port, args=(port,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()

    if not found_ports:
        print("\n[!] No open ports found. Please make sure your emulators are running.")
        return []

    print(f"\n[SUCCESS] Found {len(found_ports)} open ports: {sorted(found_ports)}")

    print("\n--- 2. Connecting to all found devices via ADB ---")
    run_adb_command("kill-server")
    time.sleep(1)
    run_adb_command("start-server")
    time.sleep(2)
    
    for port in found_ports:
        run_adb_command(f"connect 127.0.0.1:{port}")
    
    print("Connection attempts sent.")
    time.sleep(8)

    print("\n--- 3. Verifying and filtering connected devices ---")
    devices_output = run_adb_command("devices")
    
    online_devices = [
        line.split('\t')[0] 
        for line in devices_output.strip().split('\n')[1:] 
        if "device" in line and not line.startswith("emulator-")
    ]

    if not online_devices:
        print("\n[!] No valid devices connected. (They might be offline or standard emulators)")
        return []

    print(f"\n[SUCCESS] Found {len(online_devices)} valid device(s):")
    for device in online_devices:
        print(f"  - {device}")

    return online_devices


if __name__ == "__main__":
    setup_emulators()
    
    print("\nProcess finished. Emulators should now have root access.")
    input("Press Enter to exit...")