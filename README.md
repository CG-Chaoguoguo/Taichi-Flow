# Taichi-Flow

Taichi-Flow is a local scientific simulation workbench. The React/Vite client
and FastAPI domain service share one project model: immutable input revisions,
evidence-gated scenarios, a persisted queue, simulation runs, result families,
and asynchronous exports.

The cutover keeps the internal `edda/` numerical implementation and original
text-case parsing semantics. It does not change physical formulas, source-term
timing, dry/wet gates, direction order, time-step semantics, or output
meaning. This repository does not claim Fortran numerical parity.

## Runtime layout

```text
Taichi-Flow/
  api/                         FastAPI domain service and runtime coordinator
  edda/                        Internal numerical implementation
  frontend/taichi-flow/        React/Vite production UI
  artifacts/agent_runs/        Migration and verification evidence
  docs/                        Current architecture, API, and runbooks
  tests/                       Domain and solver regression tests
```

Project registration is stored under `%LOCALAPPDATA%\\Taichi-Flow` by default
(`TAICHI_FLOW_STATE_DIR` overrides it). Each project owns
`.taichi-flow/state.sqlite3`; uploads are immutable SHA-256 addressed blobs.
`TAICHI_FLOW_MAX_CONCURRENT_PROJECTS` controls the global project concurrency
limit and defaults to `2`.

## Start locally

```powershell
# from the repository root
.\\scripts\\start-dev.ps1
```

The script starts FastAPI on `http://127.0.0.1:8000` and the production UI on
`http://127.0.0.1:3000`. For separate processes:

```powershell
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
cd frontend\\taichi-flow
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

Electron uses `TAICHI_FLOW_API_URL` for its API origin. The browser client uses
relative `/api` requests and the Vite proxy during development.

## Public domains

- Projects: `/api/projects`, `/api/projects/import`, `/api/projects/{id}`
- Inputs and revisions: `/api/projects/{id}/uploads`, `/input-revisions`
- Scenarios and queue: `/scenarios`, `/queue`, `/queue/order`
- Runs and terminal: `/api/projects/{id}/simulations/{run_id}`
- Results and exports: `/results/{run_id}`, `/exports`
- Realtime: `/ws/simulations/{run_id}` and `/ws/projects/{id}/queue`
- System: `/api/health`, `/api/info`, `/api/system/metrics`,
  `/api/parameters/catalog`

Errors use `{code, message, details, request_id}`. The removed project-list,
root-upload, singular-simulation, old-result, and old WebSocket paths are not
served or redirected.

## Verification

Run each command separately from the repository root:

```powershell
python -m pytest tests\\test_workbench_domain_api.py tests\\test_workbench_scheduler.py tests\\test_workbench_run_controls.py tests\\test_workbench_results_exports.py tests\\test_workbench_realtime.py tests\\test_parameter_catalog.py -q
cd frontend\\taichi-flow
npm run build
```

Migration and browser evidence is kept under
`artifacts/agent_runs/2026-08-02_taichi_flow_full_ui_cutover/` and the append-only
`agentlog.md`.
