[CmdletBinding()]
param([string]$Root = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..")) }
$Root = [System.IO.Path]::GetFullPath($Root)
$activePath = Join-Path $Root ".runtime\portable\active.json"
$modulePath = Join-Path $Root "scripts\desktop-dev\TaichiFlow.DesktopDev.psm1"
if (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) {
    Write-Host "No active Taichi-Flow portable session was found."
    exit 0
}
Import-Module $modulePath -Force
try { $active = Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { throw "Portable active state is unreadable: $activePath" }
$results = @()
foreach ($record in @($active.processes | Sort-Object @{Expression={ if ($_.name -eq "electron") { 0 } else { 1 } }})) {
    $actual = Get-TaichiFlowProcessIdentity -ProcessId ([int]$record.pid)
    if (Test-TaichiFlowOwnedProcessIdentity -Record $record -Actual $actual) {
        $result = Stop-TaichiFlowOwnedProcess -Record $record
        $results += $result
        Write-Host "Stopped owned $($record.name) PID $($record.pid)."
    } else {
        $results += [pscustomobject]@{ Name = [string]$record.name; Stopped = $false; Reason = "identity-mismatch-or-already-exited" }
        Write-Host "Skipped $($record.name) PID $($record.pid): identity no longer matches."
    }
}
$active | Add-Member -NotePropertyName stopped_at -NotePropertyValue ([DateTime]::UtcNow.ToString("o")) -Force
$active | Add-Member -NotePropertyName status -NotePropertyValue "stopped" -Force
$active | Add-Member -NotePropertyName cleanup -NotePropertyValue $results -Force
$sessionPath = [string]$active.state_path
if (-not [string]::IsNullOrWhiteSpace($sessionPath)) { $active | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $sessionPath -Encoding UTF8 }
Remove-Item -LiteralPath $activePath -Force -ErrorAction SilentlyContinue
Write-Host "Portable Taichi-Flow session stopped; unknown processes were not terminated."
