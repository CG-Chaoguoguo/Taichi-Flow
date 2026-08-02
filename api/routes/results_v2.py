"""Result families and export jobs for the Taichi-Flow domain API."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
import hashlib
import json
import zipfile

from api.services.result_service import (
    create_export_job,
    delete_results,
    get_export_job,
    index_results,
    list_export_jobs,
    result_metadata,
    resolve_result_file,
    run_export_job,
    simulation_output_dir,
)
from api.services.workbench_store import WorkbenchError


router = APIRouter()


class ExportCreate(BaseModel):
    simulation_id: str = Field(..., min_length=1)
    families: list[str] = Field(default_factory=list)
    filenames: list[str] = Field(default_factory=list)


@router.get("/projects/{project_id}/results/{simulation_id}")
async def get_results(request: Request, project_id: str, simulation_id: str):
    return index_results(request.app.state.workbench, project_id, simulation_id)


@router.get("/projects/{project_id}/results/{simulation_id}/metadata")
async def get_results_metadata(request: Request, project_id: str, simulation_id: str):
    return result_metadata(request.app.state.workbench, project_id, simulation_id)


@router.get("/projects/{project_id}/results/{simulation_id}/files/{filename:path}")
async def download_result_file(request: Request, project_id: str, simulation_id: str, filename: str):
    path, download_name = resolve_result_file(
        request.app.state.workbench,
        project_id,
        simulation_id,
        filename,
    )
    return FileResponse(path=str(path), filename=download_name, media_type="application/octet-stream")


@router.get("/projects/{project_id}/results/{simulation_id}/download.zip")
async def download_results_zip(request: Request, project_id: str, simulation_id: str):
    store = request.app.state.workbench
    output_dir = simulation_output_dir(store, project_id, simulation_id)
    index = index_results(store, project_id, simulation_id)
    if not index["count"]:
        raise WorkbenchError("results_empty", "No result files are available.", status_code=404)
    archive_path = output_dir / f"{simulation_id}_results.zip"
    manifest = []
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for family in index["families"]:
            for file_info in family["files"]:
                source = output_dir.joinpath(*Path(file_info["source_filename"]).parts)
                archive_name = file_info["filename"]
                archive.write(source, arcname=archive_name)
                manifest.append({"path": archive_name, "size": source.stat().st_size, "sha256": file_info["sha256"]})
        archive.writestr("manifest.json", json.dumps({"simulation_id": simulation_id, "files": manifest}, ensure_ascii=False, indent=2))
    return FileResponse(path=str(archive_path), filename=f"{simulation_id}_results.zip", media_type="application/zip")


@router.delete("/projects/{project_id}/results/{simulation_id}")
async def remove_results(request: Request, project_id: str, simulation_id: str):
    delete_results(request.app.state.workbench, project_id, simulation_id)
    return {"simulation_id": simulation_id, "deleted": True}


@router.get("/projects/{project_id}/exports")
async def list_exports(request: Request, project_id: str):
    exports = list_export_jobs(request.app.state.workbench, project_id)
    return {"exports": exports, "count": len(exports)}


@router.post("/projects/{project_id}/exports", status_code=202)
async def create_export(request: Request, project_id: str, payload: ExportCreate, background_tasks: BackgroundTasks):
    store = request.app.state.workbench
    job = create_export_job(
        store,
        project_id,
        payload.simulation_id,
        {"families": payload.families, "filenames": payload.filenames},
    )
    background_tasks.add_task(run_export_job, store, project_id, job["export_id"])
    return job


@router.get("/projects/{project_id}/exports/{export_id}")
async def get_export(request: Request, project_id: str, export_id: str):
    return get_export_job(request.app.state.workbench, project_id, export_id)


@router.get("/projects/{project_id}/exports/{export_id}/download")
async def download_export(request: Request, project_id: str, export_id: str):
    job = get_export_job(request.app.state.workbench, project_id, export_id)
    if job["status"] != "completed" or not job.get("archive_path"):
        raise WorkbenchError("export_not_ready", "Export archive is not ready.", status_code=409)
    archive_path = Path(str(job["archive_path"])).resolve()
    export_root = request.app.state.workbench.project_database(project_id).export_dir.resolve()
    try:
        archive_path.relative_to(export_root)
    except ValueError as exc:
        raise WorkbenchError("invalid_export_path", "Export archive is outside the project export directory.", status_code=409) from exc
    if not archive_path.is_file():
        raise WorkbenchError("export_not_found", "Export archive was not found.", status_code=404)
    return FileResponse(path=str(archive_path), filename=f"{export_id}.zip", media_type="application/zip")
