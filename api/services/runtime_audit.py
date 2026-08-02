"""Persist production audit evidence without changing solver behavior."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from edda.config.sim_config import SimulationConfig
from api.services.result_files import (
    classify_result_family as _shared_classify_result_family,
    is_result_file as _shared_is_result_file,
    taichi_result_name,
)


METADATA_FILENAMES = {
    "effective_config.json",
    "input_source_registry.json",
    "job_metadata.json",
    "output_manifest.json",
    "parameter_audit.json",
    "request_payload.json",
    "runmode_capabilities.json",
    "runtime_input_manifest.json",
    "runtime_provenance.json",
}

REFERENCE_RESULT_PREFIXES = (
    "flow_depth_",
    "flow_velocity_",
    "max_flow_depth_",
    "max_flow_velocity_",
    "erosion_depth_",
    "deposit_depth_",
    "total_depth_",
    "volumetric_sediment_conce",
    "volumetric_sediment_concentration_",
    "fs_min_",
    "z_at_fs_min_",
    "depth_at_fs_min_",
    "p_at_fs_min_",
    "pf_at_fs_min",
    "list_z_p_fs_",
    "outnq_",
    "hydrograph_",
)

REFERENCE_ARTIFACT_PREFIXES = {
    "Flow_depth_*": ("flow_depth_",),
    "Max_flow_depth_*": ("max_flow_depth_",),
    "Flow_velocity_*": ("flow_velocity_",),
    "Max_flow_velocity_*": ("max_flow_velocity_",),
    "Erosion_depth_*": ("erosion_depth_",),
    "Deposit_depth_*": ("deposit_depth_",),
    "Total_depth_*": ("total_depth_",),
    "Volumetric_sediment_concentration_*": ("volumetric_sediment_conce", "volumetric_sediment_concentration_"),
    "FS_min_*": ("fs_min_",),
    "OUTNQ_*": ("outnq_",),
    "HYDROGRAPH_*": ("hydrograph_",),
    "EDDALog.txt": ("eddalog.txt",),
    "EDDALog pressure-head / FS listing sections": ("list_z_p_fs_",),
}

NONINVENTORY_REFERENCE_ARTIFACTS = {
    "EDDALog mass-balance sections",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _classify_result_family(relative_path: str) -> str:
    return _shared_classify_result_family(relative_path)


def _is_result_file(path: Path, relative_path: str) -> bool:
    return _shared_is_result_file(path, relative_path)


def _matches_reference_artifact(relative_path: str, artifact: str) -> bool:
    name = Path(relative_path).name.lower()
    prefixes = REFERENCE_ARTIFACT_PREFIXES.get(artifact)
    if not prefixes:
        return False
    return any(name.startswith(prefix.lower()) for prefix in prefixes)


def _build_reference_output_parity(
    relative_paths: List[str],
    reference_output_expectations: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not reference_output_expectations:
        return None

    expected_output_families = list(reference_output_expectations.get("expected_output_families", []) or [])
    expected_log_artifacts = list(reference_output_expectations.get("expected_log_artifacts", []) or [])
    output_timing = reference_output_expectations.get("output_timing", {}) or {}
    artifacts = expected_output_families + expected_log_artifacts
    artifact_status: List[Dict[str, Any]] = []

    for artifact in artifacts:
        inventory_observable = artifact not in NONINVENTORY_REFERENCE_ARTIFACTS
        observed_files = (
            [path for path in relative_paths if _matches_reference_artifact(path, artifact)]
            if inventory_observable
            else []
        )
        if observed_files:
            parity_status = "present"
        elif inventory_observable:
            parity_status = "missing"
        else:
            parity_status = "not_observable_from_file_inventory"
        artifact_status.append(
            {
                "artifact": artifact,
                "timing": output_timing.get(artifact),
                "inventory_observable": inventory_observable,
                "observed_files": observed_files,
                "parity_status": parity_status,
            }
        )

    return {
        "expected_output_families": expected_output_families,
        "expected_log_artifacts": expected_log_artifacts,
        "artifact_status": artifact_status,
        "present_artifacts": [entry["artifact"] for entry in artifact_status if entry["parity_status"] == "present"],
        "missing_artifacts": [entry["artifact"] for entry in artifact_status if entry["parity_status"] == "missing"],
        "noninventory_artifacts": [
            entry["artifact"]
            for entry in artifact_status
            if entry["parity_status"] == "not_observable_from_file_inventory"
        ],
    }


def build_output_manifest(
    output_dir: Path,
    reference_output_expectations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata_files: List[Dict[str, Any]] = []
    generated_input_files: List[Dict[str, Any]] = []
    result_files: List[Dict[str, Any]] = []
    other_files: List[Dict[str, Any]] = []
    result_family_summary: Dict[str, int] = {}

    if output_dir.exists():
        for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
            relative_path = path.relative_to(output_dir).as_posix()
            entry = {
                "relative_path": relative_path,
                "size_bytes": path.stat().st_size,
                "suffix": path.suffix.lower(),
            }
            if path.name in METADATA_FILENAMES:
                metadata_files.append(entry)
            elif relative_path.startswith("_generated_inputs/"):
                generated_input_files.append(entry)
            elif _is_result_file(path, relative_path):
                family = _classify_result_family(relative_path)
                entry["family"] = family
                entry["download_filename"] = taichi_result_name(relative_path)
                result_files.append(entry)
                result_family_summary[family] = result_family_summary.get(family, 0) + 1
            else:
                other_files.append(entry)

    expected_metadata_files = sorted(METADATA_FILENAMES)
    present_metadata_names = {entry["relative_path"] for entry in metadata_files if "relative_path" in entry}
    missing_metadata_files = [name for name in expected_metadata_files if name not in present_metadata_names]
    all_relative_paths = [
        *(entry["relative_path"] for entry in metadata_files),
        *(entry["relative_path"] for entry in generated_input_files),
        *(entry["relative_path"] for entry in result_files),
        *(entry["relative_path"] for entry in other_files),
    ]
    reference_output_parity = _build_reference_output_parity(all_relative_paths, reference_output_expectations)

    manifest = {
        "generated_at": _timestamp(),
        "output_dir": str(output_dir),
        "expected_metadata_files": expected_metadata_files,
        "metadata_files": metadata_files,
        "missing_metadata_files": missing_metadata_files,
        "generated_input_files": generated_input_files,
        "result_files": result_files,
        "result_family_summary": result_family_summary,
        "other_files": other_files,
        "counts": {
            "metadata_files": len(metadata_files),
            "missing_metadata_files": len(missing_metadata_files),
            "generated_input_files": len(generated_input_files),
            "result_files": len(result_files),
            "other_files": len(other_files),
        },
    }
    if reference_output_parity is not None:
        manifest["reference_output_parity"] = reference_output_parity
    return manifest


def write_output_manifest_file(
    output_dir: Path,
    reference_output_expectations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = build_output_manifest(output_dir, reference_output_expectations=reference_output_expectations)
    _write_json(output_dir / "output_manifest.json", manifest)
    return manifest


def _manifest_lookup(runtime_input_manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        entry.get("family"): entry
        for entry in runtime_input_manifest.get("inputs", [])
        if isinstance(entry, dict) and entry.get("family")
    }


def _output_evidence(output_manifest: Optional[Dict[str, Any]]) -> List[str]:
    result_files = (output_manifest or {}).get("result_files", [])
    return [entry["relative_path"] for entry in result_files if "relative_path" in entry]


def _reference_artifact_status(
    output_manifest: Optional[Dict[str, Any]],
    artifact: str,
) -> Dict[str, Any]:
    parity = (output_manifest or {}).get("reference_output_parity") or {}
    for entry in parity.get("artifact_status", []):
        if entry.get("artifact") == artifact:
            return entry
    return {}


def _family_parameter_entry(
    manifest: Dict[str, Dict[str, Any]],
    family: str,
    parameter: str,
    parsed: bool = True,
    mapped: bool = True,
    consumed_override: Optional[bool] = None,
    status_override: Optional[str] = None,
    output_evidence: Optional[List[str]] = None,
    extra_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry = manifest.get(family, {})
    consumed = bool(entry.get("consumed")) if consumed_override is None else consumed_override
    status = status_override or entry.get("production_status") or "missing"
    evidence = {
        "family": family,
        "path": entry.get("path"),
        "exists_on_disk": entry.get("exists_on_disk"),
        "input_state": entry.get("input_state"),
        "selected_source": entry.get("selected_source"),
        "source_registry_key": entry.get("source_registry_key"),
        "resolved_via_fallback": entry.get("resolved_via_fallback"),
        "effective_runtime_source": entry.get("effective_runtime_source"),
        "effective_runtime_source_active": entry.get("effective_runtime_source_active"),
        "runtime_stage": entry.get("runtime_stage"),
        "notes": entry.get("notes"),
        "blocked_reason": entry.get("blocked_reason"),
        "activation_condition": entry.get("activation_condition"),
        "original_branch_active": entry.get("original_branch_active"),
        "current_backend_branch_active": entry.get("current_backend_branch_active"),
        "activation_basis": entry.get("activation_basis"),
        "expected_output_families": entry.get("expected_output_families"),
        "status_basis": entry.get("status_basis"),
        "structure_summary": entry.get("structure_summary"),
    }
    if extra_evidence:
        evidence.update(extra_evidence)
    return {
        "parameter": parameter,
        "parsed": parsed,
        "mapped": mapped,
        "consumed": consumed,
        "output_evidence": output_evidence or [],
        "status": status,
        "evidence": evidence,
    }


def _source_registry_parameter_entry(
    parameter: str,
    registry_entry: Optional[Dict[str, Any]],
    *,
    consumed: bool,
    output_evidence: Optional[List[str]] = None,
) -> Dict[str, Any]:
    entry = registry_entry or {}
    state = entry.get("state")
    runtime_active = entry.get("runtime_active")
    if runtime_active is None:
        runtime_active = state in {"file_backed", "config_fallback"}
    runtime_equivalent_implemented = entry.get("runtime_equivalent_implemented")
    if runtime_equivalent_implemented is None:
        runtime_equivalent_implemented = bool(runtime_active)
    evidence = {
        **entry,
        "resolved_via_fallback": state == "config_fallback",
        "effective_runtime_source": entry.get("selected_source"),
        "effective_runtime_source_active": bool(runtime_active),
        "runtime_equivalent_implemented": bool(runtime_equivalent_implemented),
    }
    return {
        "parameter": parameter,
        "parsed": bool(entry),
        "mapped": bool(entry),
        "consumed": bool(consumed and runtime_equivalent_implemented),
        "output_evidence": output_evidence or [],
        "status": entry.get("selected_source") or entry.get("state") or "missing",
        "evidence": evidence,
    }


def build_parameter_audit(
    config: SimulationConfig,
    runtime_input_manifest: Dict[str, Any],
    provenance: Dict[str, Any],
    request_payload: Optional[Dict[str, Any]] = None,
    output_manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = _manifest_lookup(runtime_input_manifest)
    reference_audit = provenance.get("reference_config_audit") or {}
    rainfall_audit = provenance.get("rainfall_audit") or {}
    normalization = provenance.get("config_normalization") or {}
    flag_closure = reference_audit.get("flag_closure") or []
    unsupported_flags = reference_audit.get("unsupported_flags") or []
    outputs = _output_evidence(output_manifest)
    sidecar_output_parity = provenance.get("sidecar_output_parity") or runtime_input_manifest.get("sidecar_output_parity")
    input_source_registry = runtime_input_manifest.get("input_source_registry") or provenance.get("input_source_registry") or {}

    parameters: List[Dict[str, Any]] = [
        {
            "parameter": "hydrology.use_background_flux_offset",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "active" if config.hydrology.use_background_flux_offset else "inactive",
            "evidence": {
                "configured_value": config.hydrology.use_background_flux_offset,
            },
        },
        {
            "parameter": "hydrology.K_sat",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.hydrology.K_sat,
            },
        },
        {
            "parameter": "soil.gamma_s",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.soil.gamma_s,
            },
        },
        {
            "parameter": "soil.c",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.soil.c,
            },
        },
        {
            "parameter": "soil.phi",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.soil.phi,
            },
        },
        {
            "parameter": "soil.gamma_w",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.soil.gamma_w,
            },
        },
        {
            "parameter": "rheology.n_manning",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.rheology.n_manning,
                "manifest_manning_source": provenance.get("manning_source"),
            },
        },
        {
            "parameter": "rheology.limitfr",
            "parsed": True,
            "mapped": True,
            "consumed": True,
            "output_evidence": outputs,
            "status": "configured",
            "evidence": {
                "configured_value": config.rheology.limitfr,
            },
        },
    ]

    if provenance.get("source_mode") == "reference_config":
        parameters.extend(
            [
                {
                    "parameter": "manning_source",
                    "parsed": True,
                    "mapped": True,
                    "consumed": bool(
                        manifest.get("manningfil", {}).get("consumed")
                        or manifest.get("manning_global", {}).get("consumed")
                    ),
                    "output_evidence": outputs,
                    "status": provenance.get("manning_source"),
                    "evidence": {
                        "manifest_families": ["manningfil", "manning_global"],
                    },
                },
                {
                    "parameter": "rainfall_mode",
                    "parsed": True,
                    "mapped": True,
                    "consumed": bool(
                        manifest.get("rainfall_schedule", {}).get("consumed")
                        or manifest.get("rainfall_spatial_series", {}).get("consumed")
                    ),
                    "output_evidence": outputs,
                    "status": runtime_input_manifest.get("rainfall_mode"),
                    "evidence": {
                        "manifest_families": ["rainfall_schedule", "rainfall_spatial_series", "rifil"],
                        "period_source_map": runtime_input_manifest.get("period_source_map"),
                    },
                },
                _source_registry_parameter_entry(
                    "water_table_source",
                    input_source_registry.get("water_table_source"),
                    consumed=(
                        bool(manifest.get("depfil", {}).get("consumed"))
                        or input_source_registry.get("water_table_source", {}).get("state") == "config_fallback"
                    ),
                    output_evidence=outputs if bool(manifest.get("depfil", {}).get("consumed")) else [],
                ),
                _source_registry_parameter_entry(
                    "initial_infiltration_source",
                    input_source_registry.get("initial_infiltration_source"),
                    consumed=(
                        bool(manifest.get("rizerofil", {}).get("consumed"))
                        or input_source_registry.get("initial_infiltration_source", {}).get("state") == "config_fallback"
                    ),
                    output_evidence=outputs if bool(manifest.get("rizerofil", {}).get("consumed")) else [],
                ),
                _source_registry_parameter_entry(
                    "rainfall_source",
                    input_source_registry.get("rainfall_source"),
                    consumed=bool(
                        manifest.get("rainfall_schedule", {}).get("consumed")
                        or manifest.get("rainfall_spatial_series", {}).get("consumed")
                    ),
                    output_evidence=outputs,
                ),
                _source_registry_parameter_entry(
                    "dfs_infiltration_variant",
                    input_source_registry.get("dfs_infiltration_variant"),
                    consumed=True,
                    output_evidence=outputs,
                ),
                _source_registry_parameter_entry(
                    "dfs_face_flux_variant",
                    input_source_registry.get("dfs_face_flux_variant"),
                    consumed=True,
                    output_evidence=outputs,
                ),
                _source_registry_parameter_entry(
                    "dfs_failure_source_variant",
                    input_source_registry.get("dfs_failure_source_variant"),
                    consumed=True,
                    output_evidence=outputs,
                ),
                _source_registry_parameter_entry(
                    "outflow_point_source",
                    input_source_registry.get("outflow_point_source"),
                    consumed=bool(manifest.get("outflow.txt", {}).get("consumed")),
                    output_evidence=_reference_artifact_status(output_manifest, "OUTNQ_*").get("observed_files", []),
                ),
                _source_registry_parameter_entry(
                    "inflow_source",
                    input_source_registry.get("inflow_source"),
                    consumed=bool(manifest.get("inflow.txt", {}).get("consumed")),
                    output_evidence=outputs if bool(manifest.get("inflow.txt", {}).get("consumed")) else [],
                ),
                {
                    "parameter": "period_source_map",
                    "parsed": True,
                    "mapped": True,
                    "consumed": False,
                    "output_evidence": [],
                    "status": "metadata-only",
                    "evidence": {
                        "period_source_map": runtime_input_manifest.get("period_source_map"),
                        "status_basis": "The solver consumes generated rainfall files, not the metadata map itself.",
                    },
                },
                {
                    "parameter": "rheology.shallown",
                    "parsed": True,
                    "mapped": True,
                    "consumed": False,
                    "output_evidence": [],
                    "status": "missing_runtime_consumption",
                    "evidence": {
                        "configured_value": config.rheology.shallown,
                        "limitation": "No production runtime consumption point is currently audited for `shallown`.",
                        "status_basis": "Original Fortran source-trace only exposed `shallown` inside commented-out Manning adjustment blocks in `dfs.F90`/`wfs.F90`.",
                    },
                },
                {
                    "parameter": "time.wavemax",
                    "parsed": True,
                    "mapped": True,
                    "consumed": False,
                    "output_evidence": [],
                    "status": "mapped-only",
                    "evidence": {
                        "configured_value": config.time.wavemax,
                        "status_basis": "Current repo audit did not locate a production Taichi runtime consumer for `wavemax`, even though original `wfs.F90` uses it in the time-step stability test.",
                    },
                },
                {
                    "parameter": "soil.double_layer.uww",
                    "parsed": True,
                    "mapped": True,
                    "consumed": True,
                    "output_evidence": outputs,
                    "status": "consumed",
                    "evidence": {
                        "configured_value": (
                            config.soil.double_layer.uww
                            if config.soil.double_layer
                            else None
                        ),
                        "status_basis": "Current `DoubleLayerSoilModel` now reads `config.soil.double_layer.uww` directly for the original double-layer pore-pressure / FS terms.",
                    },
                },
                {
                    "parameter": "zmax",
                    "parsed": "zmax" in reference_audit,
                    "mapped": False,
                    "consumed": False,
                    "output_evidence": [],
                    "status": "parsed-only",
                    "evidence": {
                        "configured_value": reference_audit.get("zmax"),
                        "status_basis": "Original reference config scalar `zmax` is now parsed for provenance, but the current backend has no canonical config field or runtime consumer for original `zmax` semantics.",
                    },
                },
                _family_parameter_entry(
                    manifest,
                    "zfil",
                    "native_input.zfil",
                    status_override="partial-semantic-alignment" if manifest.get("zfil") else "missing",
                    output_evidence=outputs if manifest.get("zfil", {}).get("consumed") else [],
                    extra_evidence={
                        "current_runtime_mapping": "ltstar_field",
                        "original_fortran_semantic": "ltstar grid when `ltstar < 0`; zmax grid when `zmax < 0`",
                    },
                ),
                _family_parameter_entry(
                    manifest,
                    "dirfil",
                    "native_input.dirfil",
                ),
                _family_parameter_entry(
                    manifest,
                    "depfil",
                    "native_input.depfil",
                ),
                _family_parameter_entry(
                    manifest,
                    "rizerofil",
                    "native_input.rizerofil",
                ),
                _family_parameter_entry(
                    manifest,
                    "outflow.txt",
                    "sidecar.outflow.txt",
                ),
                _family_parameter_entry(
                    manifest,
                    "hydrograph.txt",
                    "sidecar.hydrograph.txt",
                ),
                _family_parameter_entry(
                    manifest,
                    "inflow.txt",
                    "sidecar.inflow.txt",
                ),
                {
                    "parameter": "output.OUTNQ_*",
                    "parsed": "OUTNQ_*" in (provenance.get("reference_output_expectations") or {}).get("expected_output_families", []),
                    "mapped": True,
                    "consumed": False,
                    "output_evidence": _reference_artifact_status(output_manifest, "OUTNQ_*").get("observed_files", []),
                    "status": _reference_artifact_status(output_manifest, "OUTNQ_*").get("parity_status", "missing"),
                    "evidence": {
                        "reference_artifact": _reference_artifact_status(output_manifest, "OUTNQ_*"),
                        "sidecar_output_parity": (sidecar_output_parity or {}).get("outflow.txt"),
                    },
                },
                {
                    "parameter": "sidecar.EDDALog.txt",
                    "parsed": "EDDALog.txt" in (provenance.get("reference_output_expectations") or {}).get("expected_log_artifacts", []),
                    "mapped": True,
                    "consumed": False,
                    "output_evidence": _reference_artifact_status(output_manifest, "EDDALog.txt").get("observed_files", []),
                    "status": "metadata-only",
                    "evidence": {
                        "reference_artifact": _reference_artifact_status(output_manifest, "EDDALog.txt"),
                        "sidecar_output_parity": (sidecar_output_parity or {}).get("EDDALog.txt"),
                    },
                },
            ]
        )
        for unsupported_flag in flag_closure:
            parameters.append(
                {
                    "parameter": unsupported_flag.get("canonical_key") or f"flag.{unsupported_flag['flag']}",
                    "parsed": True,
                    "mapped": False,
                    "consumed": False,
                    "output_evidence": [],
                    "status": unsupported_flag.get("current_status"),
                    "evidence": unsupported_flag,
                }
            )

    return {
        "generated_at": _timestamp(),
        "source_mode": provenance.get("source_mode"),
        "request_payload_present": request_payload is not None,
        "config_normalization": normalization,
        "reference_case_activation": runtime_input_manifest.get("reference_case_activation"),
        "reference_output_expectations": provenance.get("reference_output_expectations"),
            "reference_summary": {
                "manning_source": provenance.get("manning_source"),
                "rainfall_mode": runtime_input_manifest.get("rainfall_mode"),
                "input_source_registry": input_source_registry,
                "period_source_map": runtime_input_manifest.get("period_source_map"),
                "audit_notes": reference_audit.get("audit_notes"),
                "rainfall_active_source": rainfall_audit.get("active_source"),
            "sidecar_summaries": {
                family: manifest.get(family, {}).get("structure_summary")
                for family in ("inflow.txt", "outflow.txt", "hydrograph.txt")
                if manifest.get(family, {}).get("structure_summary") is not None
            },
            "flag_closure": flag_closure,
            "unsupported_flags": unsupported_flags,
            "sidecar_output_parity": sidecar_output_parity,
            "reference_output_parity": (output_manifest or {}).get("reference_output_parity"),
        },
        "parameters": parameters,
    }


def write_parameter_audit_file(output_dir: Path, parameter_audit: Dict[str, Any]) -> None:
    _write_json(output_dir / "parameter_audit.json", parameter_audit)
