<#
.SYNOPSIS
  Sends a Wake-on-LAN magic packet.
.EXAMPLE
  wake.ps1 macbook               # name from ~/.brochacho/machines.json
  wake.ps1 A8-A1-59-39-A0-AF      # or a MAC address
  wake.ps1 -List
#>
param([string]$Target, [switch]$List)

$cfg = Join-Path $HOME ".brochacho\machines.json"
$machines = if (Test-Path $cfg) { Get-Content $cfg -Raw | ConvertFrom-Json } else { $null }

if ($List -or -not $Target) {
    if ($machines) { $machines.PSObject.Properties | ForEach-Object { "{0,-12} {1}  ({2}) {3}" -f $_.Name, $_.Value.mac, $_.Value.os, $(if ($_.Value.aliases) { "aka " + ($_.Value.aliases -join ", ") }) } }
    else { "No machines yet in $cfg" }
    exit 0
}

$broadcast = "255.255.255.255"
# Match a machine by name or by one of its "aliases".
$entry = if ($machines) {
    $machines.PSObject.Properties | Where-Object { $_.Name -eq $Target.ToLower() -or $_.Value.aliases -contains $Target.ToLower() } | Select-Object -First 1
} else { $null }
if ($entry) {
    $mac = $entry.Value.mac
    if ($entry.Value.broadcast) { $broadcast = $entry.Value.broadcast }
} elseif ($Target -match '^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$') {
    $mac = $Target
} else {
    Write-Error "Unknown machine '$Target'. Known: $(($machines.PSObject.Properties.Name) -join ', ')"; exit 1
}

# Magic packet: 6 x 0xFF, then the MAC 16 times.
$macBytes = [byte[]](($mac -replace '[:-]', '') -split '(..)' -ne '' | ForEach-Object { [Convert]::ToByte($_, 16) })
$packet = [byte[]](@(0xFF) * 6 + $macBytes * 16)

$udp = New-Object Net.Sockets.UdpClient
$udp.EnableBroadcast = $true
foreach ($addr in @($broadcast, "255.255.255.255") | Select-Object -Unique) {
    foreach ($port in 9, 7) { [void]$udp.Send($packet, $packet.Length, $addr, $port) }
}
$udp.Close()
"Sent magic packet to $mac via $broadcast. Give it ~20 s to wake."
