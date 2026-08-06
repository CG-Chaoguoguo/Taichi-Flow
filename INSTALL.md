# Taichi-Flow installation

Taichi-Flow combines a Python/Taichi computation service, a FastAPI workbench
API, and a React/Vite frontend. Python 3.11 and Node.js 20.19 or newer are the
recommended local toolchain on Windows.

## Clone

```powershell
git clone https://github.com/CG-Chaoguoguo/Taichi-Flow.git
cd Taichi-Flow
```

## Python environment

Create and activate a project-local virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For GDAL, Rasterio, and other geospatial packages on Windows, a Conda
environment is usually more reliable:

```powershell
conda env create -f environment.yml
conda activate taichi-flow
```

CUDA is optional. Without a compatible NVIDIA runtime, use a CPU backend for
development and unit tests.

## Frontend dependencies

```powershell
Set-Location frontend\taichi-flow
npm ci
Set-Location ..\..
```

## Start the browser workbench

From the repository root:

```powershell
.\scripts\start-dev.ps1
```

The API listens on `http://127.0.0.1:8000` and Vite on
`http://127.0.0.1:3000`. Stop only the processes owned by this checkout with:

```powershell
.\scripts\stop-dev.ps1
```

## Start the Electron development workbench

The desktop launcher and all of its supporting PowerShell modules are kept in
`scripts\desktop-dev`:

```powershell
.\scripts\desktop-dev\Start-Taichi-Flow-Desktop-Dev.bat
.\scripts\desktop-dev\Start-Taichi-Flow-Desktop-Dev.bat preview
```

See [scripts/desktop-dev/README.md](scripts/desktop-dev/README.md) for launcher
contracts, recovery, smoke testing, and future packaging boundaries.

## Verification

Run commands separately from the repository root:

```powershell
python -m pytest tests\test_workbench_domain_api.py tests\test_workbench_scheduler.py tests\test_workbench_run_controls.py tests\test_workbench_results_exports.py tests\test_workbench_realtime.py tests\test_parameter_catalog.py -q

Set-Location frontend\taichi-flow
npm test
npm run test:desktop
npm run build
```

Generated outputs, uploads, runtime databases, build products, browser
screenshots, and diagnostic logs are local-only and excluded by `.gitignore`.
Maintained test source and fixtures under `tests/fixtures/` remain versioned.

## Support

- Repository: <https://github.com/CG-Chaoguoguo/Taichi-Flow>
- Issues: <https://github.com/CG-Chaoguoguo/Taichi-Flow/issues>
- Documentation: [docs/](docs/)
