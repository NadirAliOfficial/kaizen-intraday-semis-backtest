#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Auto-setup script for IBC + IB Gateway on Windows VPS.
    Run once as Administrator. On every subsequent reboot,
    IB Gateway launches and logs in automatically.

.PREREQUISITE
    IB Gateway must already be installed to C:\Jts before running.
    Download: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

.USAGE
    Right-click PowerShell -> Run as Administrator
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\setup_ibc.ps1
#>

# ── Config ────────────────────────────────────────────────────────────────────
$GatewayPath = "C:\Jts"
$IbcPath     = "C:\IBC"
$ibkrUser    = "debamamv07"
$ibkrPass    = "dev13579"
$tradingMode = "paper"
$port        = 4002

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "`n[*] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "    [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "`n[ERROR] $msg`n" -ForegroundColor Red; exit 1 }

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "   IBC Auto-Setup for Windows VPS" -ForegroundColor Yellow
Write-Host "   Kaizen Intraday Semis - Production" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "  IBKR User    : $ibkrUser" -ForegroundColor White
Write-Host "  Mode         : $tradingMode (port $port)" -ForegroundColor White
Write-Host "  IBC Path     : $IbcPath" -ForegroundColor White
Write-Host "  Gateway Path : $GatewayPath" -ForegroundColor White
Write-Host ""

# ── Step 0: Windows password for auto-logon ───────────────────────────────────
$winPassSS = Read-Host "  Enter Windows login password (for auto-logon)" -AsSecureString
$winPass   = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                 [Runtime.InteropServices.Marshal]::SecureStringToBSTR($winPassSS))
if (-not $winPass) { Write-Fail "Windows password cannot be empty." }

Write-Host ""
Read-Host "  Ready. Press Enter to start, or Ctrl+C to cancel"

# ── Step 1: Detect IB Gateway ─────────────────────────────────────────────────
Write-Step "Detecting IB Gateway..."

if (-not (Test-Path $GatewayPath)) {
    Write-Fail "IB Gateway not found at $GatewayPath. Install it first."
}

$versionDirs = Get-ChildItem "$GatewayPath\ibgateway" -Directory -ErrorAction SilentlyContinue |
               Sort-Object Name -Descending

if ($versionDirs) {
    $twsVersion = $versionDirs[0].Name
    Write-OK "Detected version $twsVersion"
} else {
    Write-Warn "Could not auto-detect version from $GatewayPath\ibgateway\"
    $twsVersion = Read-Host "  Enter TWS version manually (e.g. 10.30)"
    if (-not $twsVersion) { Write-Fail "Version is required." }
}

# ── Step 2: Download IBC ──────────────────────────────────────────────────────
Write-Step "Downloading latest IBC from GitHub..."

try {
    $release = Invoke-RestMethod "https://api.github.com/repos/IbcAlpha/IBC/releases/latest" -UseBasicParsing
    $asset   = $release.assets | Where-Object { $_.name -like "IBCWindows*.zip" } | Select-Object -First 1
    if (-not $asset) {
        $asset = $release.assets | Where-Object { $_.name -like "*Windows*.zip" } | Select-Object -First 1
    }
    if (-not $asset) {
        $asset = $release.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
    }
    if (-not $asset) { Write-Fail "No zip found in IBC GitHub release. Assets: $(($release.assets | Select-Object -ExpandProperty name) -join ', ')" }
    $zipPath = "$env:TEMP\IBC_latest.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
    Write-OK "Downloaded IBC $($release.tag_name)"
} catch {
    Write-Fail "Download failed: $_"
}

# ── Step 3: Install IBC ───────────────────────────────────────────────────────
Write-Step "Installing IBC to $IbcPath..."

if (Test-Path $IbcPath) {
    Write-Warn "Backing up existing IBC to ${IbcPath}_backup"
    if (Test-Path "${IbcPath}_backup") { Remove-Item "${IbcPath}_backup" -Recurse -Force }
    Rename-Item $IbcPath "${IbcPath}_backup"
}

New-Item -ItemType Directory -Path $IbcPath -Force | Out-Null
Expand-Archive -Path $zipPath -DestinationPath $IbcPath -Force
New-Item -ItemType Directory -Path "$IbcPath\Logs" -Force | Out-Null
Write-OK "IBC installed"

# ── Step 4: Write config.ini ──────────────────────────────────────────────────
Write-Step "Writing config.ini..."

# config.ini must be ASCII (no BOM) — Java Properties parser strips backslashes,
# so use forward slashes for paths inside the ini file.
$gatewayPathFwd = $GatewayPath -replace '\\', '/'
$lines = @(
    "IbLoginId=$ibkrUser",
    "IbPassword=$ibkrPass",
    "TradingMode=$tradingMode",
    "IbDir=$gatewayPathFwd",
    "AcceptIncomingConnectionAction=accept",
    "ReadonlyLogin=no",
    "ExistingSessionDetectedAction=primary",
    "AcceptNonBrokerageAccountWarning=yes",
    "ReloginAfterSecondFactorAuthenticationTimeout=yes",
    "SecondFactorAuthenticationExpiryAction=restart",
    "LogComponents=never"
)
[System.IO.File]::WriteAllLines("$IbcPath\config.ini", $lines, [System.Text.Encoding]::ASCII)
Write-OK "config.ini written (ASCII, no BOM)"

# ── Step 4b: Install Java 17 (required by IB Gateway 10.x) ───────────────────
Write-Step "Installing Java 17 (required by IB Gateway 10.x)..."

$javaExe = "C:\Program Files\Eclipse Adoptium\jre-17.0.11.9-hotspot\bin\java.exe"
if (-not (Test-Path $javaExe)) {
    $javaUrl = "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jre_x64_windows_hotspot_17.0.11_9.msi"
    $javaMsi = "$env:TEMP\java17.msi"
    Invoke-WebRequest -Uri $javaUrl -OutFile $javaMsi -UseBasicParsing
    Start-Process msiexec.exe -ArgumentList "/i `"$javaMsi`" /quiet /norestart" -Wait
    Write-OK "Java 17 installed"
} else {
    Write-OK "Java 17 already installed"
}

# ── Step 5: Write StartGateway.bat ────────────────────────────────────────────
Write-Step "Writing StartGateway.bat..."

# IB Gateway 10.x requires Java 17 + module access flags for Swing reflection
$javaCmd = "`"$javaExe`" --add-opens java.desktop/javax.swing=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED -cp `"$IbcPath\IBC.jar;$GatewayPath\ibgateway\$twsVersion\jars\*`" ibcalpha.ibc.IbcGateway `"$IbcPath\config.ini`" $twsVersion `"$GatewayPath\ibgateway\$twsVersion`" $tradingMode"
$bat = @("@echo off", $javaCmd)
Set-Content "$IbcPath\StartGateway.bat" -Value $bat -Encoding ASCII
Write-OK "StartGateway.bat written"

# ── Step 6: Task Scheduler ────────────────────────────────────────────────────
Write-Step "Registering Task Scheduler job 'IBC_Gateway'..."

$taskName = "IBC_Gateway"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action    = New-ScheduledTaskAction -Execute "$IbcPath\StartGateway.bat"
$trigger   = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"
$settings  = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-OK "Task 'IBC_Gateway' registered (fires 30s after every boot)"

# ── Step 7: Windows Auto-Logon ────────────────────────────────────────────────
Write-Step "Enabling Windows auto-logon..."

$reg = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty $reg "AutoAdminLogon"    "1"               -Type String
Set-ItemProperty $reg "DefaultUserName"   "$env:USERNAME"   -Type String
Set-ItemProperty $reg "DefaultPassword"   "$winPass"        -Type String
Set-ItemProperty $reg "DefaultDomainName" "$env:USERDOMAIN" -Type String

Write-OK "Auto-logon enabled for $env:USERNAME"

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "   Setup Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  IBC Path     : $IbcPath" -ForegroundColor White
Write-Host "  Config       : $IbcPath\config.ini" -ForegroundColor White
Write-Host "  Launcher     : $IbcPath\StartGateway.bat" -ForegroundColor White
Write-Host "  Port         : $port ($tradingMode)" -ForegroundColor White
Write-Host "  Task         : IBC_Gateway (30s after boot)" -ForegroundColor White
Write-Host "  Auto-logon   : Enabled for $env:USERNAME" -ForegroundColor White
Write-Host ""
Write-Host "  NEXT: Reboot the VPS." -ForegroundColor Yellow
Write-Host "  Boot flow: Windows auto-logon -> IBC -> IB Gateway -> IBKR login -> port $port ready" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
