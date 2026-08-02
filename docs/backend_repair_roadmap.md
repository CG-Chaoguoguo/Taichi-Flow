# Backend Repair Roadmap

This detailed staged roadmap has been migrated out of `docs/`.

Current canonical location:

- [../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/backend_repair_roadmap.md](../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/backend_repair_roadmap.md)

Current development summary:

- [current_development_status.md](current_development_status.md)

1. double-layer and zone families are production-reachable without helper
   reinjection;
2. the required spatial file families have native or formally structured
   production loaders;
3. runtime evidence proves these spatial inputs participated in the run;
4. helper-only spatial restoration is no longer needed for parity claims.

### Frontend consequence

Only after S4 should advanced spatial-heterogeneity configuration be considered
for user-facing exposure.

### What S4 must not do

- no silent fallback from missing spatial files to helper patches;
- no claim of original parity while helper injection remains mandatory.

## S5 — Research-Grade Regression And Acceptance System

### Goal

Build the evidence system needed to keep the repaired backend stable and
scientifically auditable.

### Target capability families

- effective-config snapshotting;
- runtime capability manifests;
- acceptance-matrix-backed regression cases;
- reproducible backend audit artifacts;
- controlled frontend exposure gates tied to backend acceptance state.

### Entry conditions

- S1–S4 closure decisions frozen;
- capability-family classifications stable enough for regression locking.

### Done definition

S5 is complete only when:

1. every production-relevant capability family has a traceable acceptance
   status;
2. regression artifacts can detect loss of production reachability or semantic
   drift;
3. frontend exposure gates are derived from backend evidence, not optimism;
4. the project can state clearly which original EDDA families are truly covered.

### Frontend consequence

S5 is the stage that supports deliberate, broad, low-risk frontend configuration
exposure. Before S5, frontend work must stay gated by the capability matrix.

### What S5 must not do

- no replacing acceptance evidence with one-off manual claims;
- no collapsing `P`, `H`, and `M` into a single “supported soon” bucket.

## Stage Order Discipline

The expected order is:

1. `S0` freeze and terminology lock
2. `S1` native input chain recovery
3. `S2` high-risk parameter hardening
4. `S3` output and process-log closure
5. `S4` spatial ecosystem closure
6. `S5` regression and acceptance system

Any deviation should be documented explicitly. The default project rule is:
**do not skip ahead because a single local patch looks convenient**.

## S0 Exit Condition

S0 may be considered complete when:

- the matrix in [docs/backend_alignment_matrix.md](backend_alignment_matrix.md)
  is frozen;
- the definitions in [docs/backend_acceptance_criteria.md](backend_acceptance_criteria.md)
  are frozen;
- the frontend gate in [docs/frontend_exposure_gate.md](frontend_exposure_gate.md)
  is frozen;
- the team agrees to treat `P`, `H`, and `M` as real blockers for broad
  frontend exposure.
