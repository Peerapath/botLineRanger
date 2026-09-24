---
name: lgrgs-api-forge
description: >
  Reverse-engineer and replay the LINE Rangers (com.linecorp.LGRGS) native game API off-device,
  and reproduce its battle anti-cheat crypto. Use when working on the Test-Mitmproxy-Api project's
  API replay, stage-forge, headless account, or battle-log/tempsave tasks - or when hand-calling a
  cert-pinned Cocos2d-x/OpenSSL mobile game API gives 401/500, or you need to reproduce fields the
  client RSA/AES-encrypts. Captures the Ghidra + memory + SQLCipher + API-replay methodology and the
  concrete cracked values so you don't re-derive them.
---

# LINE Rangers (LGRGS) API replay + anti-cheat crypto

Goal: drive the user's OWN account over the pinned game API without the phone, and forge
stage clears (SOLVED - see next section).

## STATUS: main-stage forge SOLVED (2026-09-19) - use `tools/stage_forge.py`
`python tools/stage_forge.py --acct roster/accounts/account-*.json --to 150` (or --xml/--cookie) clears
stages purely over the API. Per stage: enter -> body = captured battleLog template (bm/bt/e/enemies/tt, the
same st02 log for EVERY stage) + `stc`, `pt=1`, **`atw`=str(max(999999, enemyTowerHp*3+10000))**,
`sn_e`=RSA(str(battleSn)), `win_e`=RSA("true"), `icu`=base64(iv + AES-128-CBC(key=HM16(HM16(rsn)+HM16(bsn)),
pkcs7(HM16(modulus)))) with **HM16(s)=md5(s).hexdigest().upper()[:16]**; `i_e` absent (or RSA("[]")) ->
wait >= pt+0.5 s since enter -> POST save with compact key-sorted JSON. Win = `battleResult.isCleared`.
Ablation (one fresh guest per factor): **icu is THE enforced check** (absent/random/wrong-rsn = silent
200 loss that still costs a heart) - the old icu guess RSA(md5hex(n)) is why every earlier forge got
"200 but rewardExp=0". atw is optional (absent/"0" win; 0<atw<towerHp -> 400/102205). 102205 = hard
reject (also pt > real elapsed, ~1 s slack) that keeps the battle open and costs no heart - re-post the
same battleSn.
The sections below that say the forge is blocked / the server re-simulates are HISTORY - they were wrong. Everything below is verified on MuMuPlayer (x86_64 Android running an ARM64 libgame.so
via `libnb` native-bridge translation). Client v12.3, API prefix `/v12.3`, host
`rangers-api.line-apps.com`.

## Environment / gotchas (hit these first)
- ADB: `D:/Program Files/Netease/MuMuPlayer/nx_main/adb.exe`, device `127.0.0.1:16416`. Root: `su 0 <cmd>`.
- **Git Bash mangles `/sdcard`, `/data/...` args** -> `export MSYS_NO_PATHCONV=1` for every adb line that
  passes a device path as a bare arg (not inside `adb shell "..."`).
- **Pull binary files (DBs, /proc/mem) with `adb exec-out "su 0 cat <path>"`** - `adb shell cat` injects CR
  bytes and corrupts binaries (symptom: pulled size = real+N).
- Read `/proc/PID/mem` via a device-side `sh` that `dd`s each `rw-p` region with LITERAL skip/count numbers
  (have Python compute `skip=start//4096`, `count=(end-start)//4096`); nested-quote hex math on-device fails.
- **Frida does NOT work on MuMu** - libgame.so is ARM64 translated to x86_64 anon regions by `libnb`, so
  arm64 hooks segfault and the .so isn't a file in the maps. Runtime hooking needs a real rooted ARM64 phone.
- Windows Python `open('/tmp/..')` fails; write scratch to the session scratchpad dir instead.

## Session / token (headless)
- `bot/botLineRanger.py::getLFAC()` reads+decrypts `_ENC_LF_AC_KEY` from device shared_prefs
  (`/data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml`, AES key = `_DEVICE_UUID_KEY`).
- `tools/rangers_api.py::call(cookie, path, method, body)` replays any endpoint with `LF_AC=` cookie +
  the app's exact headers. `tools/relogin.py` + `tools/new_account.py` mint fresh guests/tokens headlessly
  (GET /v12.3/signup/platform; the `/auth/v3.*` chain is Trident-signed - `new_account.sign()`).
- **Business-API 401 gotcha:** the whole `rangers-api` business tier can 401 EVERY off-device token (even a
  brand-new signup's) for a while, while the on-device game still works. Observed 2026-09-17: a ~2h TRANSIENT
  maintenance/version-transition window; it recovered on its own. Poll with `scratchpad/api_poll.py` in a
  `while sleep 900` loop that exits on /home==200, then proceed. Don't burn hours reversing "appSecret" for
  what is usually transient.

## Ghidra headless workflow (how all the crypto was found)
Project at `roster/scratch/ghproj` (lgproj, libgame.so imported). Run a postScript:
`analyzeHeadless.bat "%BASE%\ghproj" lgproj -process libgame.so -noanalysis -postScript X.java -scriptPath ...`
with `JAVA_HOME=%BASE%\jdk21\jdk-21.0.12.1+1`. **Run via PowerShell** (`& "...run_X.bat"`), not Git Bash.
Scripts in `roster/scratch/gscripts/` decompile: targets by name, callers of a func, a whole address range,
or callees N levels deep. Obfuscated strings are built char-by-char as LE int immediates in code (e.g.
`0x5f6e6977`="win_", `0x655f7361`="as_e", `0x655f6e69770a`=len5+"win_e") - `findBytes` for the ASCII won't
find them, so decode immediates or trace crypto primitives + base64 + callers instead. Output dumps land at
`~/*_DECOMP.txt`.

## Battle tempsave (local SQLCipher DB) - CRACKED
- Path: `/data/data/com.linecorp.LGRGS/files/.res/battle_tempsave/battle_tempsave.db`.
- **SQLCipher key = `rngr:!@battle_tempsave:#@key`** (built char-by-char in `FUN_0190ad88`);
  PBKDF2-HMAC-SHA1, 64000 iters, page 1024, reserve 48, HMAC-SHA1 over `ct||iv||pgno_LE`,
  hmac_key = PBKDF2-SHA1(enc_key, salt^0x3a, 2). Verified codec: `scratchpad/sqlcipher_lib.py`
  (decrypt/encrypt round-trips AND reproduces the game's stored per-page HMAC 7/7 - so a re-encrypted DB is
  game-accepted). Decrypt-only helper: `scratchpad/dump_log.py`.
- **The DB populates DURING a main-stage battle** (row = `battle_tempsave(battleSn, battleLog)`), not after -
  earlier "always empty" was a timing error. Capture with a fast device watcher `scratchpad/bts_watch.sh`
  (copies the db to /sdcard on any size/mtime change while you auto-play). The row is deleted on successful
  save; a cold relaunch DISCARDS it (so the tempsave-edit-then-resume forge does NOT trigger a submit).

## The battleLog / save-body anti-cheat crypto - CRACKED (no secret key!)
The encrypted `_e` fields are PUBLIC-KEY encryption with the per-battle key the server hands you at enter:
- `/stage/enter/{stc}` returns `rsaKeyBase = {"modulus":"<decimal>","exponent":"<decimal>"}` (e.g. RSA-512,
  modulus ~155 decimal chars, exponent 65537) + `battleSn`.
- **Field = `base64( RSA_public_encrypt(n, e, plaintext + b' '*(RSA_size-len), padding=RSA_NO_PADDING) )`**
  (deterministic; builder `FUN_01a05844`; single-line base64). Space padding appended to the END.
  `scratchpad/forge_crypto.py::rsa_no_pad_field(n_dec,e_dec,pt_bytes)` reproduces it.
- Plaintexts: `as_e`=str(battleSn); `win_e`="true"/"false"; `icu`=digest(modulus); score fields as %lld/%d.
- Alternate PATH (only when nProtect anti-cheat is active - NOT on the emulator): AES-256... actually
  AES-128-CBC, key from a custom MT19937 (`FUN_0190e790` seeder, constant 0x6c078965, adds +const not +i)
  seeded by battleSn, random 16-byte IV prepended, PKCS7. See `scratchpad/mt_kdf.py` and CRYPTOCORE dump.
- **/stage/save body carries NO battle timeline / no enemy list** (those live only in the tempsave). The
  save body (builder `FUN_00c7ec50` + wrapper `FUN_00c533c0`) is a flat dict: for a main stage
  `win_e`, `as`(plaintext score), `as_e`, plus `glv_e` and device meta `dt/df/bu`; boss modes add
  es_e/eb_e/tb_e/et_e. So the server does NOT re-simulate a timeline from the save.

## API stage-forge - SOLVED protocol, but blocked by server re-simulation (2026-09-17)
Correct call (verified HTTP 200):
- **Path: `/v12.3/stage/save/{battleSn}/{stageCode}?reqId=<unix_seconds>`** - battleSn FIRST, stageCode SECOND.
  The reversed order `{stageCode}/{battleSn}` (what the prior session assumed) returns a featureless
  `{"errorCode":500}` for ANY body - that generic 500 means WRONG ROUTE, not a bad body. A well-routed request
  returns a *semantic* errorCode instead, so use it to tell "route wrong" from "content wrong".
- **Body = the battleLog (tempsave-style) flat dict** (NOT the FUN_00c7ec50 as/as_e set, which returns 102205):
  `{bm:0, bt:<zlib>, e:<timeline>, enemies:[...], icu:RSA(md5hex(n)), pt:<int>, sn_e:RSA(str(battleSn)),
  stc:<code>, tt:"team1", win_e:RSA("true")}`, RSA fields via `forge_crypto.rsa_no_pad_field` with THIS enter's
  rsaKeyBase. Returns 200 with a full `result.battleResult`. Scripts: `scratchpad/forge_pipeline.py`,
  `forge_iterate.py`, `forge_crypto.py`.

**HARD LIMIT - the forge does NOT actually clear the stage.** A forged save returns 200 but **rewardExp=0 and
NO clear is credited**: `/stage/last`.receivedFirstClearRewardStageCodes doesn't grow, lastStageCode doesn't
advance, and the next stage stays locked (enter -> errorCode 102201). This holds even with the GENUINE captured
winning timeline replayed for a fresh battleSn. Conclusion: **the server RE-SIMULATES the inner `e` timeline
against the specific battleSn's parameters (enemy/RNG, fresh each enter)** - a replayed/forged timeline parses
(200) but re-sim scores it "not a win", so it grants nothing. So the crypto+protocol are fully broken but
game-logic re-simulation still prevents pure-API clearing. To actually clear, you must produce a genuine winning
log for that exact battleSn - i.e. play it (UI `botLineRanger.playMainStageAtNumber(1|2)`, or tap the node +
START + spam-deploy x=275/375/475/575/675 y=478, `scratchpad/battle_spam.sh`); the crypto crack then lets you
resubmit/tamper the non-simulated fields. Useful stage facts: codes are `st%02d` (st01..st151); enter locked
stages -> 102201; `/stage/save` needs POST (GET->405); the enter response gives `enemyTowerHp` + rsaKeyBase.

## Re-sim contract CONFIRMED from decompile (2026-09-17, workflow wf_b994d3a5 - 4 analysts)
Four parallel Ghidra-dump analysts converged (B/C/D high-confidence) on WHY pure-API forge fails:
- **The server RECOMPUTES the win; it does NOT trust the client.** Save-response parser `FUN_00c53fdc`
  never reads `win_e` back - it routes only on an internal category `*(param_3+0x70)` (0x200/0x204=success
  ->scene 6) + JSON `errorCode`; clear/reward come ONLY from the server-authored `battleResult`. The client
  ships the whole `e`/`bt`/`enemies`/`pt` - redundant unless the server re-runs the fight. Dedicated
  `errorCode 102204 (0x18f3c) = SUSPECTED_ABUSING` is the server's cheat verdict (sibling 102205=bad body).
- **`win_e`/`as_e`/`es_e`/`eb_e`/`tb_e`/`et_e`/`glv_e`/`icu` are anti-REPLAY binding to that battleSn, not a
  trusted result.** So asserting `win_e=RSA("true")` CANNOT credit a clear. Route builder `FUN_00c51fbc`
  (mode 6 -> config key "grs" = /stage/save/{battleSn}/{stc}); body `FUN_00c7ec50`+`FUN_00c533c0`; POST
  `FUN_010451c0` (cookie LF_AC + timestamp/timeID only - NO body-HMAC/appSecret on the save path).
- **`e` is ONE unified trace** built by the single recorder `FUN_00c79fe0` (event dict {t,et,v,en,cen};
  dispatch on eventObj vtable+0x50: 3=ENEMY, 4=deploy/summon, 0xb=END, 0xf=TOWER_DMG_HP, 0x12=booster).
  Input & output events interleave in the same array. `bt` (serializer `FUN_00c8a738`, zlib9+base64) is a
  DERIVED, mode-gated snapshot; `e` is authoritative. The 20-entry `et` name table `DAT_00840d68` is in
  .rodata (NOT yet dumped) - exact code->name map beyond ENEMY(3)/END(0xb)/TOWER_DMG_HP(0xf) is inferred.
- **NO client-side simulator/verify to lift.** Resend (`FUN_00effab8`) re-POSTs the stored battleLog
  VERBATIM (routes on stored `bm`; cleanup `FUN_00f00ff4` = DELETE) - no re-sim, no rebuild. Win is just a
  bool read from the live engine vtable **+0x4c8**. The `battleSn`-seeded MT19937 (`FUN_0190e790`) drives
  ONLY the field crypto keystream (`FUN_0190f110`/`FUN_0190e80c`), **NOT combat**.
- **The combat sim core is NOT in the current dumps.** It lives in the cocos2d battle-scene update loop
  behind the `FUN_00c46484()` engine vtable (slot +0x4c8 = isWin setter), entangled with CCNode/scheduler/
  render + encrypted `unit.db` master data. Headless Unicorn/Qiling emulation feasibility = **LOW**.

## FORK RESOLVED (2026-09-17, combat-core Ghidra pass, high confidence): server does NOT deterministically re-sim
The `FUN_00c46484()` singleton is a STATE MODEL (a 0x40-byte object, vtable `01dcf820` = a big block of tiny
8-byte getters: +0x3b8 team=`FUN_00c493c4`, +0x498 rsaKeyBase=`FUN_00c49688`, +0x4c8 isWin=`FUN_00c49778`,
+0x7a8/+0x838 towerHp) - it HOLDS results, it does not simulate. The real combat is a **real-time cocos2d
scheduler sim** (`scheduleUpdate`/`schedule`/`scheduleOnce` on the battle nodes) that **uses `arc4random`
for authoritative combat rolls** - proven in the event-emit combat fns: `FUN_00cfacb4` does
`(float)arc4random()/4.2949673e9 <= prob` (crit/dodge/skill-proc roll), `FUN_00cd72c8` `arc4random()%3`
(tower damage/knockback variant), `FUN_00c510dc` `scheduleOnce(random 20-29s)` (spawn timing). Dump:
`~/COMBAT_DECOMP.txt` (wide), `~/COMBAT2_DECOMP.txt` (vtable maps), `~/COMBAT3_DECOMP.txt` (combat set +
timing/RNG edges); scripts `gscripts/ghidra_combat{,2,3}.java`.

**`arc4random` is an UNSEEDABLE kernel-entropy CSPRNG** -> the client battle is non-deterministic and NOT
reproducible from battleSn (or anything). Therefore the server **cannot** re-run the client's exact battle
and require a matching trace - it is logically impossible. The anti-cheat is necessarily a **VALIDATION /
anti-replay** of the submitted log (bounds/consistency/energy-accounting/win-condition, and/or the server's
own independent sim checking the claimed win is *achievable*), NOT a deterministic replay. **This re-opens
pure-API forge as feasible**: we do NOT need to reimplement the combat engine; we need to build an `e` whose
recorded numbers satisfy the validator. Old belief "reproduce the sim (feasibility LOW)" is the wrong target.

**NEXT PHASE - discover the validator's rules empirically (cheap):** (1) capture ONE genuine winning log
template via the tempsave SQLCipher key (`rngr:!@battle_tempsave:#@key`; play st01/02 with spam-deploy, pull
+ decrypt battle_tempsave.db mid-battle) - gives the exact accepted `e` format. (2) On a THROWAWAY guest,
submit that log for its OWN battleSn (baseline credit), then re-target+re-sign it for a FRESH battleSn of the
same stage and probe mutations (shorten, change damage, drop deploys) to map what the validator rejects vs
SUSPECTED_ABUSING (102204). Open sub-question: does /stage/enter return CONSTANT enemy/towerHp per stage? if
yes, one template per stage re-signs to any battleSn. **Account risk: 102204 is a real cheat verdict - guests
only.** Prior "replay genuine log for fresh battleSn -> no credit" is now read as anti-replay / un-retargeted
params, NOT proof of re-sim.

## Cross-refs (auto-memory)
`lgrgs-battlelog-field-crypto`, `lgrgs-battle-tempsave-sqlcipher-key`, `lgrgs-business-api-401-appsecret`,
`lgrgs-native-api-cert-pinned`, `lgrgs-stage-battle-api`, `mumu-warp-vpn-blocks-native-capture`.
