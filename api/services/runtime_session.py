"""Runtime session lifecycle for Taichi Flow service jobs."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import gc
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from api.services import (
    apply_native_runtime_inputs,
    build_direct_runtime_metadata,
    build_parameter_audit,
    build_reference_runtime_metadata,
    normalize_simulation_config_payload,
    parse_reference_config_file,
    write_output_manifest_file,
    write_parameter_audit_file,
    write_runmode_capabilities_file,
    write_runtime_metadata_files,
)
from api.services.parameter_catalog import build_parameter_catalog
from api.services.edda_semantic_gate import validate_runtime_control_plan
from api.services.compute_policy_resolver import (
    annotate_failure_source_registry,
    compute_policy_resolution_identity,
)
from api.services.structured_input_resolver import materialize_structured_rainfall
from api.services.runtime_profile import (
    RuntimeProfile,
    apply_profile_environment,
    resolve_runtime_profile,
    restore_profile_environment,
)
from edda.backend.backend_manager import reset_taichi_runtime
from edda.config.sim_config import BoundaryConditionConfig, SimulationConfig
from edda.config.edda_runtime_plan import EddaRuntimeControlPlan, build_runtime_control_plan
from taichi_flow.solver import FlowSolver


SolverFactory = Callable[[SimulationConfig], Any]


class SimulationStopRequested(Exception):
    """Internal control-flow signal for a user-requested stop."""


def _runtime_error_payload(exc: Exception) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"error": str(exc)}
    code = getattr(exc, "code", None)
    details = getattr(exc, "details", None)
    if code:
        payload["error_code"] = str(code)
    if details is not None:
        payload["error_details"] = deepcopy(details)
    return payload


def _policy_resolution_projection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the mapper/frozen fields that must agree at runtime.

    The mapper does not need to reproduce queue bookkeeping such as the
    numeric-variant baseline or the original Settings map byte-for-byte.  It
    must, however, reach the same failure-source decision and source evidence
    before the frozen resolution is copied into the runtime manifest.
    """
    detected = payload.get("detected") or {}
    effective = payload.get("effective") or {}
    return {
        "status": payload.get("status"),
        "simulate_shallow_landslide": detected.get("simulate_shallow_landslide"),
        "topology_status": detected.get("topology_status"),
        "detected_variant": detected.get("dfs_failure_source_variant"),
        "mode": effective.get("mode"),
        "effective_simulate_shallow_landslide": effective.get("simulate_shallow_landslide"),
        "active_variant": effective.get("active_variant"),
    }


def _deep_merge(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = deepcopy(base)
    if not override:
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def _config_requested_backend(overrides: Optional[Dict[str, Any]]) -> Optional[str]:
    compute = (overrides or {}).get("compute")
    if isinstance(compute, dict):
        backend = compute.get("backend")
        if backend:
            return str(backend)
    return None


def _write_frontend_uniform_rainfall(
    rainfall_config: Dict[str, Any],
    output_dir: Path,
) -> Dict[str, Any]:
    periods = rainfall_config.get("periods")
    if not isinstance(periods, list) or not periods:
        raise ValueError("Uniform rainfall mode requires at least one period.")

    rows: List[Tuple[float, float, float]] = []
    for idx, period in enumerate(periods):
        if not isinstance(period, dict):
            raise ValueError(f"Uniform rainfall period {idx + 1} must be an object.")
        start_s = float(period.get("start_s", 0.0))
        end_s = float(period.get("end_s", 0.0))
        cri_mps = float(period.get("cri_mps", 0.0))
        if end_s <= start_s:
            raise ValueError(f"Uniform rainfall period {idx + 1} must satisfy end_s > start_s.")
        rows.append((start_s, end_s, cri_mps))

    rows.sort(key=lambda item: item[0])
    for idx in range(1, len(rows)):
        if rows[idx][0] < rows[idx - 1][1]:
            raise ValueError("Uniform rainfall periods must not overlap.")

    rainfall_file = output_dir / "_generated_inputs" / "uniform_rainfall_from_frontend.csv"
    rainfall_file.parent.mkdir(parents=True, exist_ok=True)

    import numpy as np

    base = np.datetime64("2000-01-01T00:00:00")
    with rainfall_file.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("time,rainfall\n")
        for start_s, _end_s, cri_mps in rows:
            timestamp = base + np.timedelta64(int(round(start_s)), "s")
            rainfall_mm_hr = cri_mps * 3600.0 * 1000.0
            handle.write(f"{str(timestamp)},{rainfall_mm_hr:.15f}\n")
        terminal = base + np.timedelta64(int(round(rows[-1][1])), "s")
        handle.write(f"{str(terminal)},0.000000000000000\n")

    return {
        "mode": "single_file",
        "file": str(rainfall_file),
    }


def _native_file_stage(family: str) -> Tuple[str, str, Optional[str]]:
    stages = {
        "demfil": ("production-reachable", "initialize.dem_reader", None),
        "slofil": ("production-reachable", "post_initialize.native_slope_loader", None),
        "triggerslide": ("production-reachable", "post_initialize.native_triggerslide_loader", "Always-on original triggering-slide grid; one-shot DFS injection when tnow>0."),
        "zonfil": ("production-reachable", "initialize.zone_reader", None),
        "zfil": ("partial", "post_initialize.native_ltstar_loader", "Active when double-layer runtime is enabled and ltstar grid input is selected."),
        "manningfil": ("production-reachable", "post_initialize.native_manning_loader", None),
        "rifil": ("conditional-production-reachable", "initialize.rainfall_reader.spatial_series", "Active for non-uniform rainfall periods backed by raster files."),
        "depfil": ("partial", "post_initialize.native_depthwt_loader", "Active when scalar depth is replaced by a depth raster."),
        "rizerofil": ("partial", "post_initialize.native_rizero_loader", "Active when scalar rizero is replaced by an infiltration raster."),
        "outflow.txt": ("partial", "post_initialize.outflow_sidecar_loader", "Active when selected-cell outflow observation/export is enabled."),
        "inflow.txt": ("partial", "post_initialize.inflow_sidecar_loader", "Active when inflow hydrograph forcing is enabled."),
        "hydrograph.txt": ("partial", "post_initialize.hydrograph_sidecar_loader", "Active when hydrograph output is enabled."),
        "drainage.txt": ("partial-default-off-experimental", "post_initialize.stormdrain_runtime_hook", "Default-off stormdrain hook."),
        "swmm.txt": ("recognized-only", "none", "Recorded for original getdwinput provenance."),
    }
    return stages.get(family, ("recognized", "none", None))


WORKBENCH_FAMILY_TO_NATIVE = {
    "manning": "manningfil",
    "slope": "slofil",
    "thickness": "zfil",
    "trigger": "triggerslide",
    "groundwater": "depfil",
    "infiltration": "rizerofil",
    "rainfall": "rifil",
    "zones": "zonfil",
    "soil": "zonfil",
    "dem": "demfil",
    "outflow": "outflow.txt",
    "inflow": "inflow.txt",
    "monitoring": "hydrograph.txt",
    "drainage": "drainage.txt",
    "swmm": "swmm.txt",
}


def _normalize_case_input_family(family: str) -> str:
    return WORKBENCH_FAMILY_TO_NATIVE.get(family, family)


def _case_input_overrides(
    case_input_files: Optional[Dict[str, str]],
    run_flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not case_input_files:
        return {}

    native_files: Dict[str, Dict[str, Any]] = {}
    overrides: Dict[str, Any] = {
        "native_inputs": {
            "enabled": True,
            "source_mode": "api_payload",
            "files": native_files,
        }
    }

    flags = run_flags or {}
    simulate_inflow_hydrograph = bool(flags.get("simulate_inflow_hydrograph", False))
    simulate_outflow_cell = bool(flags.get("simulate_outflow_cell", True))

    for raw_family, path in case_input_files.items():
        if not path:
            continue
        family = _normalize_case_input_family(raw_family)
        status, runtime_stage, activation_condition = _native_file_stage(family)
        original_branch_active = None
        current_backend_branch_active = None
        if family == "inflow.txt":
            original_branch_active = simulate_inflow_hydrograph
            current_backend_branch_active = simulate_inflow_hydrograph
            if not simulate_inflow_hydrograph:
                status = "inactive-by-original-flag"
                runtime_stage = "none"
                activation_condition = "Inactive because original `simulate_inflow_hydrograph` is false."
        elif family == "outflow.txt":
            original_branch_active = simulate_outflow_cell
            current_backend_branch_active = simulate_outflow_cell
        native_files[family] = {
            "family": family,
            "path": path,
            "provenance": "api_payload",
            "status": status,
            "runtime_stage": runtime_stage,
            "activation_condition": activation_condition,
            "status_basis": "Uploaded by the frontend as an original EDDA native input family.",
            "original_branch_active": original_branch_active,
            "current_backend_branch_active": current_backend_branch_active,
        }

    dem_path = case_input_files.get("demfil") or case_input_files.get("dem")
    if dem_path:
        overrides["dem_file"] = dem_path

    zone_path = case_input_files.get("zonfil") or case_input_files.get("zones") or case_input_files.get("soil")
    if zone_path:
        overrides["soil_zones_file"] = zone_path
        overrides["spatial_zones"] = {
            "enabled": True,
            "zone_file": zone_path,
        }

    return overrides


@dataclass
class PreparedRuntime:
    simulation_id: str
    output_dir: Path
    config: SimulationConfig
    effective_config: Dict[str, Any]
    runtime_input_manifest: Dict[str, Any]
    provenance: Dict[str, Any]
    request_payload: Dict[str, Any]
    job_metadata: Dict[str, Any]
    runtime_profile: RuntimeProfile
    runtime_control_plan: EddaRuntimeControlPlan


def prepare_runtime_from_payload(
    *,
    app_output_dir: Path,
    dem_file: Optional[str] = None,
    rainfall_file: Optional[str] = None,
    soil_zones_file: Optional[str] = None,
    boundary_file: Optional[str] = None,
    boundary_config: Optional[Dict[str, Any]] = None,
    output_dir: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    case_config_file: Optional[str] = None,
    case_base_dir: Optional[str] = None,
    case_input_files: Optional[Dict[str, str]] = None,
    runtime_profile_name: Optional[str] = None,
    session_id: Optional[str] = None,
    frozen_effective_config: Optional[Dict[str, Any]] = None,
    frozen_compute_policy_resolution: Optional[Dict[str, Any]] = None,
) -> PreparedRuntime:
    """Prepare config/provenance without changing solver equations."""
    profile = resolve_runtime_profile(runtime_profile_name)
    simulation_id = str(uuid.uuid4())
    run_output_dir = Path(output_dir) if output_dir else app_output_dir / simulation_id
    run_output_dir.mkdir(parents=True, exist_ok=True)

    raw_overrides = overrides if overrides is not None else config
    raw_overrides = deepcopy(raw_overrides) if raw_overrides is not None else {}
    structured_rainfall_audit: Optional[Dict[str, Any]] = None
    structured_rainfall = raw_overrides.pop("structured_rainfall", None) if isinstance(raw_overrides, dict) else None
    if isinstance(structured_rainfall, dict):
        if not dem_file:
            raise ValueError("Structured rainfall requires a bound DEM input.")
        rainfall_config, structured_rainfall_audit = materialize_structured_rainfall(
            structured_rainfall,
            dem_file=dem_file,
            output_dir=run_output_dir,
        )
        raw_overrides["rainfall"] = rainfall_config
    rainfall_payload = raw_overrides.get("rainfall") if isinstance(raw_overrides, dict) else None
    if isinstance(rainfall_payload, dict) and rainfall_payload.get("mode") == "uniform_periods":
        raw_overrides["rainfall"] = _write_frontend_uniform_rainfall(rainfall_payload, run_output_dir)
    run_flags = raw_overrides.get("run_flags") if isinstance(raw_overrides, dict) else None
    raw_overrides = _deep_merge(raw_overrides, _case_input_overrides(case_input_files, run_flags if isinstance(run_flags, dict) else None))
    if not dem_file and isinstance(raw_overrides.get("dem_file"), str):
        dem_file = str(raw_overrides["dem_file"])
    if not soil_zones_file and isinstance(raw_overrides.get("soil_zones_file"), str):
        soil_zones_file = str(raw_overrides["soil_zones_file"])
    normalized_overrides, config_normalization = normalize_simulation_config_payload(raw_overrides)
    normalized_overrides = normalized_overrides or {}
    requested_backend = _config_requested_backend(normalized_overrides)
    if requested_backend is None:
        normalized_overrides = _deep_merge(
            {"compute": {"backend": profile.default_backend}},
            normalized_overrides,
        )

    request_payload = {
        "dem_file": dem_file,
        "rainfall_file": rainfall_file,
        "soil_zones_file": soil_zones_file,
        "boundary_file": boundary_file,
        "boundary_config": boundary_config,
        "output_dir": str(run_output_dir),
        "overrides": raw_overrides,
        "case_config_file": case_config_file,
        "case_base_dir": case_base_dir,
        "case_input_files": case_input_files,
        "runtime_profile": profile.name,
        "session_id": session_id,
    }
    request_payload = {key: value for key, value in request_payload.items() if value is not None}

    top_level_overrides = {
        "dem_file": dem_file,
        "rainfall_file": rainfall_file,
        "soil_zones_file": soil_zones_file,
    }
    # A workbench queue carries the Settings snapshot that was used at
    # enqueue time.  Reference mapping must use that same sparse gate map for
    # policy resolution (not the current Settings and not an implicit empty
    # map), otherwise an explicitly unlocked live policy would be rejected
    # during mapper preparation.
    frozen_policy_gates = None
    if isinstance(frozen_compute_policy_resolution, dict):
        candidate_gates = frozen_compute_policy_resolution.get("settings_snapshot")
        if isinstance(candidate_gates, dict):
            frozen_policy_gates = deepcopy(candidate_gates)

    if case_config_file:
        parsed_reference = parse_reference_config_file(case_config_file, case_base_dir)
        flow_config, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(
            parsed_reference,
            run_output_dir,
            config_overrides=normalized_overrides,
            top_level_overrides=top_level_overrides,
            global_gates=frozen_policy_gates,
            strict_reference=True,
        )
        if boundary_config:
            flow_config.boundary_conditions = BoundaryConditionConfig(**boundary_config)
        elif boundary_file:
            flow_config.boundary_conditions = BoundaryConditionConfig(
                mode="file",
                boundary_file=boundary_file,
                default_type="outflow",
                include_nodata=True,
            )
    else:
        if not dem_file:
            raise ValueError("`dem_file` is required when `case_config_file` is not provided.")
        config_dict = {
            "dem_file": dem_file,
            "rainfall_file": rainfall_file,
            "soil_zones_file": soil_zones_file,
            "output_dir": str(run_output_dir),
            "output_format": "geotiff",
            "save_intermediate": True,
            "compute": {"backend": profile.default_backend},
        }
        if boundary_config:
            config_dict["boundary_conditions"] = boundary_config
        elif boundary_file:
            config_dict["boundary_conditions"] = {
                "mode": "file",
                "boundary_file": boundary_file,
                "default_type": "outflow",
                "include_nodata": True,
            }
        config_dict = _deep_merge(config_dict, normalized_overrides)
        flow_config = SimulationConfig.from_dict(config_dict)
        effective_config, runtime_input_manifest, provenance = build_direct_runtime_metadata(flow_config)

    if frozen_compute_policy_resolution is not None:
        # Workbench runs carry an enqueue-time policy snapshot.  Reuse it as
        # the authoritative audit/provenance record instead of resolving the
        # current global Settings again during runtime preparation.
        frozen_resolution = deepcopy(frozen_compute_policy_resolution)
        expected_id, expected_hash = compute_policy_resolution_identity(frozen_resolution)
        if frozen_resolution.get("resolution_id") not in {None, expected_id} or frozen_resolution.get("resolution_hash") not in {None, expected_hash}:
            raise ValueError("Frozen compute policy resolution identity is invalid.")
        frozen_resolution.setdefault("resolution_id", expected_id)
        frozen_resolution.setdefault("resolution_hash", expected_hash)
        mapped_resolution = runtime_input_manifest.get("compute_policy_resolution") or {}
        if mapped_resolution and _policy_resolution_projection(mapped_resolution) != _policy_resolution_projection(frozen_resolution):
            raise ValueError(
                "Mapper compute policy resolution differs from the enqueue-time frozen resolution."
            )
        runtime_input_manifest["compute_policy_resolution"] = frozen_resolution
        provenance["compute_policy_resolution"] = frozen_resolution
        effective_config["compute_policy_resolution"] = frozen_resolution
        registry = runtime_input_manifest.setdefault("input_source_registry", {})
        failure_entry = registry.setdefault(
            "dfs_failure_source_variant",
            {
                "family": "dfs_failure_source_variant",
                "state": "config_fallback",
                "selected_source": None,
            },
        )
        registry["dfs_failure_source_variant"] = annotate_failure_source_registry(
            dict(failure_entry), frozen_resolution
        )
    if frozen_effective_config is not None:
        frozen_effective = deepcopy(frozen_effective_config)
        runtime_input_manifest["frozen_effective_config"] = frozen_effective
        provenance["frozen_effective_config"] = deepcopy(frozen_effective)
        effective_config["frozen_effective_config"] = deepcopy(frozen_effective)

    if structured_rainfall_audit is not None:
        effective_config["structured_rainfall"] = structured_rainfall_audit
        runtime_input_manifest["structured_rainfall"] = structured_rainfall_audit
        provenance["structured_rainfall"] = structured_rainfall_audit

    runtime_control_plan = build_runtime_control_plan(flow_config)
    semantic_gate = validate_runtime_control_plan(runtime_control_plan)
    control_plan_payload = runtime_control_plan.to_dict()
    effective_config["edda_runtime_control_plan"] = control_plan_payload
    effective_config["edda_semantic_gate"] = semantic_gate
    runtime_input_manifest["edda_runtime_control_plan"] = control_plan_payload
    runtime_input_manifest["edda_semantic_gate"] = semantic_gate
    provenance["edda_runtime_control_plan"] = control_plan_payload
    provenance["edda_semantic_gate"] = semantic_gate

    if not requested_backend and flow_config.compute.backend == "auto":
        flow_config.compute.backend = profile.default_backend

    effective_config["config_normalization"] = config_normalization
    effective_config["runtime_profile"] = profile.to_dict()
    provenance["config_normalization"] = config_normalization
    provenance["runtime_profile"] = profile.to_dict()

    job_metadata = {
        "simulation_id": simulation_id,
        "created_at": datetime.now().isoformat(),
        "source_mode": provenance.get("source_mode"),
        "case_config_file": provenance.get("reference_config_file") or case_config_file,
        "output_dir": str(run_output_dir),
        "runtime_profile": profile.to_dict(),
    }

    return PreparedRuntime(
        simulation_id=simulation_id,
        output_dir=run_output_dir,
        config=flow_config,
        effective_config=effective_config,
        runtime_input_manifest=runtime_input_manifest,
        provenance=provenance,
        request_payload=request_payload,
        job_metadata=job_metadata,
        runtime_profile=profile,
        runtime_control_plan=runtime_control_plan,
    )


class RuntimeSession:
    """Owns one solver lifecycle and releases heavy runtime state after use."""

    _active_sessions = 0
    _active_lock = RLock()

    def __init__(
        self,
        prepared: PreparedRuntime,
        *,
        solver_factory: Optional[SolverFactory] = None,
        reset_runtime_on_dispose: bool = True,
    ) -> None:
        self.prepared = prepared
        self.solver_factory = solver_factory or FlowSolver
        self.reset_runtime_on_dispose = reset_runtime_on_dispose
        self.solver: Any = None
        self.stop_requested = False
        self._registered_active = False
        self._previous_environment: Optional[Dict[str, Optional[str]]] = None
        self.resource_summary: Dict[str, Any] = {}

    @property
    def simulation_id(self) -> str:
        return self.prepared.simulation_id

    @property
    def output_dir(self) -> Path:
        return self.prepared.output_dir

    def initialize(self) -> Dict[str, Any]:
        self._previous_environment = apply_profile_environment(self.prepared.runtime_profile)
        with RuntimeSession._active_lock:
            RuntimeSession._active_sessions += 1
            self._registered_active = True
        try:
            self.solver = self.solver_factory(self.prepared.config)
            self.solver.initialize()
            self.solver.retain_output_history = False
            self.prepared.runtime_input_manifest = apply_native_runtime_inputs(
                self.solver,
                self.prepared.runtime_input_manifest,
            )
            runtime_gate = validate_runtime_control_plan(
                self.prepared.runtime_control_plan,
                runtime_input_manifest=self.prepared.runtime_input_manifest,
            )
            self.prepared.runtime_input_manifest["edda_semantic_gate"] = runtime_gate
            self.prepared.effective_config["edda_semantic_gate"] = runtime_gate
            self.prepared.provenance["edda_semantic_gate"] = runtime_gate
            self._write_metadata_bundle()
            return self.state_entry(status="pending")
        except Exception:
            self.dispose()
            raise

    def state_entry(self, *, status: str) -> Dict[str, Any]:
        return {
            "id": self.simulation_id,
            "status": status,
            "progress": 0.0,
            "current_time": 0.0,
            "end_time": self.prepared.config.time.t_end,
            "step_count": 0,
            "output_count": 0,
            "runtime_session": self,
            "solver": None,
            "config": self.prepared.config,
            "request_payload": self.prepared.request_payload,
            "job_metadata": self.prepared.job_metadata,
            "effective_config": self.prepared.effective_config,
            "runtime_input_manifest": self.prepared.runtime_input_manifest,
            "runtime_provenance": self.prepared.provenance,
            "parameter_audit": None,
            "parameter_catalog": None,
            "runmode_capabilities": None,
            "output_manifest": None,
            "runtime_profile": self.prepared.runtime_profile.to_dict(),
            "output_dir": str(self.output_dir),
            "start_time": None,
            "end_time_actual": None,
            "error": None,
            "error_code": None,
            "error_details": {},
            "resource_summary": {},
        }

    def run_to_completion(self, app_state: Dict[str, Any]) -> None:
        sim_data = app_state["simulations"][self.simulation_id]
        try:
            sim_data["status"] = "running"
            sim_data["start_time"] = datetime.now().isoformat()

            def progress_callback(time_info: Dict[str, Any]) -> None:
                if self.stop_requested or sim_data.get("stop_requested"):
                    raise SimulationStopRequested()
                sim_data["progress"] = time_info["progress"]
                sim_data["current_time"] = time_info["t_current"]
                sim_data["step_count"] = time_info["step_count"]
                solver = self.solver
                sim_data["output_count"] = getattr(solver.time_stepper, "output_count", 0) if solver else sim_data.get("output_count", 0)

            self.solver.set_progress_callback(progress_callback)
            self.solver.run()
            if self.stop_requested or sim_data.get("stop_requested"):
                raise SimulationStopRequested()
            self.solver.export_final_results()
            self._write_metadata_bundle()

            sim_data.update(
                {
                    "status": "completed",
                    "end_time_actual": datetime.now().isoformat(),
                    "progress": 100.0,
                    "output_count": getattr(self.solver.time_stepper, "output_count", 0),
                    "effective_config": self.prepared.effective_config,
                    "runtime_input_manifest": self.prepared.runtime_input_manifest,
                    "runtime_provenance": self.prepared.provenance,
                    "parameter_audit": self._latest_parameter_audit,
                    "parameter_catalog": self._latest_parameter_catalog,
                    "runmode_capabilities": self._latest_runmode_capabilities,
                    "output_manifest": self._latest_output_manifest,
                }
            )
        except SimulationStopRequested:
            sim_data.update(
                {
                    "status": "stopped",
                    "end_time_actual": datetime.now().isoformat(),
                    "error": None,
                    "error_code": None,
                    "error_details": {},
                    "effective_config": self.prepared.effective_config,
                    "runtime_input_manifest": self.prepared.runtime_input_manifest,
                    "runtime_provenance": self.prepared.provenance,
                }
            )
            try:
                self._write_metadata_bundle()
                sim_data.update(
                    {
                        "parameter_audit": self._latest_parameter_audit,
                        "parameter_catalog": self._latest_parameter_catalog,
                        "runmode_capabilities": self._latest_runmode_capabilities,
                        "output_manifest": self._latest_output_manifest,
                    }
                )
            except Exception:
                pass
        except Exception as exc:
            sim_data["status"] = "failed"
            sim_data.update(_runtime_error_payload(exc))
            try:
                self._write_metadata_bundle()
            except Exception:
                pass
        finally:
            summary = self.dispose()
            sim_data["runtime_session"] = None
            sim_data["solver"] = None
            sim_data["resource_summary"] = summary

    def request_stop(self) -> None:
        """Ask the running background session to stop at the next callback."""
        self.stop_requested = True

    def dispose(self) -> Dict[str, Any]:
        solver = self.solver
        if solver is not None:
            try:
                solver.progress_callback = None
                solver.output_callback = None
                if hasattr(solver, "results") and isinstance(solver.results, list):
                    solver.results.clear()
            except Exception:
                pass
        self.solver = None

        should_reset_runtime = False
        with RuntimeSession._active_lock:
            if self._registered_active:
                RuntimeSession._active_sessions = max(0, RuntimeSession._active_sessions - 1)
                self._registered_active = False
            should_reset_runtime = RuntimeSession._active_sessions == 0

        if self._previous_environment is not None:
            restore_profile_environment(self._previous_environment)
            self._previous_environment = None

        gc.collect()
        if self.reset_runtime_on_dispose and should_reset_runtime:
            with RuntimeSession._active_lock:
                # Re-check while holding the lifecycle lock so a new session
                # cannot race a reset between decrement and disposal.
                if RuntimeSession._active_sessions == 0:
                    reset_taichi_runtime()
            gc.collect()

        self.resource_summary = {
            "children": 0,
            "pid": os.getpid(),
            "active_sessions": RuntimeSession._active_sessions,
            "final_heap_bytes": gc.get_stats()[0]["collected"] if hasattr(gc, "get_stats") else None,
            "taichi_runtime_reset": self.reset_runtime_on_dispose and RuntimeSession._active_sessions == 0,
        }
        return dict(self.resource_summary)

    def _write_metadata_bundle(self) -> None:
        write_runtime_metadata_files(
            self.output_dir,
            self.prepared.effective_config,
            self.prepared.runtime_input_manifest,
            self.prepared.provenance,
        )
        output_manifest = write_output_manifest_file(
            self.output_dir,
            reference_output_expectations=self.prepared.provenance.get("reference_output_expectations"),
        )
        parameter_audit = build_parameter_audit(
            self.prepared.config,
            self.prepared.runtime_input_manifest,
            self.prepared.provenance,
            request_payload=self.prepared.request_payload,
            output_manifest=output_manifest,
        )
        write_parameter_audit_file(self.output_dir, parameter_audit)
        runmode_capabilities = write_runmode_capabilities_file(
            self.output_dir,
            config=self.prepared.config,
            reference_audit=self.prepared.provenance.get("reference_config_audit"),
            parameter_audit=parameter_audit,
            source_mode=self.prepared.provenance.get("source_mode"),
        )
        parameter_catalog = build_parameter_catalog(
            parameter_audit,
            self.prepared.runtime_input_manifest,
            self.prepared.provenance,
        )
        _write_json(self.output_dir / "parameter_catalog.json", parameter_catalog)
        _write_json(self.output_dir / "request_payload.json", self.prepared.request_payload)
        _write_json(self.output_dir / "job_metadata.json", self.prepared.job_metadata)

        self._latest_output_manifest = output_manifest
        self._latest_parameter_audit = parameter_audit
        self._latest_parameter_catalog = parameter_catalog
        self._latest_runmode_capabilities = runmode_capabilities
