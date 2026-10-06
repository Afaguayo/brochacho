<#
.SYNOPSIS
  One-time bot setup: paste the bot token; this saves it, opens the invite page and starts Brochacho.
#>
$ErrorActionPreference = "Stop"
Write-Host "`n=== Brochacho setup ===`n" -ForegroundColor Cyan

$secure = Read-Host "Paste your Discord bot token (hidden)" -AsSecureString
$token = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if ($token -notmatch '^[\w-]+\.[\w-]+\.[\w-]+$') {
    Write-Host "That doesn't look like a bot token (three parts separated by dots)." -ForegroundColor Red
    Read-Host "Press Enter to close"; exit 1
}

# Saved where the Discord plugin reads it. UTF-8 without BOM, or the plugin misreads line 1.
$dir = Join-Path $HOME ".claude\channels\discord"
New-Item -ItemType Directory -Force $dir | Out-Null
[IO.File]::WriteAllText((Join-Path $dir ".env"), "DISCORD_BOT_TOKEN=$token`n", (New-Object Text.UTF8Encoding($false)))
Write-Host "Token saved to $dir\.env" -ForegroundColor Green

# A bot token's first part is the bot's ID in base64, which is also the application ID.
$idPart = $token.Split('.')[0].Replace('-', '+').Replace('_', '/')
while ($idPart.Length % 4) { $idPart += '=' }
$appId = [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String($idPart))

# View Channels, Send Messages, Send in Threads, Read History, Attach Files, Add Reactions.
Start-Process "https://discord.com/oauth2/authorize?client_id=$appId&scope=bot&permissions=274878008384"
Write-Host "Opened the invite page: add the bot to a server you're in."

Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\start-brochacho.ps1`""

Write-Host "`nLast step:" -ForegroundColor Cyan
Write-Host " 1. DM your bot 'hi' on Discord. It replies with a pairing code."
Write-Host " 2. In the Brochacho window:  /discord:access pair <code>"
Write-Host " 3. Then lock it to you:      /discord:access policy allowlist"
Read-Host "`nPress Enter to close"
