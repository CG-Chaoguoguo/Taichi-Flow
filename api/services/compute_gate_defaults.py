"""Global compute-gate defaults: EDDA switches, DFS variants, and boundary types."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from api.services.edda_switch_registry import (
    EDDA_SWITCH_BY_KEY,
    EDDA_SWITCH_REGISTRY,
    REGISTRY_VERSION,
    canonical_control_value,
)
from api.services.parameter_catalog import (
    PARAMETER_ENUM_SPECS,
    STATIC_GATE_PARAMETER_KEYS,
    gate_parameter_keys,
    is_gate_parameter_key,
)
from api.services.parameter_templates import (
    BJ_HXL_SWITCH_VALUES,
    canonicalize_edda_control_parameters,
    merge_parameter_values,
)


COMPUTE_GATE_SETTINGS_KEY = "compute_gate_defaults"

VARIANT_AND_POLICY_AUTO_KEYS = frozenset({
    "hydrology.dfs_face_flux_variant",
    "hydrology.dfs_manningbar_variant",
    "hydrology.dfs_dry_face_velocity_variant",
    "hydrology.dfs_artivis_variant",
    "hydrology.dfs_absubar_variant",
    "hydrology.dfs_failure_source_policy",
})

DISPLAY_VARIANT_DEFAULTS: Dict[str, Any] = {
    "hydrology.dfs_face_flux_variant": "both_thin_weighted",
    "hydrology.dfs_manningbar_variant": "exponential_cv",
    "hydrology.dfs_dry_face_velocity_variant": "keep_velocity_bj",
    "hydrology.dfs_artivis_variant": "depth_ratio_bj",
    "hydrology.dfs_absubar_variant": "max_component_bj",
}

STATIC_GATE_DEFAULTS: Dict[str, Any] = {
    **DISPLAY_VARIANT_DEFAULTS,
    "boundary_conditions.mode": "auto",
    "boundary_conditions.default_type": "outflow",
    "boundary_conditions.include_nodata": True,
}

EXPERIMENTAL_GATE_DEFAULTS: Dict[str, Any] = {
    "experimental.enable_live_doublelayer_in_dfs": False,
}

POLICY_KEY = "hydrology.dfs_failure_source_policy"
EXPERIMENTAL_LIVE_KEY = "experimental.enable_live_doublelayer_in_dfs"
FSSIMUL_PATH = "edda.run_controls.simulate_shallow_landslide"

EDITABLE_EDDA_GATE_PATHS = frozenset(
    spec.taichi_config_path
    for spec in EDDA_SWITCH_REGISTRY
    if spec.frontend_policy == "editable"
)


class ComputeGateValidationError(ValueError):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def compute_gate_baseline() -> Dict[str, Any]:
    """Display/template defaults for Settings UI; not injected into Auto keys."""
    values: Dict[str, Any] = dict(STATIC_GATE_DEFAULTS)
    values.update(EXPERIMENTAL_GATE_DEFAULTS)
    values["edda.registry_version"] = REGISTRY_VERSION
    for spec in EDDA_SWITCH_REGISTRY:
        values[spec.taichi_config_path] = deepcopy(BJ_HXL_SWITCH_VALUES[spec.key])
    return canonicalize_edda_control_parameters(values)


def compute_gate_merge_baseline() -> Dict[str, Any]:
    """Keys that may still apply globally when not explicitly overridden."""
    values: Dict[str, Any] = {
        key: value
        for key, value in STATIC_GATE_DEFAULTS.items()
        if key not in VARIANT_AND_POLICY_AUTO_KEYS
    }
    values["edda.registry_version"] = REGISTRY_VERSION
    for spec in EDDA_SWITCH_REGISTRY:
        if spec.taichi_config_path == FSSIMUL_PATH:
            continue
        values[spec.taichi_config_path] = deepcopy(BJ_HXL_SWITCH_VALUES[spec.key])
    return canonicalize_edda_control_parameters(values)


def strip_gate_parameters(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {str(key): value for key, value in dict(values or {}).items() if not is_gate_parameter_key(str(key))}


def extract_gate_parameters(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {str(key): value for key, value in dict(values or {}).items() if is_gate_parameter_key(str(key))}


def merge_compute_gate_defaults(
    baseline: Optional[Mapping[str, Any]],
    patch: Optional[Mapping[str, Any]],
    gates: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Apply explicit global gate overrides, then overlay non-gate scenario patch keys."""
    explicit_gates = extract_gate_parameters(gates)
    merged = merge_parameter_values(dict(baseline or {}), explicit_gates)
    return merge_parameter_values(merged, strip_gate_parameters(patch))


def scenario_gate_overrides(explicit_gates: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Merge baseline for other gates plus sparse user overrides (no Auto-key injection)."""
    return {**compute_gate_merge_baseline(), **extract_gate_parameters(explicit_gates)}


def merge_scenario_compute_parameters(
    baseline: Optional[Mapping[str, Any]],
    patch: Optional[Mapping[str, Any]],
    explicit_gates: Optional[Mapping[str, Any]] = None,
    *,
    template_id: Optional[str] = None,
    strict_reference: bool = False,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Merge scenario parameters and atomically apply the four-state policy."""
    from api.services.compute_policy_resolver import (
        apply_resolved_policy_to_parameters,
        resolve_compute_policy,
    )

    gates = extract_gate_parameters(explicit_gates)
    merged = merge_compute_gate_defaults(baseline, patch, scenario_gate_overrides(gates))
    resolution = resolve_compute_policy(
        dict(baseline or {}),
        global_gates=gates,
        template_id=template_id,
        strict_reference=strict_reference,
    )
    return apply_resolved_policy_to_parameters(merged, resolution), resolution.to_dict()


@dataclass(frozen=True)
class ScenarioComputeSnapshot:
    """Pure, database-free compute policy snapshot for one scenario boundary."""

    effective_parameters: Dict[str, Any]
    resolution: Dict[str, Any]
    validation_issues: list[Dict[str, Any]]

    @property
    def status(self) -> str:
        return str(self.resolution.get("status") or "resolved")


def resolve_scenario_compute_snapshot(
    baseline: Optional[Mapping[str, Any]],
    patch: Optional[Mapping[str, Any]],
    *,
    global_gates: Optional[Mapping[str, Any]] = None,
    template_id: Optional[str] = None,
    template_metadata: Optional[Mapping[str, Any]] = None,
    source_mode: str = "workbench",
    strict_reference: bool = True,
) -> ScenarioComputeSnapshot:
    """Resolve a scenario once from its immutable baseline and sparse inputs.

    This function deliberately has no database, filesystem, provider, or
    solver side effects.  Callers use its result for preview, enqueue
    validation, queue snapshots, and runtime construction.
    """
    from api.services.compute_policy_resolver import (
        ComputePolicyResolutionError,
        VARIANT_PATH,
        apply_resolved_policy_to_parameters,
        compute_policy_resolution_identity,
        resolve_compute_policy,
    )

    gates = extract_gate_parameters(global_gates)
    baseline_values = dict(baseline or {})
    policy_metadata = {}
    if isinstance(template_metadata, Mapping):
        candidate = template_metadata.get("_compute_policy")
        if isinstance(candidate, Mapping):
            policy_metadata = dict(candidate)
    # Keep parser provenance authoritative for the two controls that decide
    # the failure-source topology.  ``normalized_parameter_values`` still
    # canonicalizes missing boolean switches to ``False`` for the legacy
    # 45-switch runtime contract; that representation must not turn an
    # unknown imported ``fssimul`` into a valid Chamoli ``disabled`` result.
    # The resolver needs the raw ``None`` so strict reference imports fail
    # closed, while explicit global overrides remain available.
    if "original_fssimul" in policy_metadata:
        baseline_values[FSSIMUL_PATH] = policy_metadata.get("original_fssimul")
    if VARIANT_PATH not in baseline_values and policy_metadata.get("topology"):
        baseline_values[VARIANT_PATH] = policy_metadata["topology"]

    merged = merge_compute_gate_defaults(
        baseline_values,
        patch,
        scenario_gate_overrides(gates),
    )
    try:
        resolution = resolve_compute_policy(
            baseline_values,
            global_gates=gates,
            template_id=template_id,
            source_mode=source_mode,
            strict_reference=strict_reference,
            detected_evidence=list(policy_metadata.get("evidence") or []),
            topology_status=policy_metadata.get("topology_status"),
        )
    except ComputePolicyResolutionError as exc:
        requested = str(gates.get(POLICY_KEY) or "auto")
        blocked = {
            "status": "blocked",
            "source": "global_override" if requested != "auto" else "auto",
            "requested": requested,
            "detected": {
                "simulate_shallow_landslide": baseline_values.get(FSSIMUL_PATH),
                "dfs_failure_source_variant": baseline_values.get(VARIANT_PATH),
                "topology_status": policy_metadata.get("topology_status"),
                "evidence": list(policy_metadata.get("evidence") or []),
            },
            "effective": {"mode": None, "simulate_shallow_landslide": None, "active_variant": None},
            "numeric_variants": _collect_snapshot_numeric_variants(baseline_values, gates),
            "settings_snapshot": gates,
            "warnings": [],
            "blocking_issue": {
                "code": exc.code,
                "severity": "error",
                "message": exc.message,
                "details": dict(exc.details),
            },
        }
        resolution_id, resolution_hash = compute_policy_resolution_identity(blocked)
        blocked["resolution_id"] = resolution_id
        blocked["resolution_hash"] = resolution_hash
        return ScenarioComputeSnapshot(
            effective_parameters=merged,
            resolution=blocked,
            validation_issues=[blocked["blocking_issue"]],
        )

    return ScenarioComputeSnapshot(
        effective_parameters=apply_resolved_policy_to_parameters(merged, resolution),
        resolution=resolution.to_dict(),
        validation_issues=[],
    )


def _collect_snapshot_numeric_variants(
    baseline: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        key: {
            "source": "global_override" if key in gates else ("scenario_baseline" if key in baseline else "missing"),
            "value": gates[key] if key in gates else baseline.get(key),
        }
        for key in VARIANT_AND_POLICY_AUTO_KEYS
        if key != POLICY_KEY
    }


def editable_gate_parameter_keys() -> set[str]:
    keys = set(STATIC_GATE_PARAMETER_KEYS)
    keys.update(EDITABLE_EDDA_GATE_PATHS)
    return keys


def validate_compute_gate_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a cleaned gate override map, or raise ComputeGateValidationError."""
    payload = dict(values or {})
    allowed = editable_gate_parameter_keys()
    unknown = sorted(key for key in payload if key not in gate_parameter_keys())
    if unknown:
        raise ComputeGateValidationError(
            "parameter_not_editable",
            "设置中包含未知的计算门禁键。",
            {"keys": unknown},
        )
    restricted = sorted(key for key in payload if is_gate_parameter_key(key) and key not in allowed)
    if restricted:
        raise ComputeGateValidationError(
            "parameter_not_editable",
            "受限计算门禁不能从设置页写入。",
            {"keys": restricted},
        )

    cleaned: Dict[str, Any] = {}
    for key, value in payload.items():
        if key == POLICY_KEY and str(value).strip().lower() == "auto":
            continue
        if key == "edda.registry_version":
            text = str(value)
            if text != REGISTRY_VERSION:
                raise ComputeGateValidationError(
                    "parameter_enum_invalid",
                    f"计算门禁登记版本必须为 {REGISTRY_VERSION}。",
                    {"key": key, "value": value},
                )
            cleaned[key] = text
            continue
        if key in EDITABLE_EDDA_GATE_PATHS:
            control_key = key.rsplit(".", 1)[-1]
            switch = EDDA_SWITCH_BY_KEY[control_key]
            cleaned[key] = canonical_control_value(switch, value)
            continue
        enum_spec = PARAMETER_ENUM_SPECS.get(key)
        if enum_spec and enum_spec.get("value_type") == "enum":
            allowed_values = [str(item) for item in enum_spec.get("allowed_values") or []]
            text = str(value)
            if text not in allowed_values:
                raise ComputeGateValidationError(
                    "parameter_enum_invalid",
                    f"参数 {key} 取值无效：{value!r}；允许值：{', '.join(allowed_values)}。",
                    {"key": key, "value": value, "allowed_values": allowed_values},
                )
            cleaned[key] = text
            continue
        if enum_spec and enum_spec.get("value_type") == "boolean":
            if not isinstance(value, bool):
                raise ComputeGateValidationError(
                    "parameter_enum_invalid",
                    f"参数 {key} 必须为布尔值。",
                    {"key": key, "value": value},
                )
            cleaned[key] = value
            continue
        cleaned[key] = value
    if cleaned.get(POLICY_KEY) == "live" and not bool(cleaned.get(EXPERIMENTAL_LIVE_KEY)):
        raise ComputeGateValidationError(
            "live_policy_locked",
            "实时双层为实验模式，请先开启 experimental.enable_live_doublelayer_in_dfs。",
            {"key": POLICY_KEY, "value": "live"},
        )
    if POLICY_KEY in cleaned and cleaned[POLICY_KEY] == "live" and EXPERIMENTAL_LIVE_KEY in cleaned and cleaned[EXPERIMENTAL_LIVE_KEY] is False:
        raise ComputeGateValidationError(
            "live_unlock_required",
            "当前策略为实时双层时不能关闭实验解锁，请先切换失稳源策略。",
            {"key": EXPERIMENTAL_LIVE_KEY},
        )
    return cleaned
