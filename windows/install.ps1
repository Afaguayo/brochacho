<#
.SYNOPSIS
  Installs Brochacho on Windows: Bun, the Discord channel plugin, a "Brochacho" Desktop shortcut,
  and this PC's entry in ~/.brochacho/machines.json for Wake-on-LAN.

.PARAMETER Vault      Folder Brochacho works in (saved in the shortcuts).
.PARAMETER Autostart  Also start Brochacho when you log in.
.PARAMETER StayAwake  Shortcuts keep the PC awake while Brochacho runs.
.PARAMETER Uninstall  Remove the shortcuts (leaves Bun, the plugin and your token).
#>
param(
    [string]$Vault = $env:BROCHACHO_VAULT,
    [switch]$Autostart,
    [switch]$StayAwake,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$desktopLnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Brochacho.lnk"
$startupLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Brochacho.lnk"

if ($Uninstall) {
    Remove-Item $desktopLnk, $startupLnk -ErrorAction SilentlyContinue
    Write-Host "Removed Brochacho shortcuts." -ForegroundColor Green
    exit 0
}

# 1. Bun (the channel plugin is a Bun script).
$bunBin = Join-Path $HOME ".bun\bin"
$env:Path = "$bunBin;$env:Path"
if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Bun..."
    powershell -NoProfile -c "irm bun.sh/install.ps1 | iex"
}

# 2. The official Discord channel plugin.
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "Claude Code is not installed: https://code.claude.com/docs/en/quickstart" -ForegroundColor Red; exit 1
}
if (-not ((claude plugin list) -match "discord@claude-plugins-official")) {
    claude plugin marketplace add anthropics/claude-plugins-official
    claude plugin install discord@claude-plugins-official --scope user
}
# Off for normal sessions; the launcher turns it on just for Brochacho (brochacho.settings.json).
claude plugin disable discord@claude-plugins-official --scope user 2>$null | Out-Null

# 3. Shortcuts.
$launchArgs = "-NoExit -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-brochacho.ps1`""
if ($Vault) { $launchArgs += " -Vault `"$Vault`"" }
if ($StayAwake) { $launchArgs += " -StayAwake" }
$icon = Join-Path (Split-Path $PSScriptRoot -Parent) "docs\brochacho.ico"

function New-Shortcut($path, $windowStyle) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $s.Arguments = $launchArgs
    $s.WorkingDirectory = $HOME
    $s.WindowStyle = $windowStyle   # 1 normal, 7 minimized
    $s.Description = "Turn on Brochacho (Claude on Discord)"
    if (Test-Path $icon) { $s.IconLocation = $icon }
    $s.Save()
}
New-Shortcut $desktopLnk 1
Write-Host "Desktop shortcut: $desktopLnk" -ForegroundColor Green
if ($Autostart) {
    New-Shortcut $startupLnk 7
    Write-Host "Starts at login: $startupLnk" -ForegroundColor Green
}

# 4. Register this PC for Wake-on-LAN (wired adapter preferred).
$cfgDir = Join-Path $HOME ".brochacho"; $cfg = Join-Path $cfgDir "machines.json"
New-Item -ItemType Directory -Force $cfgDir | Out-Null
$machines = if (Test-Path $cfg) { Get-Content $cfg -Raw | ConvertFrom-Json } else { New-Object PSObject }
$nic = Get-NetAdapter -Physical | Where-Object Status -eq Up | Sort-Object { $_.MediaType -ne "802.3" } | Select-Object -First 1
if ($nic) {
    $ip = Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 | Select-Object -First 1
    $bcast = ($ip.IPAddress -replace '\.\d+$', '.255')
    $name = $env:COMPUTERNAME.ToLower()
    $entry = [pscustomobject]@{ mac = $nic.MacAddress; broadcast = $bcast; os = "windows"; aliases = @("pc") }
    if ($machines.$name.aliases) { $entry.aliases = @($machines.$name.aliases) }   # keep aliases on re-install
    $machines | Add-Member -NotePropertyName $name -NotePropertyValue $entry -Force
    [IO.File]::WriteAllText($cfg, ($machines | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    Write-Host "Registered '$name' ($($nic.MacAddress)) in $cfg" -ForegroundColor Green
    $wol = Get-NetAdapterAdvancedProperty -Name $nic.Name -DisplayName "Wake on Magic Packet" -ErrorAction SilentlyContinue
    if ($wol -and $wol.DisplayValue -ne "Enabled") {
        Write-Host "Note: 'Wake on Magic Packet' is off for $($nic.Name); turn it on in Device Manager to wake this PC remotely." -ForegroundColor Yellow
    }
}

if (-not (Test-Path (Join-Path $HOME ".claude\channels\discord\.env"))) {
    Write-Host "`nNext: run windows\setup.ps1 to add your bot token." -ForegroundColor Cyan
} else {
    Write-Host "`nDone. Double-click 'Brochacho' on your Desktop to turn it on." -ForegroundColor Cyan
}
