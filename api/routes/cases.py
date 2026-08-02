"""Case configuration endpoints for Taichi Flow."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

from api.services.parameter_catalog import build_case_config_interface
from api.services.reference_config_parser import parse_reference_config_file


router = APIRouter()


class CaseConfigParseRequest(BaseModel):
    """Request for parsing a legacy text case configuration."""

    case_config_file: str = Field(..., description="Path to a legacy text case configuration file")
    case_base_dir: Optional[str] = Field(None, description="Optional base directory for relative case paths")


@router.post("/parse-config")
async def parse_case_config(payload: CaseConfigParseRequest) -> Dict[str, Any]:
    """Parse a case config into a frontend-safe manifest."""
    try:
        parsed = parse_reference_config_file(payload.case_config_file, payload.case_base_dir)
        return build_case_config_interface(parsed)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse case config: {exc}") from exc
