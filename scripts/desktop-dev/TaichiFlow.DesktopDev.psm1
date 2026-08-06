Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RequiredServiceId = "taichi-flow-api"
$script:RequiredApiContractVersion = 1
$script:MinimumNodeVersion = "20.19.0"

function Resolve-TaichiFlowDesktopMode {
    param([AllowEmptyString()][string]$Mode = "dev")
    $normalized = if ([string]::IsNullOrWhiteSpace($Mode)) { "dev" } else { $Mode.Trim().ToLowerInvariant() }
    if ($normalized -notin @("dev", "preview")) {
        throw "Unsupported desktop mode '$Mode'. Use 'dev' or 'preview'."
    }
    return $normalized
}

function Test-MinimumNodeVersion {
    param(
        [Parameter(Mandatory = $true)][string]$ActualVersion,
        [string]$MinimumVersion = $script:MinimumNodeVersion
    )
    try {
        return ([version]$ActualVersion.TrimStart("v")) -ge ([version]$MinimumVersion)
    } catch {
        return $false
    }
}

function Get-TaichiFlowHash {
    param([Parameter(Mandatory = $true)][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-TaichiFlowFileHash {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TaichiFlowCheckoutId {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)
    $normalized = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd("\").ToLowerInvariant()
    return (Get-TaichiFlowHash $normalized).Substring(0, 16)
}

function Add-TaichiFlowPythonCandidate {
    param(
        [System.Collections.Generic.List[object]]$Candidates,
        [System.Collections.Generic.HashSet[string]]$Seen,
        [Parameter(Mandatory = $true)][string]$Source,
        [AllowEmptyString()][string]$FilePath = "",
        [string[]]$PrefixArguments = @()
    )
    if ([string]::IsNullOrWhiteSpace($FilePath)) { return }
    $key = "$($FilePath.Trim().ToLowerInvariant())|$($PrefixArguments -join ' ')"
    if ($Seen.Add($key)) {
        $Candidates.Add([pscustomobject]@{
            Source = $Source
            FilePath = $FilePath
            PrefixArguments = @($PrefixArguments)
        })
    }
}

function Get-TaichiFlowPythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [hashtable]$Environment,
        [string[]]$DiscoveredCommands
    )
    if ($null -eq $Environment) {
        $Environment = @{
            TAICHI_FLOW_PYTHON = $env:TAICHI_FLOW_PYTHON
            CONDA_PREFIX = $env:CONDA_PREFIX
        }
    }
    if ($null -eq $DiscoveredCommands) {
        $discovered = New-Object System.Collections.Generic.List[string]
        foreach ($name in @("python", "python3")) {
            $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -ne $command) { $discovered.Add($command.Source) }
        }
        $DiscoveredCommands = $discovered.ToArray()
    }

    $candidates = New-Object System.Collections.Generic.List[object]
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    Add-TaichiFlowPythonCandidate $candidates $seen "TAICHI_FLOW_PYTHON" ([string]$Environment["TAICHI_FLOW_PYTHON"])
    Add-TaichiFlowPythonCandidate $candidates $seen "repository .venv" (Join-Path $RepositoryRoot ".venv\Scripts\python.exe")
    $condaPrefix = [string]$Environment["CONDA_PREFIX"]
    if (-not [string]::IsNullOrWhiteSpace($condaPrefix)) {
        Add-TaichiFlowPythonCandidate $candidates $seen "current Conda environment" (Join-Path $condaPrefix "python.exe")
    }
    $pyCommand = Get-Command "py.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    $pyPath = if ($null -ne $pyCommand) { $pyCommand.Source } else { "py.exe" }
    Add-TaichiFlowPythonCandidate $candidates $seen "py -3.11" $pyPath @("-3.11")
    foreach ($path in $DiscoveredCommands) {
        Add-TaichiFlowPythonCandidate $candidates $seen "discovered interpreter" $path
    }
    return $candidates.ToArray()
}

function Invoke-TaichiFlowPythonProbe {
    param([Parameter(Mandatory = $true)]$Candidate)
    $probeCode = @'
import json, sys
result = {"version": ".".join(map(str, sys.version_info[:3])), "imports_ready": False}
try:
    import fastapi
    import uvicorn
    import taichi
    result["imports_ready"] = True
except Exception as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"
print("TAICHI_FLOW_PROBE=" + json.dumps(result, ensure_ascii=True))
'@
    try {
        $encodedProbe = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($probeCode))
        $probeLauncher = "import base64;exec(base64.b64decode('$encodedProbe'))"
        $arguments = @($Candidate.PrefixArguments) + @("-c", $probeLauncher)
        $output = @(& $Candidate.FilePath @arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $line = $output | Where-Object { [string]$_ -like "TAICHI_FLOW_PROBE=*" } | Select-Object -Last 1
        if ($exitCode -ne 0 -or $null -eq $line) {
            return [pscustomobject]@{
                Candidate = $Candidate; Success = $false; Version = ""; ImportsReady = $false
                Error = ($output | Out-String).Trim()
            }
        }
        $payload = ([string]$line).Substring("TAICHI_FLOW_PROBE=".Length) | ConvertFrom-Json
        $probeError = if ($null -ne $payload.PSObject.Properties["error"]) { [string]$payload.error } else { "" }
        return [pscustomobject]@{
            Candidate = $Candidate; Success = $true; Version = [string]$payload.version
            ImportsReady = [bool]$payload.imports_ready; Error = $probeError
        }
    } catch {
        return [pscustomobject]@{
            Candidate = $Candidate; Success = $false; Version = ""; ImportsReady = $false; Error = $_.Exception.Message
        }
    }
}

function Select-TaichiFlowPythonProbe {
    param([Parameter(Mandatory = $true)][object[]]$ProbeResults)
    foreach ($probe in $ProbeResults) {
        if (-not $probe.Success -or -not $probe.ImportsReady) { continue }
        try { $version = [version]$probe.Version } catch { continue }
        if ($version -ge [version]"3.9.0" -and $version -lt [version]"3.14.0") {
            return $probe
        }
    }
    throw "No compatible Python interpreter was found. Taichi-Flow desktop development requires Python 3.9-3.13 with FastAPI, Uvicorn, and Taichi importable; Python 3.14 is explicitly unsupported."
}

function Resolve-TaichiFlowPython {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)
    $probes = New-Object System.Collections.Generic.List[object]
    foreach ($candidate in @(Get-TaichiFlowPythonCandidate -RepositoryRoot $RepositoryRoot)) {
        $probe = Invoke-TaichiFlowPythonProbe -Candidate $candidate
        $probes.Add($probe)
        if ($probe.Success -and $probe.ImportsReady) {
            try {
                $version = [version]$probe.Version
                if ($version -ge [version]"3.9.0" -and $version -lt [version]"3.14.0") { return $probe }
            } catch { }
        }
    }
    Select-TaichiFlowPythonProbe -ProbeResults $probes.ToArray() | Out-Null
}

function Test-TaichiFlowPortFree {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) { $listener.Stop() }
    }
}

function Find-TaichiFlowFreePort {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PreferredPort,
        [scriptblock]$PortProbe = { param($Port) Test-TaichiFlowPortFree -Port $Port },
        [ValidateRange(1, 500)][int]$SearchWindow = 100
    )
    $lastPort = [Math]::Min(65535, $PreferredPort + $SearchWindow - 1)
    for ($port = $PreferredPort; $port -le $lastPort; $port += 1) {
        if ([bool](& $PortProbe $port)) { return $port }
    }
    throw "No free loopback port was found in range $PreferredPort-$lastPort."
}

function Get-TaichiFlowProcessIdentity {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    $creation = $process.CreationDate
    if ($creation -is [datetime]) {
        $creationUtc = $creation.ToUniversalTime().ToString("o")
    } else {
        $creationUtc = [System.Management.ManagementDateTimeConverter]::ToDateTime([string]$creation).ToUniversalTime().ToString("o")
    }
    $commandLine = [string]$process.CommandLine
    return [pscustomobject]@{
        pid = [int]$process.ProcessId
        parent_pid = [int]$process.ParentProcessId
        creation_time_utc = $creationUtc
        command_line = $commandLine
        command_fingerprint = Get-TaichiFlowHash $commandLine
        executable_path = [string]$process.ExecutablePath
    }
}

function Test-TaichiFlowOwnedProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]$Record,
        $Actual
    )
    if ($null -eq $Actual -or -not [bool]$Record.owned) { return $false }
    return ([int]$Record.pid -eq [int]$Actual.pid) -and
        ([string]$Record.creation_time_utc -eq [string]$Actual.creation_time_utc) -and
        ([string]$Record.command_fingerprint -eq [string]$Actual.command_fingerprint)
}

function Get-TaichiFlowSessionDisposition {
    param(
        [Parameter(Mandatory = $true)]$State,
        [object[]]$LiveProcesses
    )
    foreach ($record in @($State.processes)) {
        foreach ($actual in @($LiveProcesses)) {
            if (Test-TaichiFlowOwnedProcessIdentity -Record $record -Actual $actual) { return "active" }
        }
    }
    return "stale-record-only"
}

function Get-TaichiFlowPortOwner {
    param([Parameter(Mandatory = $true)][int]$Port)
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) { return $null }
    return Get-TaichiFlowProcessIdentity -ProcessId ([int]$connection.OwningProcess)
}

function Test-TaichiFlowApiService {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        $health = $response.Content | ConvertFrom-Json
        $owner = Get-TaichiFlowPortOwner -Port $Port
        $ownerCommand = if ($null -ne $owner) { ([string]$owner.command_line).ToLowerInvariant() } else { "" }
        $sourceMatches = $null -ne $owner -and $ownerCommand.Contains("uvicorn") -and $ownerCommand.Contains("api.app:app")
        $contractMatches = [string]$health.service_id -eq $script:RequiredServiceId -and
            [int]$health.api_contract_version -eq $script:RequiredApiContractVersion -and
            [string]$health.checkout_id -eq (Get-TaichiFlowCheckoutId -RepositoryRoot $RepositoryRoot)
        return [pscustomobject]@{ Reusable = [bool]($sourceMatches -and $contractMatches); Health = $health; Owner = $owner }
    } catch {
        return [pscustomobject]@{ Reusable = $false; Health = $null; Owner = (Get-TaichiFlowPortOwner -Port $Port); Error = $_.Exception.Message }
    }
}

function Test-TaichiFlowViteService {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$FrontendRoot
    )
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2
        $owner = Get-TaichiFlowPortOwner -Port $Port
        $rootToken = [System.IO.Path]::GetFullPath($FrontendRoot).TrimEnd("\").ToLowerInvariant()
        $sourceMatches = $null -ne $owner -and ([string]$owner.command_line).ToLowerInvariant().Contains($rootToken) -and ([string]$owner.command_line).ToLowerInvariant().Contains("vite")
        $contentMatches = $response.StatusCode -eq 200 -and ([string]$response.Content).Contains("/@vite/client")
        return [pscustomobject]@{ Reusable = [bool]($sourceMatches -and $contentMatches); Owner = $owner }
    } catch {
        return [pscustomobject]@{ Reusable = $false; Owner = (Get-TaichiFlowPortOwner -Port $Port); Error = $_.Exception.Message }
    }
}

function Start-TaichiFlowLoggedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$StandardOutputPath,
        [Parameter(Mandatory = $true)][string]$StandardErrorPath,
        [hashtable]$Environment = @{},
        [switch]$Visible
    )
    New-Item -ItemType Directory -Path (Split-Path -Parent $StandardOutputPath) -Force | Out-Null
    $previous = @{}
    try {
        foreach ($key in $Environment.Keys) {
            $previous[$key] = [Environment]::GetEnvironmentVariable([string]$key, "Process")
            [Environment]::SetEnvironmentVariable([string]$key, [string]$Environment[$key], "Process")
        }
        $parameters = @{
            FilePath = $FilePath
            ArgumentList = @($ArgumentList)
            WorkingDirectory = $WorkingDirectory
            RedirectStandardOutput = $StandardOutputPath
            RedirectStandardError = $StandardErrorPath
            PassThru = $true
        }
        if (-not $Visible) { $parameters["WindowStyle"] = "Hidden" }
        $process = Start-Process @parameters
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable([string]$key, $previous[$key], "Process")
        }
    }
    $identity = $null
    for ($attempt = 0; $attempt -lt 20 -and $null -eq $identity; $attempt += 1) {
        Start-Sleep -Milliseconds 50
        $identity = Get-TaichiFlowProcessIdentity -ProcessId $process.Id
    }
    if ($null -eq $identity) { throw "$Name exited before its process identity could be recorded." }
    return [pscustomobject]@{ Process = $process; Identity = $identity }
}

function New-TaichiFlowProcessRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Identity,
        [Parameter(Mandatory = $true)][bool]$Owned,
        [string]$StandardOutputPath = "",
        [string]$StandardErrorPath = ""
    )
    return [pscustomobject]@{
        name = $Name
        pid = [int]$Identity.pid
        creation_time_utc = [string]$Identity.creation_time_utc
        command_fingerprint = [string]$Identity.command_fingerprint
        executable_path = [string]$Identity.executable_path
        owned = $Owned
        stdout = $StandardOutputPath
        stderr = $StandardErrorPath
    }
}

function Wait-TaichiFlowHttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][scriptblock]$Validator,
        [int]$TimeoutSeconds = 90,
        [System.Diagnostics.Process]$Process
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if ($null -ne $Process -and $Process.HasExited) { throw "Process exited with code $($Process.ExitCode) while waiting for $Url." }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ([bool](& $Validator $response)) { return }
        } catch { }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out after $TimeoutSeconds seconds waiting for $Url."
}

function Write-TaichiFlowSessionState {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$StatePath
    )
    New-Item -ItemType Directory -Path (Split-Path -Parent $StatePath) -Force | Out-Null
    $temporaryPath = "$StatePath.tmp"
    $State | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $StatePath -Force
}

function Read-TaichiFlowSessionState {
    param([Parameter(Mandatory = $true)][string]$StatePath)
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json } catch { return $null }
}

function Get-TaichiFlowDescendantProcessId {
    param([Parameter(Mandatory = $true)][int]$RootProcessId)
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $known = New-Object 'System.Collections.Generic.HashSet[int]'
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($RootProcessId)
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        foreach ($child in $all | Where-Object { [int]$_.ParentProcessId -eq $parent }) {
            $childId = [int]$child.ProcessId
            if ($known.Add($childId)) { $queue.Enqueue($childId) }
        }
    }
    return @($known | ForEach-Object { $_ })
}

function Stop-TaichiFlowOwnedProcess {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [int]$GraceMilliseconds = 1500
    )
    $actual = Get-TaichiFlowProcessIdentity -ProcessId ([int]$Record.pid)
    if (-not (Test-TaichiFlowOwnedProcessIdentity -Record $Record -Actual $actual)) {
        return [pscustomobject]@{ Name = [string]$Record.name; Stopped = $false; Reason = "not-owned-or-identity-mismatch" }
    }
    $descendants = @(Get-TaichiFlowDescendantProcessId -RootProcessId ([int]$Record.pid))
    $root = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -ne $root) {
        [void]$root.CloseMainWindow()
        try { [void]$root.WaitForExit($GraceMilliseconds) } catch { }
    }
    $root = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -ne $root) { Stop-Process -Id $root.Id -Force -ErrorAction SilentlyContinue }
    foreach ($childId in ($descendants | Sort-Object -Descending)) {
        Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ Name = [string]$Record.name; Stopped = $true; Reason = "owned-process-stopped" }
}

function Test-TaichiFlowNpmDependencies {
    param(
        [Parameter(Mandatory = $true)][string]$FrontendRoot,
        [Parameter(Mandatory = $true)][string]$LockStampPath,
        [string]$ExpectedElectronVersion = "43.2.0"
    )
    $packageLock = Join-Path $FrontendRoot "package-lock.json"
    $installedLock = Join-Path $FrontendRoot "node_modules\.package-lock.json"
    $electronExecutable = Join-Path $FrontendRoot "node_modules\electron\dist\electron.exe"
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "node_modules") -PathType Container)) { return $false }
    if (-not (Test-Path -LiteralPath $packageLock -PathType Leaf) -or -not (Test-Path -LiteralPath $installedLock -PathType Leaf) -or -not (Test-Path -LiteralPath $electronExecutable -PathType Leaf)) { return $false }
    try {
        $nodeCommand = Get-Command "node.exe" -ErrorAction Stop | Select-Object -First 1
        $lockProbeCode = "const fs=require('node:fs');const root=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const installed=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));console.log(JSON.stringify({declared:root.packages[''].devDependencies.electron,installed:installed.packages['node_modules/electron'].version}));"
        $lockVersions = (& $nodeCommand.Source -e $lockProbeCode $packageLock $installedLock) | ConvertFrom-Json
        if ([string]$lockVersions.declared -ne $ExpectedElectronVersion) { return $false }
        if ([string]$lockVersions.installed -ne $ExpectedElectronVersion) { return $false }
        $npmCommand = Get-Command "npm.cmd" -ErrorAction Stop | Select-Object -First 1
        & $npmCommand.Source ls --depth=0 --json --prefix $FrontendRoot 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $electronPackage = Join-Path $FrontendRoot "node_modules\electron\package.json"
        $electronPathFile = Join-Path $FrontendRoot "node_modules\electron\path.txt"
        if (-not (Test-Path -LiteralPath $electronPackage -PathType Leaf) -or -not (Test-Path -LiteralPath $electronPathFile -PathType Leaf)) { return $false }
        $installedPackageVersion = (& $nodeCommand.Source -p "require(process.argv[1]).version" $electronPackage).Trim()
        $binaryName = (Get-Content -LiteralPath $electronPathFile -Raw).Trim()
        return $LASTEXITCODE -eq 0 -and $installedPackageVersion -eq $ExpectedElectronVersion -and $binaryName -eq "electron.exe" -and (Get-Item -LiteralPath $electronExecutable).Length -gt 0
    } catch {
        return $false
    }
}

function Resolve-TaichiFlowElectronExitCode {
    param(
        [AllowNull()]$ProcessExitCode,
        [AllowNull()]$ExitReport
    )
    if ($null -ne $ExitReport) {
        if ([bool]$ExitReport.success) { return 0 }
        if ($null -ne $ExitReport.PSObject.Properties["exitCode"]) { return [int]$ExitReport.exitCode }
        return 1
    }
    if ($null -ne $ProcessExitCode -and [string]$ProcessExitCode -ne "") { return [int]$ProcessExitCode }
    return -1
}

Export-ModuleMember -Function @(
    "Resolve-TaichiFlowDesktopMode",
    "Test-MinimumNodeVersion",
    "Get-TaichiFlowHash",
    "Get-TaichiFlowFileHash",
    "Get-TaichiFlowCheckoutId",
    "Get-TaichiFlowPythonCandidate",
    "Invoke-TaichiFlowPythonProbe",
    "Select-TaichiFlowPythonProbe",
    "Resolve-TaichiFlowPython",
    "Test-TaichiFlowPortFree",
    "Find-TaichiFlowFreePort",
    "Get-TaichiFlowProcessIdentity",
    "Test-TaichiFlowOwnedProcessIdentity",
    "Get-TaichiFlowSessionDisposition",
    "Get-TaichiFlowPortOwner",
    "Test-TaichiFlowApiService",
    "Test-TaichiFlowViteService",
    "Start-TaichiFlowLoggedProcess",
    "New-TaichiFlowProcessRecord",
    "Wait-TaichiFlowHttpReady",
    "Write-TaichiFlowSessionState",
    "Read-TaichiFlowSessionState",
    "Stop-TaichiFlowOwnedProcess",
    "Test-TaichiFlowNpmDependencies",
    "Resolve-TaichiFlowElectronExitCode"
)
