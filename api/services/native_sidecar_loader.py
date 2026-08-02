"""Helpers for auditing original EDDA sidecar files without altering solver semantics."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from edda.io.spatial_input_loader import SpatialInputLoader


FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\d+|\.\d+)(?:[eEdD][-+]?\d+)?")
PRECOMPUTED_UNSFIN_FILENAMES = {
    "gindx": "precomputed_unsfin_gindx.txt",
    "tfail_s": "precomputed_unsfin_tfail.txt",
    "fdepth_m": "precomputed_unsfin_fdepth.txt",
    "meta": "precomputed_unsfin_meta.json",
}
VALIDATE_PRECOMPUTED_UNSFIN_FAILURE_GRIDS_ENV = (
    "EDDA_EXPERIMENT_VALIDATE_PRECOMPUTED_UNSFIN_FAILURE_GRID_MATCH"
)
ALLOWED_PRECOMPUTED_UNSFIN_PROVENANCE = {
    "original_unsfin_memory_dump",
    "production_native_unsfin",
}
ORIGINAL_UNSFIN_PROVIDER_ALIASES = {
    "original_instrumented_unsfin": "original_unsfin_memory_dump",
    "original_unsfin_memory_dump": "original_unsfin_memory_dump",
    "production_native_unsfin": "production_native_unsfin",
}
ALLOWED_PRECOMPUTED_UNSFIN_SHAPE_KINDS = {
    "active_cell_vector",
    "ascii_grid",
    "dem_yx_grid",
    "solver_xy_grid",
    "plain_numeric_matrix",
}


def _parse_floats(line: str) -> List[float]:
    return [float(token.replace("D", "E").replace("d", "e")) for token in FLOAT_RE.findall(line)]


def _read_nonempty_lines(path: Path) -> List[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def _compact_histogram(values: np.ndarray, *, bins: int = 10) -> List[Dict[str, float]]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return []
    if np.isclose(float(np.nanmin(finite)), float(np.nanmax(finite))):
        return [
            {
                "lower": float(finite[0]),
                "upper": float(finite[0]),
                "count": int(finite.size),
            }
        ]
    counts, edges = np.histogram(finite, bins=bins)
    return [
        {
            "lower": float(edges[idx]),
            "upper": float(edges[idx + 1]),
            "count": int(count),
        }
        for idx, count in enumerate(counts)
    ]


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _artifact_hashes(paths: Dict[str, Path]) -> Dict[str, Dict[str, Any]]:
    hashes: Dict[str, Dict[str, Any]] = {}
    for key, path in paths.items():
        hashes[key] = {
            "path": str(path),
            "bytes": path.stat().st_size if path.exists() else 0,
            "sha256": _file_sha256(path) if path.exists() else None,
        }
    return hashes


def _normalize_precomputed_unsfin_provenance(meta: Dict[str, Any]) -> Optional[str]:
    raw = str(meta.get("source_provenance") or meta.get("provider") or "").strip()
    if not raw:
        return None
    return ORIGINAL_UNSFIN_PROVIDER_ALIASES.get(raw, raw)


def _validate_precomputed_unsfin_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    shape_kind = str(meta.get("shape_kind") or "").strip()
    raw_provider = str(meta.get("provider") or "").strip()
    source_provenance = _normalize_precomputed_unsfin_provenance(meta)

    if source_provenance not in ALLOWED_PRECOMPUTED_UNSFIN_PROVENANCE:
        errors.append(
            "source_provenance must be original_unsfin_memory_dump or production_native_unsfin"
        )
    if shape_kind not in ALLOWED_PRECOMPUTED_UNSFIN_SHAPE_KINDS:
        errors.append("shape_kind is required and must describe the artifact grid/vector layout")

    serialized = json.dumps(meta, sort_keys=True).lower()
    blocked_markers = ("output_inferred", "faildph", "ls_scar", "volumetric_sediment")
    if any(marker in serialized for marker in blocked_markers):
        errors.append("metadata contains blocked output-inference provenance marker")

    if source_provenance == "original_unsfin_memory_dump" and not meta.get("dump_point"):
        errors.append("original_unsfin_memory_dump artifacts require an explicit dump_point")

    return {
        "valid": not errors,
        "errors": errors,
        "shape_kind": shape_kind or None,
        "raw_provider": raw_provider or None,
        "source_provenance": source_provenance,
    }


def _read_numeric_grid(path: Path) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Read an original instrumentation artifact without assuming one fixed dump format.

    The preferred artifact format is ESRI-style ASCII grid because it preserves
    shape metadata.  A plain whitespace matrix is accepted only for test/probe
    artifacts; callers still validate shape against DEM/runtime dimensions.
    """
    try:
        grid, metadata = SpatialInputLoader(str(path)).read()
        return np.asarray(grid, dtype=np.float64), {
            **metadata,
            "format": "ascii_grid",
        }
    except Exception as ascii_exc:
        data = np.loadtxt(path, dtype=np.float64)
        if data.ndim == 0:
            data = data.reshape((1, 1))
        return np.asarray(data, dtype=np.float64), {
            "format": "plain_numeric_matrix",
            "ascii_grid_error": str(ascii_exc),
        }


def find_precomputed_unsfin_artifacts(case_dir: Path) -> Dict[str, Any]:
    """Locate original `unsfin` schedule artifacts without fabricating fallbacks."""
    case_dir = Path(case_dir)
    search_dirs = [
        case_dir,
        case_dir / "results",
        case_dir / "Results",
        case_dir / "original_reference_artifacts",
    ]
    artifact_paths: Dict[str, Optional[str]] = {}
    missing: List[str] = []
    for key, filename in PRECOMPUTED_UNSFIN_FILENAMES.items():
        found: Optional[Path] = None
        for base in search_dirs:
            candidate = base / filename
            if candidate.exists():
                found = candidate
                break
        artifact_paths[key] = str(found) if found else str(case_dir / filename)
        if found is None:
            missing.append(filename)

    return {
        "artifact_paths": artifact_paths,
        "missing_artifacts": missing,
        "all_required_present": not missing,
        "search_dirs": [str(path) for path in search_dirs],
    }


def _artifact_summary(
    *,
    gindx: np.ndarray,
    tfail: np.ndarray,
    fdepth: np.ndarray,
    orientation: str,
    artifact_paths: Dict[str, Optional[str]],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    active = (gindx > 0) & (fdepth > 0.0) & np.isfinite(tfail)
    fdepth_active = fdepth[active]
    tfail_active = tfail[active]
    finite_tfail = tfail[np.isfinite(tfail)]
    return {
        "parse_status": "ok",
        "artifact_paths": artifact_paths,
        "shape": list(gindx.shape),
        "runtime_orientation": orientation,
        "meta": meta,
        "gindx_nonzero_count": int(np.count_nonzero(gindx > 0)),
        "fdepth_nonzero_count": int(np.count_nonzero(fdepth > 0.0)),
        "fdepth_active_count": int(fdepth_active.size),
        "fdepth_sum": float(np.sum(fdepth_active)) if fdepth_active.size else 0.0,
        "fdepth_max": float(np.max(fdepth_active)) if fdepth_active.size else 0.0,
        "tfail_finite_count": int(finite_tfail.size),
        "tfail_active_count": int(tfail_active.size),
        "tfail_min": float(np.min(tfail_active)) if tfail_active.size else None,
        "tfail_max": float(np.max(tfail_active)) if tfail_active.size else None,
        "tfail_lte_600_count": int(np.count_nonzero(tfail_active <= 600.0)),
        "tfail_histogram": _compact_histogram(tfail_active),
        "scheduled_cell_count": int(np.count_nonzero(active)),
    }


def _active_cell_vector_to_dem_grid(vector: np.ndarray, dem_grid: np.ndarray, nodata: Any) -> np.ndarray:
    if nodata is None:
        valid_mask = np.isfinite(dem_grid)
    else:
        valid_mask = ~np.isclose(dem_grid, nodata)
    valid_count = int(np.count_nonzero(valid_mask))
    if vector.size != valid_count:
        raise ValueError(f"active-cell vector length {vector.size} does not match DEM valid-cell count {valid_count}.")
    grid = np.zeros(dem_grid.shape, dtype=np.float64)
    grid[valid_mask] = vector.astype(np.float64, copy=False)
    return grid


def _env_flag(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _latest_timestamped_grid(base_dir: Path, patterns: Tuple[str, ...]) -> Optional[Path]:
    candidates: List[Tuple[float, Path]] = []
    search_dirs = [base_dir / "results", base_dir / "Results", base_dir]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            for path in search_dir.glob(pattern):
                matches = re.findall(r"(\d+(?:\.\d+)?)", path.stem)
                timestamp = float(matches[-1]) if matches else -1.0
                candidates.append((timestamp, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], str(item[1])))
    return candidates[-1][1]


def _reference_failure_grid_validation(
    *,
    case_dir: Path,
    gindx_runtime: np.ndarray,
    fdepth_runtime: np.ndarray,
) -> Dict[str, Any]:
    """Check source artifacts against original-live failure output grids.

    This is a fail-closed provenance guard, not a way to infer source terms
    from outputs.  When enabled, case-local reference failure grids may reject
    a stale or branch-mismatched `gindx/tfail/fdepth` sidecar, but they never
    create replacement runtime arrays.
    """
    ls_path = _latest_timestamped_grid(case_dir, ("LS_ScarEDDA_*.txt", "LS_Scar*.txt"))
    fdepth_path = _latest_timestamped_grid(case_dir, ("faildphEDDA_*.txt", "faildph*.txt"))
    if ls_path is None or fdepth_path is None:
        return {
            "enabled": True,
            "status": "missing_reference_failure_grid",
            "ls_scar_path": str(ls_path) if ls_path else None,
            "faildph_path": str(fdepth_path) if fdepth_path else None,
            "valid": False,
        }

    ls_grid, ls_meta = SpatialInputLoader(str(ls_path)).read()
    fdepth_grid, fdepth_meta = SpatialInputLoader(str(fdepth_path)).read()
    ls_grid = np.asarray(ls_grid, dtype=np.float64)
    fdepth_grid = np.asarray(fdepth_grid, dtype=np.float64)
    gindx_yx = np.asarray(gindx_runtime, dtype=np.float64).T
    fdepth_yx = np.asarray(fdepth_runtime, dtype=np.float64).T
    if ls_grid.shape != gindx_yx.shape or fdepth_grid.shape != fdepth_yx.shape:
        return {
            "enabled": True,
            "status": "reference_failure_grid_shape_mismatch",
            "ls_scar_path": str(ls_path),
            "faildph_path": str(fdepth_path),
            "ls_scar_shape": list(ls_grid.shape),
            "faildph_shape": list(fdepth_grid.shape),
            "gindx_shape": list(gindx_yx.shape),
            "fdepth_shape": list(fdepth_yx.shape),
            "valid": False,
        }

    nodata = ls_meta.get("nodata")
    if nodata is None:
        valid_mask = np.isfinite(ls_grid)
    else:
        valid_mask = ~np.isclose(ls_grid, nodata)
    if fdepth_meta.get("nodata") is not None:
        valid_mask &= ~np.isclose(fdepth_grid, fdepth_meta["nodata"])
    valid_mask &= np.isfinite(fdepth_grid)

    gindx_mismatch = np.round(gindx_yx[valid_mask], 6) != np.round(ls_grid[valid_mask], 6)
    fdepth_mismatch = np.round(fdepth_yx[valid_mask], 6) != np.round(fdepth_grid[valid_mask], 6)
    gindx_delta = gindx_yx[valid_mask] - ls_grid[valid_mask]
    fdepth_delta = fdepth_yx[valid_mask] - fdepth_grid[valid_mask]
    gindx_mismatch_count = int(np.count_nonzero(gindx_mismatch))
    fdepth_mismatch_count = int(np.count_nonzero(fdepth_mismatch))
    return {
        "enabled": True,
        "status": "ok" if gindx_mismatch_count == 0 and fdepth_mismatch_count == 0 else "mismatch",
        "valid": gindx_mismatch_count == 0 and fdepth_mismatch_count == 0,
        "ls_scar_path": str(ls_path),
        "faildph_path": str(fdepth_path),
        "valid_count": int(np.count_nonzero(valid_mask)),
        "artifact_gindx_nonzero_count": int(np.count_nonzero(gindx_yx[valid_mask] > 0)),
        "reference_ls_scar_nonzero_count": int(np.count_nonzero(ls_grid[valid_mask] > 0)),
        "artifact_fdepth_nonzero_count": int(np.count_nonzero(fdepth_yx[valid_mask] > 0.0)),
        "reference_faildph_nonzero_count": int(np.count_nonzero(fdepth_grid[valid_mask] > 0.0)),
        "gindx_vs_lsscar_mismatch_count": gindx_mismatch_count,
        "gindx_vs_lsscar_max_abs_error": float(np.max(np.abs(gindx_delta))) if gindx_delta.size else 0.0,
        "fdepth_vs_faildph_mismatch_count": fdepth_mismatch_count,
        "fdepth_vs_faildph_max_abs_error": float(np.max(np.abs(fdepth_delta))) if fdepth_delta.size else 0.0,
    }


def load_precomputed_unsfin_schedule(case_dir: Path, dem_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load original EDDA `unsfin` artifacts as an explicit runtime schedule provider.

    This function intentionally does not infer `tfail` from `LS_Scar` or
    `faildph`.  Missing original artifacts remain blocked and auditable.
    """
    locator = find_precomputed_unsfin_artifacts(Path(case_dir))
    if not locator["all_required_present"]:
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "missing_artifacts",
            **locator,
            "runtime_arrays": None,
        }

    paths = {key: Path(value) for key, value in locator["artifact_paths"].items() if value is not None}
    hashes = _artifact_hashes(paths)
    gindx_grid, gindx_meta = _read_numeric_grid(paths["gindx"])
    tfail_grid, tfail_meta = _read_numeric_grid(paths["tfail_s"])
    fdepth_grid, fdepth_meta = _read_numeric_grid(paths["fdepth_m"])
    meta: Dict[str, Any] = {}
    try:
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    except Exception as exc:
        meta = {"parse_warning": f"Could not parse meta json: {exc}"}
    meta_validation = _validate_precomputed_unsfin_meta(meta)
    if not meta_validation["valid"]:
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "invalid_meta",
            "artifact_paths": locator["artifact_paths"],
            "artifact_hashes": hashes,
            "meta": meta,
            "meta_validation": meta_validation,
            "runtime_arrays": None,
        }

    shape = gindx_grid.shape
    if tfail_grid.shape != shape or fdepth_grid.shape != shape:
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "shape_mismatch",
            "artifact_paths": locator["artifact_paths"],
            "artifact_hashes": hashes,
            "meta": meta,
            "meta_validation": meta_validation,
            "shapes": {
                "gindx": list(gindx_grid.shape),
                "tfail_s": list(tfail_grid.shape),
                "fdepth_m": list(fdepth_grid.shape),
            },
            "runtime_arrays": None,
        }

    dem_shape: Optional[Tuple[int, int]] = None
    dem_grid: Optional[np.ndarray] = None
    dem_nodata: Any = None
    if dem_file is not None:
        dem_grid, dem_metadata = SpatialInputLoader(str(dem_file)).read()
        dem_nodata = dem_metadata.get("nodata")
        dem_shape = tuple(dem_grid.shape)

    shape_kind = meta_validation.get("shape_kind")
    if len(shape) == 1 and shape_kind != "active_cell_vector":
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "invalid_shape_kind",
            "artifact_paths": locator["artifact_paths"],
            "artifact_hashes": hashes,
            "meta": meta,
            "meta_validation": meta_validation,
            "artifact_shape": list(shape),
            "runtime_arrays": None,
        }
    if len(shape) == 1 and dem_grid is None:
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "missing_dem_for_active_cell_vector",
            "artifact_paths": locator["artifact_paths"],
            "artifact_hashes": hashes,
            "meta": meta,
            "meta_validation": meta_validation,
            "artifact_shape": list(shape),
            "runtime_arrays": None,
        }
    if len(shape) == 2 and shape_kind == "active_cell_vector":
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "invalid_shape_kind",
            "artifact_paths": locator["artifact_paths"],
            "artifact_hashes": hashes,
            "meta": meta,
            "meta_validation": meta_validation,
            "artifact_shape": list(shape),
            "runtime_arrays": None,
        }

    if dem_shape is None or shape == dem_shape:
        orientation = "ascii_grid_transposed_to_solver_xy"
        gindx_runtime = gindx_grid.T
        tfail_runtime = tfail_grid.T
        fdepth_runtime = fdepth_grid.T
    elif shape == tuple(reversed(dem_shape)):
        orientation = "already_solver_xy"
        gindx_runtime = gindx_grid
        tfail_runtime = tfail_grid
        fdepth_runtime = fdepth_grid
    elif dem_grid is not None and len(shape) == 1:
        try:
            gindx_mapped = _active_cell_vector_to_dem_grid(gindx_grid, dem_grid, dem_nodata)
            tfail_mapped = _active_cell_vector_to_dem_grid(tfail_grid, dem_grid, dem_nodata)
            fdepth_mapped = _active_cell_vector_to_dem_grid(fdepth_grid, dem_grid, dem_nodata)
        except ValueError as exc:
            return {
                "family": "precomputed_unsfin_schedule",
                "parse_status": "active_cell_vector_shape_mismatch",
                "artifact_paths": locator["artifact_paths"],
                "artifact_hashes": hashes,
                "meta": meta,
                "meta_validation": meta_validation,
                "artifact_shape": list(shape),
                "dem_shape": list(dem_shape),
                "error": str(exc),
                "runtime_arrays": None,
            }
        orientation = "active_cell_vector_mapped_to_dem_valid_cells"
        gindx_runtime = gindx_mapped.T
        tfail_runtime = tfail_mapped.T
        fdepth_runtime = fdepth_mapped.T
    else:
        return {
            "family": "precomputed_unsfin_schedule",
            "parse_status": "dem_shape_mismatch",
            "artifact_paths": locator["artifact_paths"],
            "artifact_hashes": hashes,
            "meta": meta,
            "meta_validation": meta_validation,
            "artifact_shape": list(shape),
            "dem_shape": list(dem_shape),
            "runtime_arrays": None,
        }

    failure_grid_validation = None
    if _env_flag(VALIDATE_PRECOMPUTED_UNSFIN_FAILURE_GRIDS_ENV):
        failure_grid_validation = _reference_failure_grid_validation(
            case_dir=Path(case_dir),
            gindx_runtime=gindx_runtime,
            fdepth_runtime=fdepth_runtime,
        )
        if not failure_grid_validation.get("valid"):
            return {
                "family": "precomputed_unsfin_schedule",
                "parse_status": "reference_failure_grid_mismatch",
                "artifact_paths": locator["artifact_paths"],
                "artifact_hashes": hashes,
                "meta": meta,
                "meta_validation": meta_validation,
                "reference_failure_grid_validation": failure_grid_validation,
                "runtime_arrays": None,
            }

    summary = _artifact_summary(
        gindx=gindx_runtime,
        tfail=tfail_runtime,
        fdepth=fdepth_runtime,
        orientation=orientation,
        artifact_paths=locator["artifact_paths"],
        meta={
            **meta,
            "source_provenance": meta_validation.get("source_provenance"),
            "raw_provider": meta_validation.get("raw_provider"),
            "meta_validation": meta_validation,
            "grid_read_formats": {
                "gindx": gindx_meta.get("format"),
                "tfail_s": tfail_meta.get("format"),
                "fdepth_m": fdepth_meta.get("format"),
            },
            "raw_grid_shape": list(shape),
            "dem_shape": list(dem_shape) if dem_shape is not None else None,
        },
    )
    return {
        "family": "precomputed_unsfin_schedule",
        **summary,
        "artifact_hashes": hashes,
        "source_provenance": meta_validation.get("source_provenance"),
        "meta_validation": meta_validation,
        "reference_failure_grid_validation": failure_grid_validation,
        "runtime_arrays": {
            "gindx": np.asarray(gindx_runtime, dtype=np.int32),
            "tfail_s": np.asarray(tfail_runtime, dtype=np.float64),
            "fdepth_m": np.asarray(fdepth_runtime, dtype=np.float64),
        },
    }


def _build_valid_cell_id_mapping(dem_file: Path) -> Dict[int, Tuple[int, int]]:
    dem_grid, metadata = SpatialInputLoader(str(dem_file)).read()
    nodata = metadata.get("nodata")
    if nodata is None:
        valid_mask = np.isfinite(dem_grid)
    else:
        valid_mask = ~np.isclose(dem_grid, nodata)

    mapping: Dict[int, Tuple[int, int]] = {}
    next_id = 1
    nrows, ncols = valid_mask.shape
    for row in range(nrows):
        for col in range(ncols):
            if not valid_mask[row, col]:
                continue
            mapping[next_id] = (col, row)
            next_id += 1
    return mapping


def _map_cell_ids(dem_file: Optional[Path], cell_ids: List[int]) -> Dict[str, Any]:
    if dem_file is None:
        return {
            "grid_mapping_status": "missing_dem",
            "grid_coords_preview": [],
            "missing_cell_ids": [],
        }
    try:
        mapping = _build_valid_cell_id_mapping(dem_file)
    except Exception as exc:  # pragma: no cover - defensive metadata path
        return {
            "grid_mapping_status": "mapping_failed",
            "grid_coords_preview": [],
            "missing_cell_ids": cell_ids[:10],
            "mapping_error": str(exc),
        }

    coords_preview: List[Dict[str, int]] = []
    missing: List[int] = []
    for cell_id in cell_ids:
        coord = mapping.get(cell_id)
        if coord is None:
            missing.append(cell_id)
            continue
        if len(coords_preview) < 10:
            coords_preview.append({"cell_id": cell_id, "col": coord[0], "row": coord[1]})

    return {
        "grid_mapping_status": "mapped" if not missing else "partial",
        "grid_coords_preview": coords_preview,
        "missing_cell_ids": missing[:10],
    }


def parse_cell_list_sidecar(sidecar_file: Path, family: str, dem_file: Optional[Path] = None) -> Dict[str, Any]:
    lines = _read_nonempty_lines(sidecar_file)
    numeric: List[int] = []
    for line in lines:
        values = _parse_floats(line)
        if values:
            numeric.extend(int(value) for value in values)

    summary: Dict[str, Any] = {
        "family": family,
        "path": str(sidecar_file),
        "format": "header + count + cell ids",
        "nonempty_line_count": len(lines),
        "parse_status": "ok" if numeric else "no_numeric_content",
        "declared_cell_count": 0,
        "parsed_cell_count": 0,
        "cell_ids": [],
        "cell_ids_preview": [],
        "preview_truncated": False,
        "extra_numeric_tokens": 0,
    }

    if not numeric:
        summary.update(_map_cell_ids(dem_file, []))
        return summary

    declared_count = max(int(numeric[0]), 0)
    cell_ids = numeric[1:1 + declared_count]
    extra_numeric_tokens = max(0, len(numeric) - 1 - len(cell_ids))

    summary.update(
        {
            "declared_cell_count": declared_count,
            "parsed_cell_count": len(cell_ids),
            "cell_ids": cell_ids,
            "cell_ids_preview": cell_ids[:10],
            "preview_truncated": len(cell_ids) > 10,
            "extra_numeric_tokens": extra_numeric_tokens,
        }
    )
    summary.update(_map_cell_ids(dem_file, cell_ids))
    return summary


def parse_inflow_sidecar(sidecar_file: Path, dem_file: Optional[Path] = None) -> Dict[str, Any]:
    lines = _read_nonempty_lines(sidecar_file)
    numeric_lines = [_parse_floats(line) for line in lines if _parse_floats(line)]

    summary: Dict[str, Any] = {
        "family": "inflow.txt",
        "path": str(sidecar_file),
        "format": "count -> (period, dt) -> per-cell id + pulse rows",
        "nonempty_line_count": len(lines),
        "parse_status": "ok" if numeric_lines else "no_numeric_content",
        "declared_cell_count": 0,
        "parsed_cell_count": 0,
        "inflow_period_s": None,
        "inflow_dt_s": None,
        "expected_pulses_per_cell": None,
        "parsed_block_count": 0,
        "cell_ids_preview": [],
        "preview_truncated": False,
        "malformed_blocks": 0,
    }

    if len(numeric_lines) < 2:
        summary["parse_status"] = "insufficient_numeric_lines"
        summary.update(_map_cell_ids(dem_file, []))
        return summary

    declared_count = max(int(numeric_lines[0][0]), 0)
    inflow_period = float(numeric_lines[1][0]) if len(numeric_lines[1]) >= 1 else None
    inflow_dt = float(numeric_lines[1][1]) if len(numeric_lines[1]) >= 2 else None
    expected_pulses = None
    if inflow_period is not None and inflow_dt and inflow_dt > 0.0:
        expected_pulses = int(inflow_period / inflow_dt) + 1

    cell_ids: List[int] = []
    parsed_blocks = 0
    malformed_blocks = 0
    idx = 2
    while idx < len(numeric_lines) and len(cell_ids) < declared_count:
        cell_line = numeric_lines[idx]
        idx += 1
        if not cell_line:
            malformed_blocks += 1
            continue
        cell_id = int(cell_line[0])
        cell_ids.append(cell_id)
        if expected_pulses is None:
            continue
        block_ok = True
        for _ in range(expected_pulses):
            if idx >= len(numeric_lines) or len(numeric_lines[idx]) < 3:
                block_ok = False
                malformed_blocks += 1
                break
            idx += 1
        if block_ok:
            parsed_blocks += 1

    summary.update(
        {
            "declared_cell_count": declared_count,
            "parsed_cell_count": len(cell_ids),
            "inflow_period_s": inflow_period,
            "inflow_dt_s": inflow_dt,
            "expected_pulses_per_cell": expected_pulses,
            "parsed_block_count": parsed_blocks,
            "cell_ids_preview": cell_ids[:10],
            "preview_truncated": len(cell_ids) > 10,
            "malformed_blocks": malformed_blocks,
        }
    )
    summary.update(_map_cell_ids(dem_file, cell_ids))
    return summary


def load_inflow_runtime_payload(sidecar_file: Path, dem_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Parse the full original `inflow.txt` hydrograph payload for runtime use.

    This keeps `parse_inflow_sidecar()` lightweight for audit metadata while
    exposing the per-cell time-series data needed by the production runtime
    forcing chain.
    """
    lines = _read_nonempty_lines(sidecar_file)
    numeric_lines = [_parse_floats(line) for line in lines if _parse_floats(line)]

    payload: Dict[str, Any] = {
        "family": "inflow.txt",
        "path": str(sidecar_file),
        "parse_status": "ok" if numeric_lines else "no_numeric_content",
        "declared_cell_count": 0,
        "inflow_period_s": None,
        "inflow_dt_s": None,
        "expected_pulses_per_cell": None,
        "configured_hydrographs": [],
        "malformed_blocks": 0,
    }

    if len(numeric_lines) < 2:
        payload["parse_status"] = "insufficient_numeric_lines"
        return payload

    declared_count = max(int(numeric_lines[0][0]), 0)
    inflow_period = float(numeric_lines[1][0]) if len(numeric_lines[1]) >= 1 else None
    inflow_dt = float(numeric_lines[1][1]) if len(numeric_lines[1]) >= 2 else None
    expected_pulses = None
    if inflow_period is not None and inflow_dt and inflow_dt > 0.0:
        expected_pulses = int(inflow_period / inflow_dt) + 1

    id_mapping = _build_valid_cell_id_mapping(dem_file) if dem_file is not None else {}

    hydrographs: List[Dict[str, Any]] = []
    malformed_blocks = 0
    idx = 2
    while idx < len(numeric_lines) and len(hydrographs) < declared_count:
        cell_line = numeric_lines[idx]
        idx += 1
        if not cell_line:
            malformed_blocks += 1
            continue
        cell_id = int(cell_line[0])
        series: List[Dict[str, float]] = []
        if expected_pulses is None:
            malformed_blocks += 1
        else:
            for _ in range(expected_pulses):
                if idx >= len(numeric_lines) or len(numeric_lines[idx]) < 3:
                    malformed_blocks += 1
                    break
                row = numeric_lines[idx]
                idx += 1
                series.append(
                    {
                        "time_s": float(row[0]),
                        "discharge_m3s": float(row[1]),
                        "cv": float(row[2]),
                    }
                )
        hydrograph: Dict[str, Any] = {
            "cell_id": cell_id,
            "series": series,
        }
        coord = id_mapping.get(cell_id)
        if coord is not None:
            hydrograph["col"] = int(coord[0])
            hydrograph["row"] = int(coord[1])
        hydrographs.append(hydrograph)

    payload.update(
        {
            "declared_cell_count": declared_count,
            "inflow_period_s": inflow_period,
            "inflow_dt_s": inflow_dt,
            "expected_pulses_per_cell": expected_pulses,
            "configured_hydrographs": hydrographs,
            "malformed_blocks": malformed_blocks,
        }
    )
    return payload


def parse_case_sidecar(sidecar_file: Path, family: str, dem_file: Optional[Path] = None) -> Dict[str, Any]:
    if family == "inflow.txt":
        return parse_inflow_sidecar(sidecar_file, dem_file=dem_file)
    if family in {"outflow.txt", "hydrograph.txt"}:
        return parse_cell_list_sidecar(sidecar_file, family=family, dem_file=dem_file)
    return {
        "family": family,
        "path": str(sidecar_file),
        "parse_status": "unsupported_family",
    }
