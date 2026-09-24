# Points the emulator's system-wide HTTP proxy at mitmproxy on the host.

. "$PSScriptRoot\..\config.ps1"

Assert-Device

$value = "{0}:{1}" -f $ProxyHost, $ProxyPort
Write-Step "Setting the global proxy to $value on $Device"
Invoke-AdbShell "settings put global http_proxy $value" | Out-Null

$current = (Invoke-AdbShell "settings get global http_proxy" | Out-String).Trim()
if ($current -eq $value) {
    Write-Ok "global http_proxy = $current"
} else {
    Write-Bad "expected '$value' but the device reports '$current'"
}

Write-Info "Clear it again with scripts\clear-proxy.ps1 (the emulator has no internet while mitmproxy is down)."
