# Developer guide

## Local setup

Use a Python environment that contains Taichi and run commands from the
repository root. `TAICHI_FLOW_PYTHON` may point to an explicit interpreter:

```powershell
$env:TAICHI_FLOW_PYTHON = "C:\\path\\to\\python.exe"
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
cd frontend\\taichi-flow
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

`TAICHI_FLOW_STATE_DIR` selects an isolated catalog for tests. Set
`TAICHI_FLOW_MAX_CONCURRENT_PROJECTS=2` (the default) when exercising scheduler
admission. Keep the design source outside this repository read-only.

## Backend changes

- Extend `WorkbenchStore` only through transactions and explicit schema
  migrations. Do not store raster bytes in SQLite.
- Add public routes under `api/routes/workbench.py`, `results_v2.py`, or
  `realtime.py`; update the API/fixture tests with every new action.
- The local directory browser is the narrow exception in `api/app.py`: it must
  remain loopback-only, expose directories but never files, and reject UNC or
  any path outside the mounted local roots returned by the service.
- Use project-root constrained paths for every artifact and download.
- A parameter is editable only when its catalog evidence says
  `production_consumed` or `config_fallback_consumed`.
- Run lifecycle changes must preserve the queue state machine and restart
  recovery. Do not change numerical formulas or output semantics for UI work.

## Frontend changes

The production client is `frontend/taichi-flow`. Keep the reference component
structure and `data-qoder-*` attributes. API calls live in
`src/api/taichiFlowAdapter.ts`; domain state lives in
`src/stores/taichiFlowStore.ts`. Components must render loading, empty, error,
and disconnected states from real responses rather than mock records.
Project-scoped navigation must remain natively disabled until an active project
exists, and every project route must also be wrapped by `ProjectRouteGuard`.
Desktop-only directory access is exposed through
`taichi-flow:select-directory`; renderer code receives only the typed preload
bridge and never Electron or Node primitives.

Run:

```powershell
python -m pytest tests\\test_workbench_domain_api.py tests\\test_workbench_scheduler.py tests\\test_workbench_run_controls.py tests\\test_workbench_results_exports.py tests\\test_workbench_realtime.py tests\\test_parameter_catalog.py -q
cd frontend\\taichi-flow
npm test
npm run build
node --test desktop\\directoryPicker.test.cjs
```

Append each result to `agentlog.md` with command, artifact path, compared case,
metric/diff evidence, production decision, cleanup status, and next action.
