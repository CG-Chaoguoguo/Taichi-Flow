[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$NodePath,
    [Parameter(Mandatory = $true)][string]$NpmCliPath,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ArgumentsBase64,
    [Parameter(Mandatory = $true)][string]$ExitCodePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$resolvedExitCode = 1

try {
    $json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ArgumentsBase64))
    $npmArguments = @(ConvertFrom-Json $json)
    Set-Location -LiteralPath $WorkingDirectory
    & $NodePath $NpmCliPath @npmArguments
    $resolvedExitCode = if ($null -eq $LASTEXITCODE) { 1 } else { [int]$LASTEXITCODE }
} catch {
    Write-Error $_
    $resolvedExitCode = 1
} finally {
    New-Item -ItemType Directory -Path (Split-Path -Parent $ExitCodePath) -Force | Out-Null
    Set-Content -LiteralPath $ExitCodePath -Value ([string]$resolvedExitCode) -Encoding ASCII
}

exit $resolvedExitCode
