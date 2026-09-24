# Runs one mitmproxy per redirected target, each in reverse mode.
#
# Reverse mode is what makes the iptables redirect work: the DNAT rewrites the
# destination and loses the original one, so each listener has to be told which
# upstream it is standing in for.
#
#   .\scripts\start-reverse.ps1                  start every target, each in its own window
#   .\scripts\start-reverse.ps1 -Target rangers-api   run just this one in the foreground
#   .\scripts\start-reverse.ps1 -Force           stop whatever holds the ports first

param(
    [string]$Target = "",
    [switch]$Force
)

. "$PSScriptRoot\..\config.ps1"

if (-not (Test-Path $AddonPath)) { throw "Addon not found at $AddonPath" }
New-Item -ItemType Directory -Force -Path $CaptureDir | Out-Null

function Clear-Port {
    param([int]$Port, [string]$Label)
    $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $existing) { return $true }
    $owners = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    if ($Force) {
        foreach ($owner in $owners) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue }
        Write-Warn "stopped the process holding port $Port"
        return $true
    }
    Write-Bad "port $Port ($Label) is already in use - re-run with -Force"
    return $false
}

# Foreground: one target, output stays in this window.
if ($Target) {
    $chosen = $NativeTargets | Where-Object { $_.Name -eq $Target }
    if (-not $chosen) {
        $names = ($NativeTargets | ForEach-Object { $_.Name }) -join ", "
        throw "Unknown target '$Target'. Known targets: $names"
    }
    if (-not (Clear-Port -Port $chosen.LocalPort -Label $chosen.Name)) { exit 1 }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $flowFile = Join-Path $CaptureDir ("flows-{0}-{1}.mitm" -f $chosen.Name, $stamp)
    Write-Step ("{0}: listening on 0.0.0.0:{1}, forwarding to {2}" -f $chosen.Name, $chosen.LocalPort, $chosen.Upstream)

    $mitmArgs = @(
        "--mode", ("reverse:" + $chosen.Upstream),
        "--listen-host", "0.0.0.0",
        "--listen-port", "$($chosen.LocalPort)",
        "-s", "$AddonPath",
        "--set", "game_capture_dir=$CaptureDir",
        "--set", "game_noise=",
        "--set", "flow_detail=0",
        "-w", "$flowFile"
    )
    # The stage-battle enter/save exchange rides the rangers-api channel, so the
    # focused recorder only needs to watch that one. It writes per-battle JSON
    # files and prints a loud banner the moment a save is captured.
    if ($chosen.Name -eq "rangers-api" -and (Test-Path $BattleAddonPath)) {
        $battleDir = Join-Path $CaptureDir "battles"
        New-Item -ItemType Directory -Force -Path $battleDir | Out-Null
        $mitmArgs += @("-s", "$BattleAddonPath", "--set", "battle_dir=$battleDir")
        Write-Info "stage-battle recorder attached -> $battleDir"
    }
    if ($chosen.TlsMin) {
        $mitmArgs += @("--set", "tls_version_client_min=$($chosen.TlsMin)")
        Write-Info "accepting TLS down to $($chosen.TlsMin) on this channel"
    }
    Write-Info "Press Ctrl+C to stop."
    & mitmdump @mitmArgs
    return
}

# No target named: launch each one in its own window.
foreach ($t in $NativeTargets) {
    if (-not (Clear-Port -Port $t.LocalPort -Label $t.Name)) { continue }
    $childArgs = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$PSCommandPath", "-Target", $t.Name)
    if ($Force) { $childArgs += "-Force" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $childArgs | Out-Null
    Write-Step ("{0}: starting on port {1} -> {2}" -f $t.Name, $t.LocalPort, $t.Upstream)
}

foreach ($t in $NativeTargets) {
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $t.LocalPort) { $ready = $true; break }
        Start-Sleep -Milliseconds 400
    }
    if ($ready) {
        Write-Ok ("{0} is listening on {1}" -f $t.Name, $t.LocalPort)
    } else {
        Write-Bad ("{0} never started listening on {1} - check its window" -f $t.Name, $t.LocalPort)
    }
}

Write-Host ""
Write-Info "Now add the redirect: .\scripts\redirect-native.ps1"
