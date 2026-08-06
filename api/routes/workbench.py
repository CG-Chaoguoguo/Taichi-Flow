"""Public Taichi-Flow workbench REST endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, File, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.services.raster_preview import build_raster_preview
from api.services.raster_engine import RasterEngineError, identify_raster, prepare_raster
from api.services.workbench_store import WorkbenchError


router = APIRouter()


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)
    root_path: str = Field(..., min_length=1)
    description: str = ""


class ProjectImport(BaseModel):
    root_path: str = Field(..., min_length=1)
    name: Optional[str] = None
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None


class InputBindingPayload(BaseModel):
    binding_key: str = Field(..., min_length=1)
    asset_id: str = Field(..., min_length=1)
    family: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    period_id: Optional[str] = None
    ordinal: Optional[int] = Field(None, ge=1)
    active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InputRevisionCreate(BaseModel):
    version_tag: Optional[str] = None
    upload_ids: list[str] = Field(default_factory=list)
    parent_revision_id: Optional[str] = None
    bindings: Optional[list[InputBindingPayload]] = None


class UploadFromPath(BaseModel):
    path: str = Field(..., min_length=1)
    family: str = Field(..., min_length=1)


class AssetDeleteRequest(BaseModel):
    asset_ids: list[str] = Field(..., min_length=1)


class RasterIdentifyCoordinate(BaseModel):
    x: float
    y: float


class RasterIdentifyRequest(BaseModel):
    coordinate: RasterIdentifyCoordinate
    asset_ids: list[str] = Field(..., min_length=1)
    active_asset_id: Optional[str] = None
    neighborhood_size: Literal[3, 5] = 3


class MapStateUpdate(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    expected_version: Optional[int] = Field(None, ge=1)


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1)
    input_revision_id: Optional[str] = None
    base_scenario_id: Optional[str] = None
    parameter_patch: Dict[str, Any] = Field(default_factory=dict)
    parameter_template_id: Optional[str] = None


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    parameter_patch: Optional[Dict[str, Any]] = None
    input_revision_id: Optional[str] = None
    input_bindings: Optional[list[InputBindingPayload]] = None
    parameter_template_id: Optional[str] = None
    expected_version: Optional[int] = Field(None, ge=1)


class LegacyMigrationPreviewRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1)


class LegacyMigrationCommitRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1)
    expected_version: int = Field(..., ge=1)


class QueueCreate(BaseModel):
    scenario_id: str = Field(..., min_length=1)


class QueueReorder(BaseModel):
    item_id: str = Field(..., min_length=1)
    new_position: int = Field(..., ge=1)


class QueueDeleteRequest(BaseModel):
    queue_item_ids: list[str] = Field(..., min_length=1)


@router.get("/projects")
async def list_projects(request: Request):
    projects = request.app.state.workbench.list_projects()
    return {"projects": projects, "count": len(projects)}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, payload: ProjectCreate):
    return request.app.state.workbench.create_or_open_project(
        name=payload.name,
        root_path=payload.root_path,
        description=payload.description,
    )


@router.post("/projects/import", status_code=status.HTTP_201_CREATED)
async def import_project(request: Request, payload: ProjectImport):
    """Register an existing directory without reading legacy manifests at runtime."""
    root = payload.root_path.strip()
    return request.app.state.workbench.create_or_open_project(
        name=(payload.name or "").strip() or root.replace("\\", "/").rstrip("/").split("/")[-1],
        root_path=root,
        description=payload.description,
    )


@router.get("/projects/{project_id}")
async def get_project(request: Request, project_id: str):
    return request.app.state.workbench.get_project(project_id)


@router.patch("/projects/{project_id}")
async def update_project(request: Request, project_id: str, payload: ProjectUpdate):
    return request.app.state.workbench.update_project(
        project_id,
        name=payload.name,
        description=payload.description,
    )


@router.get("/projects/{project_id}/uploads")
async def list_uploads(request: Request, project_id: str):
    return {"uploads": request.app.state.workbench.list_uploads(project_id)}


@router.get("/projects/{project_id}/assets")
async def list_assets(request: Request, project_id: str):
    assets = request.app.state.workbench.list_uploads(project_id)
    return {"assets": assets, "count": len(assets)}


@router.post("/projects/{project_id}/assets/delete-preview")
async def preview_asset_delete(request: Request, project_id: str, payload: AssetDeleteRequest):
    return request.app.state.workbench.preview_asset_delete(project_id, payload.asset_ids)


@router.post("/projects/{project_id}/assets/batch-delete")
async def batch_delete_assets(request: Request, project_id: str, payload: AssetDeleteRequest):
    return request.app.state.workbench.batch_delete_assets(project_id, payload.asset_ids)


@router.get("/projects/{project_id}/parameter-templates")
async def list_parameter_templates(request: Request, project_id: str):
    templates = request.app.state.workbench.list_parameter_templates(project_id)
    return {"templates": templates, "count": len(templates)}


@router.post("/projects/{project_id}/parameter-imports/preview")
async def preview_parameter_import(
    request: Request,
    project_id: str,
    scenario_id: str = Query(..., min_length=1),
    file: UploadFile = File(...),
):
    await file.seek(0)
    return await run_in_threadpool(
        request.app.state.workbench.preview_parameter_import,
        project_id,
        scenario_id,
        filename=file.filename or "edda_in.txt",
        stream=file.file,
    )


@router.post("/projects/{project_id}/parameter-imports/apply")
async def apply_parameter_import(
    request: Request,
    project_id: str,
    scenario_id: str = Query(..., min_length=1),
    expected_version: int = Query(..., ge=1),
    file: UploadFile = File(...),
):
    await file.seek(0)
    return await run_in_threadpool(
        request.app.state.workbench.apply_parameter_import,
        project_id,
        scenario_id,
        expected_version=expected_version,
        filename=file.filename or "edda_in.txt",
        stream=file.file,
    )


@router.post("/projects/{project_id}/migrations/legacy/preview")
async def preview_legacy_migration(
    request: Request,
    project_id: str,
    payload: LegacyMigrationPreviewRequest,
):
    return await run_in_threadpool(
        request.app.state.workbench.preview_legacy_migration,
        project_id,
        payload.scenario_id,
    )


@router.post("/projects/{project_id}/migrations/legacy/commit")
async def commit_legacy_migration(
    request: Request,
    project_id: str,
    payload: LegacyMigrationCommitRequest,
):
    return await run_in_threadpool(
        request.app.state.workbench.commit_legacy_migration,
        project_id,
        payload.scenario_id,
        expected_version=payload.expected_version,
    )


@router.post("/projects/{project_id}/assets/{family}", status_code=status.HTTP_201_CREATED)
async def upload_assets(
    request: Request,
    project_id: str,
    family: str,
    files: list[UploadFile] = File(...),
):
    assets = []
    for file in files:
        await file.seek(0)
        assets.append(
            await run_in_threadpool(
                request.app.state.workbench.ingest_upload,
                project_id,
                family=family,
                filename=file.filename or "",
                stream=file.file,
                media_type=file.content_type,
            )
        )
    return {"assets": assets, "count": len(assets)}


@router.delete("/projects/{project_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(request: Request, project_id: str, asset_id: str):
    request.app.state.workbench.delete_asset(project_id, asset_id)
    return None


@router.post("/projects/{project_id}/assets/{asset_id}/archive")
async def archive_asset(request: Request, project_id: str, asset_id: str):
    return request.app.state.workbench.archive_asset(project_id, asset_id)


@router.post("/projects/{project_id}/uploads/from-path", status_code=status.HTTP_201_CREATED)
async def upload_input_from_path(request: Request, project_id: str, payload: UploadFromPath):
    return await run_in_threadpool(
        request.app.state.workbench.ingest_upload_from_path,
        project_id,
        family=payload.family,
        path=payload.path,
    )


@router.post("/projects/{project_id}/uploads/{family}", status_code=status.HTTP_201_CREATED)
async def upload_input(
    request: Request,
    project_id: str,
    family: str,
    file: UploadFile = File(...),
):
    await file.seek(0)
    return await run_in_threadpool(
        request.app.state.workbench.ingest_upload,
        project_id,
        family=family,
        filename=file.filename or "",
        stream=file.file,
        media_type=file.content_type,
    )


@router.delete("/projects/{project_id}/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(request: Request, project_id: str, upload_id: str):
    request.app.state.workbench.delete_upload(project_id, upload_id)
    return None


@router.get("/projects/{project_id}/uploads/{upload_id}/preview")
async def preview_upload(
    request: Request,
    project_id: str,
    upload_id: str,
    mode: Literal["downsample", "full"] = Query(default="downsample"),
    max_size: int = Query(default=512, ge=64, le=4096),
):
    workbench = request.app.state.workbench
    blob_path = workbench.get_upload_blob_path(project_id, upload_id)

    def _build():
        return build_raster_preview(blob_path, mode=mode, max_size=max_size)

    try:
        result = await run_in_threadpool(_build)
    except FileNotFoundError as exc:
        raise WorkbenchError("upload_blob_missing", str(exc), status_code=404) from exc
    except ValueError as exc:
        raise WorkbenchError("preview_unsupported", str(exc), status_code=422) from exc
    except Exception as exc:  # noqa: BLE001 — surface loader failures cleanly
        raise WorkbenchError("preview_failed", f"无法生成栅格预览：{exc}", status_code=422) from exc

    xmin, ymin, xmax, ymax = result.bounds
    headers = {
        "X-Raster-Width": str(result.width),
        "X-Raster-Height": str(result.height),
        "X-Raster-Bounds": f"{xmin},{ymin},{xmax},{ymax}",
        "X-Value-Min": str(result.value_min),
        "X-Value-Max": str(result.value_max),
        "X-Preview-Mode": result.mode,
        "Cache-Control": "private, max-age=60",
    }
    if result.nodata is not None:
        headers["X-Nodata"] = str(result.nodata)
    if result.capped:
        headers["X-Preview-Capped"] = "true"
    return Response(content=result.png_bytes, media_type="image/png", headers=headers)


def _raster_profile_payload(project_id: str, asset_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(profile)
    payload["asset_id"] = asset_id
    payload["profile_url"] = f"/api/projects/{project_id}/assets/{asset_id}/raster-profile"
    cache_file = Path(str(payload.get("cache_path"))).resolve() if payload.get("cache_path") else None
    if payload.get("status") == "ready" and cache_file is not None and cache_file.is_file():
        payload["cog_url"] = f"/api/projects/{project_id}/assets/{asset_id}/raster/cog"
    else:
        payload["cog_url"] = None
    return payload


@router.get("/projects/{project_id}/assets/{asset_id}/raster-profile")
async def get_raster_profile(request: Request, project_id: str, asset_id: str):
    store = request.app.state.workbench
    context = store.get_raster_asset_context(project_id, asset_id)
    record = store.get_raster_profile_record(project_id, asset_id)
    if record:
        profile = dict(record.get("profile") or {})
        profile["status"] = str(record.get("status") or profile.get("status") or "pending")
        if record.get("error"):
            profile["error"] = str(record["error"])
        if record.get("cache_path"):
            profile["cache_path"] = str(record["cache_path"])
    else:
        profile = {
            "status": "pending",
            "profile_version": "1",
            "source_sha256": context["sha256"],
            "family": context["family"],
            "message": "等待建立栅格元数据档案。",
        }
    payload = _raster_profile_payload(project_id, asset_id, profile)
    payload["name"] = context["name"]
    payload["sha256"] = context["sha256"]
    return payload


@router.post("/projects/{project_id}/assets/{asset_id}/raster/prepare")
async def prepare_raster_asset(request: Request, project_id: str, asset_id: str):
    store = request.app.state.workbench
    context = store.get_raster_asset_context(project_id, asset_id)

    def _prepare() -> Dict[str, Any]:
        profile, cache = prepare_raster(
            context["source_path"],
            context["database"].state_dir,
            sha256=str(context["sha256"]),
            family=str(context["family"]),
        )
        saved = store.save_raster_profile(project_id, asset_id, profile, cache_path=cache)
        saved["name"] = context["name"]
        saved["sha256"] = context["sha256"]
        return _raster_profile_payload(project_id, asset_id, saved)

    try:
        return await run_in_threadpool(_prepare)
    except RasterEngineError as exc:
        error_profile = {
            "status": "error",
            "profile_version": "1",
            "source_sha256": context["sha256"],
            "family": context["family"],
            "error": exc.message,
        }
        store.save_raster_profile(project_id, asset_id, error_profile, error=exc.message)
        raise WorkbenchError(exc.code, exc.message, status_code=422, details=exc.details) from exc
    except FileNotFoundError as exc:
        raise WorkbenchError("upload_blob_missing", str(exc), status_code=404) from exc


def _file_chunks(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as source:
        source.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = source.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _range_response(path: Path, *, etag: str, range_header: Optional[str]) -> Response:
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Cache-Control": "private, max-age=3600",
        "Content-Type": "image/tiff",
    }
    if not range_header:
        headers["Content-Length"] = str(size)
        return StreamingResponse(_file_chunks(path, 0, max(0, size - 1)), status_code=200, headers=headers, media_type="image/tiff")
    if not range_header.startswith("bytes=") or "," in range_header:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    raw = range_header.removeprefix("bytes=").strip()
    start_text, _, end_text = raw.partition("-")
    try:
        if not start_text:
            suffix = int(end_text)
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if size <= 0 or start < 0 or start >= size or end < start:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    end = min(end, size - 1)
    headers.update({
        "Content-Length": str(end - start + 1),
        "Content-Range": f"bytes {start}-{end}/{size}",
    })
    return StreamingResponse(_file_chunks(path, start, end), status_code=206, headers=headers, media_type="image/tiff")


@router.get("/projects/{project_id}/assets/{asset_id}/raster/cog")
async def get_raster_cog(request: Request, project_id: str, asset_id: str):
    store = request.app.state.workbench
    record = store.get_raster_profile_record(project_id, asset_id)
    if not record or str(record.get("status")) != "ready" or not record.get("cache_path"):
        raise WorkbenchError(
            "raster_not_ready",
            "栅格浏览缓存尚未准备完成，请先执行 prepare。",
            status_code=409,
        )
    path = Path(str(record["cache_path"])).resolve()
    if not path.is_file():
        raise WorkbenchError("raster_cache_missing", "栅格浏览缓存不存在，请重新准备。", status_code=409)
    context = store.get_raster_asset_context(project_id, asset_id)
    return _range_response(
        path,
        etag=f'"{context["sha256"]}-{record.get("profile_version", "1")}"',
        range_header=request.headers.get("range"),
    )


@router.post("/projects/{project_id}/raster/identify")
async def identify_rasters(request: Request, project_id: str, payload: RasterIdentifyRequest):
    store = request.app.state.workbench
    asset_ids = list(dict.fromkeys(str(item) for item in payload.asset_ids if str(item).strip()))
    if not asset_ids:
        raise WorkbenchError("asset_ids_required", "至少选择一个可识别图层。", status_code=422)

    def _identify() -> list[Dict[str, Any]]:
        layers: list[Dict[str, Any]] = []
        for asset_id in asset_ids:
            context = store.get_raster_asset_context(project_id, asset_id)
            result = identify_raster(
                context["source_path"],
                sha256=str(context["sha256"]),
                family=str(context["family"]),
                x=payload.coordinate.x,
                y=payload.coordinate.y,
                neighborhood_size=payload.neighborhood_size if asset_id == payload.active_asset_id else 0,
            )
            result["asset_id"] = asset_id
            result["name"] = context["name"]
            result["family"] = context["family"]
            layers.append(result)
        return layers

    try:
        layers = await run_in_threadpool(_identify)
        return {
            "coordinate": {"x": payload.coordinate.x, "y": payload.coordinate.y},
            "active_asset_id": payload.active_asset_id,
            "layers": layers,
        }
    except RasterEngineError as exc:
        raise WorkbenchError(exc.code, exc.message, status_code=422, details=exc.details) from exc


@router.get("/projects/{project_id}/map-state")
async def get_project_map_state(request: Request, project_id: str):
    return request.app.state.workbench.get_map_state(project_id)


@router.patch("/projects/{project_id}/map-state")
async def update_project_map_state(request: Request, project_id: str, payload: MapStateUpdate):
    return request.app.state.workbench.update_map_state(
        project_id,
        payload.state,
        expected_version=payload.expected_version,
    )


@router.get("/projects/{project_id}/input-revisions")
async def list_input_revisions(request: Request, project_id: str):
    revisions = request.app.state.workbench.list_input_revisions(project_id)
    return {"revisions": revisions, "count": len(revisions)}


@router.post("/projects/{project_id}/input-revisions", status_code=status.HTTP_201_CREATED)
async def create_input_revision(request: Request, project_id: str, payload: InputRevisionCreate):
    return request.app.state.workbench.create_input_revision(
        project_id,
        version_tag=payload.version_tag,
        upload_ids=payload.upload_ids,
        parent_revision_id=payload.parent_revision_id,
        bindings=[item.model_dump() for item in payload.bindings] if payload.bindings is not None else None,
    )


@router.get("/projects/{project_id}/input-revisions/{revision_id}")
async def get_input_revision(request: Request, project_id: str, revision_id: str):
    revision = request.app.state.workbench.get_input_revision(project_id, revision_id)
    revision["files"] = request.app.state.workbench.input_revision_files(project_id, revision_id)
    revision["bindings"] = request.app.state.workbench.input_revision_bindings(project_id, revision_id)
    return revision


@router.post("/projects/{project_id}/input-revisions/{revision_id}/validate")
async def validate_input_revision(request: Request, project_id: str, revision_id: str):
    return request.app.state.workbench.validate_input_revision(project_id, revision_id)


@router.get("/projects/{project_id}/input-revisions/{revision_id}/config-interface")
async def get_config_interface(request: Request, project_id: str, revision_id: str):
    """Parse revision config (edda_in) into a frontend-safe case config interface."""
    return await run_in_threadpool(
        request.app.state.workbench.get_config_interface,
        project_id,
        revision_id,
    )


@router.get("/projects/{project_id}/scenarios")
async def list_scenarios(request: Request, project_id: str):
    scenarios = request.app.state.workbench.list_scenarios(project_id)
    return {"scenarios": scenarios, "count": len(scenarios)}


@router.post("/projects/{project_id}/scenarios", status_code=status.HTTP_201_CREATED)
async def create_scenario(request: Request, project_id: str, payload: ScenarioCreate):
    return request.app.state.workbench.create_scenario(
        project_id,
        name=payload.name,
        input_revision_id=payload.input_revision_id,
        base_scenario_id=payload.base_scenario_id,
        parameter_patch=payload.parameter_patch,
        parameter_template_id=payload.parameter_template_id,
    )


@router.get("/projects/{project_id}/scenarios/{scenario_id}")
async def get_scenario(request: Request, project_id: str, scenario_id: str):
    return request.app.state.workbench._public_scenario(
        project_id,
        request.app.state.workbench._scenario_row(project_id, scenario_id),
    )


@router.get("/projects/{project_id}/scenarios/{scenario_id}/configuration")
async def get_scenario_configuration(request: Request, project_id: str, scenario_id: str):
    return request.app.state.workbench.get_scenario_configuration(project_id, scenario_id)


@router.patch("/projects/{project_id}/scenarios/{scenario_id}")
async def update_scenario(
    request: Request,
    project_id: str,
    scenario_id: str,
    payload: ScenarioUpdate,
):
    return request.app.state.workbench.update_scenario(
        project_id,
        scenario_id,
        name=payload.name,
        parameter_patch=payload.parameter_patch,
        input_revision_id=payload.input_revision_id,
        input_bindings=[item.model_dump() for item in payload.input_bindings] if payload.input_bindings is not None else None,
        parameter_template_id=payload.parameter_template_id,
        expected_version=payload.expected_version,
    )


@router.post("/projects/{project_id}/scenarios/{scenario_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_scenario(request: Request, project_id: str, scenario_id: str):
    return request.app.state.workbench.duplicate_scenario(project_id, scenario_id)


@router.post("/projects/{project_id}/scenarios/{scenario_id}/archive")
async def archive_scenario(request: Request, project_id: str, scenario_id: str):
    return request.app.state.workbench.archive_scenario(project_id, scenario_id)


@router.delete("/projects/{project_id}/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(request: Request, project_id: str, scenario_id: str):
    request.app.state.workbench.delete_scenario(project_id, scenario_id)
    return None


@router.get("/projects/{project_id}/queue")
async def list_queue(request: Request, project_id: str):
    items = request.app.state.workbench.list_queue(project_id)
    return {"items": items, "count": len(items)}


@router.post("/projects/{project_id}/queue", status_code=status.HTTP_201_CREATED)
async def enqueue_scenario(request: Request, project_id: str, payload: QueueCreate):
    return request.app.state.workbench.enqueue_scenario(project_id, payload.scenario_id)


@router.post("/projects/{project_id}/queue/start")
async def start_queue(request: Request, project_id: str):
    return request.app.state.workbench.start_queue_batch(project_id)


@router.patch("/projects/{project_id}/queue/order")
async def reorder_queue(request: Request, project_id: str, payload: QueueReorder):
    items = request.app.state.workbench.reorder_queue(
        project_id,
        payload.item_id,
        payload.new_position,
    )
    return {"items": items, "count": len(items)}


@router.post("/projects/{project_id}/queue/delete-preview")
async def preview_queue_delete(request: Request, project_id: str, payload: QueueDeleteRequest):
    return request.app.state.workbench.preview_queue_delete(project_id, payload.queue_item_ids)


@router.post("/projects/{project_id}/queue/batch-delete")
async def batch_delete_queue(request: Request, project_id: str, payload: QueueDeleteRequest):
    return request.app.state.workbench.batch_delete_queue_items(project_id, payload.queue_item_ids)


@router.delete("/projects/{project_id}/queue/{queue_item_id}")
async def cancel_queue_item(request: Request, project_id: str, queue_item_id: str):
    return request.app.state.workbench.cancel_queue_item(project_id, queue_item_id)


@router.post("/projects/{project_id}/queue/{queue_item_id}/retry", status_code=status.HTTP_201_CREATED)
async def retry_queue_item(request: Request, project_id: str, queue_item_id: str):
    return request.app.state.workbench.retry_queue_item(project_id, queue_item_id)


@router.get("/projects/{project_id}/simulations")
async def list_simulations(request: Request, project_id: str):
    simulations = request.app.state.workbench.list_simulations(project_id)
    return {"simulations": simulations, "count": len(simulations)}


@router.get("/projects/{project_id}/simulations/{simulation_id}")
async def get_project_simulation(request: Request, project_id: str, simulation_id: str):
    return request.app.state.workbench.public_simulation(
        project_id,
        request.app.state.workbench.simulation_row(project_id, simulation_id),
    )


@router.get("/projects/{project_id}/simulations/{simulation_id}/terminal")
async def get_project_simulation_terminal(request: Request, project_id: str, simulation_id: str):
    simulation = request.app.state.workbench.public_simulation(
        project_id,
        request.app.state.workbench.simulation_row(project_id, simulation_id),
    )
    return {"simulation_id": simulation_id, "status": simulation["status"], "entries": simulation["terminal_log"]}


@router.get("/simulations/{simulation_id}")
async def get_simulation(request: Request, simulation_id: str):
    _project_id, simulation = request.app.state.workbench.find_simulation(simulation_id)
    return simulation


@router.post("/simulations/{simulation_id}/stop")
async def stop_simulation(request: Request, simulation_id: str):
    project_id, simulation = request.app.state.workbench.find_simulation(simulation_id)
    if simulation["status"] not in {"starting", "running", "stopping"}:
        raise WorkbenchError("simulation_not_stoppable", "Simulation is not active.", status_code=409)
    if not request.app.state.coordinator.request_stop(simulation_id):
        raise WorkbenchError("simulation_not_active", "Simulation is not owned by the active scheduler.", status_code=409)
    request.app.state.workbench.update_run(project_id, simulation_id, {"status": "stopping"})
    return request.app.state.workbench.public_simulation(
        project_id,
        request.app.state.workbench.simulation_row(project_id, simulation_id),
    )


@router.post("/projects/{project_id}/queue/{queue_item_id}/stop")
async def stop_queue_item(request: Request, project_id: str, queue_item_id: str):
    item = request.app.state.workbench._queue_row(project_id, queue_item_id)
    simulation_id = item["simulation_id"]
    if not simulation_id:
        return request.app.state.workbench.cancel_queue_item(project_id, queue_item_id)
    return await stop_simulation(request, str(simulation_id))
