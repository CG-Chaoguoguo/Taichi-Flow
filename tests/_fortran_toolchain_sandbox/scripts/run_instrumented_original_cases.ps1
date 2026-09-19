param(
    [string]$InstrumentedExePath = "",
    [string]$Case20Root = "",
    [string]$Case50Root = "",
    [string]$SandboxRoot = "",
    [string[]]$Cases = @("20a", "50a"),
    [int]$TimeoutSeconds = 900,
    [string]$RunLabel = ""
)

$ErrorActionPreference = "Continue"

if (-not $SandboxRoot) {
    $SandboxRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $InstrumentedExePath) {
    $InstrumentedExePath = Join-Path $SandboxRoot "work\instrumented_build\EDDA.exe"
}

$LogsDir = Join-Path $SandboxRoot "logs"
$WorkDir = Join-Path $SandboxRoot "work\instrumented_case_runs"
$ArtifactRootName = "original_reference_artifacts"
if ($RunLabel) {
    $safeRunLabel = ($RunLabel -replace '[^A-Za-z0-9_.-]', '_')
    $ArtifactRootName = "original_reference_artifacts_$safeRunLabel"
}
$ArtifactRoot = Join-Path $SandboxRoot "generated\$ArtifactRootName"
New-Item -ItemType Directory -Force -Path $LogsDir, $WorkDir, $ArtifactRoot | Out-Null

$MsysUcrtBin = Join-Path $SandboxRoot "toolchain\msys64\ucrt64\bin"
$MsysMingwBin = Join-Path $SandboxRoot "toolchain\msys64\mingw64\bin"
$OriginalPath = $env:PATH
foreach ($candidatePath in @($MsysUcrtBin, $MsysMingwBin)) {
    if (Test-Path $candidatePath) {
        $env:PATH = "$candidatePath;$env:PATH"
    }
}

$LogPath = Join-Path $LogsDir "run_instrumented_original_cases.log"
"" | Set-Content -Path $LogPath -Encoding UTF8

function Write-RunLog {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
    Write-Output $Message
}

function Copy-Case {
    param([string]$Source, [string]$Destination)
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Run-OneCase {
    param([string]$Name, [string]$SourceRoot)
    $caseWork = Join-Path $WorkDir $Name
    $artifactDir = Join-Path $ArtifactRoot $Name
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null

    if (-not (Test-Path $SourceRoot)) {
        Write-RunLog "BLOCKED ${Name}: source root not found: $SourceRoot"
        return
    }
    if (-not (Test-Path $InstrumentedExePath)) {
        Write-RunLog "BLOCKED ${Name}: instrumented exe not found: $InstrumentedExePath"
        return
    }

    Copy-Case -Source $SourceRoot -Destination $caseWork
    Copy-Item -LiteralPath $InstrumentedExePath -Destination (Join-Path $caseWork "EDDA.exe") -Force
    $precomputedDir = Join-Path $caseWork "original_reference_artifacts"
    foreach ($precomputed in @("precomputed_unsfin_tfail.txt", "precomputed_unsfin_fdepth.txt", "precomputed_unsfin_gindx.txt", "precomputed_unsfin_meta.json")) {
        $sourcePrecomputed = Join-Path $precomputedDir $precomputed
        if (Test-Path $sourcePrecomputed) {
            Copy-Item -LiteralPath $sourcePrecomputed -Destination (Join-Path $caseWork $precomputed) -Force
            Write-RunLog "$Name staged precomputed artifact $precomputed"
        }
    }
    if ($RunLabel -match "restore") {
        $stateSourceDir = Join-Path $SandboxRoot "generated\original_reference_artifacts_unsfin_full_q_manifest_20a\$Name"
        foreach ($stateFile in @("unsfin_state_manifest.json", "unsfin_state_checksums.json", "unsfin_state_gindx.txt", "unsfin_state_tfail.txt", "unsfin_state_fdepth.txt", "unsfin_state_q.bin", "unsfin_state_q_tracked_rows.txt")) {
            $sourceState = Join-Path $stateSourceDir $stateFile
            if (Test-Path $sourceState) {
                Copy-Item -LiteralPath $sourceState -Destination (Join-Path $caseWork $stateFile) -Force
                Write-RunLog "$Name staged restore state artifact $stateFile"
            } else {
                Write-RunLog "$Name missing restore state artifact $stateFile"
            }
        }
    }

    Write-RunLog "Running $Name in copied workdir $caseWork"
    $stdoutPath = Join-Path $LogsDir "run_${Name}_stdout.txt"
    $stderrPath = Join-Path $LogsDir "run_${Name}_stderr.txt"
    if (Test-Path $stdoutPath) { Remove-Item -LiteralPath $stdoutPath -Force }
    if (Test-Path $stderrPath) { Remove-Item -LiteralPath $stderrPath -Force }
    $proc = Start-Process -FilePath (Join-Path $caseWork "EDDA.exe") `
        -WorkingDirectory $caseWork `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
        -PassThru
    $completed = $proc.WaitForExit($TimeoutSeconds * 1000)
    if (-not $completed) {
        Write-RunLog "$Name timeout_after_seconds=$TimeoutSeconds; killing pid=$($proc.Id)"
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        } catch {
            Write-RunLog "$Name failed_to_stop_after_timeout: $($_.Exception.Message)"
        }
        $exitCode = "TIMEOUT"
    } else {
        $exitCode = $proc.ExitCode
    }
    Write-RunLog "$Name exit_code=$exitCode"

    foreach ($file in @(
        "instrumented_progress.log",
        "precomputed_unsfin_gindx.txt",
        "precomputed_unsfin_tfail.txt",
        "precomputed_unsfin_fdepth.txt",
        "precomputed_unsfin_meta.json",
        "original_downstream_internal_600s.txt",
        "original_downstream_internal_600s_meta.json",
        "original_deposition_first_event.txt",
        "original_deposition_first_event_meta.json",
        "original_deposition_positive_event.txt",
        "original_deposition_positive_event_meta.json",
        "original_dfs_minimal_gate_dump.txt",
        "original_dfs_minimal_gate_dump_meta.json",
        "dfs_noop_stub_args.txt",
        "original_erosion_event_probe.csv",
        "original_erosion_event_probe_meta.json",
        "original_erosion_event_probe_progress.txt",
        "original_first_event_tau_components.csv",
        "original_first_event_tau_components_meta.json",
        "original_first_event_tau_components_progress.txt",
        "original_target_35716_erosion_components.csv",
        "original_target_35716_erosion_components_meta.json",
        "original_target_35716_erosion_components_progress.txt",
        "original_target_36762_erosion_components.csv",
        "original_target_36762_erosion_components_meta.json",
        "original_target_36762_erosion_components_progress.txt",
        "original_tracked_scalar_momentum_terms_raw.txt",
        "original_tracked_scalar_momentum_terms_meta.json",
        "original_momentum_assignment_terms_raw.txt",
        "original_momentum_assignment_terms_meta.json",
        "original_assignment_skip_predicate_raw.txt",
        "original_assignment_skip_predicate_meta.json",
        "original_depth_component_ledger_raw.txt",
        "original_depth_face_qq_ledger_raw.txt",
        "unsfin_state_manifest.json",
        "unsfin_state_checksums.json",
        "unsfin_state_gindx.txt",
        "unsfin_state_tfail.txt",
        "unsfin_state_fdepth.txt",
        "unsfin_state_q.bin",
        "unsfin_state_q_tracked_rows.txt",
        "state_restore_manifest_check.txt",
        "restore_allocatable_status_matrix.csv",
        "unsfin_internal_checkpoint_events.csv",
        "unsfin_q_state_manifest.json",
        "unsfin_q_state_checksums.json",
        "unsfin_q_state_tracked_rows.txt",
        "unsfin_failure_scaffold_manifest.json",
        "unsfin_failure_scaffold_checksums.json",
        "unsfin_doublelayer_state_manifest.json",
        "unsfin_doublelayer_state_checksums.json"
    )) {
        $candidate = Join-Path $caseWork $file
        if (Test-Path $candidate) {
            Copy-Item -LiteralPath $candidate -Destination (Join-Path $artifactDir $file) -Force
            Write-RunLog "$Name copied artifact $file"
        } else {
            Write-RunLog "$Name missing artifact $file"
        }
    }
}

if ($Cases -contains "20a") {
    Run-OneCase -Name "20a" -SourceRoot $Case20Root
}
if ($Cases -contains "50a") {
    Run-OneCase -Name "50a" -SourceRoot $Case50Root
}

$env:PATH = $OriginalPath

Write-Output "artifact_root=$ArtifactRoot"
Write-Output "log=$LogPath"
