# Taichi-Flow API reference

All browser calls use a relative `/api` origin. The route list below mirrors
the FastAPI application; the canonical wire schemas remain available from
`/openapi.json`. Errors use `{code, message, details, request_id}` where
provided by the service. Validation errors are HTTP 422 and immutable-state
conflicts are HTTP 409.

## Projects, assets, and inputs

```text
GET    /api/projects
POST   /api/projects
POST   /api/projects/import
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
GET    /api/projects/{project_id}/uploads
POST   /api/projects/{project_id}/uploads/{family}
POST   /api/projects/{project_id}/uploads/from-path
DELETE /api/projects/{project_id}/uploads/{upload_id}
GET    /api/projects/{project_id}/uploads/{upload_id}/preview
GET    /api/projects/{project_id}/assets
POST   /api/projects/{project_id}/assets/{family}
POST   /api/projects/{project_id}/assets/delete-preview
POST   /api/projects/{project_id}/assets/batch-delete
DELETE /api/projects/{project_id}/assets/{asset_id}
POST   /api/projects/{project_id}/assets/{asset_id}/archive
GET    /api/projects/{project_id}/assets/{asset_id}/raster-profile
POST   /api/projects/{project_id}/assets/{asset_id}/raster/prepare
GET    /api/projects/{project_id}/assets/{asset_id}/raster/cog
POST   /api/projects/{project_id}/raster/identify
GET    /api/projects/{project_id}/map-state
PATCH  /api/projects/{project_id}/map-state
GET    /api/projects/{project_id}/input-revisions
POST   /api/projects/{project_id}/input-revisions
GET    /api/projects/{project_id}/input-revisions/{revision_id}
POST   /api/projects/{project_id}/input-revisions/{revision_id}/validate
GET    /api/projects/{project_id}/input-revisions/{revision_id}/config-interface
POST   /api/cases/parse-config
POST   /api/cases/imports/preview
POST   /api/cases/imports/commit
```

Uploads are staged and validated before publication into an immutable input
revision. The case endpoints parse or import an original-EDDA directory; they
do not silently alter the source directory.

## Scenarios, queue, and simulations

```text
GET    /api/projects/{project_id}/parameter-templates
POST   /api/projects/{project_id}/parameter-imports/preview
POST   /api/projects/{project_id}/parameter-imports/apply
POST   /api/projects/{project_id}/migrations/legacy/preview
POST   /api/projects/{project_id}/migrations/legacy/commit
GET    /api/projects/{project_id}/scenarios
POST   /api/projects/{project_id}/scenarios
GET    /api/projects/{project_id}/scenarios/{scenario_id}
GET    /api/projects/{project_id}/scenarios/{scenario_id}/configuration
PATCH  /api/projects/{project_id}/scenarios/{scenario_id}
POST   /api/projects/{project_id}/scenarios/{scenario_id}/duplicate
POST   /api/projects/{project_id}/scenarios/{scenario_id}/archive
DELETE /api/projects/{project_id}/scenarios/{scenario_id}
GET    /api/projects/{project_id}/queue
POST   /api/projects/{project_id}/queue
PATCH  /api/projects/{project_id}/queue/order
DELETE /api/projects/{project_id}/queue/{queue_item_id}
POST   /api/projects/{project_id}/queue/{queue_item_id}/retry
POST   /api/projects/{project_id}/queue/{queue_item_id}/stop
GET    /api/projects/{project_id}/simulations
GET    /api/projects/{project_id}/simulations/{simulation_id}
GET    /api/projects/{project_id}/simulations/{simulation_id}/terminal
GET    /api/simulations/{simulation_id}
POST   /api/simulations/{simulation_id}/stop
```

The singular simulation routes are compatibility aliases for existing clients;
they remain mounted and are not the primary project-scoped workflow.

## Results, exports, settings, realtime, and system

```text
GET    /api/projects/{project_id}/results/{simulation_id}
GET    /api/projects/{project_id}/results/{simulation_id}/metadata
GET    /api/projects/{project_id}/results/{simulation_id}/files/{filename}
GET    /api/projects/{project_id}/results/{simulation_id}/download.zip
DELETE /api/projects/{project_id}/results/{simulation_id}
GET    /api/projects/{project_id}/exports
POST   /api/projects/{project_id}/exports
GET    /api/projects/{project_id}/exports/{export_id}
GET    /api/projects/{project_id}/exports/{export_id}/download
GET    /api/parameters/catalog
GET    /api/settings/compute-gates
PUT    /api/settings/compute-gates
GET    /api/health
GET    /api/info
GET    /api/system/metrics
GET    /api/system/directories?path={absolute_local_path}
WS     /ws/simulations/{run_id}
WS     /ws/projects/{project_id}/queue
```

`GET /api/system/directories` is loopback-only and returns directories, never
files or file contents. It rejects UNC/network locations. Electron uses the
native directory dialog; the browser route is limited to mounted local roots.

The backend exposes WebSocket snapshots, while the current React client uses
REST polling as its operational fallback. A future WebSocket client must keep
the same polling fallback and state contract.
