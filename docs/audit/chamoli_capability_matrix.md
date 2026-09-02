# Chamoli EDDA vs Taichi-Flow capability matrix

Generated from live parser + `EDDA_SWITCH_REGISTRY` 1.0.0. Machine-readable copy: `chamoli_capability_matrix.json`.

Oracle policy: rerun the matching 2021-03-01 `edda.exe` with a real console (Intel Fortran redirected I/O fails at `edda_in.txt` line 101 on `results\`). Do not use `Debug\EDDA.exe` (2026-07-10) or stdout-redirected launches. Do not treat the 00:56 init-only log as a numerical oracle.

## What this case actually runs

Chamoli `edda_in.txt` process flags:

| Fortran | Value | Taichi status | Frontend |
|---|---|---|---|
| rainsimul | F | production_consumed | editable |
| infilsimul | F | production_consumed | editable |
| inflowsimul | T | partial | read_only |
| outflowsimul | T | production_consumed | editable |
| fssimul | F | production_consumed (auto → disabled; native UNSFIN provider skipped) | read_only |
| debrissimul | T | partial (DFS on; WFS fail-closed) | read_only |
| erosionsimul | T | production_consumed | editable |
| sepdepositionsimul | T | production_consumed | editable |
| dwsimul | F | partial | read_only |
| barriersimul | F | unsupported | read_only |
| buildingsimul | F | parsed_only **extension flag** (not a 46th registry switch) | read_only |

Grid: 748×715 / 41069 cells. `simul=14400s`, `tout=45s`.

## Variant contract (Chamoli ≠ BJ_HXL)

- Sediment line is **six values**: `d50=0.035`, `cvstar=0.6`, `cvglacier=0.3`, `cvlandslide=0.55`, `coedepo=0.001`, `cs=0.7`. The old 4-value parser would have assigned `coedepo=0.3` and `cs=0.55`.
- Rheology 8th value is **debrisflowmanning=0.070**, not BJ `shallown`. Solver Manning-bar variant is `debrisflowmanning_cvtol`.
- Face-flux averaging is auto-detected as **`arithmetic_mean_chamoli`** (both-thin gate + area-mean `cvbar` without depth + arithmetic `frhobar`). BJ stays **`both_thin_weighted`**.
- Dry-face predicted velocity is auto-detected as **`zero_dry_face_chamoli`** (`fvpredi=0` when the upstream cell is thinner than `tol`, Chamoli `dfs.F90:736-737`). BJ stays **`keep_velocity_bj`**.
- Artificial viscosity is auto-detected as **`velocity_ratio_chamoli`** (`0.02*|Δv|/(|v_nq|+|v_i|+1)`, diagonal `/√2`). BJ stays **`depth_ratio_bj`**.
- Editable via Settings → 计算与数值 → 数值变种: `hydrology.dfs_face_flux_variant` / `dfs_manningbar_variant` / `dfs_dry_face_velocity_variant` / `dfs_artivis_variant` / `dfs_absubar_variant` (not 45 EDDA switches). Defaults are sparse Auto (key absent).
- Independent Settings key `hydrology.dfs_failure_source_policy` ∈ `{auto, disabled, precomputed, live}`. Auto: `fssimul=F` → `disabled` (Chamoli); `fssimul=T` + DFS tfail staging → `precomputed` (BJ). Live requires `experimental.enable_live_doublelayer_in_dfs`. Do not add a third solver enum.
- `triggerslidefil` (`Data\tutorial\landslide.asc`) is always read and injected once in `dfs.F90` when `slide1==1 .and. tnow>0`, independent of `fssimul`.
- Chamoli Fortran has **no** `maxsoliddepthsave` prompt; parser stores `save_max_solid_depth=null`, which disables that writer (`bool(None)` is false).
- Present rasters: dem, slope, zones, glacier (`zfil`, `ltstar=-1`), landslide (`triggerslide`). Declared but missing: manning, directions, depthwt, rizero, road/catchment/mouthpoint, flexible/rigid, rifil (unused because `rainsimul=F` and `cri>=0`).

## 45-switch counts

- Registry stays at **exactly 45**.
- `production_consumed`: 16
- Chamoli-null registry key: `save_max_solid_depth` only
- CUDA production path: Taichi kernels, profile `cuda_production_default`. CPU对照 is the same kernels on `ti.cpu`, not a separate Fortran rewrite.

## Frontend exposure (Inspector / ParameterModule)

- Binding fields now include 触发滑坡 / 入流过程 / 出流边界.
- Editable catalog adds `rheology.debrisflowmanning` and `rheology.cvlandslide`; `rheology.cvglacier` is read-only (Chamoli Fortran comments out `rhoero=cvglacier`; erosion density uses zone `cvero`).
- Editable enum dropdowns (Settings 数值变种): `hydrology.dfs_face_flux_variant`, `hydrology.dfs_manningbar_variant`, `hydrology.dfs_dry_face_velocity_variant`, `hydrology.dfs_artivis_variant`, `hydrology.dfs_absubar_variant`. Hidden from ParameterModule. Read-only boundary display: `boundary_conditions.mode/default_type/include_nodata`.
- Inspector `spatial_zones.zones` is an editable **ZoneSoilEditor** card (not a 5-column read-only preview). Chamoli 4 zones: top `cvero` 0.6/0.3/0.4/0.55; bottom `K_sat` **2.0e-7** (zone 1) vs **9e-7** (zones 2–4). Multi-zone global `soil.c/phi/gamma_s`, `hydrology.K_sat`, `erosion.tau_c/ctao/k_erosion` render as 只读.
- `buildingsimul` is shown from `audit.extension_flags`, not added to the 45-switch registry.
- Workbench preflight: parser-absent `save_max_solid_depth=null` is served as `false` (writer off). Stored `chamoli_ui_case` still flags leftover rainfall periods vs `t_end` even with `rainsimul=F` (queue blocked). ZoneSoilEditor edit → save enable → reset was verified in the browser.

## Core semantic fixes (2026-08-20)

| Gap | Fortran | Taichi fix | BJ guard |
|---|---|---|---|
| Zone `cvero` → `rhoero` | `dfs.F90:444` `rhoero=cvero(zo)` | parse top vals[17]; `cvero_field`; fallback `cvstar` | BJ zone tops omit column → sentinel `-1` |
| glacier → erodible | `ltstar<0` → `inierodithick=ltstar` | `zfil` loads `ltstar_field` + `erodible_thickness` | BJ scalar `ltstar=3` unchanged |
| MaxFF classify | previous `cv` vs new `fhpredi2` | `_commit_step` captures `prev_cv` before Cv overwrite | gated to `debrisflowmanning_cvtol` |
| Face-flux averages | Chamoli area-mean `cvbar` + arithmetic `frhobar` | `arithmetic_mean_chamoli` kernel branch + auto-detect | BJ `both_thin_weighted` unchanged |
| Boundary / outflow ledger | Fortran `outflow(i)` sidecar only; volume terms omit outflow cells | audit: strict DFS skips generic edge clear; `_accumulate_volume_balance` already excludes outflow | shared ledger |
| Zone `ltstar` default when `ltstar_raw<0` | Fortran `ltstar=0` then `zfil`; `inierodithick<0 → 0` | zone col 24 default **0** (was fake 3.0); zfil NODATA → **0** not median | BJ scalar `ltstar=3` unchanged |

## Per-zone double-layer soil (2026-08-21)

Fortran stores top/bottom as `(nzon)` arrays indexed by `zo(i)`. Taichi rasterizes consumed params (`ct/phit/phibt/uwst/kst/ksb/thsat*/thresi*/alphat/alphab/kero/ctao/cvero`) into per-cell fields; Richards/FS kernels read those fields. Unused Fortran reads (`cb/phibb/uwsb/porosity/diffusivity`) stay unwired. `ltstar/lbstar` remain cell-level (glacier.asc / scalar), not zone-table columns.

Config/UI gaps closed this round:

- Scenario patch channel `spatial_zones.zones` (`{zone_id: {field: value}}`) deep-merges into `parsed.zones[id].top/.bottom`; preflight rejects unknown zone_id, non-numeric, `K_sat<=0`, `theta_sat<=theta_res`.
- Catalog: `spatial_zones.zones` is editable structured; multi-zone global soil/erosion scalars are UI-locked as 只读.
- Tests: `tests/test_zone_double_layer_independence.py` (Chamoli 4-zone ksb, patch zone 2 only, zfil NODATA=0, catalog, preflight).

## Dry-face + artivis variants (2026-08-21)

Two BJ≠Chamoli wavefront-front variants, both previously implemented only on the BJ side:

| Gap | Fortran | Taichi | BJ guard |
|---|---|---|---|
| Dry-face velocity zero | Chamoli `dfs.F90:736-737` zeros `fvpredi` if upstream `h<=tol` | `zero_dry_face_chamoli` after `fvpred=dv+fv`, before sign-flip | `keep_velocity_bj` |
| Artificial viscosity weight | Chamoli velocity ratio + diagonal `/√2` | `velocity_ratio_chamoli` | `depth_ratio_bj` (`0.02*|Δh|/(h_i+h_nq)`) |

Settings 数值变种 now has five dropdowns. Live parse of Chamoli `dfs.F90` auto-detects the Chamoli pair plus `signed_mean_chamoli`; BJ CUDA t=2 guard stays `keep_velocity_bj` / `depth_ratio_bj` / `both_thin_weighted` / `exponential_cv` / `max_component_bj`. Stored `chamoli_ui_case` was imported before these keys existed, so its workbench effective values still fall back to global BJ Settings defaults until re-imported.

### t=180 short window (`artifacts/chamoli_cuda_t180_wavefront/`, 2146 s)

| t (s) | Flow_depth max/RMSE/wet (this) | prior t=900_zones | note |
|---|---|---|---|
| 45 | **5.47 / 0.096 / 2023** | 28.82 / 0.48 / 2026 | early peak closed; Taichi-only wet → 0 |
| 90 | 8.93 / 0.191 / 3266 | 8.81 / 0.27 / 3278 | RMSE better; max-abs similar |
| 135 | **27.02 / 0.419 / 3941** | 35.60 / 0.63 / 3952 | improved |
| 180 | 39.45 / 0.604 / 4562 | 39.36 / 0.68 / 4572 | peak cell (576,594): Fortran 51.7 vs Taichi 12.3 (lag, not overshoot) |

MaxFF no longer grows (0.050 vs prior 0.051→0.275). Residual sign flipped from Taichi-ahead to Taichi-behind (Fortran-only wet 24→88). Timebox hunt: inflow staging already matches `dfs.F90:253-301`; `use_fortran_absubar_velocity_state` already true; no additional discrete Fortran signature wired.

### CUDA t=900 after wavefront variants (`artifacts/chamoli_cuda_t900_wavefront/`)

Production window CUDA `t_end=900` (20 frames). Elapsed **4106 s**. `missing_count=0`. Variants: `zero_dry_face_chamoli` + `velocity_ratio_chamoli`. **Do not claim numerical parity.**

| t (s) | Flow_depth | SFdepth | MaxFFdepth | pass |
|---|---|---|---|---|
| 45 | 5.47 / 0.096 / 2023 | 5.47 | 0.050 | 4 |
| 90 | 8.93 / 0.191 / 3266 | 8.93 | 0.050 | 4 |
| 135 | 27.02 / 0.419 / 3941 | 27.02 | 0.050 | 2 |
| 180 | 39.45 / 0.604 / 4562 | 39.45 | 0.050 | 2 |
| 270 | 80.89 / 0.982 / 5620 | 80.89 | 0.069 | 2 |
| 315 | **86.02** / 1.169 / 6066 | 86.02 | 0.064 | 2 |
| 450 | 68.30 / 1.281 / 6947 | 68.30 | 0.109 | 2 |
| 630 | 46.90 / 1.018 / 7730 | 46.90 | 0.200 | 2 |
| 765 | 45.31 / 1.043 / 8250 | 45.31 | 0.208 | 2 |
| 900 | **37.21 / 0.889 / 8811** | **43.21** | **0.144** | 2 |

t=900 Flow_depth improved 51.05/3.06 → 37.21/0.889; SF 68.02 → 43.21; MaxFF 0.672 → 0.144. Peak max-abs remains ~86 m at t=315 (was 85.87). LS_Scar / faildph pass all frames.

### t=900 all families (wavefront run)

| Family | status | max abs | RMSE | wet |
|---|---|---|---|---|
| Flow_depth | residual | 37.21 | 0.889 | 8811 |
| Flow_velocity | residual | 29.78 | 1.674 | 6203 |
| Max_flow_depth | residual | 39.71 | 1.049 | 8811 |
| Max_flow_velocity | residual | 17.83 | 0.634 | 8826 |
| Erosion_depth | residual | 7.77 | 0.568 | 7692 |
| Deposit_depth | residual | 10.67 | 0.737 | 5323 |
| Total_depth | residual | 37.29 | 0.965 | 8811 |
| Cv | residual | 0.594 | 0.086 | 8797 |
| LS_Scar | pass | 0 | 0 | — |
| faildph | pass | 0 | 0 | — |
| SFdepth | residual | 43.21 | 2.567 | 8366 |
| DFdepth | residual | 36.87 | 2.174 | 3860 |
| FFdepth | residual | 0.150 | 0.003 | 242 |
| MaxSFdepth | residual | 39.71 | 1.049 | 8532 |
| MaxDFdepth | residual | 44.03 | 3.270 | 3938 |
| MaxFFdepth | residual | 0.144 | 0.003 | 8811 |

## CUDA t=900 full-family vs live Fortran oracle (`artifacts/chamoli_cuda_t900_zones/`)

Production window: `docs/audit/_run_chamoli_window.py` CUDA `t_end=900` (20 frames at `tout=45`). Elapsed **2057.5 s**. All 16 families present every frame (`missing_count=0`). **Do not claim numerical parity.** Summary JSON: `artifacts/chamoli_cuda_t900_zones/frame_diff_summary.json`. BJ short guard: `artifacts/bj_cpu_t2_faceflux_guard/` status=complete, 14.1 s, `both_thin_weighted` / `exponential_cv`.

t=45 / t=90 Flow_depth and MaxFF match the prior face-flux window exactly (28.817 / 8.813 and 0.051 / 0.173). The zone/`ltstar` NODATA=0 change did not move those early frames.

LS_Scar / faildph stay **pass** on all 20 frames (`fssimul=F`). DF / MaxDF pass at 45 s and 90 s, then residual as the debris field grows.

### 20-frame focus (max abs / RMSE / wet)

| t (s) | Flow_depth | SFdepth | MaxFFdepth | pass |
|---|---|---|---|---|
| 45 | 28.82 / 0.48 / 2026 | 28.82 / 0.48 / 1992 | 0.051 / 0.002 / 2024 | 4 |
| 90 | 8.81 / 0.27 / 3278 | 8.81 / 0.27 / 3227 | 0.173 / 0.002 / 3274 | 4 |
| 135 | 35.60 / 0.63 / 3952 | 35.60 / 0.63 / 3878 | 0.272 / 0.002 / 3949 | 2 |
| 180 | 39.36 / 0.68 / 4572 | 39.36 / 0.68 / 4451 | 0.275 / 0.002 / 4570 | 2 |
| 270 | 78.32 / 1.13 / 5632 | 78.32 / 1.13 / 5419 | 0.193 / 0.003 / 5627 | 2 |
| 315 | **85.87** / 1.39 / 6074 | 85.87 / 1.39 / 5810 | 0.202 / 0.003 / 6070 | 2 |
| 450 | 68.30 / 1.51 / 6949 | 68.30 / 1.51 / 6352 | 0.461 / 0.005 / 6946 | 2 |
| 630 | 48.74 / 1.94 / 7727 | 52.33 / 2.40 / 6676 | 0.385 / 0.005 / 7724 | 2 |
| 765 | 53.91 / 2.64 / 8251 | 81.33 / 3.44 / 6981 | 0.429 / 0.006 / 8249 | 2 |
| 900 | 51.05 / 3.06 / 8813 | **68.02** / 4.54 / 7333 | 0.672 / 0.007 / 8811 | 2 |

Peak Flow_depth max-abs in this window is **85.87 m at t=315 s**. MaxFF stays sub-metre (0.67 m at t=900).

### t=900 all families

| Family | status | max abs | RMSE | wet |
|---|---|---|---|---|
| Flow_depth | residual | 51.05 | 3.055 | 8813 |
| Flow_velocity | residual | 39.24 | 2.221 | 7006 |
| Max_flow_depth | residual | 51.05 | 2.862 | 8814 |
| Max_flow_velocity | residual | 20.40 | 1.437 | 9709 |
| Erosion_depth | residual | 7.84 | 0.564 | 7718 |
| Deposit_depth | residual | 12.29 | 0.764 | 5329 |
| Total_depth | residual | 51.95 | 2.856 | 8814 |
| Cv | residual | 0.594 | 0.152 | 8798 |
| LS_Scar | pass | 0 | 0 | — |
| faildph | pass | 0 | 0 | — |
| SFdepth | residual | 68.02 | 4.542 | 7333 |
| DFdepth | residual | 36.87 | 2.174 | 3861 |
| FFdepth | residual | 0.672 | 0.007 | 247 |
| MaxSFdepth | residual | 51.05 | 2.862 | 8527 |
| MaxDFdepth | residual | 44.03 | 3.270 | 3942 |
| MaxFFdepth | residual | 0.672 | 0.007 | 8811 |

## CUDA face-flux variant vs live Fortran oracle (`artifacts/chamoli_cuda_t90_faceflux/`)

Production window: `docs/audit/_run_chamoli_window.py` CUDA `t_end=90` (~1276 s) with auto-detected `arithmetic_mean_chamoli`. Diffs at **45 s and 90 s**. **Do not claim numerical parity.** BJ short guard: `artifacts/bj_cpu_t2_faceflux_guard/` keeps `both_thin_weighted` / `exponential_cv`.

### t=45 s (face-flux) vs prior fix (`chamoli_cuda_t90_fix`)

| Family | face-flux max abs | prior max abs | face-flux RMSE | prior RMSE |
|---|---|---|---|---|
| Flow_depth | **28.82** | 94.52 | **0.48** | 5.24 |
| MaxFFdepth | **0.051** | 2.18 | — | 0.045 |

Wet cells (Flow_depth): 2026 (was 2663).

### t=90 s (face-flux) vs prior fix

| Family | face-flux max abs | prior max abs | face-flux RMSE | prior RMSE |
|---|---|---|---|---|
| Flow_depth | **8.81** | 100.83 | **0.27** | 5.30 |
| Max_flow_depth | 17.90 | 107.23 | 0.41 | 6.85 |
| MaxFFdepth | **0.173** | 2.18 | 0.002 | 0.045 |
| LS_Scar / faildph / DF / MaxDF | pass | pass | 0 | 0 |

## Wavefront diagnosis (prior fix, kept)

Evidence: `artifacts/chamoli_cuda_t90_fix/wavefront_diag.json`.

1. **Erodible/cvero effect**: glacier on Taichi-only wet cells is 10–50 m (median 50), so glacier wiring is live; Flow_depth footprint still close to pre-fix → not solely a missing-thickness issue.
2. **MaxFF window**: prev_cv classify closed the 180.9 m MaxFF gap at the probe cell.
3. **Face-flux averaging**: Chamoli arithmetic `cvbar`/`frhobar` (this round) materially reduced Flow_depth residual; remaining mismatch is not claimed as parity.

## Pre-fix CUDA t=45s baseline (kept for comparison)

Production window runner: `docs/audit/_run_chamoli_window.py` → `artifacts/chamoli_cuda_t45/`. Elapsed 1082 s. All **16** writer families present. MaxFFdepth max abs was **180.9**. CPU对照 (`artifacts/chamoli_cpu_t45/`) matched CUDA within ~0.010 m Flow_depth.

## Absubar velocity-modulus variant (2026-08-22)

Chamoli `dfs.F90:209-212` builds a signed Cartesian `absubar` from raw `fv` with literal `0.707` diagonals. The previous Taichi path used BJ `max(vorth,vcomp)` on `0.5*fv`, which starved `sfmanning ∝ absubar²` and almost eliminated erosion.

| Gap | Fortran | Taichi | BJ guard |
|---|---|---|---|
| Source-rate speed modulus | signed `vx,vy` from raw `fv`, `0.707` diagonals | `signed_mean_chamoli` | `max_component_bj` on `0.5*fv` |

### CUDA t=315 (`artifacts/chamoli_cuda_t315_absubar/`, 1577 s)

`live_arch=cuda`, `dfs_absubar_variant=signed_mean_chamoli`. dt probe: 6874 accepted / 1635 rejected (CFL 641, depth_change 994). **Do not claim numerical parity.**

| t (s) | Flow_depth max/RMSE (this / wavefront) | erosion volume ratio vs Fortran |
|---|---|---|
| 45 | **0.076 / 0.002** vs 5.47 / 0.096 | **1.001** (was 0.002) |
| 315 | **20.37 / 0.421** vs 86.02 / 1.169 | 1.256 (was 0.028) |

### CUDA t=900 (`artifacts/chamoli_cuda_t900_absubar/`, 2256 s)

20 frames, `missing_count=0`, pass=2 (LS_Scar / faildph). Erosion volume ratio grows from 1.001 at t=45 to **1.722 at t=900**; deposit stays ~1.04. Flow_depth t=900 **35.02 / 0.821 / 8920** (wavefront 37.21 / 0.889 / 8811). Peak family max-abs is MaxDFdepth 52.65 (wavefront ALL 44.03 was MaxDF). Mean accepted dt 0.062 s (Fortran EDDALog scaled ~0.377 s).

| Family | status | max abs | RMSE | wet |
|---|---|---|---|---|
| Flow_depth | residual | 35.02 | 0.821 | 8920 |
| Flow_velocity | residual | 24.06 | 1.630 | 6451 |
| Max_flow_depth | residual | 35.30 | 0.843 | 8920 |
| Erosion_depth | residual | 6.22 | 0.424 | 7803 |
| Deposit_depth | residual | 5.67 | 0.249 | 5352 |
| SFdepth | residual | 47.62 | 2.162 | 4946 |
| DFdepth | residual | 47.79 | 2.211 | 4527 |
| MaxDFdepth | residual | 52.65 | 3.102 | 4569 |
| MaxFFdepth | residual | 0.155 | 0.002 | 8887 |
| LS_Scar / faildph | pass | 0 | 0 | — |

## Historical failure-source four-state policy (2026-08-23; superseded)

Orthogonal concepts stay three: `edda.run_controls.simulate_shallow_landslide` (`fssimul`), topology `hydrology.dfs_failure_source_variant` (`precomputed_unsfin_schedule` | `live_doublelayer_in_dfs`), and independent `triggerslide`. Registry remains **45**.

Fortran evidence on the live Chamoli tree:

- Main `call unsfin` is present but **not executed** when `fssimul=F`.
- DFS stages `tempfsh/tempfsrho` only across precomputed `tfail`; live `call doublelayer(...tempfsh...)` is commented. `auto` therefore must not pick live.
- `triggerslide` remains a one-shot DFS inject.

CUDA t=45 A/B (same inputs/env, `requested_arch=cuda`, `live_arch=cuda`, no CPU fallback):

| Run | Path | elapsed_s | provider dir | 16 Taichi ASCII rasters vs A |
|---|---|---|---|---|
| A (with provider) | `artifacts/chamoli_cuda_t45_policy_A_baseline/` | 1036.98 | present | — |
| B (policy skip) | `artifacts/chamoli_cuda_t45_policy_B_skip/` | 194.96 | **absent** | **identical** (`max_abs=0`, `n_diff=0`) |

Provider wall-clock saved **842.0 s**. B `compute_policy_resolution.effective.mode=disabled`, `skip_reason=control_off`. Flow_depth vs Fortran remains ~0.076 m; **do not claim CUDA–Fortran parity**. UNSFIN `ts_carry` cell loop stays serial CPU; it is not CUDA-migrated.

**BJ production schedule closure blocked.** Isolated path-free BJ import (`policy_accept_bj_20260823`) has `fssimul=true` but no bundled Fortran topology evidence, so Auto falls back to `live` with a warning. Existing BJ t=2 remains five-variant smoke only.

Browser evidence (not `chamoli_ui_case`): `docs/audit/2026-08-23_*.png`. Settings six Auto fields, live lock/unlock/anti-lock, Chamoli RunModule `自动 → 关闭浅层失稳；triggerslide 独立有效`, BJ RunModule `自动 → 实时双层（Taichi 实验）`.

## Production failure-source policy (2026-08-25)

The physical solver still has only two variants: `precomputed_unsfin_schedule` and
`live_doublelayer_in_dfs`. The user-facing policy is a separate four-state sparse
override (`auto | disabled | precomputed | live`); `disabled` is represented by
`edda.run_controls.simulate_shallow_landslide=false`, never by a third solver
enum. `triggerslide` remains an independent one-shot DFS injection.

Auto is strict for reference imports:

| evidence | Auto result |
|---|---|
| `fssimul=F` | `resolved / disabled`; UNSFIN is skipped and `triggerslide` is unchanged |
| `fssimul=T` + active `call unsfin`, `tfail` crossing, `tempfsh` and `tempfsrho` staging, no live call | `resolved / precomputed` |
| `fssimul=T` + active live `call doublelayer` | `resolved / live` only when the experimental unlock and runtime capability are present |
| missing/unknown/conflicting producer/consumer topology | `blocked / failure_source_topology_unknown` (never a silent live fallback) |

The detector normalizes fixed-form comments/continuations and returns structured
evidence. It does not infer a mode from a project name, template allowlist, or
output raster. Explicit global overrides may select disabled or precomputed for an
unknown import; live remains locked until the experiment is explicitly unlocked.
Direct path-free API payloads retain a documented compatibility warning when no
reference topology is supplied; this exception does not relax strict workbench or
reference-import runs.

Preview, queue, scheduler, Simulation Run, mapper, registry and runtime manifest
share one resolution payload and identity hash. Queue schema v9 stores the frozen
`effective_config_json` and `compute_policy_resolution_json`; retry reuses those
columns and does not reread Settings. Historical runs are
`legacy_unrecorded`, not backfilled from current Settings. Registry meanings stay
orthogonal: `selected_source` is the physical source, while `schedule_provider`
records skipped/native/uploaded/none lifecycle.

Current reference evidence confirms Chamoli `fssimul=F` and BJ_HXL complete template
`fssimul=T` + recognized precomputed topology. A path-free BJ fixture without that
provenance is intentionally blocked. The 2026-08-23 browser captures showing BJ
Auto → live are retained as historical evidence only and are superseded by the
timestamped 2026-08-25 artifacts under `artifacts/audit/`.

The existing Chamoli CUDA A/B result remains valid: provider skip saved 842.0 s
with identical public rasters (`max_abs=0`, `n_diff=0`); it does not claim
CUDA–Fortran equivalence. UNSFIN `ts_carry` stays a serial CPU precompute and is
not parallelized or moved into CUDA.

## Still open

- Chamoli CUDA/Fortran residual remains. After `signed_mean_chamoli`, early erosion matches Fortran (~1.00 at t=45) but over-erodes later (1.72 at t=900). Flow_depth peak lag at t=315 dropped 86 m → 20 m. Inflow hydrograph remains `partial`.
- `buildingsimul` ARF/WRF runtime (`dfs.F90:58`).
- WFS and UNSFIN **active** BJ production schedule remain fail-closed until a validated ledger exists (**BJ production schedule closure blocked**). Chamoli off-branch LS_Scar/faildph writers match zeros. Zone porosity stays unwired.
