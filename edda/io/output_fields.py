"""Canonical solver output-field projections used by tests and exporters."""

from __future__ import annotations

from typing import Any

import numpy as np


FLOW_VELOCITY_OUTPUT_STATE_FIELDS = {
    "post_face_flux": None,
    "source_entry": "depo_velocity_source_entry",
    "pre_source_branch": "depo_velocity_pre_source_branch",
    "before_face_flux": "depo_velocity_before_face_flux",
    "after_face_flux": "depo_velocity_after_face_flux",
}


def _safe_get(state: dict[str, Any], key: str) -> np.ndarray | None:
    value = state.get(key)
    if value is None:
        return None
    try:
        return np.asarray(value)
    except Exception:
        return None


def scalar_fields(state: dict[str, Any]) -> dict[str, np.ndarray]:
    """Project solver state aliases into the public scalar output names."""

    aliases = {
        "Flow_depth": ("h", "flow_depth"),
        "Total_depth": ("total_depth",),
        "Max_flow_depth": ("max_flow_depth",),
        "Max_flow_velocity": ("max_flow_velocity",),
        "Volumetric_sediment": ("Cv", "volumetric_sediment"),
        "Erosion_depth": ("erosion_depth",),
        "Deposit_depth": ("deposition_depth", "deposit_depth"),
        "fs_min": ("FS", "fs_min"),
    }
    fields: dict[str, np.ndarray] = {}
    for output_name, keys in aliases.items():
        for key in keys:
            array = _safe_get(state, key)
            if array is not None:
                fields[output_name] = array.T if array.ndim == 2 else array
                break
    return fields


def _flow_velocity_from_directional_state(raw: Any) -> tuple[np.ndarray, np.ndarray] | None:
    array = np.asarray(raw)
    if array.ndim != 3:
        return None
    if array.shape[-1] == 8:
        directional = array.transpose(1, 0, 2)
    elif array.shape[0] == 8:
        directional = array.transpose(2, 1, 0)
    else:
        return None
    scalar = 0.5 * sum(np.abs(directional[:, :, index]) for index in range(4))
    return directional, scalar


def velocity_fields(state: dict[str, Any]) -> dict[str, np.ndarray]:
    """Project directional Fortran velocity state into named output fields."""

    fields: dict[str, np.ndarray] = {}
    converted = _flow_velocity_from_directional_state(
        state.get("fv_fortran") if state.get("fv_fortran") is not None else state.get("fv")
    ) if state.get("fv_fortran") is not None or state.get("fv") is not None else None
    if converted is not None:
        directional, scalar = converted
        for index in range(8):
            fields[f"Flow_velocity_{index + 1}"] = directional[:, :, index]
        fields["Flow_velocity"] = scalar
    direct = _safe_get(state, "flow_velocity")
    if direct is not None:
        fields["Flow_velocity"] = direct.T if direct.ndim == 2 else direct
    return fields


def add_velocity_state_diagnostics(arrays: dict[str, np.ndarray], fields_obj: Any) -> list[str]:
    """Add non-default velocity-state snapshots for diagnostic reports."""

    exported: list[str] = []
    diagnostic_sources = {
        "source_entry": "depo_velocity_source_entry",
        "pre_source_branch": "depo_velocity_pre_source_branch",
        "before_face_flux": "depo_velocity_before_face_flux",
        "after_face_flux": "depo_velocity_after_face_flux",
    }
    for label, attribute in diagnostic_sources.items():
        field = getattr(fields_obj, attribute, None)
        if field is None or not hasattr(field, "to_numpy"):
            continue
        converted = _flow_velocity_from_directional_state(field.to_numpy())
        if converted is None:
            continue
        directional, scalar = converted
        scalar_name = f"Flow_velocity_diag_{label}"
        arrays[scalar_name] = scalar
        exported.append(scalar_name)
        for index in range(8):
            direction_name = f"Flow_velocity_diag_{label}_{index + 1}"
            arrays[direction_name] = directional[:, :, index]
            exported.append(direction_name)
    return exported


def apply_flow_velocity_output_state(
    arrays: dict[str, np.ndarray],
    fields_obj: Any,
    output_state: str,
) -> list[str]:
    """Replace exported velocity arrays with the requested solver state."""

    if output_state == "post_face_flux":
        return []
    attr = FLOW_VELOCITY_OUTPUT_STATE_FIELDS.get(output_state)
    if attr is None:
        raise ValueError(f"Unsupported Flow_velocity output state: {output_state!r}")
    field = getattr(fields_obj, attr, None)
    if field is None or not hasattr(field, "to_numpy"):
        raise RuntimeError(
            f"Requested Flow_velocity output state {output_state!r}, but field {attr!r} is unavailable."
        )
    converted = _flow_velocity_from_directional_state(field.to_numpy())
    if converted is None:
        raise RuntimeError(
            f"Requested Flow_velocity output state {output_state!r}, but field {attr!r} has unsupported shape."
        )
    directional, scalar = converted
    arrays["Flow_velocity"] = scalar
    replaced = ["Flow_velocity"]
    for index in range(8):
        name = f"Flow_velocity_{index + 1}"
        arrays[name] = directional[:, :, index]
        replaced.append(name)
    return replaced


__all__ = [
    "FLOW_VELOCITY_OUTPUT_STATE_FIELDS",
    "add_velocity_state_diagnostics",
    "apply_flow_velocity_output_state",
    "scalar_fields",
    "velocity_fields",
]
