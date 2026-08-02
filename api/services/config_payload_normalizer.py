"""Normalize service-layer config payloads without changing solver semantics."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from edda.config.sim_config import (
    BoundaryConditionConfig,
    ComputeParams,
    HydrologyParams,
    NativeInputConfig,
    RainfallConfig,
    RheologyParams,
    SimulationConfig,
    SoilParams,
    SpatialZoneConfig,
    TimeParams,
)


SECTION_MODELS: Dict[str, Type[BaseModel]] = {
    "boundary_conditions": BoundaryConditionConfig,
    "compute": ComputeParams,
    "hydrology": HydrologyParams,
    "native_inputs": NativeInputConfig,
    "rainfall": RainfallConfig,
    "rheology": RheologyParams,
    "soil": SoilParams,
    "spatial_zones": SpatialZoneConfig,
    "time": TimeParams,
}

SECTION_ALIASES: Dict[str, Dict[str, str]] = {
    "hydrology": {
        "saturated_hydraulic_conductivity": "K_sat",
        "saturated_water_content": "theta_s",
        "initial_water_content": "theta_i",
        "wetting_front_suction": "psi_f",
    },
    "soil": {
        "density": "gamma_s",
        "cohesion": "c",
        "friction_angle": "phi",
    },
    "rheology": {
        "manning_n": "n_manning",
    },
}


def _empty_audit() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "normalized_aliases": [],
        "shadowed_aliases": [],
        "dropped_unrecognized_keys": [],
    }


def _normalize_section(
    section_name: str,
    section_value: Dict[str, Any],
    model_type: Type[BaseModel],
) -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    known_fields = set(model_type.model_fields.keys())
    aliases = SECTION_ALIASES.get(section_name, {})
    normalized: Dict[str, Any] = {}
    audit = _empty_audit()

    for key, value in section_value.items():
        canonical_key = aliases.get(key, key)
        if canonical_key not in known_fields:
            audit["dropped_unrecognized_keys"].append(
                {
                    "path": f"{section_name}.{key}",
                    "reason": "unknown_section_field",
                }
            )
            continue

        if canonical_key in normalized and canonical_key != key:
            audit["shadowed_aliases"].append(
                {
                    "from": f"{section_name}.{key}",
                    "to": f"{section_name}.{canonical_key}",
                }
            )
            continue

        normalized[canonical_key] = deepcopy(value)
        if canonical_key != key:
            audit["normalized_aliases"].append(
                {
                    "from": f"{section_name}.{key}",
                    "to": f"{section_name}.{canonical_key}",
                }
            )

    return normalized, audit


def normalize_simulation_config_payload(
    config: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """
    Normalize request config aliases into canonical SimulationConfig field names.

    This is intentionally service-layer only. It does not change scientific
    formulas or introduce new solver behavior; it prevents silent parameter
    drops caused by API/frontend naming drift.
    """
    if config is None:
        return None, _empty_audit()

    if not isinstance(config, dict):
        audit = _empty_audit()
        audit["dropped_unrecognized_keys"].append(
            {
                "path": "config",
                "reason": "non_mapping_payload",
            }
        )
        return config, audit

    normalized: Dict[str, Any] = {}
    audit = _empty_audit()
    top_level_fields = set(SimulationConfig.model_fields.keys())

    for key, value in config.items():
        if key not in top_level_fields:
            audit["dropped_unrecognized_keys"].append(
                {
                    "path": key,
                    "reason": "unknown_top_level",
                }
            )
            continue

        model_type = SECTION_MODELS.get(key)
        if model_type is not None and isinstance(value, dict):
            normalized_section, section_audit = _normalize_section(key, value, model_type)
            normalized[key] = normalized_section
            for audit_key in audit:
                audit[audit_key].extend(section_audit[audit_key])
            continue

        normalized[key] = deepcopy(value)

    return normalized, audit
