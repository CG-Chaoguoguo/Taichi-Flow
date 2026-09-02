[CmdletBinding()]
param(
    [ValidateSet("dev", "preview")][string]$Mode = "dev",
    [ValidateSet("electron", "browser", "services")][string]$Presentation = "electron",
    [string]$ApiHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$ApiPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$FrontendPort = 3000,
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 90,
    [switch]$OpenDevTools,
    [switch]$Smoke,
    [string]$SmokeReportPath = "",
    [string]$SmokeScreenshotPath = "",
    [switch]$SkipNpmInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modulePath = Join-Path $PSScriptRoot "TaichiFlow.DesktopDev.psm1"
Import-Module $modulePath -Force

$modeName = Resolve-TaichiFlowDesktopMode $Mode
$presentationName = $Presentation.Trim().ToLowerInvariant()
if ($presentationName -ne "electron" -and $modeName -ne "dev") {
    throw "The '$presentationName' presentation is available only with -Mode dev. Preview mode requires the Electron presentation."
}
if ($ApiHost -notin @("127.0.0.1", "localhost", "::1") -or $FrontendHost -notin @("127.0.0.1", "localhost", "::1")) {
    throw "The managed Taichi-Flow launcher only permits loopback -ApiHost and -FrontendHost values."
}
$bindHost = "127.0.0.1"
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$frontendRoot = Join-Path $repositoryRoot "frontend\taichi-flow"
$runtimeRoot = Join-Path $repositoryRoot ".runtime\desktop-dev"
$sessionId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$sessionRoot = Join-Path $runtimeRoot "sessions\$sessionId"
$statePath = Join-Path $sessionRoot "state.json"
$activeStatePath = Join-Path $runtimeRoot "active.json"
$launcherLogPath = Join-Path $sessionRoot "launcher.log"
$checkoutId = Get-TaichiFlowCheckoutId -RepositoryRoot $repositoryRoot
$sourceRevision = Get-TaichiFlowSourceRevision -RepositoryRoot $repositoryRoot
$script:SessionState = $null
$script:PublishActiveState = $false
$startupMutex = $null
$existingActiveState = $null
$persistServices = $false

New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null

function Write-LauncherLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Message
    Write-Host $line
    Add-Content -LiteralPath $launcherLogPath -Value $line -Encoding UTF8
}

function Save-LauncherState {
    if ($null -eq $script:SessionState) { return }
    Write-TaichiFlowSessionState -State $script:SessionState -StatePath $statePath
    if ($script:PublishActiveState) {
        Write-TaichiFlowSessionState -State $script:SessionState -StatePath $activeStatePath
    }
}

function Add-LauncherProcessRecord {
    param([Parameter(Mandatory = $true)]$Record)
    $script:SessionState.processes = @($script:SessionState.processes) + @($Record)
    Save-LauncherState
}

function Invoke-LauncherNpmStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $npmCommand = Get-Command "npm.cmd" -ErrorAction Stop | Select-Object -First 1
    $nodeCommand = Get-Command "node.exe" -ErrorAction Stop | Select-Object -First 1
    $npmCliPath = Join-Path (Split-Path -Parent $npmCommand.Source) "node_modules\npm\bin\npm-cli.js"
    if (-not (Test-Path -LiteralPath $npmCliPath -PathType Leaf)) { throw "Unable to locate npm CLI at $npmCliPath" }
    $runnerPath = Join-Path $PSScriptRoot "Run-NpmCommand.ps1"
    $exitCodePath = Join-Path $sessionRoot "$Name.exit-code.txt"
    $argumentJson = ConvertTo-Json @($Arguments) -Compress
    $argumentBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($argumentJson))
    $stdout = Join-Path $sessionRoot "$Name.stdout.log"
    $stderr = Join-Path $sessionRoot "$Name.stderr.log"
    Write-LauncherLog "$Name started: npm $($Arguments -join ' ')"
    $runnerArguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runnerPath,
        "-NodePath", $nodeCommand.Source, "-NpmCliPath", $npmCliPath,
        "-WorkingDirectory", $frontendRoot, "-ArgumentsBase64", $argumentBase64,
        "-ExitCodePath", $exitCodePath
    )
    $started = Start-TaichiFlowLoggedProcess -Name $Name -FilePath "powershell.exe" -ArgumentList $runnerArguments -WorkingDirectory $frontendRoot -StandardOutputPath $stdout -StandardErrorPath $stderr
    Add-LauncherProcessRecord (New-TaichiFlowProcessRecord -Name $Name -Identity $started.Identity -Owned $true -StandardOutputPath $stdout -StandardErrorPath $stderr)
    $started.Process.WaitForExit()
    if (-not (Test-Path -LiteralPath $exitCodePath -PathType Leaf)) { throw "$Name ended without writing its tracked exit code. See $stderr" }
    $stepExitCode = [int](Get-Content -LiteralPath $exitCodePath -Raw).Trim()
    if ($stepExitCode -ne 0) {
        throw "$Name failed with exit code $stepExitCode. See $stderr"
    }
    Write-LauncherLog "$Name completed successfully."
}

function Invoke-ExistingDesktopFocus {
    param([Parameter(Mandatory = $true)]$ExistingState)
    $desktopRecord = @($ExistingState.processes | Where-Object { $_.name -eq "electron" }) | Select-Object -Last 1
    if ($null -eq $desktopRecord) { return $false }
    $actual = Get-TaichiFlowProcessIdentity -ProcessId ([int]$desktopRecord.pid)
    if (-not (Test-TaichiFlowOwnedProcessIdentity -Record $desktopRecord -Actual $actual)) { return $false }
    if ([string]$ExistingState.repository_root -ne $repositoryRoot) { return $false }
    if ($null -ne $ExistingState.PSObject.Properties["source_revision"] -and [string]$ExistingState.source_revision -ne $sourceRevision) { return $false }

    $electronExecutable = Join-Path $frontendRoot "node_modules\electron\dist\electron.exe"
    if (-not (Test-Path -LiteralPath $electronExecutable -PathType Leaf)) { return $false }
    $existingUserDataDir = if ($null -ne $ExistingState.PSObject.Properties["electron_user_data_dir"] -and -not [string]::IsNullOrWhiteSpace([string]$ExistingState.electron_user_data_dir)) {
        [string]$ExistingState.electron_user_data_dir
    } else {
        Join-Path $runtimeRoot "electron-user-data"
    }
    New-Item -ItemType Directory -Path $existingUserDataDir -Force | Out-Null
    $environment = @{
        TAICHI_FLOW_DESKTOP_MODE = [string]$ExistingState.mode
        TAICHI_FLOW_API_URL = [string]$ExistingState.api_url
        TAICHI_FLOW_DESKTOP_URL = [string]$ExistingState.desktop_url
        TAICHI_FLOW_OPEN_DEVTOOLS = "0"
    }
    $previous = @{}
    try {
        foreach ($key in $environment.Keys) {
            $previous[$key] = [Environment]::GetEnvironmentVariable([string]$key, "Process")
            [Environment]::SetEnvironmentVariable([string]$key, [string]$environment[$key], "Process")
        }
        Write-LauncherLog "An active desktop session was found; forwarding a second-instance focus request."
        $focusProcess = Start-Process -FilePath $electronExecutable -ArgumentList @("--disable-gpu", "--disable-gpu-compositing", "--user-data-dir=$existingUserDataDir", "desktop\main.cjs") -WorkingDirectory $frontendRoot -PassThru
        $focusAcknowledged = $focusProcess.WaitForExit(10000)
        if (-not $focusAcknowledged) {
            Stop-Process -Id $focusProcess.Id -Force -ErrorAction SilentlyContinue
            throw "The existing Electron instance did not acknowledge the focus request within 10 seconds."
        }
    } finally {
        foreach ($key in $environment.Keys) {
            [Environment]::SetEnvironmentVariable([string]$key, $previous[$key], "Process")
        }
    }
    return $true
}

function Invoke-ExistingServiceSession {
    param([Parameter(Mandatory = $true)]$ExistingState)
    if ([string]$ExistingState.repository_root -ne $repositoryRoot -or
        [string]$ExistingState.mode -ne "dev" -or
        ($null -ne $ExistingState.PSObject.Properties["source_revision"] -and [string]$ExistingState.source_revision -ne $sourceRevision)) {
        return $false
    }
    if ($null -eq $ExistingState.PSObject.Properties["presentation"] -or
        [string]$ExistingState.presentation -notin @("browser", "services")) {
        return $false
    }
    $serviceRecords = @($ExistingState.processes | Where-Object { $_.name -in @("api", "vite") })
    if ($serviceRecords.Count -ne 2) { return $false }
    foreach ($record in $serviceRecords) {
        $actual = Get-TaichiFlowProcessIdentity -ProcessId ([int]$record.pid)
        if (-not (Test-TaichiFlowProcessIdentityMatch -Record $record -Actual $actual)) { return $false }
    }
    $serviceUrl = [string]$ExistingState.desktop_url
    if ([string]::IsNullOrWhiteSpace($serviceUrl)) { return $false }
    if ($presentationName -eq "browser") {
        Write-LauncherLog "A live browser/services session was found; opening its verified renderer URL."
        Start-Process $serviceUrl | Out-Null
    } else {
        Write-LauncherLog "A live browser/services session was found; reusing its verified services without opening a UI."
    }
    $script:SessionState.api_url = [string]$ExistingState.api_url
    $script:SessionState.desktop_url = $serviceUrl
    $script:SessionState.status = "focused-existing-service-session"
    Write-TaichiFlowSessionState -State $script:SessionState -StatePath $statePath
    return $true
}

function Remove-ActiveStateIfOwned {
    if (-not (Test-Path -LiteralPath $activeStatePath -PathType Leaf)) { return }
    $active = Read-TaichiFlowSessionState -StatePath $activeStatePath
    if ($null -ne $active -and [string]$active.session_id -eq $sessionId) {
        Remove-Item -LiteralPath $activeStatePath -Force -ErrorAction SilentlyContinue
    }
}

$exitCode = 1
try {
    $startupMutex = Enter-TaichiFlowStartupLock -RepositoryRoot $repositoryRoot -TimeoutSeconds ([Math]::Min(30, $TimeoutSeconds))
    $existingActiveState = Read-TaichiFlowSessionState -StatePath $activeStatePath
    Write-LauncherLog "Taichi-Flow desktop launcher session=$sessionId mode=$modeName repository=$repositoryRoot"
    foreach ($requiredPath in @(
        (Join-Path $repositoryRoot "api\app.py"),
        (Join-Path $frontendRoot "package.json"),
        (Join-Path $frontendRoot "desktop\main.cjs"),
        (Join-Path $frontendRoot "desktop\runtime-contract.json")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Repository identity check failed; missing $requiredPath"
        }
    }

    $script:SessionState = [pscustomobject][ordered]@{
        session_id = $sessionId
        repository_root = $repositoryRoot
        checkout_id = $checkoutId
        source_revision = $sourceRevision
        created_at = [DateTime]::UtcNow.ToString("o")
        updated_at = [DateTime]::UtcNow.ToString("o")
        launcher_pid = $PID
        mode = $modeName
        presentation = $presentationName
        status = "starting"
        api_url = ""
        api_instance_id = ""
        desktop_url = ""
        electron_user_data_dir = (Join-Path $runtimeRoot "electron-user-data")
        state_path = $statePath
        launcher_log = $launcherLogPath
        processes = @()
        cleanup = @()
    }
    Write-TaichiFlowSessionState -State $script:SessionState -StatePath $statePath

    if ($null -ne $existingActiveState -and [string]$existingActiveState.session_id -ne $sessionId) {
        if ($presentationName -ne "electron" -and (Invoke-ExistingServiceSession -ExistingState $existingActiveState)) {
            $exitCode = 0
            return
        }
        if ($presentationName -eq "electron" -and (Invoke-ExistingDesktopFocus -ExistingState $existingActiveState)) {
            $script:SessionState.status = "focused-existing-session"
            Write-TaichiFlowSessionState -State $script:SessionState -StatePath $statePath
            $exitCode = 0
            return
        }
        Write-LauncherLog "Discarding stale active-session record without terminating any process."
        Remove-Item -LiteralPath $activeStatePath -Force -ErrorAction SilentlyContinue
    }
    $script:PublishActiveState = $true
    Save-LauncherState

    $nodeCommand = Get-Command "node.exe" -ErrorAction Stop | Select-Object -First 1
    $nodeVersion = (& $nodeCommand.Source -p "process.versions.node").Trim()
    if (-not (Test-MinimumNodeVersion -ActualVersion $nodeVersion)) {
        throw "Node.js $nodeVersion is unsupported. Install Node.js 22.12 or newer (Electron 43.2.0 requirement)."
    }
    Write-LauncherLog "Node.js $nodeVersion passed the minimum-version check."

    $lockStampPath = Join-Path $runtimeRoot "npm-lock.sha256"
    if (-not (Test-TaichiFlowNpmDependencies -FrontendRoot $frontendRoot -LockStampPath $lockStampPath)) {
        if ($SkipNpmInstall) { throw "npm dependencies are missing or inconsistent with package-lock.json, and -SkipNpmInstall was requested." }
        Invoke-LauncherNpmStep -Name "npm-ci" -Arguments @("ci", "--no-audit", "--no-fund")
        Get-TaichiFlowFileHash -Path (Join-Path $frontendRoot "package-lock.json") | Set-Content -LiteralPath $lockStampPath -Encoding ASCII
        if (-not (Test-TaichiFlowNpmDependencies -FrontendRoot $frontendRoot -LockStampPath $lockStampPath)) {
            throw "npm ci completed, but the Electron dependency probe still failed."
        }
    }
    Write-LauncherLog "npm dependencies and Electron 43.2.0 are consistent with the lock file."
    Get-TaichiFlowFileHash -Path (Join-Path $frontendRoot "package-lock.json") | Set-Content -LiteralPath $lockStampPath -Encoding ASCII

    $viteSelection = $null
    $selectedFrontendPort = $FrontendPort
    if ($modeName -eq "dev") {
        if (-not (Test-TaichiFlowPortFree -Port $FrontendPort)) {
            $viteSelection = Test-TaichiFlowViteService -Port $FrontendPort -FrontendRoot $frontendRoot
            if ($null -ne $viteSelection -and -not $viteSelection.Reusable) {
                Write-LauncherLog "Vite reuse rejected: source=$([bool]($null -ne $viteSelection.Owner)) proxy=$([bool]$viteSelection.ProxyMatches) error=$([string]$viteSelection.Error)"
            }
        }
        if ($null -eq $viteSelection -or -not $viteSelection.Reusable) {
            $selectedFrontendPort = Find-TaichiFlowFreePort -PreferredPort $FrontendPort
        }
    }

    $apiSelection = $null
    $rendererOrigin = if ($modeName -eq "preview") { "app://taichi-flow" } else { "http://$bindHost`:$selectedFrontendPort" }
    if (-not (Test-TaichiFlowPortFree -Port $ApiPort)) {
        $apiSelection = Test-TaichiFlowApiService -Port $ApiPort -RepositoryRoot $repositoryRoot -RendererOrigin $rendererOrigin
        if ($null -ne $apiSelection -and -not $apiSelection.Reusable) {
            Write-LauncherLog "API reuse rejected: source=$([bool]($null -ne $apiSelection.Owner)) cors=$([bool]$apiSelection.CorsMatches) error=$([string]$apiSelection.Error)"
        }
    }
    $apiProcess = $null
    if ($null -ne $apiSelection -and $apiSelection.Reusable) {
        $selectedApiPort = $ApiPort
        $apiInstanceId = if ($null -ne $apiSelection.Health -and $null -ne $apiSelection.Health.PSObject.Properties["api_instance_id"]) {
            [string]$apiSelection.Health.api_instance_id
        } else { "" }
        Add-LauncherProcessRecord (New-TaichiFlowProcessRecord -Name "api" -Identity $apiSelection.Owner -Owned $false)
        Write-LauncherLog "Reusing verified Taichi-Flow API service on port $selectedApiPort."
    } else {
        $selectedApiPort = Find-TaichiFlowFreePort -PreferredPort $ApiPort
        if ($selectedApiPort -ne $ApiPort) {
            Write-LauncherLog "Port $ApiPort is occupied by an unverified service; using API port $selectedApiPort without terminating the conflict."
        }
        $pythonProbe = Resolve-TaichiFlowPython -RepositoryRoot $repositoryRoot
        Write-LauncherLog "Python $($pythonProbe.Version) selected from $($pythonProbe.Candidate.Source): $($pythonProbe.Candidate.FilePath)"
        $apiInstanceId = Get-TaichiFlowHash "$checkoutId|$sourceRevision|$selectedApiPort"
        $apiStdout = Join-Path $sessionRoot "api.stdout.log"
        $apiStderr = Join-Path $sessionRoot "api.stderr.log"
        $apiArguments = @($pythonProbe.Candidate.PrefixArguments) + @(
            "-m", "uvicorn", "api.app:app", "--app-dir", $repositoryRoot,
            "--host", $bindHost, "--port", [string]$selectedApiPort, "--log-level", "info"
        )
        $apiEnvironment = @{
            TAICHI_FLOW_ALLOWED_ORIGINS = "app://taichi-flow,http://$bindHost`:$selectedFrontendPort"
            TAICHI_FLOW_API_INSTANCE_ID = $apiInstanceId
            # Force UTF-8 mode so Chinese scenario/project names survive SQLite and JSON round-trips on Windows.
            PYTHONUTF8 = "1"
        }
        $apiProcess = Start-TaichiFlowLoggedProcess -Name "api" -FilePath $pythonProbe.Candidate.FilePath -ArgumentList $apiArguments -WorkingDirectory $repositoryRoot -StandardOutputPath $apiStdout -StandardErrorPath $apiStderr -Environment $apiEnvironment
        Add-LauncherProcessRecord (New-TaichiFlowProcessRecord -Name "api" -Identity $apiProcess.Identity -Owned $true -StandardOutputPath $apiStdout -StandardErrorPath $apiStderr)
        Wait-TaichiFlowHttpReady -Url "http://$bindHost`:$selectedApiPort/api/health" -TimeoutSeconds $TimeoutSeconds -Process $apiProcess.Process -Validator {
            param($Response)
            try {
                $health = $Response.Content | ConvertFrom-Json
                return [string]$health.service_id -eq "taichi-flow-api" -and [int]$health.api_contract_version -eq 1 -and [string]$health.checkout_id -eq $checkoutId
            } catch { return $false }
        }
        $apiSelection = Test-TaichiFlowApiService -Port $selectedApiPort -RepositoryRoot $repositoryRoot -RendererOrigin $rendererOrigin -ExpectedExecutablePath $pythonProbe.Candidate.FilePath
        if (-not $apiSelection.Reusable) { throw "Started API did not pass source, checkout, and contract verification." }
        Write-LauncherLog "Owned API service is healthy on port $selectedApiPort."
    }
    $apiUrl = "http://$bindHost`:$selectedApiPort"
    $script:SessionState.api_url = $apiUrl
    $script:SessionState.api_instance_id = $apiInstanceId
    Save-LauncherState

    if ($modeName -eq "dev" -and $null -ne $viteSelection -and $viteSelection.Reusable) {
        $viteProxyCheck = Test-TaichiFlowViteService -Port $selectedFrontendPort -FrontendRoot $frontendRoot -ExpectedApiUrl $apiUrl
        if (-not $viteProxyCheck.Reusable) {
            throw "The reusable Vite service does not proxy to the selected API. Choose a free -FrontendPort or stop the conflicting Vite process."
        }
    }

    $desktopUrl = ""
    if ($modeName -eq "dev") {
        $viteProcess = $null
        if ($null -ne $viteSelection -and $viteSelection.Reusable) {
            Add-LauncherProcessRecord (New-TaichiFlowProcessRecord -Name "vite" -Identity $viteSelection.Owner -Owned $false)
            Write-LauncherLog "Reusing verified Vite service on port $selectedFrontendPort."
        } else {
            if ($selectedFrontendPort -ne $FrontendPort) {
                Write-LauncherLog "Port $FrontendPort is occupied by an unverified service; using Vite port $selectedFrontendPort without terminating the conflict."
            }
            $viteScript = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"
            $viteStdout = Join-Path $sessionRoot "vite.stdout.log"
            $viteStderr = Join-Path $sessionRoot "vite.stderr.log"
            $viteProcess = Start-TaichiFlowLoggedProcess -Name "vite" -FilePath $nodeCommand.Source -ArgumentList @($viteScript, "--host", $bindHost, "--port", [string]$selectedFrontendPort, "--strictPort") -WorkingDirectory $frontendRoot -StandardOutputPath $viteStdout -StandardErrorPath $viteStderr -Environment @{ TAICHI_FLOW_API_URL = $apiUrl }
            Add-LauncherProcessRecord (New-TaichiFlowProcessRecord -Name "vite" -Identity $viteProcess.Identity -Owned $true -StandardOutputPath $viteStdout -StandardErrorPath $viteStderr)
            Wait-TaichiFlowHttpReady -Url "http://$bindHost`:$selectedFrontendPort/" -TimeoutSeconds $TimeoutSeconds -Process $viteProcess.Process -Validator {
                param($Response)
                return $Response.StatusCode -eq 200 -and ([string]$Response.Content).Contains("/@vite/client")
            }
            $viteSelection = Test-TaichiFlowViteService -Port $selectedFrontendPort -FrontendRoot $frontendRoot -ExpectedApiUrl $apiUrl -ExpectedExecutablePath $nodeCommand.Source
            if (-not $viteSelection.Reusable) { throw "Started Vite service did not pass process-source verification." }
            Write-LauncherLog "Owned Vite service is ready on port $selectedFrontendPort."
        }
        $desktopUrl = "http://$bindHost`:$selectedFrontendPort"
    } else {
        Invoke-LauncherNpmStep -Name "npm-build" -Arguments @("run", "build")
        Write-LauncherLog "Preview mode will load the compiled dist through app://taichi-flow."
    }
    $script:SessionState.desktop_url = $desktopUrl
    Save-LauncherState

    if ($presentationName -ne "electron") {
        if ($presentationName -eq "browser") {
            Write-LauncherLog "Opening the explicitly requested browser presentation at $desktopUrl."
            Start-Process $desktopUrl | Out-Null
        } else {
            Write-LauncherLog "Services-only presentation selected; no UI was opened. Renderer URL: $desktopUrl"
        }
        $persistServices = $true
        $script:SessionState.status = if ($presentationName -eq "browser") { "browser-running" } else { "services-running" }
        Save-LauncherState
        $exitCode = 0
        Exit-TaichiFlowStartupLock -Mutex $startupMutex
        $startupMutex = $null
        return
    }

    $electronExecutable = Join-Path $frontendRoot "node_modules\electron\dist\electron.exe"
    $electronStdout = Join-Path $sessionRoot "electron.stdout.log"
    $electronStderr = Join-Path $sessionRoot "electron.stderr.log"
    $electronExitReportPath = Join-Path $sessionRoot "electron-exit-report.json"
    $electronUserDataDir = [string]$script:SessionState.electron_user_data_dir
    New-Item -ItemType Directory -Path $electronUserDataDir -Force | Out-Null
    if ([string]::IsNullOrWhiteSpace($SmokeReportPath)) { $SmokeReportPath = Join-Path $sessionRoot "desktop-smoke-report.json" }
    if ([string]::IsNullOrWhiteSpace($SmokeScreenshotPath)) { $SmokeScreenshotPath = Join-Path $sessionRoot "desktop-smoke.png" }
    $electronEnvironment = @{
        TAICHI_FLOW_DESKTOP_MODE = $modeName
        TAICHI_FLOW_DESKTOP_URL = $desktopUrl
        TAICHI_FLOW_API_URL = $apiUrl
        TAICHI_FLOW_OPEN_DEVTOOLS = if ($OpenDevTools) { "1" } else { "0" }
        TAICHI_FLOW_DESKTOP_SMOKE = if ($Smoke) { "1" } else { "0" }
        TAICHI_FLOW_DESKTOP_SMOKE_REPORT = $SmokeReportPath
        TAICHI_FLOW_DESKTOP_SMOKE_SCREENSHOT = $SmokeScreenshotPath
        TAICHI_FLOW_DESKTOP_EXIT_REPORT = $electronExitReportPath
    }
    Write-LauncherLog "Starting Electron mode=$modeName api=$apiUrl renderer=$($desktopUrl.Trim())"
    $electronProcess = Start-TaichiFlowLoggedProcess -Name "electron" -FilePath $electronExecutable -ArgumentList @("--disable-gpu", "--disable-gpu-compositing", "--user-data-dir=$electronUserDataDir", "desktop\main.cjs") -WorkingDirectory $frontendRoot -StandardOutputPath $electronStdout -StandardErrorPath $electronStderr -Environment $electronEnvironment -Visible
    Add-LauncherProcessRecord (New-TaichiFlowProcessRecord -Name "electron" -Identity $electronProcess.Identity -Owned $true -StandardOutputPath $electronStdout -StandardErrorPath $electronStderr)
    $script:SessionState.status = "running"
    Save-LauncherState
    Exit-TaichiFlowStartupLock -Mutex $startupMutex
    $startupMutex = $null
    $electronProcess.Process.WaitForExit()
    $nativeExitCode = $null
    try { $nativeExitCode = $electronProcess.Process.get_ExitCode() } catch { }
    $desktopExitReport = Read-TaichiFlowSessionState -StatePath $electronExitReportPath
    $exitCode = Resolve-TaichiFlowElectronExitCode -ProcessExitCode $nativeExitCode -ExitReport $desktopExitReport -ExpectedMode $modeName
    if ($exitCode -ne 0) { throw "Electron exited without a successful lifecycle report (resolved code $exitCode). See $electronStderr" }
    Write-LauncherLog "Electron exited normally."
    $script:SessionState.status = "electron-closed"
} catch {
    Write-LauncherLog "ERROR: $($_.Exception.Message)"
    if ($null -ne $script:SessionState) { $script:SessionState.status = "failed" }
    $exitCode = 1
} finally {
    if ($null -ne $script:SessionState) {
        $cleanup = @()
        if (-not $persistServices) {
            $cleanupRecords = @($script:SessionState.processes)
            [array]::Reverse($cleanupRecords)
            foreach ($record in $cleanupRecords) {
                $result = Stop-TaichiFlowOwnedProcess -Record $record
                $cleanup += $result
                if ($result.Stopped) { Write-LauncherLog "Cleanup stopped owned process '$($record.name)' PID $($record.pid)." }
            }
        } else {
            Write-LauncherLog "Leaving service processes running for the '$presentationName' presentation; stop-dev.ps1 owns explicit shutdown."
        }
        $script:SessionState.cleanup = $cleanup
        $script:SessionState.updated_at = [DateTime]::UtcNow.ToString("o")
        if (-not $persistServices -and $script:SessionState.status -ne "focused-existing-session" -and $script:SessionState.status -ne "focused-existing-service-session") {
            $script:SessionState.status = if ($exitCode -eq 0) { "closed-clean" } else { "failed-cleaned" }
        }
        Write-TaichiFlowSessionState -State $script:SessionState -StatePath $statePath
    }
    if (-not $persistServices) { Remove-ActiveStateIfOwned }
    Exit-TaichiFlowStartupLock -Mutex $startupMutex
    $ownedLive = 0
    if ($null -ne $script:SessionState) {
        foreach ($record in @($script:SessionState.processes | Where-Object { $_.owned })) {
            if ($null -ne (Get-TaichiFlowProcessIdentity -ProcessId ([int]$record.pid))) { $ownedLive += 1 }
        }
    }
    $self = Get-Process -Id $PID
    $rssMb = [Math]::Round($self.WorkingSet64 / 1MB, 1)
    $peakMb = [Math]::Round($self.PeakWorkingSet64 / 1MB, 1)
    Write-LauncherLog "[CLEANUP] children=$ownedLive handles=$($self.HandleCount) rss=$rssMb MB peak_rss=$peakMb MB heap=n/a"
    Write-Host "Launcher log: $launcherLogPath"
}

exit $exitCode
