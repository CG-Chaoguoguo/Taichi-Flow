"""Production parser for original EDDA `edda_in.txt` reference configurations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from api.services.edda_switch_registry import (
    EDDA_SWITCH_REGISTRY,
    EddaSwitchSnapshot,
    build_switch_snapshot,
)
from api.services.native_sidecar_loader import parse_case_sidecar


FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\d+|\.\d+)(?:[eEdD][-+]?\d+)?")
ZONE_RE = re.compile(r"^zone,\s*(\d+)", re.IGNORECASE)
FILE_KEY_RE = re.compile(r"\(([^)]+)\)")


@dataclass
class ZoneLayerParams:
    c: float
    phi: float
    phib: float
    gamma_s: float
    diffusivity: float
    k_sat: float
    theta_sat: float
    theta_res: float
    theta_ini: float
    porosity: float
    psi_f: float
    alpha: float
    kero: float = 1e-6
    ctao: float = 10.0
    # Chamoli top-layer column; BJ edda_in stops at ctao. None => rhoero falls back to cvstar.
    cvero: Optional[float] = None


@dataclass
class ZoneParamsParsed:
    zone_id: int
    bottom: ZoneLayerParams
    top: ZoneLayerParams


@dataclass
class NativeInputFileRef:
    family: str
    raw_paths: List[str] = field(default_factory=list)
    resolved_paths: List[str] = field(default_factory=list)
    exists: List[bool] = field(default_factory=list)
    priority: str = "recognized"
    production_status: str = "recognized"
    notes: Optional[str] = None
    blocked_reason: Optional[str] = None
    activation_condition: Optional[str] = None
    status_basis: Optional[str] = None
    structure_summary: Optional[Dict[str, Any]] = None
    original_branch_active: Optional[bool] = None
    current_backend_branch_active: Optional[bool] = None
    activation_basis: Optional[str] = None
    expected_output_families: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceConfigParseResult:
    reference_config_file: str
    reference_base_dir: str
    nzsb: int
    nzst: int
    nzon: int
    uww: float
    ltstar_raw: float
    lbstar: float
    zmax: float
    depth: float
    rizero: float
    min_slope_angle_deg: float
    background_flux_offset: bool
    nper: int
    rainfall_duration_s: float
    cri_mps: List[float]
    capt_s: List[float]
    rainfall_mode: str
    rainfall_period_sources: List[Dict[str, Any]]
    period_source_map: Dict[str, Dict[str, Any]]
    alpha1: float
    beta1: float
    alpha2: float
    beta2: float
    kresis: float
    manning_global: float
    manning_source: str
    limitfr: float
    shallown: float
    debrisflowmanning: Optional[float]
    d50: float
    cvstar: float
    cvglacier: Optional[float]
    cvlandslide: Optional[float]
    coedepo: float
    cs: float
    dfs_manningbar_variant: str
    dfs_manningbar_variant_source: Optional[str]
    dfs_manningbar_variant_basis: Optional[str]
    dfs_dry_face_velocity_variant: str
    dfs_dry_face_velocity_variant_source: Optional[str]
    dfs_dry_face_velocity_variant_basis: Optional[str]
    dfs_artivis_variant: str
    dfs_artivis_variant_source: Optional[str]
    dfs_artivis_variant_basis: Optional[str]
    dfs_absubar_variant: str
    dfs_absubar_variant_source: Optional[str]
    dfs_absubar_variant_basis: Optional[str]
    dtmin: float
    dtmax: float
    dti: float
    dtd: float
    toldh: float
    toldhp: float
    simul: float
    tout: float
    wavemax: float
    zones: Dict[int, ZoneParamsParsed]
    file_inputs: Dict[str, NativeInputFileRef]
    flags: Dict[str, Any]
    switch_snapshot: EddaSwitchSnapshot
    extension_flags: Dict[str, Any]
    flag_closure: List[Dict[str, Any]]
    unsupported_flags: List[Dict[str, Any]]
    supported_fields: List[str]
    recognized_unsupported_fields: List[str]
    unrecognized_fields: List[str]
    audit_notes: List[str]
    reference_output_expectations: Dict[str, Any]
    dfs_infiltration_variant: str
    dfs_infiltration_variant_source: Optional[str]
    dfs_infiltration_variant_basis: Optional[str]
    dfs_face_flux_variant: str
    dfs_face_flux_variant_source: Optional[str]
    dfs_face_flux_variant_basis: Optional[str]
    dfs_failure_source_variant: str
    dfs_failure_source_variant_source: Optional[str]
    dfs_failure_source_variant_basis: Optional[str]
    dfs_failure_source_evidence: List[Dict[str, Any]]
    dfs_failure_source_topology_status: str
    inflow_denominator_variant: str
    inflow_denominator_variant_source: Optional[str]
    inflow_denominator_variant_basis: Optional[str]
    inflow_denominator_direction: Optional[int]
    inflow_denominator_fv_value: Optional[float]

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "reference_config_file": self.reference_config_file,
            "reference_base_dir": self.reference_base_dir,
            "supported_fields": self.supported_fields,
            "recognized_unsupported_fields": self.recognized_unsupported_fields,
            "unrecognized_fields": self.unrecognized_fields,
            "flags": self.flags,
            "switch_snapshot": self.switch_snapshot.to_dict(),
            "extension_flags": self.extension_flags,
            "flag_closure": self.flag_closure,
            "rainfall_mode": self.rainfall_mode,
            "rainfall_period_sources": self.rainfall_period_sources,
            "period_source_map": self.period_source_map,
            "manning_source": self.manning_source,
            "zmax": self.zmax,
            "file_inputs": {
                key: file_ref.to_dict() for key, file_ref in self.file_inputs.items()
            },
            "zone_ids": sorted(self.zones.keys()),
            "unsupported_flags": self.unsupported_flags,
            "audit_notes": self.audit_notes,
            "reference_output_expectations": self.reference_output_expectations,
            "dfs_infiltration_variant": self.dfs_infiltration_variant,
            "dfs_infiltration_variant_source": self.dfs_infiltration_variant_source,
            "dfs_infiltration_variant_basis": self.dfs_infiltration_variant_basis,
            "dfs_face_flux_variant": self.dfs_face_flux_variant,
            "dfs_face_flux_variant_source": self.dfs_face_flux_variant_source,
            "dfs_face_flux_variant_basis": self.dfs_face_flux_variant_basis,
            "dfs_failure_source_variant": self.dfs_failure_source_variant,
            "dfs_failure_source_variant_source": self.dfs_failure_source_variant_source,
            "dfs_failure_source_variant_basis": self.dfs_failure_source_variant_basis,
            "dfs_failure_source_evidence": self.dfs_failure_source_evidence,
            "dfs_failure_source_topology_status": self.dfs_failure_source_topology_status,
            "dfs_manningbar_variant": self.dfs_manningbar_variant,
            "dfs_manningbar_variant_source": self.dfs_manningbar_variant_source,
            "dfs_manningbar_variant_basis": self.dfs_manningbar_variant_basis,
            "dfs_dry_face_velocity_variant": self.dfs_dry_face_velocity_variant,
            "dfs_dry_face_velocity_variant_source": self.dfs_dry_face_velocity_variant_source,
            "dfs_dry_face_velocity_variant_basis": self.dfs_dry_face_velocity_variant_basis,
            "dfs_artivis_variant": self.dfs_artivis_variant,
            "dfs_artivis_variant_source": self.dfs_artivis_variant_source,
            "dfs_artivis_variant_basis": self.dfs_artivis_variant_basis,
            "dfs_absubar_variant": self.dfs_absubar_variant,
            "dfs_absubar_variant_source": self.dfs_absubar_variant_source,
            "dfs_absubar_variant_basis": self.dfs_absubar_variant_basis,
            "inflow_denominator_variant": self.inflow_denominator_variant,
            "inflow_denominator_variant_source": self.inflow_denominator_variant_source,
            "inflow_denominator_variant_basis": self.inflow_denominator_variant_basis,
            "inflow_denominator_direction": self.inflow_denominator_direction,
            "inflow_denominator_fv_value": self.inflow_denominator_fv_value,
        }


FILE_FAMILY_ALIASES = {
    "triggerslidefil": "triggerslide",
    "ltstarfil": "zfil",
}

SUPPORTED_FILE_FAMILIES = {
    "demfil": ("priority-0", "production-reachable"),
    "zonfil": ("priority-1", "production-reachable"),
    "slofil": ("priority-1", "production-reachable"),
    "zfil": ("priority-1", "partial"),
    "triggerslide": ("priority-0", "production-reachable"),
    "manningfil": ("priority-2", "production-reachable"),
    "rifil": ("priority-1", "conditional-production-reachable"),
}
RECOGNIZED_ONLY_FILE_FAMILIES = {
    "dirfil": ("priority-2", "recognized-only"),
    "depfil": ("recognized", "partial"),
    "rizerofil": ("recognized", "partial"),
    "roadfil": ("recognized", "recognized-only"),
    "catchmentfil": ("recognized", "recognized-only"),
    "mouthpointfil": ("recognized", "recognized-only"),
    "nxtfil": ("priority-3", "recognized-only"),
    "ndxfil": ("priority-3", "recognized-only"),
    "dscfil": ("priority-3", "recognized-only"),
    "wffil": ("priority-3", "recognized-only"),
    "folder": ("recognized", "recognized-only"),
    "suffix": ("recognized", "recognized-only"),
}

CASE_DISCOVERY_FAMILIES = {
    "inflow.txt": ("recognized", "partial"),
    "outflow.txt": ("recognized", "partial"),
    "hydrograph.txt": ("recognized", "partial"),
    "drainage.txt": ("recognized", "partial"),
    "swmm.txt": ("recognized", "recognized-only"),
}


UNSUPPORTED_FLAG_SPECS: Dict[str, Dict[str, str]] = {
    "skip_other_timesteps": {
        "current_status": "production-unsupported",
        "blocked_reason": "Legacy slope-failure timestep-skipping control is not implemented in the current production backend.",
        "status_basis": "The original initialization file exposes `lskip`, but the current backend has no equivalent output-throttling contract for this legacy slope-failure pathway.",
    },
    "use_analytic_fillable_porosity": {
        "current_status": "source-trace-blocked",
        "blocked_reason": "Visible original source proves parsing of `lany`, but no active runtime consumer was located in the current source-trace set.",
        "status_basis": "Do not expose or wire this option until an active original consumer or validated equivalent is identified.",
    },
    "estimate_positive_pressure_head": {
        "current_status": "source-trace-blocked",
        "blocked_reason": "Visible original source proves parsing of `llus`, but no active runtime consumer was located in the current source-trace set.",
        "status_basis": "Do not expose or wire this option until an active original consumer or validated equivalent is identified.",
    },
    "use_psi0_negative_inverse_alpha": {
        "current_status": "source-trace-blocked",
        "blocked_reason": "Visible original source proves parsing of `lps0`, but no active runtime consumer was located in the current source-trace set.",
        "status_basis": "Do not expose or wire this option until an active original consumer or validated equivalent is identified.",
    },
    "log_mass_balance_results": {
        "current_status": "metadata-parity-only",
        "blocked_reason": "Current backend emits structured JSON metadata instead of original `EDDALog.txt` mass-balance logging parity.",
        "status_basis": "The original flag is parseable, but current production evidence exists only through backend-native metadata files.",
    },
    "flow_direction_mode": {
        "current_status": "source-trace-blocked",
        "blocked_reason": "Visible original source proves parsing of `flowdir`, but no active consumer was located beyond DEM-derived connectivity setup.",
        "status_basis": "Current backend uses a fixed DEM-derived connectivity path; do not expose `gener/slope/hydro` as a real switch.",
    },
    "use_full_dynamic_wave": {
        "current_status": "fixed-status-only",
        "blocked_reason": "Current backend does not honor the original dynamic-wave mode switch as a configurable production toggle.",
        "status_basis": "Reference config parser records the flag, but current production runtime follows a fixed backend-selected solver path instead of switching between original EDDA run modes.",
    },
    "simulate_rainfall": {
        "current_status": "fixed-status-only",
        "blocked_reason": "Current backend treats rainfall as an input-driven fixed scientific path, not as an independent off/on runtime switch.",
        "status_basis": "Production behavior is determined by supplied rainfall inputs and source-selection logic rather than a separate run-mode gate.",
    },
    "simulate_infiltration": {
        "current_status": "fixed-status-only",
        "blocked_reason": "Current backend treats infiltration as part of the production scientific path instead of a safe standalone toggle.",
        "status_basis": "No evidence-backed independent contract exists for disabling infiltration without changing the scientific path.",
    },
    "simulate_inflow_hydrograph": {
        "current_status": "partial",
        "blocked_reason": "Current backend can now consume original `inflow.txt` hydrograph forcing for the DFS production path, but full original mass-balance/log parity is still incomplete.",
        "status_basis": "Original `inflowsimul` semantics are now wired into the FastAPI -> solver path through the original `inflow.txt` sidecar and DFS staging fields, while legacy reporting parity remains partial.",
    },
    "simulate_outflow_cell": {
        "current_status": "partial",
        "blocked_reason": "Current backend now consumes `outflow.txt` for selected-cell observation/export, but full original hydraulic parity is still incomplete.",
        "status_basis": "Current backend can load the sidecar-selected outflow cells and emit partial `OUTNQ_*` parity, but it still keeps generic edge outflow handling alongside the original sidecar path.",
    },
    "simulate_shallow_landslide": {
        "current_status": "fixed-status-only",
        "blocked_reason": "Current backend couples shallow-failure logic into the production path without a separate evidence-backed off/on contract.",
        "status_basis": "The original run-mode label exists, but current backend parity is only a fixed-path subset.",
    },
    "simulate_debris_flow": {
        "current_status": "partial-fixed-path",
        "blocked_reason": "Current backend runs a debris-flow production path, but does not expose the original branch-selection semantics as a safe independent switch.",
        "status_basis": "Do not market this as a toggle until original `debrissimul` parity is modeled safely.",
    },
    "simulate_erosion": {
        "current_status": "fixed-status-only",
        "blocked_reason": "Current backend erosion/deposition logic is part of the fixed production path rather than an independently validated runtime switch.",
        "status_basis": "The original flag exists, but current backend parity is only a fixed-path subset.",
    },
    "simulate_water_and_solid_separately": {
        "current_status": "partial-fixed-path",
        "blocked_reason": "Current backend does not expose a safe standalone contract for the original separate water/solid treatment mode.",
        "status_basis": "Partial runtime behavior exists, but the original switch semantics are not closed.",
    },
    "simulate_drainage_flow": {
        "current_status": "partial-default-off-experimental",
        "blocked_reason": "Stormdrain/dwsimul runtime is consumed only by the source-backed `EDDA_EXPERIMENT_STORMDRAIN=1` hook and remains default-off.",
        "status_basis": "Original `dwsimul` semantics are validated against the copied 20a stormdrain oracle; current production behavior is unchanged unless the experimental flag is set.",
    },
    "save_runoff_grids": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original runoff-grid export parity is not implemented in the current backend.",
        "status_basis": "Current backend-native output families do not provide original runoff-grid flag control.",
    },
    "save_fs_min_legacy": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit some FS-related outputs, but original legacy flag-controlled parity is incomplete.",
        "status_basis": "Treat as partial backend capability, not original export parity.",
    },
    "save_fs_depth_at_min": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original depth-at-minimum-FS output family is not implemented in the current backend.",
        "status_basis": "No current runtime export parity exists for this legacy flag.",
    },
    "save_fs_pore_pressure_at_min": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original pore-pressure-at-minimum-FS output family is not implemented in the current backend.",
        "status_basis": "No current runtime export parity exists for this legacy flag.",
    },
    "save_infiltration_rate": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original actual-infiltration-rate export family is not implemented in the current backend.",
        "status_basis": "Current backend computes infiltration-related state, but not under the original output-flag/export contract.",
    },
    "save_basal_flux": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original basal-flux export family is not implemented in the current backend.",
        "status_basis": "No current runtime export parity exists for this legacy flag.",
    },
    "save_deposit_distribution": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit deposition-related outputs, but not under the original legacy deposit-distribution flag contract.",
        "status_basis": "Treat as partial result support, not original flag parity.",
    },
    "save_pf": {
        "current_status": "production-unsupported",
        "blocked_reason": "Probability-of-failure export parity is not implemented in the current backend.",
        "status_basis": "No current runtime export parity exists for this legacy flag.",
    },
    "save_road_risk": {
        "current_status": "production-unsupported",
        "blocked_reason": "Road-risk export parity is not implemented in the current backend.",
        "status_basis": "The required road-risk runtime/output family is absent.",
    },
    "save_road_warning": {
        "current_status": "production-unsupported",
        "blocked_reason": "Road-warning export parity is not implemented in the current backend.",
        "status_basis": "The required warning-level runtime/output family is absent.",
    },
    "save_detached_trace": {
        "current_status": "production-unsupported",
        "blocked_reason": "Detached-material trace export parity is not implemented in the current backend.",
        "status_basis": "The required trace runtime/output family is absent.",
    },
    "pressure_head_fs_listing_flag": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original pressure-head / FS listing parity is not implemented in the current backend.",
        "status_basis": "Current backend does not emit the original listing family or `EDDALog` equivalent for this control.",
    },
    "slope_failure_output_count": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original slope-failure-specific output schedule count is not implemented in the current backend.",
        "status_basis": "Current backend has generic output timing, not the legacy slope-failure schedule contract.",
    },
    "slope_failure_output_times_s": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original slope-failure-specific output schedule list is not implemented in the current backend.",
        "status_basis": "Current backend has generic output timing, not the legacy slope-failure schedule contract.",
    },
    "save_fs_min_grid": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit FS-related outputs, but original whole-process `fsminsave` parity is incomplete.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_flow_depth": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit depth outputs, but not under the original `flowdepthsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_max_flow_depth": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit some maximum-depth outputs, but not under the original `maxflowdepthsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_flow_velocity": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit velocity outputs, but not under the original `fvsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_max_flow_velocity": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit some maximum-velocity outputs, but not under the original `maxfvsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_erosion_depth": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit erosion-related outputs, but not under the original `erodepthsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_deposition_depth": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit deposition-related outputs, but not under the original `debdepodepthsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_total_depth": {
        "current_status": "production-unsupported",
        "blocked_reason": "Original total-depth export parity is not implemented in the current backend.",
        "status_basis": "No current runtime export parity exists for the original `totaldepthsave` family.",
    },
    "save_volumetric_sediment_concentration": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit concentration outputs, but not under the original `cvsave` control contract.",
        "status_basis": "Treat as partial backend result support, not original flag parity.",
    },
    "save_outflow_process": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit original-style `OUTNQ_*` text exports from the selected-cell outflow observer, but full hydraulic parity with original outflow routing is still incomplete.",
        "status_basis": "Current result export path now adds partial original-style outflow-process export alongside backend-native GeoTIFF/NetCDF outputs.",
    },
    "save_hydrograph_cells": {
        "current_status": "partial",
        "blocked_reason": "Current backend can emit source-backed `HYDROGRAPH_*` monitored output, but only the zero-flow synthetic oracle has been validated so far.",
        "status_basis": "The parser records the flag and current backend can load `hydrograph.txt` monitored cells into an observer/export chain; broader non-zero hydrosave oracle coverage remains future work.",
    },
    "save_drainage_nodal_flow": {
        "current_status": "partial-default-off-experimental",
        "blocked_reason": "Drainage nodal-flow output parity is currently available only as experimental stormdrain hook diagnostics, not as a default production writer.",
        "status_basis": "Original `dwnodesave` writes `dw_nodal_flow.txt`; current hook emits comparable node diagnostics only when `EDDA_EXPERIMENT_STORMDRAIN=1` is enabled.",
    },
    "save_drainage_conduit_flow": {
        "current_status": "partial-default-off-experimental",
        "blocked_reason": "Drainage conduit-flow output parity is currently available only as experimental stormdrain hook diagnostics, not as a default production writer.",
        "status_basis": "Original `dwconduitsave` writes `dw_conduit_flow.txt`; current hook emits comparable conduit diagnostics only when `EDDA_EXPERIMENT_STORMDRAIN=1` is enabled.",
    },
}


def parse_floats(line: str) -> List[float]:
    return [float(token.replace("D", "E").replace("d", "e")) for token in FLOAT_RE.findall(line)]


def parse_bool_line(line: str) -> bool:
    token = line.strip().lower()
    if token.startswith("t") or token.startswith(".t"):
        return True
    if token.startswith("f") or token.startswith(".f"):
        return False
    raise ValueError(f"Cannot parse boolean from line: {line}")


def find_line_index(lines: List[str], prefix: str, start: int = 0, end: Optional[int] = None) -> int:
    prefix_l = prefix.lower()
    search_end = len(lines) if end is None else min(end, len(lines))
    for i in range(max(start, 0), search_end):
        line = lines[i]
        if line.lower().startswith(prefix_l):
            return i
    raise ValueError(f"Cannot find line starting with: {prefix}")


def find_optional_line_index(
    lines: List[str],
    prefix: str,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[int]:
    prefix_l = prefix.lower()
    search_end = len(lines) if end is None else min(end, len(lines))
    for i in range(max(start, 0), search_end):
        line = lines[i]
        if line.lower().startswith(prefix_l):
            return i
    return None


def parse_zone_layers(lines: List[str], zone_start_idx: int) -> Tuple[ZoneLayerParams, ZoneLayerParams]:
    numeric_rows: List[List[float]] = []
    i = zone_start_idx + 1
    while i < len(lines) and len(numeric_rows) < 2:
        vals = parse_floats(lines[i])
        if len(vals) >= 15:
            numeric_rows.append(vals)
        i += 1

    if len(numeric_rows) < 2:
        raise ValueError(f"Failed parsing zone rows near line {zone_start_idx + 1}")

    bottom_vals = numeric_rows[0]
    top_vals = numeric_rows[1]

    bottom = ZoneLayerParams(
        c=bottom_vals[0],
        phi=bottom_vals[2],
        phib=bottom_vals[4],
        gamma_s=bottom_vals[6],
        diffusivity=bottom_vals[7],
        k_sat=bottom_vals[8],
        theta_sat=bottom_vals[9],
        theta_res=bottom_vals[10],
        theta_ini=bottom_vals[11],
        porosity=bottom_vals[12],
        psi_f=bottom_vals[13],
        alpha=bottom_vals[14],
        kero=1e-6,
        ctao=10.0,
        cvero=None,
    )
    top = ZoneLayerParams(
        c=top_vals[0],
        phi=top_vals[2],
        phib=top_vals[4],
        gamma_s=top_vals[6],
        diffusivity=top_vals[7],
        k_sat=top_vals[8],
        theta_sat=top_vals[9],
        theta_res=top_vals[10],
        theta_ini=top_vals[11],
        porosity=top_vals[12],
        psi_f=top_vals[13],
        alpha=top_vals[14],
        kero=top_vals[15] if len(top_vals) > 15 else 1e-6,
        ctao=top_vals[16] if len(top_vals) > 16 else 10.0,
        cvero=top_vals[17] if len(top_vals) > 17 else None,
    )
    return bottom, top


def _normalize_relative_path(raw_path: str) -> str:
    return raw_path.strip().replace("\\", "/")


def _resolve_case_path(base_dir: Path, raw_path: str) -> str:
    normalized = _normalize_relative_path(raw_path)
    candidate = Path(normalized)
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / normalized).resolve())


def _looks_like_path(value: str) -> bool:
    token = value.strip()
    if not token:
        return False
    return any(sep in token for sep in ("/", "\\")) and "." in token


def _extract_file_family_key(line: str) -> Optional[str]:
    line_lower = line.lower()
    if (
        "file name" not in line_lower
        and "list of file name" not in line_lower
        and not line_lower.startswith("folder where")
        and "identification code" not in line_lower
    ):
        return None
    matches = FILE_KEY_RE.findall(line)
    if not matches:
        return None
    # Lines such as "List of file name(s) ... (rifil())" contain two
    # parenthesized groups. The original EDDA key is the final one, and
    # "rifil()" should normalize to "rifil" instead of the earlier "(s)".
    return matches[-1].strip().lower().strip("() ")


def _collect_path_lines(lines: List[str], start_idx: int) -> List[str]:
    values: List[str] = []
    idx = start_idx
    while idx < len(lines):
        candidate = lines[idx].strip()
        if not _looks_like_path(candidate):
            break
        values.append(candidate)
        idx += 1
    return values


def _parse_file_inputs(lines: List[str], base_dir: Path) -> Tuple[Dict[str, NativeInputFileRef], List[str], List[str]]:
    file_inputs: Dict[str, NativeInputFileRef] = {}
    recognized_families: List[str] = []
    unrecognized_families: List[str] = []

    for idx, line in enumerate(lines):
        key = _extract_file_family_key(line)
        if not key:
            continue

        raw_paths = _collect_path_lines(lines, idx + 1)
        key = FILE_FAMILY_ALIASES.get(key, key)
        if key in SUPPORTED_FILE_FAMILIES:
            priority, status = SUPPORTED_FILE_FAMILIES[key]
            recognized_families.append(key)
        elif key in RECOGNIZED_ONLY_FILE_FAMILIES:
            priority, status = RECOGNIZED_ONLY_FILE_FAMILIES[key]
            recognized_families.append(key)
        else:
            priority, status = "recognized", "unrecognized"
            unrecognized_families.append(key)

        resolved = [_resolve_case_path(base_dir, value) for value in raw_paths]
        exists = [Path(path).exists() for path in resolved]
        file_inputs[key] = NativeInputFileRef(
            family=key,
            raw_paths=raw_paths,
            resolved_paths=resolved,
            exists=exists,
            priority=priority,
            production_status=status,
            notes=None if raw_paths else "Label found but no subsequent path lines were detected.",
        )

    return file_inputs, sorted(set(recognized_families)), sorted(set(unrecognized_families))


def _build_rainfall_period_sources(
    cri_mps: List[float],
    capt_s: List[float],
    file_inputs: Dict[str, NativeInputFileRef],
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    rifil_ref = file_inputs.get("rifil")
    rifil_paths = rifil_ref.resolved_paths if rifil_ref else []
    rifil_exists = rifil_ref.exists if rifil_ref else []
    period_sources: List[Dict[str, Any]] = []
    period_source_map: Dict[str, Dict[str, Any]] = {}

    for idx, cri in enumerate(cri_mps):
        path = rifil_paths[idx] if idx < len(rifil_paths) else None
        exists = rifil_exists[idx] if idx < len(rifil_exists) else None
        entry = {
            "period_index": idx + 1,
            "capt_start_s": capt_s[idx] if idx < len(capt_s) else None,
            "capt_end_s": capt_s[idx + 1] if idx + 1 < len(capt_s) else None,
            "cri_mps": cri,
            "source": "rifil_grid" if cri < 0.0 else "uniform_cri",
            "rifil_path": path if cri < 0.0 else None,
            "rifil_exists": exists if cri < 0.0 else None,
        }
        period_sources.append(entry)
        period_source_map[str(idx + 1)] = {
            "source": entry["source"],
            "cri_mps": cri,
            "capt_start_s": entry["capt_start_s"],
            "capt_end_s": entry["capt_end_s"],
            "rifil_path": entry["rifil_path"],
            "rifil_exists": entry["rifil_exists"],
        }

    negative_count = sum(cri < 0.0 for cri in cri_mps)
    if negative_count == 0:
        rainfall_mode = "uniform_cri"
    elif negative_count == len(cri_mps):
        rainfall_mode = "raster_rifil"
    else:
        rainfall_mode = "mixed"

    return rainfall_mode, period_sources, period_source_map


def _determine_manning_source(file_inputs: Dict[str, NativeInputFileRef]) -> str:
    manning_ref = file_inputs.get("manningfil")
    if manning_ref and any(manning_ref.exists):
        return "raster_manningfil"
    return "global_initiation_manning"


def _discover_case_sidecar_inputs(base_dir: Path, file_inputs: Dict[str, NativeInputFileRef]) -> List[str]:
    discovered: List[str] = []
    dem_ref = file_inputs.get("demfil")
    dem_path = None
    if dem_ref and dem_ref.resolved_paths:
        dem_path = Path(dem_ref.resolved_paths[0])
    for family, (priority, status) in CASE_DISCOVERY_FAMILIES.items():
        path = base_dir / family
        if not path.exists():
            continue
        if family == "hydrograph.txt":
            notes = "Case sidecar file detected for monitored-cell hydrograph output."
        elif family == "inflow.txt":
            notes = "Case sidecar file detected for inflow hydrograph forcing; current backend can now map the active branch into DFS runtime forcing for supported production cases."
        elif family == "drainage.txt":
            notes = "Case stormdrain topology file detected; consumed only by the default-off EDDA_EXPERIMENT_STORMDRAIN runtime hook."
        elif family == "swmm.txt":
            notes = "Case SWMM source file detected for original getdwinput provenance; current hook consumes generated drainage.txt topology."
        else:
            notes = "Case sidecar file detected; current production backend does not consume it and existing use remains helper-only."
        file_inputs[family] = NativeInputFileRef(
            family=family,
            raw_paths=[family],
            resolved_paths=[str(path.resolve())],
            exists=[True],
            priority=priority,
            production_status=status,
            notes=notes,
            structure_summary=parse_case_sidecar(path, family=family, dem_file=dem_path),
        )
        discovered.append(family)
    return discovered


def _detect_dfs_infiltration_variant(base_dir: Path) -> Tuple[str, Optional[str], Optional[str]]:
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "tol_clipped_fhw",
            None,
            "No bundled `dfs.F90` was found in the case directory, so the native-input runtime keeps the existing production default `tol_clipped_fhw` staging variant.",
        )

    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "tol_clipped_fhw",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; the native-input runtime falls back to the existing production default `tol_clipped_fhw` staging variant.",
        )

    direct_variant = (
        "fhw(i)=fh(i)*(1-cv(i)/cvstar)" in text
        and "inflx(i)=tempri(i) +(tempinflowh(i)+fhw(i))/dt" in text
    )
    tol_variant = (
        "fhw(i)=fh(i)*(1-cv(i)/cvstar)+tempri(i)*dt+tempinflowh(i)" in text
        and "if (fhw(i)<tol) fhw(i)=0." in text
        and "inflx(i)=fhw(i)/dt" in text
    )

    if direct_variant:
        return (
            "direct_rain_plus_storage",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` stages infiltration with `fhw=fh*(1-cv/cvstar)` and `inflx=tempri+(tempinflowh+fhw)/dt`, which keeps rainfall forcing active before the thin-front `tol` depth is exceeded.",
        )

    if tol_variant:
        return (
            "tol_clipped_fhw",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` stages infiltration with `fhw=fh*(1-cv/cvstar)+tempri*dt+tempinflowh`, clips `fhw<tol` to zero, and uses `inflx=fhw/dt`.",
        )

    return (
        "tol_clipped_fhw",
        str(dfs_path.resolve()),
        "Bundled `dfs.F90` did not match a recognized infiltration staging signature; the native-input runtime falls back to the existing production default `tol_clipped_fhw` variant until a new signature is traced.",
    )


def _compact_fortran_source(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _strip_fortran_line_comments(text: str) -> str:
    """Drop `!` comments so inactive alternate branches do not match detectors."""
    lines: list[str] = []
    for line in text.splitlines():
        if "!" in line:
            line = line.split("!", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _normalize_fortran_active_source(text: str) -> str:
    """Lowercase, drop comments/continuations, and compact active Fortran statements."""
    logical_lines: list[str] = []
    for raw in _strip_fortran_line_comments(text).splitlines():
        # Fixed-form Fortran treats column-one C, *, and debug D lines as
        # comments.  Check the raw line before stripping whitespace so an
        # inactive alternate branch cannot satisfy a topology signature.
        first = raw[:1]
        second = raw[1:2]
        if first == "*" or (
            first.lower() in {"c", "d"} and (not second or second.isspace() or second in {"*", "!"})
        ):
            continue
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped[:1].lower() == "c" and (len(stripped) == 1 or stripped[1] in {" ", "\t"}):
            continue
        # A non-blank, non-zero fixed-form column six is a continuation
        # marker.  Join it before handling free-form `&` continuations.
        fixed_continuation = len(raw) >= 6 and raw[:5].isspace() and raw[5] not in {" ", "0"}
        if fixed_continuation:
            continuation_body = raw[6:].strip()
            if continuation_body and logical_lines:
                logical_lines[-1] = f"{logical_lines[-1]} {continuation_body}".strip()
            elif continuation_body:
                logical_lines.append(continuation_body)
            continue
        logical_lines.append(stripped)

    pending = ""
    statements: list[str] = []
    for stripped in logical_lines:
        if stripped.startswith("&"):
            stripped = stripped[1:].lstrip()
        pending = f"{pending} {stripped}".strip() if pending else stripped
        if pending.endswith("&"):
            pending = pending[:-1].rstrip()
            continue
        statements.append(pending)
        pending = ""
    if pending:
        statements.append(pending)
    return _compact_fortran_source("\n".join(statements)).replace("&", "")


def _detect_dfs_face_flux_variant(base_dir: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """Classify DFS face-flux averaging / thin-front gates from bundled `dfs.F90`.

    Recognized variants:
    - ``both_thin_weighted`` (BJ/NO.5): both-thin gate + depth/area-weighted
      ``hbar/cvbar/frhobar``.
    - ``arithmetic_mean_chamoli`` (Chamoli): both-thin gate + area-weighted
      ``hbar``, area-mean ``cvbar`` without depth, arithmetic ``frhobar``.
    - ``asymmetric_head_guard``: asymmetric thin-front gate + arithmetic averages.
    """
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "both_thin_weighted",
            None,
            "No bundled `dfs.F90` was found in the case directory, so the native-input runtime keeps the BJ production default `both_thin_weighted` face-flux variant.",
        )

    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "both_thin_weighted",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; the native-input runtime falls back to the BJ production default `both_thin_weighted` face-flux variant.",
        )

    compact = _compact_fortran_source(_strip_fortran_line_comments(text))
    both_thin_gate = "if(fhpredi(i)<=tol.and.fhpredi(nq)<=tol)then" in compact
    weighted_hbar = (
        "hbar=(fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))/(cellareacal(i)+cellareacal(nq))"
        in compact
    )
    depth_weighted_cvbar = (
        "cvbar=(parai*cellareacal(i)+paran*cellareacal(nq))/(fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))"
        in compact
    )
    area_mean_cvbar = (
        "cvbar=(parai*cellareacal(i)+paran*cellareacal(nq))/(cellareacal(i)+cellareacal(nq))" in compact
        and not depth_weighted_cvbar
    )
    depth_weighted_frhobar = (
        "frhobar=(frhopredi(i)*fhpredi(i)*cellareacal(i)+frhopredi(nq)*fhpredi(nq)*cellareacal(nq))/(fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))"
        in compact
    )
    arithmetic_frhobar = "frhobar=0.5*(frhopredi(i)+frhopredi(nq))" in compact

    # Chamoli: both-thin + weighted hbar + area-mean cvbar + arithmetic frhobar.
    if both_thin_gate and weighted_hbar and area_mean_cvbar and arithmetic_frhobar:
        return (
            "arithmetic_mean_chamoli",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` uses the Chamoli both-thin face gate with `cellareacal`-weighted `hbar`, "
            "area-mean `cvbar` without depth weighting, and arithmetic `frhobar=0.5*(ρi+ρnq)`.",
        )

    if both_thin_gate and weighted_hbar and depth_weighted_cvbar and depth_weighted_frhobar:
        return (
            "both_thin_weighted",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` skips a face only when both paired cells remain thinner than `tol`, uses `cellareacal`-weighted `hbar/cvbar/frhobar`, and emits face discharge with the NO.5/NO.8/Test31 width expression `celsiz*(sqrt(2)-1)`.",
        )

    asymmetric_variant = (
        "if((fhpredi(i)<=tol.and.hi>=hn).or.(fhpredi(nq)<=tol.and.hn>=hi))then" in compact
        and "hbar=0.5*(fhpredi(i)+fhpredi(nq))" in compact
        and arithmetic_frhobar
    )
    if asymmetric_variant:
        return (
            "asymmetric_head_guard",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` uses the EntireBanzigou-style asymmetric head guard for thin-front face gating and arithmetic `hbar/cvbar/frhobar` averaging.",
        )

    return (
        "both_thin_weighted",
        str(dfs_path.resolve()),
        "Bundled `dfs.F90` did not match a recognized face-flux signature; the native-input runtime falls back to the BJ production default `both_thin_weighted` variant until a new signature is traced.",
    )


def _detect_dfs_failure_source_variant(
    base_dir: Path,
) -> Tuple[str, Optional[str], Optional[str], List[Dict[str, Any]], str]:
    dfs_path = base_dir / "dfs.F90"
    main_path = base_dir / "edda main program.F90"
    if not main_path.exists():
        main_candidates = sorted(
            path
            for pattern in ("*main*program*.F90", "*main*program*.f90", "*edda*.F90", "*edda*.f90")
            for path in base_dir.glob(pattern)
            if path.is_file()
        )
        if main_candidates:
            main_path = main_candidates[0]
    evidence: List[Dict[str, Any]] = []
    if not dfs_path.exists():
        return (
            "",
            None,
            "No bundled `dfs.F90` was found; failure-source topology remains unknown.",
            evidence,
            "missing_source",
        )

    try:
        dfs_text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; failure-source topology remains unknown.",
            evidence,
            "unknown",
        )

    try:
        main_text = main_path.read_text(encoding="utf-8", errors="ignore") if main_path.exists() else ""
    except OSError:
        main_text = ""

    dfs_active = _normalize_fortran_active_source(dfs_text)
    main_active = _normalize_fortran_active_source(main_text)
    live_signature = "calldoublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)"
    unsfin_call = "callunsfin" in main_active
    tfail_gate = "if(tnow<=tfail(i).and.tnext>tfail(i))then" in dfs_active
    tempfsh_stage = "tempfsh(i)=fsdepth(i)" in dfs_active
    tempfsrho_stage = "tempfsrho(i)=(rhos-rhow)*cvstar+rhow" in dfs_active
    live_variant = live_signature in dfs_active
    precomputed_signatures = (
        unsfin_call
        and tfail_gate
        and tempfsh_stage
        and tempfsrho_stage
    )
    precomputed_variant = precomputed_signatures and not live_variant

    evidence.append(
        {
            "file": str(main_path.resolve()) if main_path.exists() else None,
            "active_statement": "call unsfin",
            "matched": unsfin_call,
        }
    )
    evidence.append(
        {
            "file": str(dfs_path.resolve()),
            "active_statement": "if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
            "matched": tfail_gate,
        }
    )
    evidence.append(
        {
            "file": str(dfs_path.resolve()),
            "active_statement": live_signature,
            "matched": live_variant,
        }
    )
    evidence.append(
        {
            "file": str(dfs_path.resolve()),
            "active_statement": "tempfsh(i)=fsdepth(i)",
            "matched": tempfsh_stage,
        }
    )
    evidence.append(
        {
            "file": str(dfs_path.resolve()),
            "active_statement": "tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
            "matched": tempfsrho_stage,
        }
    )

    if live_variant and precomputed_signatures:
        return (
            "",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` and the main program expose conflicting live `doublelayer` and precomputed `unsfin` signatures.",
            evidence,
            "conflict",
        )

    if precomputed_variant:
        return (
            "precomputed_unsfin_schedule",
            str(dfs_path.resolve()),
            "Active statements call `unsfin` before DFS and stage `tempfsh/tempfsrho` only when the timestep crosses precomputed `tfail`; the live `doublelayer` call is not active.",
            evidence,
            "recognized",
        )

    if live_variant:
        return (
            "live_doublelayer_in_dfs",
            str(dfs_path.resolve()),
            "Active `dfs.F90` statements keep the live `doublelayer` call inside the DFS loop.",
            evidence,
            "recognized",
        )

    return (
        "",
        str(dfs_path.resolve()),
        "Bundled failure-source staging did not match a recognized active `dfs/unsfin` signature.",
        evidence,
        "unknown",
    )


def _detect_dfs_manningbar_variant(base_dir: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """Distinguish BJ exponential Manning from Chamoli debrisflowmanning.

    Chamoli `dfs.F90:417-421` uses `manningbar=debrisflowmanning` when `cv>cvtol`
    during erosion staging, and the face-flux `cvbar>cvtol` branch is a no-op.
    BJ_HXL uses `manningbar=manning(i)*manningb*exp(manningm*cv(i))`.
    """
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "exponential_cv",
            None,
            "No bundled `dfs.F90` was found; Manning-bar staging keeps the BJ/HXL exponential-cv production default.",
        )
    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "exponential_cv",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; Manning-bar staging falls back to exponential-cv.",
        )
    compact = _compact_fortran_source(text)
    if "manningbar=debrisflowmanning" in compact:
        return (
            "debrisflowmanning_cvtol",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` assigns `manningbar=debrisflowmanning` when `cv>cvtol` in the erosion-rate branch "
            "(Chamoli `dfs.F90:417-421`); the face-flux `cvbar>cvtol` assignment is a no-op.",
        )
    if "manningbar=manning(i)*manningb*exp(manningm*cv(i))" in compact:
        return (
            "exponential_cv",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` applies the BJ/HXL `manningb*exp(manningm*cv)` correction when `cv>cvtol`.",
        )
    return (
        "exponential_cv",
        str(dfs_path.resolve()),
        "Bundled Manning-bar staging did not match a recognized signature; the runtime keeps the exponential-cv default.",
    )


def _detect_dfs_dry_face_velocity_variant(base_dir: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """Chamoli zeros predicted face velocity when the upstream cell is dry.

    Chamoli ``dfs.F90:736-737`` (after ``fvpredi=dv+fv``, before sign reversal):

        if (fvpredi(i,ii)<0 .and. fhpredi(nq)<=tol) fvpredi(i,ii)=0
        if (fvpredi(i,ii)>0 .and. fhpredi(i)<=tol) fvpredi(i,ii)=0

    BJ ``dfs.F90`` has no equivalent; predicted velocity is kept.
    """
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "keep_velocity_bj",
            None,
            "No bundled `dfs.F90` was found; dry-face velocity staging keeps the BJ production default `keep_velocity_bj`.",
        )
    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "keep_velocity_bj",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; dry-face velocity staging falls back to `keep_velocity_bj`.",
        )
    compact = _compact_fortran_source(_strip_fortran_line_comments(text))
    zero_from_dry_neighbor = "if(fvpredi(i,ii)<0.and.fhpredi(nq)<=tol)fvpredi(i,ii)=0" in compact
    zero_from_dry_self = "if(fvpredi(i,ii)>0.and.fhpredi(i)<=tol)fvpredi(i,ii)=0" in compact
    if zero_from_dry_neighbor and zero_from_dry_self:
        return (
            "zero_dry_face_chamoli",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` zeros `fvpredi` when the upstream cell is thinner than `tol` "
            "(Chamoli `dfs.F90:736-737`), after `fvpredi=dv+fv` and before the sign-reversal branch.",
        )
    return (
        "keep_velocity_bj",
        str(dfs_path.resolve()),
        "Bundled `dfs.F90` does not zero predicted face velocity on a dry upstream cell; "
        "the runtime keeps the BJ production default `keep_velocity_bj`.",
    )


def _detect_dfs_artivis_variant(base_dir: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """Distinguish BJ depth-ratio artificial viscosity from Chamoli velocity-ratio.

    Chamoli ``dfs.F90:730-732`` weights ``artivis`` by
    ``0.02*|Δv|/(|v_nq|+|v_i|+1)`` and divides the diagonal term by ``√2``.
    BJ uses ``0.02*|Δh|/(h_i+h_nq)`` on every direction.
    """
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "depth_ratio_bj",
            None,
            "No bundled `dfs.F90` was found; artificial-viscosity staging keeps the BJ production default `depth_ratio_bj`.",
        )
    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "depth_ratio_bj",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; artificial-viscosity staging falls back to `depth_ratio_bj`.",
        )
    compact = _compact_fortran_source(_strip_fortran_line_comments(text))
    velocity_ratio = (
        "0.02*abs((fv(nq,ii)-fv(i,ii))/(abs(fv(nq,ii))+abs(fv(i,ii))+1))*artivis" in compact
    )
    depth_ratio = "0.02*abs(fhpredi(i)-fhpredi(nq))/(fhpredi(i)+fhpredi(nq))*artivis" in compact
    if velocity_ratio:
        return (
            "velocity_ratio_chamoli",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` weights artificial viscosity by the face-velocity ratio "
            "`0.02*|Δv|/(|v_nq|+|v_i|+1)` and divides the diagonal `artivis` term by `√2` "
            "(Chamoli `dfs.F90:730-732`).",
        )
    if depth_ratio:
        return (
            "depth_ratio_bj",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` weights artificial viscosity by the depth ratio "
            "`0.02*|Δh|/(h_i+h_nq)` on every direction (BJ production default).",
        )
    return (
        "depth_ratio_bj",
        str(dfs_path.resolve()),
        "Bundled artificial-viscosity staging did not match a recognized signature; the runtime keeps `depth_ratio_bj`.",
    )


def _detect_dfs_absubar_variant(base_dir: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """Distinguish BJ max-component `absubar` from Chamoli signed-mean reconstruction.

    Chamoli ``dfs.F90:209-212``:

        vx=(fv(i,5)-fv(i,1))*0.5+...0.5*0.707...
        absubar(i)=(vx**2.+vy**2.)**0.5

    BJ reconstructs ``max(vorth,vcomp)`` from ``fvpredi2=0.5*(fv+fvpredi)``.
    """
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "max_component_bj",
            None,
            "No bundled `dfs.F90` was found; `absubar` staging keeps the BJ production default `max_component_bj`.",
        )
    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "max_component_bj",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; `absubar` staging falls back to `max_component_bj`.",
        )
    compact = _compact_fortran_source(_strip_fortran_line_comments(text))
    signed_mean = (
        "vx=(fv(i,5)-fv(i,1))*0.5" in compact
        and "0.5*0.707" in compact
        and "absubar(i)=(vx**2" in compact
    )
    if signed_mean:
        return (
            "signed_mean_chamoli",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` reconstructs `absubar` as a signed Cartesian speed from raw `fv` "
            "with literal `0.707` diagonals (Chamoli `dfs.F90:209-212`), not BJ `max(vorth,vcomp)`.",
        )
    return (
        "max_component_bj",
        str(dfs_path.resolve()),
        "Bundled `dfs.F90` does not use the Chamoli signed-mean `absubar` reconstruction; "
        "the runtime keeps the BJ production default `max_component_bj`.",
    )


def _detect_inflow_denominator_variant(
    base_dir: Path,
) -> Tuple[str, Optional[str], Optional[str], Optional[int], Optional[float]]:
    dfs_path = base_dir / "dfs.F90"
    if not dfs_path.exists():
        return (
            "CELLAREA",
            None,
            "No bundled `dfs.F90` was found; inflow staging keeps the existing area denominator.",
            None,
            None,
        )

    try:
        text = dfs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (
            "UNKNOWN_FAIL_CLOSED",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` could not be read cleanly; inflow denominator selection cannot be source-backed.",
            None,
            None,
        )

    compact = _compact_fortran_source(text)
    fv_match = re.search(r"fv\(i,4\)=([-+]?(?:\d+\.\d*|\d+|\.\d+)(?:[ed][-+]?\d+)?)", compact)
    has_celsiz_fv = (
        "tempinflowh(i)=inflowhq(k,j+1)*dt/celsiz/fv(i,4)" in compact
        or "tempinflowh(i)=((inflowht(k,j+1)-tnow)*inflowhq(k,j+1)+(tnext-inflowht(k,j+1))*inflowhq(k,j+2))/celsiz/fv(i,4)"
        in compact
    )
    if has_celsiz_fv and fv_match:
        fv_value = float(fv_match.group(1).replace("d", "e"))
        return (
            "CELSIZ_DIRECTIONAL_VELOCITY",
            str(dfs_path.resolve()),
            (
                "Bundled `dfs.F90` stages active `inflow.txt` with "
                "`tempinflowh = ... / celsiz / fv(i,4)` after assigning `fv(i,4)`; "
                "the runtime must use the traced directional velocity denominator."
            ),
            4,
            fv_value,
        )

    has_cellareacal = (
        "tempinflowh(i)=inflowhq(k,j+1)*dt/cellareacal(i)" in compact
        or "tempinflowh(i)=((inflowht(k,j+1)-tnow)*inflowhq(k,j+1)+(tnext-inflowht(k,j+1))*inflowhq(k,j+2))/cellareacal(i)"
        in compact
    )
    if has_cellareacal:
        return (
            "CELLAREACAL",
            str(dfs_path.resolve()),
            (
                "Bundled `dfs.F90` stages active `inflow.txt` with `cellareacal(i)`. "
                "Current runtime uses the equivalent cell-area denominator while ARF/WRF runtime consumers remain inactive."
            ),
            None,
            None,
        )

    has_cellarea = "tempinflowh(i)=inflowhq(k,j+1)*dt/cellarea" in compact
    if has_cellarea:
        return (
            "CELLAREA",
            str(dfs_path.resolve()),
            "Bundled `dfs.F90` stages active `inflow.txt` with the scalar `cellarea` denominator.",
            None,
            None,
        )

    return (
        "CELLAREA",
        str(dfs_path.resolve()),
        "Bundled `dfs.F90` did not match a traced inflow denominator signature; the runtime keeps the existing area denominator.",
        None,
        None,
    )


def _parse_optional_bool(
    lines: List[str],
    prefix: str,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[bool]:
    idx = find_optional_line_index(lines, prefix, start=start, end=end)
    if idx is None or idx + 1 >= len(lines):
        return None
    try:
        return parse_bool_line(lines[idx + 1])
    except ValueError:
        return None


def _parse_optional_bool_any(
    lines: List[str],
    prefixes: List[str],
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[bool]:
    for prefix in prefixes:
        value = _parse_optional_bool(lines, prefix, start=start, end=end)
        if value is not None:
            return value
    return None


def _parse_optional_int(
    lines: List[str],
    prefix: str,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[int]:
    idx = find_optional_line_index(lines, prefix, start=start, end=end)
    if idx is None or idx + 1 >= len(lines):
        return None
    values = parse_floats(lines[idx + 1])
    if not values:
        return None
    return int(values[0])


def _parse_optional_float_list(
    lines: List[str],
    prefix: str,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[List[float]]:
    idx = find_optional_line_index(lines, prefix, start=start, end=end)
    if idx is None or idx + 1 >= len(lines):
        return None
    values = parse_floats(lines[idx + 1])
    return values or None


def _parse_optional_string(
    lines: List[str],
    prefix: str,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[str]:
    idx = find_optional_line_index(lines, prefix, start=start, end=end)
    if idx is None or idx + 1 >= len(lines):
        return None
    token = lines[idx + 1].strip()
    return token or None


def _build_unsupported_flags(flags: Dict[str, Any]) -> List[Dict[str, Any]]:
    unsupported_flags: List[Dict[str, Any]] = []
    for spec in EDDA_SWITCH_REGISTRY:
        value = flags.get(spec.key)
        if value is None:
            continue
        if spec.status in {"production_consumed", "config_fallback_consumed"}:
            continue
        unsupported_flags.append(
            {
                "flag": spec.key,
                "configured_value": value,
                "current_status": spec.status,
                "blocked_reason": spec.status_reason,
                "status_basis": spec.fortran_runtime_consumer,
            }
        )
    return unsupported_flags


def _build_flag_closure(flags: Dict[str, Any]) -> List[Dict[str, Any]]:
    closure: List[Dict[str, Any]] = []
    for spec in EDDA_SWITCH_REGISTRY:
        value = flags.get(spec.key)
        if value is None:
            continue
        closure.append(
            {
                "flag": spec.key,
                "canonical_key": spec.taichi_config_path,
                "configured_value": value,
                "current_status": spec.status,
                "blocked_reason": spec.status_reason,
                "status_basis": spec.fortran_runtime_consumer,
                "source_index": spec.source_index,
                "consumption_stage": spec.consumption_stage,
                "dependencies": list(spec.dependencies),
                "affected_output_families": list(spec.affected_output_families),
            }
        )
    return closure


def _build_reference_output_expectations(flags: Dict[str, Any]) -> Dict[str, Any]:
    grid_flag_map = {
        "save_fs_min_legacy": "fs_min_legacy_*",
        "save_fs_depth_at_min": "depth_at_fs_min_*",
        "save_fs_pore_pressure_at_min": "p_at_fs_min_*",
        "save_runoff_grids": "runoff_*",
        "save_infiltration_rate": "actual_infiltration_rate_*",
        "save_basal_flux": "basal_flux_*",
        "save_deposit_distribution": "deposit_distribution_*",
        "save_pf": "pf_at_fs_min_*",
        "save_road_risk": "road_risk_*",
        "save_road_warning": "road_warning_*",
        "save_detached_trace": "detached_trace_*",
        "save_fs_min_grid": "fs_min_*",
        "save_flow_depth": "Flow_depth_*",
        "save_max_flow_depth": "Max_flow_depth_*",
        "save_flow_velocity": "Flow_velocity_*",
        "save_max_flow_velocity": "Max_flow_velocity_*",
        "save_erosion_depth": "Erosion_depth_*",
        "save_deposition_depth": "Deposit_depth_*",
        "save_total_depth": "Total_depth_*",
        "save_max_solid_depth": "Maxsoliddepth_*",
        "save_volumetric_sediment_concentration": "Volumetric_sediment_concentration_*",
    }
    process_flag_map = {
        "save_outflow_process": "OUTNQ_*",
        "save_hydrograph_cells": "HYDROGRAPH_*",
    }
    expected_grid_families = [
        family for flag, family in grid_flag_map.items() if flags.get(flag) is True
    ]
    expected_process_families = [
        family for flag, family in process_flag_map.items() if flags.get(flag) is True
    ]
    expected_log_artifacts = ["EDDALog.txt"]
    if flags.get("pressure_head_fs_listing_flag") not in (None, 0):
        expected_log_artifacts.append("EDDALog pressure-head / FS listing sections")
    if flags.get("log_mass_balance_results") is True:
        expected_log_artifacts.append("EDDALog mass-balance sections")
    output_timing = {family: "periodic_output" for family in expected_grid_families}
    for family in expected_process_families:
        output_timing[family] = "end_of_run_only"
    output_timing["EDDALog.txt"] = "initialization_and_end_of_run"
    if "EDDALog pressure-head / FS listing sections" in expected_log_artifacts:
        output_timing["EDDALog pressure-head / FS listing sections"] = "end_of_run_only"
    if "EDDALog mass-balance sections" in expected_log_artifacts:
        output_timing["EDDALog mass-balance sections"] = "end_of_run_only"
    return {
        "expected_grid_families": expected_grid_families,
        "expected_process_families": expected_process_families,
        "expected_log_artifacts": expected_log_artifacts,
        "expected_output_families": expected_grid_families + expected_process_families,
        "output_timing": output_timing,
    }


def _annotate_reference_case_activation(
    file_inputs: Dict[str, NativeInputFileRef],
    *,
    flags: Dict[str, Any],
    nzon: int,
    ltstar_raw: float,
    zmax: float,
    depth: float,
    rizero: float,
    rainfall_mode: str,
    manning_source: str,
) -> None:
    def _exists(family: str) -> bool:
        ref = file_inputs.get(family)
        return bool(ref and any(ref.exists))

    def _set(
        family: str,
        *,
        original_branch_active: Optional[bool],
        current_backend_branch_active: Optional[bool],
        activation_basis: str,
        expected_output_families: Optional[List[str]] = None,
    ) -> None:
        ref = file_inputs.get(family)
        if ref is None:
            return
        ref.original_branch_active = original_branch_active
        ref.current_backend_branch_active = current_backend_branch_active
        ref.activation_basis = activation_basis
        if expected_output_families is not None:
            ref.expected_output_families = expected_output_families

    aligned_basis = (
        "This family is part of the visible original case path and is also "
        "consumed by the current production backend."
    )
    _set("demfil", original_branch_active=True, current_backend_branch_active=True, activation_basis=aligned_basis)
    _set("slofil", original_branch_active=True, current_backend_branch_active=True, activation_basis=aligned_basis)
    _set(
        "triggerslide",
        original_branch_active=True,
        current_backend_branch_active=True,
        activation_basis=(
            "Original EDDA always reads `triggerslidefil` in `edda main program.F90` and injects it once "
            "inside `dfs.F90` when `slide1==1 .and. tnow>0`, independent of `fssimul`."
        ),
    )
    zonfil_active = nzon > 1
    _set(
        "zonfil",
        original_branch_active=zonfil_active,
        current_backend_branch_active=zonfil_active,
        activation_basis=(
            "Original EDDA reads `zonfil` only when `nzon > 1`; for `nzon == 1` it assigns every active cell to zone 1. "
            "The current backend follows the same activation condition."
        ),
    )
    _set(
        "manningfil",
        original_branch_active=manning_source == "raster_manningfil",
        current_backend_branch_active=manning_source == "raster_manningfil",
        activation_basis="Original and current backends only activate the spatial Manning branch when a usable raster exists and the scalar global Manning branch is not active.",
    )
    _set(
        "rifil",
        original_branch_active=rainfall_mode in {"raster_rifil", "mixed"},
        current_backend_branch_active=rainfall_mode in {"raster_rifil", "mixed"},
        activation_basis="Original and current backends activate `rifil(j)` only for rainfall periods with negative `cri(j)` values.",
    )
    _set(
        "depfil",
        original_branch_active=depth < 0,
        current_backend_branch_active=(depth < 0 and _exists("depfil")),
        activation_basis=(
            "Original EDDA activates `depfil` only when scalar `depth < 0`; "
            f"this reference config uses depth={depth}, so the original branch is {'active' if depth < 0 else 'inactive'}. "
            "Current backend can seed the same per-cell initial water-table-depth condition only for that original branch."
        ),
    )
    _set(
        "rizerofil",
        original_branch_active=rizero < 0,
        current_backend_branch_active=(rizero < 0 and _exists("rizerofil")),
        activation_basis=(
            "Original EDDA activates `rizerofil` only when scalar `rizero < 0`; "
            f"this reference config uses rizero={rizero}, so the original branch is {'active' if rizero < 0 else 'inactive'}. "
            "Current backend can seed the same per-cell initial/background infiltration field only for that original branch."
        ),
    )
    _set(
        "zfil",
        original_branch_active=(ltstar_raw < 0) or (zmax < 0),
        current_backend_branch_active=ltstar_raw < 0,
        activation_basis=(
            "Original EDDA uses the file declared as `zfil`/`ltstarfil` for upper-layer soil thickness "
            "when scalar `ltstar < 0`, and reuses that same file as the `zmax` grid only when scalar "
            f"`zmax < 0`. The current backend only wires the ltstar branch via `ltstar_raw < 0`; this "
            f"reference config has ltstar={ltstar_raw} and zmax={zmax}."
        ),
    )
    _set(
        "dirfil",
        original_branch_active=None,
        current_backend_branch_active=False,
        activation_basis="`dirfil` is declared and `flowdir` is parsed, but no active original consumer beyond DEM-derived connectivity was located in the visible case path; current backend remains fixed to DEM-derived connectivity.",
    )
    for family in ("nxtfil", "ndxfil", "dscfil", "wffil", "roadfil", "catchmentfil", "mouthpointfil"):
        _set(
            family,
            original_branch_active=None,
            current_backend_branch_active=False,
            activation_basis="This family was declared for provenance, but no active original or current production consumer was located on the visible case path.",
        )
    _set(
        "outflow.txt",
        original_branch_active=flags.get("simulate_outflow_cell") is True,
        current_backend_branch_active=(flags.get("simulate_outflow_cell") is True and _exists("outflow.txt")),
        activation_basis="Original EDDA activates the fixed `outflow.txt` sidecar only when `simulate_outflow_cell = T`; current backend now consumes the sidecar for selected-cell outflow observation/export, but full hydraulic parity remains partial.",
        expected_output_families=["OUTNQ_*"] if flags.get("save_outflow_process") is True else [],
    )
    _set(
        "hydrograph.txt",
        original_branch_active=flags.get("save_hydrograph_cells") is True,
        current_backend_branch_active=(flags.get("save_hydrograph_cells") is True and _exists("hydrograph.txt")),
        activation_basis="Original EDDA activates the fixed `hydrograph.txt` sidecar only when `save_hydrograph_cells = T`; current backend consumes the same sidecar for monitored-output HYDROGRAPH export when present, with non-zero oracle coverage still partial.",
        expected_output_families=["HYDROGRAPH_*"] if flags.get("save_hydrograph_cells") is True else [],
    )
    _set(
        "inflow.txt",
        original_branch_active=flags.get("simulate_inflow_hydrograph") is True,
        current_backend_branch_active=flags.get("simulate_inflow_hydrograph") is True,
        activation_basis="Original EDDA activates the fixed `inflow.txt` sidecar only when `simulate_inflow_hydrograph = T`; current backend now maps the same flag + sidecar pair into DFS inflow forcing for supported production runs.",
    )
    _set(
        "drainage.txt",
        original_branch_active=flags.get("simulate_drainage_flow") is True,
        current_backend_branch_active=(
            flags.get("simulate_drainage_flow") is True
            and os.environ.get("EDDA_EXPERIMENT_STORMDRAIN", "").strip() == "1"
            and _exists("drainage.txt")
        ),
        activation_basis=(
            "Original EDDA activates `getdwinput`/`readdrainage`/`dwflow` only when `dwsimul = T`. "
            "Current backend consumes generated `drainage.txt` only behind `EDDA_EXPERIMENT_STORMDRAIN=1`."
        ),
        expected_output_families=[
            family
            for family, active in (
                ("dw_nodal_flow.txt", flags.get("save_drainage_nodal_flow") is True),
                ("dw_conduit_flow.txt", flags.get("save_drainage_conduit_flow") is True),
            )
            if active
        ],
    )


def parse_reference_config_file(reference_config_file: str, reference_base_dir: Optional[str] = None) -> ReferenceConfigParseResult:
    reference_path = Path(reference_config_file)
    if not reference_path.exists():
        raise FileNotFoundError(f"Reference config file not found: {reference_config_file}")

    base_dir = Path(reference_base_dir) if reference_base_dir else reference_path.parent
    with reference_path.open("r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip() for line in handle if line.strip()]

    idx_nz = find_line_index(lines, "nzsb, nzst, mmax, nper")
    vals_nz = parse_floats(lines[idx_nz + 1])
    nzsb = int(vals_nz[0])
    nzst = int(vals_nz[1])
    nper = int(vals_nz[3])
    uww = vals_nz[5]
    rainfall_duration_s = vals_nz[6]
    nzon = int(vals_nz[7])

    idx_lt = find_line_index(lines, "ltstar, lbstar, zmax,   depth")
    vals_lt = parse_floats(lines[idx_lt + 1])
    ltstar_raw = vals_lt[0]
    lbstar = vals_lt[1]
    zmax = vals_lt[2]
    depth = vals_lt[3]
    rizero = vals_lt[4]
    min_slope_angle_deg = vals_lt[5]

    idx_cri = find_line_index(lines, "cri(1), cri(2)")
    cri_mps = parse_floats(lines[idx_cri + 1])
    idx_capt = find_line_index(lines, "capt(1), capt(2)")
    capt_s = parse_floats(lines[idx_capt + 1])

    idx_bkgrof = find_line_index(lines, "Add steady background flux to transient infiltration rate")
    background_flux_offset = parse_bool_line(lines[idx_bkgrof + 1])

    idx_ab = find_line_index(lines, "alpha1 beta1 alpha2")
    vals_ab = parse_floats(lines[idx_ab + 1])
    alpha1, beta1, alpha2, beta2, kresis, manning_global, limitfr = vals_ab[:7]
    heading_ab = lines[idx_ab].lower()
    eighth = vals_ab[7] if len(vals_ab) > 7 else None
    if "debrisflowmanning" in heading_ab:
        debrisflowmanning = eighth
        shallown = 0.2
    else:
        debrisflowmanning = None
        shallown = eighth if eighth is not None else 0.2

    idx_cv = find_line_index(lines, "d50    cvstar")
    vals_cv = parse_floats(lines[idx_cv + 1])
    heading_cv = lines[idx_cv].lower()
    if "cvglacier" in heading_cv or "cvlandslide" in heading_cv:
        if len(vals_cv) < 6:
            raise ValueError(
                "Chamoli-style sediment line `d50 cvstar cvglacier cvlandslide coedepo cs` "
                f"requires 6 values, got {len(vals_cv)}."
            )
        d50, cvstar, cvglacier, cvlandslide, coedepo, cs = vals_cv[:6]
    else:
        d50, cvstar, coedepo, cs = vals_cv[:4]
        cvglacier = None
        cvlandslide = None

    idx_dt = find_line_index(lines, "dtmin(s)   dtmax(s)")
    vals_dt = parse_floats(lines[idx_dt + 1])
    dtmin, dtmax, dti, dtd, simul, tout, toldh, toldhp, wavemax = vals_dt[:9]

    zones: Dict[int, ZoneParamsParsed] = {}
    for idx, line in enumerate(lines):
        match = ZONE_RE.match(line)
        if not match:
            continue
        zone_id = int(match.group(1))
        bottom, top = parse_zone_layers(lines, idx)
        zones[zone_id] = ZoneParamsParsed(zone_id=zone_id, bottom=bottom, top=top)

    if not zones:
        raise ValueError("No zone definitions parsed from edda_in.txt")

    file_inputs, recognized_file_families, unrecognized_file_families = _parse_file_inputs(lines, base_dir)
    if "rifil" in file_inputs and len(file_inputs["rifil"].raw_paths) > len(cri_mps):
        rifil_ref = file_inputs["rifil"]
        rifil_ref.raw_paths = rifil_ref.raw_paths[: len(cri_mps)]
        rifil_ref.resolved_paths = rifil_ref.resolved_paths[: len(cri_mps)]
        rifil_ref.exists = rifil_ref.exists[: len(cri_mps)]
    recognized_file_families.extend(_discover_case_sidecar_inputs(base_dir, file_inputs))
    dfs_infiltration_variant, dfs_infiltration_variant_source, dfs_infiltration_variant_basis = _detect_dfs_infiltration_variant(base_dir)
    dfs_face_flux_variant, dfs_face_flux_variant_source, dfs_face_flux_variant_basis = _detect_dfs_face_flux_variant(base_dir)
    (
        dfs_failure_source_variant,
        dfs_failure_source_variant_source,
        dfs_failure_source_variant_basis,
        dfs_failure_source_evidence,
        dfs_failure_source_topology_status,
    ) = _detect_dfs_failure_source_variant(base_dir)
    dfs_manningbar_variant, dfs_manningbar_variant_source, dfs_manningbar_variant_basis = _detect_dfs_manningbar_variant(base_dir)
    dfs_dry_face_velocity_variant, dfs_dry_face_velocity_variant_source, dfs_dry_face_velocity_variant_basis = (
        _detect_dfs_dry_face_velocity_variant(base_dir)
    )
    dfs_artivis_variant, dfs_artivis_variant_source, dfs_artivis_variant_basis = _detect_dfs_artivis_variant(base_dir)
    dfs_absubar_variant, dfs_absubar_variant_source, dfs_absubar_variant_basis = _detect_dfs_absubar_variant(base_dir)
    if debrisflowmanning is not None:
        dfs_manningbar_variant = "debrisflowmanning_cvtol"
        dfs_manningbar_variant_source = str(reference_path.resolve())
        dfs_manningbar_variant_basis = (
            "edda_in heading includes `debrisflowmanning`; Chamoli dfs.F90:417-421 "
            "assigns `manningbar=debrisflowmanning` when `cv>cvtol`."
        )
    (
        inflow_denominator_variant,
        inflow_denominator_variant_source,
        inflow_denominator_variant_basis,
        inflow_denominator_direction,
        inflow_denominator_fv_value,
    ) = _detect_inflow_denominator_variant(base_dir)
    rainfall_mode, rainfall_period_sources, period_source_map = _build_rainfall_period_sources(
        cri_mps,
        capt_s,
        file_inputs,
    )
    manning_source = _determine_manning_source(file_inputs)
    legacy_section_end = idx_ab
    whole_process_section_start = idx_dt

    flags = {
        "skip_other_timesteps": _parse_optional_bool(
            lines,
            "Skip other timesteps? Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "use_analytic_fillable_porosity": _parse_optional_bool(
            lines,
            "Use analytic solution for fillable porosity?",
            end=legacy_section_end,
        ),
        "estimate_positive_pressure_head": _parse_optional_bool(
            lines,
            "Estimate positive pressure head in rising water table zone",
            end=legacy_section_end,
        ),
        "use_psi0_negative_inverse_alpha": _parse_optional_bool(
            lines,
            "Use psi0=-1/alpha?",
            end=legacy_section_end,
        ),
        "log_mass_balance_results": _parse_optional_bool(
            lines,
            "Log mass balance results?",
            end=legacy_section_end,
        ),
        "flow_direction_mode": _parse_optional_string(
            lines,
            "Flow direction (enter \"gener\", \"slope\", or \"hydro\")",
            end=legacy_section_end,
        ),
        "use_full_dynamic_wave": _parse_optional_bool(
            lines,
            "Using the full dynamic wave equation to compute the velocity?",
            start=whole_process_section_start,
        ),
        "simulate_rainfall": _parse_optional_bool_any(
            lines,
            [
                "Simulte rainfall? Enter T (.true.) or F (.false.)",
                "Simulate rainfall? Enter T (.true.) or F (.false.)",
            ],
            start=whole_process_section_start,
        ),
        "simulate_infiltration": _parse_optional_bool_any(
            lines,
            [
                "Simulte infiltration? Enter T (.true.) or F (.false.)",
                "Simulate infiltration? Enter T (.true.) or F (.false.)",
            ],
            start=whole_process_section_start,
        ),
        "simulate_inflow_hydrograph": _parse_optional_bool(
            lines,
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "simulate_outflow_cell": _parse_optional_bool(
            lines,
            "Simulate outflow cell? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "simulate_shallow_landslide": _parse_optional_bool(
            lines,
            "Simulate shallow landslide? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "simulate_debris_flow": _parse_optional_bool(
            lines,
            "Simulate debris flow? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "simulate_erosion": _parse_optional_bool_any(
            lines,
            [
                "Simulte erosion? Enter T (.true.) or F (.false.)",
                "Simulate erosion? Enter T (.true.) or F (.false.)",
            ],
            start=whole_process_section_start,
        ),
        "simulate_water_and_solid_separately": _parse_optional_bool_any(
            lines,
            [
                "Simulte simulate the water and solid material seperately? Enter T (.true.) or F (.false.)",
                "Simulate simulate the water and solid material seperately? Enter T (.true.) or F (.false.)",
            ],
            start=whole_process_section_start,
        ),
        "simulate_drainage_flow": _parse_optional_bool_any(
            lines,
            [
                "Simulte drainage flow? Enter T (.true.) or F (.false.)",
                "Simulate drainage flow? Enter T (.true.) or F (.false.)",
            ],
            start=whole_process_section_start,
        ),
        "simulate_barrier": _parse_optional_bool_any(
            lines,
            [
                "Simulte barrier? Enter T (.true.) or F (.false.)",
                "Simulate barrier? Enter T (.true.) or F (.false.)",
            ],
            start=whole_process_section_start,
        ),
        "save_runoff_grids": _parse_optional_bool(
            lines,
            "Save grid files of runoff? Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_fs_min_legacy": _parse_optional_bool(
            lines,
            "Save grid of minimum factor of safety? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_fs_depth_at_min": _parse_optional_bool(
            lines,
            "Save grid of depth of minimum factor of safety? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_fs_pore_pressure_at_min": _parse_optional_bool(
            lines,
            "Save grid of pore pressure at depth of minimum factor of safety? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_infiltration_rate": _parse_optional_bool(
            lines,
            "Save grid files of actual infiltration rate? Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_basal_flux": _parse_optional_bool(
            lines,
            "Save grid files of unsaturated zone basal flux? Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_deposit_distribution": _parse_optional_bool(
            lines,
            "Save grid files of the deposit distribution? Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_pf": _parse_optional_bool(
            lines,
            "Save grid of probability of failure (pf) at depth of minimum factor of safety? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_road_risk": _parse_optional_bool(
            lines,
            "Save grid of risk imposed by the slope failure to the road? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_road_warning": _parse_optional_bool(
            lines,
            "Save grid of warning level along the road? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "save_detached_trace": _parse_optional_bool(
            lines,
            "Save grid of trace of the detached material and debris? Enter Enter T (.true.) or F (.false.)",
            end=legacy_section_end,
        ),
        "pressure_head_fs_listing_flag": _parse_optional_int(
            lines,
            "Save listing of pressure head and factor of safety",
            end=legacy_section_end,
        ),
        "slope_failure_output_count": _parse_optional_int(
            lines,
            "Number of times to save output grids of slope failures",
            end=legacy_section_end,
        ),
        "slope_failure_output_times_s": _parse_optional_float_list(
            lines,
            "Times of output grids",
            end=legacy_section_end,
        ),
        "save_fs_min_grid": _parse_optional_bool(
            lines,
            "Save grid of minimum factor of safety? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_flow_depth": _parse_optional_bool(
            lines,
            "Save grid of flow depth? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_max_flow_depth": _parse_optional_bool(
            lines,
            "Save grid of maximum flow depth? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_flow_velocity": _parse_optional_bool(
            lines,
            "Save grid of flow velocity? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_max_flow_velocity": _parse_optional_bool(
            lines,
            "Save grid of maximum flow velocity? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_erosion_depth": _parse_optional_bool(
            lines,
            "Save grid of Erosion depth? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_deposition_depth": _parse_optional_bool(
            lines,
            "Save grid of deposition depth when simulating water and soil deposition seperately? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_total_depth": _parse_optional_bool(
            lines,
            "Save grid of total depth of flow depth and deposit depth? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_max_solid_depth": _parse_optional_bool(
            lines,
            "Save grid of maximum depth of solid material? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_volumetric_sediment_concentration": _parse_optional_bool(
            lines,
            "Save grid of volumetric sediment concentration? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_outflow_process": _parse_optional_bool(
            lines,
            "Save outflow process? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_drainage_nodal_flow": _parse_optional_bool(
            lines,
            "Save drainage nodal flow? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_drainage_conduit_flow": _parse_optional_bool(
            lines,
            "Save drainage conduit flow? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
        "save_hydrograph_cells": _parse_optional_bool(
            lines,
            "Save hydrograph of specified cells? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
    }
    extension_flags = {
        "save_hydrograph_cells": flags.pop("save_hydrograph_cells"),
        "simulate_buildings": _parse_optional_bool(
            lines,
            "Simulate buildings with ARF and WRF? Enter T (.true.) or F (.false.)",
            start=whole_process_section_start,
        ),
    }
    flags["background_flux_offset"] = background_flux_offset
    switch_snapshot = build_switch_snapshot(
        flags,
        source=str(reference_path.resolve()),
    )
    flags = dict(switch_snapshot.values)
    all_flags = {
        **flags,
        **{key: value for key, value in extension_flags.items() if value is not None},
    }
    flag_closure = _build_flag_closure(flags)
    unsupported_flags = _build_unsupported_flags(flags)
    reference_output_expectations = _build_reference_output_expectations(all_flags)
    _annotate_reference_case_activation(
        file_inputs,
        flags=all_flags,
        nzon=nzon,
        ltstar_raw=ltstar_raw,
        zmax=zmax,
        depth=depth,
        rizero=rizero,
        rainfall_mode=rainfall_mode,
        manning_source=manning_source,
    )

    supported_fields = {
        "alpha1",
        "alpha2",
        "background_flux_offset",
        "beta1",
        "beta2",
        "capt",
        "coedepo",
        "cri",
        "cs",
        "d50",
        "demfil",
        "triggerslide",
        "depth",
        "dtmax",
        "dtmin",
        "dtd",
        "dti",
        "kresis",
        "lbstar",
        "limitfr",
        "ltstar",
        "manning_global",
        "manningfil",
        "rifil",
        "min_slope_angle_deg",
        "nzsb",
        "nzst",
        "rizero",
        "shallown",
        "simul",
        "slofil",
        "toldh",
        "toldhp",
        "tout",
        "uww",
        "wavemax",
        "zfil",
        "zonfil",
        "zones",
    }
    if debrisflowmanning is not None:
        supported_fields.add("debrisflowmanning")
    if cvlandslide is not None:
        supported_fields.add("cvlandslide")
    if cvglacier is not None:
        supported_fields.add("cvglacier")
    supported_fields = sorted(supported_fields)
    recognized_unsupported_fields = sorted({
        family
        for family, file_ref in file_inputs.items()
        if file_ref.production_status in {
            "recognized-only",
            "helper-only",
            "production-unsupported",
        }
    }.union({
        "depfil",
        "dirfil",
        "nxtfil",
        "ndxfil",
        "dscfil",
        "estimate_positive_pressure_head",
        "flow_direction_mode",
        "log_mass_balance_results",
        "pressure_head_fs_listing_flag",
        "save_hydrograph_cells",
        "save_road_risk",
        "save_road_warning",
        "save_runoff_grids",
        "save_detached_trace",
        "save_pf",
        "save_basal_flux",
        "save_deposit_distribution",
        "save_fs_depth_at_min",
        "save_fs_min_grid",
        "save_fs_min_legacy",
        "save_fs_pore_pressure_at_min",
        "save_flow_depth",
        "save_flow_velocity",
        "save_infiltration_rate",
        "save_max_flow_depth",
        "save_max_flow_velocity",
        "save_total_depth",
        "save_volumetric_sediment_concentration",
        "save_erosion_depth",
        "save_deposition_depth",
        "save_outflow_process",
        "save_drainage_nodal_flow",
        "save_drainage_conduit_flow",
        "simulate_debris_flow",
        "simulate_drainage_flow",
        "simulate_inflow_hydrograph",
        "simulate_infiltration",
        "simulate_rainfall",
        "simulate_erosion",
        "simulate_outflow_cell",
        "simulate_shallow_landslide",
        "simulate_water_and_solid_separately",
        "skip_other_timesteps",
        "slope_failure_output_count",
        "slope_failure_output_times_s",
        "use_analytic_fillable_porosity",
        "use_full_dynamic_wave",
        "use_psi0_negative_inverse_alpha",
        "wffil",
        "zmax",
    }))
    if rainfall_mode == "uniform_cri":
        recognized_unsupported_fields.append("rifil")
        recognized_unsupported_fields = sorted(set(recognized_unsupported_fields))

    audit_notes: List[str] = []
    audit_notes.append(f"Bundled DFS infiltration staging variant resolved to `{dfs_infiltration_variant}`.")
    if dfs_infiltration_variant_basis:
        audit_notes.append(dfs_infiltration_variant_basis)
    audit_notes.append(f"Bundled DFS face-flux variant resolved to `{dfs_face_flux_variant}`.")
    if dfs_face_flux_variant_basis:
        audit_notes.append(dfs_face_flux_variant_basis)
    audit_notes.append(f"Bundled DFS failure-source variant resolved to `{dfs_failure_source_variant}`.")
    if dfs_failure_source_variant_basis:
        audit_notes.append(dfs_failure_source_variant_basis)
    audit_notes.append(f"Bundled DFS Manning-bar variant resolved to `{dfs_manningbar_variant}`.")
    if dfs_manningbar_variant_basis:
        audit_notes.append(dfs_manningbar_variant_basis)
    audit_notes.append(f"Bundled DFS dry-face velocity variant resolved to `{dfs_dry_face_velocity_variant}`.")
    if dfs_dry_face_velocity_variant_basis:
        audit_notes.append(dfs_dry_face_velocity_variant_basis)
    audit_notes.append(f"Bundled DFS artificial-viscosity variant resolved to `{dfs_artivis_variant}`.")
    if dfs_artivis_variant_basis:
        audit_notes.append(dfs_artivis_variant_basis)
    audit_notes.append(f"Bundled DFS absubar variant resolved to `{dfs_absubar_variant}`.")
    if dfs_absubar_variant_basis:
        audit_notes.append(dfs_absubar_variant_basis)
    if cvlandslide is not None:
        audit_notes.append(
            "Sediment line used the Chamoli six-value layout "
            "`d50 cvstar cvglacier cvlandslide coedepo cs` from `trini.f90:382`."
        )
    if "triggerslide" in file_inputs:
        audit_notes.append(
            "Triggering-slide grid `triggerslidefil` is always read by original `edda main program.F90` "
            "and injected once in `dfs.F90` when `slide1==1 .and. tnow>0`, independent of `fssimul`."
        )
    audit_notes.append(f"Bundled inflow denominator variant resolved to `{inflow_denominator_variant}`.")
    if inflow_denominator_variant_basis:
        audit_notes.append(inflow_denominator_variant_basis)
    if "zfil" in file_inputs and ltstar_raw < 0:
        audit_notes.append(
            "`ltstar < 0` detected; original EDDA and the current backend both activate the `zfil` "
            "file as the upper-layer soil-thickness (`ltstar`) grid for this case."
        )
    if "zfil" in file_inputs and zmax >= 0:
        audit_notes.append(
            f"Original EDDA keeps scalar `zmax={zmax}` active for this reference config, so the original "
            "`zfil -> zmax` branch is inactive on this case."
        )
    audit_notes.append(
        "Scalar `zmax` was parsed from the reference config, but the current backend still has no canonical "
        "config or runtime consumer for the original `zmax` branch when `zmax < 0`."
    )
    if "dirfil" in file_inputs:
        audit_notes.append("`dirfil` is recognized in the parser but is not yet consumed by the production runtime in S1.")
    if "depfil" in file_inputs:
        if depth >= 0:
            audit_notes.append(
                f"`depfil` was declared, but the original reference config keeps scalar `depth={depth}` active, so the `depfil` branch is inactive on this case."
            )
        else:
            audit_notes.append(
                "`depfil` was parsed as the original initial water-table-depth grid, and current production runtime now seeds that per-cell branch into DFS infiltration staging."
            )
    if "rizerofil" in file_inputs:
        if rizero >= 0:
            audit_notes.append(
                f"`rizerofil` was declared, but the original reference config keeps scalar `rizero={rizero}` active, so the `rizerofil` branch is inactive on this case."
            )
        else:
            audit_notes.append(
                "`rizerofil` was parsed as the original initial infiltration-rate grid, and current production runtime now seeds that per-cell branch into steady/double-layer initialization and DFS staging."
            )
    if "nxtfil" in file_inputs or "ndxfil" in file_inputs or "dscfil" in file_inputs or "wffil" in file_inputs:
        audit_notes.append("TopoIndex support files are recognized for provenance but remain outside the active S1 runtime subset.")
    if "outflow.txt" in file_inputs:
        audit_notes.append("`outflow.txt` exists in the case directory, and current production backend now consumes it for selected-cell outflow observation/export while full hydraulic parity remains partial.")
    if "hydrograph.txt" in file_inputs:
        audit_notes.append("`hydrograph.txt` was detected; current backend can now consume it for hydrosave monitored-output export when the original flag is active, with non-zero oracle coverage still partial.")
    if "inflow.txt" in file_inputs:
        audit_notes.append("`inflow.txt` was detected and current backend now closes the original DFS inflow-forcing chain for supported production runs, while full original reporting parity remains partial.")
    if rainfall_mode == "uniform_cri":
        audit_notes.append("All parsed `cri` values are non-negative; `rifil` paths are provenance only for this run and uniform period rainfall is active.")
    elif rainfall_mode == "raster_rifil":
        audit_notes.append("All parsed `cri` values are negative; each rainfall period must be supplied by the matching `rifil(j)` raster.")
    else:
        audit_notes.append("Parsed rainfall periods mix uniform `cri` values and negative-`cri` raster periods; production mapping must preserve the per-period source selection in metadata.")
    if manning_source == "raster_manningfil":
        audit_notes.append("Declared `manningfil` exists; production runtime should use the spatial Manning raster instead of the global initiation value.")
    else:
        audit_notes.append("No existing `manningfil` raster was found; production runtime should use the global initiation Manning coefficient.")
    if flags.get("use_analytic_fillable_porosity") is not None:
        audit_notes.append("Original `lany` flag was parsed, but no active consumer was located in the visible original source tree or current production backend.")
    if flags.get("estimate_positive_pressure_head") is not None:
        audit_notes.append("Original `llus` flag was parsed, but no active consumer was located in the visible original source tree or current production backend.")
    if flags.get("use_psi0_negative_inverse_alpha") is not None:
        audit_notes.append("Original `lps0` flag was parsed, but no active consumer was located in the visible original source tree or current production backend.")
    if flags.get("flow_direction_mode"):
        audit_notes.append("Original `flowdir=gener/slope/hydro` mode was parsed, but current backend remains fixed to DEM-derived connectivity and visible original active consumers were not found.")
    if flags.get("use_full_dynamic_wave") is not None:
        audit_notes.append("Original `fulldyna` flag was parsed, but current backend does not expose a safe independent dynamic-wave/diffusive-wave switch.")

    return ReferenceConfigParseResult(
        reference_config_file=str(reference_path.resolve()),
        reference_base_dir=str(base_dir.resolve()),
        nzsb=nzsb,
        nzst=nzst,
        nzon=nzon,
        uww=uww,
        ltstar_raw=ltstar_raw,
        lbstar=lbstar,
        zmax=zmax,
        depth=depth,
        rizero=rizero,
        min_slope_angle_deg=min_slope_angle_deg,
        background_flux_offset=background_flux_offset,
        nper=nper,
        rainfall_duration_s=rainfall_duration_s,
        cri_mps=cri_mps,
        capt_s=capt_s,
        rainfall_mode=rainfall_mode,
        rainfall_period_sources=rainfall_period_sources,
        period_source_map=period_source_map,
        alpha1=alpha1,
        beta1=beta1,
        alpha2=alpha2,
        beta2=beta2,
        kresis=kresis,
        manning_global=manning_global,
        manning_source=manning_source,
        limitfr=limitfr,
        shallown=shallown,
        debrisflowmanning=debrisflowmanning,
        d50=d50,
        cvstar=cvstar,
        cvglacier=cvglacier,
        cvlandslide=cvlandslide,
        coedepo=coedepo,
        cs=cs,
        dtmin=dtmin,
        dtmax=dtmax,
        dti=dti,
        dtd=dtd,
        toldh=toldh,
        toldhp=toldhp,
        simul=simul,
        tout=tout,
        wavemax=wavemax,
        zones=zones,
        file_inputs=file_inputs,
        flags=flags,
        switch_snapshot=switch_snapshot,
        extension_flags=extension_flags,
        flag_closure=flag_closure,
        unsupported_flags=unsupported_flags,
        supported_fields=supported_fields,
        recognized_unsupported_fields=recognized_unsupported_fields,
        unrecognized_fields=sorted(set(unrecognized_file_families)),
        audit_notes=audit_notes,
        reference_output_expectations=reference_output_expectations,
        dfs_infiltration_variant=dfs_infiltration_variant,
        dfs_infiltration_variant_source=dfs_infiltration_variant_source,
        dfs_infiltration_variant_basis=dfs_infiltration_variant_basis,
        dfs_face_flux_variant=dfs_face_flux_variant,
        dfs_face_flux_variant_source=dfs_face_flux_variant_source,
        dfs_face_flux_variant_basis=dfs_face_flux_variant_basis,
        dfs_failure_source_variant=dfs_failure_source_variant,
        dfs_failure_source_variant_source=dfs_failure_source_variant_source,
        dfs_failure_source_variant_basis=dfs_failure_source_variant_basis,
        dfs_failure_source_evidence=dfs_failure_source_evidence,
        dfs_failure_source_topology_status=dfs_failure_source_topology_status,
        dfs_manningbar_variant=dfs_manningbar_variant,
        dfs_manningbar_variant_source=dfs_manningbar_variant_source,
        dfs_manningbar_variant_basis=dfs_manningbar_variant_basis,
        dfs_dry_face_velocity_variant=dfs_dry_face_velocity_variant,
        dfs_dry_face_velocity_variant_source=dfs_dry_face_velocity_variant_source,
        dfs_dry_face_velocity_variant_basis=dfs_dry_face_velocity_variant_basis,
        dfs_artivis_variant=dfs_artivis_variant,
        dfs_artivis_variant_source=dfs_artivis_variant_source,
        dfs_artivis_variant_basis=dfs_artivis_variant_basis,
        dfs_absubar_variant=dfs_absubar_variant,
        dfs_absubar_variant_source=dfs_absubar_variant_source,
        dfs_absubar_variant_basis=dfs_absubar_variant_basis,
        inflow_denominator_variant=inflow_denominator_variant,
        inflow_denominator_variant_source=inflow_denominator_variant_source,
        inflow_denominator_variant_basis=inflow_denominator_variant_basis,
        inflow_denominator_direction=inflow_denominator_direction,
        inflow_denominator_fv_value=inflow_denominator_fv_value,
    )
