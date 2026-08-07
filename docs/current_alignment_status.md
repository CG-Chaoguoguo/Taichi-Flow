# Current Scientific Alignment Status

Last updated: 2026-04-12

## 2026-04-15 Candidate2 Status Addendum

The `candidate2` diagnostic line is now formally parked pending new evidence.
This is not because the project found no differences, but because the full
test-only chain still failed to identify a production-expressible
trigger-level first cause.

Current official status for `candidate2`:

- status: closed / parked pending new evidence;
- production edit status: No-Go;
- current best confirmed divergence: `qq result emission` at
  `after_edge_fluxes` inside `DFS._compute_edge_fluxes()` for the large-case
  freeze line, and `fhw` as the earliest observable but still non-trigger
  intermediate difference in the observability audits;
- current stop reason: no verified trigger-level first-cause that can be
  translated into a production rule entry;
- allowed work: future evidence acquisition only, including internal logging,
  rule-level comparison, and micro-case trigger isolation;
- disallowed work: no more large-case `patch/freeze/face-combination` expansion,
  no return to `qq/qqmass` carry experiments, and no production-solver edit
  branch.

The candidate2 chain is therefore a controlled closure and risk-management
outcome, not an abandoned unexplained bug.

## Purpose

This note gives a concise current-status view of the EDDA-Taichi alignment
effort. It is the documentation-side companion to the more detailed project
report in `PROJECT_REPORTS/MILESTONE_ALIGNMENT_SUMMARY_2026-04-09.md`.

## Current Status In One Paragraph

EDDA-Taichi has already moved past broad architectural and scalar-field
misalignment. For the real `EntireBanzigou1005` case, the solver now aligns
very closely with the original EDDA through `3600s`, `7200s`, `10800s`, and
`14400s`, and remains tightly aligned for most scalar outputs at `18000s`.
The remaining unresolved gap is concentrated in the final `18000s`
`Flow_velocity_1..8` topology, where a late thin-front feeder branch still
activates on the wrong accepted-step sequence.

## What Is Already Stable

- active-domain masking and `NoData` handling;
- 8-direction neighbor mapping consistent with `flodir.f90`;
- critical precision paths;
- DFS-aligned production route for the real case;
- double-layer and rainfall forcing sequencing needed for scientific tests;
- checkpoint and exact accepted-step diagnostics for late-window tracing;
- EDDA-style `Deposit_depth` output semantics, now corrected to compare
  positive bed-elevation change `max(z_bed-z_original, 0)` instead of the
  cumulative deposition bookkeeping field.

## What Still Needs To Be Closed

- the `18000s` branch-selection mismatch in `Flow_velocity_1..8`;
- final unified export of the full EDDA-style result set once the remaining
  velocity topology gap is closed.
- the `candidate2` line does **not** currently add a production-fix candidate
  for that remaining mismatch; it remains documentation-complete but parked
  until new trigger-level evidence exists.

## Current Best Root-Cause Summary

The remaining bias comes from a late thin-front donor network where some cells
cross `tol = 0.01 m` too early and others too late. That changes which faces are
active when a thin cell first turns on, and the wrong branch then persists into
the final directional-velocity output.

This is a narrow, scientifically meaningful mismatch, not a broad failure of
the migrated solver.

The latest audits also explicitly ruled out several nearby alternatives:

- main DFS time-advance inconsistency;
- inactive listed inputs (`ri*.txt`, `depthwt.asc`, `rizero.asc`) for this case;
- rainfall interval averaging / `capt` boundary handling in the current
  forcing path;
- accidental use of DEM-only slope instead of `bcslope.asc`;
- broad source-field/reset mismatches in the current donor-ring trace.
- a slope-unit mismatch between `bcslope.asc` and original `slo(i)`;
- Taichi/CUDA evaluating the late clear-water face kernel differently from a
  strict sequential execution of the current formulas.
- incorrect output-boundary ordering in the continuous production run around
  `14400s` itself; a real `t_end == output boundary` bug existed in the Python
  control flow and is now fixed, but the main `0 -> 18000s` production path
  already follows the normal output-truncation route at `14400s`, so that bug
  is not the remaining scientific root cause by itself.

The newest upstream audit also extends the traced mismatch source farther
upstream than before: the currently confirmed donor chain now reaches
`(147,204)`, then hands off through the `146`, `145`, and `144` rings before
reaching the previously documented `143/142/141/140` cells. This means the
remaining gap is not born in the final residual cluster itself; it is already a
moving branch-selection problem several accepted steps earlier.

A second follow-up audit corrected the interpretation of a truncation artifact.
The trustworthy local source in that upstream ring is still `(149,205)`, but
it must be read at the natural accepted-step `17963.363999479661s`, not at the
extra micro-step used only to land on `17963.364s`. At that accepted-step:

- `(149,205)` crosses locally with `tempinflowh = 0.0`,
- the crossing is driven by the local `fhw -> inflx -> ir -> fhpredi1` chain,
- then the same-step discharge lifts `(149,204)` in committed `h`

The newest pulse-history audit adds one more important correction: this local
crossing is not the whole story. `(149,205)` had already participated in an
earlier donor-fed pulse during `17943 -> 17955s`, then relaxed back near
`tol`, and only later re-crossed locally. That means the remaining root-cause
focus shifts one layer farther upstream again: the divergence is not born at
the later local re-crossing alone, but in the accepted-step history of the
support ring that seeds that earlier pulse.

The latest follow-up audit sharpens that support-ring picture again. The
current earliest confirmed oscillatory core is no longer `(149,205)` itself but
the upstream ring around `(147,204)`, `(148,204)`, and `(148,205)`. In the
current trace, `(149,205)` is already a downstream threshold responder to a
two-second on/off pattern that is active in that ring by `17927 -> 17935s`.

The newest reservoir-detachment audit pushes the chain farther upstream again
and changes the interpretation of what still matters. The traced donor path now
reaches a stable wet source region around `(137,201)`, with persistent support
from nearby cells such as `(136,202)` and `(137,200)`. Those cells are no
longer behaving like marginal `tol = 0.01 m` thin-front gates; they are already
well-wetted source cells. That means the remaining unresolved problem is now
best framed as a reservoir-edge branch-partition mismatch:

- how the stable wet source around `(137,201)` splits discharge into
  `(137,200)`, `(136,201)`, and `(136,200)`,
- and how that split seeds the later thin-front feeder branch that remains
  misaligned at `18000s`.

Separately, the newest output-semantics audit corrected one comparison-layer
ambiguity that had remained in the project: EDDA's `Deposit_depth` output is
the positive bed-elevation change, not the cumulative deposition bookkeeping
field. After correcting that mapping, the real-case `Deposit_depth` comparison
for the `14400 -> 18000s` CUDA window is exact (`RMSE = 0`), so this variable
is no longer part of the unresolved residual set.

A newest follow-up audit sharpens the late-window reservoir interpretation again. The clearest remaining terminal support cell is `(139,202)`: the reference keeps it barely active at `18000s` with only `Flow_velocity_4`, while the current Taichi/CUDA run has already let it fall completely below the predictor dry gate. The decisive detachment now has a concrete accepted-step window: `(139,202)` is still active at `17995.363999479661s` but fully dead by `17997.363999479661s`. That makes `17995.363999479661 -> 17997.363999479661s` the current best local target for the first still-unmatched control-flow difference.

The newest executable-semantics audit trims that search space again. It rules
out several nearby alternatives that were still worth checking once the late
branch loss had been localized:

- the current real-case runner already matches original EDDA's `dt = 1.0`
  startup semantics;
- the supplied `dfs.F90` uses `bkgrof` only on `tempir` before the
  `doublelayer(...)` call, not on the surface-water `tempri` update, and the
  current port matches that supplied behavior;
- the current `cell_id` ordering for the traced residual cells matches the
  Fortran row-major valid-cell numbering used by the `nq<i` owner-face rule;
- the supplied Fortran does contain a real `tanslodir(1:8)` carry-over quirk,
  but the currently traced reservoir-edge residual cells all have full
  eight-neighbor support, so that quirk is not the first local cause of the
  current `17991 -> 17997s` detachment chain.

The newest local reroute audit sharpens the reservoir-edge picture once more.
The critical `17991.363999479661s -> 17993.363999479661s` transition is not a
pure shut-off. It is a topological reroute:

- at `17991.363999479661s`, `(139,202)` is supported through `dir4` from
  `(140,203)`, while `dir3` is still dry-skipped;
- by `17993.363999479661s`, `(140,203)` has dropped below the predictor dry
  gate, `(139,203)` has risen above it, and `(139,202)` is still alive but now
  on the wrong directional set (`dir3`, `dir6` instead of the expected
  southeast support branch).

This means the current best local target is no longer just "why does
`(140,203)` die?" but more specifically:

- why does `(139,203)` become the takeover donor at exactly that accepted step,
- while the reference solution appears to preserve the southeast support chain
  toward the final output?

## 2026-04-12 Documentation-Cleanup Note

The repository is being prepared for GitHub publication using branch-based
development. The current scientific blocker remains the same: the late
`Flow_velocity_1..8` branch topology at `18000s`. Documentation and dependency
files may be updated independently, but production solver changes should remain
on dedicated feature branches and continue to cite the corresponding original
EDDA Fortran statements.

For the active issue list and recommended branch split, see:

- `docs/current_development_issues.md`
- `docs/github_workflow.md`

## Where To Go Next

### Candidate2 audit / closure archive

- `tests/output/candidate2C1_direction_closure_memo.md`
  - Candidate2 master closure memo, now carrying the cross-stage evidence chain
    from A5-A10, B1-B3, C3, and D1.
- `tests/output/candidate2B1_rule_mapping_audit_report.md`
  - Rule-mapping audit showing the current freeze line still lands on
    `qq/qqmass` result emission rather than a trigger condition.
- `tests/output/candidate2B3_trigger_rule_observability_report.md`
  - Trigger-rule observability audit showing no stable trigger-level first
    divergence before `qq result emission`.
- `tests/output/candidate2C3_capability_backlog.md`
  - Future reopen capability backlog and engineering preconditions.
- `tests/output/candidate2C3_reopen_decision_tree.md`
  - Candidate2 reopen decision tree.
- `tests/output/candidate2D1_micro_case_execution_report.md`
  - Micro-case trigger-isolation execution report; current outcome remains
    `worth_reopening_now = No`.

- For the milestone summary: `PROJECT_REPORTS/MILESTONE_ALIGNMENT_SUMMARY_2026-04-09.md`
- For the quantitative reference-case comparison:
  `PROJECT_REPORTS/FIX_LOGS/REAL_CASE_ALIGNMENT_REPORT_2026-03-28.md`
- For the latest root-cause diagnostics:
  `PROJECT_REPORTS/FIX_LOGS/LATE_CLUSTER_BRANCH_CHAIN_2026-04-06.md`
- For the latest source/accepted-step audit:
  `PROJECT_REPORTS/FIX_LOGS/SOURCE_FIELD_AND_ACCEPTED_STEP_AUDIT_2026-04-10.md`
- For the newest upstream donor-chain trace:
  `PROJECT_REPORTS/FIX_LOGS/UPSTREAM_DONOR_RING_AUDIT_2026-04-10.md`
- For the natural-step source correction:
  `PROJECT_REPORTS/FIX_LOGS/NATURAL_STEP_SOURCE_AUDIT_2026-04-10.md`
- For the earlier pulse-history correction:
  `PROJECT_REPORTS/FIX_LOGS/PULSE_HISTORY_AUDIT_2026-04-10.md`
- For the upstream support-ring phase audit:
  `PROJECT_REPORTS/FIX_LOGS/SUPPORT_RING_PHASE_AUDIT_2026-04-10.md`
- For the reservoir-edge branch-detachment audit:
  `PROJECT_REPORTS/FIX_LOGS/RESERVOIR_BRANCH_DETACHMENT_AUDIT_2026-04-10.md`
- For the output-semantics correction:
  `PROJECT_REPORTS/FIX_LOGS/OUTPUT_SEMANTICS_AUDIT_2026-04-10.md`
- For the reservoir-edge step detachment audit:
  `PROJECT_REPORTS/FIX_LOGS/RESERVOIR_EDGE_STEP_DETACHMENT_AUDIT_2026-04-10.md`
- For the executable-semantics exclusion audit:
  `PROJECT_REPORTS/FIX_LOGS/EXECUTABLE_SEMANTICS_AUDIT_2026-04-10.md`
- For the branch-reroute audit:
  `PROJECT_REPORTS/FIX_LOGS/RESERVOIR_BRANCH_REROUTE_AUDIT_2026-04-10.md`
- For the output-boundary ordering audit:
  `PROJECT_REPORTS/FIX_LOGS/OUTPUT_BOUNDARY_ORDER_AUDIT_2026-04-10.md`

## 2026-04-10 Additional Audit
- Case-local dfs.F90/wfs.F90 are byte-identical to Reference Software\\Edda; the audit is not chasing the wrong source snapshot.
- The reference executable used in EntireBanzigou1005 is x64 and byte-identical to x64\\Debug\\EDDA.exe; the remaining mismatch is not explained by a hidden Win32/x87 path.
- Replacing stage-surface cv with the persisted Fortran-style cv array is more literal, but it does not materially change the 18000s directional-velocity residual.
- In the critical 17991 -> 17993s reservoir-edge window, 	empfsh_flow, erosion_rate, and deposition_rate are zero at the traced residual cells, so the remaining mismatch is now best treated as a pure clear-water face-flux / branch-reroute problem.

## 2026-04-10 Follow-Up Audit
- `bcslope.asc` is already read in degrees and converted to radians exactly as original EDDA does for `slo(i)`.
- The traced donor/support cells in the late residual chain all have full 8-neighbor support, so the known supplied-Fortran `tanslodir` carry-over quirk is not acting on those residual cells through missing-neighbor directions.
- At the exact accepted-step state `t = 17991.363999479661s`, `dt = 2.0s`, the Taichi/CUDA `_compute_edge_fluxes(...)` results match a strict sequential NumPy reproduction to machine precision (`fv_max_abs_diff ≈ 2.36e-14`).
- This means the remaining mismatch is not created by Taichi/CUDA executing the late clear-water face kernel incorrectly at the same staged state; it is already present in the staged history that reaches that state, or in some earlier executable-semantics divergence that feeds it.

## 2026-04-10 Rainfall Interval Audit
- The current `RainfallReader.get_interval_average_rainfall(...)` path now has
  direct regression coverage against the supplied `dfs.F90` interval-selection
  semantics.
- Around all `capt` boundaries in the real `EntireBanzigou1005` schedule,
  sampled at the same `dt` scale the solver actually uses (`1e-6s` to `2.0s`),
  the maximum difference between the current implementation and a direct Python
  translation of the Fortran logic is `1.7e-21 m/s`.
- This rules out rainfall interval averaging and `capt` boundary handling as a
  first-order cause of the remaining `18000s` `Flow_velocity_1..8` mismatch.

## 2026-04-10 Post-14400 Local History Audit
- The traced reservoir-edge / donor-chain neighborhood (`rows 130:156`,
  `cols 195:209`) matches the original EDDA directional-velocity outputs
  exactly at both `10800s` and `14400s` (`max_abs_diff = 0`).
- On the traced chain cells, the entire `14400 -> 18000s` accepted-step window
  is source-free above `1e-12`: `tempfsh_flow = 0`, `erosion_rate = 0`, and
  `deposition_rate = 0` throughout the scan.
- The local predictor stage is also exact at the key accepted-step activations:
  reconstructed `fhw` and `fhpredi1` match the recorded traces exactly at both
  `17961.363999479661 -> 17963.363999479661s` and
  `17991.363999479661 -> 17993.363999479661s`.
- This pushes the remaining search space into a narrower class:
  post-`14400s` accepted-step history / branch-support divergence imported from
  outside the already verified local block, not a local predictor/source-term
  bug inside that block.

## 2026-04-10 Post-14400 Origin Audit
- The full-grid `Flow_velocity_1..8` field at `14400s` matches the original
  EDDA outputs exactly (`max_abs_diff = 0`, `count_over_1e-9 = 0`).
- The traced local block (`rows 130:156`, `cols 195:209`) is likewise exact at
  both `10800s` and `14400s`.
- The same block stays source-free through `14400 -> 18000s` above numerical
  round-off (`tempfsh_flow = 0`, `erosion_rate = 0`,
  `deposition_rate max = 3.05e-17`).
- This means the remaining `18000s` mismatch is generated after `14400s` inside
  a pure rainfall/infiltration + clear-water history window, not inherited from
  a pre-existing `14400s` velocity mismatch in the traced region.

## 2026-04-10 Face Pairing And Late-Window Exclusions
- At the accepted-step state `t = 17991.363999479661s`, the current pairwise
  shared-face rule (`neighbor_cell_id > current_cell_id`) is exactly
  equivalent to original Fortran `qq(i,ii) /= 0 ; nq < i ; cycle` semantics:
  `fv/qq/qqt/qqmass/fybar` all match exactly between the two reproductions.
- The real-case time-step control parameters are parsed exactly from
  `edda_in.txt`:
  - `dtmin = 1.0e-5`
  - `dtmax = 2.0`
  - `dti = 1.0e-4`
  - `dtd = 1.0e-3`
  - `toldh = 0.1`
  - `toldhp = 0.05`
- The full `14400 -> 18000s` accepted-step window is globally source-free to
  numerical precision:
  - `max_tempfsh_abs = 0.0`
  - `max_erosion_abs = 0.0`
  - `max_deposition_abs = 1.0967661053157558e-16`
- This further narrows the remaining `18000s` mismatch to a pure
  rainfall/infiltration + clear-water accepted-step history divergence, not a
  shared-face ownership bug, not misparsed time-step controls, and not any
  late-window source-term activity.
