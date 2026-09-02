"""Validate and materialize path-free scenario inputs at the runtime boundary."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import math

import numpy as np

from api.services.edda_semantic_gate import SemanticGateViolation, validate_flat_edda_controls
from api.services.edda_input_mapper import _write_geotiff_grid, _write_rainfall_file
from api.services.parameter_catalog import PARAMETER_ENUM_SPECS
from api.services.rainfall_timeline import regular_boundaries
from api.services.scenario_config_overrides import (
    ZONE_LAYER_FIELD_MAP,
    ZONE_PATCH_PASSTHROUGH_KEYS,
    _coerce_zone_id,
)
from edda.io.spatial_input_loader import SpatialInputLoader, fill_raster_nodata


RASTER_SOURCES = {"raster", "rifil", "rifil_grid", "raster_rifil"}
UNIFORM_SOURCES = {"uniform", "uniform_cri"}


def _rainfall_is_active(parameters: Dict[str, Any]) -> bool:
    """Rainfall hydrograph is a run contract only while ``rainsimul`` is on."""
    return parameters.get("edda.run_controls.simulate_rainfall") is not False


def _active_bindings(manifest: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return [dict(item) for item in manifest if bool(item.get("active", True))]


def validate_scenario_configuration(
    parameters: Dict[str, Any],
    manifest: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate the semantic binding contract without resolving legacy config paths."""
    errors: list[str] = []
    warnings: list[str] = []
    issues: list[Dict[str, Any]] = []

    def add_issue(
        code: str,
        severity: str,
        message: str,
        *,
        parameter_key: Optional[str] = None,
        binding_key: Optional[str] = None,
        period_id: Optional[str] = None,
    ) -> None:
        issue: Dict[str, Any] = {"code": code, "severity": severity, "message": message}
        if parameter_key:
            issue["parameter_key"] = parameter_key
        if binding_key:
            issue["binding_key"] = binding_key
        if period_id:
            issue["period_id"] = period_id
        issues.append(issue)
        (errors if severity == "error" else warnings).append(message)

    def add_error(code: str, message: str, **location: Optional[str]) -> None:
        add_issue(code, "error", message, **location)

    def add_warning(code: str, message: str, **location: Optional[str]) -> None:
        add_issue(code, "warning", message, **location)

    bindings = _active_bindings(manifest)
    by_key = {str(item.get("binding_key") or ""): item for item in bindings}
    if "dem.primary" not in by_key:
        add_error("missing_dem_binding", "缺少活动的 DEM 主输入绑定（dem.primary）。", binding_key="dem.primary")

    rainfall_active = _rainfall_is_active(parameters)
    periods = parameters.get("rainfall.periods")
    if not rainfall_active:
        add_warning(
            "rainfall_inactive_schedule_ignored",
            "模拟降雨已关闭；降雨过程仅作档案保留，不参与本次运行预检。",
            parameter_key="edda.run_controls.simulate_rainfall",
        )
        periods = []
    elif not isinstance(periods, list) or not periods:
        add_error("rainfall_periods_empty", "降雨过程至少需要一个时段。", parameter_key="rainfall.periods")
        periods = []
    timeline = parameters.get("rainfall.timeline")
    expected_boundaries: list[float] | None = None
    if rainfall_active and isinstance(timeline, dict):
        timeline_mode = str(timeline.get("mode") or "regular").lower()
        if timeline_mode == "regular":
            try:
                expected_boundaries = regular_boundaries(
                    float(timeline.get("start_s")),
                    float(timeline.get("end_s")),
                    float(timeline.get("interval_s")),
                )
            except (TypeError, ValueError) as exc:
                add_error("rainfall_timeline_invalid", str(exc), parameter_key="rainfall.timeline")
        elif timeline_mode == "custom":
            try:
                expected_boundaries = [float(value) for value in timeline.get("boundaries_s") or []]
                if len(expected_boundaries) < 2 or any(
                    right <= left for left, right in zip(expected_boundaries, expected_boundaries[1:])
                ):
                    raise ValueError
            except (TypeError, ValueError):
                add_error("rainfall_timeline_boundaries_invalid", "非等间隔降雨时间轴必须提供严格递增的边界数组。", parameter_key="rainfall.timeline")
                expected_boundaries = None
        else:
            add_error("rainfall_timeline_mode_invalid", f"降雨时间轴模式无效：{timeline_mode}。", parameter_key="rainfall.timeline")

        if expected_boundaries is not None:
            expected_count = len(expected_boundaries) - 1
            if len(periods) != expected_count:
                add_error("rainfall_period_count_mismatch", f"降雨时间轴要求 {expected_count} 个时段，当前为 {len(periods)} 个。", parameter_key="rainfall.periods")
            declared_count = timeline.get("period_count")
            if declared_count is not None and int(declared_count) != expected_count:
                add_error("rainfall_period_count_declared_mismatch", "降雨时间轴记录的时段数与起止时间及间隔不一致。", parameter_key="rainfall.timeline")
            source_count = timeline.get("declared_period_count")
            if source_count is not None and int(source_count) != expected_count:
                add_error("rainfall_source_period_count_mismatch", "edda_in 的 nper 与 capt 时间边界数量不一致。", parameter_key="rainfall.timeline")
            source_end = timeline.get("declared_end_s")
            if source_end is not None and not math.isclose(float(source_end), expected_boundaries[-1], rel_tol=0.0, abs_tol=1e-9):
                add_error("rainfall_source_end_mismatch", "edda_in 的降雨结束时间与 capt 最后边界不一致。", parameter_key="rainfall.timeline")
            supplied_boundaries = timeline.get("boundaries_s")
            if isinstance(supplied_boundaries, list) and (
                len(supplied_boundaries) != len(expected_boundaries)
                or any(
                    not math.isclose(float(left), right, rel_tol=0.0, abs_tol=1e-9)
                    for left, right in zip(supplied_boundaries, expected_boundaries)
                )
            ):
                add_error("rainfall_timeline_boundary_mismatch", "降雨时间轴边界与开始、结束和间隔不一致。", parameter_key="rainfall.timeline")
    seen_period_ids: set[str] = set()
    seen_indices: set[int] = set()
    previous_end: Optional[float] = None
    raster_count = 0
    uniform_count = 0
    for offset, raw in enumerate(periods):
        if not isinstance(raw, dict):
            add_error("rainfall_period_invalid", f"降雨时段 {offset + 1} 不是有效对象。", parameter_key="rainfall.periods", period_id=f"period-{offset + 1:04d}")
            continue
        period_id = str(raw.get("period_id") or f"period-{offset + 1:04d}")
        if period_id in seen_period_ids:
            add_error("rainfall_period_duplicate", f"降雨时段标识重复：{period_id}。", parameter_key="rainfall.periods", period_id=period_id)
        seen_period_ids.add(period_id)
        try:
            period_index = int(raw.get("index") or offset + 1)
        except (TypeError, ValueError):
            period_index = -1
        if period_index in seen_indices or period_index != offset + 1:
            add_error("rainfall_period_index_invalid", f"降雨时段 {period_id} 的序号必须唯一且按 1..N 连续排列。", parameter_key="rainfall.periods", period_id=period_id)
        seen_indices.add(period_index)
        try:
            start = float(raw.get("start_s"))
            end = float(raw.get("end_s"))
        except (TypeError, ValueError):
            add_error("rainfall_period_boundary_invalid", f"降雨时段 {period_id} 缺少有效的起止时间。", parameter_key="rainfall.periods", period_id=period_id)
            continue
        if end <= start:
            add_error("rainfall_period_boundary_order", f"降雨时段 {period_id} 必须满足结束时间大于开始时间。", parameter_key="rainfall.periods", period_id=period_id)
        if previous_end is not None and not math.isclose(start, previous_end, rel_tol=0.0, abs_tol=1e-9):
            add_error("rainfall_period_not_contiguous", f"降雨时段 {period_id} 与上一时段不连续。", parameter_key="rainfall.periods", period_id=period_id)
        if previous_end is None and parameters.get("time.t_start") is not None:
            try:
                if not math.isclose(start, float(parameters["time.t_start"]), rel_tol=0.0, abs_tol=1e-9):
                    add_error("rainfall_start_time_mismatch", f"降雨时段 {period_id} 的起点与模拟开始时间不一致。", parameter_key="time.t_start", period_id=period_id)
            except (TypeError, ValueError):
                add_error("simulation_start_invalid", "模拟开始时间不是有效数值。", parameter_key="time.t_start")
        previous_end = end
        if expected_boundaries is not None and offset + 1 < len(expected_boundaries):
            if not (
                math.isclose(start, expected_boundaries[offset], rel_tol=0.0, abs_tol=1e-9)
                and math.isclose(end, expected_boundaries[offset + 1], rel_tol=0.0, abs_tol=1e-9)
            ):
                add_error("rainfall_period_timeline_mismatch", f"降雨时段 {period_id} 的边界与时间轴不一致。", parameter_key="rainfall.timeline", period_id=period_id)
        source = str(raw.get("source") or "uniform").lower()
        if source in RASTER_SOURCES:
            raster_count += 1
            binding = next(
                (
                    item
                    for item in bindings
                    if item.get("role") == "rainfall-period"
                    and (
                        str(item.get("period_id") or "") == period_id
                        or str(item.get("asset_id") or item.get("upload_id") or "") == str(raw.get("asset_id") or "")
                    )
                ),
                None,
            )
            if not binding:
                add_error("rainfall_period_binding_missing", f"降雨时段 {period_id} 尚未绑定栅格资产。", parameter_key="rainfall.periods", binding_key=f"rainfall.period.{offset + 1:04d}", period_id=period_id)
        elif source in UNIFORM_SOURCES:
            uniform_count += 1
            try:
                value = float(raw.get("cri_mps"))
                if value < 0:
                    add_error("rainfall_uniform_value_negative", f"降雨时段 {period_id} 的均匀雨强不能为负数。", parameter_key="rainfall.periods", period_id=period_id)
            except (TypeError, ValueError):
                add_error("rainfall_uniform_value_missing", f"降雨时段 {period_id} 缺少均匀雨强。", parameter_key="rainfall.periods", period_id=period_id)
        else:
            add_error("rainfall_period_source_invalid", f"降雨时段 {period_id} 的来源无效：{source}。", parameter_key="rainfall.periods", period_id=period_id)

    requested_mode = str(parameters.get("rainfall.mode") or "uniform").lower()
    derived_mode = "mixed" if raster_count and uniform_count else "raster" if raster_count else "uniform"
    if periods and requested_mode not in {derived_mode, "raster_rifil" if derived_mode == "raster" else derived_mode, "uniform_cri" if derived_mode == "uniform" else derived_mode}:
        add_warning("rainfall_mode_normalized", f"降雨模式已按时段来源解析为 {derived_mode}。", parameter_key="rainfall.mode")

    if previous_end is not None and parameters.get("time.t_end") is not None:
        try:
            if not math.isclose(float(parameters["time.t_end"]), previous_end, rel_tol=0.0, abs_tol=1e-9):
                add_error("rainfall_end_time_mismatch", "降雨过程终点与模拟结束时间不一致；请显式扩展或截断过程。", parameter_key="time.t_end")
        except (TypeError, ValueError):
            add_error("simulation_end_invalid", "模拟结束时间不是有效数值。", parameter_key="time.t_end")

    manning_source = str(parameters.get("manning.source") or "global").lower()
    if manning_source in {"raster", "raster_manningfil", "spatial"} and "manning.raster" not in by_key:
        add_error("manning_binding_missing", "空间曼宁模式需要活动的 manning.raster 绑定。", parameter_key="manning.source", binding_key="manning.raster")

    semantic_gate: Dict[str, Any]
    try:
        semantic_gate = validate_flat_edda_controls(parameters)
    except SemanticGateViolation as exc:
        semantic_gate = {
            "strict": True,
            "decision": "reject",
            "code": exc.code,
            "details": exc.details,
        }
        add_error(
            exc.code,
            exc.message,
            parameter_key=(
                f"edda.run_controls.{exc.details['control']}"
                if exc.details.get("control")
                else "edda.registry_version"
            ),
        )

    dem_meta = (by_key.get("dem.primary") or {}).get("raster_metadata") or {}
    dem_shape = (dem_meta.get("rows"), dem_meta.get("cols"))
    if all(value is not None for value in dem_shape):
        for binding in bindings:
            if binding.get("role") not in {"rainfall-period", "manning-raster", "zones", "slope", "thickness"}:
                continue
            metadata = binding.get("raster_metadata") or {}
            shape = (metadata.get("rows"), metadata.get("cols"))
            if all(value is not None for value in shape) and shape != dem_shape:
                add_error("grid_shape_mismatch", f"栅格 {binding.get('binding_key')} 的行列数与 DEM 不一致。", binding_key=str(binding.get("binding_key") or ""))
                continue
            if dem_meta.get("cell_size") is not None and metadata.get("cell_size") is not None:
                if not math.isclose(float(dem_meta["cell_size"]), float(metadata["cell_size"]), rel_tol=1e-9, abs_tol=1e-12):
                    add_error("grid_resolution_mismatch", f"栅格 {binding.get('binding_key')} 的分辨率与 DEM 不一致。", binding_key=str(binding.get("binding_key") or ""))
            dem_origin = dem_meta.get("origin") or {}
            origin = metadata.get("origin") or {}
            if all(value is not None for value in (dem_origin.get("x"), dem_origin.get("y"), origin.get("x"), origin.get("y"))):
                if not (
                    math.isclose(float(dem_origin["x"]), float(origin["x"]), rel_tol=0.0, abs_tol=1e-9)
                    and math.isclose(float(dem_origin["y"]), float(origin["y"]), rel_tol=0.0, abs_tol=1e-9)
                ):
                    add_error("grid_origin_mismatch", f"栅格 {binding.get('binding_key')} 的空间原点与 DEM 不一致。", binding_key=str(binding.get("binding_key") or ""))
            dem_extent = dem_meta.get("extent")
            extent = metadata.get("extent")
            if isinstance(dem_extent, (list, tuple)) and isinstance(extent, (list, tuple)) and len(dem_extent) == len(extent) == 4:
                if any(not math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-8) for left, right in zip(dem_extent, extent)):
                    add_error("grid_extent_mismatch", f"栅格 {binding.get('binding_key')} 的空间范围与 DEM 不一致。", binding_key=str(binding.get("binding_key") or ""))
            dem_crs = dem_meta.get("crs")
            crs = metadata.get("crs")
            if dem_crs and crs and str(dem_crs) != str(crs):
                add_error("grid_crs_mismatch", f"栅格 {binding.get('binding_key')} 的坐标参考系与 DEM 不一致。", binding_key=str(binding.get("binding_key") or ""))

    zones_value = parameters.get("spatial_zones.zones")
    if zones_value is not None:
        if not isinstance(zones_value, dict):
            add_error(
                "spatial_zones_invalid",
                "分区参数必须是以区号为键的对象。",
                parameter_key="spatial_zones.zones",
            )
        else:
            seen_zone_ids: set[int] = set()
            for raw_key, raw_row in zones_value.items():
                zone_id = _coerce_zone_id(raw_key, raw_row)
                if zone_id is None:
                    add_error(
                        "spatial_zone_id_invalid",
                        f"分区标识无效：{raw_key!r}。",
                        parameter_key="spatial_zones.zones",
                    )
                    continue
                if zone_id in seen_zone_ids:
                    add_error(
                        "spatial_zone_id_duplicate",
                        f"分区 {zone_id} 重复。",
                        parameter_key="spatial_zones.zones",
                    )
                seen_zone_ids.add(zone_id)
                if not isinstance(raw_row, dict):
                    add_error(
                        "spatial_zone_row_invalid",
                        f"分区 {zone_id} 不是有效对象。",
                        parameter_key="spatial_zones.zones",
                    )
                    continue
                numeric_fields: Dict[str, float] = {}
                for field_name, value in raw_row.items():
                    name = str(field_name)
                    if name == "cvero" and value is None:
                        continue
                    if name in ZONE_PATCH_PASSTHROUGH_KEYS:
                        continue
                    if name not in ZONE_LAYER_FIELD_MAP:
                        add_warning(
                            "spatial_zone_field_ignored",
                            f"分区 {zone_id} 忽略未知字段 {name}。",
                            parameter_key="spatial_zones.zones",
                        )
                        continue
                    if value is None:
                        continue
                    try:
                        numeric_fields[name] = float(value)
                    except (TypeError, ValueError):
                        add_error(
                            "spatial_zone_field_not_numeric",
                            f"分区 {zone_id} 的 {name} 必须是数值。",
                            parameter_key="spatial_zones.zones",
                        )
                for ksat_key, label in (
                    ("K_sat_top", "顶层 K_sat"),
                    ("K_sat_bottom", "底层 K_sat"),
                    ("K_sat", "K_sat"),
                ):
                    if ksat_key in numeric_fields and numeric_fields[ksat_key] <= 0.0:
                        add_error(
                            "spatial_zone_ksat_nonpositive",
                            f"分区 {zone_id} 的 {label} 必须大于 0。",
                            parameter_key="spatial_zones.zones",
                        )
                top_sat = numeric_fields.get("theta_sat_top", numeric_fields.get("theta_s"))
                top_res = numeric_fields.get("theta_res_top")
                if top_sat is not None and top_res is not None and not (top_sat > top_res):
                    add_error(
                        "spatial_zone_theta_order_invalid",
                        f"分区 {zone_id} 顶层 theta_sat 必须大于 theta_res。",
                        parameter_key="spatial_zones.zones",
                    )
                bottom_sat = numeric_fields.get("theta_sat_bottom")
                bottom_res = numeric_fields.get("theta_res_bottom")
                if bottom_sat is not None and bottom_res is not None and not (bottom_sat > bottom_res):
                    add_error(
                        "spatial_zone_theta_order_invalid",
                        f"分区 {zone_id} 底层 theta_sat 必须大于 theta_res。",
                        parameter_key="spatial_zones.zones",
                    )

    for key, enum_spec in PARAMETER_ENUM_SPECS.items():
        if key not in parameters:
            continue
        value = parameters.get(key)
        allowed = list(enum_spec.get("allowed_values") or [])
        if value is None:
            continue
        value_type = str(enum_spec.get("value_type") or "enum")
        if value_type == "boolean":
            if not isinstance(value, bool):
                add_error(
                    "parameter_enum_invalid",
                    f"参数 {key} 必须为布尔值。",
                    parameter_key=key,
                )
            continue
        allowed_text = [str(item) for item in allowed]
        if not isinstance(value, str) or value not in allowed_text:
            add_error(
                "parameter_enum_invalid",
                f"参数 {key} 取值无效：{value!r}；允许值：{', '.join(allowed_text)}。",
                parameter_key=key,
            )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "edda_semantic_gate": semantic_gate,
    }


def build_structured_rainfall_payload(
    parameters: Dict[str, Any],
    manifest: list[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _rainfall_is_active(parameters):
        return {
            "mode": str(parameters.get("rainfall.mode") or "uniform"),
            "units": "m/s",
            "timeline": deepcopy(parameters.get("rainfall.timeline")),
            "periods": [],
        }
    bindings = _active_bindings(manifest)
    periods = deepcopy(parameters.get("rainfall.periods") or [])
    resolved = []
    for offset, period in enumerate(periods):
        period_id = str(period.get("period_id") or f"period-{offset + 1:04d}")
        source = str(period.get("source") or "uniform").lower()
        item = {
            "period_id": period_id,
            "index": int(period.get("index") or offset + 1),
            "start_s": float(period["start_s"]),
            "end_s": float(period["end_s"]),
            "source": "raster" if source in RASTER_SOURCES else "uniform",
        }
        if item["source"] == "raster":
            binding = next(
                (
                    entry
                    for entry in bindings
                    if entry.get("role") == "rainfall-period"
                    and (
                        str(entry.get("period_id") or "") == period_id
                        or str(entry.get("asset_id") or entry.get("upload_id") or "") == str(period.get("asset_id") or "")
                    )
                ),
                None,
            )
            if not binding or not binding.get("blob_path"):
                raise ValueError(f"Rainfall period {period_id} has no resolved raster asset.")
            item["asset_id"] = binding.get("asset_id") or binding.get("upload_id")
            item["path"] = str(binding["blob_path"])
        else:
            item["cri_mps"] = float(period.get("cri_mps") or 0.0)
        resolved.append(item)
    return {
        "mode": str(parameters.get("rainfall.mode") or "uniform"),
        "units": "m/s",
        "timeline": deepcopy(parameters.get("rainfall.timeline")),
        "periods": resolved,
    }


def materialize_structured_rainfall(
    payload: Dict[str, Any],
    *,
    dem_file: str,
    output_dir: Path,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Create the existing canonical CSV/spatial-series forcing from semantic periods."""
    periods = list(payload.get("periods") or [])
    if not periods:
        raise ValueError("Structured rainfall requires at least one period.")
    boundaries = [float(periods[0]["start_s"]), *[float(item["end_s"]) for item in periods]]
    sources = [str(item.get("source") or "uniform") for item in periods]
    audit = {
        "source_mode": "structured_scenario",
        "units": {"stored": "m/s", "generated_spatial_tif": "mm/hr"},
        "interval_bounds_s": boundaries,
        "period_sources": sources,
    }
    if all(source == "uniform" for source in sources):
        rainfall_file = output_dir / "_generated_inputs" / "rainfall_from_structured_scenario.csv"
        _write_rainfall_file([float(item.get("cri_mps") or 0.0) for item in periods], boundaries, rainfall_file)
        audit["generated_file"] = str(rainfall_file)
        return {"mode": "single_file", "file": str(rainfall_file)}, audit

    dem_grid, dem_metadata = SpatialInputLoader(dem_file).read()
    dem_shape = dem_grid.shape
    dem_nodata = dem_metadata.get("nodata")
    dem_active = np.isfinite(dem_grid) if dem_nodata is None else ~np.isclose(dem_grid, dem_nodata)
    spatial_dir = output_dir / "_generated_inputs" / "rainfall_structured"
    spatial_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    for index, period in enumerate(periods, start=1):
        if period.get("source") == "raster":
            source_path = Path(str(period.get("path") or ""))
            if not source_path.is_file():
                raise FileNotFoundError(f"Structured rainfall raster is missing: {source_path}")
            grid_mps, metadata = SpatialInputLoader(str(source_path)).read()
            if grid_mps.shape != dem_shape:
                raise ValueError(
                    f"Structured rainfall shape {grid_mps.shape} does not match DEM shape {dem_shape}: {source_path}"
                )
            grid_mps = fill_raster_nodata(grid_mps, metadata.get("nodata"), 0.0)
        else:
            grid_mps = np.full(dem_shape, float(period.get("cri_mps") or 0.0), dtype=np.float64)
        grid_mps = np.where(dem_active, grid_mps, 0.0)
        target = spatial_dir / f"period_{index:04d}.tif"
        _write_geotiff_grid(target, grid_mps * 3600.0 * 1000.0, dem_metadata)
        generated.append(str(target))
    audit["generated_directory"] = str(spatial_dir)
    audit["generated_files"] = generated
    return {
        "mode": "spatial_tif_series",
        "directory": str(spatial_dir),
        "file_pattern": "period_*.tif",
        "time_step_hours": (boundaries[1] - boundaries[0]) / 3600.0,
        "interval_bounds_s": boundaries,
    }, audit
