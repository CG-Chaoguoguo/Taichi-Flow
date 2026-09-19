# FIX3 comparison and source replay tools

Run from the repository root using the project's Python environment.
These tracked tools require NumPy; source replay also uses Taichi and the
tracked solver test helpers. They do not require historical `docs/audit/` files.

## Commands

```powershell
python -m tools.fix3.grid_compare candidate.asc reference.asc --metric erosion_depth
python -m tools.fix3.acceptance candidate_dir reference_dir --end-time-s 900 --output-interval-s 45 --json-out artifacts/fix3/acceptance.json
python -m tools.fix3.replay_source_operator --source path/to/dfs.F90 --output artifacts/fix3/replay --arch cpu --vcvars path/to/vcvars64.bat --setvars path/to/setvars.bat
```

Use `--help` for the complete options. Grid comparison requires matching grid
geometry and NoData masks. Run acceptance checks expected output families and
times; it does not silently resample or replace missing frames. Supply explicit
manifests and evidence classes when evaluating a real reference run.

Source replay requires Windows, an Intel Fortran compiler environment, Visual
Studio build tools, and separately supplied original Fortran source. Compiler
defaults are machine-specific; pass the paths shown above for your installation.
It compares synthetic local source states, not full trajectories, CFL/retry
behavior, or original executable equivalence. Importing it and running the
source-anchor regression test does not invoke a compiler.

## Tests and local output

```powershell
python -m pytest tests/test_fix3_grid_compare.py tests/test_fix3_source_replay.py -q
```

Keep generated grids, reports, parse/metrics caches, compiler output, and replay
inputs under `artifacts/fix3/` (ignored). The tools accept explicit output paths;
they do not enforce this directory. Other local FIX3 run orchestrators, UI
automation, and one-off report scripts are intentionally not distributed.
