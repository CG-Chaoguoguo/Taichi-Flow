"""Unified four-state failure-source policy resolution for compute gates."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from api.services.edda_switch_registry import EDDA_SWITCH_BY_KEY, canonical_control_value

POLICY_KEY = "hydrology.dfs_failure_source_policy"
EXPERIMENTAL_LIVE_KEY = "experimental.enable_live_doublelayer_in_dfs"
FSSIMUL_PATH = "edda.run_controls.simulate_shallow_landslide"
VARIANT_PATH = "hydrology.dfs_failure_source_variant"

POLICY_VALUES = frozenset({"auto", "disabled", "precomputed", "live"})
TOPOLOGY_PRECOMPUTED = "precomputed_unsfin_schedule"
TOPOLOGY_LIVE = "live_doublelayer_in_dfs"
RECOGNIZED_TOPOLOGIES = frozenset({TOPOLOGY_PRECOMPUTED, TOPOLOGY_LIVE})

VARIANT_GATE_KEYS = (
    "hydrology.dfs_face_flux_variant",
    "hydrology.dfs_manningbar_variant",
    "hydrology.dfs_dry_face_velocity_variant",
    "hydrology.dfs_artivis_variant",
    "hydrology.dfs_absubar_variant",
)

class ComputePolicyResolutionError(ValueError):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class ResolvedComputePolicy:
    status: str
    source: str
    requested: str
    detected: Dict[str, Any]
    effective: Dict[str, Any]
    numeric_variants: Dict[str, Any]
    settings_snapshot: Dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "status": self.status,
            "source": self.source,
            "requested": self.requested,
            "detected": self.detected,
            "effective": self.effective,
            "numeric_variants": self.numeric_variants,
            "settings_snapshot": deepcopy(self.settings_snapshot),
            "warnings": list(self.warnings),
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        payload["resolution_hash"] = digest
        payload["resolution_id"] = f"cpr-{digest[:16]}"
        return payload


def compute_policy_resolution_identity(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Return the stable id/hash shared by queue, run, and runtime manifests."""
    canonical = {
        str(key): value
        for key, value in dict(payload).items()
        if key not in {"resolution_id", "resolution_hash"}
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"cpr-{digest[:16]}", digest


def legacy_unrecorded_compute_policy_resolution() -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "legacy_unrecorded",
        "source": "legacy_unrecorded",
        "requested": "auto",
        "detected": {
            "simulate_shallow_landslide": None,
            "dfs_failure_source_variant": None,
            "topology_status": "unknown",
            "evidence": [],
        },
        "effective": {"mode": None, "simulate_shallow_landslide": None, "active_variant": None},
        "numeric_variants": {},
        "settings_snapshot": {},
        "warnings": ["该历史运行没有冻结的失稳源策略记录。"],
    }
    resolution_id, resolution_hash = compute_policy_resolution_identity(payload)
    payload["resolution_id"] = resolution_id
    payload["resolution_hash"] = resolution_hash
    return payload


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"t", "true", "1", "yes", "on"}:
        return True
    if text in {"f", "false", "0", "no", "off"}:
        return False
    return None


def _read_topology(parameters: Mapping[str, Any]) -> Optional[str]:
    value = parameters.get(VARIANT_PATH)
    if value is None:
        return None
    text = str(value).strip()
    if text in RECOGNIZED_TOPOLOGIES:
        return text
    if not text or text in {"unknown", "conflict", "missing_source"}:
        return None
    return None


def _auto_effective_mode(
    simulate_shallow_landslide: Optional[bool],
    topology: Optional[str],
) -> Optional[str]:
    if simulate_shallow_landslide is False:
        return "disabled"
    if simulate_shallow_landslide is True:
        if topology == TOPOLOGY_PRECOMPUTED:
            return "precomputed"
        if topology == TOPOLOGY_LIVE:
            return "live"
    return None


def _requested_policy(global_gates: Mapping[str, Any]) -> tuple[str, str]:
    raw = global_gates.get(POLICY_KEY)
    if raw is None:
        return "auto", "auto"
    text = str(raw).strip().lower()
    if text not in POLICY_VALUES or text == "auto":
        return "auto", "auto"
    return "global_override", text


def _collect_numeric_variants(
    parameters: Mapping[str, Any],
    global_gates: Mapping[str, Any],
) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    for key in VARIANT_GATE_KEYS:
        if key in global_gates:
            resolved[key] = {"source": "global_override", "value": global_gates[key]}
        elif key in parameters:
            resolved[key] = {"source": "case_baseline", "value": parameters[key]}
        else:
            resolved[key] = {"source": "missing", "value": None}
    return resolved


def resolve_compute_policy(
    parameters: Mapping[str, Any],
    *,
    global_gates: Optional[Mapping[str, Any]] = None,
    strict_reference: bool = False,
    source_mode: str = "reference_config",
    template_id: Optional[str] = None,
    detected_evidence: Optional[list[dict[str, Any]]] = None,
    topology_status: Optional[str] = None,
) -> ResolvedComputePolicy:
    gates = dict(global_gates or {})
    policy_source, requested = _requested_policy(gates)
    if policy_source == "auto" and source_mode == "direct_api":
        policy_source = "direct_api_compatibility"
    detected_fssimul = _coerce_bool(parameters.get(FSSIMUL_PATH))
    detected_topology = _read_topology(parameters)
    if str(topology_status or "").lower() in {"unknown", "conflict", "missing_source"}:
        detected_topology = None
    evidence = list(detected_evidence or [])
    warnings: list[str] = []

    # Strictness is an input-boundary decision.  Production reference and
    # workbench callers must opt in explicitly; direct/unit callers retain
    # the compatibility fallback unless they provide strict_reference=True.
    strict = bool(strict_reference)

    if requested == "auto":
        effective_mode = _auto_effective_mode(detected_fssimul, detected_topology)
        if effective_mode is None:
            if detected_fssimul is True and detected_topology is None:
                message = (
                    "simulate_shallow_landslide=true but bundled failure-source topology "
                    "evidence is missing or conflicting."
                )
                warnings.append(message)
                if strict and source_mode != "direct_api":
                    raise ComputePolicyResolutionError(
                        "failure_source_topology_unknown",
                        message,
                        {
                            "simulate_shallow_landslide": True,
                            "dfs_failure_source_variant": None,
                            "template_id": template_id,
                        },
                    )
            if detected_fssimul is None and strict and source_mode != "direct_api":
                raise ComputePolicyResolutionError(
                    "failure_source_control_unknown",
                    "simulate_shallow_landslide could not be established from the imported reference configuration.",
                    {
                        "simulate_shallow_landslide": None,
                        "dfs_failure_source_variant": detected_topology,
                        "template_id": template_id,
                    },
                )
            if detected_fssimul is False:
                effective_mode = "disabled"
            elif source_mode == "direct_api":
                effective_mode = "live"
            else:
                effective_mode = None
    elif requested == "disabled":
        effective_mode = "disabled"
    elif requested == "precomputed":
        effective_mode = "precomputed"
    elif requested == "live":
        effective_mode = "live"
    else:
        effective_mode = "disabled"

    live_unlocked = bool(gates.get(EXPERIMENTAL_LIVE_KEY))
    if (
        source_mode == "direct_api"
        and requested == "auto"
        and effective_mode == "live"
        and (detected_fssimul is None or detected_topology is None)
    ):
        warnings.append(
            "Direct API compatibility fallback selected the live failure-source path because reference Fortran topology was not supplied."
        )
    if effective_mode == "live" and source_mode != "direct_api" and not live_unlocked:
        raise ComputePolicyResolutionError(
            "live_policy_locked",
            "实时双层为实验模式，请先开启 experimental.enable_live_doublelayer_in_dfs。",
            {
                "key": POLICY_KEY,
                "requested": requested,
                "detected_topology": detected_topology,
            },
        )

    if requested == "precomputed" and detected_fssimul is False:
        warnings.append("Counterfactual override: case fssimul=false but policy selected precomputed.")
    if requested == "disabled" and detected_fssimul is True:
        warnings.append("Counterfactual override: case fssimul=true but policy disabled the failure-source ledger.")
    if requested == "live":
        warnings.append("Experimental live double-layer path; not an original Chamoli or BJ compile path.")

    if effective_mode == "precomputed":
        active_variant = TOPOLOGY_PRECOMPUTED
    elif effective_mode == "live":
        active_variant = TOPOLOGY_LIVE
    else:
        active_variant = None

    detected_payload = {
        "simulate_shallow_landslide": detected_fssimul,
        "dfs_failure_source_variant": detected_topology,
        "topology_status": topology_status or ("recognized" if detected_topology else "unknown"),
        "evidence": evidence,
    }
    return ResolvedComputePolicy(
        status="resolved",
        source=policy_source,
        requested=requested,
        detected=detected_payload,
        effective={
            "mode": effective_mode,
            "simulate_shallow_landslide": effective_mode != "disabled",
            "configured_variant": detected_topology,
            "active_variant": active_variant,
        },
        numeric_variants=_collect_numeric_variants(parameters, gates),
        settings_snapshot=gates,
        warnings=warnings,
    )


def apply_resolved_policy_to_parameters(
    parameters: Mapping[str, Any],
    resolution: ResolvedComputePolicy | Mapping[str, Any],
) -> Dict[str, Any]:
    payload = resolution if isinstance(resolution, Mapping) else resolution.to_dict()
    effective = payload.get("effective") or {}
    merged = deepcopy(dict(parameters))
    control_enabled = bool(effective.get("simulate_shallow_landslide"))
    switch = EDDA_SWITCH_BY_KEY["simulate_shallow_landslide"]
    merged[FSSIMUL_PATH] = canonical_control_value(switch, control_enabled)
    active_variant = effective.get("active_variant")
    configured_variant = effective.get("configured_variant")
    if active_variant:
        merged[VARIANT_PATH] = str(active_variant)
    elif configured_variant:
        merged[VARIANT_PATH] = str(configured_variant)
    return merged


def annotate_failure_source_registry(
    registry_entry: Dict[str, Any],
    resolution: ResolvedComputePolicy | Mapping[str, Any],
) -> Dict[str, Any]:
    payload = resolution if isinstance(resolution, Mapping) else resolution.to_dict()
    effective = payload.get("effective") or {}
    mode = str(effective.get("mode") or "disabled")
    updated = dict(registry_entry)
    detected_variant = (payload.get("detected") or {}).get("dfs_failure_source_variant")
    updated.update(
        {
            "requested_policy": payload.get("requested"),
            "policy_source": payload.get("source"),
            "detected_variant": detected_variant,
            "effective_mode": mode,
            "control_enabled": bool(effective.get("simulate_shallow_landslide")),
        }
    )
    if mode == "disabled":
        updated.update(
            {
                "selected_source": "disabled",
                "schedule_provider": "skipped_fssimul_off",
                "runtime_active": False,
                "runtime_equivalent_implemented": False,
                "blocked_reason": None,
                "skip_reason": "control_off",
            }
        )
        return updated
    updated["skip_reason"] = None
    if mode == "live":
        updated.update(
            {
                "selected_source": TOPOLOGY_LIVE,
                "schedule_provider": "none",
                "runtime_active": True,
                "runtime_equivalent_implemented": True,
                "blocked_reason": None,
            }
        )
        return updated
    updated["selected_source"] = TOPOLOGY_PRECOMPUTED
    updated.setdefault("schedule_provider", "none")
    return updated


def should_attempt_native_unsfin_provider(
    resolution: ResolvedComputePolicy | Mapping[str, Any],
    *,
    force_native_provider_generation: bool = False,
) -> bool:
    payload = resolution if isinstance(resolution, Mapping) else resolution.to_dict()
    effective = payload.get("effective") or {}
    if str(effective.get("mode") or "disabled") != "precomputed":
        return False
    if not bool(effective.get("simulate_shallow_landslide")):
        return False
    return True


def resolution_from_parsed(
    parsed: Any,
    *,
    global_gates: Optional[Mapping[str, Any]] = None,
    config_overrides: Optional[Mapping[str, Any]] = None,
    strict_reference: bool = False,
    source_mode: str = "reference_config",
    template_id: Optional[str] = None,
) -> ResolvedComputePolicy:
    flags = getattr(parsed, "flags", {}) or {}
    topology = getattr(parsed, "dfs_failure_source_variant", None)
    topology_status = str(getattr(parsed, "dfs_failure_source_topology_status", "") or "")
    if topology_status in {"unknown", "conflict", "missing_source"}:
        topology = None
    parameters = {
        FSSIMUL_PATH: flags.get("simulate_shallow_landslide"),
        VARIANT_PATH: topology,
    }
    hydrology = {}
    if isinstance(config_overrides, Mapping):
        hydrology = config_overrides.get("hydrology") if isinstance(config_overrides.get("hydrology"), Mapping) else {}
        if VARIANT_PATH in config_overrides and _read_topology({VARIANT_PATH: config_overrides[VARIANT_PATH]}):
            parameters[VARIANT_PATH] = config_overrides[VARIANT_PATH]
        nested_variant = hydrology.get("dfs_failure_source_variant") if hydrology else None
        if _read_topology({VARIANT_PATH: nested_variant}):
            parameters[VARIANT_PATH] = nested_variant
    gates = dict(global_gates or {})
    if not gates and isinstance(config_overrides, Mapping):
        nested_policy = hydrology.get("dfs_failure_source_policy") if hydrology else None
        if config_overrides.get(POLICY_KEY) is not None:
            gates[POLICY_KEY] = config_overrides[POLICY_KEY]
        elif nested_policy is not None:
            gates[POLICY_KEY] = nested_policy
        experimental = config_overrides.get(EXPERIMENTAL_LIVE_KEY)
        if experimental is None and isinstance(config_overrides.get("experimental"), Mapping):
            experimental = config_overrides["experimental"].get("enable_live_doublelayer_in_dfs")
        if experimental is not None:
            gates[EXPERIMENTAL_LIVE_KEY] = experimental
    evidence = list(getattr(parsed, "dfs_failure_source_evidence", None) or [])
    return resolve_compute_policy(
        parameters,
        global_gates=gates,
        strict_reference=strict_reference,
        source_mode=source_mode,
        template_id=template_id,
        detected_evidence=evidence,
        topology_status=topology_status,
    )
