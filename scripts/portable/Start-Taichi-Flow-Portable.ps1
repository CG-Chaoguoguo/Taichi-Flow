[CmdletBinding()]
param(
    [string]$Root = "",
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 90,
    [switch]$Smoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$Root = [System.IO.Path]::GetFullPath($Root)
$manifestPath = Join-Path $Root "portable-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "This directory is not a Taichi-Flow portable bundle (portable-manifest.json is missing)."
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$manifest.schema_version -ne 1) { throw "Unsupported portable manifest schema." }
$buildId = [string]$manifest.build_id
$checkoutId = [string]$manifest.checkout_id
$pythonRoot = Join-Path $Root ".runtime\portable\python"
$pythonPath = Join-Path $pythonRoot "python.exe"
$electronDirectory = Join-Path $Root ".runtime\portable\electron"
# Keep Electron's upstream executable name.  Electron launches helper
# processes from its own executable name; renaming electron.exe can make the
# GPU/render helper fail to start on some Windows hosts.
$electronPath = Join-Path $electronDirectory "electron.exe"
$appRoot = Join-Path $Root "app"
$stateRoot = Join-Path $Root ".runtime\portable\state"
$sessionId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$sessionRoot = Join-Path $Root ".runtime\portable\sessions\$sessionId"
$statePath = Join-Path $sessionRoot "state.json"
$activePath = Join-Path $Root ".runtime\portable\active.json"
$logPath = Join-Path $sessionRoot "launcher.log"
$userDataPath = Join-Path $Root ".runtime\portable\electron-user-data"
$runtimeHelper = Join-Path $Root "scripts\portable\relocate_paths.py"
$desktopMain = Join-Path $appRoot "desktop\main.cjs"
$preferredApiPort = if ($null -ne $manifest.PSObject.Properties["ports"] -and $null -ne $manifest.ports.PSObject.Properties["api"]) { [int]$manifest.ports.api } else { 8000 }

foreach ($required in @($pythonPath, $electronPath, $desktopMain, $runtimeHelper)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Portable runtime file is missing: $required" }
}
New-Item -ItemType Directory -Path $sessionRoot,$stateRoot,$userDataPath -Force | Out-Null

$modulePath = Join-Path $Root "scripts\desktop-dev\TaichiFlow.DesktopDev.psm1"
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "Portable process-management module is missing: $modulePath" }
Import-Module $modulePath -Force

function Write-PortableLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Message
    Write-Host $line
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Save-PortableState {
    if ($null -eq $script:PortableState) { return }
    Write-TaichiFlowSessionState -State $script:PortableState -StatePath $statePath
    if ($script:PublishActive) { Write-TaichiFlowSessionState -State $script:PortableState -StatePath $activePath }
}

function Add-PortableProcess {
    param([Parameter(Mandatory = $true)]$Record)
    $script:PortableState.processes = @($script:PortableState.processes) + @($Record)
    Save-PortableState
}

function Test-PortablePortFree {
    param([Parameter(Mandatory = $true)][int]$Port)
    return Test-TaichiFlowPortFree -Port $Port
}

function Test-PortableApi {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        return [bool]([string]$health.service_id -eq "taichi-flow-api" -and
            [int]$health.api_contract_version -eq 1 -and
            [string]$health.checkout_id -eq $checkoutId -and
            [string]$health.build_id -eq $buildId -and
            [string]$health.distribution_mode -eq "portable")
    } catch { return $false }
}

function Get-PortableActiveState {
    if (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) { return $null }
    try {
        $candidate = Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$candidate.build_id -ne $buildId) { return $null }
        return $candidate
    } catch { return $null }
}

function Test-PortableOwnedRecord {
    param([Parameter(Mandatory = $true)]$Record)
    try {
        return Test-TaichiFlowOwnedProcessIdentity -Record $Record -Actual (Get-TaichiFlowProcessIdentity -ProcessId ([int]$Record.pid))
    } catch { return $false }
}

function Invoke-PortableFocus {
    param([Parameter(Mandatory = $true)]$Existing)
    $electronRecord = @($Existing.processes | Where-Object { $_.name -eq "electron" }) | Select-Object -Last 1
    if ($null -eq $electronRecord -or -not (Test-PortableOwnedRecord $electronRecord)) { return $false }
    $apiUrl = [string]$Existing.api_url
    $environment = @{
        TAICHI_FLOW_DESKTOP_MODE = "preview"
        TAICHI_FLOW_API_URL = $apiUrl
        TAICHI_FLOW_DESKTOP_URL = ""
        TAICHI_FLOW_BUILD_ID = $buildId
        TAICHI_FLOW_DISTRIBUTION_MODE = "portable"
    }
    $previous = @{}
    try {
        foreach ($key in $environment.Keys) {
            $previous[$key] = [Environment]::GetEnvironmentVariable([string]$key, "Process")
            [Environment]::SetEnvironmentVariable([string]$key, [string]$environment[$key], "Process")
        }
        Write-PortableLog "An active portable desktop session was found; forwarding a focus request."
        $focus = Start-Process -FilePath $electronPath -ArgumentList @("--user-data-dir=$userDataPath", $desktopMain) -WorkingDirectory $appRoot -PassThru -WindowStyle Hidden
        if (-not $focus.WaitForExit(10000)) {
            Stop-Process -Id $focus.Id -Force -ErrorAction SilentlyContinue
            throw "The active portable Electron instance did not acknowledge focus within 10 seconds."
        }
    } finally {
        foreach ($key in $environment.Keys) { [Environment]::SetEnvironmentVariable([string]$key, $previous[$key], "Process") }
    }
    return $true
}

$script:PortableState = $null
$script:PublishActive = $false
$startupMutex = $null
$exitCode = 1
$apiStarted = $false
$electronStarted = $false

try {
    $lockName = "Local\TaichiFlowPortable-$($buildId -replace '[^A-Za-z0-9_-]', '_')"
    $startupMutex = [System.Threading.Mutex]::new($false, $lockName)
    try { if (-not $startupMutex.WaitOne([TimeSpan]::FromSeconds(30))) { throw "Another portable launcher is starting this bundle." } }
    catch [System.Threading.AbandonedMutexException] { }

    $existing = Get-PortableActiveState
    if ($null -ne $existing -and (Invoke-PortableFocus -Existing $existing)) {
        $exitCode = 0
        return
    }
    if (Test-Path -LiteralPath $activePath -PathType Leaf) { Remove-Item -LiteralPath $activePath -Force -ErrorAction SilentlyContinue }

    $script:PortableState = [pscustomobject][ordered]@{
        session_id = $sessionId
        build_id = $buildId
        checkout_id = $checkoutId
        repository_root = $Root
        created_at = [DateTime]::UtcNow.ToString("o")
        updated_at = [DateTime]::UtcNow.ToString("o")
        launcher_pid = $PID
        status = "starting"
        api_url = ""
        api_port = 0
        api_instance_id = ""
        desktop_url = "app://taichi-flow/index.html"
        electron_user_data_dir = $userDataPath
        state_path = $statePath
        launcher_log = $logPath
        relocation = $null
        processes = @()
        cleanup = @()
    }
    Save-PortableState

    Write-PortableLog "Portable launcher session=$sessionId build=$buildId root=$Root"
    $relocation = @(& $pythonPath $runtimeHelper --root $Root --manifest $manifestPath 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Portable path relocation failed: $($relocation -join [Environment]::NewLine)" }
    $relocationLine = $relocation | Where-Object { [string]$_ -like "TAICHI_FLOW_RELOCATION=*" } | Select-Object -Last 1
    if ($null -eq $relocationLine) { throw "Portable path relocation returned no structured report." }
    $script:PortableState.relocation = ([string]$relocationLine).Substring("TAICHI_FLOW_RELOCATION=".Length) | ConvertFrom-Json

    $selectedApiPort = Find-TaichiFlowFreePort -PreferredPort $preferredApiPort
    if ($selectedApiPort -ne $preferredApiPort) { Write-PortableLog "API port $preferredApiPort is occupied; using $selectedApiPort without terminating the owner." }
    $apiUrl = "http://127.0.0.1:$selectedApiPort"
    $apiStdout = Join-Path $sessionRoot "api.stdout.log"
    $apiStderr = Join-Path $sessionRoot "api.stderr.log"
    $apiInstanceId = Get-TaichiFlowHash "$buildId|$sessionId|$selectedApiPort"
    $runtimePath = "$pythonRoot;$($pythonRoot)\DLLs;$env:PATH"
    $apiEnvironment = @{
        TAICHI_FLOW_ALLOWED_ORIGINS = "app://taichi-flow"
        TAICHI_FLOW_API_INSTANCE_ID = $apiInstanceId
        TAICHI_FLOW_CHECKOUT_ID = $checkoutId
        TAICHI_FLOW_BUILD_ID = $buildId
        TAICHI_FLOW_DISTRIBUTION_MODE = "portable"
        TAICHI_FLOW_RUNTIME_PYTHON = [string]$manifest.runtime.python
        TAICHI_FLOW_RUNTIME_TAICHI = [string]$manifest.runtime.taichi
        TAICHI_FLOW_STATE_DIR = $stateRoot
        PYTHONUTF8 = "1"
        PATH = $runtimePath
    }
    $apiArguments = @("-m", "uvicorn", "api.app:app", "--app-dir", $Root, "--host", "127.0.0.1", "--port", [string]$selectedApiPort, "--log-level", "info")
    Write-PortableLog "Starting private Python backend on $apiUrl"
    $apiProcess = Start-TaichiFlowLoggedProcess -Name "api" -FilePath $pythonPath -ArgumentList $apiArguments -WorkingDirectory $Root -StandardOutputPath $apiStdout -StandardErrorPath $apiStderr -Environment $apiEnvironment
    $apiStarted = $true
    Add-PortableProcess (New-TaichiFlowProcessRecord -Name "api" -Identity $apiProcess.Identity -Owned $true -StandardOutputPath $apiStdout -StandardErrorPath $apiStderr)
    Wait-TaichiFlowHttpReady -Url "$apiUrl/api/health" -TimeoutSeconds $TimeoutSeconds -Process $apiProcess.Process -Validator {
        param($Response)
        try {
            $health = $Response.Content | ConvertFrom-Json
            return [string]$health.service_id -eq "taichi-flow-api" -and [int]$health.api_contract_version -eq 1 -and [string]$health.checkout_id -eq $checkoutId -and [string]$health.build_id -eq $buildId -and [string]$health.distribution_mode -eq "portable"
        } catch { return $false }
    }
    if (-not (Test-PortableApi -Port $selectedApiPort)) { throw "Private API failed the portable health contract." }
    Write-PortableLog "Private API is healthy; checkout=$checkoutId build=$buildId"
    $script:PortableState.api_url = $apiUrl
    $script:PortableState.api_port = $selectedApiPort
    $script:PortableState.api_instance_id = $apiInstanceId
    $script:PublishActive = $true
    Save-PortableState

    $electronStdout = Join-Path $sessionRoot "electron.stdout.log"
    $electronStderr = Join-Path $sessionRoot "electron.stderr.log"
    $exitReport = Join-Path $sessionRoot "electron-exit-report.json"
    $smokeReport = Join-Path $sessionRoot "portable-smoke-report.json"
    $smokeScreenshot = Join-Path $sessionRoot "portable-smoke.png"
    $electronEnvironment = @{
        TAICHI_FLOW_DESKTOP_MODE = "preview"
        TAICHI_FLOW_DESKTOP_URL = ""
        TAICHI_FLOW_API_URL = $apiUrl
        TAICHI_FLOW_BUILD_ID = $buildId
        TAICHI_FLOW_DISTRIBUTION_MODE = "portable"
        TAICHI_FLOW_DESKTOP_SMOKE = if ($Smoke) { "1" } else { "0" }
        TAICHI_FLOW_DESKTOP_SMOKE_REPORT = $smokeReport
        TAICHI_FLOW_DESKTOP_SMOKE_SCREENSHOT = $smokeScreenshot
        TAICHI_FLOW_DESKTOP_EXIT_REPORT = $exitReport
    }
    Write-PortableLog "Starting packaged Electron preview"
    if ([string]::IsNullOrWhiteSpace([string]$electronEnvironment.TAICHI_FLOW_API_URL)) { throw "Portable Electron API URL was empty before process creation." }
    $electron = Start-TaichiFlowLoggedProcess -Name "electron" -FilePath $electronPath -ArgumentList @("--disable-gpu", "--disable-gpu-compositing", "--user-data-dir=$userDataPath", $desktopMain) -WorkingDirectory $appRoot -StandardOutputPath $electronStdout -StandardErrorPath $electronStderr -Environment $electronEnvironment -Visible
    $electronStarted = $true
    Add-PortableProcess (New-TaichiFlowProcessRecord -Name "electron" -Identity $electron.Identity -Owned $true -StandardOutputPath $electronStdout -StandardErrorPath $electronStderr)
    $script:PortableState.status = if ($Smoke) { "smoke-running" } else { "running" }
    Save-PortableState
    $electron.Process.WaitForExit()
    $nativeExit = $null
    try { $nativeExit = $electron.Process.ExitCode } catch { }
    $report = $null
    if (Test-Path -LiteralPath $exitReport -PathType Leaf) { try { $report = Get-Content -LiteralPath $exitReport -Raw -Encoding UTF8 | ConvertFrom-Json } catch { } }
    if ($Smoke) {
        if ($null -eq $report -or -not [bool]$report.success) { throw "Portable Electron smoke test failed. See $electronStderr and $smokeReport" }
        if (-not (Test-Path -LiteralPath $smokeReport -PathType Leaf)) { throw "Portable Electron did not write a smoke report." }
        $smokeReportData = Get-Content -LiteralPath $smokeReport -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not [bool]$smokeReportData.success) { throw "Portable renderer smoke report is unsuccessful." }
    } elseif ($null -ne $report -and -not [bool]$report.success) {
        throw "Portable Electron exited with a failed lifecycle report. See $electronStderr"
    } elseif ($null -ne $nativeExit -and [int]$nativeExit -ne 0) {
        throw "Portable Electron exited with code $nativeExit. See $electronStderr"
    }
    Write-PortableLog "Electron exited normally."
    $exitCode = 0
    $script:PortableState.status = if ($Smoke) { "smoke-passed" } else { "closed" }
} catch {
    Write-PortableLog "ERROR: $($_.Exception.Message)"
    if ($null -ne $script:PortableState) { $script:PortableState.status = "failed" }
    $exitCode = 1
} finally {
    if ($null -ne $script:PortableState) {
        $cleanup = @()
        $records = @($script:PortableState.processes)
        [array]::Reverse($records)
        foreach ($record in $records) {
            $result = Stop-TaichiFlowOwnedProcess -Record $record
            $cleanup += $result
            if ($result.Stopped) { Write-PortableLog "Cleanup stopped owned process '$($record.name)' PID $($record.pid)." }
        }
        $script:PortableState.cleanup = $cleanup
        $script:PortableState.updated_at = [DateTime]::UtcNow.ToString("o")
        Write-TaichiFlowSessionState -State $script:PortableState -StatePath $statePath
        if ($script:PublishActive -and (Test-Path -LiteralPath $activePath -PathType Leaf)) {
            try {
                $active = Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ([string]$active.session_id -eq $sessionId) { Remove-Item -LiteralPath $activePath -Force -ErrorAction SilentlyContinue }
            } catch { }
        }
    }
    if ($null -ne $startupMutex) {
        try { $startupMutex.ReleaseMutex() } catch { }
        try { $startupMutex.Dispose() } catch { }
    }
    $liveOwned = 0
    if ($null -ne $script:PortableState) {
        foreach ($record in @($script:PortableState.processes | Where-Object { $_.owned })) {
            if ($null -ne (Get-TaichiFlowProcessIdentity -ProcessId ([int]$record.pid))) { $liveOwned += 1 }
        }
    }
    Write-PortableLog "[CLEANUP] children=$liveOwned persistent_services=0 zombies=0"
    Write-Host "Portable launcher log: $logPath"
}

exit $exitCode
