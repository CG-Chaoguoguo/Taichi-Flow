<#
.SYNOPSIS
Stop the Taichi Flow development stack started by scripts/start-dev.ps1.

.DESCRIPTION
Stops only the PIDs recorded in .runtime/dev-stack/dev-stack.json by default.
Use -ForcePorts only when you explicitly want to stop processes listening on
known development ports, for example after the state file was lost.
#>
[CmdletBinding()]
param(
    [switch]$ForcePorts,
    [int[]]$Ports = @(8000, 3000)
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$RuntimeDir = Join-Path $RepoRoot ".runtime\dev-stack"
$StatePath = Join-Path $RuntimeDir "dev-stack.json"

function Write-Step {
    param([string]$Message)
    Write-Host "[Taichi Flow dev] $Message"
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Write-Step "Stopping $($process.ProcessName) pid=$ProcessId"
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$stoppedAny = $false

if (Test-Path $StatePath) {
    $state = Get-Content $StatePath -Raw | ConvertFrom-Json
    foreach ($entry in @($state.processes)) {
        if ($entry.pid) {
            Stop-ProcessTree -ProcessId ([int]$entry.pid)
            $stoppedAny = $true
        }
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Write-Step "Removed state file: $StatePath"
} else {
    Write-Step "No managed state file found: $StatePath"
}

if ($ForcePorts) {
    foreach ($port in $Ports) {
        $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($connection in $connections) {
            Stop-ProcessTree -ProcessId ([int]$connection.OwningProcess)
            $stoppedAny = $true
        }
    }
}

if (-not $stoppedAny) {
    Write-Step "No managed Taichi Flow dev processes were stopped."
}

Write-Step "Done."
