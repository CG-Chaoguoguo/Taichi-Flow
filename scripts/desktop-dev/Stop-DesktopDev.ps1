[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "TaichiFlow.DesktopDev.psm1") -Force
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$activeStatePath = Join-Path $repositoryRoot ".runtime\desktop-dev\active.json"
$state = Read-TaichiFlowSessionState -StatePath $activeStatePath

if ($null -eq $state) {
    Write-Output "No active Taichi-Flow desktop development session was recorded."
    exit 0
}

$results = @()
$cleanupRecords = @($state.processes)
[array]::Reverse($cleanupRecords)
foreach ($record in $cleanupRecords) {
    $result = Stop-TaichiFlowOwnedProcess -Record $record
    $results += $result
    Write-Output ("{0}: {1}" -f $record.name, $result.Reason)
}

$state.cleanup = $results
$state.status = "stopped-by-recovery-entry"
$state.updated_at = [DateTime]::UtcNow.ToString("o")
if (-not [string]::IsNullOrWhiteSpace([string]$state.state_path)) {
    Write-TaichiFlowSessionState -State $state -StatePath ([string]$state.state_path)
}
Remove-Item -LiteralPath $activeStatePath -Force -ErrorAction SilentlyContinue
Write-Output "Recovery cleanup completed. Reused services and identity mismatches were preserved."
