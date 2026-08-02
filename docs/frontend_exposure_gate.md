# Frontend Exposure Gate

Last updated: 2026-04-18
Stage: S0 baseline freeze

## Purpose

This document prevents frontend integration from outrunning the current backend
acceptance state.

It is derived from:

- [docs/backend_alignment_matrix.md](backend_alignment_matrix.md)
- [docs/backend_acceptance_criteria.md](backend_acceptance_criteria.md)
- [docs/backend_repair_roadmap.md](backend_repair_roadmap.md)

The purpose here is not to design UI. The purpose is to define what the frontend
may safely expose **later**, and what must remain blocked until the backend is
more complete.

## Gate Rule

A capability family may be exposed in the frontend only if its backend evidence
state justifies it.

Baseline mapping:

- `F`: eligible for normal exposure;
- `P`: only eligible for constrained or explicitly labeled partial exposure;
- `H`: not eligible for production exposure;
- `M`: not eligible;
- `O`: excluded from the active parity-exposure backlog.

## Category 1 — Can Be Safely Exposed Later

At S0, **no broad original-EDDA capability family yet satisfies a full,
unqualified safe-exposure standard**.

This means:

- there is currently no justification for large-scale EDDA-parameter frontend
  exposure;
- existing generic run controls may continue only within the already known
  backend contract, but they must not be marketed as “full original EDDA
  capability coverage”.

## Category 2 — Gray Exposure Only / Partial Support Label Required

These families are backend-meaningful enough that they may later be shown in a
restricted or clearly labeled way **after** the relevant S1–S3 work, but they
must not be presented as full parity today.

- time control and stability control;
- rainfall timing and rainfall forcing subset;
- infiltration and pore pressure subset;
- slope stability and shallow-failure subset;
- erosion and deposition subset;
- double-layer and zone parameter subset;
- outflow boundary semantics subset.

Required label if exposed later:

- `partially supported`
- `runtime-reachable subset only`
- `not full original EDDA parity`

## Category 3 — Must Not Be Exposed

These families must remain blocked from frontend exposure until promoted by the
backend roadmap.

### High-risk parameter families

- `wavemax`
- `shallown`
- `uww`

Reason:

- these are high-risk semantic items still lacking full closure in the current
  backend evidence chain.

### Helper-only or missing file families

- `zonfil / slofil / zfil / ltstar` as native production inputs;
- `manningfil`;
- `dirfil`;
- `TopoIndex / LogTI` related files;
- native `outflow.txt` and `hydrograph.txt` input families.

Reason:

- current support is helper-only, partial, or missing;
- exposing these in frontend would mislead users into assuming production
  capability exists.

### Output-control and process-record families

- original EDDA output flags;
- outflow process export parity;
- hydrograph process export parity;
- `EDDALog.txt`-equivalent process record family.

Reason:

- backend does not yet provide formal output-control parity or process-record
  parity.

## Exposure Decision Table

| Capability family | Current backend state | Frontend gate |
| --- | --- | --- |
| Time control and stability control | P | Gray only after S2 |
| Rainfall input and timing | P | Gray only after S1/S2 |
| Infiltration and pore pressure | P | Gray only after S2 |
| Slope stability and shallow-failure conversion | P | Gray only after S2/S4 |
| Surface erosion initiation | P | Gray only after S2 |
| Rheology and regime switching | P | Block advanced controls until `shallown` is closed |
| Kinematic / dynamic flow solve | P | Do not expose advanced solver-mode controls yet |
| Erosion and deposition | P | Gray only after S2/S3 |
| Double-layer and zone system | P | Block advanced spatial controls until S4 |
| Spatial input file ecosystem | M / H | Block |
| Outflow / hydrograph family | P | Block process-facing controls until S1/S3 |
| Output control family | P / M | Block |
| Point log / process record family | M | Block |
| Helper-only alignment features | H | Block |
| Paper boundary items | O | Exclude |

## Codex / Frontend Integration Consequence

Until the backend roadmap advances beyond the current S0 state:

- no large-scale EDDA-derived parameter panel should be attached to the UI;
- no helper-restored feature should be presented as a production setting;
- no output flag family should be surfaced as if original EDDA parity already
  exists;
- any future partial exposure must cite the backend family state explicitly.

## S0 Official Frontend Gate Statement

The official S0 frontend gate is:

- **No broad EDDA-parameter exposure**;
- **partial exposure only after backend family promotion with evidence**;
- **helper-only, missing, and high-risk semantic families remain blocked**.
