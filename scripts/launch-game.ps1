# Restarts the game so it opens fresh through the proxy.
#
# Restarting matters: Android caches the trust store per process, and the
# interesting login and bootstrap calls only happen at startup.

param([switch]$NoRestart)

. "$PSScriptRoot\..\config.ps1"

Assert-Device

$installed = (Invoke-AdbShell "pm list packages $GamePackage" | Out-String).Trim()
if (-not $installed) { throw "$GamePackage is not installed on $Device." }

if (-not $NoRestart) {
    Write-Step "Force-stopping $GamePackage"
    Invoke-AdbShell "am force-stop $GamePackage" | Out-Null
}

Write-Step "Launching $GamePackage"
$output = Invoke-AdbShell "monkey -p $GamePackage -c android.intent.category.LAUNCHER 1" | Out-String
Write-Info $output.Trim()

$gamePid = (Invoke-AdbShell "pidof $GamePackage" | Out-String).Trim()
if ($gamePid) {
    Write-Ok "running as pid $gamePid"
} else {
    Write-Warn "no pid yet - the game may still be starting"
}
