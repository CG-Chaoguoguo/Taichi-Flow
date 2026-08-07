# Current Development Status

Last updated: 2026-04-20

## Current backend stage

- native input-chain S1: first-wave formally closed for the bounded subset
- current active audit: S2 parameter semantic / role consistency audit
- frontend status: broad parameter exposure is still blocked

## Current headline judgment

The backend now has a meaningful production-reachable subset, but the project is still only **partially consistent** with the parameter notes and original EDDA runtime roles.

## Current audit entry points

Detailed backend audit materials are now kept under:

- [../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS](../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS)

Recommended starting points:

- [../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_consistency_audit.md](../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_consistency_audit.md)
- [../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv](../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv)
- [../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/reference_case_parameter_role_audit.md](../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/reference_case_parameter_role_audit.md)
- [../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/input_runtime_consistency_notes.md](../PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/input_runtime_consistency_notes.md)

## Keep blocked from broad frontend exposure

- `wavemax`
- `shallown`
- `uww`
- `depth`
- `cvstar`
- `K/kresis`
- `manningfil`
- `dirfil`
- `rifil`
- output flags
- `outflow.txt`
- `hydrograph.txt`

## Selectively safer subset

Current audit supports only selective future exposure for the more stable `R1` subset, not broad EDDA-style parameter exposure.
