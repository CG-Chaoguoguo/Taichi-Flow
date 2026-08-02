# EDDA-Taichi Current Development Issues

Last updated: 2026-04-12

This document is the working issue map for the current repository state. It is
intended to guide branch-based GitHub work without changing the scientific goal:
match original EDDA first, then optimize or extend.

## Non-Negotiable Development Rule

The CUDA/Taichi backend must preserve original EDDA computation semantics.
When runtime convenience conflicts with scientific fidelity, the project should
choose original EDDA fidelity and keep the item marked unresolved.

## Active Scientific Alignment Issue

### 1. Late `Flow_velocity_1..8` branch topology at `18000s`

Status: unresolved.

Observed state:

- The real `EntireBanzigou1005` case is tightly aligned through `14400s`.
- At `18000s`, scalar fields remain close, but the 8 directional velocity grids
  still show a branch-selection mismatch in a thin clear-water front.
- The current best local focus is the reservoir-edge / feeder branch around
  `(139,202)`, `(139,203)`, `(140,203)`, and upstream support around
  `(137,201)`.

Current interpretation:

- The mismatch is not a broad CUDA arithmetic failure.
- It is not explained by NoData handling, direction order, rainfall interval
  parsing, output-boundary time stepping, or source-term activity in the traced
  late window.
- The remaining problem is a narrow accepted-step history / branch-partition
  divergence that changes which faces cross the original EDDA dry/wet gate.

Required next work:

- Continue tracing face-level clear-water flux partitioning in the
  `14400s -> 18000s` window.
- Compare every proposed fix to the exact `dfs.F90` statement sequence before it
  enters the production path.
- Keep diagnostic alternatives outside the production solver unless they are
  proven to reproduce original EDDA executable behavior.

### 2. `candidate2` diagnostic line

Status: parked pending new evidence.

Confirmed:

- A5 established the root-local minimum sufficient block `{dir2, dir4}`.
- A6 showed the missing condition moved from a root-only partition question to
  a cross-cell face-network question, with `140,203 dir4` as the first truly
  effective added cross-cell face.
- B1 showed the current freeze expression mainly hits `qq/qqmass` result
  emission inside `DFS._compute_edge_fluxes()`.
- B2 showed `fhw` is the earliest observable difference, but still only an
  intermediate state.
- B3 showed no stable trigger-level divergence in
  `candidate_face_set` / `self_neighbor_wet_gate_set` /
  `owner_neighbor_pair_execution_set` / `face_reason_code` /
  `pair_reason_code` before `qq result emission`.
- D1 landed the minimum reopen capability subset and micro-case harness, but
  still did not produce a trigger-level first-cause.

Falsified:

- continuing root-local face addition after A5;
- single-branch `dir4` farther-chain continuation as the shortest remaining
  cause (A7/A9);
- minimal dual-branch coupling as the current bottleneck (A8);
- farther-chain plus minimal dual-branch combination as a remaining minimal
  cause (A10);
- entering a production-modification branch based on current evidence.

Not yet established:

- any production-expressible trigger-level first-cause for `candidate2`;
- any stable toy-case divergence in screening or pair-execution logic that can
  be mapped back to the large case;
- any owner-selection-only trigger split worth escalating into a larger replay.

Current rule for the repository:

- do not reopen the large-case `candidate2` patch/freeze route;
- do not start a production solver edit for `candidate2`;
- only allow future evidence acquisition work that targets new trigger-level
  observability or a new production-expressible rule entry.

## Output And Comparison Work Still Needed

Status: partially complete.

Original EDDA outputs that must remain part of comparison reports:

- `Deposit_depth`
- `Erosion_depth`
- `Flow_depth`
- `Flow_velocity_1..8`
- `fs_min`
- `Max_flow_depth`
- `Max_flow_velocity`
- `Total_depth`
- `Volumetric_sediment`

Current notes:

- `Deposit_depth` comparison semantics were corrected to use positive bed
  elevation change rather than cumulative deposition bookkeeping.
- Full output-format unification should wait until the remaining directional
  velocity topology issue is closed or explicitly bounded.

## Repository And Release Issues

### 1. Large local generated outputs

Status: local cleanup required before public pushes.

Generated comparison outputs and checkpoints live under ignored directories such
as `tests/output/` and `tests/comparison/output/`. They are useful locally but
should not be committed.

### 2. Reference case data is external

Status: document-only.

The primary reference case is expected at:

```text
C:\Users\Administrator\Desktop\EntireBanzigou1005
```

The repository should not depend on committing that full case. Future public CI
should use a small synthetic or anonymized fixture.

### 3. Historical docs still contain archived claims

Status: mostly indexed, not fully rewritten.

Some early March documents are useful as repair history but are not current
status documents. Use the docs index and `PROJECT_REPORTS/README.md` to direct
new contributors to the current status first.

## Suggested Branches

- `docs/github-readiness`: README, dependency files, documentation index, and
  repository hygiene only.
- `feature/dfs-velocity-alignment`: production or diagnostic changes related to
  the remaining `Flow_velocity_1..8` mismatch.
- `feature/output-format-parity`: EDDA-style output export and comparison
  unification after velocity topology is resolved.
- `test/reference-fixtures`: small fixtures that can run in CI without the full
  private reference case.
- `feature/candidate2-evidence-only`:
  documentation, logging, and toy-case observability work only; not a
  production-fix branch and not a large-case patch/freeze branch.

## Definition Of Done For The Current Scientific Phase

The current alignment phase is not done until:

- the original EDDA equation order, direction order, dry/wet gating, and time
  stepping are matched in the production path;
- the real-case comparison includes the full EDDA output set listed above;
- any remaining difference has a specific Fortran/executable source, not a
  generic claim that results are close;
- no production-path stabilizer or formula simplification exists solely to make
  the GPU run easier.
