# Puts things back: clears the emulator proxy and stops the game.
#
# Clearing the proxy matters - with mitmproxy down and the proxy still set, the
# emulator has no working internet connection.

param([switch]$KeepGameRunning, [switch]$StopProxy, [switch]$KeepRedirect)

. "$PSScriptRoot\..\config.ps1"

Assert-Device

Write-Step "Clearing the global proxy"
Invoke-AdbShell "settings put global http_proxy :0" | Out-Null
$current = (Invoke-AdbShell "settings get global http_proxy" | Out-String).Trim()
Write-Ok "global http_proxy = $current"

# Leaving the DNAT rules behind with no listener to receive the traffic would
# cut the game off from its servers entirely, so they come out by default.
if (-not $KeepRedirect) {
    & "$PSScriptRoot\redirect-native.ps1" -Remove
} else {
    Write-Warn "iptables redirect left in place - the game needs the reverse listeners running"
}

if (-not $KeepGameRunning) {
    Write-Step "Force-stopping $GamePackage"
    Invoke-AdbShell "am force-stop $GamePackage" | Out-Null
    Write-Ok "stopped"
}

if ($StopProxy) {
    Write-Step "Stopping mitmproxy on port $ProxyPort"
    $existing = Get-NetTCPConnection -LocalPort $ProxyPort -State Listen -ErrorAction SilentlyContinue
    if ($existing) {
        $owners = $existing | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($owner in $owners) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue }
        Write-Ok "stopped"
    } else {
        Write-Info "nothing listening on $ProxyPort"
    }
}
