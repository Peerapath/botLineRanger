# Starts mitmproxy with the game_api_logger addon attached.
#
#   .\scripts\start-proxy.ps1                 mitmweb UI on http://127.0.0.1:8081
#   .\scripts\start-proxy.ps1 -Dump           console output only
#   .\scripts\start-proxy.ps1 -Force          stop whatever already holds port 8080
#   .\scripts\start-proxy.ps1 -Focus lgrgs    console shows only hosts matching "lgrgs"
#
# This runs in the foreground. Stop it with Ctrl+C.

param(
    [switch]$Dump,
    [switch]$Force,
    [string]$Focus = "",
    [string]$Noise = ""
)

. "$PSScriptRoot\..\config.ps1"

if (-not (Test-Path $AddonPath)) { throw "Addon not found at $AddonPath" }

$existing = Get-NetTCPConnection -LocalPort $ProxyPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $owners = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    $names  = @()
    foreach ($owner in $owners) {
        $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
        if ($proc) { $names += "$($proc.ProcessName) (pid $owner)" } else { $names += "pid $owner" }
    }
    $joined = $names -join ", "
    if ($Force) {
        Write-Warn "stopping $joined to free port $ProxyPort"
        foreach ($owner in $owners) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue }
    } else {
        Write-Bad "port $ProxyPort is already held by $joined"
        Write-Info "That instance has no addon attached, so nothing will be logged here."
        Write-Info "Re-run with -Force to stop it, or change `$ProxyPort in config.ps1."
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $CaptureDir | Out-Null
$stamp    = Get-Date -Format "yyyyMMdd-HHmmss"
$flowFile = Join-Path $CaptureDir "flows-$stamp.mitm"

$mitmArgs = @(
    "--listen-host", "0.0.0.0",
    "--listen-port", "$ProxyPort",
    "-s", "$AddonPath",
    "--set", "game_capture_dir=$CaptureDir",
    "-w", "$flowFile"
)
if ($Focus) { $mitmArgs += @("--set", "game_focus=$Focus") }
if ($Noise) { $mitmArgs += @("--set", "game_noise=$Noise") }

Write-Step "Listening on 0.0.0.0:$ProxyPort  (the emulator reaches it at ${ProxyHost}:${ProxyPort})"
Write-Info "Replayable flows: $flowFile"
Write-Info "Readable transcript: $CaptureDir\api-<timestamp>.jsonl"

if ($Dump) {
    # flow_detail=0 silences mitmdump's own summary so only the addon prints.
    $mitmArgs += @("--set", "flow_detail=0")
    Write-Info "Press Ctrl+C to stop."
    & mitmdump @mitmArgs
} else {
    $mitmArgs += @("--web-host", "127.0.0.1", "--web-port", "$WebPort")
    Write-Info "Web UI: http://127.0.0.1:$WebPort"
    Write-Info "Press Ctrl+C to stop."
    & mitmweb @mitmArgs
}
