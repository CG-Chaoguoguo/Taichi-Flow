"""Explicit legacy ``edda_in`` migration planning helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


NATIVE_TO_ASSET_FAMILY = {
    "demfil": "dem",
    "manningfil": "manning",
    "slofil": "slope",
    "zonfil": "zones",
    "zfil": "thickness",
    "depfil": "groundwater",
    "rizerofil": "infiltration",
    "rifil": "rainfall",
    "outflow.txt": "outflow",
    "inflow.txt": "inflow",
    "hydrograph.txt": "monitoring",
    "drainage.txt": "drainage",
    "swmm.txt": "swmm",
}


def _binding_identity(native_family: str, asset_family: str, ordinal: int) -> tuple[str, str, str | None]:
    if native_family == "demfil":
        return "dem.primary", "primary", None
    if native_family == "manningfil":
        return "manning.raster", "manning-raster", None
    if native_family == "zonfil":
        return "zones.primary", "zones", None
    if native_family == "slofil":
        return "slope.primary", "slope", None
    if native_family == "zfil":
        return "thickness.primary", "thickness", None
    if native_family == "depfil":
        return "groundwater.initial", "groundwater", None
    if native_family == "rizerofil":
        return "infiltration.initial", "infiltration", None
    if native_family == "rifil":
        period_id = f"period-{ordinal:04d}"
        return f"rainfall.period.{ordinal:04d}", "rainfall-period", period_id
    key = f"{asset_family}.primary" if ordinal == 1 else f"{asset_family}.{ordinal:04d}"
    return key, asset_family, None


def _is_active(parsed: Any, native_family: str, ordinal: int) -> bool:
    if native_family == "rifil":
        values = list(getattr(parsed, "cri_mps", []) or [])
        return ordinal <= len(values) and float(values[ordinal - 1]) < 0.0
    file_inputs = getattr(parsed, "file_inputs", {}) or {}
    reference = file_inputs.get(native_family)
    runtime_active = getattr(reference, "current_backend_branch_active", None)
    if runtime_active is not None:
        return bool(runtime_active)
    if native_family == "manningfil":
        return "raster" in str(getattr(parsed, "manning_source", ""))
    # Families without an explicit parser/runtime activation decision are
    # provenance-only. They must never become runnable bindings by default.
    return False


def build_legacy_migration_plan(parsed: Any, *, source_hash: str) -> Dict[str, Any]:
    references: list[Dict[str, Any]] = []
    proposed: list[Dict[str, Any]] = []
    unresolved_active: list[Dict[str, Any]] = []
    existing_count = 0
    missing_count = 0
    for native_family, ref in parsed.file_inputs.items():
        raw_paths = list(ref.raw_paths or [])
        resolved_paths = list(ref.resolved_paths or [])
        exists_values = list(ref.exists or [])
        asset_family = NATIVE_TO_ASSET_FAMILY.get(native_family, "native")
        for offset, raw_path in enumerate(raw_paths):
            ordinal = offset + 1
            resolved = resolved_paths[offset] if offset < len(resolved_paths) else raw_path
            exists = bool(exists_values[offset]) if offset < len(exists_values) else Path(str(resolved)).is_file()
            active = _is_active(parsed, native_family, ordinal)
            binding_key, role, period_id = _binding_identity(native_family, asset_family, ordinal)
            item = {
                "native_family": native_family,
                "family": asset_family,
                "ordinal": ordinal,
                "path": str(resolved),
                "exists": exists,
                "active": active,
                "binding_key": binding_key,
                "role": role,
                "period_id": period_id,
            }
            references.append(item)
            existing_count += int(exists)
            missing_count += int(not exists)
            if exists and active and native_family in NATIVE_TO_ASSET_FAMILY:
                proposed.append(item)
            elif not exists and active and native_family in NATIVE_TO_ASSET_FAMILY:
                unresolved_active.append(item)
    return {
        "source_hash": source_hash,
        "source_kind": "legacy_edda_in",
        "existing_file_count": existing_count,
        "missing_file_count": missing_count,
        "file_references": references,
        "proposed_bindings": proposed,
        "unresolved_active_bindings": unresolved_active,
        "unresolved_active_count": len(unresolved_active),
        "warnings": [
            *(
                [f"{missing_count} legacy path reference(s) are unavailable; only active existing files will be collected."]
                if missing_count
                else []
            ),
            *(
                [
                    f"{len(unresolved_active)} active legacy binding(s) are unresolved; the migrated input revision will remain invalid until they are replaced."
                ]
                if unresolved_active
                else []
            ),
        ],
    }
