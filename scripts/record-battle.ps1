# Brings the whole native-capture chain up so you can play one stage by hand and
# have its /stage/enter + /stage/save recorded.
#
# The stage-battle API rides rangers-api, which the game dials directly (it
# ignores the system http_proxy), so plain proxy capture never sees it. This
# does the full native path: root -> trust the mitmproxy CA -> reverse listeners
# (with the focused battle recorder on rangers-api) -> iptables redirect ->
# restart the game so it reconnects through it.
#
#   .\scripts\record-battle.ps1                 set everything up, restart the game
#   .\scripts\record-battle.ps1 -SkipGameRestart   leave the running game alone
#   .\scripts\record-battle.ps1 -Force          reclaim busy listener ports first
#
# Then play a stage. Each save prints a loud banner in the rangers-api window and
# writes captures\battles\<time>_save_<stage>_sn<sn>_<status>.json.
# Stop with:  .\scripts\stop-capture.ps1 -StopProxy

param(
    [switch]$SkipGameRestart,
    [switch]$Force
)

. "$PSScriptRoot\..\config.ps1"

Assert-Device

# adb writes its progress ("1 file pushed...") to stderr, and some device-shell
# steps below print harmless warnings there too. Under config.ps1's Stop policy
# Windows PowerShell would turn any such line into a terminating error, so relax
# to Continue for this script's own native calls. The helper scripts we invoke
# with & re-establish their own Stop policy in their own scope. Every critical
# step is verified explicitly (cert head, listening port), so nothing is masked.
$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "record-battle - native stage capture on $Device" -ForegroundColor White

if (-not (Test-Path $MitmCaPem)) {
    throw "mitmproxy CA not found at $MitmCaPem. Start mitmproxy once so it generates its CA, then re-run."
}
if (-not (Test-Path $BattleAddonPath)) {
    throw "Battle recorder addon not found at $BattleAddonPath"
}

# 1. Root --------------------------------------------------------------------
Write-Step "Switching adbd to root"
& $Adb -s $Device root | Out-Null
$isRoot = $false
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
    & $Adb -s $Device wait-for-device 2>$null | Out-Null
    $uid = (& $Adb -s $Device shell "id -u" 2>$null | Out-String).Trim()
    if ($uid -eq "0") { $isRoot = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $isRoot) { throw "adbd did not come back as root. Enable root in MuMu's settings and re-run." }
Write-Ok "running as root"

# 2. Trust store -------------------------------------------------------------
# This MuMu instance keeps /system read-only at the hypervisor level, so the
# usual remount fails. Overlay cacerts with a writable tmpfs instead. It dies on
# emulator reboot, so this checks and redoes it every run.
$hash   = Get-AndroidCertHash -PemPath $MitmCaPem
$target = "$SystemCertStore/$hash.0"
$staged = "/data/local/tmp/$hash.0"
$head = (Invoke-AdbShell "head -n 1 $target 2>/dev/null" | Out-String).Trim()
if ($head -match "BEGIN CERTIFICATE") {
    Write-Step "mitmproxy CA already trusted ($hash)"
    Write-Ok "$target present"
} else {
    Write-Step "Installing the mitmproxy CA via tmpfs overlay ($hash)"
    & $Adb -s $Device push "$MitmCaPem" "$staged" 2>$null | Out-Null
    $overlay = 'CERTS=/system/etc/security/cacerts; STAGE=/data/local/tmp/cacerts-copy; ' +
        'mkdir -p $STAGE && cp $CERTS/* $STAGE/ && cp ' + $staged + ' $STAGE/ && ' +
        'mount -t tmpfs tmpfs $CERTS && cp $STAGE/* $CERTS/ && ' +
        'chown root:root $CERTS/* && chmod 644 $CERTS/* && ' +
        'chcon u:object_r:system_security_cacerts_file:s0 $CERTS/* && echo OVERLAY_OK'
    $result = (Invoke-AdbShell $overlay | Out-String).Trim()
    Invoke-AdbShell "rm -f $staged" | Out-Null
    $head = (Invoke-AdbShell "head -n 1 $target 2>/dev/null" | Out-String).Trim()
    if ($result -match "OVERLAY_OK" -and $head -match "BEGIN CERTIFICATE") {
        $count = (Invoke-AdbShell "ls $SystemCertStore | wc -l" | Out-String).Trim()
        Write-Ok "CA installed, $count certs live in the overlay"
    } else {
        Write-Bad "overlay did not take (result: $result)"
        throw "Could not trust the mitmproxy CA - HTTPS from the game will fail."
    }
}

# 3. Reverse listeners (rangers-api window auto-attaches the battle recorder) -
Write-Step "Starting the reverse listeners"
# start-reverse.ps1 with no -Target launches each listener in its own window and
# returns; call it directly so its readiness checks run in this console too.
& "$PSScriptRoot\start-reverse.ps1" -Force:$Force

$rangers = $NativeTargets | Where-Object { $_.Name -eq "rangers-api" }
$ready = $false
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    if (Test-PortListening -Port $rangers.LocalPort) { $ready = $true; break }
    Start-Sleep -Milliseconds 400
}
if (-not $ready) {
    throw "rangers-api listener never came up on port $($rangers.LocalPort) - check its window."
}
Write-Ok "rangers-api listener up on $($rangers.LocalPort) with the battle recorder attached"

# 4. Redirect the game's direct connections ----------------------------------
& "$PSScriptRoot\redirect-native.ps1"

# 5. Restart the game so it reconnects through the redirect & re-reads certs --
# Done inline (not via launch-game.ps1) because `monkey` prints to stderr, which
# would terminate under that script's Stop policy; here EAP is Continue.
if ($SkipGameRestart) {
    Write-Warn "leaving the game as-is - it will keep its old direct connections until restarted"
} else {
    Write-Step "Restarting $GamePackage so it reconnects through the redirect"
    Invoke-AdbShell "am force-stop $GamePackage" 2>$null | Out-Null
    Invoke-AdbShell "monkey -p $GamePackage -c android.intent.category.LAUNCHER 1" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    $gamePid = (Invoke-AdbShell "pidof $GamePackage" 2>$null | Out-String).Trim()
    if ($gamePid) { Write-Ok "game running as pid $gamePid" } else { Write-Warn "no pid yet - it may still be starting" }
}

$battleDir = Join-Path $CaptureDir "battles"
Write-Host ""
Write-Ok "Recording is armed. Go play a Main Stage by hand now."
Write-Info "Watch the rangers-api mitmproxy window - a captured save prints a banner there."
Write-Info "Per-battle files:  $battleDir\<time>_save_<stage>_sn<sn>_<status>.json"
Write-Info "Full transcript:   $CaptureDir\api-<time>.jsonl"
Write-Host ""
Write-Info "When done:  .\scripts\stop-capture.ps1 -StopProxy"
Write-Info "Then mine any capture later with:  python tools\extract_battles.py --scan captures"
