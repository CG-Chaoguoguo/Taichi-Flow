"""Structured run-mode capability registry for backend/UI exposure decisions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from edda.config.sim_config import SimulationConfig


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


RUNMODE_CAPABILITIES: List[Dict[str, Any]] = [
    {
        "key": "hydrology.use_background_flux_offset",
        "raw_label": "Add steady background flux to transient infiltration rate...",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "implemented_and_switchable",
        "frontend_exposure_policy": "switchable",
        "blocked_reason": None,
        "evidence_basis": "Original `bkgrof` has active source-trace and current backend runtime consumption; React/FastAPI contract is tested.",
    },
    {
        "key": "flags.use_analytic_fillable_porosity",
        "raw_label": "Use analytic solution for fillable porosity?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "blocked_by_missing_source_trace",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Visible original source shows parsing of `lany`, but no active consumer was found in the current source-trace set.",
        "evidence_basis": "Current backend has no safe equivalent runtime gate.",
    },
    {
        "key": "flags.estimate_positive_pressure_head",
        "raw_label": "Estimate positive pressure head in rising water table zone?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "blocked_by_missing_source_trace",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Visible original source shows parsing of `llus`, but no active consumer was found in the current source-trace set.",
        "evidence_basis": "Current backend has no safe equivalent runtime gate.",
    },
    {
        "key": "flags.use_psi0_negative_inverse_alpha",
        "raw_label": "Use psi0=-1/alpha?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "blocked_by_missing_source_trace",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Visible original source shows parsing of `lps0`, but no active consumer was found in the current source-trace set.",
        "evidence_basis": "Current backend has no safe equivalent runtime gate.",
    },
    {
        "key": "flags.flow_direction_mode",
        "raw_label": "Flow direction (gener/slope/hydro)",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "blocked_by_missing_source_trace",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Original input label exists, but current backend is fixed to DEM-derived connectivity and visible original active consumers were not found.",
        "evidence_basis": "Do not expose `gener/slope/hydro` as a real switch.",
    },
    {
        "key": "flags.use_full_dynamic_wave",
        "raw_label": "Using the full dynamic wave equation to compute the velocity?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "blocked_by_missing_source_trace",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Visible original source proves parsing of `fulldyna`, but no active original branch selection was found in the current source-trace set.",
        "evidence_basis": "Current backend follows a fixed solver path and does not expose this as a safe independent toggle.",
    },
    {
        "key": "flags.log_mass_balance_results",
        "raw_label": "Log mass balance results?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend can surface structured JSON parity for requested mass-balance logging, but does not emit original `EDDALog.txt` text parity.",
        "evidence_basis": "Treat as metadata-only parity; do not expose as a real logging toggle.",
    },
    {
        "key": "flags.simulate_rainfall",
        "raw_label": "Simulte rainfall?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "implemented_but_fixed_scientific_path",
        "frontend_exposure_policy": "fixed_path",
        "blocked_reason": "Current backend treats rainfall as input-driven forcing, not as an independent off/on switch.",
        "evidence_basis": "Reference-config rainfall source selection is production-reachable.",
    },
    {
        "key": "flags.simulate_infiltration",
        "raw_label": "Simulte infiltration?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "implemented_but_fixed_scientific_path",
        "frontend_exposure_policy": "fixed_path",
        "blocked_reason": "Current backend treats infiltration as part of the production scientific path instead of a safe standalone toggle.",
        "evidence_basis": "Runtime path exists, but no safe independent contract exists.",
    },
    {
        "key": "flags.simulate_inflow_hydrograph",
        "raw_label": "Simulate inflow hydrograph?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend can now consume active `inflow.txt` hydrograph forcing for the DFS production path, but full original log/report parity remains incomplete.",
        "evidence_basis": "Reference-config `inflowsimul + inflow.txt` now reaches runtime DFS staging fields and inflow-volume accounting.",
    },
    {
        "key": "flags.simulate_outflow_cell",
        "raw_label": "Simulate outflow cell?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend now consumes `outflow.txt` for selected-cell observation/export, but full original hydraulic parity is still incomplete.",
        "evidence_basis": "Selected-cell sidecar loading and partial `OUTNQ_*` export exist; full routing parity remains blocked.",
    },
    {
        "key": "flags.simulate_shallow_landslide",
        "raw_label": "Simulate shallow landslide?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "implemented_but_fixed_scientific_path",
        "frontend_exposure_policy": "fixed_path",
        "blocked_reason": "Current backend couples shallow-failure logic into the production path without a separate evidence-backed toggle.",
        "evidence_basis": "Do not split this path until parity risk is lower.",
    },
    {
        "key": "flags.simulate_debris_flow",
        "raw_label": "Simulate debris flow?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend runs a debris-flow production path, but does not expose original `debrissimul` branch semantics as a safe independent switch.",
        "evidence_basis": "Keep status-only.",
    },
    {
        "key": "flags.simulate_erosion",
        "raw_label": "Simulte erosion?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "implemented_but_fixed_scientific_path",
        "frontend_exposure_policy": "fixed_path",
        "blocked_reason": "Current backend erosion/deposition logic is part of the fixed production path rather than an independently validated toggle.",
        "evidence_basis": "Do not split without parity evidence.",
    },
    {
        "key": "flags.simulate_water_and_solid_separately",
        "raw_label": "Simulte simulate the water and solid material seperately?",
        "family": "run_mode",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend does not expose a safe standalone contract for the original separate water/solid treatment mode.",
        "evidence_basis": "Partial runtime behavior exists only.",
    },
    {
        "key": "rainfall.source_family",
        "raw_label": "cri/capt/rifil rainfall source family",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "implemented_but_derived",
        "frontend_exposure_policy": "derived_from_inputs",
        "blocked_reason": None,
        "evidence_basis": "Production parser/mapper/runtime preserve per-period uniform-vs-raster source selection.",
    },
    {
        "key": "manning.source_family",
        "raw_label": "manningfil/global manning source family",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "implemented_but_derived",
        "frontend_exposure_policy": "derived_from_inputs",
        "blocked_reason": None,
        "evidence_basis": "Production runtime selects raster Manning when available and falls back to global initiation Manning otherwise.",
    },
    {
        "key": "native_inputs.demfil",
        "raw_label": "demfil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "implemented_but_derived",
        "frontend_exposure_policy": "importable_auditable",
        "blocked_reason": None,
        "evidence_basis": "Formal production input through upload or reference-config mapping.",
    },
    {
        "key": "native_inputs.slofil",
        "raw_label": "slofil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "implemented_but_derived",
        "frontend_exposure_policy": "importable_auditable",
        "blocked_reason": None,
        "evidence_basis": "Current backend has a production slope-grid loader.",
    },
    {
        "key": "native_inputs.zonfil",
        "raw_label": "zonfil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "implemented_but_derived",
        "frontend_exposure_policy": "importable_auditable",
        "blocked_reason": None,
        "evidence_basis": "Current backend has a production zone-grid loader.",
    },
    {
        "key": "native_inputs.dirfil",
        "raw_label": "dirfil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend derives connectivity from DEM and does not consume original direction grids.",
        "evidence_basis": "Keep provenance only.",
    },
    {
        "key": "native_inputs.zfil",
        "raw_label": "zfil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend closes the original `ltstar < 0` branch for `zfil`, but not the separate original `zmax < 0` branch that reuses the same file family.",
        "evidence_basis": "Treat as partial semantic alignment: case-driven `ltstar` use is anchored, `zmax` parity remains blocked.",
    },
    {
        "key": "native_inputs.depfil",
        "raw_label": "depfil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend now closes the original `depth < 0` initialization branch, but broader groundwater-depth family parity is still incomplete.",
        "evidence_basis": "Scalar fallback and per-cell `depfil` initialization branch are production-reachable; no broader family parity is claimed.",
    },
    {
        "key": "native_inputs.rizerofil",
        "raw_label": "rizerofil",
        "family": "input_family",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend now closes the original `rizero < 0` initialization branch, but no separate inflow-sidecar forcing semantics are implied.",
        "evidence_basis": "Scalar fallback and per-cell `rizerofil` initialization branch are production-reachable.",
    },
    {
        "key": "sidecar.outflow.txt",
        "raw_label": "outflow.txt",
        "family": "sidecar",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend now consumes `outflow.txt` for selected-cell observation/export, but full original hydraulic parity remains incomplete.",
        "evidence_basis": "Selected-cell outflow observer/export exists; generic edge outflow handling still coexists.",
    },
    {
        "key": "sidecar.hydrograph.txt",
        "raw_label": "hydrograph.txt",
        "family": "sidecar",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend can consume `hydrograph.txt` for monitored-output export, but only the zero-flow synthetic oracle has been validated.",
        "evidence_basis": "Hydrosave monitored-cell loader and original-style `HYDROGRAPH_` writer exist; keep UI switching blocked until broader oracle coverage.",
    },
    {
        "key": "sidecar.inflow.txt",
        "raw_label": "inflow.txt",
        "family": "sidecar",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend now consumes active `inflow.txt` hydrographs for DFS runtime forcing, but full original reporting parity remains incomplete.",
        "evidence_basis": "Original `inflow_read.F90` semantics are source-traced and the current backend now maps the sidecar into DFS staging fields.",
    },
    {
        "key": "sidecar.EDDALog.txt",
        "raw_label": "EDDALog.txt",
        "family": "sidecar",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend emits structured JSON metadata that preserves part of the original logging truth, but not original `EDDALog.txt` text/process parity.",
        "evidence_basis": "Do not fake original log output.",
    },
    {
        "key": "output_flags.legacy_slope_failure_family",
        "raw_label": "Legacy slope-failure / runoff / PF / road / warning / listing flags",
        "family": "output_flag_family",
        "original_true_switch": "yes",
        "current_backend_status": "unsupported_in_current_backend",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend does not implement these original legacy output families.",
        "evidence_basis": "Keep provenance only.",
    },
    {
        "key": "output_flags.whole_process_grid_family",
        "raw_label": "Whole-process grid output flags (flow depth/velocity/erosion/deposition/cv)",
        "family": "output_flag_family",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend writes real result files, but not under the original per-flag export-control contract.",
        "evidence_basis": "Treat as partial result support, not original flag parity.",
    },
    {
        "key": "output_flags.save_outflow_process",
        "raw_label": "Save outflow process?",
        "family": "output_flag_family",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend can emit partial original-style `OUTNQ_*` exports, but full hydraulic parity with original outflow routing remains incomplete.",
        "evidence_basis": "Selected-cell outflow observer/export exists; treat as partial parity only.",
    },
    {
        "key": "output_flags.save_hydrograph_cells",
        "raw_label": "Save hydrograph of specified cells?",
        "family": "output_flag_family",
        "original_true_switch": "yes",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Original `HYDROGRAPH_` export parity is implemented only for source-backed monitored-cell output and the zero-flow synthetic oracle so far.",
        "evidence_basis": "Hydrosave observer/export path exists; non-zero active-case validation remains pending.",
    },
    {
        "key": "rheology.shallown",
        "raw_label": "shallown",
        "family": "parameter",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend parses and maps `shallown`, but no production runtime consumer is audited.",
        "evidence_basis": "Keep blocked until an active original consumer or validated equivalent is identified.",
    },
    {
        "key": "time.wavemax",
        "raw_label": "wavemax",
        "family": "parameter",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend parses and maps `wavemax`, but no production Taichi runtime consumer is audited.",
        "evidence_basis": "Do not expose until runtime consumption is closed.",
    },
    {
        "key": "soil.double_layer.uww",
        "raw_label": "uww (double-layer branch)",
        "family": "parameter",
        "original_true_switch": "no",
        "current_backend_status": "implemented_but_fixed_scientific_path",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "The backend now consumes `soil.double_layer.uww` in the double-layer runtime, but this parameter is not being exposed as a standalone UI switch in the current scientific-alignment stage.",
        "evidence_basis": "Visible original `doublelayer.F90` uses `uww`, and the current backend now wires the parsed config value into the runtime path.",
    },
    {
        "key": "native_inputs.zmax",
        "raw_label": "zmax",
        "family": "parameter",
        "original_true_switch": "no",
        "current_backend_status": "blocked_by_missing_source_trace",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend preserves parsed `zmax` provenance, but no canonical runtime consumer is closed.",
        "evidence_basis": "Keep parsed-only until original active consumer or validated equivalent is identified.",
    },
    {
        "key": "soil.porosity",
        "raw_label": "porosity",
        "family": "parameter",
        "original_true_switch": "no",
        "current_backend_status": "partial",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend parses porosity in zone rows but does not map it into a production runtime field.",
        "evidence_basis": "Do not expose until parsed -> mapped -> consumed is closed.",
    },
    {
        "key": "soil.zone_stddev_family",
        "raw_label": "zone stddev family",
        "family": "parameter",
        "original_true_switch": "no",
        "current_backend_status": "unsupported_in_current_backend",
        "frontend_exposure_policy": "blocked",
        "blocked_reason": "Current backend has no parser/model/runtime support for the original zone stddev family.",
        "evidence_basis": "Keep fully blocked.",
    },
]


def _infer_source_trace_status(entry: Dict[str, Any]) -> str:
    status = entry.get("current_backend_status")
    if status == "blocked_by_missing_source_trace":
        return "missing_active_consumer"
    if entry.get("key") == "native_inputs.zfil":
        return "dual_role_partial"
    return "anchored"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _configured_value(
    key: str,
    config: Optional[SimulationConfig],
    reference_audit: Optional[Dict[str, Any]],
    parameter_audit: Optional[Dict[str, Any]],
) -> Any:
    flags = (reference_audit or {}).get("flags") or {}
    if key == "hydrology.use_background_flux_offset" and config is not None:
        return config.hydrology.use_background_flux_offset
    parameters = {
        entry.get("parameter"): entry
        for entry in (parameter_audit or {}).get("parameters", [])
        if isinstance(entry, dict) and entry.get("parameter")
    }
    if key in parameters:
        return (parameters[key].get("evidence") or {}).get("configured_value")
    if key == "native_inputs.zmax":
        return (reference_audit or {}).get("zmax")
    flag_key = key.removeprefix("flags.")
    if flag_key in flags:
        return flags.get(flag_key)
    return None


def build_runmode_capabilities(
    config: Optional[SimulationConfig] = None,
    reference_audit: Optional[Dict[str, Any]] = None,
    parameter_audit: Optional[Dict[str, Any]] = None,
    source_mode: Optional[str] = None,
) -> Dict[str, Any]:
    capabilities = deepcopy(RUNMODE_CAPABILITIES)
    parsed_flag_closure = (reference_audit or {}).get("flag_closure") or []
    for entry in capabilities:
        entry["configured_value"] = _configured_value(entry["key"], config, reference_audit, parameter_audit)
        entry["source_trace_status"] = _infer_source_trace_status(entry)

    status_summary: Dict[str, int] = {}
    exposure_summary: Dict[str, int] = {}
    for entry in capabilities:
        status = entry["current_backend_status"]
        exposure = entry["frontend_exposure_policy"]
        status_summary[status] = status_summary.get(status, 0) + 1
        exposure_summary[exposure] = exposure_summary.get(exposure, 0) + 1

    return {
        "generated_at": _timestamp(),
        "source_mode": source_mode,
        "capabilities": capabilities,
        "parsed_flag_closure": parsed_flag_closure,
        "summary": {
            "count": len(capabilities),
            "status_summary": status_summary,
            "frontend_exposure_summary": exposure_summary,
            "switchable_keys": [
                entry["key"]
                for entry in capabilities
                if entry["frontend_exposure_policy"] == "switchable"
            ],
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
