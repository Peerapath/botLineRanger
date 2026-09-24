# One-shot setup: trust store, proxy, mitmproxy, game.
#
# mitmproxy opens in its own window because it has to keep running while the
# game is used. Close that window (or Ctrl+C in it) to stop capturing, then run
# scripts\stop-capture.ps1 to give the emulator its internet back.

param(
    [switch]$Dump,
    [switch]$Force,
    [string]$Focus = "",
    [switch]$SkipGame
)

. "$PSScriptRoot\..\config.ps1"

Assert-Device

# 1. Trust store -------------------------------------------------------------
$hash = Get-AndroidCertHash -PemPath $MitmCaPem
$head = (Invoke-AdbShell "head -n 1 $SystemCertStore/$hash.0 2>/dev/null" | Out-String).Trim()
if ($head -match "BEGIN CERTIFICATE") {
    Write-Step "Trust store already has the mitmproxy CA ($hash)"
} else {
    Write-Step "Installing the mitmproxy CA"
    & "$PSScriptRoot\install-cert.ps1"
}

# 2. Proxy -------------------------------------------------------------------
& "$PSScriptRoot\set-proxy.ps1"

# 3. mitmproxy in its own window ---------------------------------------------
Write-Step "Starting mitmproxy in a new window"
$childArgs = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\start-proxy.ps1")
if ($Dump)  { $childArgs += "-Dump" }
if ($Force) { $childArgs += "-Force" }
if ($Focus) { $childArgs += @("-Focus", $Focus) }
Start-Process -FilePath "powershell.exe" -ArgumentList $childArgs | Out-Null

$ready = $false
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    if (Test-PortListening -Port $ProxyPort) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if ($ready) {
    Write-Ok "listening on port $ProxyPort"
    if (-not $Dump) { Write-Info "Web UI: http://127.0.0.1:$WebPort" }
} else {
    Write-Bad "mitmproxy did not start listening on $ProxyPort - check the new window for the reason"
    Write-Info "The emulator now has a proxy set but nothing to talk to. Run scripts\stop-capture.ps1 to undo."
    exit 1
}

# 4. Game --------------------------------------------------------------------
if ($SkipGame) {
    Write-Info "Skipping game launch as requested."
} else {
    & "$PSScriptRoot\launch-game.ps1"
}

Write-Host ""
Write-Ok "Capturing. Play through the parts of the game you want to see."
Write-Info "Transcript: $CaptureDir\api-<timestamp>.jsonl"
Write-Info "When finished: .\scripts\stop-capture.ps1 -StopProxy"
