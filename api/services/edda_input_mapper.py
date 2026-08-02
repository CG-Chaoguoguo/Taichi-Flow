"""Production mapper and runtime provenance utilities for the S1 native input chain."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.transform import from_origin

from api.services.native_sidecar_loader import (
    find_precomputed_unsfin_artifacts,
    load_inflow_runtime_payload,
    load_precomputed_unsfin_schedule,
    parse_case_sidecar,
)
from api.services.reference_config_parser import ReferenceConfigParseResult
from edda.config.sim_config import SimulationConfig
from edda.io.spatial_input_loader import SpatialInputLoader, fill_raster_nodata
from edda.solver.fortran_literals import FORTRAN_DEG2RAD


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_merge(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not override:
        return base
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _write_rainfall_file(cri_mps: List[float], capt_s: List[float], rainfall_file: Path) -> None:
    rainfall_mm_hr = np.asarray(cri_mps, dtype=np.float64) * 3600.0 * 1000.0
    rainfall_file.parent.mkdir(parents=True, exist_ok=True)

    if len(capt_s) >= len(cri_mps) + 1:
        interval_starts = np.asarray(capt_s[: len(cri_mps)], dtype=np.float64)
    else:
        interval_starts = np.arange(len(cri_mps), dtype=np.float64) * 3600.0

    start_time = np.datetime64("2000-01-01T00:00:00")
    times = start_time + interval_starts.astype("timedelta64[s]")

    with rainfall_file.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("time,rainfall\n")
        for timestamp, rain in zip(times, rainfall_mm_hr):
            handle.write(f"{str(timestamp)},{rain:.15f}\n")


def _raster_transform_from_metadata(metadata: Dict[str, Any]):
    transform = metadata.get("transform")
    if transform is not None:
        return transform
    bounds = metadata.get("bounds")
    dx = float(metadata.get("dx", 1.0))
    dy = float(metadata.get("dy", dx))
    if bounds and len(bounds) == 4:
        x_min, _, _, y_max = bounds
        return from_origin(float(x_min), float(y_max), dx, dy)
    height = float(metadata.get("height", 0.0))
    return from_origin(0.0, height * dy, dx, dy)


def _write_geotiff_grid(path: Path, grid: np.ndarray, metadata: Dict[str, Any], nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    transform = _raster_transform_from_metadata(metadata)
    crs = metadata.get("crs")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=grid.shape[0],
        width=grid.shape[1],
        count=1,
        dtype="float64",
        crs=crs if crs not in ("None", "") else None,
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(grid.astype(np.float64), 1)


def _build_rainfall_forcing(
    parsed: ReferenceConfigParseResult,
    output_dir: Path,
    native_files: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build the production rainfall configuration from original EDDA rules.

    Original EDDA reads `rifil(j)` only when `cri(j) < 0`; otherwise the scalar
    `cri(j)` is the rainfall intensity for every active cell in that period.
    """
    rainfall_audit = {
        "mode": parsed.rainfall_mode,
        "period_sources": parsed.rainfall_period_sources,
        "period_source_map": parsed.period_source_map,
        "capt_s": parsed.capt_s,
        "units": {
            "cri": "m/s",
            "rifil_grid": "m/s",
            "generated_csv": "mm/hr",
            "generated_spatial_tif": "mm/hr",
        },
    }

    if parsed.rainfall_mode == "uniform_cri":
        rainfall_file = output_dir / "_generated_inputs" / "rainfall_from_edda_in.csv"
        _write_rainfall_file(parsed.cri_mps, parsed.capt_s, rainfall_file)
        rainfall_audit["generated_file"] = str(rainfall_file)
        rainfall_audit["active_source"] = "uniform_cri"
        native_files["rifil"] = {
            "family": "rifil",
            "path": _first_path(parsed, "rifil"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "All `cri(j)` values are non-negative, so original EDDA does not consume `rifil(j)` grids for this run.",
        }
        return (
            {
                "mode": "single_file",
                "file": str(rainfall_file),
            },
            rainfall_audit,
        )

    dem_path = _first_path(parsed, "demfil")
    if not dem_path:
        raise ValueError("Cannot build spatial rainfall forcing because `demfil` is missing.")
    dem_grid, dem_metadata = SpatialInputLoader(dem_path).read()
    dem_shape = dem_grid.shape
    dem_nodata = dem_metadata.get("nodata")
    if dem_nodata is None:
        dem_active = np.isfinite(dem_grid)
    else:
        dem_active = ~np.isclose(dem_grid, dem_nodata)

    spatial_dir = output_dir / "_generated_inputs" / "rainfall_spatial_from_rifil"
    spatial_dir.mkdir(parents=True, exist_ok=True)
    generated_files: List[str] = []

    rifil_ref = parsed.file_inputs.get("rifil")
    rifil_paths = rifil_ref.resolved_paths if rifil_ref else []

    for idx, cri in enumerate(parsed.cri_mps):
        if cri < 0.0:
            if idx >= len(rifil_paths):
                raise ValueError(f"`cri({idx + 1}) < 0` but no matching `rifil({idx + 1})` path was parsed.")
            source_path = Path(rifil_paths[idx])
            if not source_path.exists():
                raise FileNotFoundError(f"`cri({idx + 1}) < 0` requires rainfall raster, but it is missing: {source_path}")
            grid_mps, grid_metadata = SpatialInputLoader(str(source_path)).read()
            if grid_mps.shape != dem_shape:
                raise ValueError(
                    f"`rifil({idx + 1})` shape {grid_mps.shape} does not match DEM shape {dem_shape}: {source_path}"
                )
            nodata_value = grid_metadata.get("nodata")
            grid_mps = fill_raster_nodata(grid_mps, nodata_value, 0.0)
            source_kind = "rifil_grid"
        else:
            grid_mps = np.full(dem_shape, float(cri), dtype=np.float64)
            source_kind = "uniform_cri"

        grid_mps = np.where(dem_active, grid_mps, 0.0)
        grid_mm_hr = grid_mps * 3600.0 * 1000.0
        tif_path = spatial_dir / f"period_{idx + 1:04d}.tif"
        _write_geotiff_grid(tif_path, grid_mm_hr, dem_metadata)
        generated_files.append(str(tif_path))
        rainfall_audit["period_sources"][idx]["generated_tif"] = str(tif_path)
        rainfall_audit["period_sources"][idx]["generated_source_kind"] = source_kind

    rainfall_audit["generated_directory"] = str(spatial_dir)
    rainfall_audit["generated_files"] = generated_files
    rainfall_audit["active_source"] = parsed.rainfall_mode
    native_files["rifil"] = {
        "family": "rifil",
        "path": _first_path(parsed, "rifil"),
        "provenance": "reference_config",
        "status": "production-reachable",
        "runtime_stage": "initialize.rainfall_reader.spatial_series",
        "notes": (
            "All rainfall periods use `rifil(j)` rasters."
            if parsed.rainfall_mode == "raster_rifil"
            else "`cri(j)<0` period(s) were converted from `rifil(j)` grids into the production spatial rainfall series; non-negative periods remain uniform grids."
        ),
    }
    return (
        {
            "mode": "spatial_tif_series",
            "directory": str(spatial_dir),
            "file_pattern": "period_*.tif",
            "time_step_hours": (
                (parsed.capt_s[1] - parsed.capt_s[0]) / 3600.0
                if len(parsed.capt_s) > 1
                else 1.0
            ),
            "interval_bounds_s": parsed.capt_s[: len(parsed.cri_mps) + 1],
        },
        rainfall_audit,
    )


def _native_file_entry(
    family: str,
    path: Optional[str],
    provenance: str,
    production_status: str,
    runtime_stage: str,
    consumed: bool = False,
    notes: Optional[str] = None,
    helper_fallback: bool = False,
    blocked_reason: Optional[str] = None,
    activation_condition: Optional[str] = None,
    status_basis: Optional[str] = None,
    structure_summary: Optional[Dict[str, Any]] = None,
    exists_on_disk: Optional[bool] = None,
    original_branch_active: Optional[bool] = None,
    current_backend_branch_active: Optional[bool] = None,
    activation_basis: Optional[str] = None,
    expected_output_families: Optional[List[str]] = None,
    input_state: Optional[str] = None,
    selected_source: Optional[str] = None,
    source_registry_key: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "family": family,
        "path": path,
        "provenance": provenance,
        "production_status": production_status,
        "runtime_stage": runtime_stage,
        "consumed": consumed,
        "helper_fallback": helper_fallback,
        "notes": notes,
        "blocked_reason": blocked_reason,
        "activation_condition": activation_condition,
        "status_basis": status_basis,
        "structure_summary": structure_summary,
        "exists_on_disk": exists_on_disk,
        "original_branch_active": original_branch_active,
        "current_backend_branch_active": current_backend_branch_active,
        "activation_basis": activation_basis,
        "expected_output_families": expected_output_families or [],
        "input_state": input_state,
        "selected_source": selected_source,
        "source_registry_key": source_registry_key,
    }


def _mark_manifest_entry(manifest: Dict[str, Any], family: str, **updates: Any) -> None:
    for entry in manifest.get("inputs", []):
        if entry.get("family") == family:
            entry.update(updates)
            return


def _first_path(parsed: ReferenceConfigParseResult, family: str) -> Optional[str]:
    ref = parsed.file_inputs.get(family)
    if not ref or not ref.resolved_paths:
        return None
    return ref.resolved_paths[0]


def _structure_summary(parsed: ReferenceConfigParseResult, family: str) -> Optional[Dict[str, Any]]:
    ref = parsed.file_inputs.get(family)
    if not ref:
        return None
    return ref.structure_summary


def _reference_output_suffix(parsed: ReferenceConfigParseResult) -> str:
    try:
        lines = Path(parsed.reference_config_file).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return "EDDA"
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith("identification code to be added to names of output files"):
            for next_line in lines[idx + 1:]:
                suffix = next_line.strip()
                if suffix:
                    return suffix
    return "EDDA"


def _any_exists(parsed: ReferenceConfigParseResult, family: str) -> bool:
    ref = parsed.file_inputs.get(family)
    return bool(ref and any(ref.exists))


def _build_reference_input_source_registry(parsed: ReferenceConfigParseResult) -> Dict[str, Dict[str, Any]]:
    depth_file_exists = _any_exists(parsed, "depfil")
    rizero_file_exists = _any_exists(parsed, "rizerofil")
    manning_file_exists = _any_exists(parsed, "manningfil")
    outflow_file_exists = _any_exists(parsed, "outflow.txt")
    inflow_file_exists = _any_exists(parsed, "inflow.txt")

    if parsed.depth < 0:
        water_table_state = "file_backed" if depth_file_exists else "truly_missing"
        water_table_source = "depfil"
    else:
        water_table_state = "config_fallback"
        water_table_source = "config_depth"

    if parsed.rizero < 0:
        infiltration_state = "file_backed" if rizero_file_exists else "truly_missing"
        infiltration_source = "rizerofil"
    else:
        infiltration_state = "config_fallback"
        infiltration_source = "config_rizero"

    if parsed.manning_source == "raster_manningfil":
        manning_state = "file_backed"
        manning_source = "raster_manningfil"
    else:
        manning_state = "config_fallback"
        manning_source = "global_manning"

    if parsed.rainfall_mode == "uniform_cri":
        rainfall_state = "config_fallback"
        rainfall_source = "uniform_cri"
    elif parsed.rainfall_mode == "raster_rifil":
        rainfall_state = "file_backed"
        rainfall_source = "raster_rifil"
    else:
        rainfall_state = "file_backed"
        rainfall_source = "mixed"

    outflow_active = bool(parsed.flags.get("simulate_outflow_cell"))
    if outflow_file_exists:
        outflow_state = "file_backed"
        outflow_selected = "outflow_txt"
    elif outflow_active:
        outflow_state = "truly_missing"
        outflow_selected = None
    else:
        outflow_state = "config_fallback"
        outflow_selected = None

    inflow_active = bool(parsed.flags.get("simulate_inflow_hydrograph"))
    if inflow_file_exists:
        inflow_state = "file_backed"
        inflow_selected = "inflow_txt"
    elif inflow_active:
        inflow_state = "truly_missing"
        inflow_selected = None
    else:
        inflow_state = "config_fallback"
        inflow_selected = None

    failure_schedule_locator = None
    failure_schedule_present = False
    if parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule":
        failure_schedule_locator = find_precomputed_unsfin_artifacts(Path(parsed.reference_base_dir))
        failure_schedule_present = bool(failure_schedule_locator.get("all_required_present"))

    return {
        "dfs_infiltration_variant": {
            "family": "dfs.F90",
            "state": "file_backed" if parsed.dfs_infiltration_variant_source else "config_fallback",
            "selected_source": parsed.dfs_infiltration_variant,
            "path": parsed.dfs_infiltration_variant_source,
            "exists_on_disk": bool(parsed.dfs_infiltration_variant_source),
            "status_basis": parsed.dfs_infiltration_variant_basis,
        },
        "dfs_face_flux_variant": {
            "family": "dfs.F90",
            "state": "file_backed" if parsed.dfs_face_flux_variant_source else "config_fallback",
            "selected_source": parsed.dfs_face_flux_variant,
            "path": parsed.dfs_face_flux_variant_source,
            "exists_on_disk": bool(parsed.dfs_face_flux_variant_source),
            "status_basis": parsed.dfs_face_flux_variant_basis,
        },
        "dfs_failure_source_variant": {
            "family": "dfs.F90",
            "state": "file_backed" if parsed.dfs_failure_source_variant_source else "config_fallback",
            "selected_source": parsed.dfs_failure_source_variant,
            "path": parsed.dfs_failure_source_variant_source,
            "exists_on_disk": bool(parsed.dfs_failure_source_variant_source),
            "status_basis": parsed.dfs_failure_source_variant_basis,
            "schedule_provider": (
                "original_tfail_artifacts"
                if failure_schedule_present
                else "missing_original_tfail_artifacts"
                if parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule"
                else None
            ),
            "schedule_loaded": False if parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule" else None,
            "artifact_locator": failure_schedule_locator,
            "runtime_active": parsed.dfs_failure_source_variant != "precomputed_unsfin_schedule",
            "runtime_equivalent_implemented": parsed.dfs_failure_source_variant != "precomputed_unsfin_schedule",
            "blocked_reason": (
                "Bundled source requests the original `unsfin` precomputed failure schedule "
                "(`gindx/tfail/fdepth`). The current backend can consume externally supplied "
                "original artifacts, but this case has not provided the validated artifact set."
                if parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule"
                and not failure_schedule_present
                else None
            ),
        },
        "inflow_denominator_variant": {
            "family": "dfs.F90",
            "state": "file_backed" if parsed.inflow_denominator_variant_source else "config_fallback",
            "selected_source": parsed.inflow_denominator_variant,
            "path": parsed.inflow_denominator_variant_source,
            "exists_on_disk": bool(parsed.inflow_denominator_variant_source),
            "status_basis": parsed.inflow_denominator_variant_basis,
            "direction": parsed.inflow_denominator_direction,
            "fv_component_if_used": parsed.inflow_denominator_fv_value,
        },
        "water_table_source": {
            "family": "depfil",
            "state": water_table_state,
            "selected_source": water_table_source,
            "path": _first_path(parsed, "depfil"),
            "exists_on_disk": depth_file_exists,
            "config_value": parsed.depth,
            "status_basis": (
                "Original EDDA reads `depfil` only when `depth < 0`; otherwise the scalar `depth` value remains active for every cell."
            ),
        },
        "initial_infiltration_source": {
            "family": "rizerofil",
            "state": infiltration_state,
            "selected_source": infiltration_source,
            "path": _first_path(parsed, "rizerofil"),
            "exists_on_disk": rizero_file_exists,
            "config_value": parsed.rizero,
            "status_basis": (
                "Original EDDA reads `rizerofil` only when `rizero < 0`; otherwise the scalar `rizero` value remains active for every cell."
            ),
        },
        "manning_source": {
            "family": "manningfil",
            "state": manning_state,
            "selected_source": manning_source,
            "path": _first_path(parsed, "manningfil"),
            "exists_on_disk": manning_file_exists,
            "config_value": parsed.manning_global,
            "status_basis": (
                "Original EDDA uses raster Manning only when a usable `manningfil` exists; otherwise it falls back to the initiation/global Manning value."
            ),
        },
        "rainfall_source": {
            "family": "rifil",
            "state": rainfall_state,
            "selected_source": rainfall_source,
            "path": _first_path(parsed, "rifil"),
            "exists_on_disk": _any_exists(parsed, "rifil"),
            "config_value": list(parsed.cri_mps),
            "period_source_map": parsed.period_source_map,
            "status_basis": (
                "Original EDDA consumes `rifil(j)` only for periods where `cri(j) < 0`; otherwise `cri(j)` defines uniform rainfall for that period."
            ),
        },
        "outflow_point_source": {
            "family": "outflow.txt",
            "state": outflow_state,
            "selected_source": outflow_selected,
            "path": _first_path(parsed, "outflow.txt"),
            "exists_on_disk": outflow_file_exists,
            "required_by_flag": outflow_active,
            "status_basis": (
                "The numbers in `outflow.txt` define outflow point positions. This family has no config fallback; it is file-driven when `simulate_outflow_cell = T`."
            ),
        },
        "inflow_source": {
            "family": "inflow.txt",
            "state": inflow_state,
            "selected_source": inflow_selected,
            "path": _first_path(parsed, "inflow.txt"),
            "exists_on_disk": inflow_file_exists,
            "required_by_flag": inflow_active,
            "runtime_active": inflow_active and inflow_file_exists,
            "status_basis": (
                "The original `inflow.txt` sidecar is file-driven. It affects runtime only when "
                "`simulate_inflow_hydrograph = T`; if the flag is false, the file may still exist "
                "for case packaging but must not be injected into runtime forcing."
            ),
        },
    }


def _input_state_for_family(
    family: str,
    input_source_registry: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    exists_on_disk: Optional[bool] = None,
) -> Optional[str]:
    registry = input_source_registry or {}
    family_to_registry = {
        "depfil": "water_table_source",
        "rizerofil": "initial_infiltration_source",
        "manningfil": "manning_source",
        "manning_global": "manning_source",
        "rifil": "rainfall_source",
        "rainfall_schedule": "rainfall_source",
        "rainfall_spatial_series": "rainfall_source",
        "outflow.txt": "outflow_point_source",
        "inflow.txt": "inflow_source",
        "precomputed_unsfin_schedule": "dfs_failure_source_variant",
    }
    registry_key = family_to_registry.get(family)
    if registry_key and registry.get(registry_key):
        return registry[registry_key].get("state")
    if exists_on_disk is True:
        return "file_backed"
    return None


def _selected_source_for_family(
    family: str,
    input_source_registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    registry = input_source_registry or {}
    family_to_registry = {
        "depfil": "water_table_source",
        "rizerofil": "initial_infiltration_source",
        "manningfil": "manning_source",
        "manning_global": "manning_source",
        "rifil": "rainfall_source",
        "rainfall_schedule": "rainfall_source",
        "rainfall_spatial_series": "rainfall_source",
        "outflow.txt": "outflow_point_source",
        "inflow.txt": "inflow_source",
        "precomputed_unsfin_schedule": "dfs_failure_source_variant",
    }
    registry_key = family_to_registry.get(family)
    if registry_key and registry.get(registry_key):
        return registry[registry_key].get("selected_source")
    return None


def _reference_file_state(
    parsed: ReferenceConfigParseResult,
    family: str,
    input_source_registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ref = parsed.file_inputs.get(family)
    if not ref:
        return {}
    exists_on_disk = any(ref.exists) if ref.exists else None
    return {
        "exists_on_disk": exists_on_disk,
        "original_branch_active": ref.original_branch_active,
        "current_backend_branch_active": ref.current_backend_branch_active,
        "activation_basis": ref.activation_basis,
        "expected_output_families": list(ref.expected_output_families or []),
        "input_state": _input_state_for_family(
            family,
            input_source_registry,
            exists_on_disk=exists_on_disk,
        ),
        "selected_source": _selected_source_for_family(family, input_source_registry),
    }


def _reference_case_activation_snapshot(
    parsed: ReferenceConfigParseResult,
    input_source_registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    return {
        family: _reference_file_state(parsed, family, input_source_registry)
        for family in sorted(parsed.file_inputs.keys())
    }


def _build_sidecar_output_parity(
    parsed: ReferenceConfigParseResult,
    native_files: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    output_timing = parsed.reference_output_expectations.get("output_timing", {})

    def _sidecar_entry(
        family: str,
        *,
        original_runtime_consumer: str,
        current_runtime_evidence: str,
        parity_status: str,
    ) -> Dict[str, Any]:
        ref = parsed.file_inputs.get(family)
        structure_summary = native_files.get(family, {}).get("structure_summary")
        expected_output_families = list((ref.expected_output_families if ref else []) or [])
        return {
            "sidecar_present": bool(native_files.get(family, {}).get("path")),
            "path": native_files.get(family, {}).get("path"),
            "production_status": native_files.get(family, {}).get("status"),
            "original_branch_active": ref.original_branch_active if ref else None,
            "current_backend_branch_active": ref.current_backend_branch_active if ref else None,
            "activation_basis": ref.activation_basis if ref else None,
            "declared_cell_count": (
                structure_summary.get("declared_cell_count")
                if isinstance(structure_summary, dict)
                else None
            ),
            "structure_summary": structure_summary,
            "original_runtime_consumer": original_runtime_consumer,
            "expected_output_families": expected_output_families,
            "expected_output_timing": {
                artifact: output_timing.get(artifact)
                for artifact in expected_output_families
            },
            "current_runtime_evidence": current_runtime_evidence,
            "parity_status": parity_status,
        }

    return {
        "outflow.txt": _sidecar_entry(
            "outflow.txt",
            original_runtime_consumer="Original DFS selects sidecar-listed outflow cells, samples per-cell discharge/Cv during accepted steps, and exports `OUTNQ_*` through `soutf.F90` at end-of-run.",
            current_runtime_evidence="Current backend can now load sidecar-selected outflow cells into a runtime observer/export chain and mark them as outflow boundaries, but generic edge outflow handling still coexists so full hydraulic parity remains partial.",
            parity_status="partial",
        ),
        "hydrograph.txt": _sidecar_entry(
            "hydrograph.txt",
            original_runtime_consumer="Original DFS/WFS uses monitored-cell ids from `hydrograph.txt`, accumulates time-history arrays, and exports `HYDROGRAPH_*` through `shydro.F90`.",
            current_runtime_evidence="Current backend can now load sidecar-selected hydrograph cells into a monitored-output observer and write original-style `HYDROGRAPH_*` text output; broader non-zero oracle coverage remains pending.",
            parity_status="partial",
        ),
        "inflow.txt": _sidecar_entry(
            "inflow.txt",
            original_runtime_consumer="Original DFS/WFS reads inflow-cell pulse forcing from `inflow.txt` and injects hydrograph forcing during runtime.",
            current_runtime_evidence="Current backend can now parse active `inflow.txt` hydrographs, map selected inflow cells into the DFS staging fields, and accumulate inflow volume, while full original log/report parity remains partial.",
            parity_status="partial",
        ),
        "EDDALog.txt": {
            "sidecar_present": False,
            "path": None,
            "production_status": "metadata-parity-only",
            "expected_log_artifacts": list(parsed.reference_output_expectations.get("expected_log_artifacts", []) or []),
            "expected_output_timing": {
                artifact: output_timing.get(artifact)
                for artifact in parsed.reference_output_expectations.get("expected_log_artifacts", []) or []
            },
            "original_runtime_consumer": "Original EDDA writes initialization listings during parsing/reader setup and appends terminal summaries after solver completion.",
            "current_runtime_evidence": "Current backend emits structured JSON metadata files instead of original `EDDALog.txt` text parity.",
            "available_backend_artifacts": [
                "effective_config.json",
                "runtime_input_manifest.json",
                "parameter_audit.json",
                "output_manifest.json",
                "runmode_capabilities.json",
            ],
            "parity_status": "metadata_only",
        },
    }


def _annotate_manifest_with_input_source_registry(
    runtime_input_manifest: Dict[str, Any],
    input_source_registry: Dict[str, Dict[str, Any]],
) -> None:
    family_to_registry = {
        "depfil": "water_table_source",
        "rizerofil": "initial_infiltration_source",
        "manningfil": "manning_source",
        "manning_global": "manning_source",
        "rifil": "rainfall_source",
        "rainfall_schedule": "rainfall_source",
        "rainfall_spatial_series": "rainfall_source",
        "outflow.txt": "outflow_point_source",
        "inflow.txt": "inflow_source",
        "precomputed_unsfin_schedule": "dfs_failure_source_variant",
    }
    for family, registry_key in family_to_registry.items():
        source_entry = input_source_registry.get(registry_key)
        if not source_entry:
            continue
        input_state = source_entry.get("state")
        runtime_active = source_entry.get("runtime_active")
        if runtime_active is None:
            runtime_active = input_state in {"file_backed", "config_fallback"}
        _mark_manifest_entry(
            runtime_input_manifest,
            family,
            input_state=input_state,
            selected_source=source_entry.get("selected_source"),
            source_registry_key=registry_key,
            resolved_via_fallback=input_state == "config_fallback",
            effective_runtime_source=source_entry.get("selected_source"),
            effective_runtime_source_active=bool(runtime_active),
        )


def build_reference_runtime_metadata(
    parsed: ReferenceConfigParseResult,
    output_dir: Path,
    config_overrides: Optional[Dict[str, Any]] = None,
    top_level_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[SimulationConfig, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    zone_ids = sorted(parsed.zones.keys())
    default_zone = parsed.zones[zone_ids[0]]

    ltstar_default = 3.0 if parsed.ltstar_raw < 0 else parsed.ltstar_raw

    zones_cfg: Dict[int, Dict[str, float]] = {}
    for zone_id in zone_ids:
        zone = parsed.zones[zone_id]
        zones_cfg[zone_id] = {
            "zone_id": zone_id,
            "K_sat": zone.top.k_sat,
            "theta_s": zone.top.theta_sat,
            "theta_i": zone.top.theta_ini,
            "psi_f": zone.top.psi_f,
            "c": zone.top.c,
            "phi": zone.top.phi,
            "gamma_s": zone.top.gamma_s,
            "gamma_w": parsed.uww,
            "depth": parsed.depth,
            "n_manning": parsed.manning_global,
            "alpha1": parsed.alpha1,
            "beta1": parsed.beta1,
            "alpha2": parsed.alpha2,
            "beta2": parsed.beta2,
            "alpha_top": zone.top.alpha,
            "alpha_bottom": zone.bottom.alpha,
            "K_sat_top": zone.top.k_sat,
            "K_sat_bottom": zone.bottom.k_sat,
            "theta_sat_top": zone.top.theta_sat,
            "theta_sat_bottom": zone.bottom.theta_sat,
            "theta_res_top": zone.top.theta_res,
            "theta_res_bottom": zone.bottom.theta_res,
            "phib": zone.top.phib,
            "kero": zone.top.kero,
            "ctao": zone.top.ctao,
            "ltstar": ltstar_default,
            "lbstar": parsed.lbstar,
        }

    output_suffix = _reference_output_suffix(parsed)
    hydrograph_structure = _structure_summary(parsed, "hydrograph.txt")
    if hydrograph_structure is not None:
        hydrograph_structure = {
            **hydrograph_structure,
            "output_filename": f"HYDROGRAPH_{output_suffix}.txt",
        }

    native_files = {
        "demfil": {
            "family": "demfil",
            "path": _first_path(parsed, "demfil"),
            "provenance": "reference_config",
            "status": "production-reachable",
            "runtime_stage": "initialize.dem_reader",
            "notes": "Mapped from `edda_in.txt` into production `SimulationConfig.dem_file`.",
        },
        "zonfil": {
            "family": "zonfil",
            "path": _first_path(parsed, "zonfil"),
            "provenance": "reference_config",
            "status": "production-reachable",
            "runtime_stage": "initialize.zone_reader",
            "notes": "Mapped into `SimulationConfig.spatial_zones.zone_file`.",
        },
        "slofil": {
            "family": "slofil",
            "path": _first_path(parsed, "slofil"),
            "provenance": "reference_config",
            "status": "production-reachable",
            "runtime_stage": "post_initialize.native_slope_loader",
            "notes": "S1 formal slope-angle loader; no test helper dependency.",
        },
        "zfil": {
            "family": "zfil",
            "path": _first_path(parsed, "zfil"),
            "provenance": "reference_config",
            "status": "partial" if parsed.ltstar_raw < 0 else "recognized-only",
            "runtime_stage": "post_initialize.native_ltstar_loader" if parsed.ltstar_raw < 0 else "none",
            "notes": (
                "Current backend can inject `zfil` into `ltstar_field` when `ltstar < 0`. "
                "Original Fortran uses the same declared file for upper-layer soil thickness when `ltstar < 0`, "
                "and reuses it as the `zmax` grid only when scalar `zmax < 0`."
            ),
            "blocked_reason": (
                None
                if parsed.ltstar_raw < 0
                else "Scalar `ltstar` is active; the current backend does not consume `zfil` when the ltstar fallback is not requested."
            ),
            "activation_condition": "Current backend only attempts the `zfil` loader when `ltstar_raw < 0` and double-layer runtime is enabled.",
            "status_basis": (
                "Original `edda main program.F90` uses the declared `zfil` file for `ltstar` when `ltstar < 0` "
                "and for `zmax` when `zmax < 0`. Current backend only closes the `ltstar` branch, so treat the family "
                "as partial semantic alignment overall."
            ),
        },
        "manningfil": {
            "family": "manningfil",
            "path": _first_path(parsed, "manningfil"),
            "provenance": "reference_config",
            "status": "production-reachable" if parsed.manning_source == "raster_manningfil" else "fallback-to-global",
            "runtime_stage": "post_initialize.native_manning_loader" if parsed.manning_source == "raster_manningfil" else "none",
            "notes": (
                "Declared `manningfil` exists; populates existing Manning fields without changing rheology formulas."
                if parsed.manning_source == "raster_manningfil"
                else "No usable `manningfil` raster exists; global initiation Manning is the active source."
            ),
            "blocked_reason": (
                None
                if parsed.manning_source == "raster_manningfil"
                else "The declared Manning raster is missing or unavailable, so the current backend falls back to the global initiation Manning value."
            ),
            "activation_condition": "The raster branch is active only when a usable `manningfil` path exists on disk.",
            "status_basis": "Original EDDA uses raster Manning only when a valid `manningfil` is provided; otherwise the initiation/global Manning value remains active.",
        },
        "dirfil": {
            "family": "dirfil",
            "path": _first_path(parsed, "dirfil"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "Recognized for provenance only in S1; current runtime still uses DEM-derived connectivity.",
            "blocked_reason": "No production runtime consumer exists for original flow-direction grids or mode switching.",
            "activation_condition": "Would require an explicit runtime path that consumes `dirfil` or the original `flowdir` mode switch.",
            "status_basis": "Current backend builds Fortran-style 8-direction connectivity directly from the DEM during solver initialization.",
        },
        "depfil": {
            "family": "depfil",
            "path": _first_path(parsed, "depfil"),
            "provenance": "reference_config",
            "status": "partial",
            "runtime_stage": "post_initialize.native_depthwt_loader",
            "notes": "Original EDDA uses `depfil` for the initial water-table-depth grid when scalar `depth < 0`; current backend now supports that per-cell initialization branch and otherwise keeps the scalar fallback active.",
            "blocked_reason": "Only the original `depth < 0` branch is wired; current backend still has no broader canonical groundwater-depth family parity outside this initialization path.",
            "activation_condition": "Consume `depfil` only when the original scalar fallback is disabled (`depth < 0`) and a usable raster exists on disk.",
            "status_basis": "Original `edda main program.F90`, `infr.F90`, and `dfs.F90` consume `depth(i)`; current backend now closes that per-cell initialization branch without changing DFS formulas.",
        },
        "rizerofil": {
            "family": "rizerofil",
            "path": _first_path(parsed, "rizerofil"),
            "provenance": "reference_config",
            "status": "partial",
            "runtime_stage": "post_initialize.native_rizero_loader",
            "notes": "Original EDDA uses `rizerofil` for the initial/background infiltration-rate grid when scalar `rizero < 0`; current backend now supports that per-cell initialization branch and otherwise keeps the scalar fallback active.",
            "blocked_reason": "Only the original `rizero < 0` initialization branch is wired; no separate inflow-sidecar forcing semantics are implied.",
            "activation_condition": "Consume `rizerofil` only when the original scalar fallback is disabled (`rizero < 0`) and a usable raster exists on disk.",
            "status_basis": "Original `steady.f90`, `inidoublelayer.F90`, and `dfs.F90` consume `rizero(i)`; current backend now seeds the same per-cell initialization path without changing runtime formulas.",
        },
        "nxtfil": {
            "family": "nxtfil",
            "path": _first_path(parsed, "nxtfil"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "TopoIndex support file recorded for provenance only.",
            "blocked_reason": "No production TopoIndex runtime path is wired in the current backend.",
            "activation_condition": "Would require the original TopoIndex support-file family and ordering workflow to be implemented.",
            "status_basis": "Current production solver initializes DEM-derived connectivity instead of consuming TopoIndex support files.",
        },
        "ndxfil": {
            "family": "ndxfil",
            "path": _first_path(parsed, "ndxfil"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "TopoIndex support file recorded for provenance only.",
            "blocked_reason": "No production TopoIndex runtime path is wired in the current backend.",
            "activation_condition": "Would require the original TopoIndex support-file family and ordering workflow to be implemented.",
            "status_basis": "Current production solver initializes DEM-derived connectivity instead of consuming TopoIndex support files.",
        },
        "dscfil": {
            "family": "dscfil",
            "path": _first_path(parsed, "dscfil"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "TopoIndex support file recorded for provenance only.",
            "blocked_reason": "No production TopoIndex runtime path is wired in the current backend.",
            "activation_condition": "Would require the original TopoIndex support-file family and ordering workflow to be implemented.",
            "status_basis": "Current production solver initializes DEM-derived connectivity instead of consuming TopoIndex support files.",
        },
        "wffil": {
            "family": "wffil",
            "path": _first_path(parsed, "wffil"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "TopoIndex support file recorded for provenance only.",
            "blocked_reason": "No production TopoIndex runtime path is wired in the current backend.",
            "activation_condition": "Would require the original TopoIndex support-file family and ordering workflow to be implemented.",
            "status_basis": "Current production solver initializes DEM-derived connectivity instead of consuming TopoIndex support files.",
        },
        "outflow.txt": {
            "family": "outflow.txt",
            "path": _first_path(parsed, "outflow.txt"),
            "provenance": "reference_config",
            "status": "partial",
            "runtime_stage": "post_initialize.outflow_sidecar_loader",
            "notes": "Current backend can now load the original outflow-cell sidecar into a selected-cell outflow observer/export chain, but full hydraulic parity with original outflow-only routing is still partial.",
            "blocked_reason": "Current backend still keeps generic edge/outflow handling alongside the sidecar-selected observer path, so original hydraulic parity remains incomplete.",
            "activation_condition": "Consume `outflow.txt` only when the sidecar exists and original `simulate_outflow_cell` is active.",
            "status_basis": "Original EDDA reads `outflow.txt` when `outflowsimul` is enabled, zeroes selected outflow cells during DFS, and later writes `OUTNQ_` files; current backend now closes the selected-cell observation/export chain but not full routing parity.",
            "structure_summary": _structure_summary(parsed, "outflow.txt"),
        },
        "hydrograph.txt": {
            "family": "hydrograph.txt",
            "path": _first_path(parsed, "hydrograph.txt"),
            "provenance": "reference_config",
            "status": "partial",
            "runtime_stage": "post_initialize.hydrograph_monitor_loader",
            "notes": "Current backend can load hydrosave-selected monitored cells and emit original-style HYDROGRAPH text output; non-zero active oracle coverage remains partial.",
            "blocked_reason": "Hydrograph monitored-output parity is proven only against the source-backed zero-flow synthetic oracle so far.",
            "activation_condition": "Consume `hydrograph.txt` only when the sidecar exists and original `save_hydrograph_cells` is active.",
            "status_basis": "Original EDDA reads `hydrograph.txt` when `hydrosave` is enabled and later writes `HYDROGRAPH_` files; current backend now closes the monitored-cell observation/export chain for source-backed checkpoint samples.",
            "structure_summary": hydrograph_structure,
        },
        "inflow.txt": {
            "family": "inflow.txt",
            "path": _first_path(parsed, "inflow.txt"),
            "provenance": "reference_config",
            "status": "partial",
            "runtime_stage": "post_initialize.inflow_sidecar_loader",
            "notes": "Original inflow sidecar exists and current backend can now map the active `inflow.txt` branch into DFS inflow-forcing staging for supported production runs.",
            "blocked_reason": "Current backend now closes the inflow forcing chain, but full original log/report parity remains incomplete and the legacy modular solver path still has no equivalent inflow contract.",
            "activation_condition": "Consume `inflow.txt` only when the sidecar exists and original `simulate_inflow_hydrograph` is active.",
            "status_basis": "Original EDDA reads `inflow.txt` when `inflowsimul` is enabled and injects inflow forcing inside `dfs.F90`/`wfs.F90`; current backend now wires the same sidecar into DFS staging fields and inflow-volume accounting.",
            "structure_summary": _structure_summary(parsed, "inflow.txt"),
        },
        "drainage.txt": {
            "family": "drainage.txt",
            "path": _first_path(parsed, "drainage.txt"),
            "provenance": "reference_config",
            "status": "partial",
            "runtime_stage": "post_initialize.stormdrain_runtime_hook",
            "notes": "Generated original stormdrain topology; consumed only by the default-off EDDA_EXPERIMENT_STORMDRAIN runtime hook.",
            "blocked_reason": "Stormdrain runtime remains experimental/default-off and activates only with EDDA_EXPERIMENT_STORMDRAIN=1.",
            "activation_condition": "Consume `drainage.txt` only when original `dwsimul` is active, the file exists, and EDDA_EXPERIMENT_STORMDRAIN=1.",
            "status_basis": "Original EDDA uses `getdwinput`/`readdrainage` to load node/conduit topology when `dwsimul` is enabled; current hook matches the copied-20a oracle for traced depth/volume terms behind an explicit flag.",
            "structure_summary": _structure_summary(parsed, "drainage.txt"),
        },
        "swmm.txt": {
            "family": "swmm.txt",
            "path": _first_path(parsed, "swmm.txt"),
            "provenance": "reference_config",
            "status": "recognized-only",
            "runtime_stage": "none",
            "notes": "Original getdwinput source file recorded for provenance; current hook consumes generated drainage.txt topology.",
            "blocked_reason": "Current stormdrain hook does not rerun original getdwinput from SWMM text.",
            "activation_condition": "Original source consumes `swmm.txt` when dwsimul is active; current consumes `drainage.txt` after original-compatible generation.",
            "status_basis": "The accepted copied-20a oracle used a coordinate-compatible SWMM file to generate drainage.txt; current runtime parity is against the generated topology.",
            "structure_summary": _structure_summary(parsed, "swmm.txt"),
        },
    }
    rainfall_config, rainfall_audit = _build_rainfall_forcing(parsed, output_dir, native_files)
    input_source_registry = _build_reference_input_source_registry(parsed)
    failure_schedule_registry = input_source_registry.get("dfs_failure_source_variant", {})
    failure_schedule_locator = failure_schedule_registry.get("artifact_locator") or {}
    failure_schedule_artifacts_present = bool(failure_schedule_locator.get("all_required_present"))

    config_dict: Dict[str, Any] = {
        "dem_file": _first_path(parsed, "demfil"),
        "rainfall": rainfall_config,
        "output_dir": str(output_dir),
        "output_format": "geotiff",
        "save_intermediate": True,
        "time": {
            "t_start": 0.0,
            "t_end": parsed.simul,
            "dt_initial": 1.0,
            "dt_min": parsed.dtmin,
            "dt_max": parsed.dtmax,
            "dt_output": parsed.tout,
            "CFL": 0.5,
            "dt_increase": parsed.dti,
            "dt_decrease": parsed.dtd,
            "toldh": parsed.toldh,
            "toldhp": parsed.toldhp,
            "wavemax": parsed.wavemax,
        },
        "hydrology": {
            "K_sat": default_zone.top.k_sat,
            "theta_s": default_zone.top.theta_sat,
            "theta_i": default_zone.top.theta_ini,
            "psi_f": default_zone.top.psi_f,
            "depthwt_initial": parsed.depth,
            "rizero_initial": parsed.rizero,
            "use_background_flux_offset": parsed.background_flux_offset,
            "dfs_infiltration_variant": parsed.dfs_infiltration_variant,
            "dfs_face_flux_variant": parsed.dfs_face_flux_variant,
            "dfs_failure_source_variant": parsed.dfs_failure_source_variant,
            "inflow_denominator_variant": parsed.inflow_denominator_variant,
            "inflow_denominator_direction": parsed.inflow_denominator_direction,
            "inflow_denominator_fv_value": parsed.inflow_denominator_fv_value,
        },
        "soil": {
            "c": default_zone.top.c,
            "phi": default_zone.top.phi,
            "gamma_s": default_zone.top.gamma_s,
            "gamma_w": parsed.uww,
            "depth": parsed.depth,
            "double_layer": {
                "enabled": True,
                "nzst": parsed.nzst,
                "nzsb": parsed.nzsb,
                "ltstar": ltstar_default,
                "lbstar": parsed.lbstar,
                "zmin": 0.001,
                "uww": parsed.uww,
                "min_slope_angle_deg": parsed.min_slope_angle_deg,
                "top_layer": {
                    "c": default_zone.top.c,
                    "phi": default_zone.top.phi,
                    "phib": default_zone.top.phib,
                    "gamma_s": default_zone.top.gamma_s,
                    "K_sat": default_zone.top.k_sat,
                    "theta_sat": default_zone.top.theta_sat,
                    "theta_res": default_zone.top.theta_res,
                    "theta_ini": default_zone.top.theta_ini,
                    "alpha": default_zone.top.alpha,
                    "diffusivity": default_zone.top.diffusivity,
                },
                "bottom_layer": {
                    "c": default_zone.bottom.c,
                    "phi": default_zone.bottom.phi,
                    "phib": default_zone.bottom.phib,
                    "gamma_s": default_zone.bottom.gamma_s,
                    "K_sat": default_zone.bottom.k_sat,
                    "theta_sat": default_zone.bottom.theta_sat,
                    "theta_res": default_zone.bottom.theta_res,
                    "theta_ini": default_zone.bottom.theta_ini,
                    "alpha": default_zone.bottom.alpha,
                    "diffusivity": default_zone.bottom.diffusivity,
                },
            },
        },
        "rheology": {
            "n_manning": parsed.manning_global,
            "alpha1": parsed.alpha1,
            "beta1": parsed.beta1,
            "alpha2": parsed.alpha2,
            "beta2": parsed.beta2,
            "rho_water": 1000.0,
            "rho_sediment": 2650.0,
            "Cv_threshold": 0.2,
            "Cv_max": parsed.cvstar,
            "limitfr": parsed.limitfr,
            "manningb": 0.0538,
            "manningm": 6.0896,
            "kresis": parsed.kresis,
            "cs": parsed.cs,
            "shallown": parsed.shallown,
        },
        "erosion": {
            "tau_c": default_zone.top.ctao,
            "ctao": default_zone.top.ctao,
            "k_erosion": default_zone.top.kero,
            "v_critical": 0.5,
            "k_deposition": parsed.coedepo,
            "d50": parsed.d50,
            "coedepo": parsed.coedepo,
        },
        "compute": {
            "backend": "auto",
            "use_double_precision": True,
        },
        "boundary_conditions": {
            "mode": "auto",
            "default_type": "outflow",
            "include_nodata": True,
        },
        "spatial_zones": {
            "enabled": True,
            "zone_file": _first_path(parsed, "zonfil"),
            "num_zones": len(zone_ids),
            "zones": zones_cfg,
        },
        "native_inputs": {
            "enabled": True,
            "source_mode": "reference_config",
            "reference_config_file": parsed.reference_config_file,
            "reference_base_dir": parsed.reference_base_dir,
            "parser_version": "S1",
            "files": native_files,
        },
    }

    if top_level_overrides:
        for key in ("dem_file", "rainfall_file", "soil_zones_file"):
            value = top_level_overrides.get(key)
            if value:
                config_dict[key] = value

    config_dict = _deep_merge(config_dict, config_overrides)
    config = SimulationConfig.from_dict(config_dict)
    sidecar_output_parity = _build_sidecar_output_parity(parsed, native_files)

    runtime_input_manifest = {
        "generated_at": _timestamp(),
        "source_mode": "reference_config",
        "reference_config_file": parsed.reference_config_file,
        "reference_base_dir": parsed.reference_base_dir,
        "helper_fallback_used": False,
        "rainfall_mode": parsed.rainfall_mode,
        "manning_source": parsed.manning_source,
        "input_source_registry": input_source_registry,
        "period_source_map": parsed.period_source_map,
        "reference_case_activation": _reference_case_activation_snapshot(parsed, input_source_registry),
        "reference_output_expectations": parsed.reference_output_expectations,
        "sidecar_output_parity": sidecar_output_parity,
        "inputs": [
            _native_file_entry("reference_config", parsed.reference_config_file, "reference_config", "production-reachable", "parse.reference_config", consumed=True),
            _native_file_entry("demfil", config.dem_file, "reference_config", "production-reachable", "initialize.dem_reader", **_reference_file_state(parsed, "demfil", input_source_registry)),
            _native_file_entry(
                "rainfall_schedule" if rainfall_config["mode"] == "single_file" else "rainfall_spatial_series",
                rainfall_config.get("file") or rainfall_config.get("directory"),
                "generated_from_reference_config",
                "production-reachable",
                "initialize.rainfall_reader",
                notes=rainfall_audit["active_source"],
            ),
            _native_file_entry(
                "rifil",
                native_files["rifil"]["path"],
                "reference_config",
                native_files["rifil"]["status"],
                native_files["rifil"]["runtime_stage"],
                notes=native_files["rifil"]["notes"],
                **_reference_file_state(parsed, "rifil", input_source_registry),
            ),
            _native_file_entry("zonfil", config.spatial_zones.zone_file if config.spatial_zones else None, "reference_config", "production-reachable", "initialize.zone_reader", **_reference_file_state(parsed, "zonfil", input_source_registry)),
            _native_file_entry("slofil", native_files["slofil"]["path"], "reference_config", "production-reachable", "post_initialize.native_slope_loader", notes=native_files["slofil"]["notes"], **_reference_file_state(parsed, "slofil", input_source_registry)),
            _native_file_entry(
                "zfil",
                native_files["zfil"]["path"],
                "reference_config",
                native_files["zfil"]["status"],
                native_files["zfil"]["runtime_stage"],
                notes=native_files["zfil"]["notes"],
                blocked_reason=native_files["zfil"]["blocked_reason"],
                activation_condition=native_files["zfil"]["activation_condition"],
                status_basis=native_files["zfil"]["status_basis"],
                **_reference_file_state(parsed, "zfil", input_source_registry),
            ),
            _native_file_entry(
                "manningfil",
                native_files["manningfil"]["path"],
                "reference_config",
                native_files["manningfil"]["status"],
                native_files["manningfil"]["runtime_stage"],
                notes=native_files["manningfil"]["notes"],
                blocked_reason=native_files["manningfil"]["blocked_reason"],
                activation_condition=native_files["manningfil"]["activation_condition"],
                status_basis=native_files["manningfil"]["status_basis"],
                **_reference_file_state(parsed, "manningfil", input_source_registry),
            ),
            _native_file_entry("manning_global", None, "reference_config", "production-reachable", "initialize.spatial_zone_or_uniform_fields", consumed=parsed.manning_source == "global_initiation_manning", notes=f"Global initiation Manning value: {parsed.manning_global}"),
            _native_file_entry("dirfil", native_files["dirfil"]["path"], "reference_config", "recognized-only", "none", notes=native_files["dirfil"]["notes"], blocked_reason=native_files["dirfil"]["blocked_reason"], activation_condition=native_files["dirfil"]["activation_condition"], status_basis=native_files["dirfil"]["status_basis"], **_reference_file_state(parsed, "dirfil", input_source_registry)),
            _native_file_entry("depfil", native_files["depfil"]["path"], "reference_config", native_files["depfil"]["status"], native_files["depfil"]["runtime_stage"], notes=native_files["depfil"]["notes"], blocked_reason=native_files["depfil"]["blocked_reason"], activation_condition=native_files["depfil"]["activation_condition"], status_basis=native_files["depfil"]["status_basis"], **_reference_file_state(parsed, "depfil", input_source_registry)),
            _native_file_entry("rizerofil", native_files["rizerofil"]["path"], "reference_config", native_files["rizerofil"]["status"], native_files["rizerofil"]["runtime_stage"], notes=native_files["rizerofil"]["notes"], blocked_reason=native_files["rizerofil"]["blocked_reason"], activation_condition=native_files["rizerofil"]["activation_condition"], status_basis=native_files["rizerofil"]["status_basis"], **_reference_file_state(parsed, "rizerofil", input_source_registry)),
            _native_file_entry("nxtfil", native_files["nxtfil"]["path"], "reference_config", "recognized-only", "none", notes=native_files["nxtfil"]["notes"], blocked_reason=native_files["nxtfil"]["blocked_reason"], activation_condition=native_files["nxtfil"]["activation_condition"], status_basis=native_files["nxtfil"]["status_basis"], **_reference_file_state(parsed, "nxtfil", input_source_registry)),
            _native_file_entry("ndxfil", native_files["ndxfil"]["path"], "reference_config", "recognized-only", "none", notes=native_files["ndxfil"]["notes"], blocked_reason=native_files["ndxfil"]["blocked_reason"], activation_condition=native_files["ndxfil"]["activation_condition"], status_basis=native_files["ndxfil"]["status_basis"], **_reference_file_state(parsed, "ndxfil", input_source_registry)),
            _native_file_entry("dscfil", native_files["dscfil"]["path"], "reference_config", "recognized-only", "none", notes=native_files["dscfil"]["notes"], blocked_reason=native_files["dscfil"]["blocked_reason"], activation_condition=native_files["dscfil"]["activation_condition"], status_basis=native_files["dscfil"]["status_basis"], **_reference_file_state(parsed, "dscfil", input_source_registry)),
            _native_file_entry("wffil", native_files["wffil"]["path"], "reference_config", "recognized-only", "none", notes=native_files["wffil"]["notes"], blocked_reason=native_files["wffil"]["blocked_reason"], activation_condition=native_files["wffil"]["activation_condition"], status_basis=native_files["wffil"]["status_basis"], **_reference_file_state(parsed, "wffil", input_source_registry)),
            _native_file_entry("outflow.txt", native_files["outflow.txt"]["path"], "reference_config", native_files["outflow.txt"]["status"], native_files["outflow.txt"]["runtime_stage"], notes=native_files["outflow.txt"]["notes"], blocked_reason=native_files["outflow.txt"]["blocked_reason"], activation_condition=native_files["outflow.txt"]["activation_condition"], status_basis=native_files["outflow.txt"]["status_basis"], structure_summary=native_files["outflow.txt"].get("structure_summary"), **_reference_file_state(parsed, "outflow.txt", input_source_registry)),
            _native_file_entry("hydrograph.txt", native_files["hydrograph.txt"]["path"], "reference_config", native_files["hydrograph.txt"]["status"], native_files["hydrograph.txt"]["runtime_stage"], notes=native_files["hydrograph.txt"]["notes"], blocked_reason=native_files["hydrograph.txt"]["blocked_reason"], activation_condition=native_files["hydrograph.txt"]["activation_condition"], status_basis=native_files["hydrograph.txt"]["status_basis"], structure_summary=native_files["hydrograph.txt"].get("structure_summary"), **_reference_file_state(parsed, "hydrograph.txt", input_source_registry)),
            _native_file_entry("inflow.txt", native_files["inflow.txt"]["path"], "reference_config", native_files["inflow.txt"]["status"], native_files["inflow.txt"]["runtime_stage"], notes=native_files["inflow.txt"]["notes"], blocked_reason=native_files["inflow.txt"]["blocked_reason"], activation_condition=native_files["inflow.txt"]["activation_condition"], status_basis=native_files["inflow.txt"]["status_basis"], structure_summary=native_files["inflow.txt"].get("structure_summary"), **_reference_file_state(parsed, "inflow.txt", input_source_registry)),
            _native_file_entry("drainage.txt", native_files["drainage.txt"]["path"], "reference_config", native_files["drainage.txt"]["status"], native_files["drainage.txt"]["runtime_stage"], notes=native_files["drainage.txt"]["notes"], blocked_reason=native_files["drainage.txt"]["blocked_reason"], activation_condition=native_files["drainage.txt"]["activation_condition"], status_basis=native_files["drainage.txt"]["status_basis"], structure_summary=native_files["drainage.txt"].get("structure_summary"), **_reference_file_state(parsed, "drainage.txt", input_source_registry)),
            _native_file_entry("swmm.txt", native_files["swmm.txt"]["path"], "reference_config", native_files["swmm.txt"]["status"], native_files["swmm.txt"]["runtime_stage"], notes=native_files["swmm.txt"]["notes"], blocked_reason=native_files["swmm.txt"]["blocked_reason"], activation_condition=native_files["swmm.txt"]["activation_condition"], status_basis=native_files["swmm.txt"]["status_basis"], structure_summary=native_files["swmm.txt"].get("structure_summary"), **_reference_file_state(parsed, "swmm.txt", input_source_registry)),
        ],
    }
    if parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule":
        runtime_input_manifest["inputs"].append(
            _native_file_entry(
                "precomputed_unsfin_schedule",
                None,
                "original_instrumentation_artifact",
                "partial" if failure_schedule_artifacts_present else "blocked",
                "post_initialize.precomputed_unsfin_schedule_loader",
                notes=(
                    "Original EDDA `unsfin` gindx/tfail/fdepth artifacts are present and can be loaded as an explicit schedule provider."
                    if failure_schedule_artifacts_present
                    else "Original EDDA `unsfin` gindx/tfail/fdepth artifacts are not present; current must not infer `tfail` from LS_Scar/faildph."
                ),
                blocked_reason=(
                    None
                    if failure_schedule_artifacts_present
                    else "Validated original `precomputed_unsfin_*` artifacts are required before the precomputed schedule branch can run."
                ),
                activation_condition="Only active when source trace selects `precomputed_unsfin_schedule` and all original artifact files are provided.",
                status_basis=parsed.dfs_failure_source_variant_basis,
                structure_summary=failure_schedule_locator,
                input_state="file_backed" if failure_schedule_artifacts_present else "truly_missing",
                selected_source=failure_schedule_registry.get("selected_source"),
                source_registry_key="dfs_failure_source_variant",
            )
        )
    _annotate_manifest_with_input_source_registry(runtime_input_manifest, input_source_registry)

    effective_config = {
        "generated_at": _timestamp(),
        "source_mode": "reference_config",
        "config": config.to_dict(),
        "reference_config_file": parsed.reference_config_file,
        "reference_config_supported_fields": parsed.supported_fields,
        "reference_config_effective_sources": {
            "rainfall": parsed.rainfall_mode,
            "manning": parsed.manning_source,
            "period_source_map": parsed.period_source_map,
        },
        "input_source_registry": input_source_registry,
        "reference_case_activation": _reference_case_activation_snapshot(parsed, input_source_registry),
        "reference_output_expectations": parsed.reference_output_expectations,
        "sidecar_output_parity": sidecar_output_parity,
        "reference_config_sidecars": {
            family: native_files[family]["structure_summary"]
            for family in ("inflow.txt", "outflow.txt", "hydrograph.txt", "drainage.txt", "swmm.txt")
            if native_files.get(family, {}).get("structure_summary") is not None
        },
        "reference_config_semantic_alerts": {
            "zfil": native_files["zfil"]["status_basis"],
            "zmax": "Scalar `zmax` was parsed from the reference config, but no canonical current-backend consumer exists.",
        },
        "rainfall_audit": rainfall_audit,
    }

    provenance = {
        "generated_at": _timestamp(),
        "source_mode": "reference_config",
        "helper_fallback_used": False,
        "reference_config_file": parsed.reference_config_file,
        "reference_config_audit": parsed.to_audit_dict(),
        "reference_output_expectations": parsed.reference_output_expectations,
        "sidecar_output_parity": sidecar_output_parity,
        "input_source_registry": input_source_registry,
        "rainfall_audit": rainfall_audit,
        "period_source_map": parsed.period_source_map,
        "manning_source": parsed.manning_source,
        "unsupported_flags": parsed.unsupported_flags,
    }

    return config, effective_config, runtime_input_manifest, provenance


def build_direct_runtime_metadata(config: SimulationConfig) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    native_file_configs = (
        getattr(config.native_inputs, "files", {}) if getattr(config, "native_inputs", None) else {}
    )

    def native_path(family: str) -> Optional[str]:
        item = native_file_configs.get(family) if native_file_configs else None
        return getattr(item, "path", None) if item is not None else None

    def native_original_branch_active(family: str, default: bool = False) -> bool:
        item = native_file_configs.get(family) if native_file_configs else None
        value = getattr(item, "original_branch_active", None) if item is not None else None
        return default if value is None else bool(value)

    input_source_registry = {
        "water_table_source": {
            "family": "depfil",
            "state": "config_fallback",
            "selected_source": "config_depth",
            "config_value": getattr(config.hydrology, "depthwt_initial", None),
            "status_basis": "Direct API payload uses canonical scalar groundwater-depth fields rather than original `depfil` sidecars.",
        },
        "initial_infiltration_source": {
            "family": "rizerofil",
            "state": "config_fallback",
            "selected_source": "config_rizero",
            "config_value": getattr(config.hydrology, "rizero_initial", None),
            "status_basis": "Direct API payload uses canonical scalar infiltration fields rather than original `rizerofil` sidecars.",
        },
        "manning_source": {
            "family": "manningfil",
            "state": "config_fallback",
            "selected_source": "global_manning",
            "config_value": getattr(config.rheology, "n_manning", None),
            "status_basis": "Direct API payload provides canonical scalar Manning values unless a production raster path is added explicitly.",
        },
        "rainfall_source": {
            "family": "rifil",
            "state": "file_backed" if (config.rainfall and config.rainfall.mode == "spatial_tif_series") else "config_fallback",
            "selected_source": "raster_rifil" if (config.rainfall and config.rainfall.mode == "spatial_tif_series") else "uniform_cri",
            "status_basis": "Direct API payload routes rainfall through canonical schedule or spatial-series config fields.",
        },
        "outflow_point_source": {
            "family": "outflow.txt",
            "state": "truly_missing",
            "selected_source": None,
            "status_basis": "Direct API payload mode does not imply original `outflow.txt` sidecar semantics unless a dedicated sidecar contract is supplied.",
        },
        "inflow_source": {
            "family": "inflow.txt",
            "state": "config_fallback",
            "selected_source": None,
            "runtime_active": False,
            "status_basis": "Direct API payload mode does not imply original `inflow.txt` sidecar semantics unless a dedicated sidecar contract is supplied.",
        },
    }
    if native_path("manningfil"):
        input_source_registry["manning_source"].update(
            {
                "state": "file_backed",
                "selected_source": "raster_manningfil",
                "path": native_path("manningfil"),
                "status_basis": "Frontend uploaded `manningfil`; direct runtime manifest exposes it to the native Manning loader.",
            }
        )
    if native_path("rifil"):
        input_source_registry["rainfall_source"].update(
            {
                "state": "file_backed",
                "selected_source": "raster_rifil",
                "path": native_path("rifil"),
                "status_basis": "Frontend uploaded `rifil`; direct runtime manifest records the non-uniform rainfall source.",
            }
        )
    if native_path("outflow.txt"):
        outflow_active = native_original_branch_active("outflow.txt", True)
        input_source_registry["outflow_point_source"].update(
            {
                "state": "file_backed",
                "selected_source": "outflow_txt",
                "path": native_path("outflow.txt"),
                "runtime_active": outflow_active,
                "status_basis": "Frontend uploaded `outflow.txt`; direct runtime manifest exposes it to the selected-cell outflow loader.",
            }
        )
    if native_path("inflow.txt"):
        inflow_active = native_original_branch_active("inflow.txt", False)
        input_source_registry["inflow_source"].update(
            {
                "state": "file_backed",
                "selected_source": "inflow_txt",
                "path": native_path("inflow.txt"),
                "runtime_active": inflow_active,
                "status_basis": (
                    "Frontend uploaded `inflow.txt`; runtime consumption follows original "
                    "`simulate_inflow_hydrograph` activation instead of file presence alone."
                ),
            }
        )
    runtime_input_manifest = {
        "generated_at": _timestamp(),
        "source_mode": "api_payload",
        "helper_fallback_used": False,
        "input_source_registry": input_source_registry,
        "inputs": [
            _native_file_entry("demfil", config.dem_file, "api_payload", "production-reachable", "initialize.dem_reader", consumed=False, status_basis="Direct API payload provides the DEM path using canonical backend config fields."),
        ],
    }

    rainfall_family = None
    rainfall_path = None
    rainfall_stage = "initialize.rainfall_reader"
    if config.rainfall and config.rainfall.mode == "spatial_tif_series" and config.rainfall.directory:
        rainfall_family = "rainfall_spatial_series"
        rainfall_path = config.rainfall.directory
    else:
        if config.rainfall and config.rainfall.file:
            rainfall_path = config.rainfall.file
        elif config.rainfall_file:
            rainfall_path = config.rainfall_file
        if rainfall_path:
            rainfall_family = "rainfall_schedule"
    if rainfall_family and rainfall_path:
        runtime_input_manifest["inputs"].append(
            _native_file_entry(
                rainfall_family,
                rainfall_path,
                "api_payload",
                "production-reachable",
                rainfall_stage,
                status_basis="Direct API payload routes rainfall through the canonical FastAPI -> solver initialization chain.",
            )
        )

    if config.spatial_zones and config.spatial_zones.zone_file:
        runtime_input_manifest["inputs"].append(
            _native_file_entry("zonfil", config.spatial_zones.zone_file, "api_payload", "production-reachable", "initialize.zone_reader", status_basis="Direct API payload provides the zone raster through canonical backend config fields.")
        )

    if config.boundary_conditions and config.boundary_conditions.boundary_file:
        runtime_input_manifest["inputs"].append(
            _native_file_entry("boundary_file", config.boundary_conditions.boundary_file, "api_payload", "production-reachable", "initialize.boundary_loader", status_basis="Boundary file is consumed during solver boundary initialization when boundary_conditions.mode='file'.")
        )
    existing_families = {item.get("family") for item in runtime_input_manifest.get("inputs", [])}
    for family, file_cfg in native_file_configs.items():
        path = getattr(file_cfg, "path", None)
        if not path or family in existing_families:
            continue
        production_status = getattr(file_cfg, "status", "recognized")
        runtime_stage = getattr(file_cfg, "runtime_stage", "none")
        entry = _native_file_entry(
            family,
            path,
            getattr(file_cfg, "provenance", "api_payload"),
            production_status,
            runtime_stage,
            notes=getattr(file_cfg, "notes", None),
            blocked_reason=getattr(file_cfg, "blocked_reason", None),
            activation_condition=getattr(file_cfg, "activation_condition", None),
            status_basis=getattr(file_cfg, "status_basis", None),
        )
        if family in {"outflow.txt", "hydrograph.txt", "inflow.txt"}:
            try:
                entry["structure_summary"] = parse_case_sidecar(Path(path), family, dem_file=Path(config.dem_file))
            except Exception as exc:
                entry["structure_summary"] = {
                    "family": family,
                    "path": path,
                    "parse_status": "failed",
                    "error": str(exc),
                }
        if family == "outflow.txt":
            active = native_original_branch_active("outflow.txt", True)
            entry["original_branch_active"] = active
            entry["current_backend_branch_active"] = active
        if family == "inflow.txt":
            active = native_original_branch_active("inflow.txt", False)
            entry["original_branch_active"] = active
            entry["current_backend_branch_active"] = active
        runtime_input_manifest["inputs"].append(entry)
        existing_families.add(family)
    _annotate_manifest_with_input_source_registry(runtime_input_manifest, input_source_registry)

    effective_config = {
        "generated_at": _timestamp(),
        "source_mode": "api_payload",
        "config": config.to_dict(),
        "input_source_registry": input_source_registry,
    }
    provenance = {
        "generated_at": _timestamp(),
        "source_mode": "api_payload",
        "helper_fallback_used": False,
        "reference_config_audit": None,
        "input_source_registry": input_source_registry,
    }
    return effective_config, runtime_input_manifest, provenance


def _validate_raster_shape(grid: np.ndarray, solver: Any, family: str) -> None:
    expected = (solver.fields.ny, solver.fields.nx)
    if grid.shape != expected:
        raise ValueError(
            f"Native input `{family}` shape {grid.shape} does not match DEM shape {expected}."
        )


def _median_fill_value(grid: np.ndarray, nodata_value: Any, fallback: float) -> float:
    if nodata_value is None:
        valid = grid[np.isfinite(grid)]
    else:
        valid = grid[~np.isclose(grid, nodata_value)]
    if valid.size == 0:
        return fallback
    return float(np.median(valid))


def apply_native_runtime_inputs(solver: Any, runtime_input_manifest: Dict[str, Any]) -> Dict[str, Any]:
    _mark_manifest_entry(runtime_input_manifest, "demfil", consumed=True)
    rainfall_reader = getattr(solver, "rainfall_reader", None)
    has_spatial_rainfall = bool(rainfall_reader is not None and getattr(rainfall_reader, "spatial_data", None) is not None)
    has_schedule_rainfall = bool(rainfall_reader is not None and not has_spatial_rainfall)
    _mark_manifest_entry(runtime_input_manifest, "rainfall_schedule", consumed=has_schedule_rainfall)
    _mark_manifest_entry(runtime_input_manifest, "rainfall_spatial_series", consumed=has_spatial_rainfall)
    rifil_entry = next((item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == "rifil"), None)
    if rifil_entry and rifil_entry.get("production_status") == "production-reachable":
        _mark_manifest_entry(runtime_input_manifest, "rifil", consumed=has_spatial_rainfall)
    if getattr(solver.config, "spatial_zones", None) and solver.config.spatial_zones and solver.config.spatial_zones.zone_file:
        _mark_manifest_entry(runtime_input_manifest, "zonfil", consumed=True)
    if (
        getattr(solver.config, "boundary_conditions", None)
        and solver.config.boundary_conditions
        and solver.config.boundary_conditions.boundary_file
    ):
        _mark_manifest_entry(runtime_input_manifest, "boundary_file", consumed=True)

    scalar_depthwt = float(getattr(solver.config.hydrology, "depthwt_initial", 0.0))
    scalar_rizero = float(getattr(solver.config.hydrology, "rizero_initial", 0.0))

    for family in ("slofil", "manningfil", "zfil", "depfil", "rizerofil"):
        entry = next((item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == family), None)
        if not entry or not entry.get("path"):
            continue
        branch_active = entry.get("original_branch_active")
        if family in {"depfil", "rizerofil"} and branch_active is False:
            _mark_manifest_entry(
                runtime_input_manifest,
                family,
                consumed=False,
                current_backend_branch_active=False,
                default_substitution_used=True,
                notes=(entry.get("notes") or "") + " Original scalar fallback remains active for this run.",
            )
            continue
        path = Path(entry["path"])
        if not path.exists():
            if family == "manningfil":
                _mark_manifest_entry(
                    runtime_input_manifest,
                    family,
                    consumed=False,
                    missing_on_disk=True,
                    default_substitution_used=True,
                    notes=(entry.get("notes") or "") + " Declared Manning raster is missing; runtime uses the global initiation Manning coefficient.",
                )
                _mark_manifest_entry(runtime_input_manifest, "manning_global", consumed=True)
                continue
            if family == "depfil":
                solver.dfs_dynamic_wave.set_initial_depthwt_field(None)
                _mark_manifest_entry(
                    runtime_input_manifest,
                    family,
                    consumed=False,
                    missing_on_disk=True,
                    default_substitution_used=True,
                    current_backend_branch_active=False,
                    notes=(entry.get("notes") or "") + f" Declared depfil raster is missing; runtime kept scalar depthwt_initial={scalar_depthwt}.",
                )
                continue
            if family == "rizerofil":
                solver.dfs_dynamic_wave.set_initial_rizero_field(None)
                if getattr(solver, "double_layer", None):
                    rikzero_np = solver.double_layer.build_initial_rikzero_field(scalar_rizero)
                    solver.double_layer.initialize_double_layer(rikzero_np.astype(solver.numpy_float_dtype))
                    solver.dfs_dynamic_wave.set_initial_rikzero_field(rikzero_np)
                _mark_manifest_entry(
                    runtime_input_manifest,
                    family,
                    consumed=False,
                    missing_on_disk=True,
                    default_substitution_used=True,
                    current_backend_branch_active=False,
                    notes=(entry.get("notes") or "") + f" Declared rizerofil raster is missing; runtime kept scalar rizero_initial={scalar_rizero}.",
                )
                continue
            _mark_manifest_entry(
                runtime_input_manifest,
                family,
                consumed=False,
                missing_on_disk=True,
                default_substitution_used=True,
                notes=(entry.get("notes") or "") + " Declared reference file is missing on disk; runtime kept the existing production value instead of using helper injection.",
            )
            continue

        loader = SpatialInputLoader(entry["path"])
        grid, metadata = loader.read()
        _validate_raster_shape(grid, solver, family)
        nodata_value = metadata.get("nodata")

        if family == "slofil":
            fill_value = _median_fill_value(grid, nodata_value, fallback=0.0)
            slope_deg = fill_raster_nodata(grid, nodata_value, fill_value)
            slope_rad = slope_deg * FORTRAN_DEG2RAD
            slope_tan = np.tan(slope_rad)
            solver.fields.slope_mag.from_numpy(slope_tan.T.astype(solver.numpy_float_dtype))
            solver.fields.slope_angle.from_numpy(slope_rad.T.astype(solver.numpy_float_dtype))
            _mark_manifest_entry(runtime_input_manifest, "slofil", consumed=True, missing_on_disk=False, default_substitution_used=False)
            continue

        if family == "manningfil":
            if entry.get("production_status") == "fallback-to-global":
                _mark_manifest_entry(
                    runtime_input_manifest,
                    "manningfil",
                    consumed=False,
                    missing_on_disk=not path.exists(),
                    default_substitution_used=True,
                )
                _mark_manifest_entry(runtime_input_manifest, "manning_global", consumed=True)
                continue
            fill_value = _median_fill_value(grid, nodata_value, fallback=float(solver.config.rheology.n_manning))
            manning_grid = fill_raster_nodata(grid, nodata_value, fill_value)
            manning_np = manning_grid.T.astype(solver.numpy_float_dtype)
            solver.fields.n_manning_field.from_numpy(manning_np)
            if getattr(solver, "rheology", None) is not None:
                solver.rheology.manning.from_numpy(manning_np)
                solver.rheology.manning_ori.from_numpy(manning_np)
            _mark_manifest_entry(runtime_input_manifest, "manningfil", consumed=True, missing_on_disk=False, default_substitution_used=False)
            continue

        if family == "zfil":
            if not getattr(solver, "double_layer", None):
                _mark_manifest_entry(
                    runtime_input_manifest,
                    "zfil",
                    consumed=False,
                    missing_on_disk=False,
                    default_substitution_used=True,
                    notes="Reference `zfil` was recognized but the current run did not enable double-layer runtime consumption.",
                )
                continue
            fill_value = _median_fill_value(grid, nodata_value, fallback=float(solver.config.soil.double_layer.ltstar))
            ltstar_grid = fill_raster_nodata(grid, nodata_value, fill_value)
            ltstar_np = ltstar_grid.T.astype(solver.numpy_float_dtype)
            solver.fields.ltstar_field.from_numpy(ltstar_np)
            rikzero_np = solver.double_layer.build_initial_rikzero_field(solver.config.hydrology.rizero_initial)
            solver.double_layer.initialize_double_layer(rikzero_np.astype(solver.numpy_float_dtype))
            solver.dfs_dynamic_wave.set_initial_rikzero_field(rikzero_np)
            _mark_manifest_entry(runtime_input_manifest, "zfil", consumed=True, missing_on_disk=False, default_substitution_used=False)
            continue

        if family == "depfil":
            fill_value = _median_fill_value(grid, nodata_value, fallback=scalar_depthwt)
            depthwt_grid = fill_raster_nodata(grid, nodata_value, fill_value)
            solver.dfs_dynamic_wave.set_initial_depthwt_field(depthwt_grid.T.astype(solver.numpy_float_dtype))
            _mark_manifest_entry(
                runtime_input_manifest,
                "depfil",
                consumed=True,
                production_status="partial",
                runtime_stage="post_initialize.native_depthwt_loader",
                missing_on_disk=False,
                default_substitution_used=False,
                current_backend_branch_active=True,
                notes="Per-cell initial water-table depth grid loaded into the original DFS infiltration staging condition.",
            )
            continue

        if family == "rizerofil":
            fill_value = _median_fill_value(grid, nodata_value, fallback=scalar_rizero)
            rizero_grid = fill_raster_nodata(grid, nodata_value, fill_value)
            rizero_np = rizero_grid.T.astype(solver.numpy_float_dtype)
            solver.dfs_dynamic_wave.set_initial_rizero_field(rizero_np)
            if getattr(solver, "double_layer", None):
                rikzero_np = solver.double_layer.build_initial_rikzero_field(rizero_np)
                solver.double_layer.initialize_double_layer(rikzero_np.astype(solver.numpy_float_dtype))
                solver.dfs_dynamic_wave.set_initial_rikzero_field(rikzero_np)
            _mark_manifest_entry(
                runtime_input_manifest,
                "rizerofil",
                consumed=True,
                production_status="partial",
                runtime_stage="post_initialize.native_rizero_loader",
                missing_on_disk=False,
                default_substitution_used=False,
                current_backend_branch_active=True,
                notes="Per-cell initial/background infiltration-rate grid loaded into DFS staging and steady/double-layer initialization.",
            )

    rnoff_topoindex_enabled = str(os.environ.get("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "")).strip() == "1"
    topoindex_entries = {
        family: next((item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == family), None)
        for family in ("nxtfil", "ndxfil", "dscfil", "wffil")
    }
    if rnoff_topoindex_enabled and any(entry and entry.get("path") for entry in topoindex_entries.values()):
        try:
            hook_result = solver.configure_rnoff_topoindex_runtime_hook(
                nxtfil=topoindex_entries["nxtfil"].get("path") if topoindex_entries["nxtfil"] else None,
                ndxfil=topoindex_entries["ndxfil"].get("path") if topoindex_entries["ndxfil"] else None,
                dscfil=topoindex_entries["dscfil"].get("path") if topoindex_entries["dscfil"] else None,
                wffil=topoindex_entries["wffil"].get("path") if topoindex_entries["wffil"] else None,
            )
            runtime_input_manifest["rnoff_topoindex_runtime_hook"] = hook_result
            for family in ("nxtfil", "ndxfil", "dscfil", "wffil"):
                _mark_manifest_entry(
                    runtime_input_manifest,
                    family,
                    consumed=True,
                    production_status="partial",
                    runtime_stage="post_initialize.rnoff_topoindex_runtime_hook",
                    missing_on_disk=False,
                    default_substitution_used=False,
                    current_backend_branch_active=bool(hook_result.get("rnoff_topoindex_runtime_enabled")),
                    blocked_reason=None,
                    notes=(
                        "TopoIndex support file configured into the default-off RNOFF runtime hook. "
                        "The hook affects only ro/rik/ir state and does not replace DFS face connectivity."
                    ),
                    structure_summary={
                        "feature_flag": "EDDA_EXPERIMENT_RNOFF_TOPOINDEX=1",
                        "active_cell_count": hook_result.get("active_cell_count"),
                        "imax": hook_result.get("imax"),
                    },
                )
        except Exception as exc:
            runtime_input_manifest["rnoff_topoindex_runtime_hook"] = {
                "rnoff_topoindex_runtime_enabled": True,
                "rnoff_topoindex_branch_active": False,
                "fail_closed": True,
                "blocked_reason": str(exc),
            }
            for family in ("nxtfil", "ndxfil", "dscfil", "wffil"):
                _mark_manifest_entry(
                    runtime_input_manifest,
                    family,
                    consumed=False,
                    production_status="blocked",
                    runtime_stage="post_initialize.rnoff_topoindex_runtime_hook",
                    current_backend_branch_active=False,
                    blocked_reason=str(exc),
                    notes="TopoIndex RNOFF runtime hook configuration failed closed.",
                )

    stormdrain_enabled = str(os.environ.get("EDDA_EXPERIMENT_STORMDRAIN", "")).strip() == "1"
    stormdrain_entry = next(
        (item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == "drainage.txt"),
        None,
    )
    if stormdrain_enabled and stormdrain_entry and stormdrain_entry.get("original_branch_active"):
        drainage_path = stormdrain_entry.get("path")
        try:
            hook_result = solver.configure_stormdrain_runtime_hook(drainage_path=drainage_path)
            runtime_input_manifest["stormdrain_runtime_hook"] = hook_result
            _mark_manifest_entry(
                runtime_input_manifest,
                "drainage.txt",
                consumed=bool(hook_result.get("stormdrain_runtime_enabled")),
                production_status="partial",
                runtime_stage="post_initialize.stormdrain_runtime_hook",
                missing_on_disk=not bool(hook_result.get("stormdrain_available")),
                default_substitution_used=False,
                current_backend_branch_active=bool(hook_result.get("stormdrain_runtime_enabled")),
                blocked_reason=None if hook_result.get("stormdrain_available") else "drainage.txt missing; stormdrain hook will fail closed on use.",
                notes=(
                    "Generated drainage topology configured into the default-off stormdrain runtime hook. "
                    "The hook affects only stormdrain depth/volume/node/conduit diagnostics and staged surface depth."
                ),
                structure_summary={
                    "feature_flag": "EDDA_EXPERIMENT_STORMDRAIN=1",
                    "active_cell_count": hook_result.get("active_cell_count"),
                    "imax": hook_result.get("imax"),
                },
            )
        except Exception as exc:
            runtime_input_manifest["stormdrain_runtime_hook"] = {
                "stormdrain_runtime_enabled": True,
                "stormdrain_branch_active": False,
                "fail_closed": True,
                "blocked_reason": str(exc),
            }
            _mark_manifest_entry(
                runtime_input_manifest,
                "drainage.txt",
                consumed=False,
                production_status="blocked",
                runtime_stage="post_initialize.stormdrain_runtime_hook",
                current_backend_branch_active=False,
                blocked_reason=str(exc),
                notes="Stormdrain runtime hook configuration failed closed.",
            )

    outflow_entry = next(
        (item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == "outflow.txt"),
        None,
    )
    if outflow_entry and outflow_entry.get("path") and outflow_entry.get("original_branch_active"):
        path = Path(outflow_entry["path"])
        if path.exists():
            structure_summary = outflow_entry.get("structure_summary") or {}
            cell_ids = list(structure_summary.get("cell_ids") or [])
            observer_result = solver.configure_outflow_process_observer(
                cell_ids,
                sidecar_path=str(path),
            )
            if observer_result["configured_cell_count"] > 0:
                _mark_manifest_entry(
                    runtime_input_manifest,
                    "outflow.txt",
                    consumed=True,
                    production_status="partial",
                    runtime_stage="post_initialize.outflow_sidecar_loader",
                    missing_on_disk=False,
                    default_substitution_used=False,
                    current_backend_branch_active=True,
                    notes="Sidecar-selected outflow cells were loaded into the current runtime observer/export chain and boundary registry.",
                    structure_summary={
                        **structure_summary,
                        "configured_cell_count": observer_result["configured_cell_count"],
                        "missing_runtime_cell_ids": observer_result["missing_cell_ids"],
                        "output_filename": observer_result["output_filename"],
                    },
                )
                sidecar_parity = runtime_input_manifest.get("sidecar_output_parity", {}).get("outflow.txt")
                if sidecar_parity:
                    sidecar_parity["parity_status"] = "partial"
                    sidecar_parity["current_backend_branch_active"] = True
                    sidecar_parity["configured_cell_count"] = observer_result["configured_cell_count"]
                    sidecar_parity["missing_runtime_cell_ids"] = observer_result["missing_cell_ids"]
                    sidecar_parity["current_runtime_evidence"] = (
                        "Current backend now loads sidecar-selected outflow cells into a runtime observer/export chain and marks those cells as outflow boundaries, "
                        "but generic edge outflow handling still coexists so full hydraulic parity remains partial."
                    )

    hydrograph_entry = next(
        (item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == "hydrograph.txt"),
        None,
    )
    if hydrograph_entry and hydrograph_entry.get("path") and hydrograph_entry.get("original_branch_active"):
        path = Path(hydrograph_entry["path"])
        if path.exists():
            structure_summary = hydrograph_entry.get("structure_summary") or {}
            cell_ids = list(structure_summary.get("cell_ids") or [])
            observer_result = solver.configure_hydrograph_monitor_observer(
                cell_ids,
                sidecar_path=str(path),
                output_filename=str(structure_summary.get("output_filename") or "HYDROGRAPH_EDDA.txt"),
            )
            if observer_result["configured_cell_count"] > 0:
                _mark_manifest_entry(
                    runtime_input_manifest,
                    "hydrograph.txt",
                    consumed=True,
                    production_status="partial",
                    runtime_stage="post_initialize.hydrograph_monitor_loader",
                    missing_on_disk=False,
                    default_substitution_used=False,
                    current_backend_branch_active=True,
                    notes="Sidecar-selected hydrograph cells were loaded into the monitored-output observer/export chain.",
                    structure_summary={
                        **structure_summary,
                        "configured_cell_count": observer_result["configured_cell_count"],
                        "missing_runtime_cell_ids": observer_result["missing_cell_ids"],
                        "output_filename": observer_result["output_filename"],
                    },
                )
                sidecar_parity = runtime_input_manifest.get("sidecar_output_parity", {}).get("hydrograph.txt")
                if sidecar_parity:
                    sidecar_parity["parity_status"] = "partial"
                    sidecar_parity["current_backend_branch_active"] = True
                    sidecar_parity["configured_cell_count"] = observer_result["configured_cell_count"]
                    sidecar_parity["missing_runtime_cell_ids"] = observer_result["missing_cell_ids"]
                    sidecar_parity["current_runtime_evidence"] = (
                        "Current backend now loads hydrosave-selected `hydrograph.txt` cells into a monitored-output observer "
                        "and writes original-style `HYDROGRAPH_*` text output. Non-zero active oracle coverage remains future work."
                    )

    inflow_entry = next(
        (item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == "inflow.txt"),
        None,
    )
    if inflow_entry and inflow_entry.get("path") and inflow_entry.get("original_branch_active"):
        path = Path(inflow_entry["path"])
        if path.exists():
            dem_path = next(
                (
                    Path(item["path"])
                    for item in runtime_input_manifest.get("inputs", [])
                    if item.get("family") == "demfil" and item.get("path")
                ),
                None,
            )
            inflow_payload = load_inflow_runtime_payload(path, dem_file=dem_path)
            denominator_registry = runtime_input_manifest.get("input_source_registry", {}).get(
                "inflow_denominator_variant",
                {},
            )
            observer_result = solver.configure_inflow_hydrograph_forcing(
                inflow_payload.get("configured_hydrographs", []),
                sidecar_path=str(path),
                denominator_variant=denominator_registry.get("selected_source"),
                denominator_source=denominator_registry.get("path"),
                denominator_basis=denominator_registry.get("status_basis"),
                denominator_direction=denominator_registry.get("direction"),
                denominator_fv_value=denominator_registry.get("fv_component_if_used"),
            )
            if observer_result["configured_cell_count"] > 0:
                structure_summary = inflow_entry.get("structure_summary") or {}
                _mark_manifest_entry(
                    runtime_input_manifest,
                    "inflow.txt",
                    consumed=True,
                    production_status="partial",
                    runtime_stage="post_initialize.inflow_sidecar_loader",
                    missing_on_disk=False,
                    default_substitution_used=False,
                    current_backend_branch_active=True,
                    notes="Sidecar-selected inflow hydrographs were loaded into the DFS runtime staging chain and inflow-volume accounting.",
                    structure_summary={
                        **structure_summary,
                        "configured_cell_count": observer_result["configured_cell_count"],
                        "missing_runtime_cell_ids": observer_result["missing_cell_ids"],
                        "inflow_period_s": inflow_payload.get("inflow_period_s"),
                        "inflow_dt_s": inflow_payload.get("inflow_dt_s"),
                        "configured_preview": observer_result.get("configured_preview", []),
                        "inflow_denominator_variant": observer_result.get("inflow_denominator_variant"),
                        "inflow_denominator_source": observer_result.get("inflow_denominator_source"),
                        "inflow_denominator_direction": observer_result.get("inflow_denominator_direction"),
                        "inflow_denominator_fv_value": observer_result.get("inflow_denominator_fv_value"),
                    },
                )
                sidecar_parity = runtime_input_manifest.get("sidecar_output_parity", {}).get("inflow.txt")
                if sidecar_parity:
                    sidecar_parity["parity_status"] = "partial"
                    sidecar_parity["current_backend_branch_active"] = True
                    sidecar_parity["configured_cell_count"] = observer_result["configured_cell_count"]
                    sidecar_parity["missing_runtime_cell_ids"] = observer_result["missing_cell_ids"]
                    sidecar_parity["current_runtime_evidence"] = (
                        "Current backend now loads active `inflow.txt` hydrographs into DFS staging fields (`tempinflowh/tempinflowrho`) "
                        "and inflow-volume accounting, while original log/report parity remains partial."
                    )

    failure_registry = runtime_input_manifest.get("input_source_registry", {}).get("dfs_failure_source_variant", {})
    truthy = {"1", "true", "yes", "on"}
    native_provider_attempted = (
        str(os.environ.get("EDDA_NATIVE_UNSFIN_RUNTIME_FEED", "")).strip().lower() in truthy
        or str(os.environ.get("EDDA_ENABLE_PRODUCTION_NATIVE_UNSFIN_RUNTIME", "")).strip().lower() in truthy
    )
    force_native_provider_generation = (
        str(os.environ.get("EDDA_FORCE_NATIVE_UNSFIN_PROVIDER_GENERATION", "")).strip().lower() in truthy
    )
    if (
        native_provider_attempted
        and not force_native_provider_generation
        and failure_registry.get("selected_source") == "precomputed_unsfin_schedule"
    ):
        case_dir_value = runtime_input_manifest.get("reference_base_dir")
        locator = (
            find_precomputed_unsfin_artifacts(Path(case_dir_value))
            if case_dir_value
            else {"all_required_present": False}
        )
        if locator.get("all_required_present"):
            runtime_input_manifest["native_unsfin_provider_request"] = {
                "native_provider_attempted": True,
                "bypassed_by_precomputed_unsfin_artifacts": True,
                "bypass_reason": (
                    "case-local precomputed_unsfin_schedule artifacts are present and avoid "
                    "host-side provider dry-run generation for CUDA candidate runs"
                ),
                "force_native_provider_generation_env": "EDDA_FORCE_NATIVE_UNSFIN_PROVIDER_GENERATION",
                "precomputed_unsfin_artifact_locator": locator,
            }
            native_provider_attempted = False
    provider_import_error: Exception | None = None
    if native_provider_attempted:
        try:
            from edda.solver.native_unsfin_provider import (
                NativeUnsfinDryRunRequest,
                configure_provider_runtime_feed,
            )
        except Exception as exc:
            provider_import_error = exc

    if native_provider_attempted and provider_import_error is not None:
        blocked_reason = f"production_native_unsfin runtime feed blocked: PROVIDER_IMPORT_FAILED; {provider_import_error!r}"
        provider_summary = {
            "provider": "production_native_unsfin",
            "mode": "runtime_smoke",
            "provider_available": False,
            "provider_selected": True,
            "dry_run_enabled": True,
            "runtime_feed_enabled": True,
            "schedule_generated": False,
            "schedule_validated": False,
            "schedule_configured_into_solver": False,
            "schedule_consumed_by_dfs": False,
            "source_provenance": "production_native_unsfin",
            "output_inferred": False,
            "blocked_reason": "PROVIDER_IMPORT_FAILED",
            "blocked_detail": repr(provider_import_error),
        }
        failure_registry.update(
            {
                "selected_source": "production_native_unsfin",
                "schedule_provider": "production_native_unsfin",
                "schedule_loaded": False,
                "runtime_active": False,
                "runtime_equivalent_implemented": False,
                "provider_available": False,
                "provider_selected": True,
                "dry_run_enabled": True,
                "runtime_feed_enabled": True,
                "schedule_generated": False,
                "schedule_validated": False,
                "schedule_configured_into_solver": False,
                "schedule_consumed_by_dfs": False,
                "source_provenance": "production_native_unsfin",
                "output_inferred": False,
                "tfail_positive_count": 0,
                "gindx_positive_count": 0,
                "fdepth_positive_count": 0,
                "consumed_count": 0,
                "committed_fired_count": 0,
                "duplicate_fire_count": 0,
                "rejected_step_discard_count": 0,
                "total_staged_depth_sum": 0.0,
                "total_staged_mass_sum": 0.0,
                "artifact_paths": {},
                "runtime_provider_manifest": provider_summary,
                "blocked_reason": blocked_reason,
            }
        )
        _mark_manifest_entry(
            runtime_input_manifest,
            "precomputed_unsfin_schedule",
            path=None,
            consumed=False,
            production_status="blocked",
            runtime_stage="post_initialize.production_native_unsfin_runtime_feed",
            missing_on_disk=False,
            default_substitution_used=False,
            current_backend_branch_active=False,
            structure_summary=provider_summary,
            blocked_reason=blocked_reason,
            notes="Feature-gated production_native_unsfin provider failed closed before DFS staging.",
        )

    elif native_provider_attempted:
        case_dir_value = runtime_input_manifest.get("reference_base_dir")
        provider_output_base = Path(getattr(solver, "output_dir", Path(case_dir_value or ".") / "outputs"))
        provider_output_dir = provider_output_base / "production_native_unsfin_provider_runtime_feed"
        explicit_ledger_window = os.environ.get("EDDA_NATIVE_UNSFIN_PROVIDER_LEDGER_WINDOW_S")
        if explicit_ledger_window is not None and str(explicit_ledger_window).strip():
            provider_ledger_window_s = float(explicit_ledger_window)
            provider_ledger_window_source = "env.EDDA_NATIVE_UNSFIN_PROVIDER_LEDGER_WINDOW_S"
        else:
            provider_ledger_window_s = float(getattr(getattr(solver.config, "time", None), "t_end", 64800.0))
            provider_ledger_window_source = "solver.config.time.t_end"
        runtime_input_manifest["native_unsfin_provider_request"] = {
            "ledger_window_s": provider_ledger_window_s,
            "ledger_window_source": provider_ledger_window_source,
            "provider_output_dir": str(provider_output_dir),
        }
        if case_dir_value:
            provider_request = NativeUnsfinDryRunRequest(
                case_dir=Path(case_dir_value),
                output_dir=provider_output_dir,
                provider_selected=True,
                dry_run_enabled=True,
                runtime_feed_enabled=False,
                ledger_window_s=provider_ledger_window_s,
                checkpoint_dir=(
                    Path(os.environ["EDDA_NATIVE_UNSFIN_PROVIDER_CHECKPOINT_DIR"])
                    if os.environ.get("EDDA_NATIVE_UNSFIN_PROVIDER_CHECKPOINT_DIR")
                    else provider_output_dir / "checkpoints"
                ),
                resume=str(os.environ.get("EDDA_NATIVE_UNSFIN_PROVIDER_RESUME", "")).strip().lower()
                in {"1", "true", "yes", "on"},
            )
            provider_result = configure_provider_runtime_feed(solver, provider_request)
        else:
            provider_request = NativeUnsfinDryRunRequest(
                case_dir=Path("."),
                output_dir=provider_output_dir,
                provider_selected=True,
                dry_run_enabled=True,
                runtime_feed_enabled=False,
                ledger_window_s=provider_ledger_window_s,
            )
            provider_result = configure_provider_runtime_feed(solver, provider_request)

        provider_summary = {
            key: provider_result.meta.get(key)
            for key in (
                "provider",
                "mode",
                "provider_available",
                "provider_selected",
                "dry_run_enabled",
                "runtime_feed_enabled",
                "schedule_generated",
                "schedule_validated",
                "schedule_configured_into_solver",
                "schedule_consumed_by_dfs",
                "source_provenance",
                "output_inferred",
                "active_order_mode",
                "per_cell_fitted_ts",
                "tfail_positive_count",
                "gindx_positive_count",
                "fdepth_positive_count",
                "consumed_count",
                "committed_fired_count",
                "duplicate_fire_count",
                "rejected_step_discard_count",
                "total_staged_depth_sum",
                "total_staged_mass_sum",
                "blocked_reason",
                "blocked_detail",
            )
            if key in provider_result.meta
        }
        failure_registry.update(
            {
                "selected_source": "production_native_unsfin",
                "schedule_provider": "production_native_unsfin",
                "schedule_loaded": provider_result.schedule_configured_into_solver,
                "runtime_active": provider_result.schedule_configured_into_solver,
                "runtime_equivalent_implemented": provider_result.schedule_configured_into_solver,
                "provider_available": provider_result.provider_available,
                "provider_selected": provider_result.provider_selected,
                "dry_run_enabled": provider_result.dry_run_enabled,
                "runtime_feed_enabled": provider_result.runtime_feed_enabled,
                "schedule_generated": provider_result.schedule_generated,
                "schedule_validated": provider_result.schedule_validated,
                "schedule_configured_into_solver": provider_result.schedule_configured_into_solver,
                "schedule_consumed_by_dfs": provider_result.schedule_consumed_by_dfs,
                "source_provenance": provider_result.meta.get("source_provenance"),
                "output_inferred": provider_result.meta.get("output_inferred"),
                "active_order_mode": provider_result.meta.get("active_order_mode"),
                "per_cell_fitted_ts": provider_result.meta.get("per_cell_fitted_ts"),
                "tfail_positive_count": provider_result.meta.get("tfail_positive_count", 0),
                "gindx_positive_count": provider_result.meta.get("gindx_positive_count", 0),
                "fdepth_positive_count": provider_result.meta.get("fdepth_positive_count", 0),
                "consumed_count": provider_result.meta.get("consumed_count", 0),
                "committed_fired_count": provider_result.meta.get("committed_fired_count", 0),
                "duplicate_fire_count": provider_result.meta.get("duplicate_fire_count", 0),
                "rejected_step_discard_count": provider_result.meta.get("rejected_step_discard_count", 0),
                "total_staged_depth_sum": provider_result.meta.get("total_staged_depth_sum", 0.0),
                "total_staged_mass_sum": provider_result.meta.get("total_staged_mass_sum", 0.0),
                "artifact_paths": provider_result.artifact_paths,
                "runtime_provider_manifest": provider_summary,
                "blocked_reason": (
                    None
                    if provider_result.ok
                    else f"production_native_unsfin runtime feed blocked: {provider_result.blocked_reason}; "
                    f"{provider_result.meta.get('blocked_detail')}"
                ),
            }
        )
        _mark_manifest_entry(
            runtime_input_manifest,
            "precomputed_unsfin_schedule",
            path=provider_result.artifact_paths.get("manifest"),
            consumed=provider_result.schedule_configured_into_solver,
            production_status="partial" if provider_result.schedule_configured_into_solver else "blocked",
            runtime_stage="post_initialize.production_native_unsfin_runtime_feed",
            missing_on_disk=False,
            default_substitution_used=False,
            current_backend_branch_active=provider_result.schedule_configured_into_solver,
            structure_summary=provider_summary,
            blocked_reason=failure_registry.get("blocked_reason"),
            notes=(
                "Feature-gated production_native_unsfin provider schedule was validated and configured into DFS staging."
                if provider_result.ok
                else "Feature-gated production_native_unsfin provider failed closed before DFS staging."
            ),
        )

    if not native_provider_attempted and failure_registry.get("selected_source") == "precomputed_unsfin_schedule":
        case_dir_value = runtime_input_manifest.get("reference_base_dir")
        dem_path = next(
            (
                Path(item["path"])
                for item in runtime_input_manifest.get("inputs", [])
                if item.get("family") == "demfil" and item.get("path")
            ),
            None,
        )
        if case_dir_value:
            schedule_payload = load_precomputed_unsfin_schedule(Path(case_dir_value), dem_file=dem_path)
        else:
            schedule_payload = {
                "family": "precomputed_unsfin_schedule",
                "parse_status": "missing_case_dir",
                "runtime_arrays": None,
            }
        schedule_summary = {key: value for key, value in schedule_payload.items() if key != "runtime_arrays"}
        artifact_paths = schedule_summary.get("artifact_paths") or {}
        registry_update = {
            "schedule_provider": (
                "original_tfail_artifacts"
                if schedule_payload.get("parse_status") == "ok"
                else "missing_original_tfail_artifacts"
            ),
            "schedule_loaded": schedule_payload.get("parse_status") == "ok",
            "artifact_validation": schedule_summary,
        }
        if schedule_payload.get("parse_status") == "ok" and schedule_payload.get("runtime_arrays"):
            arrays = schedule_payload["runtime_arrays"]
            schedule_info = solver.configure_precomputed_failure_schedule(
                tfail_s=arrays["tfail_s"],
                gindx=arrays["gindx"],
                fdepth_m=arrays["fdepth_m"],
            )
            registry_update.update(
                {
                    "runtime_active": True,
                    "runtime_equivalent_implemented": True,
                    "blocked_reason": None,
                    "consumed_count": schedule_info.get("scheduled_cell_count"),
                    "schedule_runtime_diagnostics": schedule_info,
                }
            )
            _mark_manifest_entry(
                runtime_input_manifest,
                "precomputed_unsfin_schedule",
                path=artifact_paths.get("meta"),
                consumed=True,
                production_status="partial",
                runtime_stage="post_initialize.precomputed_unsfin_schedule_loader",
                missing_on_disk=False,
                default_substitution_used=False,
                current_backend_branch_active=True,
                structure_summary=schedule_summary,
                notes="Validated original `unsfin` artifacts were loaded into the feature-gated precomputed failure schedule provider.",
            )
        else:
            blocked_reason = (
                "Validated original `precomputed_unsfin_gindx/tfail/fdepth/meta` artifacts are required; "
                f"loader status: {schedule_payload.get('parse_status')}."
            )
            registry_update.update(
                {
                    "runtime_active": False,
                    "runtime_equivalent_implemented": False,
                    "blocked_reason": blocked_reason,
                    "consumed_count": 0,
                }
            )
            _mark_manifest_entry(
                runtime_input_manifest,
                "precomputed_unsfin_schedule",
                path=artifact_paths.get("meta"),
                consumed=False,
                production_status="blocked",
                runtime_stage="post_initialize.precomputed_unsfin_schedule_loader",
                missing_on_disk=True,
                default_substitution_used=False,
                current_backend_branch_active=False,
                structure_summary=schedule_summary,
                blocked_reason=blocked_reason,
                notes="No `tfail` schedule was inferred; original artifacts remain required for this branch.",
            )
        failure_registry.update(registry_update)

    return runtime_input_manifest


def collect_runtime_source_chain_diagnostics(
    solver: Any,
    runtime_input_manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist post-run failure-source -> solids chain diagnostics.

    The solver reports accepted-step and field statistics; this helper merges
    them with the native input registry so manifests can distinguish configured
    schedule state from post-run runtime evidence.
    """
    registry = runtime_input_manifest.get("input_source_registry", {})
    failure_registry = registry.get("dfs_failure_source_variant", {})
    solver_diag = {}
    if hasattr(solver, "get_runtime_source_chain_diagnostics"):
        solver_diag = solver.get_runtime_source_chain_diagnostics()

    diagnostics = {
        "schedule_provider": failure_registry.get("schedule_provider"),
        "schedule_loaded": bool(failure_registry.get("schedule_loaded")),
        "runtime_active": bool(failure_registry.get("runtime_active")),
        "runtime_equivalent_implemented": bool(failure_registry.get("runtime_equivalent_implemented")),
        **solver_diag,
    }
    diagnostics["consumed_count"] = int(
        diagnostics.get("consumed_count")
        or failure_registry.get("consumed_count")
        or diagnostics.get("scheduled_cell_count")
        or 0
    )

    runtime_input_manifest["post_run_source_chain_diagnostics"] = diagnostics
    failure_registry["post_run_source_chain_diagnostics"] = diagnostics
    for key in (
        "scheduled_cell_count",
        "consumed_count",
        "fired_cell_count",
        "crossing_count_by_checkpoint",
        "last_staged_cell_count",
        "last_staged_depth_sum",
        "failure_source_flow_depth_sum",
        "failure_source_mass_sum",
        "Cv_max",
        "Cv_sum",
        "erosion_rate_max",
        "erosion_rate_sum",
        "deposition_rate_max",
        "deposition_rate_sum",
        "Deposit_depth_sum",
        "Erosion_depth_sum",
        "Flow_depth_sum",
    ):
        if key in diagnostics:
            failure_registry[key] = diagnostics[key]

    _mark_manifest_entry(
        runtime_input_manifest,
        "precomputed_unsfin_schedule",
        post_run_diagnostics=diagnostics,
        current_backend_branch_active=diagnostics["runtime_active"],
        consumed=diagnostics["runtime_active"] and diagnostics["consumed_count"] > 0,
    )
    return diagnostics


def write_runtime_metadata_files(
    output_dir: Path,
    effective_config: Dict[str, Any],
    runtime_input_manifest: Dict[str, Any],
    provenance: Dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in (
        ("effective_config.json", effective_config),
        ("runtime_input_manifest.json", runtime_input_manifest),
        ("runtime_provenance.json", provenance),
        ("input_source_registry.json", runtime_input_manifest.get("input_source_registry") or provenance.get("input_source_registry") or {}),
    ):
        with (output_dir / filename).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
