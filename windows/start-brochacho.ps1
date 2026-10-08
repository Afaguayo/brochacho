<#
  Compatibility launcher for shortcuts made by Brochacho 1.x. Brochacho is now one program,
  Brochacho.exe; this starts it, or runs it from source if you cloned the repo and have Python.
#>
param([string]$Vault, [switch]$StayAwake)
$exe = Join-Path $env:LOCALAPPDATA "Programs\Brochacho\Brochacho.exe"
$extra = @("start"); if ($Vault) { $extra += @("--vault", $Vault) }; if ($StayAwake) { $extra += "--stay-awake" }
if (Test-Path $exe) { & $exe @extra; exit $LASTEXITCODE }
$py = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
if ($py) { & $py.Source (Join-Path (Split-Path $PSScriptRoot -Parent) "app\brochacho.py") @extra; exit $LASTEXITCODE }
Write-Host "Brochacho is now a single Brochacho.exe. Get it here and run it once to set up:" -ForegroundColor Yellow
Write-Host "https://github.com/Afaguayo/brochacho/releases/latest"
Start-Process "https://github.com/Afaguayo/brochacho/releases/latest"
Read-Host "Press Enter to close"
