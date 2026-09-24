# Shared settings and helpers. Every script in scripts\ starts by dot-sourcing
# this file:   . "$PSScriptRoot\..\config.ps1"

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$AddonPath   = Join-Path $ProjectRoot "addons\game_api_logger.py"
# Focused recorder for stage-battle enter/save pairs, attached only to the
# rangers-api reverse listener (see start-reverse.ps1). Writes one JSON per
# battle under $CaptureDir\battles.
$BattleAddonPath = Join-Path $ProjectRoot "addons\stage_battle_recorder.py"
$CaptureDir  = Join-Path $ProjectRoot "captures"

$MuMuRoot    = "D:\Program Files\Netease\MuMuPlayer"
$Adb         = Join-Path $MuMuRoot "nx_main\adb.exe"
$MuMuManager = Join-Path $MuMuRoot "nx_main\MuMuManager.exe"

$GamePackage = "com.linecorp.LGRGS"

# 10.0.2.2 is how the host machine looks from inside MuMu's NAT network.
$ProxyHost = "10.0.2.2"
$ProxyPort = 8088
$WebPort   = 8081

$MitmCaPem       = Join-Path $env:USERPROFILE ".mitmproxy\mitmproxy-ca-cert.pem"
$SystemCertStore = "/system/etc/security/cacerts"

# The game's native code ignores the system proxy and dials these out directly,
# so setting http_proxy alone never shows their traffic. Each target gets an
# iptables DNAT rule inside the emulator (redirect-native.ps1) pointing at a
# mitmproxy running in reverse mode on LocalPort (start-reverse.ps1).
$NativeTargets = @(
    [pscustomobject]@{
        Name      = "rangers-api"
        Address   = "147.92.243.243"
        Port      = 443
        LocalPort = 9443
        Upstream  = "https://rangers-api.line-apps.com"
        TlsMin    = ""
    },
    [pscustomobject]@{
        Name      = "game-tcp"
        Address   = "147.92.240.68"
        Port      = 15508
        LocalPort = 9508
        Upstream  = "tcp://147.92.240.68:15508"
        # This channel negotiates a TLS version older than mitmproxy's default
        # floor of TLS1_2, so the handshake is refused without this.
        TlsMin    = "UNBOUNDED"
    }
)

function Write-Step { param([string]$Text) Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    [ok]   $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "    [warn] $Text" -ForegroundColor Yellow }
function Write-Bad  { param([string]$Text) Write-Host "    [fail] $Text" -ForegroundColor Red }
function Write-Info { param([string]$Text) Write-Host "    $Text" -ForegroundColor Gray }

# Android's CA store names files after an MD5 of the DER-encoded subject, first
# four bytes read little-endian. This is openssl's -subject_hash_old, computed
# here with .NET so the scripts do not need openssl on PATH.
function Get-AndroidCertHash {
    param([Parameter(Mandatory = $true)][string]$PemPath)
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($PemPath)
    $md5  = [System.Security.Cryptography.MD5]::Create().ComputeHash($cert.SubjectName.RawData)
    return ('{0:x8}' -f [BitConverter]::ToUInt32($md5, 0))
}

# Ask MuMuManager which instance is actually running, falling back to whatever
# adb already has connected. Override with $env:MITM_DEVICE if needed.
function Get-MuMuDevice {
    if ($env:MITM_DEVICE) { return $env:MITM_DEVICE }

    $candidates = @()
    if (Test-Path $MuMuManager) {
        $raw = ""
        try { $raw = (& $MuMuManager info -v all 2>$null | Out-String) } catch { $raw = "" }
        if ($raw.Trim()) {
            $parsed = $null
            try { $parsed = ConvertFrom-Json $raw } catch { $parsed = $null }
            if ($parsed) {
                if ($parsed.PSObject.Properties.Name -contains "adb_port") {
                    $candidates += $parsed
                } else {
                    foreach ($prop in $parsed.PSObject.Properties) { $candidates += $prop.Value }
                }
            }
        }
    }
    foreach ($c in $candidates) {
        if ($c.is_process_started -eq $true -and $c.adb_port) {
            $ip = "127.0.0.1"
            if ($c.adb_host_ip) { $ip = $c.adb_host_ip }
            return ("{0}:{1}" -f $ip, $c.adb_port)
        }
    }

    if (Test-Path $Adb) {
        $lines = & $Adb devices 2>$null
        foreach ($line in $lines) {
            if ($line -match '^(127\.0\.0\.1:\d+)\s+device\s*$') { return $Matches[1] }
        }
        foreach ($line in $lines) {
            if ($line -match '^(\S+)\s+device\s*$') { return $Matches[1] }
        }
    }
    return $null
}

function Assert-Device {
    if (-not $Device) {
        throw "No running MuMu instance found. Start MuMu Player, then run this again (or set `$env:MITM_DEVICE to an adb serial)."
    }
}

function Invoke-Adb {
    param([Parameter(ValueFromRemainingArguments = $true)]$Arguments)
    & $Adb -s $Device @Arguments
}

function Invoke-AdbShell {
    param([Parameter(Mandatory = $true)][string]$Command)
    & $Adb -s $Device shell $Command
}

function Test-PortListening {
    param([Parameter(Mandatory = $true)][int]$Port)
    $found = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$found
}

$Device = Get-MuMuDevice
