# Removes the emulator's system-wide HTTP proxy so it reaches the internet
# directly again.

. "$PSScriptRoot\..\config.ps1"

Assert-Device

Write-Step "Clearing the global proxy on $Device"
Invoke-AdbShell "settings put global http_proxy :0" | Out-Null

$current = (Invoke-AdbShell "settings get global http_proxy" | Out-String).Trim()
Write-Ok "global http_proxy = $current"
