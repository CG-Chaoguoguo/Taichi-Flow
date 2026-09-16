"""Global workbench settings endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.services.workbench_store import WorkbenchError


router = APIRouter()


class ComputeGateDefaultsUpdate(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


@router.get("/compute-gates")
async def get_compute_gates(request: Request) -> Dict[str, Any]:
    return request.app.state.workbench.get_compute_gate_defaults()


@router.put("/compute-gates")
async def put_compute_gates(request: Request, payload: ComputeGateDefaultsUpdate) -> Dict[str, Any]:
    try:
        return request.app.state.workbench.put_compute_gate_defaults(payload.values)
    except WorkbenchError:
        raise
