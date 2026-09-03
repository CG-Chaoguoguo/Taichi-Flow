param(
    [string]$SandboxRoot = ""
)

$ErrorActionPreference = "Continue"

if (-not $SandboxRoot) {
    $SandboxRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$LogsDir = Join-Path $SandboxRoot "logs"
$GeneratedDir = Join-Path $SandboxRoot "generated"
New-Item -ItemType Directory -Force -Path $LogsDir, $GeneratedDir | Out-Null

$setvarsCandidates = @(
    "C:\Program Files (x86)\Intel\oneAPI\setvars.bat",
    "C:\Program Files\Intel\oneAPI\setvars.bat"
)
$compilerCandidates = @(
    "C:\Program Files (x86)\Intel\oneAPI\compiler\latest\windows\bin\ifx.exe",
    "C:\Program Files\Intel\oneAPI\compiler\latest\windows\bin\ifx.exe",
    "C:\Program Files (x86)\Intel\oneAPI\compiler\latest\windows\bin\ifort.exe",
    "C:\Program Files\Intel\oneAPI\compiler\latest\windows\bin\ifort.exe"
)

$setvars = $setvarsCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$compilers = @()
foreach ($path in $compilerCandidates) {
    if (Test-Path $path) {
        $compilers += $path
    }
}

$wrapperPath = Join-Path $GeneratedDir "run_oneapi_env.cmd"
$status = "blocked"
$blocker = "Intel Fortran integration/compiler not installed."

if ($setvars -and $compilers.Count -gt 0) {
    $status = "available"
    $blocker = $null
    $wrapper = @(
        "@echo off",
        "call `"$setvars`" intel64",
        "%*"
    )
    $wrapper | Set-Content -Path $wrapperPath -Encoding ASCII
} elseif ($setvars) {
    $status = "setvars_only"
    $blocker = "Intel oneAPI setvars.bat found, but ifx/ifort compiler executable was not found."
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    sandbox_root = $SandboxRoot
    status = $status
    setvars = $setvars
    compilers = $compilers
    wrapper = if (Test-Path $wrapperPath) { $wrapperPath } else { $null }
    blocker = $blocker
}

$jsonPath = Join-Path $LogsDir "intel_oneapi_probe.json"
$mdPath = Join-Path $LogsDir "intel_oneapi_probe.md"
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonPath -Encoding UTF8

$lines = @(
    "# Intel oneAPI Probe",
    "",
    "- status: $status",
    "- setvars: $setvars",
    "- compilers: $($compilers -join ', ')",
    "- wrapper: $($result.wrapper)",
    "- blocker: $blocker"
)
$lines | Set-Content -Path $mdPath -Encoding UTF8

Write-Output "Wrote $jsonPath"
Write-Output "Wrote $mdPath"
if ($blocker) {
    Write-Output $blocker
}
