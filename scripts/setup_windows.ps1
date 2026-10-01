# ============================================================================
#  Forex Bot — one-shot Windows server setup
#  Run this in an ELEVATED PowerShell (Run as Administrator) on the AWS server.
#  It installs Python, Git, GitHub CLI, and MetaTrader 5, pulls the bot, and
#  starts the web dashboard. After this you use everything from a browser.
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host "`n[1/7] Installing Chocolatey (package manager)..." -ForegroundColor Cyan
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

Write-Host "`n[2/7] Installing Python 3.11, Git, GitHub CLI..." -ForegroundColor Cyan
choco install -y python311 git gh
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
            [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "`n[3/7] Installing MetaTrader 5 terminal..." -ForegroundColor Cyan
Invoke-WebRequest "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" `
    -OutFile "$env:TEMP\mt5setup.exe"
Start-Process "$env:TEMP\mt5setup.exe" -ArgumentList "/auto" -Wait

Write-Host "`n[4/7] Sign in to GitHub (a code will appear; open the link and enter it)..." -ForegroundColor Yellow
gh auth login --hostname github.com --git-protocol https --web

Write-Host "`n[5/7] Downloading the bot..." -ForegroundColor Cyan
Set-Location C:\
if (Test-Path C:\forex-bot) { Remove-Item -Recurse -Force C:\forex-bot }
gh repo clone inedjosh/forex-bot
Set-Location C:\forex-bot

Write-Host "`n[6/7] Installing Python packages (this takes a few minutes)..." -ForegroundColor Cyan
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install MetaTrader5 cryptography

# Open the Windows firewall for the dashboard
New-NetFirewallRule -DisplayName "ForexBot 5055" -Direction Inbound -Protocol TCP `
    -LocalPort 5055 -Action Allow -ErrorAction SilentlyContinue | Out-Null

Write-Host "`n[7/7] Creating your admin login..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe scripts\manage_users.py add admin@forexbot.local --password "ChangeMe12345" --admin

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " SETUP COMPLETE." -ForegroundColor Green
Write-Host " Admin login:  admin@forexbot.local  /  ChangeMe12345" -ForegroundColor Green
Write-Host " Starting the dashboard now. Leave this window OPEN." -ForegroundColor Green
Write-Host " Open it from your Mac browser at:  http://<THIS-SERVER-IP>:5055" -ForegroundColor Green
Write-Host "============================================================`n" -ForegroundColor Green

.\.venv\Scripts\python.exe scripts\run_ui.py --host 0.0.0.0 --port 5055
