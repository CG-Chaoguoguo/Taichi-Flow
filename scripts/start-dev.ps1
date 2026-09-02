<#
.SYNOPSIS
Start the Taichi-Flow development stack.

.DESCRIPTION
The root entry point delegates every presentation mode to the managed desktop
launcher. With no switch it starts FastAPI, Vite HMR and an independent Electron
development window. Use -Browser for an explicit browser presentation or
-ServicesOnly/-NoBrowser for a headless service session. No mode changes the
reference-compatible computation layer.
#>
[CmdletBinding()]
param(
    [string]$ApiHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$ApiPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$FrontendPort = 3000,
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 90,
    [switch]$Browser,
    [Alias("ServicesOnly")][switch]$NoBrowser,
    [switch]$SkipNpmInstall,
    [switch]$OpenDevTools,
    [switch]$Smoke,
    [string]$SmokeReportPath = "",
    [string]$SmokeScreenshotPath = ""
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$desktopLauncher = Join-Path $repoRoot "scripts\desktop-dev\Start-DesktopDev.ps1"

if ($Browser -and $NoBrowser) {
    throw "-Browser cannot be combined with -ServicesOnly or -NoBrowser. Choose one presentation mode."
}
if ($ApiHost -notin @("127.0.0.1", "localhost", "::1") -or $FrontendHost -notin @("127.0.0.1", "localhost", "::1")) {
    throw "The managed Taichi-Flow launcher only permits loopback -ApiHost and -FrontendHost values."
}
if (-not (Test-Path -LiteralPath $desktopLauncher -PathType Leaf)) {
    throw "Electron desktop launcher is missing: $desktopLauncher"
}

$presentation = if ($Browser) { "browser" } elseif ($NoBrowser) { "services" } else { "electron" }
$desktopArguments = @(
    "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $desktopLauncher,
    "-Mode", "dev", "-Presentation", $presentation,
    "-ApiHost", $ApiHost, "-ApiPort", [string]$ApiPort,
    "-FrontendHost", $FrontendHost, "-FrontendPort", [string]$FrontendPort,
    "-TimeoutSeconds", [string]$TimeoutSeconds
)
if ($SkipNpmInstall) { $desktopArguments += "-SkipNpmInstall" }
if ($OpenDevTools) { $desktopArguments += "-OpenDevTools" }
if ($Smoke) { $desktopArguments += "-Smoke" }
if (-not [string]::IsNullOrWhiteSpace($SmokeReportPath)) { $desktopArguments += @("-SmokeReportPath", $SmokeReportPath) }
if (-not [string]::IsNullOrWhiteSpace($SmokeScreenshotPath)) { $desktopArguments += @("-SmokeScreenshotPath", $SmokeScreenshotPath) }

switch ($presentation) {
    "electron" { Write-Host "[Taichi Flow dev] Default presentation: Electron desktop (Vite HMR)" }
    "browser" { Write-Host "[Taichi Flow dev] Explicit presentation: browser (Vite HMR)" }
    "services" { Write-Host "[Taichi Flow dev] Explicit presentation: services only (no UI)" }
}

& powershell.exe @desktopArguments
exit $LASTEXITCODE
