[CmdletBinding()]
param(
    [string]$Root = "",
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..")) }
$Root = [System.IO.Path]::GetFullPath($Root)
$manifestPath = Join-Path $Root "portable-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "portable-manifest.json is missing." }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $Root ".runtime\portable\python\python.exe"
$helper = Join-Path $Root "scripts\portable\relocate_paths.py"
$verifyReport = Join-Path $Root ".runtime\portable\verify-report.json"
$smokeReport = $null

function Get-PortableSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

function Invoke-PortablePython {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
    $pythonRoot = Split-Path -Parent $python
    [Environment]::SetEnvironmentVariable("PATH", "$pythonRoot;$($pythonRoot)\DLLs;$previousPath", "Process")
    try { return @(& $python @Arguments 2>&1) } finally { [Environment]::SetEnvironmentVariable("PATH", $previousPath, "Process") }
}

Write-Host "[verify] checking manifest key-file hashes"
foreach ($file in @($manifest.files)) {
    $path = Join-Path $Root ([string]$file.path)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Manifest file is missing: $($file.path)" }
    $actual = Get-PortableSha256 -Path $path
    if ($actual -ne [string]$file.sha256 -and [string]$file.path -ne "portable-manifest.json") {
        throw "Portable file hash mismatch: $($file.path)"
    }
}

Write-Host "[verify] checking private Python imports"
$probe = Invoke-PortablePython @("-c", "import sys,fastapi,uvicorn,taichi,rasterio,geopandas,shapely,psutil,dotenv; print(sys.version.split()[0]); print(taichi.__version__); print(geopandas.__version__); print(shapely.__version__); print(psutil.__version__)")
if ($LASTEXITCODE -ne 0) { throw "Private Python import verification failed: $($probe -join [Environment]::NewLine)" }

Write-Host "[verify] checking and (when needed) relocating SQLite paths"
# Verification is also the supported post-copy entry point.  Let the
# transaction perform a drive-letter/path migration first, then validate the
# resulting files; the helper atomically advances portable_root on success.
$relocation = Invoke-PortablePython @($helper, "--root", $Root, "--manifest", $manifestPath)
if ($LASTEXITCODE -ne 0) { throw "SQLite relocation verification failed: $($relocation -join [Environment]::NewLine)" }
$relocationLine = $relocation | Where-Object { [string]$_ -like "TAICHI_FLOW_RELOCATION=*" } | Select-Object -Last 1
if ($null -eq $relocationLine) { throw "SQLite relocation verification returned no report." }
$relocationReport = ([string]$relocationLine).Substring("TAICHI_FLOW_RELOCATION=".Length) | ConvertFrom-Json

Write-Host "[verify] starting the bundle with no Node.js or system Python dependency"
$startScript = Join-Path $Root "scripts\portable\Start-Taichi-Flow-Portable.ps1"
# Deliberately remove the usual interpreter hints and restrict PATH to Windows
# PowerShell/System32 while the managed launcher runs. It must use only the
# absolute private Python and packaged Electron paths.
$savedEnvironment = @{}
foreach ($name in @("TAICHI_FLOW_PYTHON", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_EXE", "NODE_PATH", "NPM_CONFIG_PREFIX", "PATH")) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
[Environment]::SetEnvironmentVariable("TAICHI_FLOW_PYTHON", "", "Process")
[Environment]::SetEnvironmentVariable("CONDA_PREFIX", "", "Process")
[Environment]::SetEnvironmentVariable("CONDA_DEFAULT_ENV", "", "Process")
[Environment]::SetEnvironmentVariable("CONDA_EXE", "", "Process")
[Environment]::SetEnvironmentVariable("NODE_PATH", "", "Process")
[Environment]::SetEnvironmentVariable("NPM_CONFIG_PREFIX", "", "Process")
[Environment]::SetEnvironmentVariable("PATH", "$env:SystemRoot\System32;$env:SystemRoot\System32\WindowsPowerShell\v1.0", "Process")
try {
    & $powershellExe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $startScript -Root $Root -TimeoutSeconds $TimeoutSeconds -Smoke
    $startExit = $LASTEXITCODE
} finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process") }
}
if ($startExit -ne 0) { throw "Portable Electron/API smoke startup failed with exit code $startExit." }
$smokeCandidates = Get-ChildItem -LiteralPath (Join-Path $Root ".runtime\portable\sessions") -Filter "portable-smoke-report.json" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime
$smokePath = $smokeCandidates | Select-Object -Last 1
if ($null -eq $smokePath) { throw "Portable smoke report was not created." }
$smokeReport = Get-Content -LiteralPath $smokePath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$smokeReport.success) { throw "Portable smoke report is unsuccessful: $($smokePath.FullName)" }
if (-not [bool]$smokeReport.apiHealth.ok -or [int]$smokeReport.apiHealth.status -ne 200) { throw "Portable API health did not return HTTP 200." }
if ([string]$smokeReport.apiHealth.body.distribution_mode -ne "portable") { throw "Portable API did not publish distribution_mode=portable." }
if ([string]$smokeReport.apiHealth.body.build_id -ne [string]$manifest.build_id) { throw "Portable API build id does not match the manifest." }

$projectRelative = [string]$manifest.project.relative_path
$projectDb = Join-Path $Root "$projectRelative\.taichi-flow\state.sqlite3"
# Passing a multi-line -c string through Windows PowerShell can split quoted
# SQL and produce a misleading Python syntax error. Use a short-lived ASCII
# script file and pass the database path as argv instead.
$queryPath = Join-Path $Root ".runtime\portable\verify-project-query.py"
$query = @'
import json, pathlib, sqlite3, sys
p = pathlib.Path(sys.argv[1])
c = sqlite3.connect(p)
payload = {
 "scenarios": c.execute("select count(*) from scenarios").fetchone()[0],
 "completed_simulations": c.execute("select count(*) from simulation_runs where status='completed'").fetchone()[0],
 "result_families": c.execute("select count(*) from result_families").fetchone()[0],
 "result_files": sum(int(r[0] or 0) for r in c.execute("select file_count from result_families")),
 "integrity": c.execute("pragma integrity_check").fetchone()[0],
}
print(json.dumps(payload))
'@
Set-Content -LiteralPath $queryPath -Value $query -Encoding ASCII
try {
    $dbOutput = Invoke-PortablePython @($queryPath, $projectDb)
    if ($LASTEXITCODE -ne 0) { throw "Portable project count query failed: $($dbOutput -join [Environment]::NewLine)" }
} finally {
    Remove-Item -LiteralPath $queryPath -Force -ErrorAction SilentlyContinue
}
$counts = ($dbOutput | Select-Object -Last 1 | ConvertFrom-Json)
if ([string]$counts.integrity -ne "ok") { throw "Portable project SQLite integrity check failed." }
if ([int]$counts.completed_simulations -lt 2 -or [int]$counts.result_families -lt 26 -or [int]$counts.result_files -lt 42) { throw "Bundled demo dataset counts are incomplete: $($dbOutput -join ' ')" }

$report = [ordered]@{
    success = $true
    verified_at = [DateTime]::UtcNow.ToString("o")
    root = $Root
    build_id = [string]$manifest.build_id
    smoke_report = $smokePath.FullName
    api_health = $smokeReport.apiHealth
    renderer = [ordered]@{
        title = [string]$smokeReport.title
        url = [string]$smokeReport.url
        text_length = [int]$smokeReport.textLength
        desktop_runtime = [bool]$smokeReport.desktopRuntime
        desktop_mode = [string]$smokeReport.desktopMode
        desktop_version = [string]$smokeReport.desktopVersion
        build_id = [string]$smokeReport.buildId
        distribution_mode = [string]$smokeReport.distributionMode
        api_url = [string]$smokeReport.apiUrl
        api_contract_version = [int]$smokeReport.apiContractVersion
        directory_picker_bridge = [bool]$smokeReport.directoryPickerBridge
        route_mode = [string]$smokeReport.routeMode
    }
    project_counts = $counts
    relocation = $relocationReport
    node_required = $false
    system_python_required = $false
}
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $verifyReport -Encoding UTF8
Write-Host "[VERIFY] success build=$($manifest.build_id) scenarios=$($counts.scenarios) completed=$($counts.completed_simulations) families=$($counts.result_families) files=$($counts.result_files)"
