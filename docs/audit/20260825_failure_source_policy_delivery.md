# Failure-source policy production-chain delivery log

> 历史交付记录（2026-08-25）。案例路径、运行日志、截图和
> `artifacts/` 目录是本地证据；本文保留结论摘要，但这些原始文件不要求
> 在 clean checkout 中存在。

Date: 2026-08-25 (Asia/Shanghai)

## Delivered

- Kept the solver's physical variants at two values: `precomputed_unsfin_schedule` and `live_doublelayer_in_dfs`.
- Added the separate global policy layer `auto | disabled | precomputed | live`. `disabled` is materialized as `simulate_shallow_landslide=false`; it is not a third solver variant.
- Made reference Auto resolution strict: `fssimul=F` resolves to disabled; complete producer/consumer evidence resolves BJ to precomputed; missing, unknown, or conflicting topology blocks instead of silently selecting live. Direct API Auto retains an explicit compatibility warning only when no reference topology is available.
- Added fixed/free-form Fortran source normalization, structured evidence, template provenance, resolution ID/hash, and the experimental live capability/unlock gates.
- Added the pure `resolve_scenario_compute_snapshot` entry point. Preview, enqueue, scheduler claim, mapper, runtime manifest, registry, and Simulation Run now use the same frozen effective configuration/resolution.
- Added SQLite schema v9 queue/run snapshot columns. Retry reuses the original snapshot; legacy runs remain `legacy_unrecorded`; missing post-upgrade queue snapshots fail closed.
- Kept `triggerslide` independent and left the serial UNSFIN `ts_carry` precompute on CPU. No root search/Richards precompute was moved into CUDA.
- Reused the existing Settings/RunModule component architecture. Auto uses deferred provenance text, RunModule is read-only, and loading/blocked/resolved/legacy states are explicit.

## Verification evidence

- Backend policy/freeze suite: 36 passed.
- Extended parser/mapper/runtime suite: 49 passed, 3 known small-grid physics-step tests deselected because their pre-existing `step_info["accepted"]` assumption is unrelated to this chain.
- TypeScript build: `tsc -b` passed.
- Focused Vitest: 2 files / 3 tests passed.
- Production Vite build passed (one existing large-chunk warning).
- Browser evidence was captured in the local-only `artifacts/audit/20260825-*`
  snapshots for Settings (dark/light/high-contrast, 1366/768), Chamoli
  disabled resolution, complete BJ precomputed resolution, and path-free BJ
  Auto blocked resolution. The browser was left on the final Settings route
  after restoring the original Settings values.
- The local-only API summary `artifacts/audit/20260825-policy-resolution-api-summary.json`
  records Chamoli `resolved/disabled`, BJ_HXL `resolved/precomputed`, and the
  path-free BJ fixture `blocked/failure_source_topology_unknown` without a live
  fallback.

## Scientific boundary

The existing Chamoli CUDA A/B evidence remains the supporting regression record: the disabled branch had no provider directory and matched the audited public grid outputs, with the provider wall-clock segment removed. This delivery does not claim CUDA--Fortran numerical equivalence. BJ production schedule closure still requires a real validated `tfail` crossing and the generated-to-consumed lifecycle evidence.

## Scope boundary

Rainfall, raster/zone editor, prototype design deletion, and other pre-existing worktree changes were not reset or folded into this feature.
