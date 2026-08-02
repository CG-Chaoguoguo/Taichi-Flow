# EDDA-Taichi Project Context Snapshot

Last updated: 2026-04-12

This document condenses the current project context into one handoff file. It is
intended for GitHub publication, future branch work, and resuming scientific
alignment without rereading every historical report.

## Project Goal

EDDA-Taichi is a Taichi/CUDA migration of the original EDDA debris-flow
simulator. The scientific goal is strict reproduction of original EDDA physics
and solver sequencing, not a simplified GPU approximation.

Core rule:

- preserve original EDDA equation order, direction order, source-term timing,
  dry/wet gates, time stepping, and output semantics;
- use CUDA/Taichi as the execution backend;
- do not simplify formulas or control flow for speed, stability, or code
  neatness unless the same behavior exists in original EDDA.

If scientific fidelity conflicts with convenience or runtime speed, scientific
fidelity wins.

## Important Local Paths

```text
Repository:
C:\Users\Administrator\EDDA-Taichi

Original EDDA Fortran source:
C:\Users\Administrator\Desktop\TaiChi\Reference Software\Edda

Main real reference case:
C:\Users\Administrator\Desktop\EntireBanzigou1005

Reference case config:
C:\Users\Administrator\Desktop\EntireBanzigou1005\edda_in.txt

Reference case log:
C:\Users\Administrator\Desktop\EntireBanzigou1005\EDDALog.txt

Reference case inputs:
C:\Users\Administrator\Desktop\EntireBanzigou1005\data\tutorial

Reference case original EDDA outputs:
C:\Users\Administrator\Desktop\EntireBanzigou1005\results
```

The real reference case is external to the repository and should not be
committed to GitHub.

## Current Repository State

The repository is being prepared for GitHub publication with branch-based
future development.

Recent documentation/readiness work added or updated:

- `README.md`
- `.gitignore`
- `.gitattributes`
- `requirements.txt`
- `environment.yml`
- `setup.py`
- `docs/README.md`
- `docs/current_alignment_status.md`
- `docs/current_development_issues.md`
- `docs/github_workflow.md`
- `PROJECT_REPORTS/README.md`

Local generated files cleaned during GitHub-readiness work:

- `.pytest_cache/`
- project-level `__pycache__/` directories outside `.venv/`
- `tests/output/`
- `tests/comparison/output/`

Kept intentionally:

- `.venv/` as local environment, ignored by Git;
- `.vscode/` as local IDE config, ignored by Git;
- `tests/data/` and `tests/comparison/data/` as small local test inputs,
  currently ignored unless intentionally promoted as fixtures.

## Git Status Caveat

Before committing, separate documentation/readiness changes from solver and
comparison-code changes. There were already non-document changes in the working
state before this context snapshot was created, including:

- `edda/solver/dfs_dynamic_wave.py`
- `tests/comparison/diagnose_late_velocity_faces.py`
- `tests/comparison/trace_late_velocity_steps.py`
- `PROJECT_REPORTS/FIX_LOGS/REAL_CASE_ALIGNMENT_REPORT_2026-03-28.md`
- `PROJECT_REPORTS/FIX_LOGS/REAL_CASE_ALIGNMENT_REPORT_2026-03-28.json`

Do not accidentally mix those with a docs-only GitHub-readiness commit unless
that is intentional.

## Current Scientific Alignment Status

The project has moved past broad architectural mismatch. The real
`EntireBanzigou1005` case is tightly aligned with original EDDA through these
checkpoints:

- `3600s`
- `7200s`
- `10800s`
- `14400s`

At `18000s`, most scalar outputs remain close, but `Flow_velocity_1..8` still
has a late clear-water thin-front branch-topology mismatch.

Stable or substantially aligned items:

- active-domain masking and NoData exclusion;
- 8-direction neighbor mapping consistent with `flodir.f90`;
- explicit Fortran-style fields for `fv`, `qq`, `qqmass`, `fybar`,
  `fhpredi*`, and `frhopredi*`;
- DFS-aligned dynamic-wave production route for the real case;
- rainfall interval handling from `edda_in.txt`;
- output-boundary time-step handling;
- checkpoint and resume-window diagnostics;
- `Deposit_depth` comparison semantics, corrected to positive bed-elevation
  change rather than cumulative deposition bookkeeping;
- most scalar outputs in the real case.

## Latest Real-Case Comparison Snapshot

Mean metrics over `3600 / 7200 / 10800 / 14400 / 18000s` from the latest tracked
report:

| Variable | Mean RMSE | Notes |
|---|---:|---|
| `Deposit_depth` | `0.000000e+00` | Exact under corrected output semantics |
| `Erosion_depth` | `0.000000e+00` | Exact in current comparison |
| `Flow_depth` | `6.229512e-05` | Scalar field closely aligned |
| `Max_flow_depth` | `3.586745e-05` | Closely aligned |
| `Max_flow_velocity` | `4.736169e-04` | Closely aligned except localized late difference |
| `Total_depth` | `6.229512e-05` | Closely aligned |
| `Volumetric_sediment` | `3.642175e-15` | Numerical round-off scale |
| `fs_min` | `8.155583e-05` | Closely aligned |
| `Flow_velocity_1..8` | about `2.05e-02` mean over all five times | Main residual comes from `18000s` |

At `18000s`, representative directional-velocity residuals are:

| Variable | RMSE | Max location | Reference | Current simulation |
|---|---:|---|---:|---:|
| `Flow_velocity_1` | `1.032772e-01` | `(163,278)` | `0.0` | `2.920314` |
| `Flow_velocity_2` | `1.024886e-01` | `(105,149)` | `-1.539` | `0.0` |
| `Flow_velocity_3` | `1.048947e-01` | `(97,194)` | `3.303` | `0.0` |
| `Flow_velocity_4` | `1.025324e-01` | `(85,270)` | `-2.673` | `0.0` |

Interpretation: the remaining mismatch is not a broad scalar failure. It is a
late directional face-activation / branch-selection problem.

## Current Best Root-Cause Understanding

The remaining gap is localized to a late clear-water thin-front feeder network.
The best current interpretation is an accepted-step history / branch-partition
divergence around the dry/wet threshold:

```text
tol = 0.01 m
```

Key traced cells and regions:

- terminal branch cells around `(139,202)`, `(139,203)`, `(140,203)`;
- upstream reservoir/support region around `(137,201)`, `(137,200)`,
  `(136,201)`, `(136,200)`;
- previously traced feeder chain through `(147,204)`, `(148,204)`, `(148,205)`,
  `(149,205)`, and downstream rings.

Current local picture:

- original EDDA keeps `(139,202)` barely active at `18000s`, with support on
  `Flow_velocity_4`;
- the current Taichi/CUDA run loses that southeast support chain by the final
  output;
- nearby cells reroute support through a different active-face topology;
- the mismatch is already seeded before the final output step.

Important exclusions already documented:

- not explained by NoData contamination;
- not explained by 8-direction order or face pairing at the checked staged
  states;
- not explained by rainfall interval averaging;
- not explained by `bcslope.asc` slope-unit mismatch;
- not explained by output-boundary `dt` handling in the normal production path;
- not explained by CUDA evaluating the same late face kernel differently from a
  strict sequential reproduction;
- not explained by late-window erosion, deposition, or failure source terms in
  the traced clear-water region.

## Original EDDA Outputs That Must Remain In Scope

Future comparison and output-format work must include all of these original EDDA
output families:

- `Deposit_depth`
- `Erosion_depth`
- `Flow_depth`
- `Flow_velocity_1..8`
- `fs_min`
- `Max_flow_depth`
- `Max_flow_velocity`
- `Total_depth`
- `Volumetric_sediment`

Do not validate only on `fs` or only on final scalar fields.

## Key Documents

Start here:

- `README.md`
- `docs/README.md`
- `docs/current_alignment_status.md`
- `docs/current_development_issues.md`
- `docs/github_workflow.md`

Scientific reports:

- `PROJECT_REPORTS/MILESTONE_ALIGNMENT_SUMMARY_2026-04-09.md`
- `PROJECT_REPORTS/FIX_LOGS/REAL_CASE_ALIGNMENT_REPORT_2026-03-28.md`
- `PROJECT_REPORTS/FIX_LOGS/EXECUTABLE_HISTORY_EXCLUSIONS_2026-04-10.md`
- `PROJECT_REPORTS/FIX_LOGS/FACE_PAIRING_AND_LATE_WINDOW_EXCLUSIONS_2026-04-10.md`
- `PROJECT_REPORTS/FIX_LOGS/POST_14400_LOCAL_HISTORY_AUDIT_2026-04-10.md`
- `PROJECT_REPORTS/FIX_LOGS/OUTPUT_BOUNDARY_DT_STATE_AUDIT_2026-04-10.md`
- `PROJECT_REPORTS/FIX_LOGS/RESERVOIR_BRANCH_REROUTE_AUDIT_2026-04-10.md`

## Environment Summary

Recommended Python version:

```text
Python 3.11
```

Recommended setup:

```powershell
conda env create -f environment.yml
conda activate edda-taichi
python -m pip install -e .
```

Alternative pip setup:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

CUDA verification:

```powershell
python - <<'PY'
import taichi as ti
ti.init(arch=ti.cuda, default_fp=ti.f64)
print('Taichi CUDA initialized')
PY
```

## Useful Commands

Fast syntax check:

```powershell
python -m py_compile edda\solver\dfs_dynamic_wave.py
```

Core dynamic-wave tests:

```powershell
python -m pytest tests\test_dfs_dynamic_wave.py tests\test_time_integration_consistency.py -q
```

Real-case alignment comparison using existing original EDDA outputs:

```powershell
python -m tests.comparison.run_entire_banzigou_alignment --max-times 5 --live-progress-seconds 300
```

## GitHub Branch Plan

Recommended branches:

- `docs/github-readiness`: documentation, dependency files, ignore rules, and
  repository hygiene only;
- `feature/dfs-velocity-alignment`: production or diagnostic changes for the
  remaining `Flow_velocity_1..8` mismatch;
- `feature/output-format-parity`: EDDA-style output export and comparison
  unification after velocity topology is resolved;
- `test/reference-fixtures`: small fixtures suitable for CI without the private
  full reference case.

Docs-only commit example:

```powershell
git switch -c docs/github-readiness
git add .gitattributes .gitignore README.md docs/README.md docs/current_alignment_status.md docs/current_development_issues.md docs/github_workflow.md docs/context_snapshot_2026-04-12.md PROJECT_REPORTS/README.md requirements.txt environment.yml setup.py
git commit -m "docs: prepare repository for GitHub publication"
```

Before committing, inspect staged files carefully:

```powershell
git status --short
git diff --cached --stat
git diff --cached --name-only
```

## Do Not Commit

- `.venv/`
- `.vscode/`
- `.pytest_cache/`
- `__pycache__/`
- `tests/output/`
- `tests/comparison/output/`
- full `EntireBanzigou1005` data or original EDDA binaries;
- generated checkpoints, `*.npz`, `*.npy`, logs, or bulk raster outputs.

## Next Technical Work

The next scientific task is still to trace the late `Flow_velocity_1..8` branch
mismatch from first principles:

1. keep using existing original EDDA outputs as reference instead of rerunning
   original EDDA from `0s`;
2. use short, output-rich CUDA/Taichi tests first;
3. focus on face-level clear-water flux partitioning in `14400s -> 18000s`;
4. only promote a fix into production if it maps directly to original EDDA
   Fortran semantics;
5. after the directional velocity topology is resolved or bounded, unify output
   format for all original EDDA result families listed above.

## Working Principle For Future Agents

Do not treat numerical closeness as sufficient. Every remaining deviation must
be traced to either:

- a specific original Fortran statement or executable behavior that has not yet
  been reproduced;
- a documented comparison/output semantics issue;
- or a measured residual that remains after all known source-level differences
  have been excluded.

Until then, the project remains in scientific-alignment mode, not final release
mode.
