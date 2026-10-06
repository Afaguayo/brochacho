<#
.SYNOPSIS
  Starts Brochacho: a Claude Code session in your vault that listens to your Discord bot.

.PARAMETER Vault
  Folder Claude works in. Defaults to $env:BROCHACHO_VAULT, then ~/Documents/SecondBrain, then the current folder.

.PARAMETER StayAwake
  Keep the PC from sleeping while Brochacho runs. Without it the PC may sleep; wake it with
  Wake-on-LAN and Brochacho reconnects on its own.
#>
param(
    [string]$Vault = $env:BROCHACHO_VAULT,
    [switch]$StayAwake
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Brochacho"
$repo = Split-Path $PSScriptRoot -Parent

# Only one Brochacho per machine: two sessions on one bot token would both answer.
$mutex = New-Object Threading.Mutex($false, "Global\Brochacho")
if (-not $mutex.WaitOne(0)) {
    Write-Host "Brochacho is already running on this PC." -ForegroundColor Yellow
    Start-Sleep 3; exit 0
}

if (-not $Vault) {
    $default = Join-Path $HOME "Documents\SecondBrain"
    $Vault = if (Test-Path $default) { $default } else { (Get-Location).Path }
}

# The Discord channel plugin runs on Bun; old terminals may not have it on PATH yet.
$bunBin = Join-Path $HOME ".bun\bin"
if (Test-Path $bunBin) { $env:Path = "$bunBin;$env:Path" }
foreach ($tool in "bun", "claude") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "$tool is not installed. Run windows\install.ps1 first." -ForegroundColor Red
        Read-Host "Press Enter to close"; exit 1
    }
}
if (-not (Test-Path (Join-Path $HOME ".claude\channels\discord\.env")) -and -not $env:DISCORD_BOT_TOKEN) {
    Write-Host "No bot token yet. Run windows\setup.ps1 first." -ForegroundColor Red
    Read-Host "Press Enter to close"; exit 1
}

if ($StayAwake) {
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: holds off sleep until this window closes.
    Add-Type -Namespace Brochacho -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);'
    [void][Brochacho.Power]::SetThreadExecutionState([uint32]"0x80000001")
}

$persona = (Get-Content (Join-Path $repo "brochacho.md") -Raw) + @"

This machine: $env:COMPUTERNAME (Windows). Wake tool: powershell -NoProfile -File "$repo\tools\wake.ps1" <machine-name>
"@

Set-Location $Vault
if (Test-Path ".git") { git pull --ff-only 2>$null | Out-Null }

Write-Host @"

  +------------------------------------------+
  |  BROCHACHO is on. DM the bot on Discord. |
  |  Close this window to turn it off.       |
  +------------------------------------------+
  vault: $Vault

"@ -ForegroundColor Cyan

# Restart after a crash or a dropped connection; a clean /exit (code 0) stops for good.
while ($true) {
    claude --settings (Join-Path $repo "brochacho.settings.json") --channels plugin:discord@claude-plugins-official --permission-mode acceptEdits --append-system-prompt $persona
    if ($LASTEXITCODE -eq 0) { break }
    Write-Host "Brochacho stopped (exit $LASTEXITCODE). Restarting in 10 s; close the window to cancel." -ForegroundColor Yellow
    Start-Sleep 10
}
