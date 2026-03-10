#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Auto-setup script for IBC + IB Gateway on Windows VPS.
    Run this once as Administrator. On every subsequent reboot,
    IB Gateway will launch and log in automatically.

.WHAT THIS DOES
    1. Uses pre-configured IBKR paper account credentials
    2. Detects your installed IB Gateway version automatically
    3. Downloads the latest IBC release from GitHub
    4. Writes config.ini and StartGateway.bat
    5. Registers a Task Scheduler job that fires at every boot
    6. Enables Windows auto-logon so the VPS desktop comes up unattended

.PREREQUISITE
    IB Gateway must already be installed before running this script.
    Download: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
    Install to the default path (C:\Jts) when prompted.

.USAGE
    Right-click PowerShell -> Run as Administrator
    cd C:\path\to\this\script
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\setup_ibc.ps1
#>

# ─── Paths ────────────────────────────────────────────────────────────────────
$GatewayPath = "C:\Jts"
$IbcPath     = "C:\IBC"

# ─── Credentials (paper account) ──────────────────────────────────────────────
$ibkrUser    = "debamamv07"
$ibkrPass    = "dev13579"
$tradingMode = "paper"
$port        = 4002

# ─── Helpers ──────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "`n[*] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "    [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "`n[ERROR] $msg`n" -ForegroundColor Red; exit 1 }

# ─── Banner ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "   IBC Auto-Setup for Windows VPS" -ForegroundColor Yellow
Write-Host "   Kaizen Intraday Semis - Production" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "  This script will:" -ForegroundColor White
Write-Host "    - Download and install IBC" -ForegroundColor Gray
Write-Host "    - Configure auto-login for IB Gateway (paper, port 4002)" -ForegroundColor Gray
Write-Host "    - Register a boot-time Task Scheduler job" -ForegroundColor Gray
Write-Host "    - Enable Windows auto-logon" -ForegroundColor Gray
Write-Host ""

# ─── Step 0: Only ask for Windows password (everything else is pre-configured) ─
Write-Host "  IBKR credentials are pre-configured (paper account)." -ForegroundColor White
Write-Host ""
Write-Host "  Windows auto-logon — enter the password for this Windows account." -ForegroundColor White
Write-Host "  This is needed so the VPS desktop opens automatically on reboot." -ForegroundColor Gray
$winPassSS = Read-Host "  Windows Login Password" -AsSecureString
$winPass   = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                 [Runtime.InteropServices.Marshal]::SecureStringToBSTR($winPassSS))
if (-not $winPass) { Write-Fail "Windows password cannot be empty." }

Write-Host ""
Write-Host "  --------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  IBKR User     : $ibkrUser" -ForegroundColor White
Write-Host "  Trading Mode  : $tradingMode (port $port)" -ForegroundColor White
Write-Host "  IBC Path      : $IbcPath" -ForegroundColor White
Write-Host "  Gateway Path  : $GatewayPath" -ForegroundColor White
Write-Host "  --------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

$confirm = Read-Host "  Looks good? Press Enter to continue, or Ctrl+C to cancel"

# ─── Step 1: Detect IB Gateway ────────────────────────────────────────────────
Write-Step "Detecting IB Gateway installation..."

if (-not (Test-Path $GatewayPath)) {
    Write-Fail "IB Gateway not found at $GatewayPath.`n  Please install it first from:`n  https://www.interactivebrokers.com/en/trading/ibgateway-stable.php"
}

# IB Gateway installs to C:\Jts\ibgateway\<version>\
$versionDirs = Get-ChildItem "$GatewayPath\ibgateway" -Directory -ErrorAction SilentlyContinue |
               Sort-Object Name -Descending

if ($versionDirs) {
    $twsVersion = $versionDirs[0].Name
    Write-OK "IB Gateway detected — version $twsVersion at $GatewayPath"
} else {
    # Fallback: ask user
    Write-Warn "Could not auto-detect version from $GatewayPath\ibgateway\"
    Write-Host "  Check the folder manually and enter the version number." -ForegroundColor Gray
    Write-Host "  Example: if you see C:\Jts\ibgateway\10.30\ then enter 10.30" -ForegroundColor Gray
    $twsVersion = Read-Host "  IB Gateway version"
    if (-not $twsVersion) { Write-Fail "Version is required." }
    Write-OK "Using version $twsVersion"
}

# ─── Step 2: Download Latest IBC ──────────────────────────────────────────────
Write-Step "Downloading latest IBC from GitHub..."

try {
    $release = Invoke-RestMethod "https://api.github.com/repos/IbcAlpha/IBC/releases/latest" `
                   -UseBasicParsing -ErrorAction Stop

    $asset = $release.assets | Where-Object { $_.name -like "IBCWindows*.zip" } | Select-Object -First 1
    if (-not $asset) { Write-Fail "Could not find IBCWindows zip in release assets." }

    $zipPath = "$env:TEMP\IBC_latest.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing -ErrorAction Stop

    Write-OK "Downloaded IBC $($release.tag_name) ($($asset.name))"
}
catch {
    Write-Fail "Failed to download IBC. Check your internet connection.`n  Error: $_"
}

# ─── Step 3: Install IBC ──────────────────────────────────────────────────────
Write-Step "Installing IBC to $IbcPath..."

if (Test-Path $IbcPath) {
    Write-Warn "Existing IBC folder found — backing up to ${IbcPath}_backup"
    if (Test-Path "${IbcPath}_backup") { Remove-Item "${IbcPath}_backup" -Recurse -Force }
    Rename-Item $IbcPath "${IbcPath}_backup"
}

New-Item -ItemType Directory -Path $IbcPath -Force | Out-Null
Expand-Archive -Path $zipPath -DestinationPath $IbcPath -Force
New-Item -ItemType Directory -Path "$IbcPath\Logs" -Force | Out-Null

Write-OK "IBC installed to $IbcPath"

# ─── Step 4: Write config.ini ─────────────────────────────────────────────────
Write-Step "Writing $IbcPath\config.ini..."

$configContent = @"
# IBC Configuration
# Auto-generated by setup_ibc.ps1
# Edit manually if credentials change.

IbLoginId=$ibkrUser
IbPassword=$ibkrPass
TradingMode=$tradingMode
IbDir=$GatewayPath

AcceptIncomingConnectionAction=accept
ReadonlyLogin=no
ExistingSessionDetectedAction=primary
AcceptNonBrokerageAccountWarning=yes
ReloginAfterSecondFactorAuthenticationTimeout=yes
SecondFactorAuthenticationExpiryAction=restart

# Suppress daily restart dialog
AcceptBidAsk=no
LogComponents=never
"@

$configContent | Set-Content "$IbcPath\config.ini" -Encoding UTF8
Write-OK "config.ini written"

# ─── Step 5: Write StartGateway.bat ───────────────────────────────────────────
Write-Step "Writing $IbcPath\StartGateway.bat..."

$batContent = @"
@echo off
REM ── IBC Gateway Launcher ──────────────────────────────────────────────────
REM Auto-generated by setup_ibc.ps1

set TWS_MAJOR_VRSN=$twsVersion
set IBC_INI=$IbcPath\config.ini
set TWSUSERID=$ibkrUser
set TWSPASSWORD=$ibkrPass
set TRADING_MODE=$tradingMode
set IBC_PATH=$IbcPath
set TWS_PATH=$GatewayPath
set LOG_PATH=$IbcPath\Logs
set JAVA_PATH=
set HIDE_CONSOLE=yes

cd /D "%IBC_PATH%"
call "%IBC_PATH%\Scripts\DisplayBannerAndLaunch.bat"
"@

$batContent | Set-Content "$IbcPath\StartGateway.bat" -Encoding ASCII
Write-OK "StartGateway.bat written"

# ─── Step 6: Task Scheduler ───────────────────────────────────────────────────
Write-Step "Registering Task Scheduler job 'IBC_Gateway'..."

$taskName = "IBC_Gateway"

# Remove old task if it exists
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction -Execute "$IbcPath\StartGateway.bat"

# Trigger: at boot + a 30s delay to let Windows settle
$trigger  = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName  $taskName `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

Write-OK "Task '$taskName' registered — runs 30s after every boot"

# ─── Step 7: Windows Auto-Logon ───────────────────────────────────────────────
Write-Step "Enabling Windows auto-logon..."

$regPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty $regPath "AutoAdminLogon"   "1"           -Type String
Set-ItemProperty $regPath "DefaultUserName"  "$env:USERNAME" -Type String
Set-ItemProperty $regPath "DefaultPassword"  "$winPass"    -Type String
Set-ItemProperty $regPath "DefaultDomainName" "$env:USERDOMAIN" -Type String

Write-OK "Auto-logon enabled for $env:USERDOMAIN\$env:USERNAME"

# ─── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "   Setup Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  IBC Path      : $IbcPath" -ForegroundColor White
Write-Host "  Config        : $IbcPath\config.ini" -ForegroundColor White
Write-Host "  Launcher      : $IbcPath\StartGateway.bat" -ForegroundColor White
Write-Host "  Gateway Port  : $port ($tradingMode)" -ForegroundColor White
Write-Host "  Task          : IBC_Gateway (fires 30s after boot)" -ForegroundColor White
Write-Host "  Auto-logon    : Enabled for $env:USERNAME" -ForegroundColor White
Write-Host ""
Write-Host "  NEXT STEPS:" -ForegroundColor Yellow
Write-Host "    1. Reboot the VPS" -ForegroundColor White
Write-Host "    2. Windows will log in automatically" -ForegroundColor White
Write-Host "    3. IBC will launch IB Gateway and log in to IBKR" -ForegroundColor White
Write-Host "    4. Your Python trading script connects on port $port" -ForegroundColor White
Write-Host ""
Write-Host "  To update credentials later, edit:" -ForegroundColor Gray
Write-Host "    $IbcPath\config.ini  (IbLoginId / IbPassword)" -ForegroundColor Gray
Write-Host "    $IbcPath\StartGateway.bat  (TWSUSERID / TWSPASSWORD)" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
