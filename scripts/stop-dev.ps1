<#
.SYNOPSIS
Stop Taichi-Flow development processes owned by the managed launchers.

.DESCRIPTION
The desktop session is handled first. Every normal stop is guarded by the
recorded PID, creation time, executable path and command fingerprint. Reused
services and legacy state records without an immutable identity are never
terminated. Use -ForcePorts only as an explicit emergency override.
#>
[CmdletBinding()]
param(
    [switch]$ForcePorts,
    [ValidateRange(1, 65535)][int[]]$Ports = @(8000, 3000)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$desktopRuntimeRoot = Join-Path $repoRoot ".runtime\desktop-dev"
$desktopActivePath = Join-Path $desktopRuntimeRoot "active.json"
$devRuntimeRoot = Join-Path $repoRoot ".runtime\dev-stack"
$devStatePath = Join-Path $devRuntimeRoot "dev-stack.json"
$modulePath = Join-Path $repoRoot "scripts\desktop-dev\TaichiFlow.DesktopDev.psm1"

Import-Module $modulePath -Force

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[Taichi Flow stop] $Message"
}

function Stop-UnsafeProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) { Stop-UnsafeProcessTree -ProcessId ([int]$child.ProcessId) }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        Write-Step "ForcePorts stopping $($process.ProcessName) pid=$ProcessId"
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$stoppedAny = $false

if (Test-Path -LiteralPath $desktopActivePath -PathType Leaf) {
    $desktopState = Read-TaichiFlowSessionState -StatePath $desktopActivePath
    if ($null -eq $desktopState) {
        Write-Step "Desktop active state is malformed; removing only the stale record."
        Remove-Item -LiteralPath $desktopActivePath -Force -ErrorAction SilentlyContinue
    } else {
        Write-Step "Stopping active desktop session $($desktopState.session_id)."
        $records = @($desktopState.processes)
        [array]::Reverse($records)
        foreach ($record in $records) {
            $result = Stop-TaichiFlowOwnedProcess -Record $record
            if ($result.Stopped) {
                $stoppedAny = $true
                Write-Step "Stopped owned desktop process '$($record.name)' pid=$($record.pid)."
            } elseif ([string]$result.Reason -eq "not-owned-or-identity-mismatch") {
                Write-Step "Skipped '$($record.name)' pid=$($record.pid): ownership identity did not match."
            }
        }
        $activeAfter = Read-TaichiFlowSessionState -StatePath $desktopActivePath
        if ($null -eq $activeAfter -or [string]$activeAfter.session_id -eq [string]$desktopState.session_id) {
            Remove-Item -LiteralPath $desktopActivePath -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Step "No active desktop session state found."
}

if (Test-Path -LiteralPath $devStatePath -PathType Leaf) {
    try { $devState = Get-Content -LiteralPath $devStatePath -Raw | ConvertFrom-Json } catch { $devState = $null }
    if ($null -eq $devState) {
        Write-Step "Legacy dev-stack state is malformed; removing only the stale record."
    } else {
        foreach ($entry in @($devState.processes)) {
            $hasIdentity = $null -ne $entry.PSObject.Properties["creation_time_utc"] -and
                $null -ne $entry.PSObject.Properties["command_fingerprint"] -and
                $null -ne $entry.PSObject.Properties["executable_path"]
            if (-not $hasIdentity) {
                Write-Step "Skipped legacy pid=$($entry.pid): no immutable process identity; use -ForcePorts only if intentional."
                continue
            }
            $record = [pscustomobject]@{
                name = [string]$entry.name
                pid = [int]$entry.pid
                creation_time_utc = [string]$entry.creation_time_utc
                command_fingerprint = [string]$entry.command_fingerprint
                executable_path = [string]$entry.executable_path
                owned = $true
                stdout = [string]$entry.stdout
                stderr = [string]$entry.stderr
            }
            $result = Stop-TaichiFlowOwnedProcess -Record $record
            if ($result.Stopped) {
                $stoppedAny = $true
                Write-Step "Stopped owned legacy process '$($record.name)' pid=$($record.pid)."
            } else {
                Write-Step "Skipped legacy '$($record.name)' pid=$($record.pid): $($result.Reason)."
            }
        }
    }
    Remove-Item -LiteralPath $devStatePath -Force -ErrorAction SilentlyContinue
    Write-Step "Removed legacy state file: $devStatePath"
}

if ($ForcePorts) {
    Write-Step "ForcePorts is enabled; this may stop unrelated listeners."
    foreach ($port in $Ports) {
        $connections = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        foreach ($connection in $connections) {
            Stop-UnsafeProcessTree -ProcessId ([int]$connection.OwningProcess)
            $stoppedAny = $true
        }
    }
}

if (-not $stoppedAny) { Write-Step "No owned Taichi-Flow processes were stopped." }
Write-Step "Done."
