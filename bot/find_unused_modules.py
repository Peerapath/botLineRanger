# -*- coding: utf-8 -*-
import os
import ast

PROJECT_DIR = os.path.abspath(".")
EXCLUDE_FILE = "exclude_modules.txt"

all_imports = set()

# scan ทุกไฟล์ .py
for root, dirs, files in os.walk(PROJECT_DIR):
    if any(skip in root for skip in ["venv", "build", "dist", "__pycache__"]):
        continue

    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8") as code_file:
                    tree = ast.parse(code_file.read(), filename=path)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            all_imports.add(n.name.split(".")[0])

                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            all_imports.add(node.module.split(".")[0])

            except Exception as e:
                print(f"Warning: {path} parse error: {e}")

# Standard libs และ libs ที่ต้องใช้งานจริง
STANDARD_LIBS = {
    "os","sys","time","shutil","threading","subprocess","socket","re","glob",
    "datetime","random","difflib","configparser","requests","webbrowser",
    "multiprocessing","tkinter"
}

# load safe modules (ห้ามถูก exclude โดยเด็ดขาด)
safe = set()
if os.path.exists("safe_modules.txt"):
    with open("safe_modules.txt", "r", encoding="utf-8") as sf:
        safe = {line.strip() for line in sf if line.strip()}

# modules ที่เราจะ exclude จริง ๆ
exclude_modules = {m for m in all_imports if m not in STANDARD_LIBS and m not in safe}

# save file
with open(EXCLUDE_FILE, "w", encoding="utf-8") as f:
    for m in sorted(exclude_modules):
        f.write(m + "\n")

print(f"===============================================")
print(f" Scanning project imports...")
print(f" Found imports     : {len(all_imports)}")
print(f" Safe modules      : {len(safe)}")
print(f" Excluding modules : {len(exclude_modules)}")
print(f" Saved to          : {EXCLUDE_FILE}")
print(f"===============================================")
