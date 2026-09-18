[CmdletBinding()]
param(
    [string]$SourceRoot = "",
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$PythonEmbedZip = "",
    [string]$PythonSitePackages = "",
    [string]$DemoProjectPath = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$frontendRoot = Join-Path $SourceRoot "frontend\taichi-flow"
$portableScriptRoot = Join-Path $SourceRoot "scripts\portable"
# Python 3.11.15 is source-only on python.org (no Windows embeddable ZIP).
# 3.11.9 is the final 3.11 release with a Windows embeddable binary and is
# the version whose Taichi 1.7.4 environment is verified on this host.
$pythonVersion = "3.11.9"
$electronVersion = "43.2.0"
$portableRuntimeLock = Join-Path $portableScriptRoot "portable-runtime.lock.txt"
$projectRelative = "data\projects\chamoli-reference-e2e-20260828-v4"
if ([string]::IsNullOrWhiteSpace($DemoProjectPath)) {
    $DemoProjectPath = Join-Path $SourceRoot "artifacts\e2e\chamoli-reference-e2e-20260828-v4"
}
$projectSource = [System.IO.Path]::GetFullPath($DemoProjectPath)
$projectDatabase = Join-Path $projectSource ".taichi-flow\state.sqlite3"
if (-not (Test-Path -LiteralPath $projectSource -PathType Container)) {
    throw "Compact demonstration project is missing: $projectSource. Supply -DemoProjectPath with a prepared project directory."
}
if (-not (Test-Path -LiteralPath $projectDatabase -PathType Leaf)) {
    throw "Demonstration project is not a portable Taichi-Flow project (state database missing): $projectDatabase"
}
if ($OutputRoot.StartsWith($projectSource, [System.StringComparison]::OrdinalIgnoreCase) -or $projectSource.StartsWith($OutputRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot and DemoProjectPath must not contain one another."
}

foreach ($required in @(
    (Join-Path $SourceRoot "api\app.py"),
    (Join-Path $SourceRoot "edda"),
    (Join-Path $frontendRoot "dist\index.html"),
    (Join-Path $frontendRoot "desktop\main.cjs"),
    (Join-Path $frontendRoot "node_modules\electron\dist\electron.exe"),
    (Join-Path $portableScriptRoot "relocate_paths.py"),
    $portableRuntimeLock
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Portable build prerequisite is missing: $required" }
}

if (Test-Path -LiteralPath $OutputRoot) {
    $marker = Join-Path $OutputRoot ".portable-build-marker"
    if (-not $Force -or -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw "Output exists and is not a confirmed portable staging directory: $OutputRoot"
    }
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
Set-Content -LiteralPath (Join-Path $OutputRoot ".portable-build-marker") -Value "Taichi-Flow portable staging; generated $(Get-Date -Format o)" -Encoding ASCII

function Copy-PortableItem {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $source = Join-Path $SourceRoot $RelativePath
    $destination = Join-Path $OutputRoot $RelativePath
    if (Test-Path -LiteralPath $source -PathType Container) {
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        foreach ($child in @(Get-ChildItem -LiteralPath $source -Force)) {
            Copy-Item -LiteralPath $child.FullName -Destination $destination -Recurse -Force
        }
    } elseif (Test-Path -LiteralPath $source -PathType Leaf) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    } else {
        throw "Cannot copy missing portable payload: $source"
    }
}

Write-Host "[portable] copying backend and static application payload"
foreach ($item in @(
    "api", "edda", "taichi_flow", "examples", "config.yaml", "config_example.yaml",
    "config_double_layer_example.yaml", "requirements.txt", "setup.py", "environment.yml"
)) { Copy-PortableItem $item }

$appRoot = Join-Path $OutputRoot "app"
New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $frontendRoot "dist") -Destination (Join-Path $appRoot "dist") -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $appRoot "dist") -PathType Container) {
    # Copy-Item above may create a nested dist when the destination already
    # exists; normalize it to the expected app\dist layout.
    $nestedDist = Join-Path $appRoot "dist\dist"
    if (Test-Path -LiteralPath $nestedDist -PathType Container) {
        Get-ChildItem -LiteralPath $nestedDist -Force | Move-Item -Destination (Join-Path $appRoot "dist") -Force
        Remove-Item -LiteralPath $nestedDist -Recurse -Force
    }
}
New-Item -ItemType Directory -Path (Join-Path $appRoot "desktop") -Force | Out-Null
foreach ($child in @(Get-ChildItem -LiteralPath (Join-Path $frontendRoot "desktop") -Force)) {
    Copy-Item -LiteralPath $child.FullName -Destination (Join-Path $appRoot "desktop") -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $frontendRoot "package.json") -Destination (Join-Path $appRoot "package.json") -Force

$outputScripts = Join-Path $OutputRoot "scripts"
New-Item -ItemType Directory -Path (Join-Path $outputScripts "portable"), (Join-Path $outputScripts "desktop-dev") -Force | Out-Null
foreach ($scriptName in @("Start-Taichi-Flow-Portable.ps1", "Stop-Taichi-Flow-Portable.ps1", "Verify-Taichi-Flow-Portable.ps1", "relocate_paths.py", "register_project.py", "portable-runtime.lock.txt")) {
    Copy-Item -LiteralPath (Join-Path $portableScriptRoot $scriptName) -Destination (Join-Path $outputScripts "portable\$scriptName") -Force
}
Copy-Item -LiteralPath (Join-Path $SourceRoot "scripts\desktop-dev\TaichiFlow.DesktopDev.psm1") -Destination (Join-Path $outputScripts "desktop-dev\TaichiFlow.DesktopDev.psm1") -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot "scripts\desktop-dev\Start-DesktopDev.ps1") -Destination (Join-Path $outputScripts "desktop-dev\Start-DesktopDev.ps1") -Force
foreach ($rootCommand in @("Start-Taichi-Flow.cmd", "Stop-Taichi-Flow.cmd", "Verify-Taichi-Flow.cmd")) {
    Copy-Item -LiteralPath (Join-Path $SourceRoot $rootCommand) -Destination (Join-Path $OutputRoot $rootCommand) -Force
}

$electronSource = Join-Path $frontendRoot "node_modules\electron\dist"
$electronDestination = Join-Path $OutputRoot ".runtime\portable\electron"
New-Item -ItemType Directory -Path $electronDestination -Force | Out-Null
foreach ($child in @(Get-ChildItem -LiteralPath $electronSource -Force)) {
    Copy-Item -LiteralPath $child.FullName -Destination $electronDestination -Recurse -Force
}
$electronExe = Join-Path $electronDestination "electron.exe"
$portableElectronExe = Join-Path $electronDestination "Taichi-Flow.exe"
if (-not (Test-Path -LiteralPath $portableElectronExe)) {
    Copy-Item -LiteralPath $electronExe -Destination $portableElectronExe -Force
}

function Resolve-BuildPython {
    if (-not [string]::IsNullOrWhiteSpace($PythonSitePackages)) { return [System.IO.Path]::GetFullPath($PythonSitePackages) }
    $known = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python\Python311\Lib\site-packages"
    if (Test-Path -LiteralPath $known -PathType Container) { return $known }
    throw "Python 3.11 site-packages source was not found. Supply -PythonSitePackages."
}

function Resolve-EmbedZip {
    if (-not [string]::IsNullOrWhiteSpace($PythonEmbedZip)) {
        $candidate = [System.IO.Path]::GetFullPath($PythonEmbedZip)
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Python embeddable ZIP not found: $candidate" }
        return $candidate
    }
    $cacheRoot = Join-Path $SourceRoot ".runtime\portable-cache"
    New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
    $cached = Join-Path $cacheRoot "python-$pythonVersion-embeddable-amd64.zip"
    if (-not (Test-Path -LiteralPath $cached -PathType Leaf)) {
        $url = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embeddable-amd64.zip"
        Write-Host "[portable] downloading official CPython $pythonVersion embeddable runtime"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $cached
    }
    return $cached
}

Write-Host "[portable] assembling private CPython $pythonVersion runtime"
$pythonRoot = Join-Path $OutputRoot ".runtime\portable\python"
New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null
Expand-Archive -LiteralPath (Resolve-EmbedZip) -DestinationPath $pythonRoot -Force
$fullPythonRoot = Split-Path -Parent (Split-Path -Parent (Resolve-BuildPython))
$sitePackagesDestination = Join-Path $pythonRoot "Lib\site-packages"
New-Item -ItemType Directory -Path $sitePackagesDestination -Force | Out-Null
foreach ($child in @(Get-ChildItem -LiteralPath (Resolve-BuildPython) -Force)) {
    Copy-Item -LiteralPath $child.FullName -Destination $sitePackagesDestination -Recurse -Force
}
# The ordinary Python installation contains the core runtime. The wheel cache
# carries packages that are absent from a minimal local installation
# (notably GeoPandas/Shapely and psutil). Copy it after the core packages so
# its transitive wheels remain a self-contained, consistent set.
$extraSitePackages = Join-Path $SourceRoot ".runtime\portable-cache\extra-site-packages"
if (-not (Test-Path -LiteralPath $extraSitePackages -PathType Container)) {
    throw "Portable extra runtime dependency cache is missing: $extraSitePackages"
}
Write-Host "[portable] adding vendored geospatial/system dependency wheels"
foreach ($child in @(Get-ChildItem -LiteralPath $extraSitePackages -Force)) {
    Copy-Item -LiteralPath $child.FullName -Destination $sitePackagesDestination -Recurse -Force
}
$fullDlls = Join-Path $fullPythonRoot "DLLs"
if (Test-Path -LiteralPath $fullDlls -PathType Container) {
    New-Item -ItemType Directory -Path (Join-Path $pythonRoot "DLLs") -Force | Out-Null
    foreach ($child in @(Get-ChildItem -LiteralPath $fullDlls -Force)) {
        Copy-Item -LiteralPath $child.FullName -Destination (Join-Path $pythonRoot "DLLs") -Recurse -Force
    }
}
foreach ($file in @("vcruntime140.dll", "vcruntime140_1.dll")) {
    $source = Join-Path $fullPythonRoot $file
    if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination $pythonRoot -Force }
}
$pth = Join-Path $pythonRoot "python311._pth"
if (-not (Test-Path -LiteralPath $pth -PathType Leaf)) { throw "Embeddable Python did not provide python311._pth" }
@("python311.zip", ".", "DLLs", "Lib\site-packages", "import site") | Set-Content -LiteralPath $pth -Encoding ASCII

$portablePython = Join-Path $pythonRoot "python.exe"
if (-not (Test-Path -LiteralPath $portablePython -PathType Leaf)) { throw "Portable Python executable is missing." }
$probeCode = "import sys,fastapi,uvicorn,taichi,rasterio,geopandas,shapely,psutil,dotenv; print(sys.version.split()[0]); print(taichi.__version__); print(geopandas.__version__); print(shapely.__version__); print(psutil.__version__)"
$probeOutput = @(& $portablePython -c $probeCode 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Portable Python import probe failed: $($probeOutput -join [Environment]::NewLine)" }
Write-Host "[portable] Python probe passed: $($probeOutput -join ' ')"

$projectDestination = Join-Path $OutputRoot $projectRelative
New-Item -ItemType Directory -Path (Split-Path -Parent $projectDestination) -Force | Out-Null
Write-Host "[portable] copying compact demonstration project"
Copy-Item -LiteralPath $projectSource -Destination $projectDestination -Recurse -Force

$sourceRevision = "unknown"
try {
    $git = Get-Command git.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $git) { $sourceRevision = (& $git.Source -C $SourceRoot rev-parse HEAD 2>$null).Trim() }
} catch { }
$hash = [System.Security.Cryptography.SHA256]::Create()
try { $buildDigest = ([BitConverter]::ToString($hash.ComputeHash([System.Text.Encoding]::UTF8.GetBytes("$sourceRevision|$electronVersion|$pythonVersion")))).Replace("-", "").ToLowerInvariant() } finally { $hash.Dispose() }
$buildId = "portable-$($buildDigest.Substring(0, 12))"
$checkoutId = "portable-$($buildDigest.Substring(12, 16))"

# These are the two path families present in the reference DB: the active
# project root and an older import staging root whose blobs were deduplicated
# into the active project's .taichi-flow store.
$legacyImportName = ".chamoli-reference-e2e-20260828-v4.import-dc1d420722f6446abebb70d77939c334"
$manifest = [ordered]@{
    schema_version = 1
    build_id = $buildId
    portable_root = $OutputRoot
    platform = "windows"
    architecture = "x64"
    source_revision = $sourceRevision
    checkout_id = $checkoutId
    runtime = [ordered]@{ python = $pythonVersion; taichi = "1.7.4"; electron = $electronVersion; electron_executable = "electron.exe"; node_required = $false; dependency_lock = "scripts\portable\portable-runtime.lock.txt" }
    project = [ordered]@{
        name = "Chamoli 90-second compact demo"
        relative_path = $projectRelative
        # Keep the static manifest portable too; the historical source root is
        # retained only in path_relocations for the one-time DB migration.
        source_path = $projectRelative
        description = "Bundled 90-second completed-record demonstration"
    }
    path_relocations = @(
        [ordered]@{ from = $projectSource; to_relative = $projectRelative },
        [ordered]@{ from = (Join-Path (Split-Path -Parent $projectSource) $legacyImportName); to_relative = $projectRelative }
    )
    ports = [ordered]@{ api = 8000 }
    files = @()
    mutable_paths = @(".runtime\portable\state\catalog.sqlite3", "$projectRelative\.taichi-flow\state.sqlite3")
    generated_at = [DateTime]::UtcNow.ToString("o")
}
$manifestPath = Join-Path $OutputRoot "portable-manifest.json"
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "[portable] relocating database paths and checking SQLite integrity"
$relocationOutput = @(& $portablePython (Join-Path $portableScriptRoot "relocate_paths.py") --root $OutputRoot --manifest $manifestPath 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Portable path relocation failed: $($relocationOutput -join [Environment]::NewLine)" }
$relocationLine = $relocationOutput | Where-Object { [string]$_ -like "TAICHI_FLOW_RELOCATION=*" } | Select-Object -Last 1
if ($null -eq $relocationLine) { throw "Portable path relocation did not return a structured report." }
$relocationReport = ([string]$relocationLine).Substring("TAICHI_FLOW_RELOCATION=".Length) | ConvertFrom-Json

$stateDir = Join-Path $OutputRoot ".runtime\portable\state"
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$registerOutput = @(& $portablePython (Join-Path $portableScriptRoot "register_project.py") --root $OutputRoot --state-dir $stateDir --project $projectDestination --name "Chamoli 90-second compact demo" --description "Bundled 90-second completed-record demonstration" 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Portable project catalog initialization failed: $($registerOutput -join [Environment]::NewLine)" }
$registeredProject = ($registerOutput | Select-Object -Last 1 | ConvertFrom-Json)

$keyFiles = @(
    "Start-Taichi-Flow.cmd", "Stop-Taichi-Flow.cmd", "Verify-Taichi-Flow.cmd",
    "scripts\portable\Start-Taichi-Flow-Portable.ps1", "scripts\portable\Stop-Taichi-Flow-Portable.ps1",
    "scripts\portable\Verify-Taichi-Flow-Portable.ps1", "scripts\portable\relocate_paths.py",
    "scripts\portable\portable-runtime.lock.txt",
    "api\app.py", "app\dist\index.html", "app\desktop\main.cjs", ".runtime\portable\python\python.exe",
    ".runtime\portable\electron\electron.exe", ".runtime\portable\electron\Taichi-Flow.exe"
)
$fileRecords = @()
foreach ($relative in $keyFiles) {
    $path = Join-Path $OutputRoot $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Key portable file is missing: $relative" }
    $fileRecords += [ordered]@{ path = $relative; sha256 = (Get-PortableSha256 -Path $path); bytes = (Get-Item -LiteralPath $path).Length }
}
$manifest.files = $fileRecords
$manifest.project.project_id = [string]$registeredProject.project_id
$manifest.project.result_family_count = [int]$relocationReport.project.result_families
$manifest.project.upload_count = [int]$relocationReport.project.path_counts.uploads
Copy-Item -LiteralPath (Join-Path $portableScriptRoot "Start-Taichi-Flow-Portable.ps1") -Destination (Join-Path $OutputRoot "scripts\portable\Start-Taichi-Flow-Portable.ps1") -Force
Copy-Item -LiteralPath (Join-Path $portableScriptRoot "Stop-Taichi-Flow-Portable.ps1") -Destination (Join-Path $OutputRoot "scripts\portable\Stop-Taichi-Flow-Portable.ps1") -Force
Copy-Item -LiteralPath (Join-Path $portableScriptRoot "Verify-Taichi-Flow-Portable.ps1") -Destination (Join-Path $OutputRoot "scripts\portable\Verify-Taichi-Flow-Portable.ps1") -Force
Copy-Item -LiteralPath (Join-Path $portableScriptRoot "relocate_paths.py") -Destination (Join-Path $OutputRoot "scripts\portable\relocate_paths.py") -Force
Copy-Item -LiteralPath (Join-Path $portableScriptRoot "register_project.py") -Destination (Join-Path $OutputRoot "scripts\portable\register_project.py") -Force

$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$report = [ordered]@{
    success = $true
    build_id = $buildId
    output_root = $OutputRoot
    python_probe = ($probeOutput -join " ")
    relocation = $relocationReport
    project = $registeredProject
    generated_at = [DateTime]::UtcNow.ToString("o")
}
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $OutputRoot "portable-build-report.json") -Encoding UTF8
Write-Host "[portable] build complete: $OutputRoot (build=$buildId)"
