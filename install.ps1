# Brochacho installer for Windows. Run in PowerShell:
#   irm https://raw.githubusercontent.com/Afaguayo/brochacho/main/install.ps1 | iex
# Downloads Brochacho.exe from the latest release and starts the setup wizard.
$ErrorActionPreference = "Stop"
$dir = Join-Path $env:LOCALAPPDATA "Programs\Brochacho"
$exe = Join-Path $dir "Brochacho.exe"
New-Item -ItemType Directory -Force $dir | Out-Null
Write-Host "Downloading Brochacho.exe..." -ForegroundColor Cyan
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest "https://github.com/Afaguayo/brochacho/releases/latest/download/Brochacho.exe" -OutFile $exe -UseBasicParsing
Unblock-File $exe
& $exe setup
