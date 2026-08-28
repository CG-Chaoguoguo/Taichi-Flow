"""Apply scenario parameter_patch overrides onto a parsed edda_in result."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from api.services.reference_config_parser import (
    NativeInputFileRef,
    ReferenceConfigParseResult,
    _build_rainfall_period_sources,
    _determine_manning_source,
)

# Flattened ZoneParams key -> (layer, ZoneLayerParams attribute).
# Thickness (ltstar/lbstar) is cell-level in original EDDA, never a zone-table field.
ZONE_LAYER_FIELD_MAP: Dict[str, Tuple[str, str]] = {
    "c": ("top", "c"),
    "phi": ("top", "phi"),
    "phib": ("top", "phib"),
    "gamma_s": ("top", "gamma_s"),
    "K_sat": ("top", "k_sat"),
    "theta_s": ("top", "theta_sat"),
    "theta_i": ("top", "theta_ini"),
    "psi_f": ("top", "psi_f"),
    "K_sat_top": ("top", "k_sat"),
    "K_sat_bottom": ("bottom", "k_sat"),
    "alpha_top": ("top", "alpha"),
    "alpha_bottom": ("bottom", "alpha"),
    "theta_sat_top": ("top", "theta_sat"),
    "theta_sat_bottom": ("bottom", "theta_sat"),
    "theta_res_top": ("top", "theta_res"),
    "theta_res_bottom": ("bottom", "theta_res"),
    "c_bottom": ("bottom", "c"),
    "phi_bottom": ("bottom", "phi"),
    "phib_bottom": ("bottom", "phib"),
    "gamma_s_bottom": ("bottom", "gamma_s"),
    "kero": ("top", "kero"),
    "ctao": ("top", "ctao"),
    "cvero": ("top", "cvero"),
}

ZONE_PATCH_PASSTHROUGH_KEYS = {
    "zone_id",
    "gamma_w",
    "depth",
    "n_manning",
    "alpha1",
    "beta1",
    "alpha2",
    "beta2",
    "ltstar",
    "lbstar",
}


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


_FACE_FLUX_ALLOWED = {
    "both_thin_weighted",
    "arithmetic_mean_chamoli",
    "asymmetric_head_guard",
}
_MANNINGBAR_ALLOWED = {
    "exponential_cv",
    "debrisflowmanning_cvtol",
}
_DRY_FACE_VELOCITY_ALLOWED = {
    "keep_velocity_bj",
    "zero_dry_face_chamoli",
}
_ARTIVIS_ALLOWED = {
    "depth_ratio_bj",
    "velocity_ratio_chamoli",
}
_ABSUBAR_ALLOWED = {
    "max_component_bj",
    "signed_mean_chamoli",
}


def _coerce_zone_id(key: Any, row: Any) -> Optional[int]:
    if isinstance(row, dict) and row.get("zone_id") is not None:
        source = row.get("zone_id")
    else:
        source = key
    try:
        return int(source)
    except (TypeError, ValueError):
        return None


def _apply_zone_layer_value(layer: Any, attr: str, value: Any) -> None:
    if attr == "cvero":
        if value is None or value == "":
            layer.cvero = None
            return
        layer.cvero = float(value)
        return
    setattr(layer, attr, float(value))


def _apply_spatial_zone_overrides(parsed: ReferenceConfigParseResult, overrides: Dict[str, Any]) -> None:
    spatial = _as_dict(overrides.get("spatial_zones"))
    zones_patch = spatial.get("zones")
    if zones_patch is None:
        zones_patch = overrides.get("spatial_zones.zones")
    if not isinstance(zones_patch, dict):
        return
    for key, row in zones_patch.items():
        if not isinstance(row, dict):
            continue
        zone_id = _coerce_zone_id(key, row)
        if zone_id is None or zone_id not in parsed.zones:
            continue
        zone = parsed.zones[zone_id]
        for field_name, value in row.items():
            if field_name in ZONE_PATCH_PASSTHROUGH_KEYS or value is None:
                continue
            mapped = ZONE_LAYER_FIELD_MAP.get(str(field_name))
            if mapped is None:
                continue
            layer_name, attr = mapped
            layer = zone.top if layer_name == "top" else zone.bottom
            try:
                _apply_zone_layer_value(layer, attr, value)
            except (TypeError, ValueError):
                continue


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
      - hydrology.dfs_face_flux_variant / hydrology.dfs_manningbar_variant
      - hydrology.dfs_dry_face_velocity_variant / hydrology.dfs_artivis_variant
      - hydrology.dfs_absubar_variant
      - spatial_zones.zones: {zone_id: {flattened ZoneParams fields}}
    """
    if not overrides:
        return parsed

    result = deepcopy(parsed)
    rainfall = _as_dict(overrides.get("rainfall"))
    manning = _as_dict(overrides.get("manning"))
    rheology = _as_dict(overrides.get("rheology"))
    hydrology = _as_dict(overrides.get("hydrology"))

    _inject_native_manning_path(result, overrides)

    n_manning = rheology.get("n_manning")
    if n_manning is not None:
        result.manning_global = float(n_manning)

    face_flux = hydrology.get("dfs_face_flux_variant")
    if face_flux is not None:
        face_flux_text = str(face_flux).strip()
        if face_flux_text in _FACE_FLUX_ALLOWED:
            result.dfs_face_flux_variant = face_flux_text
            result.dfs_face_flux_variant_basis = (
                f"Scenario override selected face-flux variant `{face_flux_text}`."
            )

    manningbar = hydrology.get("dfs_manningbar_variant")
    if manningbar is not None:
        manningbar_text = str(manningbar).strip()
        if manningbar_text in _MANNINGBAR_ALLOWED:
            result.dfs_manningbar_variant = manningbar_text
            result.dfs_manningbar_variant_basis = (
                f"Scenario override selected Manning-bar variant `{manningbar_text}`."
            )

    dry_face = hydrology.get("dfs_dry_face_velocity_variant")
    if dry_face is not None:
        dry_face_text = str(dry_face).strip()
        if dry_face_text in _DRY_FACE_VELOCITY_ALLOWED:
            result.dfs_dry_face_velocity_variant = dry_face_text
            result.dfs_dry_face_velocity_variant_basis = (
                f"Scenario override selected dry-face velocity variant `{dry_face_text}`."
            )

    artivis = hydrology.get("dfs_artivis_variant")
    if artivis is not None:
        artivis_text = str(artivis).strip()
        if artivis_text in _ARTIVIS_ALLOWED:
            result.dfs_artivis_variant = artivis_text
            result.dfs_artivis_variant_basis = (
                f"Scenario override selected artificial-viscosity variant `{artivis_text}`."
            )

    absubar = hydrology.get("dfs_absubar_variant")
    if absubar is not None:
        absubar_text = str(absubar).strip()
        if absubar_text in _ABSUBAR_ALLOWED:
            result.dfs_absubar_variant = absubar_text
            result.dfs_absubar_variant_basis = (
                f"Scenario override selected absubar variant `{absubar_text}`."
            )

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

    _apply_spatial_zone_overrides(result, overrides)
    _rebuild_rainfall_derived(result)
    return result
