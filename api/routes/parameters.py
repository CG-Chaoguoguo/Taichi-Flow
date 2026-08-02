"""Parameter catalog endpoints for Taichi Flow."""
from __future__ import annotations

from fastapi import APIRouter
from typing import Any, Dict

from api.services.parameter_catalog import build_static_parameter_catalog
from api.services.runtime_profile import runtime_profiles_catalog


router = APIRouter()


@router.get("/catalog")
async def get_parameter_catalog() -> Dict[str, Any]:
    """Return the frontend-safe editable parameter catalog."""
    catalog = build_static_parameter_catalog()
    catalog["runtime_profiles"] = runtime_profiles_catalog()
    return catalog
