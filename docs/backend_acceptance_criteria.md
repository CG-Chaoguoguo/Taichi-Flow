# Backend Acceptance Criteria

Last updated: 2026-04-18
Stage: S0 baseline freeze

## Purpose

This document defines the acceptance thresholds used by
[docs/backend_alignment_matrix.md](backend_alignment_matrix.md).

These definitions are intentionally strict. They exist to stop the project from
mislabeling:

- field presence as feature completion;
- helper injection as production capability;
- partial runtime reachability as original EDDA parity;
- paper boundary items as current must-fix production gaps.

## Core Evidence Principle

A backend capability is accepted only when the evidence chain is closed across
all three hops below:

1. original EDDA parameter / file / control family;
2. current backend implementation location;
3. production runtime reachability and runtime-use evidence.

If any hop is missing, the capability must not be marked `F`.

## Status Labels

### `F` — fully implemented and production-reachable

A capability family may be labeled `F` only if **all** conditions below are met:

1. **Production API reachable**
   - the family can be entered through the production backend path centered on
     `POST /simulation/start -> SimulationConfig`;
   - it does not depend on alignment helpers or test-only builders.

2. **Input source is formalized**
   - the production backend has a real schema / loader / configuration path for
     the required inputs;
   - the family does not depend on case-specific helper injection to restore a
     missing file or field.

3. **Runtime has a real consumption point**
   - at least one production solver / physics / I/O path demonstrably consumes
     the configuration during a real run.

4. **Runtime evidence is observable**
   - at least one of the following proves the family participated in the run:
     - effective config snapshot;
     - runtime metadata;
     - result metadata;
     - output manifest;
     - log / process record;
     - auditable call chain with production reachability.

5. **Semantic equivalence is closed or explicitly resolved**
   - the family is functionally equivalent to the original EDDA capability, or
     any remaining difference is explicitly documented and no longer changes the
     family classification.

If even one of the above is missing, do **not** use `F`.

### `P` — partially implemented

Use `P` when the family has real backend implementation, but the evidence chain
is still incomplete.

Typical `P` characteristics:

- there is a schema field and a backend module, but the full production
  evidence chain is not closed;
- runtime consumption exists, but the original EDDA input or output ecosystem is
  still incomplete;
- the capability works for a core subset but not for the full original family;
- a high-risk control parameter in the same family still lacks semantic closure;
- metadata / logs / manifests are too weak to prove end-to-end production use.

`P` means **do not advertise parity yet**.

### `H` — solver/helper available but not production-reachable

Use `H` when the family is available in research, helper, or comparison code,
not in the production backend path.

Typical `H` characteristics:

- implemented in alignment scripts, helper builders, or test-only utilities;
- requires case-specific injection after solver initialization;
- bypasses the production API / schema path;
- proves research feasibility, but not production capability.

`H` is useful scientific scaffolding, but it is **not** a production feature.

### `M` — missing

Use `M` when the backend lacks a meaningful equivalent production capability.

Typical `M` characteristics:

- no production schema / loader / runtime path exists;
- only a similarly named field exists, but no equivalent semantics;
- output or process-record parity is absent entirely;
- the original EDDA capability family has no formal current backend equivalent.

`M` must not be hidden behind vague wording such as “partially present” unless
there is real runtime coverage.

### `O` — out of original validated scope

Use `O` when the item is outside the original validated production scope that is
being targeted for parity in this project stage.

Typical `O` characteristics:

- the original paper explicitly describes the item as incomplete, empirical, or
  not fully validated;
- the item is not part of the baseline parity target for the current roadmap;
- failure to implement it does not block declaring parity for the validated
  original core.

Examples include boundary paper items such as:

- dam breaching not fully validated;
- bank failure remaining empirical;
- vertical segregation not in the primary depth-averaged model scope.

## Family-Level Versus Parameter-Level Acceptance

A parameter can be runtime-used without making the entire capability family `F`.

Examples:

- a family stays `P` if one high-risk original control in that family is still
  unresolved;
- a family stays `P` if the solver core exists but native original input files
  are still helper-only;
- a family stays `P` if outputs are fixed-export only, while original EDDA used
  a flag-controlled output system.

Therefore this project must classify at the **capability-family level**, not by
counting parameters.

## Production-Reachability Test

When deciding between `P` and `H`, ask:

1. Can the capability be entered from the production API without a custom case
   helper?
2. Does `SimulationConfig` carry the family in a formalized way?
3. Does the solver runtime consume it without helper reinjection after
   initialization?
4. Is there production metadata or output evidence that the capability was used?

If the answer to the first two is no, the family is usually `H` or `M`, not `P`.

## Frontend Gate Rule

Frontend exposure is derived from backend acceptance level:

- `F`: may be exposed normally;
- `P`: may only be exposed with an explicit partial-support label and only if
  the semantic risk is controlled;
- `H`: do not expose as production capability;
- `M`: do not expose;
- `O`: exclude from the active parity backlog.

Detailed frontend guidance is frozen in
[docs/frontend_exposure_gate.md](frontend_exposure_gate.md).

## S0 Baseline Consequence

At S0, the project baseline is:

- no broad original-EDDA capability family is yet accepted as `F`;
- the backend currently represents a strong but incomplete solver-focused
  subset;
- helper-only support must remain explicitly labeled as non-production;
- no large-scale frontend parameter exposure should proceed until the relevant
  families are promoted beyond their current state.
