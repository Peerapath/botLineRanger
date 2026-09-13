# BotLineRanger Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand the copied bot project from KaiRubyClearMission/KaiByClearMission to BotLineRanger and copy the missing build-support files that `build.bat` needs into `bot/`.

**Architecture:** Mechanical rename + file copy. No bot logic changes. The "tests" for each task are verification gates: `grep` for absence of old names, `python -c "import ..."`, and an encrypt→decrypt round-trip. Work happens in `D:\Programing\ranger\Test-Mitmproxy-Api\bot`; the prototype source is `D:\Programing\ranger\BotKaiByClearMission`.

**Tech Stack:** Python 3.11 (build), PyInstaller, PyArmor, Fernet (cryptography), batch script.

## Global Constraints

- Module/file name: `botLineRanger.py` (camelCase). Display/exe/zip/spec/dist name: `BotLineRanger`.
- GitHub repo placeholder for update/version URLs: `Peerapath/BotLineRanger` (repo does not exist yet).
- salt (both `config_secure.py` and `encrypt_config.py`): `BotLineRanger_v2_secure_salt_2025`.
- Backend values to KEEP UNCHANGED: `api_url`, `service_id` (`bot_kai_by_clear_mission`), `master_password`. Only `version_url` changes (new repo) and salt changes.
- DO NOT touch in-game currency tokens: `ruby`/`Rb` — `RUSERUBY`, `getRubyAndTicket`, `rubyBalance`, config keys `ruseruby`/`buyruby`/`guse200ruby`, account filename pattern `_Rb{ruby}_`.
- DO NOT touch: `pyarmor_runtime_009939`, hardcoded `...Python311` paths in specs, existing logs/xml/roster/captures, bot logic.
- Prototype path used only as a copy source; never modify files under `D:\Programing\ranger\BotKaiByClearMission`.
- All shell commands run from `D:\Programing\ranger\Test-Mitmproxy-Api\bot` unless stated.

---

### Task 1: Copy verbatim build-support files into `bot/`

Files with no old-name references — copy as-is.

**Files:**
- Create (copy from prototype): `bot/get_version.py`, `bot/server_version.py`, `bot/find_unused_modules.py`, `bot/update_version.py`, `bot/reset_config.py`, `bot/updater.spec`, `bot/exclude_modules.txt`, `bot/requirements.txt`, `bot/SECURITY_NOTES.md`
- Create (copy from prototype): `bot/default_config/config.ini`, `bot/default_config/configRanger.ini`, `bot/default_config/latest_version.json`

**Interfaces:**
- Produces: build-support scripts that `build.bat` invokes (`get_version.py`, `server_version.py`, `find_unused_modules.py`, `update_version.py`, `reset_config.py`) and the `default_config/latest_version.json` target for `update_version.py`.

- [ ] **Step 1: Copy the files**

```bash
SRC="D:/Programing/ranger/BotKaiByClearMission"
DST="D:/Programing/ranger/Test-Mitmproxy-Api/bot"
cp "$SRC"/get_version.py "$SRC"/server_version.py "$SRC"/find_unused_modules.py \
   "$SRC"/update_version.py "$SRC"/reset_config.py "$SRC"/updater.spec \
   "$SRC"/exclude_modules.txt "$SRC"/requirements.txt "$SRC"/SECURITY_NOTES.md "$DST"/
mkdir -p "$DST/default_config"
cp "$SRC"/default_config/config.ini "$SRC"/default_config/configRanger.ini \
   "$SRC"/default_config/latest_version.json "$DST/default_config/"
```

- [ ] **Step 2: Verify all files present and none carry an old name**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
for f in get_version.py server_version.py find_unused_modules.py update_version.py \
  reset_config.py updater.spec exclude_modules.txt requirements.txt SECURITY_NOTES.md \
  default_config/config.ini default_config/configRanger.ini default_config/latest_version.json; do
  test -f "$f" || echo "MISSING: $f"
done
grep -rni "kaiby\|kairuby\|clearmission" get_version.py server_version.py \
  find_unused_modules.py update_version.py reset_config.py updater.spec \
  exclude_modules.txt requirements.txt SECURITY_NOTES.md default_config/ || echo "CLEAN"
```

Expected: no `MISSING:` lines, and `CLEAN` printed.

- [ ] **Step 3: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add bot/get_version.py bot/server_version.py bot/find_unused_modules.py \
  bot/update_version.py bot/reset_config.py bot/updater.spec bot/exclude_modules.txt \
  bot/requirements.txt bot/SECURITY_NOTES.md bot/default_config
git commit -m "chore: copy verbatim build-support files into bot/"
```

---

### Task 2: Rename bot module and fix `main.py` identity strings

**Files:**
- Rename: `bot/botKaiRubyClearMission.py` → `bot/botLineRanger.py`
- Modify: `bot/main.py` (lines 5, 303, 307, 440–443, 1871–1873, 2135)
- Delete: `bot/__pycache__/botKaiRubyClearMission.*.pyc`

**Interfaces:**
- Produces: module `botLineRanger` (star-exports everything `main.py` needs), consumed by `main.py` and by the `.spec` hiddenimport in Task 5.

- [ ] **Step 1: Rename the module file and drop stale bytecode**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
git mv botKaiRubyClearMission.py botLineRanger.py 2>/dev/null || mv botKaiRubyClearMission.py botLineRanger.py
rm -f __pycache__/botKaiRubyClearMission.*.pyc
```

- [ ] **Step 2: Fix the comment on line 1 of the renamed file**

Edit `bot/botLineRanger.py` line 1:
- From: `# botKaiRubyClearMission.py`
- To: `# botLineRanger.py`

- [ ] **Step 3: Fix the import in `main.py` (line 5)**

- From: `from botKaiRubyClearMission import *`
- To: `from botLineRanger import *`

- [ ] **Step 4: Fix window title (line 303)**

- From: `        self.title(f"KaiByClearMission")`
- To: `        self.title("BotLineRanger")`

- [ ] **Step 5: Fix icon path (line 307)**

- From: `            self.iconbitmap(r"src\image\home\Ruby_128.ico")`
- To: `            self.iconbitmap(r"src\image\home\BotLineRanger_128.ico")`

- [ ] **Step 6: Make version label non-clickable (lines 440–443)**

Replace this block:

```python
        self.label_current_version = ctk.CTkLabel(self.bottom_frame, text=f"v{CURRENT_VERSION}",
                     text_color="gray", cursor="hand2")
        self.label_current_version.pack(side="right", padx=(5, 10))
        self.label_current_version.bind("<Button-1>", lambda e: open_gethub())
```

with:

```python
        self.label_current_version = ctk.CTkLabel(self.bottom_frame, text=f"v{CURRENT_VERSION}",
                     text_color="gray")
        self.label_current_version.pack(side="right", padx=(5, 10))
```

- [ ] **Step 7: Remove the `open_gethub()` function (lines 1871–1873)**

Delete this block entirely:

```python
def open_gethub():
    url = "https://github.com/Peerapath/BotKaiRubyClearMission/releases/latest"
    webbrowser.open(url)
```

(Leave the blank line separation between the neighboring functions tidy.)

- [ ] **Step 8: Fix module-hash list (line ~2135)**

- From: `            'botKaiRubyClearMission', 'ADB',`
- To: `            'botLineRanger', 'ADB',`

- [ ] **Step 9: Verify no old references and no orphan `open_gethub`**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
grep -n "botKaiRubyClearMission\|KaiByClearMission\|open_gethub\|Ruby_128" main.py botLineRanger.py || echo "CLEAN"
python -c "import ast; ast.parse(open('main.py',encoding='utf-8').read()); ast.parse(open('botLineRanger.py',encoding='utf-8').read()); print('SYNTAX OK')"
```

Expected: `CLEAN` and `SYNTAX OK`.

- [ ] **Step 10: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add bot/botLineRanger.py bot/main.py
git commit -m "refactor: rename bot module to botLineRanger and rebrand main.py"
```

---

### Task 3: Rename icon files

**Files:**
- Rename: `bot/src/image/home/Ruby_128.ico` → `bot/src/image/home/BotLineRanger_128.ico`
- Rename: `bot/src/image/home/Ruby_64.ico` → `bot/src/image/home/BotLineRanger_64.ico`

**Interfaces:**
- Produces: `BotLineRanger_128.ico`, referenced by `main.py:307` (Task 2) and `BotLineRanger.spec` (Task 5).

- [ ] **Step 1: Rename both icons (keep the image bytes)**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot/src/image/home"
mv "Ruby_128.ico" "BotLineRanger_128.ico"
mv "Ruby_64.ico" "BotLineRanger_64.ico"
```

- [ ] **Step 2: Verify**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot/src/image/home"
ls BotLineRanger_128.ico BotLineRanger_64.ico
test ! -f Ruby_128.ico && test ! -f Ruby_64.ico && echo "OLD GONE"
```

Expected: both new files listed, `OLD GONE` printed.

- [ ] **Step 3: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add "bot/src/image/home/BotLineRanger_128.ico" "bot/src/image/home/BotLineRanger_64.ico"
git commit -m "chore: rename window icons to BotLineRanger"
```

---

### Task 4: Update secrets — salt, version_url, re-encrypt config

`encrypt_config.py` is the build-time tool that prints Fernet ciphertext for `config_secure.py`. Its `PLAINTEXT_CONFIG` and `EMBEDDED_SALT` must match the runtime `config_secure.py._SALT`. We change salt + version_url, keep the other three plaintext values, regenerate ciphertext, and paste it back.

**Files:**
- Create (copy + edit): `bot/encrypt_config.py`
- Modify: `bot/config_secure.py` (line 15 `_SALT`, and the 4 entries of `_ENCRYPTED_DATA`)

**Interfaces:**
- Consumes: prototype `encrypt_config.py` plaintext values (`api_url`, `service_id`, `master_password` kept as-is).
- Produces: `config_secure.py` whose `_SALT = "BotLineRanger_v2_secure_salt_2025"` decrypts its own `_ENCRYPTED_DATA` back to the intended plaintext (version_url pointing at `Peerapath/BotLineRanger`).

- [ ] **Step 1: Copy `encrypt_config.py` from the prototype**

```bash
cp "D:/Programing/ranger/BotKaiByClearMission/encrypt_config.py" \
   "D:/Programing/ranger/Test-Mitmproxy-Api/bot/encrypt_config.py"
```

- [ ] **Step 2: Edit `encrypt_config.py` — version_url and salt**

In `PLAINTEXT_CONFIG`, change the `version_url` line:
- From: `    'version_url': 'https://raw.githubusercontent.com/Peerapath/BotKaiRubyClearMission/refs/heads/main/latest_version.json',`
- To: `    'version_url': 'https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/latest_version.json',`

Leave `api_url`, `service_id`, `master_password` exactly as copied.

Change the salt:
- From: `EMBEDDED_SALT = "KaiByClearMission_v2_secure_salt_2025"`
- To: `EMBEDDED_SALT = "BotLineRanger_v2_secure_salt_2025"`

- [ ] **Step 3: Run the tool to produce new ciphertext**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
python encrypt_config.py
```

Expected: prints four lines of the form `'version_url': 'gAAAA...',` etc. (Ciphertext is non-secret; the derived key is not printed in full.)

- [ ] **Step 4: Paste the four ciphertext values into `config_secure.py`**

Replace the four values inside `_ENCRYPTED_DATA` (lines ~20–24) with the four printed in Step 3, keeping the same keys (`version_url`, `api_url`, `service_id`, `master_password`).

- [ ] **Step 5: Change the runtime salt in `config_secure.py` (line 15)**

- From: `    _SALT = "KaiByClearMission_v2_secure_salt_2025"`
- To: `    _SALT = "BotLineRanger_v2_secure_salt_2025"`

- [ ] **Step 6: Verify round-trip WITHOUT printing secrets**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
python -c "
from config_secure import SecureConfig as S
assert S.get_version_url() == 'https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/latest_version.json'
assert S.get_service_id() == 'bot_kai_by_clear_mission'
# prove api_url and master_password decrypt without error / without echoing them
assert len(S.get_api_url()) > 0 and len(S.get_master_password()) > 0
print('DECRYPT OK')
"
```

Expected: `DECRYPT OK` (no exception). If a `cryptography.fernet.InvalidToken` is raised, the salt in the two files does not match — recheck Steps 4–5.

- [ ] **Step 7: Confirm no stale old-salt string remains**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
grep -n "KaiByClearMission_v2_secure_salt" config_secure.py encrypt_config.py || echo "CLEAN"
```

Expected: `CLEAN`.

- [ ] **Step 8: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add bot/encrypt_config.py bot/config_secure.py
git commit -m "chore: rotate config salt to BotLineRanger and re-encrypt secrets"
```

---

### Task 5: Rename spec, updater.py, safe_modules.txt

**Files:**
- Create (copy from prototype as new name): `bot/BotLineRanger.spec` (source: prototype `KaiByClearMission.spec`)
- Create (copy + edit): `bot/updater.py`
- Create (copy + edit): `bot/safe_modules.txt`

**Interfaces:**
- Consumes: `botLineRanger` module (Task 2), `BotLineRanger_128.ico` (Task 3).
- Produces: `BotLineRanger.spec` (PyInstaller entry named `BotLineRanger`), consumed by `build.bat` in Task 6.

- [ ] **Step 1: Copy the spec under the new name and the other two files**

```bash
SRC="D:/Programing/ranger/BotKaiByClearMission"
DST="D:/Programing/ranger/Test-Mitmproxy-Api/bot"
cp "$SRC/KaiByClearMission.spec" "$DST/BotLineRanger.spec"
cp "$SRC/updater.py" "$DST/updater.py"
cp "$SRC/safe_modules.txt" "$DST/safe_modules.txt"
```

- [ ] **Step 2: Edit `BotLineRanger.spec` — three replacements**

- hiddenimport: `        'botKaiRubyClearMission',` → `        'botLineRanger',`
- exe name: `    name='KaiByClearMission',` → `    name='BotLineRanger',`
- icon: `    icon=['src\\image\\home\\Ruby_128.ico'],` → `    icon=['src\\image\\home\\BotLineRanger_128.ico'],`

- [ ] **Step 3: Edit `safe_modules.txt`**

- `botKaiRubyClearMission` → `botLineRanger`

- [ ] **Step 4: Edit `updater.py` — URLs, filenames, process, label**

- `DOWNLOAD_URL = "https://github.com/Peerapath/BotKaiRubyClearMission/releases/latest/download/KaiByClearMission.zip"`
  → `DOWNLOAD_URL = "https://github.com/Peerapath/BotLineRanger/releases/latest/download/BotLineRanger.zip"`
- `CONFIG_URL = "https://raw.githubusercontent.com/Peerapath/BotKaiRubyClearMission/refs/heads/main/config.ini"`
  → `CONFIG_URL = "https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/config.ini"`
- `CONFIGRANGER_URL = "https://raw.githubusercontent.com/Peerapath/BotKaiRubyClearMission/refs/heads/main/configRanger.ini"`
  → `CONFIGRANGER_URL = "https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/configRanger.ini"`
- In `TARGET_PROCESSES`: `    "KaiByClearMission.exe",` → `    "BotLineRanger.exe",`
- Label: `    print("Update KaiRubyClearMission")` → `    print("Update BotLineRanger")`

- [ ] **Step 5: Verify no old names remain in the three files**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
grep -rni "kaiby\|kairuby\|clearmission\|Ruby_128\|BotKaiRuby" \
  BotLineRanger.spec updater.py safe_modules.txt || echo "CLEAN"
python -c "import ast; ast.parse(open('updater.py',encoding='utf-8').read()); print('UPDATER SYNTAX OK')"
```

Expected: `CLEAN` and `UPDATER SYNTAX OK`.

- [ ] **Step 6: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add bot/BotLineRanger.spec bot/updater.py bot/safe_modules.txt
git commit -m "chore: rebrand spec, updater, and safe_modules to BotLineRanger"
```

---

### Task 6: Rebrand `build.bat`

`build.bat` already exists in `bot/`. Replace every KaiByClearMission token and the pyarmor module name and spec reference.

**Files:**
- Modify: `bot/build.bat`

**Interfaces:**
- Consumes: `BotLineRanger.spec`, `updater.spec`, `botLineRanger.py`, `config_secure.py`, all build-support scripts from Tasks 1–5.

- [ ] **Step 1: Set name/icon/spec variables and pyarmor entry**

- `set NAME=KaiByClearMission` → `set NAME=BotLineRanger`
- `set ICON=src\image\home\Ruby_128.ico` → `set ICON=src\image\home\BotLineRanger_128.ico`
- In the `pyarmor gen` line: `main.py botKaiRubyClearMission.py config_secure.py ...`
  → `main.py botLineRanger.py config_secure.py ...`
- `pyinstaller ... KaiByClearMission.spec` → `pyinstaller ... BotLineRanger.spec`

- [ ] **Step 2: Replace all remaining `KaiByClearMission` occurrences**

Every remaining literal `KaiByClearMission` in `build.bat` (title, echo banners, `dist\KaiByClearMission` paths, `.exe`/`.zip` names, `certutil -hashfile` path, output listing) becomes `BotLineRanger`. Do it with one pass:

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
sed -i 's/KaiByClearMission/BotLineRanger/g' build.bat
```

(This also normalizes `title`, `dist\BotLineRanger`, `BotLineRanger.zip`, and the `Version\BotLineRanger_%VERSION%.zip` copy line.)

- [ ] **Step 3: Verify**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
grep -ni "kaiby\|kairuby\|clearmission\|botKaiRuby\|Ruby_128" build.bat || echo "CLEAN"
grep -n "BotLineRanger.spec\|botLineRanger.py\|set NAME=BotLineRanger" build.bat
```

Expected: `CLEAN`, and the three expected lines present.

- [ ] **Step 4: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add bot/build.bat
git commit -m "chore: rebrand build.bat to BotLineRanger"
```

---

### Task 7: Final repo-wide sweep and import smoke test

**Files:** none created — verification + fix-up only.

- [ ] **Step 1: Repo-wide grep for surviving brand names (excluding logs, bytecode, account files, prototype)**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
grep -rni "kaiby\|kairuby\|clearmission\|botKaiRuby\|BotKaiRubyClearMission" \
  --include=*.py --include=*.ini --include=*.spec --include=*.bat \
  --include=*.txt --include=*.md --include=*.json . \
  | grep -v "/bot/src/log/" \
  | grep -v "docs/superpowers/specs/2026-09-13-rename-botlineranger-design.md" \
  | grep -v "docs/superpowers/plans/2026-09-13-rename-botlineranger.md" \
  || echo "CLEAN"
```

Expected: `CLEAN`. (The two design/plan docs legitimately contain the old name as history — they are excluded. If anything else prints, fix it, following the same rename rules, then re-run.)

- [ ] **Step 2: Fix the tools/ default paths that point at the old sibling project**

Two references point at `../BotKaiByClearMission/input`; the bot now lives in this repo at `bot/input`.

In `tools/account_file.py:117`:
- From: `    parser.add_argument("--sample-dir", default="D:/Programing/ranger/BotKaiByClearMission/input",`
- To: `    parser.add_argument("--sample-dir", default="D:/Programing/ranger/Test-Mitmproxy-Api/bot/input",`

In `tools/new_account.py` docstring (lines ~37–38), change both example paths:
- `../BotKaiByClearMission/input` → `../bot/input`

- [ ] **Step 3: Byte-compile smoke test of the renamed Python files**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
python -m py_compile botLineRanger.py main.py updater.py encrypt_config.py config_secure.py \
  get_version.py server_version.py find_unused_modules.py update_version.py reset_config.py \
  && echo "COMPILE OK"
```

Expected: `COMPILE OK` (compilation only; a full runtime import may still need MuMu/adb/GUI deps not present here — compilation is the gate for this rename).

- [ ] **Step 4: Verify every file `build.bat` references now exists**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api/bot"
for f in config_secure.py get_version.py server_version.py find_unused_modules.py \
  BotLineRanger.spec updater.spec updater.py reset_config.py update_version.py \
  exclude_modules.txt botLineRanger.py default_config/latest_version.json \
  src/image/home/BotLineRanger_128.ico; do
  test -f "$f" || echo "MISSING: $f"
done
echo "done"
```

Expected: no `MISSING:` lines.

- [ ] **Step 5: Commit**

```bash
cd "D:/Programing/ranger/Test-Mitmproxy-Api"
git add tools/account_file.py tools/new_account.py
git commit -m "chore: point tools default paths at in-repo bot/input"
```

---

## Notes for the implementer
- `git mv` may warn that `bot/` files are untracked (they are, at plan start). If `git mv` fails, a plain `mv` is fine; the first `git add` in Task 1/2 will stage them.
- `sed -i` on Windows Git Bash edits in place with no backup suffix — correct here.
- If `python encrypt_config.py` (Task 4) can't import `cryptography`, install per `requirements.txt` first (`pip install cryptography`). The round-trip in Step 6 is the real gate.
- Do NOT run the full `build.bat` — it needs a PyArmor license and uploads to a server. This plan stops at correct, compilable, brand-consistent files.
