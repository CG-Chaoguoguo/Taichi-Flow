<#
.SYNOPSIS
Start the Taichi Flow development stack.

.DESCRIPTION
Starts the FastAPI Service Layer and the React/Vite default Presentation Layer,
waits until both are reachable, then opens the React UI in the default browser.
This script is for local development and frontend/backend integration only.
It does not modify or shortcut the reference-compatible computation layer.
#>
[CmdletBinding()]
param(
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 3000,
    [int]$TimeoutSeconds = 90,
    [switch]$NoBrowser,
    [switch]$SkipNpmInstall
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$FrontendDir = Join-Path $RepoRoot "frontend\taichi-flow"
$RuntimeDir = Join-Path $RepoRoot ".runtime\dev-stack"
$StatePath = Join-Path $RuntimeDir "dev-stack.json"
$ApiUrl = "http://${ApiHost}:${ApiPort}"
$ApiHealthUrl = "$ApiUrl/api/health"
$FrontendUrl = "http://${FrontendHost}:${FrontendPort}"

function Write-Step {
    param([string]$Message)
    Write-Host "[Taichi Flow dev] $Message"
}

function Get-PreferredPython {
    if ($env:TAICHI_FLOW_PYTHON -and (Test-Path $env:TAICHI_FLOW_PYTHON)) {
        return (Resolve-Path $env:TAICHI_FLOW_PYTHON).Path
    }
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python executable not found. Create .venv or add python to PATH."
    }
    return $python.Source
}

function Test-HttpReady {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Test-PortInUse {
    param([int]$Port)
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return [bool]$connection
    } catch {
        return $false
    }
}

function Wait-HttpReady {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Timeout
    )

    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpReady -Url $Url) {
            Write-Step "$Name is ready: $Url"
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "$Name did not become ready within ${Timeout}s: $Url"
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$StdOutPath,
        [string]$StdErrPath
    )

    Write-Step "Starting $Name"
    Write-Step "  cwd: $WorkingDirectory"
    Write-Step "  command: $FilePath $($ArgumentList -join ' ')"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdOutPath `
        -RedirectStandardError $StdErrPath
    Write-Step "$Name PID: $($process.Id)"
    return $process
}

New-Item -ItemType Directory -Force $RuntimeDir | Out-Null
Set-Location $RepoRoot

Write-Step "Default frontend: React/Vite ($FrontendUrl)"
Write-Step "Service layer: FastAPI ($ApiUrl)"
Write-Step "Runtime logs: $RuntimeDir"

if (-not (Test-Path $FrontendDir)) {
    throw "React frontend directory not found: $FrontendDir"
}

$pythonExe = Get-PreferredPython
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $npm) {
    throw "npm not found. Install Node.js 18+ before starting the React UI."
}

$started = @()

if (Test-HttpReady -Url $ApiHealthUrl) {
    Write-Step "FastAPI already healthy; reusing existing service."
} elseif (Test-PortInUse -Port $ApiPort) {
    throw "Port $ApiPort is already in use, but $ApiHealthUrl is not healthy. Stop the conflicting process or change -ApiPort."
} else {
    $apiOut = Join-Path $RuntimeDir "fastapi.out.log"
    $apiErr = Join-Path $RuntimeDir "fastapi.err.log"
    $apiProcess = Start-LoggedProcess `
        -Name "FastAPI" `
        -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "api.app:app", "--host", $ApiHost, "--port", [string]$ApiPort) `
        -WorkingDirectory $RepoRoot `
        -StdOutPath $apiOut `
        -StdErrPath $apiErr
    $started += [ordered]@{ name = "FastAPI"; pid = $apiProcess.Id; url = $ApiUrl; log = $apiErr; started_by_script = $true }
}

if (-not $SkipNpmInstall -and -not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Step "node_modules not found; running npm ci in frontend/taichi-flow"
    Push-Location $FrontendDir
    try {
        & $npm.Source ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

if (Test-HttpReady -Url $FrontendUrl) {
    Write-Step "React/Vite already reachable; reusing existing frontend."
} elseif (Test-PortInUse -Port $FrontendPort) {
    throw "Port $FrontendPort is already in use, but $FrontendUrl is not reachable. Stop the conflicting process or change -FrontendPort."
} else {
    $viteOut = Join-Path $RuntimeDir "vite.out.log"
    $viteErr = Join-Path $RuntimeDir "vite.err.log"
    $viteProcess = Start-LoggedProcess `
        -Name "React/Vite" `
        -FilePath $npm.Source `
        -ArgumentList @("run", "dev", "--", "--host", $FrontendHost, "--port", [string]$FrontendPort) `
        -WorkingDirectory $FrontendDir `
        -StdOutPath $viteOut `
        -StdErrPath $viteErr
    $started += [ordered]@{ name = "React/Vite"; pid = $viteProcess.Id; url = $FrontendUrl; log = $viteOut; started_by_script = $true }
}

Wait-HttpReady -Name "FastAPI health" -Url $ApiHealthUrl -Timeout $TimeoutSeconds
Wait-HttpReady -Name "React UI" -Url $FrontendUrl -Timeout $TimeoutSeconds

$state = [ordered]@{
    started_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    api_url = $ApiUrl
    api_health_url = $ApiHealthUrl
    frontend_url = $FrontendUrl
    default_frontend = "React/Vite"
    processes = $started
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $StatePath -Encoding UTF8
Write-Step "State written: $StatePath"

if (-not $NoBrowser) {
    Write-Step "Opening React UI: $FrontendUrl"
    Start-Process $FrontendUrl
} else {
    Write-Step "NoBrowser set; open manually: $FrontendUrl"
}

Write-Host ""
Write-Step "Development stack is ready."
Write-Step "Manual path: Data Upload -> Parameter Configuration -> Simulation Control -> Results -> Download."
Write-Step "Stop with: scripts\stop-dev.ps1"
