# Taichi-Flow API reference

All browser calls use a relative `/api` origin. Errors are returned as
`{code, message, details, request_id}`; validation uses HTTP 422 and immutable
state conflicts use HTTP 409.

## Projects and inputs

```text
GET    /api/projects
POST   /api/projects
POST   /api/projects/import
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
GET    /api/projects/{project_id}/uploads
POST   /api/projects/{project_id}/uploads/{family}
GET    /api/projects/{project_id}/input-revisions
POST   /api/projects/{project_id}/input-revisions
GET    /api/projects/{project_id}/input-revisions/{revision_id}
POST   /api/projects/{project_id}/input-revisions/{revision_id}/validate
```

## Scenarios, queue, and runs

```text
GET/POST /api/projects/{project_id}/scenarios
GET/PATCH/DELETE /api/projects/{project_id}/scenarios/{scenario_id}
POST /api/projects/{project_id}/scenarios/{scenario_id}/duplicate
POST /api/projects/{project_id}/scenarios/{scenario_id}/archive
GET/POST /api/projects/{project_id}/queue
PATCH /api/projects/{project_id}/queue/order
DELETE /api/projects/{project_id}/queue/{queue_item_id}
POST /api/projects/{project_id}/queue/{queue_item_id}/retry
POST /api/projects/{project_id}/queue/{queue_item_id}/stop
GET /api/projects/{project_id}/simulations
GET /api/projects/{project_id}/simulations/{run_id}
GET /api/projects/{project_id}/simulations/{run_id}/terminal
POST /api/projects/{project_id}/simulations/{run_id}/stop
```

## Results, exports, realtime, and system

```text
GET /api/projects/{project_id}/results/{run_id}
GET /api/projects/{project_id}/results/{run_id}/metadata
GET /api/projects/{project_id}/results/{run_id}/files/{filename}
GET /api/projects/{project_id}/results/{run_id}/download.zip
DELETE /api/projects/{project_id}/results/{run_id}
GET/POST /api/projects/{project_id}/exports
GET /api/projects/{project_id}/exports/{export_id}
GET /api/projects/{project_id}/exports/{export_id}/download
WS /ws/simulations/{run_id}
WS /ws/projects/{project_id}/queue
GET /api/health
GET /api/info
GET /api/system/metrics
GET /api/system/directories?path={absolute_local_path}
GET /api/parameters/catalog
```

`GET /api/system/directories` is a loopback-only browser directory browser.
Without `path` it returns mounted local roots; with an absolute path it returns
only child directories plus `current_path`, `parent_path`, `roots`, and
`can_select`. It never returns files or file contents, and rejects UNC/network
locations. Electron uses the native directory dialog instead of this endpoint.

The old project aliases, root upload routes, singular simulation routes, and
old WebSocket path are absent rather than redirected.
