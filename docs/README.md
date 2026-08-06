# Documentation index

## Current runtime

- [`architecture.md`](architecture.md) — domain boundaries, SQLite state, and
  scheduler lifecycle.
- [`api_reference.md`](api_reference.md) — current nested REST/WebSocket
  surface and error contract.
- [`developer_guide.md`](developer_guide.md) — setup, testing, and extension
  rules.
- [`user_guide.md`](user_guide.md) — project, input, scenario, queue, result,
  and export workflow.
- [`adr/0001-persistent-project-domain-state.md`](adr/0001-persistent-project-domain-state.md)
  and [`adr/0002-runtime-queue-concurrency.md`](adr/0002-runtime-queue-concurrency.md)
  — decisions for persistence and admission control.

## Scientific boundary

The existing alignment and input-chain documents remain research notes. The
frontend/domain cutover does not modify `edda/` formulas, source timing,
dry/wet gates, direction order, timestep semantics, or output meaning. No
Fortran parity claim is made by the UI verification.

## Repository hygiene

Commit stable source, maintained tests, architecture decisions, and user or
developer documentation only. Generated diagnostics, browser screenshots,
logs, outputs, local state databases, and temporary comparison material remain
under ignored local directories.
