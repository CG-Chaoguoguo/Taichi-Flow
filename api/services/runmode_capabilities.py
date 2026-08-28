"""Registry-derived backend capability view for service/runtime audit payloads.

The 45 original EDDA switches have exactly one truth source:
``EDDA_SWITCH_REGISTRY``.  This module adds only non-switch input, sidecar, and
parameter capabilities; it never restates switch status or exposure policy.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional

from api.services.edda_switch_registry import (
    EDDA_SWITCH_REGISTRY,
    REGISTRY_VERSION,
    EddaSwitchSpec,
)
from edda.config.sim_config import SimulationConfig


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_capability_key(spec: EddaSwitchSpec) -> str:
    if spec.key == "background_flux_offset":
        return "hydrology.use_background_flux_offset"
    prefix = "flags" if spec.group == "run_control" else "output_flags"
    return f"{prefix}.{spec.key}"


def _canonical_capability(spec: EddaSwitchSpec) -> Dict[str, Any]:
    supported = spec.status in {"production_consumed", "config_fallback_consumed"}
    return {
        "key": _canonical_capability_key(spec),
        "raw_label": f"{spec.original_variable} / {spec.key}",
        "family": "run_mode" if spec.group == "run_control" else "output_flag",
        "original_true_switch": "yes",
        "current_backend_status": spec.status,
        "frontend_exposure_policy": spec.frontend_policy,
        "blocked_reason": None if supported else spec.status_reason,
        "evidence_basis": (
            f"{spec.fortran_runtime_consumer}; current: {spec.taichi_runtime_consumer}; "
            f"evidence: {spec.test_or_audit_artifact}"
        ),
        "canonical_switch_key": spec.key,
        "canonical_source_index": spec.source_index,
        "canonical_group": spec.group,
        "canonical_registry_version": REGISTRY_VERSION,
        "value_type": spec.value_type,
        "allowed_values": list(spec.allowed_values),
        "original_semantics": spec.original_semantics,
        "consumption_stage": spec.consumption_stage,
        "dependencies": list(spec.dependencies),
        "affected_output_families": list(spec.affected_output_families),
    }


def _auxiliary_capability(
    key: str,
    raw_label: str,
    family: str,
    status: str,
    policy: str,
    reason: Optional[str],
    evidence: str,
    *,
    original_true_switch: str = "no",
) -> Dict[str, Any]:
    return {
        "key": key,
        "raw_label": raw_label,
        "family": family,
        "original_true_switch": original_true_switch,
        "current_backend_status": status,
        "frontend_exposure_policy": policy,
        "blocked_reason": reason,
        "evidence_basis": evidence,
        "canonical_switch_key": None,
    }


_AUXILIARY_CAPABILITIES = (
    _auxiliary_capability(
        "rainfall.source_family", "cri/capt/rifil rainfall source family", "input_family",
        "production_consumed", "derived_from_inputs", None,
        "Parser, mapper, and runtime preserve each period's uniform-vs-raster source selection.",
    ),
    _auxiliary_capability(
        "manning.source_family", "manningfil/global manning source family", "input_family",
        "production_consumed", "derived_from_inputs", None,
        "Runtime selects raster Manning when active and otherwise consumes the scalar fallback.",
    ),
    _auxiliary_capability(
        "native_inputs.demfil", "demfil", "input_family", "production_consumed",
        "importable_auditable", None, "Formal production DEM input.",
    ),
    _auxiliary_capability(
        "native_inputs.slofil", "slofil", "input_family", "production_consumed",
        "importable_auditable", None, "Production native slope-grid loader.",
    ),
    _auxiliary_capability(
        "native_inputs.triggerslide", "triggerslide / triggerslidefil", "input_family",
        "production_consumed", "importable_auditable", None,
        "Original triggering-slide grid is always read and injected once in dfs.F90 when tnow>0.",
    ),
    _auxiliary_capability(
        "native_inputs.zonfil", "zonfil", "input_family", "production_consumed",
        "importable_auditable", None,
        "Zone raster is consumed only when nzon>1; nzon=1 uses the uniform zone-1 branch.",
    ),
    _auxiliary_capability(
        "native_inputs.dirfil", "dirfil", "input_family", "parsed_only", "read_only",
        "Current connectivity is DEM-derived and does not consume the original direction grid.",
        "Retained for provenance only.",
    ),
    _auxiliary_capability(
        "native_inputs.zfil", "zfil", "input_family", "partial", "read_only",
        "The ltstar<0 branch is production-reachable; the separate zmax<0 role is not closed.",
        "Dual-role input family remains partial.",
    ),
    _auxiliary_capability(
        "native_inputs.depfil", "depfil", "input_family", "partial", "read_only",
        "Only the original depth<0 initialization branch is closed.",
        "Scalar fallback and per-cell initialization are production-reachable.",
    ),
    _auxiliary_capability(
        "native_inputs.rizerofil", "rizerofil", "input_family", "partial", "read_only",
        "Only the original rizero<0 initialization branch is closed.",
        "Scalar fallback and per-cell initialization are production-reachable.",
    ),
    _auxiliary_capability(
        "sidecar.outflow.txt", "outflow.txt", "sidecar", "partial", "read_only",
        "The dedicated mask/order/export chain is implemented; exact active numerical oracle parity is pending.",
        "Generic boundary metadata is isolated from accepted pre-clear sidecar sampling.",
    ),
    _auxiliary_capability(
        "sidecar.hydrograph.txt", "hydrograph.txt", "sidecar", "partial", "read_only",
        "Only source-backed monitored-output coverage is qualified.",
        "Hydrograph remains monitored output and is not inflow forcing.",
    ),
    _auxiliary_capability(
        "sidecar.inflow.txt", "inflow.txt", "sidecar", "partial", "read_only",
        "DFS forcing is implemented; complete original report parity remains open.",
        "Active hydrographs reach DFS staging and volume accounting.",
    ),
    _auxiliary_capability(
        "sidecar.EDDALog.txt", "EDDALog.txt", "sidecar", "metadata_only", "read_only",
        "Structured JSON audit data is not original EDDALog text/process parity.",
        "Do not synthesize an original log file.",
    ),
    _auxiliary_capability(
        "output_flags.save_hydrograph_cells", "Save hydrograph of specified cells?",
        "output_extension", "partial", "read_only",
        "Non-zero active original/Taichi oracle coverage remains pending.",
        "Extension control gates monitored-cell HYDROGRAPH output.", original_true_switch="yes",
    ),
    _auxiliary_capability(
        "rheology.shallown", "shallown", "parameter", "parsed_only", "read_only",
        "The active WFS consumer is unavailable.", "Retain provenance until WFS is implemented.",
    ),
    _auxiliary_capability(
        "rheology.debrisflowmanning", "debrisflowmanning", "parameter",
        "production_consumed", "editable", None,
        "Chamoli dfs.F90 uses debrisflowmanning when cv>cvtol in the erosion-rate Manning-bar branch.",
    ),
    _auxiliary_capability(
        "rheology.cvlandslide", "cvlandslide", "parameter",
        "production_consumed", "editable", None,
        "Original dfs.F90:561 uses cvlandslide as the triggering-slide mixture concentration.",
    ),
    _auxiliary_capability(
        "rheology.cvglacier", "cvglacier", "parameter", "parsed_only", "read_only",
        "Chamoli dfs.F90 rhoero=cvglacier assignment is commented out.",
        "Parsed for provenance only.",
    ),
    _auxiliary_capability(
        "extension_flags.simulate_buildings", "buildingsimul", "run_mode",
        "parsed_only", "read_only",
        "Original dfs.F90:58 ARF/WRF branch is not wired end to end.",
        "Chamoli-only extension flag; not part of the 45-switch BJ_HXL registry.",
        original_true_switch="yes",
    ),
    _auxiliary_capability(
        "time.wavemax", "wavemax", "parameter", "parsed_only", "read_only",
        "No active production consumer is qualified.", "Original visible stability block is inactive.",
    ),
    _auxiliary_capability(
        "soil.double_layer.uww", "uww (double-layer branch)", "parameter",
        "production_consumed", "read_only", None,
        "Parsed uww is consumed by the current double-layer runtime.",
    ),
    _auxiliary_capability(
        "native_inputs.zmax", "zmax", "parameter", "parsed_only", "read_only",
        "No canonical runtime consumer is closed.", "Retain parsed provenance only.",
    ),
    _auxiliary_capability(
        "soil.porosity", "porosity", "parameter", "parsed_only", "read_only",
        "Zone-row porosity is not mapped into a production field.", "Parsed but not consumed.",
    ),
    _auxiliary_capability(
        "soil.zone_stddev_family", "zone stddev family", "parameter", "unsupported", "read_only",
        "No parser/model/runtime support exists.", "Keep fail-closed.",
    ),
)


RUNMODE_CAPABILITIES = tuple(
    [_canonical_capability(spec) for spec in EDDA_SWITCH_REGISTRY]
    + [deepcopy(entry) for entry in _AUXILIARY_CAPABILITIES]
)


def _infer_source_trace_status(entry: Dict[str, Any]) -> str:
    if entry.get("canonical_switch_key") is not None:
        if entry.get("original_semantics") == "no_op_candidate":
            return "missing_active_consumer"
        status = entry.get("current_backend_status")
        if status in {"production_consumed", "config_fallback_consumed"}:
            return "anchored"
        if status == "partial":
            return "anchored_partial"
        if status == "metadata_only":
            return "metadata_only"
        return "missing_runtime_consumer"
    if entry.get("key") == "native_inputs.zfil":
        return "dual_role_partial"
    status = entry.get("current_backend_status")
    if status in {"parsed_only", "mapped_only", "unsupported", "blocked"}:
        return "missing_runtime_consumer"
    return "anchored"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _configured_value(
    entry: Dict[str, Any],
    config: Optional[SimulationConfig],
    reference_audit: Optional[Dict[str, Any]],
    parameter_audit: Optional[Dict[str, Any]],
) -> Any:
    key = entry["key"]
    canonical_key = entry.get("canonical_switch_key")
    flags = (reference_audit or {}).get("flags") or {}
    if canonical_key is not None:
        if config is not None:
            group = entry.get("canonical_group")
            controls = (
                config.edda.run_controls
                if group == "run_control"
                else config.edda.output_controls
            )
            if canonical_key in controls:
                return controls[canonical_key]
            if canonical_key == "background_flux_offset":
                return config.hydrology.use_background_flux_offset
        if canonical_key in flags:
            return flags[canonical_key]
        return None
    if key == "output_flags.save_hydrograph_cells":
        return flags.get("save_hydrograph_cells")
    parameters = {
        item.get("parameter"): item
        for item in (parameter_audit or {}).get("parameters", [])
        if isinstance(item, dict) and item.get("parameter")
    }
    if key in parameters:
        return (parameters[key].get("evidence") or {}).get("configured_value")
    if key == "native_inputs.zmax":
        return (reference_audit or {}).get("zmax")
    return None


def build_runmode_capabilities(
    config: Optional[SimulationConfig] = None,
    reference_audit: Optional[Dict[str, Any]] = None,
    parameter_audit: Optional[Dict[str, Any]] = None,
    source_mode: Optional[str] = None,
) -> Dict[str, Any]:
    capabilities = deepcopy(list(RUNMODE_CAPABILITIES))
    parsed_flag_closure = (reference_audit or {}).get("flag_closure") or []
    for entry in capabilities:
        entry["configured_value"] = _configured_value(
            entry, config, reference_audit, parameter_audit
        )
        entry["source_trace_status"] = _infer_source_trace_status(entry)

    status_summary: Dict[str, int] = {}
    exposure_summary: Dict[str, int] = {}
    for entry in capabilities:
        status = entry["current_backend_status"]
        exposure = entry["frontend_exposure_policy"]
        status_summary[status] = status_summary.get(status, 0) + 1
        exposure_summary[exposure] = exposure_summary.get(exposure, 0) + 1

    editable_run_modes = [
        entry["key"]
        for entry in capabilities
        if entry.get("canonical_group") == "run_control"
        and entry["frontend_exposure_policy"] == "editable"
    ]
    editable_output_keys = [
        entry["key"]
        for entry in capabilities
        if entry.get("canonical_group") in {"legacy_output", "process_output"}
        and entry["frontend_exposure_policy"] == "editable"
    ]
    return {
        "generated_at": _timestamp(),
        "source_mode": source_mode,
        "canonical_registry_version": REGISTRY_VERSION,
        "capabilities": capabilities,
        "parsed_flag_closure": parsed_flag_closure,
        "summary": {
            "count": len(capabilities),
            "canonical_switch_count": len(EDDA_SWITCH_REGISTRY),
            "auxiliary_capability_count": len(_AUXILIARY_CAPABILITIES),
            "status_summary": status_summary,
            "frontend_exposure_summary": exposure_summary,
            # Backward-compatible service-info key; now registry-derived.
            "switchable_keys": editable_run_modes,
            "editable_output_keys": editable_output_keys,
        },
    }


def write_runmode_capabilities_file(
    output_dir: Path,
    config: Optional[SimulationConfig] = None,
    reference_audit: Optional[Dict[str, Any]] = None,
    parameter_audit: Optional[Dict[str, Any]] = None,
    source_mode: Optional[str] = None,
) -> Dict[str, Any]:
    payload = build_runmode_capabilities(
        config=config,
        reference_audit=reference_audit,
        parameter_audit=parameter_audit,
        source_mode=source_mode,
    )
    _write_json(output_dir / "runmode_capabilities.json", payload)
    return payload
