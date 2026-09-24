# Adds iptables DNAT rules inside the emulator so the game's direct
# connections land on mitmproxy instead of the real servers.
#
# The system proxy setting only affects apps using Android's HTTP stack. This
# game's native networking ignores it, so the redirect has to happen at the
# network layer. Needs root, which MuMu provides.
#
#   .\scripts\redirect-native.ps1            add the rules
#   .\scripts\redirect-native.ps1 -Show      list what is currently in the nat table
#   .\scripts\redirect-native.ps1 -Remove    take the rules back out
#
# Start the matching listeners first with scripts\start-reverse.ps1, otherwise
# the game loses connectivity to those servers entirely.

param([switch]$Remove, [switch]$Show)

. "$PSScriptRoot\..\config.ps1"

Assert-Device

& $Adb -s $Device root | Out-Null
& $Adb -s $Device wait-for-device 2>$null | Out-Null
$uid = (Invoke-AdbShell "id -u" | Out-String).Trim()
if ($uid -ne "0") { throw "root is required to change iptables rules, but adbd is uid $uid" }

function Get-RuleSpec {
    param($Target)
    return ("OUTPUT -p tcp -d {0} --dport {1} -j DNAT --to-destination {2}:{3}" -f `
        $Target.Address, $Target.Port, $ProxyHost, $Target.LocalPort)
}

function Test-Rule {
    param($Target)
    $spec = Get-RuleSpec -Target $Target
    $out = (Invoke-AdbShell "iptables -t nat -C $spec 2>/dev/null && echo PRESENT || echo ABSENT" | Out-String).Trim()
    return ($out -match "PRESENT")
}

if ($Show) {
    Write-Step "nat OUTPUT chain on $Device"
    Write-Host (Invoke-AdbShell "iptables -t nat -L OUTPUT -n -v --line-numbers" | Out-String)
    foreach ($target in $NativeTargets) {
        if (Test-Rule -Target $target) {
            Write-Ok ("{0}: {1}:{2} -> {3}:{4}" -f $target.Name, $target.Address, $target.Port, $ProxyHost, $target.LocalPort)
        } else {
            Write-Info ("{0}: no rule" -f $target.Name)
        }
    }
    return
}

if ($Remove) {
    foreach ($target in $NativeTargets) {
        $spec = Get-RuleSpec -Target $target
        $removed = 0
        # A rule can be present more than once if this script was run twice.
        while (Test-Rule -Target $target) {
            Invoke-AdbShell "iptables -t nat -D $spec" | Out-Null
            $removed++
            if ($removed -gt 10) { break }
        }
        if ($removed -gt 0) {
            Write-Ok ("{0}: removed {1} rule(s)" -f $target.Name, $removed)
        } else {
            Write-Info ("{0}: nothing to remove" -f $target.Name)
        }
    }
    Write-Host ""
    Write-Info "The game talks to the real servers again. Restart it to drop existing connections."
    return
}

Write-Step "Redirecting the game's direct connections on $Device"
foreach ($target in $NativeTargets) {
    if (-not (Test-PortListening -Port $target.LocalPort)) {
        Write-Warn ("nothing is listening on host port {0} yet - run scripts\start-reverse.ps1 first, or {1} traffic will fail" -f $target.LocalPort, $target.Name)
    }
    if (Test-Rule -Target $target) {
        Write-Info ("{0}: rule already present" -f $target.Name)
        continue
    }
    $spec = Get-RuleSpec -Target $target
    Invoke-AdbShell "iptables -t nat -A $spec" | Out-Null
    if (Test-Rule -Target $target) {
        Write-Ok ("{0}: {1}:{2} -> {3}:{4}" -f $target.Name, $target.Address, $target.Port, $ProxyHost, $target.LocalPort)
    } else {
        Write-Bad ("{0}: the rule did not stick" -f $target.Name)
    }
}

Write-Host ""
Write-Info "Restart the game so it reconnects through the redirect: .\scripts\launch-game.ps1"
Write-Info "Undo with: .\scripts\redirect-native.ps1 -Remove"
