# Fortran Toolchain Sandbox

This sandbox contains temporary, auditable tooling for the EDDA original-Fortran `tfail/gindx/fdepth` evidence workflow.

It exists to unblock the `precomputed_unsfin_*` artifact path without polluting production code and without modifying original EDDA case folders.

## What This Sandbox May Contain

- Repeatable probe, install, build, run, and validation scripts under `scripts/`.
- Small patch files under `patches/`.
- Small synthetic fixtures under `fixtures/`.
- Tiny placeholder files such as `.gitkeep`.
- Generated reports under `generated/` during local runs.
- Local logs under `logs/` during local runs.

## What Must Not Be Committed

- Toolchain installers or package caches.
- MSYS2 or oneAPI installations.
- Copied original EDDA cases.
- Instrumented executables.
- Build outputs such as `.exe`, `.obj`, `.mod`, `.pdb`, `.dll`, `.lib`.
- Original EDDA result copies or large raster grids.

The sandbox `.gitignore` ignores `toolchain/`, `work/`, `generated/`, and `logs/` contents by default, while keeping `.gitkeep` placeholders.

## Guardrails

- Never overwrite original `EDDA.exe`.
- Never overwrite original `results/`.
- Never infer `tfail` from `LS_Scar` or `faildph`.
- Never treat `list_z_p_fs` as a timing artifact unless it contains actual per-cell timing rows.
- Do not modify rainfall, Manning, fallback, outflow, DFS formulas, or erosion/deposition coefficients.

## Typical Commands

Set `EDDA_CASE_20A` and `EDDA_CASE_50A` to local original-case directories
before running the build/run examples. The sandbox never assumes a machine-
specific case path.

Run a toolchain probe:

```powershell
powershell -ExecutionPolicy Bypass -File tests\_fortran_toolchain_sandbox\scripts\probe_fortran_toolchain.ps1
```

Probe Intel oneAPI:

```powershell
powershell -ExecutionPolicy Bypass -File tests\_fortran_toolchain_sandbox\scripts\setup_intel_oneapi_probe.ps1
```

Check for MSYS2/gfortran without installing:

```powershell
powershell -ExecutionPolicy Bypass -File tests\_fortran_toolchain_sandbox\scripts\install_msys2_gfortran.ps1
```

Install/update MSYS2 gfortran only when explicitly allowed:

```powershell
powershell -ExecutionPolicy Bypass -File tests\_fortran_toolchain_sandbox\scripts\install_msys2_gfortran.ps1 -Install
```

Build an instrumented copy:

```powershell
powershell -ExecutionPolicy Bypass -File tests\_fortran_toolchain_sandbox\scripts\build_instrumented_edda.ps1 `
  -CaseRoot $env:EDDA_CASE_20A
```

Run instrumented copied cases:

```powershell
powershell -ExecutionPolicy Bypass -File tests\_fortran_toolchain_sandbox\scripts\run_instrumented_original_cases.ps1 `
  -Case20Root $env:EDDA_CASE_20A -Case50Root $env:EDDA_CASE_50A `
  -InstrumentedExePath "tests\_fortran_toolchain_sandbox\work\instrumented_build\EDDA.exe"
```

Validate artifacts:

```powershell
.venv\Scripts\python.exe tests\_fortran_toolchain_sandbox\scripts\validate_precomputed_unsfin_artifacts.py
```
