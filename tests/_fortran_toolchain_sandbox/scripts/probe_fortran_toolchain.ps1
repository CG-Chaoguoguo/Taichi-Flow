param(
    [string]$SandboxRoot = ""
)

$ErrorActionPreference = "Continue"

if (-not $SandboxRoot) {
    $SandboxRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$LogsDir = Join-Path $SandboxRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Get-CommandRecord {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return [ordered]@{
            name = $Name
            on_path = $true
            path = $cmd.Source
            version = if ($cmd.Version) { $cmd.Version.ToString() } else { "" }
        }
    }
    return [ordered]@{
        name = $Name
        on_path = $false
        path = $null
        version = ""
    }
}

function Get-ExistingPathRecords {
    param([string[]]$Paths)
    $records = @()
    foreach ($path in $Paths) {
        $records += [ordered]@{
            path = $path
            exists = Test-Path $path
        }
    }
    return $records
}

$toolNames = @(
    "ifort", "ifx", "gfortran", "flang", "newflang",
    "devenv", "msbuild", "nmake", "cmake", "cl"
)
$tools = @()
foreach ($tool in $toolNames) {
    $tools += Get-CommandRecord $tool
}

$vswhereCandidates = @(
    "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
    "C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe"
)
$vswhereRecords = Get-ExistingPathRecords $vswhereCandidates
$vsInstances = @()
foreach ($candidate in $vswhereCandidates) {
    if (Test-Path $candidate) {
        try {
            $raw = & $candidate -all -products * -format json
            if ($raw) {
                $parsed = $raw | ConvertFrom-Json
                foreach ($instance in @($parsed)) {
                    $vsInstances += [ordered]@{
                        displayName = $instance.displayName
                        installationPath = $instance.installationPath
                        installationVersion = $instance.installationVersion
                        productId = $instance.productId
                        isComplete = $instance.isComplete
                        isLaunchable = $instance.isLaunchable
                    }
                }
            }
        } catch {
            $vsInstances += [ordered]@{
                error = $_.Exception.Message
                vswhere = $candidate
            }
        }
    }
}

$knownToolPaths = [ordered]@{
    msbuild = @(
        "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\amd64\MSBuild.exe",
        "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
    )
    nmake = @(
        "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\nmake.exe"
    )
    cmake = @(
        "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
    )
}

$knownPathRecords = [ordered]@{}
foreach ($key in $knownToolPaths.Keys) {
    $knownPathRecords[$key] = Get-ExistingPathRecords $knownToolPaths[$key]
}

$oneApiPaths = @(
    "C:\Program Files (x86)\Intel\oneAPI\setvars.bat",
    "C:\Program Files\Intel\oneAPI\setvars.bat",
    "C:\Program Files (x86)\Intel\oneAPI\compiler\latest\windows\bin\ifx.exe",
    "C:\Program Files\Intel\oneAPI\compiler\latest\windows\bin\ifx.exe",
    "C:\Program Files (x86)\Intel\oneAPI\compiler\latest\windows\bin\ifort.exe",
    "C:\Program Files\Intel\oneAPI\compiler\latest\windows\bin\ifort.exe"
)
$msys2Paths = @(
    (Join-Path $SandboxRoot "toolchain\msys64\mingw64\bin\gfortran.exe"),
    (Join-Path $SandboxRoot "toolchain\msys64\ucrt64\bin\gfortran.exe"),
    (Join-Path $SandboxRoot "toolchain\msys64\mingw64\bin\mingw32-make.exe"),
    (Join-Path $SandboxRoot "toolchain\msys64\usr\bin\bash.exe"),
    (Join-Path $SandboxRoot "toolchain\msys64\usr\bin\pacman.exe"),
    "C:\msys64\mingw64\bin\gfortran.exe",
    "C:\msys64\ucrt64\bin\gfortran.exe",
    "C:\msys64\usr\bin\bash.exe",
    "C:\msys64\usr\bin\pacman.exe"
)

$result = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    sandbox_root = $SandboxRoot
    tools_on_path = $tools
    vswhere = $vswhereRecords
    visual_studio_instances = $vsInstances
    known_tool_paths = $knownPathRecords
    intel_oneapi_paths = Get-ExistingPathRecords $oneApiPaths
    msys2_paths = Get-ExistingPathRecords $msys2Paths
}

$jsonPath = Join-Path $LogsDir "fortran_toolchain_probe.json"
$mdPath = Join-Path $LogsDir "fortran_toolchain_probe.md"
$result | ConvertTo-Json -Depth 12 | Set-Content -Path $jsonPath -Encoding UTF8

$lines = @()
$lines += "# Fortran Toolchain Probe"
$lines += ""
$lines += "- generated_at: $($result.generated_at)"
$lines += "- sandbox_root: `$SandboxRoot`"
$lines += ""
$lines += "## PATH Tools"
$lines += ""
$lines += "| tool | on_path | path |"
$lines += "| --- | --- | --- |"
foreach ($tool in $tools) {
    $lines += "| $($tool.name) | $($tool.on_path) | $($tool.path) |"
}
$lines += ""
$lines += "## Visual Studio Instances"
$lines += ""
if ($vsInstances.Count -eq 0) {
    $lines += "No Visual Studio instances found by vswhere."
} else {
    $lines += "| displayName | version | path |"
    $lines += "| --- | --- | --- |"
    foreach ($instance in $vsInstances) {
        $lines += "| $($instance.displayName) | $($instance.installationVersion) | $($instance.installationPath) |"
    }
}
$lines += ""
$lines += "## Intel oneAPI Paths"
$lines += ""
$lines += "| path | exists |"
$lines += "| --- | --- |"
foreach ($record in $result.intel_oneapi_paths) {
    $lines += "| $($record.path) | $($record.exists) |"
}
$lines += ""
$lines += "## MSYS2 Paths"
$lines += ""
$lines += "| path | exists |"
$lines += "| --- | --- |"
foreach ($record in $result.msys2_paths) {
    $lines += "| $($record.path) | $($record.exists) |"
}
$lines | Set-Content -Path $mdPath -Encoding UTF8

Write-Output "Wrote $jsonPath"
Write-Output "Wrote $mdPath"
