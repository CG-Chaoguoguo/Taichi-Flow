"""Public Taichi-Flow workbench REST endpoints."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Request, UploadFile, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

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


class InputRevisionCreate(BaseModel):
    version_tag: Optional[str] = None
    upload_ids: list[str] = Field(default_factory=list)
    parent_revision_id: Optional[str] = None


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1)
    input_revision_id: Optional[str] = None
    base_scenario_id: Optional[str] = None
    parameter_patch: Dict[str, Any] = Field(default_factory=dict)


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    parameter_patch: Optional[Dict[str, Any]] = None


class QueueCreate(BaseModel):
    scenario_id: str = Field(..., min_length=1)


class QueueReorder(BaseModel):
    item_id: str = Field(..., min_length=1)
    new_position: int = Field(..., ge=1)


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
    )


@router.get("/projects/{project_id}/input-revisions/{revision_id}")
async def get_input_revision(request: Request, project_id: str, revision_id: str):
    revision = request.app.state.workbench.get_input_revision(project_id, revision_id)
    revision["files"] = request.app.state.workbench.input_revision_files(project_id, revision_id)
    return revision


@router.post("/projects/{project_id}/input-revisions/{revision_id}/validate")
async def validate_input_revision(request: Request, project_id: str, revision_id: str):
    return request.app.state.workbench.validate_input_revision(project_id, revision_id)


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
    )


@router.get("/projects/{project_id}/scenarios/{scenario_id}")
async def get_scenario(request: Request, project_id: str, scenario_id: str):
    return request.app.state.workbench._public_scenario(
        project_id,
        request.app.state.workbench._scenario_row(project_id, scenario_id),
    )


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


@router.patch("/projects/{project_id}/queue/order")
async def reorder_queue(request: Request, project_id: str, payload: QueueReorder):
    items = request.app.state.workbench.reorder_queue(
        project_id,
        payload.item_id,
        payload.new_position,
    )
    return {"items": items, "count": len(items)}


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
