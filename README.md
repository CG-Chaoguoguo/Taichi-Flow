# Taichi-Flow

[English](README.md) | [简体中文](README.zh-CN.md)

Taichi-Flow is a local research workbench for terrain-driven flow and
debris-flow simulation. It combines a React/Vite desktop-oriented interface,
a FastAPI domain service, and Taichi-based numerical execution. The workbench
keeps original EDDA text-case semantics in its internal computation path while
making projects, inputs, scenarios, runs, and outputs traceable.

## Status

Taichi-Flow is a research preview. The current public workflow is intended for
local, evidence-led model setup and execution. It does not claim numerical
equivalence with the original Fortran EDDA implementation.

The repository currently validates the Chamoli reference-case workflow on
Windows with Python 3.11, Taichi 1.7.4, and a CUDA-capable NVIDIA GPU. CPU
execution remains available through the same runtime architecture.

## What the workbench provides

| Area | Capability |
| --- | --- |
| Reference cases | Read-only preview and atomic import of an original EDDA case directory |
| Inputs | Immutable SHA-256-addressed uploads, input revisions, active-binding checks, and runtime provenance |
| Scenarios | Versioned parameter patches, frozen EDDA controls, reference-case ownership, duplication, and queueing |
| Numerical runtime | Taichi CUDA or CPU execution, preflight checks, progress, terminal state, and output manifests |
| Results | Result-family browsing, individual downloads, zip export, and metadata/audit sidecars |
| Frontend | Project workspace, map-aware input inspection, Chamoli control exposure, zone editing, and result navigation |

For imported reference cases, configuration ownership is explicit:
reference_case scenarios retain their parsed EDDA control snapshot instead of
silently inheriting global defaults intended for another case family.

## Chamoli reference-case support

The Chamoli workflow is a case-specific compatibility path, not a generic
promise that every historical EDDA feature is editable.

| Status | Chamoli behavior |
| --- | --- |
| Production path | EDDA configuration preview/import, active raster bindings, 4-zone double-layer data, trigger-slide raster, input fingerprinting, scenario controls, queueing, CUDA/CPU execution, output manifests, and result downloads |
| Runtime-consumed sidecars | inflow.txt and outflow.txt are carried into the independent project and recorded as consumed when their frozen controls are active |
| Read-only audit | Parsed original switches and numeric variants that should not be freely changed from the workbench remain visible as audit information |
| Case-specific disabled path | Chamoli sets shallow-landslide simulation off; its trigger-slide source remains independently represented, while the precomputed UNSFIN path stays disabled for that source configuration |
| Partial path | Some debris-flow/WFS behavior remains explicitly partial rather than represented as full original-EDDA equivalence |
| Not supported | Barrier simulation is unsupported; the buildings flag is retained as parsed audit metadata, not a production solver feature |

The isolated Chamoli acceptance run used a 748 x 715 grid with 41,069 valid
cells. A CUDA run to 90 seconds completed 2,090 steps, produced outputs at 45
and 90 seconds, and generated 42 result files plus a complete metadata
manifest. This proves the end-to-end workbench path; it is not a 14,400-second
full-duration acceptance or a grid-cell numerical-parity claim.

Original ASCII inputs without a declared coordinate reference system are
exported with an EPSG:4326 fallback. The native affine grid transform is
preserved, but users must provide verified CRS metadata before treating that
fallback as authoritative georeferencing.

See the tracked [Chamoli capability matrix](docs/audit/chamoli_capability_matrix.md)
for source-to-runtime coverage and known boundaries.

## Reference-case data flow

~~~text
Original EDDA case directory (read-only)
  -> preview: parse edda_in.txt, inspect active inputs, calculate fingerprint
  -> commit: copy into a separate project directory and register immutable inputs
  -> input revision + reference-case parameter template
  -> scenario: frozen controls, sparse case-local overrides, preflight
  -> queue + Taichi runtime profile (CUDA or CPU)
  -> output families, runtime-input manifest, provenance, downloads, export
~~~

The source directory is not modified during preview or import, and its source
path is not preserved as a runtime parameter.

## Quick start on Windows

### Prerequisites

- Windows 10 or 11
- Python 3.11 recommended; Taichi 1.7.4 supports Python 3.9 through 3.13
- Node.js 22.12 or newer (Electron 43.2.0 desktop requirement)
- NVIDIA CUDA hardware is recommended for accelerated execution; it is not
  required for the browser workbench itself

### Install and start

~~~powershell
git clone https://github.com/CG-Chaoguoguo/Taichi-Flow.git
cd Taichi-Flow

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Push-Location frontend\taichi-flow
npm ci
Pop-Location

.\scripts\start-dev.ps1
~~~

The managed script starts FastAPI at
[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health) and opens
the workbench in an independent Electron development window backed by Vite HMR.
It does not open an external browser by default. Use `-Browser` for the
explicit browser presentation, or `-ServicesOnly`/`-NoBrowser` for a headless
service stack whose URL is normally
[http://127.0.0.1:3000/projects](http://127.0.0.1:3000/projects).

~~~powershell
.\scripts\stop-dev.ps1
~~~

Set TAICHI_FLOW_PYTHON before startup when a specific interpreter should own the
runtime:

~~~powershell
$env:TAICHI_FLOW_PYTHON = "C:\Python311\python.exe"
.\scripts\start-dev.ps1 -NoBrowser
~~~

## Typical workflow

1. Open Projects and select Import compatible case.
2. Select an original EDDA directory containing edda_in.txt and generate the
   read-only preview.
3. Confirm active inputs, sidecars, zones, variants, and the import
   fingerprint; commit to a separate destination directory.
4. Review the imported scenario, duplicate it for an experiment if needed, and
   edit only controls exposed for that reference case.
5. Run preflight, enqueue the scenario, and select a CUDA or CPU runtime
   profile.
6. Inspect runtime provenance and download result families from the Results
   panel.

## Public API highlights

The REST service is mounted below /api. The primary entry points are:

| Endpoint | Purpose |
| --- | --- |
| POST /api/cases/imports/preview | Read and audit a compatible EDDA case without writing to its source |
| POST /api/cases/imports/commit | Atomically create an independent project from a verified preview fingerprint |
| GET /api/projects | List workbench projects |
| POST /api/projects/{project_id}/scenarios | Create a scenario with parameter patches and optional control_overrides |
| PATCH /api/projects/{project_id}/scenarios/{scenario_id} | Update a scenario using optimistic versioning |
| GET /api/projects/{project_id}/results/{simulation_id} | Browse simulation result metadata and files |
| GET /api/health | Check service identity and readiness |

The [API reference](docs/api_reference.md) and
[architecture guide](docs/architecture.md) describe the wider project,
revision, queue, simulation, results, export, and WebSocket contracts.

## Repository layout

~~~text
api/                         FastAPI domain service, case import, queue, and runtime coordination
edda/                        Internal EDDA-compatible numerical implementation
frontend/taichi-flow/        React/Vite workbench and Electron integration surface
docs/                        Architecture, API, user, developer, and audit documentation
examples/                    Example configuration material
scripts/                     Managed local development helpers
tests/                       Regression and domain tests
~~~

## Verification for contributors

Run commands from the repository root. Use a writable, isolated state
directory when exercising tests that construct the FastAPI application:

~~~powershell
$env:TAICHI_FLOW_STATE_DIR = "$PWD\.runtime\pytest-local"
python -m pytest tests\test_workbench_domain_api.py tests\test_workbench_scheduler.py tests\test_workbench_run_controls.py -q

Push-Location frontend\taichi-flow
npm test
npm run build
Pop-Location
~~~

For a Chamoli-focused analysis, consult the
[capability matrix](docs/audit/chamoli_capability_matrix.md), then verify the
same case through the import, preflight, queue, and result workflow.

## Documentation

- [User guide](docs/user_guide.md)
- [Developer guide](docs/developer_guide.md)
- [Installation guide](INSTALL.md)
- [Architecture](docs/architecture.md)
- [API reference](docs/api_reference.md)
- [Chamoli capability matrix](docs/audit/chamoli_capability_matrix.md)

## Scientific boundary

Taichi-Flow preserves and audits selected original EDDA semantics, but
functional availability is not proof of scientific equivalence. Do not infer
Fortran parity from parser coverage, a completed queue item, aligned output
arrays, or a successful GPU run. Reproducible comparison requires a matching
case, duration, output cadence, reference outputs, and explicit residual
analysis.
