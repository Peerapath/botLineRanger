# Frida capture runbook (rooted arm64 phone)

One-time capture of the native rangers `/login` request so the appSecret can be reproduced.

## Prep
1. Push a frida-server build matching the phone's arch (`arm64`) and the host's frida
   version (`frida --version`, currently 17.x) to `/data/local/tmp/frida-server`.
2. `adb shell "su -c 'chmod 755 /data/local/tmp/frida-server; /data/local/tmp/frida-server &'"`
3. Confirm from host: `frida-ps -U | grep LGRGS` (empty is fine; it just proves the link works).

## Capture (do it TWICE for two fresh guests)
1. `python tools/frida/capture.py --script tools/frida/dump_login.js`
2. In the app: WARP on -> GUEST Login -> agree the 3 required + 1 optional terms -> reach home.
3. When the `=== SSL_write ... ===` block with `X-LINEGAME-APPSECRET` prints, Ctrl+C.
4. Repeat from a cleared state for a second brand-new guest.

## Collect
Two files land in `roster/scratch/login-*.capture.txt`. Each must contain, for the
`/login` request: `X-LINEGAME-APPID`, `X-LINEGAME-APPSECRET`, `X-LINEGAME-USERKEY`,
`X-LINEGAME-MCC/MNC/TIMESTAMP`, and the `Cookie:` line (`cc=...; udid=...;`). Task 2 diffs them.

If `SSL_write` was not found, the app statically links a renamed BoringSSL; add
`Process.enumerateModules()` output to the issue and hook the `curl_easy_setopt`
CURLOPT_HTTPHEADER path instead.
