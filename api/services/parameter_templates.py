"""Versioned, path-free parameter templates for scenario authoring."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from api.services.edda_switch_registry import (
    EDDA_SWITCH_REGISTRY,
    REGISTRY_VERSION,
    canonical_control_value,
)
from api.services.rainfall_timeline import timeline_from_boundaries

BJ_HXL_TEMPLATE_V1_ID = "pt-bj-hxl-v1"
BJ_HXL_TEMPLATE_V2_ID = "pt-bj-hxl-v2"
BJ_HXL_TEMPLATE_V3_ID = "pt-bj-hxl-v3"
BJ_HXL_TEMPLATE_ID = "pt-bj-hxl-v4"
BJ_HXL_SOURCE_HASH = "6ed94a70bd075d392c4cd1ea2659416efc62e2beb0e9c8ca247648ff50cd9689"

BJ_HXL_SWITCH_VALUES: Dict[str, Any] = {
    "save_runoff_grids": False,
    "save_fs_min_legacy": True,
    "save_fs_depth_at_min": True,
    "save_fs_pore_pressure_at_min": False,
    "save_infiltration_rate": False,
    "save_basal_flux": False,
    "save_deposit_distribution": True,
    "save_pf": False,
    "save_road_risk": False,
    "save_road_warning": False,
    "save_detached_trace": False,
    "pressure_head_fs_listing_flag": -1,
    "slope_failure_output_count": 1,
    "slope_failure_output_times_s": [3600.0],
    "skip_other_timesteps": False,
    "use_analytic_fillable_porosity": True,
    "estimate_positive_pressure_head": True,
    "use_psi0_negative_inverse_alpha": False,
    "log_mass_balance_results": True,
    "flow_direction_mode": "slope",
    "background_flux_offset": True,
    "use_full_dynamic_wave": True,
    "simulate_rainfall": True,
    "simulate_infiltration": True,
    "simulate_inflow_hydrograph": False,
    "simulate_outflow_cell": True,
    "simulate_shallow_landslide": True,
    "simulate_debris_flow": True,
    "simulate_erosion": True,
    "simulate_water_and_solid_separately": True,
    "simulate_drainage_flow": False,
    "simulate_barrier": False,
    "save_fs_min_grid": True,
    "save_flow_depth": True,
    "save_max_flow_depth": True,
    "save_flow_velocity": True,
    "save_max_flow_velocity": True,
    "save_erosion_depth": True,
    "save_deposition_depth": True,
    "save_total_depth": True,
    "save_max_solid_depth": True,
    "save_volumetric_sediment_concentration": True,
    "save_outflow_process": False,
    "save_drainage_nodal_flow": False,
    "save_drainage_conduit_flow": False,
}

if tuple(BJ_HXL_SWITCH_VALUES) != tuple(spec.key for spec in EDDA_SWITCH_REGISTRY):
    raise RuntimeError("BJ_HXL switch defaults must follow the canonical 45-switch order")


def _bj_hxl_rainfall_periods() -> list[Dict[str, Any]]:
    return [
        {
            "period_id": f"period-{index:04d}",
            "index": index,
            "start_s": float((index - 1) * 3600),
            "end_s": float(index * 3600),
            "source": "raster",
            "cri_mps": None,
        }
        for index in range(1, 73)
    ]


def _bj_hxl_values() -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "hydrology.use_background_flux_offset": True,
        "hydrology.K_sat": 1.0e-6,
        "hydrology.rizero_initial": 1.0e-9,
        "hydrology.depthwt_initial": 7.0,
        "soil.gamma_s": 21000.0,
        "soil.c": 10500.0,
        "soil.phi": 26.0,
        "soil.gamma_w": 9800.0,
        "soil.depth": 7.0,
        "soil.double_layer.lbstar": 4.0,
        "soil.double_layer.ltstar": 3.0,
        "soil.double_layer.min_slope_angle_deg": 0.1,
        "soil.double_layer.nzsb": 10,
        "soil.double_layer.nzst": 10,
        "soil.double_layer.uww": 9800.0,
        "rheology.n_manning": 0.1,
        "rheology.limitfr": 1.0,
        "rheology.alpha1": 3.8,
        "rheology.alpha2": 0.02,
        "rheology.beta1": 3.51,
        "rheology.beta2": 2.97,
        "rheology.cs": 0.7,
        "rheology.kresis": 2500.0,
        "rheology.shallown": 0.2,
        "erosion.d50": 0.001,
        "erosion.coedepo": 0.005,
        "erosion.k_deposition": 0.005,
        "time.t_end": 259200.0,
        "time.dt_max": 2.0,
        "time.dt_min": 1.0e-5,
        "time.dt_decrease": 0.001,
        "time.dt_increase": 0.0001,
        "time.toldh": 0.05,
        "time.toldhp": 0.1,
        "time.dt_output": 3600.0,
        "time.wavemax": 0.25,
        "compute.use_double_precision": False,
        "compute.async_output": True,
        "compute.write_geotiff_frames": True,
        "compute.numerical_observe_stride": 20,
        "rainfall.mode": "raster",
        "rainfall.periods": _bj_hxl_rainfall_periods(),
        "manning.source": "global",
        "spatial_zones.zones": {
            "1": {
                "zone_id": 1,
                "K_sat": 1.0e-6,
                "theta_s": 0.4,
                "theta_i": 0.1155,
                "psi_f": 0.051,
                "c": 10500.0,
                "phi": 26.0,
                "gamma_s": 21000.0,
                "gamma_w": 9800.0,
                "depth": 7.0,
                "n_manning": 0.1,
                "alpha1": 3.8,
                "beta1": 3.51,
                "alpha2": 0.02,
                "beta2": 2.97,
                "alpha_top": 0.8,
                "alpha_bottom": 0.8,
                "K_sat_top": 1.0e-6,
                "K_sat_bottom": 1.0e-6,
                "theta_sat_top": 0.4,
                "theta_sat_bottom": 0.4,
                "theta_res_top": 0.25,
                "theta_res_bottom": 0.25,
                "phib": 24.6,
                "kero": 5.0e-7,
                "ctao": 15.0,
                "ltstar": 3.0,
                "lbstar": 4.0,
            }
        },
    }
    return values


def _template_payload(template_id: str, version: str, values: Dict[str, Any]) -> Dict[str, Any]:
    topology = values.get("hydrology.dfs_failure_source_variant") or "precomputed_unsfin_schedule"
    return {
        "template_id": template_id,
        "version": version,
        "name": "BJ_HXL_Text 默认参数",
        "description": "由 BJ_HXL_Text 自然案例规范化得到；不包含任何文件路径。",
        "source_kind": "bundled_case",
        "source_hash": BJ_HXL_SOURCE_HASH,
        "values": deepcopy(values),
        "field_provenance": {
            key: {"source": "BJ_HXL_Text/edda_in.txt", "source_hash": BJ_HXL_SOURCE_HASH}
            for key in values
        } | {
            "_compute_policy": {
                "source_mode": "bundled_case",
                "source_files": ["BJ_HXL_Text/edda_in.txt", "dfs.F90", "edda main program.F90"],
                "original_fssimul": values.get("edda.run_controls.simulate_shallow_landslide", True),
                "topology": topology,
                "topology_status": "recognized",
                "evidence": [
                    {
                        "active_statement": "bundled BJ template topology",
                        "matched": True,
                        "source": "BJ_HXL_Text",
                    }
                ],
                "detector_version": "template-v1",
            }
        },
    }


def builtin_bj_hxl_template_v1() -> Dict[str, Any]:
    """Keep the original template immutable for scenarios already referencing it."""
    return _template_payload(BJ_HXL_TEMPLATE_V1_ID, "1", _bj_hxl_values())


def _bj_hxl_v2_values() -> Dict[str, Any]:
    values = _bj_hxl_values()
    boundaries = [float(index * 3600) for index in range(73)]
    values["rainfall.timeline"] = timeline_from_boundaries(
        boundaries,
        source="bundled_case",
        declared_period_count=72,
        declared_end_s=259200.0,
    )
    return values


def builtin_bj_hxl_template_v2() -> Dict[str, Any]:
    """Keep the timeline-enabled v2 immutable for existing scenarios."""
    return _template_payload(BJ_HXL_TEMPLATE_V2_ID, "2", _bj_hxl_v2_values())


def _bj_hxl_v3_values() -> Dict[str, Any]:
    values = _bj_hxl_v2_values()
    values["edda.registry_version"] = REGISTRY_VERSION
    for spec in EDDA_SWITCH_REGISTRY:
        values[spec.taichi_config_path] = deepcopy(BJ_HXL_SWITCH_VALUES[spec.key])
    return values


def builtin_bj_hxl_template_v3() -> Dict[str, Any]:
    """Keep the 45-control v3 snapshot immutable for existing scenarios."""
    return _template_payload(BJ_HXL_TEMPLATE_V3_ID, "3", _bj_hxl_v3_values())


def builtin_bj_hxl_template() -> Dict[str, Any]:
    """Return current BJ_HXL defaults with failure-source topology recorded."""
    values = _bj_hxl_v3_values()
    values["hydrology.dfs_failure_source_variant"] = "precomputed_unsfin_schedule"
    return _template_payload(BJ_HXL_TEMPLATE_ID, "4", values)


def builtin_parameter_templates() -> list[Dict[str, Any]]:
    return [
        builtin_bj_hxl_template_v1(),
        builtin_bj_hxl_template_v2(),
        builtin_bj_hxl_template_v3(),
        builtin_bj_hxl_template(),
    ]


def canonicalize_edda_control_parameters(values: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce parser-absent boolean switches to False without changing key count."""
    canonical = deepcopy(values)
    for spec in EDDA_SWITCH_REGISTRY:
        path = spec.taichi_config_path
        if path in canonical:
            canonical[path] = canonical_control_value(spec, canonical[path])
    return canonical


def merge_parameter_values(baseline: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the flat, dotted scenario parameter contract deterministically."""
    return canonicalize_edda_control_parameters({**deepcopy(baseline), **deepcopy(patch)})


def normalize_rainfall_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Derive timeline metadata for older clients that only submit period rows."""
    normalized = deepcopy(patch)
    periods = normalized.get("rainfall.periods")
    if "rainfall.timeline" in normalized or not isinstance(periods, list) or not periods:
        return normalized
    try:
        boundaries = [float(periods[0]["start_s"]), *[float(period["end_s"]) for period in periods]]
    except (KeyError, TypeError, ValueError):
        return normalized
    normalized["rainfall.timeline"] = timeline_from_boundaries(
        boundaries,
        source="period_rows_compat",
        declared_period_count=len(periods),
        declared_end_s=boundaries[-1],
    )
    return normalized


def normalized_parameter_values(parsed: Any) -> Dict[str, Any]:
    """Convert a parsed legacy config to the path-free scenario parameter contract."""
    values = builtin_bj_hxl_template()["values"]
    # Reference-case mapping has always initialized the production solver in
    # FP64. Keep that source-owned runtime default visible and frozen in each
    # imported reference template instead of inheriting the ordinary template's
    # FP32 default implicitly.
    values["compute.use_double_precision"] = True
    scalar_map = {
        "hydrology.use_background_flux_offset": "background_flux_offset",
        "hydrology.rizero_initial": "rizero",
        "hydrology.depthwt_initial": "depth",
        "soil.gamma_w": "uww",
        "soil.depth": "depth",
        "soil.double_layer.lbstar": "lbstar",
        "soil.double_layer.min_slope_angle_deg": "min_slope_angle_deg",
        "soil.double_layer.nzsb": "nzsb",
        "soil.double_layer.nzst": "nzst",
        "soil.double_layer.uww": "uww",
        "rheology.n_manning": "manning_global",
        "rheology.limitfr": "limitfr",
        "rheology.alpha1": "alpha1",
        "rheology.alpha2": "alpha2",
        "rheology.beta1": "beta1",
        "rheology.beta2": "beta2",
        "rheology.cs": "cs",
        "rheology.kresis": "kresis",
        "rheology.shallown": "shallown",
        "rheology.debrisflowmanning": "debrisflowmanning",
        "rheology.cvlandslide": "cvlandslide",
        "rheology.cvglacier": "cvglacier",
        "erosion.d50": "d50",
        "erosion.coedepo": "coedepo",
        "erosion.k_deposition": "coedepo",
        "time.t_end": "simul",
        "time.dt_max": "dtmax",
        "time.dt_min": "dtmin",
        "time.dt_decrease": "dtd",
        "time.dt_increase": "dti",
        "time.toldh": "toldh",
        "time.toldhp": "toldhp",
        "time.dt_output": "tout",
        "time.wavemax": "wavemax",
    }
    for key, attribute in scalar_map.items():
        value = getattr(parsed, attribute, None)
        if value is not None:
            values[key] = value

    ltstar_raw = float(getattr(parsed, "ltstar_raw", values["soil.double_layer.ltstar"]))
    raster_ltstar = ltstar_raw < 0
    if raster_ltstar:
        ltstar_raw = max(0.0, float(getattr(parsed, "zmax", 0.0)) - float(getattr(parsed, "lbstar", 0.0)))
    values["soil.double_layer.ltstar"] = ltstar_raw

    zones = getattr(parsed, "zones", {}) or {}
    if zones:
        default_zone = zones[sorted(zones)[0]]
        values.update(
            {
                "hydrology.K_sat": default_zone.top.k_sat,
                "soil.gamma_s": default_zone.top.gamma_s,
                "soil.c": default_zone.top.c,
                "soil.phi": default_zone.top.phi,
                "erosion.tau_c": default_zone.top.ctao,
                "erosion.ctao": default_zone.top.ctao,
                "erosion.k_erosion": default_zone.top.kero,
            }
        )
        normalized_zones: Dict[str, Any] = {}
        for zone_id, zone in zones.items():
            normalized_zones[str(zone_id)] = {
                "zone_id": int(zone.zone_id),
                "K_sat": zone.top.k_sat,
                "theta_s": zone.top.theta_sat,
                "theta_i": zone.top.theta_ini,
                "psi_f": zone.top.psi_f,
                "c": zone.top.c,
                "phi": zone.top.phi,
                "gamma_s": zone.top.gamma_s,
                "gamma_w": float(getattr(parsed, "uww", 9800.0)),
                "depth": float(getattr(parsed, "depth", 1.0)),
                "n_manning": float(getattr(parsed, "manning_global", 0.03)),
                "alpha1": float(getattr(parsed, "alpha1", 0.0765)),
                "beta1": float(getattr(parsed, "beta1", 10.11)),
                "alpha2": float(getattr(parsed, "alpha2", 0.0538)),
                "beta2": float(getattr(parsed, "beta2", 17.48)),
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
                "cvero": zone.top.cvero,
                "c_bottom": zone.bottom.c,
                "phi_bottom": zone.bottom.phi,
                "phib_bottom": zone.bottom.phib,
                "gamma_s_bottom": zone.bottom.gamma_s,
                "ltstar": 0.0 if raster_ltstar else ltstar_raw,
                "lbstar": float(getattr(parsed, "lbstar", 1.0)),
            }
        values["spatial_zones.zones"] = normalized_zones

    cri_values = list(getattr(parsed, "cri_mps", []) or [])
    boundaries = list(getattr(parsed, "capt_s", []) or [])
    values["rainfall.timeline"] = timeline_from_boundaries(
        boundaries,
        source="edda_in",
        declared_period_count=getattr(parsed, "nper", None),
        declared_end_s=getattr(parsed, "rainfall_duration_s", None),
    )
    periods = []
    for offset, cri in enumerate(cri_values):
        index = offset + 1
        raster = float(cri) < 0.0
        periods.append(
            {
                "period_id": f"period-{index:04d}",
                "index": index,
                "start_s": float(boundaries[offset]) if offset < len(boundaries) else None,
                "end_s": float(boundaries[offset + 1]) if offset + 1 < len(boundaries) else None,
                "source": "raster" if raster else "uniform",
                "cri_mps": None if raster else float(cri),
            }
        )
    values["rainfall.periods"] = periods
    mode = str(getattr(parsed, "rainfall_mode", "uniform_cri"))
    values["rainfall.mode"] = "raster" if mode == "raster_rifil" else "mixed" if mode == "mixed" else "uniform"
    values["manning.source"] = "raster" if "raster" in str(getattr(parsed, "manning_source", "")) else "global"
    face_flux = getattr(parsed, "dfs_face_flux_variant", None)
    if face_flux is not None:
        values["hydrology.dfs_face_flux_variant"] = str(face_flux)
    manningbar = getattr(parsed, "dfs_manningbar_variant", None)
    if manningbar is not None:
        values["hydrology.dfs_manningbar_variant"] = str(manningbar)
    dry_face = getattr(parsed, "dfs_dry_face_velocity_variant", None)
    if dry_face is not None:
        values["hydrology.dfs_dry_face_velocity_variant"] = str(dry_face)
    artivis = getattr(parsed, "dfs_artivis_variant", None)
    if artivis is not None:
        values["hydrology.dfs_artivis_variant"] = str(artivis)
    absubar = getattr(parsed, "dfs_absubar_variant", None)
    if absubar is not None:
        values["hydrology.dfs_absubar_variant"] = str(absubar)
    failure_source = getattr(parsed, "dfs_failure_source_variant", None)
    topology_status = str(getattr(parsed, "dfs_failure_source_topology_status", "") or "")
    if failure_source and topology_status in {"", "recognized"}:
        values["hydrology.dfs_failure_source_variant"] = str(failure_source)
    elif topology_status in {"unknown", "conflict", "missing_source"}:
        values.pop("hydrology.dfs_failure_source_variant", None)
    values.setdefault("boundary_conditions.mode", "auto")
    values.setdefault("boundary_conditions.default_type", "outflow")
    values.setdefault("boundary_conditions.include_nodata", True)
    snapshot = getattr(parsed, "switch_snapshot", None)
    if snapshot is not None:
        snapshot_values = snapshot.values
        values["edda.registry_version"] = snapshot.registry_version
        for spec in EDDA_SWITCH_REGISTRY:
            group = "output_controls" if spec.group in {"legacy_output", "process_output"} else "run_controls"
            values[f"edda.{group}.{spec.key}"] = canonical_control_value(
                spec, snapshot_values[spec.key]
            )
        for key, value in (getattr(parsed, "extension_flags", {}) or {}).items():
            values[f"edda.extension_controls.{key}"] = value
    return values
