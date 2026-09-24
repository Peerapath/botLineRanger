# Removes the mitmproxy CA from Android's system trust store, undoing
# install-cert.ps1.

. "$PSScriptRoot\..\config.ps1"

Assert-Device
Write-Host "Device: $Device"

if (-not (Test-Path $MitmCaPem)) {
    throw "mitmproxy CA not found at $MitmCaPem, so its hash cannot be computed."
}

$hash   = Get-AndroidCertHash -PemPath $MitmCaPem
$target = "$SystemCertStore/$hash.0"

Write-Step "Switching adbd to root"
& $Adb -s $Device root | Out-Null
& $Adb -s $Device wait-for-device 2>$null | Out-Null

Write-Step "Removing $target"
Invoke-AdbShell "mount -o rw,remount / 2>/dev/null; mount -o rw,remount /system 2>/dev/null; true" | Out-Null
Invoke-AdbShell "rm -f $target" | Out-Null

$still = (Invoke-AdbShell "ls $target 2>/dev/null" | Out-String).Trim()
if ($still) {
    Write-Bad "$target is still present"
} else {
    Write-Ok "certificate removed"
}
