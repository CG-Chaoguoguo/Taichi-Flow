"""FastAPI application factory for the Taichi-Flow workbench."""
from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import uuid4
import logging
import math
import os
import shutil
import subprocess

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.routes import cases, parameters, realtime, results_v2, settings, workbench
from api.services.runmode_capabilities import build_runmode_capabilities
from api.services.directory_picker import DirectoryPickerService
from api.services.scheduler import (
    RuntimeRunExecutor,
    RunExecutor,
    SimulationCoordinator,
    default_max_concurrent_projects,
)
from api.services.workbench_store import WorkbenchError, WorkbenchStore


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SERVICE_ID = "taichi-flow-api"
API_CONTRACT_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ID = sha256(os.path.normcase(str(PROJECT_ROOT)).encode("utf-8")).hexdigest()[:16]


def _allowed_origins() -> list[str]:
    origins = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "app://taichi-flow",
    ]
    configured = os.environ.get("TAICHI_FLOW_ALLOWED_ORIGINS", "")
    origins.extend(item.strip() for item in configured.split(",") if item.strip())
    return list(dict.fromkeys(origins))

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


class DirectoryLocationResponse(BaseModel):
    name: str
    path: str
    writable: bool
    kind: str = "directory"
    size: Optional[int] = None


class DirectoryListingResponse(BaseModel):
    current_path: Optional[str]
    parent_path: Optional[str]
    roots: list[DirectoryLocationResponse]
    directories: list[DirectoryLocationResponse]
    files: list[DirectoryLocationResponse] = []
    can_select: bool


def _normalize_percent(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return max(0.0, min(100.0, numeric))


def _read_cpu_percent():
    if psutil is not None:
        try:
            value = _normalize_percent(psutil.cpu_percent(interval=0.1))
            if value is not None:
                return value
        except Exception:
            logger.debug("psutil CPU metrics unavailable", exc_info=True)
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return None
    try:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                "$v=(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
                "if ($null -ne $v) { [math]::Round($v, 1) }",
            ],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
        if result.returncode == 0:
            return _normalize_percent(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        logger.debug("Windows CIM CPU metrics unavailable", exc_info=True)
    return None


def _find_nvidia_smi():
    candidates = [
        os.environ.get("NVIDIA_SMI"),
        shutil.which("nvidia-smi"),
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        r"C:\Windows\System32\nvidia-smi.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return shutil.which("nvidia-smi") or "nvidia-smi"


def _read_gpu_metrics():
    try:
        result = subprocess.run(
            [_find_nvidia_smi(), "--query-gpu=utilization.gpu,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode == 0:
            first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
            if first_line:
                parts = [part.strip() for part in first_line.split(",", 1)]
                return {
                    "gpu_percent": _normalize_percent(parts[0]),
                    "gpu_name": parts[1] if len(parts) > 1 else None,
                }
    except (OSError, subprocess.SubprocessError, ValueError):
        logger.debug("NVIDIA GPU metrics unavailable", exc_info=True)
    return {"gpu_percent": None, "gpu_name": None}


def _error_payload(request: Request, code: str, message: str, details=None):
    return {
        "code": code,
        "message": message,
        "details": details,
        "request_id": getattr(request.state, "request_id", None),
    }


def create_app(
    *,
    state_dir: Optional[Path] = None,
    scheduler_enabled: bool = True,
    run_executor: Optional[RunExecutor] = None,
    scheduler_poll_interval: float = 0.1,
    max_concurrent_projects: Optional[int] = None,
    directory_roots: Optional[Sequence[Path]] = None,
) -> FastAPI:
    store = WorkbenchStore(state_dir)
    directory_picker = DirectoryPickerService(directory_roots)
    executor = run_executor or RuntimeRunExecutor()
    coordinator = SimulationCoordinator(
        store,
        executor,
        max_concurrent_projects=max_concurrent_projects or default_max_concurrent_projects(),
        poll_interval=scheduler_poll_interval,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info("Starting Taichi-Flow workbench; state_dir=%s", store.state_dir)
        application.state.scheduler_enabled = scheduler_enabled
        recovered = store.recover_interrupted_runs()
        if recovered:
            logger.warning("Marked %s interrupted queue item(s) after restart", recovered)
        if scheduler_enabled:
            await coordinator.start()
        try:
            yield
        finally:
            if scheduler_enabled:
                await coordinator.stop()
            logger.info("Shutting down Taichi-Flow workbench")

    application = FastAPI(
        title="Taichi-Flow API",
        description="Persistent local scientific simulation workbench",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.workbench = store
    application.state.coordinator = coordinator
    application.state.run_executor = executor

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @application.exception_handler(WorkbenchError)
    async def workbench_error_handler(request: Request, exc: WorkbenchError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.code, exc.message, exc.details),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(request, "validation_error", "请求数据校验失败。", exc.errors()),
        )

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, "http_error", str(exc.detail)),
        )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(workbench.router, prefix="/api", tags=["workbench"])
    application.include_router(results_v2.router, prefix="/api", tags=["results", "exports"])
    application.include_router(realtime.router, tags=["realtime"])
    application.include_router(cases.router, prefix="/api/cases", tags=["cases"])
    application.include_router(parameters.router, prefix="/api/parameters", tags=["parameters"])
    application.include_router(settings.router, prefix="/api/settings", tags=["settings"])

    @application.get("/api/system/directories", tags=["system"], response_model=DirectoryListingResponse)
    async def system_directories(request: Request, path: Optional[str] = None):
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise WorkbenchError(
                "directory_picker_local_only",
                "目录选择器仅允许本机访问。",
                status_code=403,
            )
        return directory_picker.list_directories(path)

    @application.get("/")
    async def root():
        return {"message": "Taichi-Flow API", "version": "1.0.0", "docs": "/docs", "status": "running"}

    @application.get("/api/health")
    async def health_check():
        return {
            "status": "healthy",
            "service_id": SERVICE_ID,
            "api_contract_version": API_CONTRACT_VERSION,
            "checkout_id": CHECKOUT_ID,
            "active_simulations": coordinator.active_count if scheduler_enabled else 0,
            "state_dir": str(store.state_dir),
            "scheduler_enabled": scheduler_enabled,
            "max_concurrent_projects": coordinator.max_concurrent_projects,
        }

    @application.get("/api/system/metrics")
    async def system_metrics():
        gpu = _read_gpu_metrics()
        return {"cpu_percent": _read_cpu_percent(), "gpu_percent": gpu["gpu_percent"], "gpu_name": gpu["gpu_name"]}

    @application.get("/api/info")
    async def get_info():
        capabilities = build_runmode_capabilities(source_mode="service_info")
        return {
            "name": "Taichi-Flow API",
            "version": "1.0.0",
            "description": "Persistent GPU-accelerated debris-flow workbench",
            "max_concurrent_projects": int(os.environ.get("TAICHI_FLOW_MAX_CONCURRENT_PROJECTS", "2")),
            "runmode_capabilities_summary": capabilities["summary"],
            "editable_run_modes": capabilities["summary"]["switchable_keys"],
        }

    return application


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True, log_level="info")


if __name__ == "__main__":
    main()
