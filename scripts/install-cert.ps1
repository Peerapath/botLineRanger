# Installs the mitmproxy CA into Android's *system* trust store.
#
# Apps that target API 24 or newer ignore user-installed CAs, so dropping the
# certificate into the user store is not enough for a game. This needs root,
# which MuMu provides.
#
# Reverse it with remove-cert.ps1.

. "$PSScriptRoot\..\config.ps1"

Assert-Device
Write-Host "Device: $Device"

if (-not (Test-Path $MitmCaPem)) {
    throw "mitmproxy CA not found at $MitmCaPem. Start mitmproxy once so it generates its CA, then run this again."
}

$hash   = Get-AndroidCertHash -PemPath $MitmCaPem
$target = "$SystemCertStore/$hash.0"
$staged = "/data/local/tmp/$hash.0"
Write-Step "Certificate hash is $hash -> $target"

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
if (-not $isRoot) { throw "adbd did not come back as root. Enable root in MuMu's settings and try again." }
Write-Ok "running as root"

Write-Step "Remounting /system read-write"
Invoke-AdbShell "mount -o rw,remount / 2>/dev/null; mount -o rw,remount /system 2>/dev/null; true" | Out-Null
$probe = (Invoke-AdbShell "touch $SystemCertStore/.probe 2>/dev/null && echo WRITABLE && rm -f $SystemCertStore/.probe" | Out-String).Trim()
if ($probe -notmatch "WRITABLE") { throw "$SystemCertStore is still read-only. The certificate cannot be installed." }
Write-Ok "$SystemCertStore is writable"

# Match the SELinux label the certificates already there are using.
$label = "u:object_r:system_security_cacerts_file:s0"
$sample = (Invoke-AdbShell "ls -Z $SystemCertStore 2>/dev/null | head -n 1" | Out-String).Trim()
if ($sample -match '(u:object_r:\S+:s0)') { $label = $Matches[1] }
Write-Info "SELinux label: $label"

Write-Step "Copying the certificate in"
& $Adb -s $Device push "$MitmCaPem" "$staged" | Out-Null
Invoke-AdbShell "cp $staged $target" | Out-Null
Invoke-AdbShell "chmod 644 $target" | Out-Null
Invoke-AdbShell "chown root:root $target" | Out-Null
Invoke-AdbShell "chcon $label $target 2>/dev/null; true" | Out-Null
Invoke-AdbShell "rm -f $staged" | Out-Null

Write-Step "Verifying"
$localSize  = (Get-Item $MitmCaPem).Length
$remoteSize = (Invoke-AdbShell "wc -c < $target 2>/dev/null" | Out-String).Trim()
$firstLine  = (Invoke-AdbShell "head -n 1 $target 2>/dev/null" | Out-String).Trim()

if ($firstLine -notmatch "BEGIN CERTIFICATE") {
    Write-Bad "$target does not look like a PEM certificate (first line: '$firstLine')"
    throw "Certificate install failed."
}
if ("$remoteSize" -ne "$localSize") {
    Write-Warn "size on device ($remoteSize B) differs from the local file ($localSize B)"
} else {
    Write-Ok "$target installed, $remoteSize bytes"
}
Write-Info (Invoke-AdbShell "ls -laZ $target" | Out-String).Trim()

Write-Host ""
Write-Ok "Done. Force-stop the game before capturing so it re-reads the trust store."
Write-Info "MuMu can reset /system when the instance restarts - re-run this script if capture stops working."
