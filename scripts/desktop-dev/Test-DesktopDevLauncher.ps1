[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modulePath = Join-Path $PSScriptRoot "TaichiFlow.DesktopDev.psm1"
Import-Module $modulePath -Force

$script:Assertions = 0

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $script:Assertions += 1
    if ($Actual -ne $Expected) {
        throw "$Message. Expected '$Expected', got '$Actual'."
    }
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $script:Assertions += 1
    if (-not $Condition) {
        throw $Message
    }
}

Assert-Equal (Resolve-TaichiFlowDesktopMode "") "dev" "Empty mode must resolve to dev"
Assert-Equal (Resolve-TaichiFlowDesktopMode "PREVIEW") "preview" "Mode parsing must be case-insensitive"

$invalidModeRejected = $false
try {
    Resolve-TaichiFlowDesktopMode "release" | Out-Null
} catch {
    $invalidModeRejected = $true
}
Assert-True $invalidModeRejected "Unsupported modes must be rejected"

Assert-True (Test-MinimumNodeVersion -ActualVersion "22.12.0") "Electron 43.2.0 Node floor must pass"
Assert-True (-not (Test-MinimumNodeVersion -ActualVersion "22.11.9")) "Node versions below the Electron floor must fail"

$candidateEnvironment = @{
    TAICHI_FLOW_PYTHON = "C:\Python311\python.exe"
    CONDA_PREFIX = "C:\Conda\envs\taichi"
}
$candidateSpecs = @(Get-TaichiFlowPythonCandidate -RepositoryRoot "C:\repo" -Environment $candidateEnvironment -DiscoveredCommands @("C:\Python313\python.exe"))
Assert-Equal $candidateSpecs[0].Source "TAICHI_FLOW_PYTHON" "Explicit Python must have highest priority"
Assert-Equal $candidateSpecs[1].Source "repository .venv" "Repository virtual environment must be second"
Assert-Equal $candidateSpecs[2].Source "current Conda environment" "Current Conda environment must be third"
Assert-Equal $candidateSpecs[3].Source "py -3.11" "Python launcher 3.11 must precede generic discovery"

$candidatesWithoutExplicitPython = @(Get-TaichiFlowPythonCandidate -RepositoryRoot "C:\repo" -Environment @{} -DiscoveredCommands @())
Assert-Equal $candidatesWithoutExplicitPython[0].Source "repository .venv" "An unset optional Python environment variable must be skipped without aborting discovery"

$probeResults = @(
    [pscustomobject]@{ Candidate = $candidateSpecs[0]; Success = $true; Version = "3.14.0"; ImportsReady = $true },
    [pscustomobject]@{ Candidate = $candidateSpecs[1]; Success = $true; Version = "3.11.9"; ImportsReady = $true }
)
$selectedProbe = Select-TaichiFlowPythonProbe -ProbeResults $probeResults
Assert-Equal $selectedProbe.Version "3.11.9" "Python 3.14 must be rejected even when imports appear available"

$python39Probe = Select-TaichiFlowPythonProbe -ProbeResults @([pscustomobject]@{ Candidate = $candidateSpecs[0]; Success = $true; Version = "3.9.18"; ImportsReady = $true })
Assert-Equal $python39Probe.Version "3.9.18" "The repository-supported Python 3.9 floor must remain eligible"

$selectedPort = Find-TaichiFlowFreePort -PreferredPort 3000 -PortProbe {
    param($Port)
    return $Port -ge 3002
}
Assert-Equal $selectedPort 3002 "Port conflicts must advance to the next free loopback port"

$ownedRecord = [pscustomobject]@{
    owned = $true
    pid = 4242
    creation_time_utc = "2026-08-04T00:00:00.0000000Z"
    command_fingerprint = "abc123"
    executable_path = "python.exe"
}
$matchingProcess = [pscustomobject]@{
    pid = 4242
    creation_time_utc = "2026-08-04T00:00:00.0000000Z"
    command_fingerprint = "abc123"
    executable_path = "python.exe"
}
Assert-True (Test-TaichiFlowOwnedProcessIdentity -Record $ownedRecord -Actual $matchingProcess) "Owned process identity must match all immutable fields"

$reusedRecord = $ownedRecord.PSObject.Copy()
$reusedRecord.owned = $false
Assert-True (-not (Test-TaichiFlowOwnedProcessIdentity -Record $reusedRecord -Actual $matchingProcess)) "Reused services must never be cleanup targets"
Assert-True (Test-TaichiFlowProcessIdentityMatch -Record $ownedRecord -Actual $matchingProcess) "Service-session reuse must compare immutable process identity"
$differentExecutable = $matchingProcess.PSObject.Copy()
$differentExecutable.executable_path = "other.exe"
Assert-True (-not (Test-TaichiFlowProcessIdentityMatch -Record $ownedRecord -Actual $differentExecutable)) "Service-session reuse must reject executable-path drift"
$crossPrivilegeRecord = $ownedRecord.PSObject.Copy()
$crossPrivilegeRecord | Add-Member -NotePropertyName identity_source -NotePropertyValue "process-api"
$crossPrivilegeRecord.executable_path = "python"
$crossPrivilegeRecord.command_fingerprint = Get-TaichiFlowHash "python"
$crossPrivilegeActual = [pscustomobject]@{
    pid = 4242
    creation_time_utc = "2026-08-04T00:00:00.0000000Z"
    command_fingerprint = Get-TaichiFlowHash '"C:\Python311\python.exe" -m uvicorn api.app:app'
    executable_path = "C:\Python311\python.exe"
    identity_source = "wmi"
}
Assert-True (Test-TaichiFlowProcessIdentityMatch -Record $crossPrivilegeRecord -Actual $crossPrivilegeActual) "Cross-privilege identity checks must remain safe and reusable"

$replacementProcess = $matchingProcess.PSObject.Copy()
$replacementProcess.creation_time_utc = "2026-08-04T00:01:00.0000000Z"
Assert-True (-not (Test-TaichiFlowOwnedProcessIdentity -Record $ownedRecord -Actual $replacementProcess)) "PID reuse with a different creation time must be rejected"

Assert-Equal (Get-TaichiFlowSessionDisposition -State ([pscustomobject]@{ processes = @($ownedRecord) }) -LiveProcesses @()) "stale-record-only" "Stale state must only be cleaned as a record"

$testWorker = Start-Process -FilePath "powershell.exe" -ArgumentList '-NoProfile -Command "Start-Sleep -Seconds 30"' -WindowStyle Hidden -PassThru
try {
    $testIdentity = $null
    for ($attempt = 0; $attempt -lt 20 -and $null -eq $testIdentity; $attempt += 1) {
        Start-Sleep -Milliseconds 50
        $testIdentity = Get-TaichiFlowProcessIdentity -ProcessId $testWorker.Id
    }
    if ($null -eq $testIdentity) { throw "Self-test worker exited before its identity could be recorded." }
    $testRecord = New-TaichiFlowProcessRecord -Name "selftest-worker" -Identity $testIdentity -Owned $true
    $stopResult = @(Stop-TaichiFlowOwnedProcess -Record $testRecord -GraceMilliseconds 100)
    Assert-Equal $stopResult.Count 1 "Owned-process cleanup must return one structured result without leaking wait output"
    Assert-Equal $stopResult[0].Reason "owned-process-stopped" "Owned-process cleanup must report an explicit reason"
Assert-True ($null -eq (Get-TaichiFlowProcessIdentity -ProcessId $testWorker.Id)) "Owned-process cleanup must terminate the matching worker"
} finally {
    Stop-Process -Id $testWorker.Id -Force -ErrorAction SilentlyContinue
}

Assert-Equal (Resolve-TaichiFlowElectronExitCode -ProcessExitCode $null -ExitReport ([pscustomobject]@{ success = $true; exitCode = 0 })) 0 "A signed desktop exit report must resolve a missing GUI process exit code"
Assert-Equal (Resolve-TaichiFlowElectronExitCode -ProcessExitCode $null -ExitReport ([pscustomobject]@{ success = $false; exitCode = 1 })) 1 "A failed desktop exit report must remain blocking"
Assert-Equal (Resolve-TaichiFlowElectronExitCode -ProcessExitCode $null -ExitReport $null) 1 "A missing desktop exit report must fail closed"
Assert-Equal (Resolve-TaichiFlowElectronExitCode -ProcessExitCode 0 -ExitReport ([pscustomobject]@{ success = $true; exitCode = 0; mode = "dev"; runtimeErrors = @() }) -ExpectedMode "dev") 0 "A matching clean desktop exit report must pass"
Assert-Equal (Resolve-TaichiFlowElectronExitCode -ProcessExitCode 0 -ExitReport ([pscustomobject]@{ success = $true; exitCode = 0; mode = "preview"; runtimeErrors = @() }) -ExpectedMode "dev") 1 "A desktop exit report from the wrong mode must fail closed"

$rootEntryPoint = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\start-dev.ps1") -Raw
Assert-True $rootEntryPoint.Contains('"-Presentation", $presentation') "The root entry point must delegate presentation selection to the managed launcher"
Assert-True (-not $rootEntryPoint.Contains('Start-Process $FrontendUrl')) "The root entry point must not open a browser implicitly"

Write-Output "[SELFTEST] assertions=$script:Assertions status=passed"
