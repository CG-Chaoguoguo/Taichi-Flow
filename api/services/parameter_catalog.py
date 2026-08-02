"""Frontend-safe parameter catalog for Taichi Flow."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api.services.reference_config_parser import ReferenceConfigParseResult


EDITABLE_PARAMETERS = {
    "hydrology.use_background_flux_offset",
    "hydrology.K_sat",
    "soil.gamma_s",
    "soil.c",
    "soil.phi",
    "soil.gamma_w",
    "rheology.n_manning",
    "rheology.limitfr",
}

CASE_CONFIG_OVERRIDE_PATHS = {
    "alpha1": ["rheology.alpha1"],
    "alpha2": ["rheology.alpha2"],
    "background_flux_offset": ["hydrology.use_background_flux_offset"],
    "beta1": ["rheology.beta1"],
    "beta2": ["rheology.beta2"],
    "coedepo": ["erosion.coedepo", "erosion.k_deposition"],
    "cs": ["rheology.cs"],
    "d50": ["erosion.d50"],
    "depth": ["soil.depth", "hydrology.depthwt_initial"],
    "dtmax": ["time.dt_max"],
    "dtmin": ["time.dt_min"],
    "dtd": ["time.dt_decrease"],
    "dti": ["time.dt_increase"],
    "kresis": ["rheology.kresis"],
    "lbstar": ["soil.double_layer.lbstar"],
    "limitfr": ["rheology.limitfr"],
    "ltstar": ["soil.double_layer.ltstar"],
    "manning_global": ["rheology.n_manning"],
    "min_slope_angle_deg": ["soil.double_layer.min_slope_angle_deg"],
    "nzsb": ["soil.double_layer.nzsb"],
    "nzst": ["soil.double_layer.nzst"],
    "rizero": ["hydrology.rizero_initial"],
    "shallown": ["rheology.shallown"],
    "simul": ["time.t_end"],
    "toldh": ["time.toldh"],
    "toldhp": ["time.toldhp"],
    "tout": ["time.dt_output"],
    "uww": ["soil.gamma_w", "soil.double_layer.uww"],
    "wavemax": ["time.wavemax"],
    "zones": ["spatial_zones.zones"],
    "zonfil": ["spatial_zones.zone_file"],
}

CONFIG_PATHS = {
    **{key: paths[0] for key, paths in CASE_CONFIG_OVERRIDE_PATHS.items()},
    "hydrology.use_background_flux_offset": "hydrology.use_background_flux_offset",
    "hydrology.K_sat": "hydrology.K_sat",
    "soil.gamma_s": "soil.gamma_s",
    "soil.c": "soil.c",
    "soil.phi": "soil.phi",
    "soil.gamma_w": "soil.gamma_w",
    "rheology.n_manning": "rheology.n_manning",
    "rheology.limitfr": "rheology.limitfr",
    "rainfall_mode": "rainfall",
    "rainfall_source": "rainfall",
    "manning_source": "rheology.n_manning",
    "water_table_source": "hydrology.depthwt_initial",
    "initial_infiltration_source": "hydrology.rizero_initial",
    "dfs_infiltration_variant": "hydrology.dfs_infiltration_variant",
    "dfs_face_flux_variant": "hydrology.dfs_face_flux_variant",
    "dfs_failure_source_variant": "hydrology.dfs_failure_source_variant",
    "outflow_point_source": "native_inputs.files.outflow",
    "inflow_source": "native_inputs.files.inflow",
}

LABELS = {
    "alpha1": "Quadratic rheology alpha1",
    "alpha2": "Quadratic rheology alpha2",
    "background_flux_offset": "Background infiltration offset",
    "beta1": "Quadratic rheology beta1",
    "beta2": "Quadratic rheology beta2",
    "coedepo": "Deposition coefficient",
    "cs": "Suspension coefficient",
    "d50": "Median particle diameter",
    "depth": "Soil depth / initial water table fallback",
    "dtmax": "Maximum timestep",
    "dtmin": "Minimum timestep",
    "dtd": "Rejected-step timestep decrement",
    "dti": "Accepted-step timestep increment",
    "kresis": "Viscous resistance coefficient",
    "lbstar": "Bottom layer thickness",
    "ltstar": "Top layer thickness",
    "manning_global": "Global Manning roughness",
    "min_slope_angle_deg": "Minimum slope angle threshold",
    "nzsb": "Bottom-layer sublayer count",
    "nzst": "Top-layer sublayer count",
    "rizero": "Initial infiltration fallback",
    "simul": "Simulation end time",
    "toldh": "Absolute depth-change limiter",
    "toldhp": "Relative depth-change limiter",
    "tout": "Output interval",
    "uww": "Water unit weight",
    "wavemax": "Dynamic-wave stability coefficient",
    "zones": "Spatial zone parameters",
    "zonfil": "Zone raster file",
    "hydrology.use_background_flux_offset": "Background infiltration offset",
    "hydrology.K_sat": "Saturated hydraulic conductivity",
    "soil.gamma_s": "Soil unit weight",
    "soil.c": "Cohesion",
    "soil.phi": "Friction angle",
    "soil.gamma_w": "Water unit weight",
    "rheology.n_manning": "Manning roughness",
    "rheology.limitfr": "Froude limiter",
    "rainfall_mode": "Rainfall mode",
    "rainfall_source": "Rainfall source",
    "manning_source": "Manning source",
    "water_table_source": "Initial water table source",
    "initial_infiltration_source": "Initial infiltration source",
    "dfs_infiltration_variant": "DFS infiltration variant",
    "dfs_face_flux_variant": "DFS face-flux variant",
    "dfs_failure_source_variant": "Failure-source variant",
    "outflow_point_source": "Outflow observation source",
    "inflow_source": "Inflow forcing source",
}


def _case_override_paths(field_name: str) -> List[str]:
    return list(CASE_CONFIG_OVERRIDE_PATHS.get(field_name, []))


def _runtime_status(row: Dict[str, Any]) -> str:
    evidence = row.get("evidence") or {}
    if row.get("consumed"):
        if evidence.get("input_state") == "config_fallback" or evidence.get("resolved_via_fallback"):
            return "config_fallback_consumed"
        return "production_consumed"
    if row.get("mapped"):
        status = str(row.get("status") or evidence.get("production_status") or "")
        if "partial" in status:
            return "partial"
        return "mapped_only"
    if row.get("parsed"):
        return "parsed_only"
    return "metadata_only"


def _entry_from_audit(row: Dict[str, Any]) -> Dict[str, Any]:
    key = str(row.get("parameter"))
    evidence = row.get("evidence") or {}
    status = _runtime_status(row)
    return {
        "key": key,
        "label": LABELS.get(key, key.replace("_", " ").replace(".", " / ")),
        "config_path": CONFIG_PATHS.get(key),
        "parser_field": evidence.get("family") or key,
        "runtime_consumer": evidence.get("runtime_stage") or CONFIG_PATHS.get(key),
        "activation_condition": evidence.get("activation_condition"),
        "runtime_status": status,
        "editable": key in EDITABLE_PARAMETERS and status in {
            "production_consumed",
            "config_fallback_consumed",
        },
        "output_evidence": row.get("output_evidence") or [],
        "evidence": evidence,
    }


def _unsupported_entries(provenance: Optional[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    reference_audit = (provenance or {}).get("reference_config_audit") or {}
    for row in reference_audit.get("unsupported_flags") or []:
        key = str(row.get("flag") or row.get("parameter") or "unsupported")
        yield {
            "key": key,
            "label": key.replace("_", " "),
            "config_path": None,
            "parser_field": key,
            "runtime_consumer": None,
            "activation_condition": row.get("activation_condition"),
            "runtime_status": "unsupported",
            "editable": False,
            "output_evidence": [],
            "evidence": row,
        }


def build_parameter_catalog(
    parameter_audit: Optional[Dict[str, Any]] = None,
    runtime_input_manifest: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a frontend-safe parameter catalog from runtime evidence."""
    rows = list((parameter_audit or {}).get("parameters") or [])
    catalog = [_entry_from_audit(row) for row in rows]
    catalog.extend(_unsupported_entries(provenance))

    seen = set()
    deduped = []
    for entry in catalog:
        key = entry["key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    status_counts: Dict[str, int] = {}
    for entry in deduped:
        status = entry["runtime_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "catalog_version": "taichi-flow-parameter-catalog-v1",
        "editable_statuses": ["production_consumed", "config_fallback_consumed"],
        "parameters": deduped,
        "status_counts": status_counts,
        "input_source_registry": (runtime_input_manifest or {}).get("input_source_registry", {}),
    }


def build_static_parameter_catalog() -> Dict[str, Any]:
    """Return a minimal catalog before a case is parsed or a run is started."""
    parameters = []
    for key in sorted(EDITABLE_PARAMETERS):
        parameters.append(
            {
                "key": key,
                "label": LABELS.get(key, key),
                "config_path": CONFIG_PATHS.get(key),
                "parser_field": None,
                "runtime_consumer": CONFIG_PATHS.get(key),
                "activation_condition": "direct_config_payload",
                "runtime_status": "production_consumed",
                "editable": True,
                "output_evidence": [],
                "evidence": {"source": "static_catalog"},
            }
        )
    return {
        "catalog_version": "taichi-flow-parameter-catalog-v1",
        "editable_statuses": ["production_consumed", "config_fallback_consumed"],
        "parameters": parameters,
        "status_counts": {"production_consumed": len(parameters)},
        "input_source_registry": {},
    }


def build_case_config_interface(parsed: ReferenceConfigParseResult) -> Dict[str, Any]:
    """Build a parsed legacy case-config interface without constructing a solver."""
    audit = parsed.to_audit_dict()
    # Parsers and offline migration adapters may provide only the fields that
    # were present in a case.  Keep the catalog shape deterministic without
    # turning absent legacy values into editable runtime parameters.
    defaults = {
        "simul": 0.0,
        "tout": 0.0,
        "dtmin": 0.0,
        "dtmax": 0.0,
        "dti": 0.0,
        "dtd": 0.0,
        "toldh": 0.0,
        "toldhp": 0.0,
        "wavemax": 0.0,
        "rainfall_mode": "",
        "cri_mps": [],
        "capt_s": [],
        "manning_source": "",
        "manning_global": 0.0,
        "alpha1": 0.0,
        "beta1": 0.0,
        "alpha2": 0.0,
        "beta2": 0.0,
        "kresis": 0.0,
        "limitfr": 0.0,
        "shallown": 0.0,
        "d50": 0.0,
        "cvstar": 0.0,
        "coedepo": 0.0,
        "cs": 0.0,
        "nzsb": 0,
        "nzst": 0,
        "uww": 0.0,
        "ltstar_raw": 0.0,
        "lbstar": 0.0,
        "zmax": 0.0,
        "depth": 0.0,
        "rizero": 0.0,
        "min_slope_angle_deg": 0.0,
        "zones": {},
    }
    for name, default in defaults.items():
        if not hasattr(parsed, name):
            setattr(parsed, name, default)
    parsed_values = {
        "time": {
            "simul": parsed.simul,
            "tout": parsed.tout,
            "dtmin": parsed.dtmin,
            "dtmax": parsed.dtmax,
            "dti": parsed.dti,
            "dtd": parsed.dtd,
            "toldh": parsed.toldh,
            "toldhp": parsed.toldhp,
            "wavemax": parsed.wavemax,
        },
        "rainfall": {
            "mode": parsed.rainfall_mode,
            "cri_mps": parsed.cri_mps,
            "capt_s": parsed.capt_s,
            "periods": [
                {
                    "index": idx + 1,
                    "start_s": parsed.capt_s[idx] if idx < len(parsed.capt_s) else None,
                    "end_s": parsed.capt_s[idx + 1] if idx + 1 < len(parsed.capt_s) else None,
                    "cri_mps": cri,
                    "source": "rifil" if cri < 0 else "uniform_cri",
                }
                for idx, cri in enumerate(parsed.cri_mps)
            ],
        },
        "manning": {
            "source": parsed.manning_source,
            "global": parsed.manning_global,
        },
        "rheology": {
            "alpha1": parsed.alpha1,
            "beta1": parsed.beta1,
            "alpha2": parsed.alpha2,
            "beta2": parsed.beta2,
            "kresis": parsed.kresis,
            "manning_global": parsed.manning_global,
            "limitfr": parsed.limitfr,
            "shallown": parsed.shallown,
            "d50": parsed.d50,
            "cvstar": parsed.cvstar,
            "coedepo": parsed.coedepo,
            "cs": parsed.cs,
        },
        "double_layer": {
            "nzsb": parsed.nzsb,
            "nzst": parsed.nzst,
            "uww": parsed.uww,
            "ltstar": parsed.ltstar_raw,
            "lbstar": parsed.lbstar,
            "zmax": parsed.zmax,
            "depth": parsed.depth,
            "rizero": parsed.rizero,
            "min_slope_angle_deg": parsed.min_slope_angle_deg,
        },
        "zones": {
            str(zone_id): {
                "zone_id": zone.zone_id,
                "bottom": asdict(zone.bottom),
                "top": asdict(zone.top),
            }
            for zone_id, zone in parsed.zones.items()
        },
    }
    file_inputs: List[Dict[str, Any]] = []
    for family, ref in audit.get("file_inputs", {}).items():
        file_inputs.append(
            {
                "family": family,
                "raw_paths": ref.get("raw_paths") or [],
                "resolved_paths": ref.get("resolved_paths") or [],
                "exists": ref.get("exists") or [],
                "production_status": ref.get("production_status"),
                "activation_condition": ref.get("activation_condition"),
                "runtime_status": _file_runtime_status(ref),
                "editable": False,
                "notes": ref.get("notes"),
                "blocked_reason": ref.get("blocked_reason"),
                "expected_output_families": ref.get("expected_output_families") or [],
            }
        )

    parameters = []
    for field_name in audit.get("supported_fields") or []:
        override_paths = _case_override_paths(field_name)
        config_path = override_paths[0] if override_paths else CONFIG_PATHS.get(field_name)
        parameters.append(
            {
                "key": field_name,
                "label": LABELS.get(field_name, field_name),
                "config_path": config_path,
                "override_paths": override_paths,
                "parser_field": field_name,
                "runtime_consumer": config_path,
                "activation_condition": None,
                "runtime_status": "mapped_only",
                "editable": False,
                "output_evidence": [],
                "evidence": {
                    "source": "case_config_parse",
                    "override_payload_field": "overrides",
                    "override_paths": override_paths,
                },
            }
        )
    for field_name in audit.get("recognized_unsupported_fields") or []:
        parameters.append(
            {
                "key": field_name,
                "label": field_name,
                "config_path": None,
                "parser_field": field_name,
                "runtime_consumer": None,
                "activation_condition": None,
                "runtime_status": "unsupported",
                "editable": False,
                "output_evidence": [],
                "evidence": {"source": "case_config_parse"},
            }
        )

    return {
        "case_config_file": parsed.reference_config_file,
        "case_base_dir": parsed.reference_base_dir,
        "case_config_name": Path(parsed.reference_config_file).name,
        "file_inputs": file_inputs,
        "parsed_values": parsed_values,
        "parameter_catalog": {
            "catalog_version": "taichi-flow-case-config-catalog-v1",
            "editable_statuses": ["production_consumed", "config_fallback_consumed"],
            "parameters": parameters,
        },
        "runtime_status": {
            "source_mode": "legacy_case_config",
            "supported_field_count": len(audit.get("supported_fields") or []),
            "recognized_unsupported_field_count": len(audit.get("recognized_unsupported_fields") or []),
            "unrecognized_field_count": len(audit.get("unrecognized_fields") or []),
        },
        "audit": audit,
    }


def _file_runtime_status(ref: Dict[str, Any]) -> str:
    status = str(ref.get("production_status") or "")
    if "production-reachable" in status:
        return "production_consumed"
    if status == "partial":
        return "partial"
    if "recognized" in status:
        return "metadata_only"
    return "unsupported"
