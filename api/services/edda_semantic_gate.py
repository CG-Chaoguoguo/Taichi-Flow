"""Fail-closed admission policy for requests that declare original EDDA controls."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional

from api.services.edda_switch_registry import (
    EDDA_SWITCH_REGISTRY,
    REGISTRY_VERSION,
)
from edda.config.edda_runtime_plan import EddaRuntimeControlPlan


@dataclass
class SemanticGateViolation(ValueError):
    code: str
    message: str
    details: dict[str, Any]

    def __str__(self) -> str:
        return self.message


def _raise(code: str, message: str, **details: Any) -> None:
    raise SemanticGateViolation(code=code, message=message, details=details)


def _validate_snapshot_shape(plan: EddaRuntimeControlPlan) -> None:
    if plan.registry_version != REGISTRY_VERSION:
        _raise(
            "edda_registry_version_mismatch",
            f"EDDA registry version {plan.registry_version!r} does not match runtime {REGISTRY_VERSION!r}.",
            configured_version=plan.registry_version,
            runtime_version=REGISTRY_VERSION,
        )


def _validate_snapshot_values(plan: EddaRuntimeControlPlan) -> None:
    specs = {spec.key: spec for spec in EDDA_SWITCH_REGISTRY}
    expected_run = {
        spec.key for spec in EDDA_SWITCH_REGISTRY if spec.group == "run_control"
    }
    expected_output = {
        spec.key
        for spec in EDDA_SWITCH_REGISTRY
        if spec.group in {"legacy_output", "process_output"}
    }
    missing_run = sorted(expected_run - set(plan.run_controls))
    missing_output = sorted(expected_output - set(plan.output_controls))
    extra_run = sorted(set(plan.run_controls) - expected_run)
    extra_output = sorted(set(plan.output_controls) - expected_output)
    if missing_run or missing_output or extra_run or extra_output:
        _raise(
            "edda_control_snapshot_incomplete",
            "Strict EDDA control snapshot must match the canonical 45-switch registry exactly.",
            missing_run_controls=missing_run,
            missing_output_controls=missing_output,
            unknown_run_controls=extra_run,
            unknown_output_controls=extra_output,
        )

    values = {**plan.run_controls, **plan.output_controls}
    for key, value in values.items():
        spec = specs[key]
        if spec.value_type == "boolean":
            type_valid = type(value) is bool
        elif spec.value_type == "integer":
            type_valid = type(value) is int
        elif spec.value_type == "number_array":
            type_valid = isinstance(value, (list, tuple)) and all(
                type(item) in {int, float} for item in value
            )
        elif spec.value_type == "enum":
            type_valid = isinstance(value, str)
        else:
            type_valid = False
        allowed_valid = not spec.allowed_values or value in spec.allowed_values
        if not type_valid or not allowed_valid:
            _raise(
                "edda_control_value_invalid",
                f"Strict EDDA control {key!r} violates the canonical {spec.value_type} contract.",
                control=key,
                configured_value=value,
                expected_type=spec.value_type,
                allowed_values=list(spec.allowed_values),
            )


def validate_runtime_control_plan(
    plan: EddaRuntimeControlPlan,
    *,
    runtime_input_manifest: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Validate static admission and, when supplied, runtime-source readiness."""
    if not plan.strict:
        return {
            "strict": False,
            "decision": "allow_direct_api_compatibility",
            "source_mode": plan.source_mode,
        }

    _validate_snapshot_shape(plan)
    _validate_snapshot_values(plan)

    if not plan.run_enabled("simulate_debris_flow"):
        _raise(
            "edda_wfs_unsupported",
            "simulate_debris_flow=false selects original WFS, which is not implemented.",
            control="simulate_debris_flow",
            configured_value=False,
            required_action="Provide a validated WFS implementation and paired original oracle.",
        )
    if plan.run_enabled("simulate_drainage_flow"):
        _raise(
            "edda_drainage_unsupported",
            "Original drainage-flow semantics are not production-qualified.",
            control="simulate_drainage_flow",
            configured_value=True,
        )
    if plan.run_enabled("simulate_barrier"):
        _raise(
            "edda_barrier_unsupported",
            "Original barrier semantics are not implemented end to end.",
            control="simulate_barrier",
            configured_value=True,
        )
    if plan.output_value("pressure_head_fs_listing_flag") == -2:
        _raise(
            "edda_detailed_unsfin_listing_unsupported",
            "pressure_head_fs_listing_flag=-2 requires the original detailed six-column UNSFIN listing.",
            control="pressure_head_fs_listing_flag",
            configured_value=-2,
        )

    if runtime_input_manifest is not None and plan.run_enabled("simulate_outflow_cell"):
        outflow_entry = next(
            (
                item
                for item in runtime_input_manifest.get("inputs", [])
                if item.get("family") == "outflow.txt"
            ),
            None,
        )
        structure = (outflow_entry or {}).get("structure_summary") or {}
        configured_count = int(structure.get("configured_cell_count") or 0)
        if not outflow_entry or not bool(outflow_entry.get("consumed")) or configured_count <= 0:
            _raise(
                "edda_outflow_sidecar_required",
                "simulate_outflow_cell=true requires outflow.txt to be configured into the dedicated DFS mask.",
                control="simulate_outflow_cell",
                configured_value=True,
                path=(outflow_entry or {}).get("path"),
                consumed=bool((outflow_entry or {}).get("consumed")),
                configured_cell_count=configured_count,
            )

    if runtime_input_manifest is not None and plan.run_enabled("simulate_shallow_landslide"):
        failure_source = (
            runtime_input_manifest.get("input_source_registry", {})
            .get("dfs_failure_source_variant", {})
        )
        if not bool(failure_source.get("runtime_active")):
            _raise(
                "edda_unsfin_schedule_required",
                "simulate_shallow_landslide=true requires a validated UNSFIN schedule configured into DFS.",
                control="simulate_shallow_landslide",
                configured_value=True,
                selected_source=failure_source.get("selected_source"),
                blocked_reason=failure_source.get("blocked_reason"),
            )

    return {
        "strict": True,
        "decision": "allow_supported_edda_semantics",
        "source_mode": plan.source_mode,
        "registry_version": plan.registry_version,
    }


def validate_flat_edda_controls(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the same gate to the workbench's path-free dotted contract."""
    registry_version = parameters.get("edda.registry_version")
    run_prefix = "edda.run_controls."
    output_prefix = "edda.output_controls."
    extension_prefix = "edda.extension_controls."
    run_controls = {
        str(key)[len(run_prefix):]: value
        for key, value in parameters.items()
        if str(key).startswith(run_prefix)
    }
    output_controls = {
        str(key)[len(output_prefix):]: value
        for key, value in parameters.items()
        if str(key).startswith(output_prefix)
    }
    extension_controls = {
        str(key)[len(extension_prefix):]: value
        for key, value in parameters.items()
        if str(key).startswith(extension_prefix)
    }
    if registry_version is None and not (run_controls or output_controls or extension_controls):
        return {
            "strict": False,
            "decision": "allow_direct_api_compatibility",
            "source_mode": "workbench_control_free_compatibility",
        }
    plan = EddaRuntimeControlPlan(
        registry_version=str(registry_version or ""),
        source_mode="workbench_reference_import",
        strict=True,
        run_controls=MappingProxyType(run_controls),
        output_controls=MappingProxyType(output_controls),
        extension_controls=MappingProxyType(extension_controls),
    )
    return validate_runtime_control_plan(plan)
