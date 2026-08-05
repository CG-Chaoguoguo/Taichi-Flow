"""Apply scenario parameter_patch overrides onto a parsed edda_in result."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from api.services.reference_config_parser import (
    NativeInputFileRef,
    ReferenceConfigParseResult,
    _build_rainfall_period_sources,
    _determine_manning_source,
)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_manning_source(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"global_manning", "global_initiation_manning", "global", "uniform"}:
        return "global_initiation_manning"
    if text in {"raster_manningfil", "raster", "spatial", "file"}:
        return "raster_manningfil"
    return text


def _normalize_rainfall_mode(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"uniform", "uniform_cri", "global"}:
        return "uniform_cri"
    if text in {"raster", "raster_rifil", "spatial", "file"}:
        return "raster_rifil"
    if text == "mixed":
        return "mixed"
    return text


def _force_manning_source(parsed: ReferenceConfigParseResult, source: str) -> None:
    """Mutate file_inputs / manning_source to match the requested mode."""
    manning_ref = parsed.file_inputs.get("manningfil")
    if source == "global_initiation_manning":
        if manning_ref is not None:
            # Preserve paths for audit but mark as non-existent so runtime falls back.
            manning_ref.exists = [False for _ in manning_ref.exists] or [False]
        parsed.manning_source = "global_initiation_manning"
        return

    if source == "raster_manningfil":
        if manning_ref is None:
            parsed.file_inputs["manningfil"] = NativeInputFileRef(
                family="manningfil",
                raw_paths=[],
                resolved_paths=[],
                exists=[False],
                priority="priority-2",
                production_status="production-reachable",
                notes="Requested by scenario override; upload required.",
            )
        parsed.manning_source = "raster_manningfil"


def _apply_rainfall_mode(parsed: ReferenceConfigParseResult, mode: str) -> None:
    if not parsed.cri_mps:
        return
    if mode == "uniform_cri":
        # Keep non-negative cri values; convert negatives to a small positive placeholder
        # so uniform mode activates. Prefer absolute value when previously negative.
        new_cri: List[float] = []
        for cri in parsed.cri_mps:
            if cri < 0:
                new_cri.append(0.0)
            else:
                new_cri.append(float(cri))
        parsed.cri_mps = new_cri
    elif mode == "raster_rifil":
        parsed.cri_mps = [-1.0 for _ in parsed.cri_mps]
    # mixed: leave cri as-is; period overrides can refine


def _apply_rainfall_periods(parsed: ReferenceConfigParseResult, periods: Any) -> None:
    if not isinstance(periods, list):
        return
    for period in periods:
        if not isinstance(period, dict):
            continue
        index = period.get("index") or period.get("period_index")
        if index is None:
            continue
        try:
            idx = int(index) - 1
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(parsed.cri_mps):
            continue

        source = str(period.get("source") or "").strip().lower()
        if "cri_mps" in period and period["cri_mps"] is not None:
            cri = float(period["cri_mps"])
            if source in {"rifil", "rifil_grid", "raster", "raster_rifil"}:
                parsed.cri_mps[idx] = -abs(cri) if cri != 0 else -1.0
            elif source in {"uniform", "uniform_cri"}:
                parsed.cri_mps[idx] = abs(cri)
            else:
                parsed.cri_mps[idx] = cri
        elif source in {"rifil", "rifil_grid", "raster", "raster_rifil"}:
            parsed.cri_mps[idx] = -1.0
        elif source in {"uniform", "uniform_cri"}:
            if parsed.cri_mps[idx] < 0:
                parsed.cri_mps[idx] = 0.0

        # Optional capt bound updates
        start_s = period.get("start_s")
        end_s = period.get("end_s")
        if start_s is not None and idx < len(parsed.capt_s):
            parsed.capt_s[idx] = float(start_s)
        if end_s is not None and idx + 1 < len(parsed.capt_s):
            parsed.capt_s[idx + 1] = float(end_s)


def _rebuild_rainfall_derived(parsed: ReferenceConfigParseResult) -> None:
    mode, period_sources, period_source_map = _build_rainfall_period_sources(
        parsed.cri_mps,
        parsed.capt_s,
        parsed.file_inputs,
    )
    parsed.rainfall_mode = mode
    parsed.rainfall_period_sources = period_sources
    parsed.period_source_map = period_source_map


def _inject_native_manning_path(parsed: ReferenceConfigParseResult, overrides: Dict[str, Any]) -> None:
    """Allow uploaded manningfil path via native_inputs.files.manningfil."""
    native = _as_dict(overrides.get("native_inputs"))
    files = _as_dict(native.get("files"))
    manning_entry = files.get("manningfil")
    if not isinstance(manning_entry, dict):
        return
    path = manning_entry.get("path")
    if not path:
        return
    path_str = str(path)
    exists = True  # uploaded blob path is expected to exist
    parsed.file_inputs["manningfil"] = NativeInputFileRef(
        family="manningfil",
        raw_paths=[path_str],
        resolved_paths=[path_str],
        exists=[exists],
        priority="priority-2",
        production_status="production-reachable",
        notes="Injected from scenario/workbench upload override.",
    )


def apply_scenario_overrides(
    parsed: ReferenceConfigParseResult,
    overrides: Optional[Dict[str, Any]],
) -> ReferenceConfigParseResult:
    """
    Return a deep-copied parse result with rainfall/manning scenario overrides applied.

    Supported override keys (after dotted expansion):
      - rainfall.mode: uniform_cri | raster_rifil | mixed
      - rainfall.periods: [{index, source, cri_mps, start_s, end_s}, ...]
      - manning.source: global_manning | raster_manningfil
      - rheology.n_manning: global Manning scalar (also updates manning_global)
    """
    if not overrides:
        return parsed

    result = deepcopy(parsed)
    rainfall = _as_dict(overrides.get("rainfall"))
    manning = _as_dict(overrides.get("manning"))
    rheology = _as_dict(overrides.get("rheology"))

    _inject_native_manning_path(result, overrides)

    n_manning = rheology.get("n_manning")
    if n_manning is not None:
        result.manning_global = float(n_manning)

    manning_source = _normalize_manning_source(manning.get("source"))
    if manning_source:
        _force_manning_source(result, manning_source)
    else:
        # Re-evaluate from file existence after possible path injection
        result.manning_source = _determine_manning_source(result.file_inputs)

    rainfall_mode = _normalize_rainfall_mode(rainfall.get("mode"))
    if rainfall_mode:
        _apply_rainfall_mode(result, rainfall_mode)

    if "periods" in rainfall:
        _apply_rainfall_periods(result, rainfall.get("periods"))

    _rebuild_rainfall_derived(result)
    return result
