# Taichi-Flow architecture

Taichi-Flow has three runtime boundaries:

1. **React/Vite workbench** — `frontend/taichi-flow` contains the reference
   layout and calls only the nested Taichi-Flow API. Zustand persists theme,
   recent project IDs, and the active project ID; domain records never live in
   browser storage.
2. **FastAPI domain service** — `api/app.py` mounts project, input revision,
   scenario, queue, run, result, export, system, and realtime routes. The
   `WorkbenchStore` owns the catalog and per-project SQLite state.
3. **Numerical runtime** — `api/services/scheduler.py` admits one run per
   project, up to `TAICHI_FLOW_MAX_CONCURRENT_PROJECTS` projects globally, and
   hands a validated scenario snapshot to the existing Taichi runtime.

## State and lifecycle

The global catalog defaults to `%LOCALAPPDATA%\Taichi-Flow`. A project has a
`.taichi-flow/state.sqlite3` database in WAL mode and immutable content-addressed
blobs under its project root. Input uploads are staged, hashed, validated, and
published into an `InputRevision`. A scenario references exactly one revision
and stores both its parameter patch and server-computed effective snapshot.

Scenarios become immutable after completion/archive or any run history. Copying
is the supported edit path. Adding a scenario creates a persisted `waiting`
item; an explicit queue-start transaction releases the current waiting batch as
`queued`. New items added during a run remain waiting for the next batch.
Service restart marks `starting`, `running`, and `stopping` work as
`interrupted`; the user must retry.

The scheduler keeps project FIFO and runtime configuration signatures separate.
It serializes runtime initialization/reset/disposal and never mixes incompatible
Taichi initialization signatures in one active runtime set.

## API boundaries

| Domain | Primary paths |
| --- | --- |
| Projects | `/api/projects`, `/api/projects/import`, `/api/projects/{id}` |
| Inputs | `/api/projects/{id}/uploads/{family}`, `/input-revisions` |
| Scenarios | `/api/projects/{id}/scenarios` and duplicate/archive actions |
| Queue | `/api/projects/{id}/queue`, `/queue/start`, `/queue/order`, batch delete, stop/retry |
| Runs | `/api/projects/{id}/simulations`, run detail/stop/terminal |
| Results | `/api/projects/{id}/results/{run_id}` and safe file downloads |
| Exports | `/api/projects/{id}/exports` and asynchronous download |
| Realtime | `/ws/simulations/{run_id}`, `/ws/projects/{id}/queue` |
| System | `/api/health`, `/api/info`, `/api/system/metrics`, parameter catalog |

Errors have the shape `{code, message, details, request_id}`. Old root upload,
singular simulation, project alias, and old WebSocket routes are intentionally
not mounted.

## Numerical boundary

This cutover does not alter formulas, source-term ordering, dry/wet thresholds,
eight-direction ordering, timestep rules, or output semantics in `edda/`. The
frontend exposes only parameter catalog entries with runtime-consumer evidence;
parsed-only and mapped-only fields remain read-only metadata.
