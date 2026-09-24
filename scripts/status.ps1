# Checks every link in the chain and says which one is broken.
# Safe to run at any time - it only reads state.

. "$PSScriptRoot\..\config.ps1"

Write-Host ""
Write-Host "mitmproxy game capture - status" -ForegroundColor White

Write-Step "Host tools"
if (Test-Path $Adb) { Write-Ok "adb: $Adb" } else { Write-Bad "adb missing at $Adb" }
foreach ($tool in @("mitmdump", "mitmweb")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if ($found) { Write-Ok "$tool`: $($found.Source)" } else { Write-Bad "$tool not on PATH" }
}
if (Test-Path $MitmCaPem) {
    $hash = Get-AndroidCertHash -PemPath $MitmCaPem
    Write-Ok "CA certificate: $MitmCaPem (hash $hash)"
} else {
    $hash = $null
    Write-Bad "CA certificate missing at $MitmCaPem - start mitmproxy once to generate it"
}

Write-Step "Emulator"
if (-not $Device) {
    Write-Bad "no running MuMu instance found - start MuMu Player and re-run"
    Write-Host ""
    return
}
Write-Ok "device: $Device"
Write-Info ("android {0} (sdk {1}), abi {2}" -f `
    (Invoke-AdbShell "getprop ro.build.version.release" | Out-String).Trim(), `
    (Invoke-AdbShell "getprop ro.build.version.sdk" | Out-String).Trim(), `
    (Invoke-AdbShell "getprop ro.product.cpu.abi" | Out-String).Trim())

$uid = (Invoke-AdbShell "id -u" | Out-String).Trim()
if ($uid -eq "0") { Write-Ok "adbd is running as root" } else { Write-Warn "adbd is uid $uid - install-cert.ps1 will request root" }

Write-Step "Trust store"
if ($hash) {
    $target = "$SystemCertStore/$hash.0"
    $head = (Invoke-AdbShell "head -n 1 $target 2>/dev/null" | Out-String).Trim()
    if ($head -match "BEGIN CERTIFICATE") {
        Write-Ok "mitmproxy CA is installed at $target"
    } else {
        Write-Bad "mitmproxy CA is NOT in the system store - run scripts\install-cert.ps1"
    }
}

Write-Step "Proxy"
$expected = "{0}:{1}" -f $ProxyHost, $ProxyPort
$current  = (Invoke-AdbShell "settings get global http_proxy" | Out-String).Trim()
if ($current -eq $expected) {
    Write-Ok "emulator global http_proxy = $current"
} elseif ($current -and $current -ne "null" -and $current -ne ":0") {
    Write-Warn "emulator global http_proxy = $current (expected $expected)"
} else {
    Write-Bad "emulator has no proxy set - run scripts\set-proxy.ps1"
}

$listening = Get-NetTCPConnection -LocalPort $ProxyPort -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    $owners = $listening | Select-Object -ExpandProperty OwningProcess -Unique
    $names = @()
    foreach ($owner in $owners) {
        $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
        if ($proc) { $names += "$($proc.ProcessName) (pid $owner)" } else { $names += "pid $owner" }
    }
    Write-Ok "host port $ProxyPort is listening - $($names -join ', ')"
} else {
    Write-Bad "nothing is listening on host port $ProxyPort - run scripts\start-proxy.ps1"
}

# Drive a real request through the proxy from inside the emulator. This proves
# the whole path at once - routing, firewall and mitmproxy's listener.
if ($listening) {
    $plain = (Invoke-AdbShell "curl -s -o /dev/null -w '%{http_code}' --max-time 8 -x ${ProxyHost}:${ProxyPort} http://example.com 2>/dev/null" | Out-String).Trim()
    if ($plain -match '^[1-5]\d\d$') {
        Write-Ok "HTTP through the proxy works (example.com returned $plain)"
    } else {
        Write-Bad "the emulator cannot reach ${ProxyHost}:${ProxyPort} - check Windows Firewall"
    }

    # A 200 here means the emulator trusted mitmproxy's certificate, which is
    # the thing install-cert.ps1 exists to achieve.
    $secure = (Invoke-AdbShell "curl -s -o /dev/null -w '%{http_code}' --max-time 8 -x ${ProxyHost}:${ProxyPort} https://example.com 2>/dev/null" | Out-String).Trim()
    if ($secure -match '^[1-5]\d\d$') {
        Write-Ok "HTTPS is being decrypted and trusted (example.com returned $secure)"
    } else {
        Write-Bad "HTTPS through the proxy is rejected - the CA is not trusted yet, run scripts\install-cert.ps1"
    }
}

Write-Step "Game"
$installed = (Invoke-AdbShell "pm list packages $GamePackage" | Out-String).Trim()
if ($installed) { Write-Ok "$GamePackage is installed" } else { Write-Bad "$GamePackage is not installed" }
$gamePid = (Invoke-AdbShell "pidof $GamePackage" | Out-String).Trim()
if ($gamePid) { Write-Ok "running as pid $gamePid" } else { Write-Info "not running" }

Write-Step "Captures"
if (Test-Path $CaptureDir) {
    $latest = Get-ChildItem -Path $CaptureDir -Filter "api-*.jsonl" -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        $lines = (Get-Content $latest.FullName | Measure-Object -Line).Lines
        Write-Ok "$($latest.Name) - $lines entries, last written $($latest.LastWriteTime)"
    } else {
        Write-Info "no transcripts yet"
    }
} else {
    Write-Info "no captures directory yet"
}
Write-Host ""
