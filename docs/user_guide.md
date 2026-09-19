# Taichi-Flow user guide

1. Start `scripts\start-dev.ps1` and use the Electron workbench. If you chose
   `-Browser` or `-ServicesOnly`, open `http://127.0.0.1:3000/projects` instead.
2. Create or import a project. Enter the required root path directly or choose
   **选择目录**. Electron opens the native system directory window; the browser
   opens an in-app browser for mounted local disks. The chosen value is filled
   into the form and is not submitted until you click **创建** or **打开并导入**.
   UNC/network shares are intentionally excluded. The project root and catalog
   record are retained across service restarts.
3. Upload DEM, rainfall, soil, boundary, text configuration, or native input
   families from the project workspace. Uploads are hashed and become part of
   an immutable input revision only after validation.
4. Create a scenario from a published revision. Edit only evidence-gated
   parameters; completed or archived scenarios must be duplicated first.
5. Add the scenario to the queue. The queue is FIFO within a project and may
   run two different projects concurrently by default.
6. Follow terminal snapshots in the calculation page. The current client uses
   REST polling; the backend also exposes WebSocket snapshot routes for a
   future realtime client. Stop, cancel, or retry actions are explicit and
   remain visible after a service restart.
7. Browse result families and download a single file or a project-root-safe
   ZIP. Create an export to receive effective parameters plus a checksummed
   manifest.

The settings page changes local theme/accessibility preferences and exposes the
global compute-gate defaults through `GET/PUT /api/settings/compute-gates`.
These gates control which evidence-backed runtime options are available to new
runs; they are not a replacement for scenario parameters. Server metrics remain
read-only.

Before a project is active, **方案、计算、队列、导出** are disabled and omitted
from keyboard focus; their tooltip explains that a project must be created or
opened first. **项目** remains available, while **设置** is fixed at the bottom
of the sidebar immediately above the collapse/expand control.
