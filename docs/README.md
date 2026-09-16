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
frontend/domain cutover itself does not modify `edda/` formulas, source timing,
dry/wet gates, direction order, timestep semantics, or output meaning. Later
solver repairs are documented separately; no Fortran parity claim is made by
the UI verification.

## Evidence

Migration, OpenAPI inventory, browser screenshots, and test logs may live under
the local-only `artifacts/` directory. A clean clone is not expected to contain
those raw files. All of `docs/audit/`, including Markdown/JSON summaries and
screenshots, is also local-only and is not distributed with a clean checkout.
The root `agentlog.md` is local-only and is not a documentation entry point.
Reusable comparison tools and their usage are documented in
[`tools/fix3/README.md`](../tools/fix3/README.md); their generated evidence stays local.
