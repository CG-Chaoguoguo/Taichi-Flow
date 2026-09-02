"""
Main EDDA solver integrating all physics modules.

Simulation sequence:
1. Initialize fields and modules
2. Time loop:
   a. Update rainfall input
   b. Compute infiltration and stability:
      - If double-layer enabled: Richards equation → pore pressure → minimum FS → failure check
      - Else: simplified hydrology → stability check (backward compatibility)
   c. Compute flow (shallow water)
   d. Update rheology
   e. Compute erosion/deposition
   f. Update bed elevation
   g. Adapt time step
   h. Output results
3. Finalize and export
"""
import csv
import json
import taichi as ti
import numpy as np
import os
from pathlib import Path
from typing import Optional, Callable, Tuple, Union, List, Dict, Any, Mapping, Sequence
import logging
from tqdm import tqdm

from edda.config.sim_config import SimulationConfig
from edda.config.edda_runtime_plan import build_runtime_control_plan
from edda.core.fields import EDDAFields
from edda.backend.backend_manager import assert_live_cuda, initialize_taichi, live_backend_snapshot
from edda.io.dem_reader import DEMReader
from edda.io.hydrograph_exporter import write_hydrograph_file
from edda.io.rainfall_reader import RainfallReader
from edda.io.result_exporter import ResultExporter
from edda.io.async_result_writer import AsyncResultWriter, GridWriteJob
from edda.io.topoindex_sidecar import build_rnoff_pre_dfs_period_precompute_contract
from edda.io.zone_reader import ZoneReader
from edda.physics.hydrology import HydrologyModel
from edda.physics.stability import StabilityModel
from edda.physics.rheology import RheologyModel
from edda.physics.erosion import ErosionModel
from edda.physics.deposition import DepositionModel
from edda.physics.double_layer_soil import DoubleLayerSoilModel
from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver
from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
from edda.solver.native_unsfin_provider import (
    DEFAULT_FULL_WINDOW_S,
    NativeUnsfinDryRunRequest,
    RNOFF_DFS_SHADOW_FEED_FLAG_DISABLED_REASON,
    RNOFF_NATIVE_FEED_FLAG_DISABLED_REASON,
    configure_provider_runtime_feed,
    rnoff_native_unsfin_feed_flag_enabled,
    rnoff_dfs_shadow_feed_flag_enabled,
    run_provider_dry_run,
    runtime_feed_flag_enabled,
)
from edda.solver.shallow_water import ShallowWaterSolver
from edda.solver.time_stepper import TimeStepper

logger = logging.getLogger(__name__)


@ti.kernel
def apply_outflow_boundaries_kernel(fields: ti.template()):
    """Apply outflow boundary conditions (h=0, u=0, v=0, Cv=0)."""
    for i, j in fields.h:
        if fields.is_boundary[i, j]:
            bc_type = fields.boundary_type[i, j]
            if bc_type == 1:  # Outflow boundary
                fields.h[i, j] = 0.0
                fields.u[i, j] = 0.0
                fields.v[i, j] = 0.0
                fields.Cv[i, j] = 0.0
                # rho will be set to rhow in rheology module


class EDDASolver:
    """
    Main EDDA solver coordinating all physics modules.
    """

    OUTPUT_STATE_EXCLUDED_FIELDS: Tuple[str, ...] = ("pt",)
    PERIODIC_OUTPUT_FIELDS: Tuple[str, ...] = (
        "h",
        "Cv",
        "z_bed",
        "z_original",
        "is_nodata",
        "fv_fortran",
        "erosion_depth",
        "deposition_depth",
        "max_flow_depth",
        "max_flow_velocity",
        "max_solid_depth",
        "total_depth",
        "fdepth",
        "sfh",
        "dfh",
        "ffh",
        "maxsfh",
        "maxdfh",
        "maxffh",
    )

    def __init__(self, config: SimulationConfig):
        """
        Initialize EDDA solver.

        Args:
            config: Simulation configuration
        """
        self.config = config
        self.edda_runtime_control_plan = build_runtime_control_plan(config)
        self.fields = None
        self.time_stepper = None
        self.results = []
        self.backend_snapshot: Dict[str, Any] = {}
        self.numerical_dt_history: List[float] = []
        self.numerical_reject_reasons: Dict[str, int] = {}
        self.numerical_reject_examples: Dict[str, Dict[str, Any]] = {}
        self.numerical_max_abs_relative_error = 0.0
        self.numerical_volume_violation_count = 0
        self.numerical_dt_min_hits = 0
        self.numerical_nonfinite_counts: Dict[str, int] = {}
        self._async_output_writer: Optional[AsyncResultWriter] = None
        self.numerical_observe_count = 0

        # Physics modules
        self.hydrology = None
        self.stability = None
        self.rheology = None
        self.erosion = None
        self.deposition = None
        self.shallow_water = None
        self.dynamic_wave_workspace = None
        self.dfs_dynamic_wave = None
        self.double_layer = None  # Double-layer soil model (optional)

        # I/O
        self.rainfall_reader = None
        self.result_exporter = None

        # Callbacks
        self.progress_callback = None
        self.output_callback = None
        self.outflow_process_observer: Optional[Dict[str, Any]] = None
        self.hydrograph_monitor_observer: Optional[Dict[str, Any]] = None
        self.inflow_hydrograph_config: Optional[Dict[str, Any]] = None
        self.rnoff_topoindex_runtime_hook_config: Optional[Dict[str, Any]] = None
        self.rnoff_topoindex_runtime_manifest: Dict[str, Any] = {
            "rnoff_topoindex_runtime_enabled": False,
            "rnoff_topoindex_branch_active": False,
            "changed_field_names": [],
        }
        self.rnoff_native_unsfin_provider_manifest: Dict[str, Any] = {
            "rnoff_native_unsfin_provider_validation_enabled": False,
            "rnoff_contract_loaded": False,
            "rik_period_loaded": False,
            "q_formula_validated": False,
            "native_unsfin_rnoff_feed_active": False,
            "schedule_generated_with_rnoff": False,
            "provider_schedule_generation_active": False,
            "dfs_runtime_feed_blocked": False,
            "rnoff_dfs_shadow_lifecycle_requested": False,
            "rnoff_dfs_shadow_feed_gate_enabled": False,
            "shadow_lifecycle_active": False,
            "shadow_schedule_loaded": False,
            "shadow_crossing_count": 0,
            "shadow_candidate_stage_count": 0,
            "shadow_rejected_discard_count": 0,
            "shadow_accepted_commit_count": 0,
            "shadow_duplicate_fire_count": 0,
            "schedule_consumed_by_dfs": False,
            "final_state_mutated": False,
            "changed_field_names": [],
            "fallback_reason": None,
        }
        self.stormdrain_runtime_hook_config: Optional[Dict[str, Any]] = None
        self.stormdrain_runtime_manifest: Dict[str, Any] = {
            "stormdrain_runtime_enabled": False,
            "stormdrain_branch_active": False,
            "changed_field_names": [],
        }
        # Persistent carry-over of original dfs.F90 `tempdt`, which survives
        # across accepted steps and influences the step size restored after
        # output-aligned truncation.
        self.fortran_tempdt = 0.0
        self.dfs_accepted_step_id = 0
        self.dfs_candidate_step_id = 0
        self.step_lifecycle_trace_enabled = False
        self.step_lifecycle_trace_window_start: Optional[float] = None
        self.step_lifecycle_trace_window_end: Optional[float] = None
        self.step_lifecycle_trace_limit = 20000
        self.step_lifecycle_trace_records: list[dict[str, Any]] = []

        # Numeric dtype for NumPy buffers (kept consistent with configured precision)
        self.numpy_float_dtype = np.float64 if self.config.compute.use_double_precision else np.float32

        logger.info("EDDASolver initialized")

    def configure_step_lifecycle_trace(
        self,
        *,
        enabled: bool = False,
        window_start: Optional[float] = None,
        window_end: Optional[float] = None,
        limit: int = 20000,
    ) -> None:
        """Enable default-off accepted/rejected timestep lifecycle tracing.

        The trace is observational only: it records the Python-level DFS time
        controller state and the first-reject diagnostic already produced by
        the Taichi DFS kernel. It must not influence candidate dt, retry,
        accepted-state commit, or output scheduling.
        """

        self.step_lifecycle_trace_enabled = bool(enabled)
        self.step_lifecycle_trace_window_start = None if window_start is None else float(window_start)
        self.step_lifecycle_trace_window_end = None if window_end is None else float(window_end)
        self.step_lifecycle_trace_limit = int(limit) if int(limit) > 0 else 20000
        self.step_lifecycle_trace_records = []

    def get_step_lifecycle_trace_records(self) -> list[dict[str, Any]]:
        return list(self.step_lifecycle_trace_records)

    def _step_lifecycle_trace_in_window(self, t_start: float, t_end: float) -> bool:
        if not self.step_lifecycle_trace_enabled:
            return False
        if len(self.step_lifecycle_trace_records) >= self.step_lifecycle_trace_limit:
            return False
        window_start = self.step_lifecycle_trace_window_start
        window_end = self.step_lifecycle_trace_window_end
        if window_start is not None and t_end < window_start:
            return False
        if window_end is not None and t_start > window_end:
            return False
        return True

    def _record_step_lifecycle_trace(self, record: dict[str, Any]) -> None:
        if len(self.step_lifecycle_trace_records) < self.step_lifecycle_trace_limit:
            self.step_lifecycle_trace_records.append(record)

    def _run_control_enabled(self, key: str, *, compatibility_default: bool = True) -> bool:
        plan = getattr(self, "edda_runtime_control_plan", None)
        if plan is None:
            return bool(compatibility_default)
        return plan.run_enabled(key, compatibility_default=compatibility_default)

    def initialize(self):
        """Initialize all components."""
        logger.info("Initializing EDDA solver...")
        self.numerical_dt_history = []
        self.numerical_reject_reasons = {}
        self.numerical_reject_examples = {}
        self.numerical_max_abs_relative_error = 0.0
        self.numerical_volume_violation_count = 0
        self.numerical_dt_min_hits = 0
        self.numerical_nonfinite_counts = {}
        self.numerical_observe_count = 0

        # Initialize Taichi backend
        requested_backend = str(self.config.compute.backend).lower()
        initialize_taichi(
            backend=requested_backend,
            use_double_precision=self.config.compute.use_double_precision,
            num_threads=self.config.compute.num_threads,
            device_memory_GB=8.0 if requested_backend in {"cuda", "auto"} else 1.0,
        )
        if requested_backend == "cuda":
            snapshot = assert_live_cuda()
            print(
                "[edda] CUDA backend confirmed: "
                f"arch={snapshot.get('live_arch')} "
                f"gpu={snapshot.get('gpu_name')} "
                f"vram={snapshot.get('gpu_memory_used_MB')}MB/"
                f"{snapshot.get('gpu_memory_total_MB')}MB",
                flush=True,
            )
        else:
            snapshot = live_backend_snapshot()
            print(
                f"[edda] compute backend={requested_backend} live_arch={snapshot.get('live_arch')}",
                flush=True,
            )
        self.backend_snapshot = {
            "requested_backend": requested_backend,
            **dict(snapshot),
            "fallback_active": bool(
                requested_backend == "cuda"
                and (
                    str(snapshot.get("manager_backend") or "").lower() != "cuda"
                    or "cuda" not in str(snapshot.get("live_arch") or "").lower()
                )
            ),
        }

        # Load DEM
        logger.info(f"Loading DEM: {self.config.dem_file}")
        dem_reader = DEMReader(self.config.dem_file)
        elevation, metadata = dem_reader.read()

        # Keep original NoData cells excluded from the computational domain.
        # Original EDDA does not interpolate them into active terrain.
        nodata_mask = dem_reader.get_nodata_mask()
        if np.any(nodata_mask):
            logger.info("Detected NoData cells; preserving mask and excluding them from simulation")

        # Initialize fields
        ny, nx = elevation.shape
        dx = metadata['dx']
        dy = metadata['dy']

        logger.info(f"Grid size: {nx} x {ny}")
        logger.info(f"Grid spacing: dx={dx:.2f}m, dy={dy:.2f}m")

        fp_dtype = ti.f64 if self.config.compute.use_double_precision else ti.f32
        self.fields = EDDAFields(nx, ny, dx, dy, fp_dtype=fp_dtype)
        # Transpose elevation from (ny, nx) to (nx, ny) for Taichi fields
        self.fields.initialize_from_numpy(elevation.T.astype(self.numpy_float_dtype))
        self.fields.set_nodata_mask(nodata_mask.T.astype(np.int32))
        self.fields.initialize_all()
        self._initialize_flow_connectivity(nodata_mask.T)

        # Compute slopes from DEM
        logger.info("Computing slopes from DEM")
        self.fields.compute_slopes()

        # Initialize boundary conditions
        logger.info("Setting boundary conditions...")
        boundary_mask, boundary_types = self._initialize_boundary_conditions(nodata_mask.T)
        self.fields.set_boundary_conditions(boundary_mask, boundary_types)

        # Initialize spatial zone system if enabled
        if self.config.spatial_zones and self.config.spatial_zones.enabled:
            logger.info("Initializing spatial zone system...")
            self._initialize_spatial_zones()
        else:
            # Use uniform parameters from configuration
            logger.info("Using uniform parameters (no spatial zones)")
            self._initialize_uniform_parameters()

        # Initialize time stepper
        self.time_stepper = TimeStepper(
            t_start=self.config.time.t_start,
            t_end=self.config.time.t_end,
            dt_initial=self.config.time.dt_initial,
            dt_min=self.config.time.dt_min,
            dt_max=self.config.time.dt_max,
            dt_output=self.config.time.dt_output,
            CFL=self.config.time.CFL,
            dx=dx,
            dy=dy
        )

        # Initialize physics modules
        logger.info("Initializing physics modules...")

        self.hydrology = HydrologyModel(
            self.fields,
            self.config.hydrology
        )

        self.stability = StabilityModel(
            self.fields,
            self.config.soil
        )

        self.rheology = RheologyModel(
            self.fields,
            self.config.rheology
        )

        self.erosion = ErosionModel(
            self.fields,
            tau_c=self.config.erosion.tau_c,
            k_erosion=self.config.erosion.k_erosion,
            rho_sediment=self.config.rheology.rho_sediment,
            rho_water=self.config.rheology.rho_water,
            cvstar=self.config.rheology.Cv_max,
            phi=self.config.soil.phi
        )
        self.erosion.kresis = self.config.rheology.kresis
        self.erosion.cs = self.config.rheology.cs
        self.erosion.manningb = self.config.rheology.manningb
        self.erosion.manningm = self.config.rheology.manningm

        self.deposition = DepositionModel(
            self.fields,
            self.config.erosion,
            d50=self.config.erosion.d50,
            rho_sediment=self.config.rheology.rho_sediment,
            rho_water=self.config.rheology.rho_water,
            cvstar=self.config.rheology.Cv_max,
            coedepo=self.config.erosion.coedepo,
        )

        self.shallow_water = ShallowWaterSolver(self.fields)
        self.dynamic_wave_workspace = FortranDynamicWaveWorkspace(self.fields)
        self.dfs_dynamic_wave = DFSDynamicWaveSolver(
            self.fields,
            self.config,
            self.dynamic_wave_workspace,
            runtime_control_plan=self.edda_runtime_control_plan,
        )

        # Connect Manning field from rheology to SWE solver for Newton-Raphson
        self.shallow_water.set_manning_field(self.rheology.manning)

        # Initialize rainfall reader
        rainfall_cfg = self.config.rainfall
        if rainfall_cfg and rainfall_cfg.mode == "spatial_tif_series" and rainfall_cfg.directory:
            logger.info(f"Loading spatial rainfall data from directory: {rainfall_cfg.directory}")
            self.rainfall_reader = RainfallReader(rainfall_cfg.directory)
            self.rainfall_reader.read_spatial_rainfall(
                rainfall_cfg.directory,
                file_pattern=rainfall_cfg.file_pattern,
                interval_bounds_s=rainfall_cfg.interval_bounds_s,
            )
        else:
            rainfall_file = None
            if rainfall_cfg and rainfall_cfg.file:
                rainfall_file = rainfall_cfg.file
            elif self.config.rainfall_file:
                rainfall_file = self.config.rainfall_file

            if rainfall_file:
                logger.info(f"Loading rainfall data: {rainfall_file}")
                self.rainfall_reader = RainfallReader(rainfall_file)
                self.rainfall_reader.read()

        # Initialize double-layer soil model if enabled
        if self.config.soil.double_layer and self.config.soil.double_layer.enabled:
            logger.info("Initializing double-layer soil model...")
            self.double_layer = DoubleLayerSoilModel(
                self.fields,
                self.config.soil.double_layer
            )

            rikzero_np = self.double_layer.build_initial_rikzero_field(
                self.config.hydrology.rizero_initial
            )
            self.double_layer.initialize_double_layer(rikzero_np.astype(self.numpy_float_dtype))
            self.dfs_dynamic_wave.set_double_layer_model(self.double_layer)
            self.dfs_dynamic_wave.set_initial_rikzero_field(rikzero_np)
            logger.info("Double-layer soil model initialized")
        else:
            logger.info("Using simplified single-layer soil model")

        # Store output directory and metadata for result export
        self.output_dir = Path(self.config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.export_metadata = {
            'crs': metadata.get('crs'),
            'transform': metadata.get('transform'),
            'nodata_value': -9999.0
        }

        logger.info("Initialization complete")

    def configure_outflow_process_observer(
        self,
        cell_ids: List[int],
        *,
        sidecar_path: Optional[str] = None,
        output_filename: str = "OUTNQ_Taichi.txt",
    ) -> Dict[str, Any]:
        """
        Configure a minimal original-EDDA-style outflow process observer.

        This closes only the sidecar-driven observation/export chain. It does
        not change the scientific update order or add new source terms.
        """
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before configuring outflow process observation.")

        plan = getattr(self, "edda_runtime_control_plan", None)
        if plan is not None and plan.strict and not plan.run_enabled(
            "simulate_outflow_cell",
            compatibility_default=False,
        ):
            self.fields.dfs_outflow_mask.fill(0)
            self.outflow_process_observer = {
                "sidecar_path": sidecar_path,
                "output_filename": output_filename,
                "cells": [],
                "missing_cell_ids": [],
                "samples": [],
                "last_sample": [],
                "configured_cell_count": 0,
                "max_discharge": {},
                "max_time_hours": {},
                "disabled_by_control": True,
            }
            return {
                "configured_cell_count": 0,
                "missing_cell_ids": [],
                "output_filename": output_filename,
                "disabled_by_control": True,
            }

        cell_id_grid = self.fields.cell_id.to_numpy()
        id_to_coord: Dict[int, Tuple[int, int]] = {}
        for i in range(cell_id_grid.shape[0]):
            for j in range(cell_id_grid.shape[1]):
                cell_id = int(cell_id_grid[i, j])
                if cell_id > 0:
                    id_to_coord[cell_id] = (i, j)

        selected_cells: List[Dict[str, int]] = []
        missing_cell_ids: List[int] = []
        for cell_id in cell_ids:
            coord = id_to_coord.get(int(cell_id))
            if coord is None:
                missing_cell_ids.append(int(cell_id))
                continue
            selected_cells.append({"cell_id": int(cell_id), "i": coord[0], "j": coord[1]})

        if selected_cells:
            dfs_outflow_mask = self.fields.dfs_outflow_mask.to_numpy().astype(np.int32, copy=True)
            for cell in selected_cells:
                dfs_outflow_mask[cell["i"], cell["j"]] = 1
            self.fields.dfs_outflow_mask.from_numpy(dfs_outflow_mask)

        self.outflow_process_observer = {
            "sidecar_path": sidecar_path,
            "output_filename": output_filename,
            "cells": selected_cells,
            "missing_cell_ids": missing_cell_ids,
            "samples": [],
            "last_sample": [],
            "configured_cell_count": len(selected_cells),
            "max_discharge": {cell["cell_id"]: 0.0 for cell in selected_cells},
            "max_time_hours": {cell["cell_id"]: 0.0 for cell in selected_cells},
            "disabled_by_control": False,
        }
        return {
            "configured_cell_count": len(selected_cells),
            "missing_cell_ids": missing_cell_ids,
            "output_filename": output_filename,
            "disabled_by_control": False,
        }

    def configure_hydrograph_monitor_observer(
        self,
        cell_ids: List[int],
        *,
        sidecar_path: Optional[str] = None,
        output_filename: str = "HYDROGRAPH_EDDA.txt",
    ) -> Dict[str, Any]:
        """
        Configure original-EDDA-style monitored-cell HYDROGRAPH output.

        This is an observer/export chain only. It samples existing DFS face
        flux and concentration state at output checkpoints and does not change
        the runtime equations, boundary conditions, or inflow forcing.
        """
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before configuring hydrograph monitoring.")

        cell_id_grid = self.fields.cell_id.to_numpy()
        id_to_coord: Dict[int, Tuple[int, int]] = {}
        for i in range(cell_id_grid.shape[0]):
            for j in range(cell_id_grid.shape[1]):
                cell_id = int(cell_id_grid[i, j])
                if cell_id > 0:
                    id_to_coord[cell_id] = (i, j)

        selected_cells: List[Dict[str, int]] = []
        missing_cell_ids: List[int] = []
        for cell_id in cell_ids:
            coord = id_to_coord.get(int(cell_id))
            if coord is None:
                missing_cell_ids.append(int(cell_id))
                continue
            selected_cells.append({"cell_id": int(cell_id), "i": coord[0], "j": coord[1]})

        self.hydrograph_monitor_observer = {
            "sidecar_path": sidecar_path,
            "output_filename": output_filename,
            "cells": selected_cells,
            "missing_cell_ids": missing_cell_ids,
            "samples": [],
            "configured_cell_count": len(selected_cells),
            "max_discharge": {cell["cell_id"]: 0.0 for cell in selected_cells},
            "max_time_hours": {cell["cell_id"]: 0.0 for cell in selected_cells},
        }
        if selected_cells:
            self.hydrograph_monitor_observer["samples"].append(
                {
                    "time_hours": 0.0,
                    "cells": [
                        {"cell_id": int(cell["cell_id"]), "discharge_cms": 0.0, "cv": 0.0}
                        for cell in selected_cells
                    ],
                }
            )
        return {
            "configured_cell_count": len(selected_cells),
            "missing_cell_ids": missing_cell_ids,
            "output_filename": output_filename,
        }

    def configure_inflow_hydrograph_forcing(
        self,
        hydrographs: List[Dict[str, Any]],
        *,
        sidecar_path: Optional[str] = None,
        denominator_variant: Optional[str] = None,
        denominator_source: Optional[str] = None,
        denominator_basis: Optional[str] = None,
        denominator_direction: Optional[int] = None,
        denominator_fv_value: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Configure original-EDDA-style inflow hydrograph forcing for DFS runs.

        This only wires the sidecar-selected inflow pulses into the DFS staging
        fields. It does not alter the scientific update order.
        """
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before configuring inflow hydrograph forcing.")
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before configuring inflow forcing.")

        cell_id_grid = self.fields.cell_id.to_numpy()
        id_to_coord: Dict[int, Tuple[int, int]] = {}
        for i in range(cell_id_grid.shape[0]):
            for j in range(cell_id_grid.shape[1]):
                cell_id = int(cell_id_grid[i, j])
                if cell_id > 0:
                    id_to_coord[cell_id] = (i, j)

        configured_cells: List[Dict[str, Any]] = []
        missing_cell_ids: List[int] = []
        configured_preview: List[Dict[str, Any]] = []
        for hydrograph in hydrographs:
            cell_id = int(hydrograph["cell_id"])
            coord = id_to_coord.get(cell_id)
            if coord is None:
                missing_cell_ids.append(cell_id)
                continue
            series = hydrograph.get("series") or []
            times = [float(point["time_s"]) for point in series]
            discharges = [float(point["discharge_m3s"]) for point in series]
            cvs = [float(point["cv"]) for point in series]
            configured = {
                "cell_id": cell_id,
                "i": coord[0],
                "j": coord[1],
                "times_s": times,
                "discharges_m3s": discharges,
                "cvs": cvs,
            }
            configured_cells.append(configured)
            if len(configured_preview) < 10:
                configured_preview.append(
                    {
                        "cell_id": cell_id,
                        "i": coord[0],
                        "j": coord[1],
                        "pulse_count": len(times),
                        "first_time_s": times[0] if times else None,
                        "last_time_s": times[-1] if times else None,
                    }
                )

        self.dfs_dynamic_wave.configure_inflow_hydrographs(
            configured_cells,
            denominator_variant=denominator_variant,
            denominator_source=denominator_source,
            denominator_basis=denominator_basis,
            denominator_direction=denominator_direction,
            denominator_fv_value=denominator_fv_value,
        )
        self.inflow_hydrograph_config = {
            "sidecar_path": sidecar_path,
            "configured_cell_count": len(configured_cells),
            "missing_cell_ids": missing_cell_ids,
            "configured_preview": configured_preview,
            "inflow_denominator_variant": self.dfs_dynamic_wave.inflow_denominator_config.get("variant"),
            "inflow_denominator_source": self.dfs_dynamic_wave.inflow_denominator_config.get("source"),
            "inflow_denominator_basis": self.dfs_dynamic_wave.inflow_denominator_config.get("basis"),
            "inflow_denominator_direction": self.dfs_dynamic_wave.inflow_denominator_config.get("direction"),
            "inflow_denominator_fv_value": self.dfs_dynamic_wave.inflow_denominator_config.get("fv_value"),
        }
        return dict(self.inflow_hydrograph_config)

    def configure_rnoff_topoindex_runtime_hook(
        self,
        *,
        nxtfil: Optional[str] = None,
        ndxfil: Optional[str] = None,
        dscfil: Optional[str] = None,
        wffil: Optional[str] = None,
        imax: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Configure the default-off original RNOFF/TopoIndex runoff-routing hook.

        This only wires the validated TopoIndex sidecar family into the DFS
        staging lifecycle. The hook remains inert unless
        ``EDDA_EXPERIMENT_RNOFF_TOPOINDEX=1`` is set, and it must not mutate
        DFS face connectivity or equations.
        """
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before configuring RNOFF/TopoIndex runtime hook.")
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before configuring RNOFF/TopoIndex runtime hook.")

        configured = self.dfs_dynamic_wave.configure_rnoff_topoindex_runtime_hook(
            nxtfil=nxtfil,
            ndxfil=ndxfil,
            dscfil=dscfil,
            wffil=wffil,
            imax=imax,
        )
        self.rnoff_topoindex_runtime_hook_config = {
            "nxtfil": nxtfil,
            "ndxfil": ndxfil,
            "dscfil": dscfil,
            "wffil": wffil,
            "imax": imax,
        }
        self.rnoff_topoindex_runtime_manifest = dict(configured)
        return dict(configured)

    def apply_rnoff_topoindex_runtime_hook(self, dt: float) -> Dict[str, Any]:
        """
        Run the configured RNOFF/TopoIndex hook against current staged fields.

        This public entrypoint is used by full-solver smoke/oracle comparison
        harnesses. Normal solver execution calls the same DFS hook internally
        after surface forcing is staged.
        """
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before applying RNOFF/TopoIndex runtime hook.")
        manifest = self.dfs_dynamic_wave.apply_rnoff_topoindex_runtime_hook(dt)
        self.rnoff_topoindex_runtime_manifest = dict(manifest)
        return dict(manifest)

    def get_rnoff_topoindex_runtime_diagnostics(self) -> Dict[str, Any]:
        """Return latest solver-level RNOFF/TopoIndex runtime diagnostics."""
        if self.dfs_dynamic_wave is not None:
            self.rnoff_topoindex_runtime_manifest = self.dfs_dynamic_wave.get_rnoff_topoindex_runtime_manifest()
        return dict(self.rnoff_topoindex_runtime_manifest)

    def _rnoff_provider_one_based_values(
        self,
        values: Any,
        *,
        imax: int,
        name: str,
    ) -> Dict[int, float]:
        if values is None:
            raise ValueError(f"{name} is required for RNOFF native unsfin provider validation")
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        if isinstance(values, Mapping):
            converted: Dict[int, float] = {}
            for raw_key, raw_value in values.items():
                key = int(raw_key)
                if key < 1 or key > imax:
                    raise ValueError(f"{name} has out-of-range one-based cell id {key}")
                converted[key] = float(raw_value)
            return converted
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{name} must be numeric, not text")

        array = np.asarray(values, dtype=np.float64)
        if array.ndim == 2:
            if self.fields is None:
                raise RuntimeError("Solver fields must be initialized before grid values can be mapped by cell id.")
            cell_ids = np.asarray(self.fields.cell_id.to_numpy(), dtype=np.int64)
            if cell_ids.shape != array.shape:
                raise ValueError(f"{name} shape {array.shape} does not match cell_id shape {cell_ids.shape}")
            mapped: Dict[int, float] = {}
            for index in np.ndindex(array.shape):
                cell_id = int(cell_ids[index])
                if 1 <= cell_id <= imax:
                    mapped[cell_id] = float(array[index])
            if not mapped:
                raise ValueError(f"{name} did not map any active one-based cell ids")
            return mapped
        if array.ndim == 1:
            if array.size == imax:
                return {cell_id + 1: float(value) for cell_id, value in enumerate(array)}
            if array.size == imax + 1:
                return {cell_id: float(array[cell_id]) for cell_id in range(1, imax + 1)}
        raise ValueError(f"{name} must be a mapping, one-dimensional array, or two-dimensional grid")

    def _rnoff_provider_period_inputs(
        self,
        rideb_periods: Any,
        *,
        imax: int,
    ) -> List[Dict[int, float]]:
        if rideb_periods is None:
            if self.fields is None:
                raise RuntimeError("Solver fields must be initialized before default tempri can be used.")
            rideb_periods = [self.fields.tempri.to_numpy()]
        if isinstance(rideb_periods, Mapping):
            if any(isinstance(value, (Mapping, Sequence, np.ndarray)) and not isinstance(value, (str, bytes)) for value in rideb_periods.values()):
                return [
                    self._rnoff_provider_one_based_values(
                        rideb_periods[key],
                        imax=imax,
                        name=f"rideb_period[{key}]",
                    )
                    for key in sorted(rideb_periods)
                ]
            try:
                return [self._rnoff_provider_one_based_values(rideb_periods, imax=imax, name="rideb_periods")]
            except (TypeError, ValueError):
                pass
        if isinstance(rideb_periods, (str, bytes)):
            raise ValueError("rideb_periods must be numeric period arrays, not text")
        return [
            self._rnoff_provider_one_based_values(period, imax=imax, name=f"rideb_period[{index}]")
            for index, period in enumerate(rideb_periods, start=1)
        ]

    def validate_rnoff_native_unsfin_provider_runtime_path(
        self,
        *,
        nxtfil: Optional[str] = None,
        ndxfil: Optional[str] = None,
        dscfil: Optional[str] = None,
        wffil: Optional[str] = None,
        imax: Optional[int] = None,
        rideb_periods: Any = None,
        kst: Any = None,
        depth: Any = None,
        rizero: Any = None,
        provider_output_dir: Optional[str] = None,
        q_runtime_oracle_status: Optional[str] = None,
        bkgrof: bool = True,
        env: Optional[Mapping[str, str]] = None,
        provider_generator: Optional[Callable[..., Any]] = None,
        rnoff_schedule_generator: Optional[Callable[..., Any]] = None,
        provider_schedule_generation_enabled: bool = False,
        shadow_lifecycle_enabled: bool = False,
        shadow_window_start_s: float = 0.0,
        shadow_window_end_s: Optional[float] = None,
        schedule_target_cells: Optional[Sequence[int]] = None,
        ledger_window_s: float = DEFAULT_FULL_WINDOW_S,
    ) -> Dict[str, Any]:
        """Validate source-aligned RNOFF contract plumbing into native unsfin provider.

        This is explicitly a dry-run/provider validation path. It does not feed
        DFS runtime state, does not mutate final state, and keeps the existing
        DFS-internal RNOFF bridge available.
        """
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before RNOFF provider validation.")
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before RNOFF provider validation.")

        env_source = dict(os.environ if env is None else env)
        imax_value = int(imax or np.max(self.fields.cell_id.to_numpy()))
        enabled = rnoff_native_unsfin_feed_flag_enabled(env_source)
        shadow_gate_enabled = rnoff_dfs_shadow_feed_flag_enabled(env_source)
        manifest: Dict[str, Any] = {
            "rnoff_native_unsfin_provider_validation_enabled": enabled,
            "rnoff_topoindex_gate_enabled": str(env_source.get("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "")).strip() in {"1", "true", "True", "yes", "on"},
            "rnoff_native_unsfin_feed_gate_enabled": str(env_source.get("EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED", "")).strip() in {"1", "true", "True", "yes", "on"},
            "rnoff_dfs_shadow_feed_gate_enabled": shadow_gate_enabled,
            "native_unsfin_runtime_feed_enabled": runtime_feed_flag_enabled(dict(env_source)),
            "provider_dry_run_only": True,
            "rnoff_dfs_shadow_lifecycle_requested": bool(shadow_lifecycle_enabled),
            "shadow_lifecycle_active": False,
            "shadow_schedule_loaded": False,
            "shadow_crossing_count": 0,
            "shadow_candidate_stage_count": 0,
            "shadow_rejected_discard_count": 0,
            "shadow_accepted_commit_count": 0,
            "shadow_duplicate_fire_count": 0,
            "shadow_final_state_mutated": False,
            "schedule_consumed_by_dfs": False,
            "final_state_mutated": False,
            "changed_field_names": [],
            "current_dfs_internal_bridge_preserved": True,
            "rnoff_contract_loaded": False,
            "rik_period_loaded": False,
            "q_formula_validated": False,
            "q_runtime_oracle_status": q_runtime_oracle_status,
            "native_unsfin_rnoff_feed_active": False,
            "schedule_generated_with_rnoff": False,
            "provider_schedule_generation_active": False,
            "dfs_runtime_feed_blocked": False,
            "fallback_reason": None,
            "provider_result_status": None,
            "provider_blocked_reason": None,
            "precompute_contract_period_count": 0,
            "precompute_contract_sidecar_shape_validated": False,
            "precompute_contract_fail_closed": False,
            "precompute_contract_blocked_reason": None,
            "dfs_source_staging_kernel_gate_enabled": False,
            "dfs_source_staging_kernel_required_gates_active": False,
            "dfs_source_staging_kernel_active": False,
            "source_staging_kernel_vs_cpu_match": None,
            "kernel_fallback_active": False,
            "kernel_fallback_reason": None,
            "kernel_candidate_stage_count": 0,
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": 0,
            "project_cuda_backend_stage1_gate_enabled": False,
            "project_cuda_backend_stage1_active": False,
            "project_cuda_backend_stage1_components": [],
            "cuda_backend_stage1_active": False,
            "cuda_backend_stage1_component_count": 0,
        }
        if not enabled:
            manifest["fallback_reason"] = RNOFF_NATIVE_FEED_FLAG_DISABLED_REASON
            self.rnoff_native_unsfin_provider_manifest = dict(manifest)
            return dict(manifest)
        if shadow_lifecycle_enabled and not shadow_gate_enabled:
            manifest["dfs_runtime_feed_blocked"] = True
            manifest["fallback_reason"] = RNOFF_DFS_SHADOW_FEED_FLAG_DISABLED_REASON
            self.rnoff_native_unsfin_provider_manifest = dict(manifest)
            return dict(manifest)

        kst_values = self._rnoff_provider_one_based_values(
            kst if kst is not None else self.fields.K_sat_top_field.to_numpy(),
            imax=imax_value,
            name="kst",
        )
        depth_source = depth
        if depth_source is None and hasattr(self.dfs_dynamic_wave, "depthwt0_field"):
            depth_source = self.dfs_dynamic_wave.depthwt0_field.to_numpy()
        rizero_source = rizero
        if rizero_source is None and hasattr(self.dfs_dynamic_wave, "rizero0_field"):
            rizero_source = self.dfs_dynamic_wave.rizero0_field.to_numpy()
        depth_values = self._rnoff_provider_one_based_values(depth_source, imax=imax_value, name="depth")
        rikzero_values = self._rnoff_provider_one_based_values(rizero_source, imax=imax_value, name="rikzero")
        period_inputs = self._rnoff_provider_period_inputs(rideb_periods, imax=imax_value)

        contract = build_rnoff_pre_dfs_period_precompute_contract(
            nxtfil=nxtfil,
            ndxfil=ndxfil,
            dscfil=dscfil,
            wffil=wffil,
            imax=imax_value,
            rideb_periods=period_inputs,
            kst=kst_values,
            depth=depth_values,
            rizero=rikzero_values,
            environ=env_source,
            diagnostic_request=False,
            case_path=Path(self.config.dem_file).parent,
            provenance_note="EDDASolver source-aligned RNOFF native unsfin provider dry-run validation",
        )
        contract_manifest = dict(contract.manifest)
        manifest.update(
            {
                "precompute_contract_period_count": int(contract_manifest.get("period_count", 0)),
                "precompute_contract_sidecar_shape_validated": bool(contract_manifest.get("sidecar_shape_validated", False)),
                "precompute_contract_fail_closed": bool(contract_manifest.get("fail_closed", False)),
                "precompute_contract_blocked_reason": contract_manifest.get("blocked_reason"),
            }
        )
        if contract_manifest.get("fail_closed") or not contract_manifest.get("sidecar_shape_validated"):
            manifest["fallback_reason"] = contract_manifest.get("blocked_reason")
            self.rnoff_native_unsfin_provider_manifest = dict(manifest)
            return dict(manifest)

        output_dir = Path(provider_output_dir) if provider_output_dir is not None else self.output_dir / "rnoff_native_unsfin_provider_validation"
        request = NativeUnsfinDryRunRequest(
            case_dir=Path(self.config.dem_file).parent,
            output_dir=output_dir,
            provider_selected=True,
            dry_run_enabled=True,
            runtime_feed_enabled=False,
            ledger_window_s=ledger_window_s,
            rnoff_native_unsfin_feed_enabled=True,
            rnoff_contract=contract,
            rnoff_contract_kst=kst_values,
            rnoff_contract_rikzero=rikzero_values,
            rnoff_contract_bkgrof=bkgrof,
            rnoff_q_runtime_oracle_status=q_runtime_oracle_status,
            rnoff_provider_schedule_generation_enabled=provider_schedule_generation_enabled,
            rnoff_schedule_target_cells=schedule_target_cells,
        )
        if provider_schedule_generation_enabled and runtime_feed_flag_enabled(dict(env_source)):
            runtime_request = NativeUnsfinDryRunRequest(
                case_dir=request.case_dir,
                output_dir=request.output_dir,
                provider_selected=True,
                dry_run_enabled=True,
                runtime_feed_enabled=True,
                ledger_window_s=request.ledger_window_s,
                checkpoint_dir=request.checkpoint_dir,
                resume=request.resume,
                checkpoint_interval=request.checkpoint_interval,
                metadata_overrides=request.metadata_overrides,
                rnoff_native_unsfin_feed_enabled=True,
                rnoff_contract=contract,
                rnoff_contract_kst=kst_values,
                rnoff_contract_rikzero=rikzero_values,
                rnoff_contract_bkgrof=bkgrof,
                rnoff_q_runtime_oracle_status=q_runtime_oracle_status,
                rnoff_provider_schedule_generation_enabled=True,
                rnoff_schedule_target_cells=schedule_target_cells,
                rnoff_schedule_initial_ts=request.rnoff_schedule_initial_ts,
            )
            runtime_result = configure_provider_runtime_feed(
                self,
                runtime_request,
                env=dict(env_source),
                generator=provider_generator,
                rnoff_schedule_generator=rnoff_schedule_generator,
            )
            runtime_info = dict(runtime_result.meta.get("runtime_schedule_info") or {})
            manifest.update(
                {
                    "provider_dry_run_only": False,
                    "provider_result_status": runtime_result.status,
                    "provider_blocked_reason": runtime_result.blocked_reason,
                    "provider_artifact_paths": dict(runtime_result.artifact_paths),
                    "rnoff_contract_loaded": bool(runtime_result.meta.get("rnoff_contract_loaded", False)),
                    "rik_period_loaded": bool(runtime_result.meta.get("rik_period_loaded", False)),
                    "q_formula_validated": bool(runtime_result.meta.get("q_formula_validated", False)),
                    "q_runtime_oracle_status": runtime_result.meta.get("q_runtime_oracle_status"),
                    "native_unsfin_rnoff_feed_active": bool(runtime_result.meta.get("native_unsfin_rnoff_feed_active", False)),
                    "schedule_generated_with_rnoff": bool(runtime_result.meta.get("schedule_generated_with_rnoff", False)),
                    "provider_schedule_generation_active": bool(runtime_result.meta.get("provider_schedule_generation_active", False)),
                    "dfs_runtime_feed_blocked": bool(runtime_result.meta.get("dfs_runtime_feed_blocked", False)),
                    "rnoff_dfs_runtime_feed_active": bool(runtime_result.meta.get("rnoff_dfs_runtime_feed_active", False)),
                    "schedule_consumed_by_dfs": bool(runtime_result.meta.get("schedule_consumed_by_dfs", False)),
                    "final_state_mutated": bool(runtime_result.meta.get("final_state_mutated", False)),
                    "changed_field_names": list(runtime_result.meta.get("changed_field_names", [])),
                    "fallback_reason": runtime_result.meta.get("fallback_reason"),
                    "rnoff_gpu_field_feed_gate_enabled": bool(
                        runtime_result.meta.get("rnoff_gpu_field_feed_gate_enabled", False)
                    ),
                    "rnoff_gpu_field_feed_active": bool(
                        runtime_result.meta.get("rnoff_gpu_field_feed_active", False)
                    ),
                    "schedule_buffer_uploaded_to_taichi": bool(
                        runtime_result.meta.get("schedule_buffer_uploaded_to_taichi", False)
                    ),
                    "taichi_schedule_buffer_roundtrip_ok": runtime_result.meta.get(
                        "taichi_schedule_buffer_roundtrip_ok"
                    ),
                    "taichi_schedule_buffer_fallback_reason": runtime_result.meta.get(
                        "taichi_schedule_buffer_fallback_reason"
                    ),
                    "dfs_source_staging_field_gate_enabled": bool(
                        runtime_result.meta.get("dfs_source_staging_field_gate_enabled", False)
                    ),
                    "dfs_source_staging_field_active": bool(
                        runtime_result.meta.get("dfs_source_staging_field_active", False)
                    ),
                    "source_staging_field_roundtrip_ok": runtime_result.meta.get(
                        "source_staging_field_roundtrip_ok"
                    ),
                    "source_staging_cpu_vs_taichi_match": runtime_result.meta.get(
                        "source_staging_cpu_vs_taichi_match"
                    ),
                    "dfs_source_staging_fast_consume_gate_enabled": bool(
                        runtime_result.meta.get("dfs_source_staging_fast_consume_gate_enabled", False)
                    ),
                    "dfs_source_staging_fast_consume_active": bool(
                        runtime_result.meta.get("dfs_source_staging_fast_consume_active", False)
                    ),
                    "parity_validation_mode": runtime_result.meta.get("parity_validation_mode"),
                    "per_stage_parity_download_disabled": bool(
                        runtime_result.meta.get("per_stage_parity_download_disabled", False)
                    ),
                    "dfs_source_staging_kernel_gate_enabled": bool(
                        runtime_result.meta.get("dfs_source_staging_kernel_gate_enabled", False)
                    ),
                    "dfs_source_staging_kernel_required_gates_active": bool(
                        runtime_result.meta.get("dfs_source_staging_kernel_required_gates_active", False)
                    ),
                    "dfs_source_staging_kernel_active": bool(
                        runtime_result.meta.get("dfs_source_staging_kernel_active", False)
                    ),
                    "source_staging_kernel_vs_cpu_match": runtime_result.meta.get(
                        "source_staging_kernel_vs_cpu_match"
                    ),
                    "project_cuda_backend_stage1_gate_enabled": bool(
                        runtime_result.meta.get("project_cuda_backend_stage1_gate_enabled", False)
                    ),
                    "project_cuda_backend_stage1_active": bool(
                        runtime_result.meta.get("project_cuda_backend_stage1_active", False)
                    ),
                    "project_cuda_backend_stage1_components": list(
                        runtime_result.meta.get("project_cuda_backend_stage1_components", [])
                    ),
                    "project_cuda_backend_stage1_field_lifecycle": runtime_result.meta.get(
                        "project_cuda_backend_stage1_field_lifecycle"
                    ),
                    "cuda_backend_stage1_active": bool(runtime_result.meta.get("cuda_backend_stage1_active", False)),
                    "cuda_backend_stage1_component_count": int(
                        runtime_result.meta.get("cuda_backend_stage1_component_count", 0) or 0
                    ),
                    "transfer_bytes_h2d": int(runtime_result.meta.get("transfer_bytes_h2d", 0) or 0),
                    "transfer_bytes_d2h": int(runtime_result.meta.get("transfer_bytes_d2h", 0) or 0),
                    "kernel_fallback_active": bool(runtime_result.meta.get("kernel_fallback_active", False)),
                    "kernel_fallback_reason": runtime_result.meta.get("kernel_fallback_reason"),
                    "kernel_candidate_stage_count": int(
                        runtime_result.meta.get("kernel_candidate_stage_count", 0) or 0
                    ),
                    "kernel_h2d_bytes": int(runtime_result.meta.get("kernel_h2d_bytes", 0) or 0),
                    "kernel_d2h_bytes": int(runtime_result.meta.get("kernel_d2h_bytes", 0) or 0),
                    "dfs_source_staging_field_fallback_reason": runtime_result.meta.get(
                        "dfs_source_staging_field_fallback_reason"
                    ),
                    "rnoff_provider_feed": runtime_result.meta.get("rnoff_provider_feed"),
                    "rnoff_provider_schedule": runtime_result.meta.get("rnoff_provider_schedule"),
                    "rnoff_runtime_feed_summary": runtime_result.meta.get("rnoff_runtime_feed_summary"),
                    "runtime_schedule_info": runtime_info,
                    "committed_fire_count": int(runtime_info.get("committed_fired_count", 0) or 0),
                    "rejected_step_discard_count": int(runtime_info.get("rejected_step_discard_count", 0) or 0),
                    "duplicate_fire_count": int(runtime_info.get("duplicate_fire_count", 0) or 0),
                    "gindx_zero_no_feed_count": int(runtime_result.meta.get("gindx_zero_no_feed_count", 0) or 0),
                }
            )
            self.rnoff_native_unsfin_provider_manifest = dict(manifest)
            return dict(manifest)
        result = run_provider_dry_run(
            request,
            generator=provider_generator,
            rnoff_schedule_generator=rnoff_schedule_generator,
        )
        manifest.update(
            {
                "provider_result_status": result.status,
                "provider_blocked_reason": result.blocked_reason,
                "provider_artifact_paths": dict(result.artifact_paths),
                "rnoff_contract_loaded": bool(result.meta.get("rnoff_contract_loaded", False)),
                "rik_period_loaded": bool(result.meta.get("rik_period_loaded", False)),
                "q_formula_validated": bool(result.meta.get("q_formula_validated", False)),
                "q_runtime_oracle_status": result.meta.get("q_runtime_oracle_status"),
                "native_unsfin_rnoff_feed_active": bool(result.meta.get("native_unsfin_rnoff_feed_active", False)),
                "schedule_generated_with_rnoff": bool(result.meta.get("schedule_generated_with_rnoff", False)),
                "provider_schedule_generation_active": bool(result.meta.get("provider_schedule_generation_active", False)),
                "dfs_runtime_feed_blocked": bool(result.meta.get("dfs_runtime_feed_blocked", False)),
                "schedule_consumed_by_dfs": False,
                "fallback_reason": result.meta.get("fallback_reason"),
                "rnoff_provider_feed": result.meta.get("rnoff_provider_feed"),
                "rnoff_provider_schedule": result.meta.get("rnoff_provider_schedule"),
            }
        )
        if shadow_lifecycle_enabled:
            shadow_manifest = self._run_rnoff_provider_shadow_lifecycle(
                result=result,
                output_dir=output_dir,
                window_start_s=shadow_window_start_s,
                window_end_s=shadow_window_end_s,
            )
            manifest.update(shadow_manifest)
        self.rnoff_native_unsfin_provider_manifest = dict(manifest)
        return dict(manifest)

    def get_rnoff_native_unsfin_provider_diagnostics(self) -> Dict[str, Any]:
        """Return latest source-aligned RNOFF native unsfin provider validation manifest."""
        return dict(self.rnoff_native_unsfin_provider_manifest)

    @staticmethod
    def _write_dict_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(str(key))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys or ["phase"])
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in keys})

    def _run_rnoff_provider_shadow_lifecycle(
        self,
        *,
        result: Any,
        output_dir: Path,
        window_start_s: float,
        window_end_s: Optional[float],
    ) -> Dict[str, Any]:
        manifest: Dict[str, Any] = {
            "shadow_lifecycle_active": False,
            "shadow_schedule_loaded": False,
            "shadow_crossing_count": 0,
            "shadow_candidate_stage_count": 0,
            "shadow_rejected_discard_count": 0,
            "shadow_accepted_commit_count": 0,
            "shadow_duplicate_fire_count": 0,
            "shadow_final_state_mutated": False,
            "schedule_consumed_by_dfs": False,
            "final_state_mutated": False,
            "changed_field_names": [],
            "dfs_runtime_feed_blocked": True,
            "shadow_artifact_paths": {},
        }
        if result.status != "generated" or not result.meta.get("schedule_generated_with_rnoff"):
            manifest["fallback_reason"] = result.blocked_reason or "RNOFF_PROVIDER_SCHEDULE_DIAGNOSTICS_MISSING"
            return manifest
        schedule_json = result.artifact_paths.get("rnoff_schedule_summary")
        if not schedule_json:
            manifest["fallback_reason"] = "RNOFF_PROVIDER_SCHEDULE_DIAGNOSTICS_MISSING"
            return manifest
        payload = json.loads(Path(schedule_json).read_text(encoding="utf-8"))
        rows = payload.get("rows")
        if not isinstance(rows, list):
            manifest["fallback_reason"] = "RNOFF_PROVIDER_SCHEDULE_DIAGNOSTICS_MALFORMED"
            return manifest

        shadow = self.dfs_dynamic_wave.run_rnoff_provider_schedule_shadow_lifecycle(
            rows,
            t_start_s=window_start_s,
            t_end_s=window_end_s,
            source_meta={
                "provider_artifact": schedule_json,
                "provider_result_status": result.status,
            },
        )
        event_rows = list(shadow.get("events", []))
        shadow_dir = output_dir / "rnoff_dfs_shadow_lifecycle"
        events_path = shadow_dir / "rnoff_dfs_shadow_events.csv"
        summary_path = shadow_dir / "rnoff_dfs_shadow_lifecycle.json"
        self._write_dict_rows_csv(events_path, event_rows)
        summary_payload = {
            "mode": "rnoff_dfs_shadow_lifecycle",
            "shadow_final_state_mutated": False,
            "schedule_consumed_by_dfs": False,
            "dfs_runtime_feed_blocked": True,
            "summary": {key: value for key, value in shadow.items() if key != "events"},
            "events": event_rows,
        }
        summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

        return {
            "shadow_lifecycle_active": True,
            "shadow_schedule_loaded": bool(shadow.get("shadow_schedule_loaded", False)),
            "shadow_crossing_count": int(shadow.get("shadow_crossing_count", 0) or 0),
            "shadow_candidate_stage_count": int(shadow.get("shadow_candidate_stage_count", 0) or 0),
            "shadow_rejected_discard_count": int(shadow.get("shadow_rejected_discard_count", 0) or 0),
            "shadow_accepted_commit_count": int(shadow.get("shadow_accepted_commit_count", 0) or 0),
            "shadow_duplicate_fire_count": int(shadow.get("shadow_duplicate_fire_count", 0) or 0),
            "shadow_final_state_mutated": False,
            "schedule_consumed_by_dfs": False,
            "final_state_mutated": False,
            "changed_field_names": [],
            "dfs_runtime_feed_blocked": True,
            "fallback_reason": None,
            "rnoff_dfs_shadow_lifecycle": {key: value for key, value in shadow.items() if key != "events"},
            "shadow_artifact_paths": {
                "events": str(events_path),
                "summary": str(summary_path),
            },
        }

    def configure_stormdrain_runtime_hook(
        self,
        *,
        drainage_path: Optional[str] = None,
        expected_node_count: Optional[int] = None,
        expected_conduit_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Configure the default-off original stormdrain topology hook.

        This hook only loads and validates ``drainage.txt`` topology behind
        ``EDDA_EXPERIMENT_STORMDRAIN=1``. It does not mutate DFS equations,
        face connectivity, hydrograph output selection, inflow forcing, native
        unsfin scheduling, provider defaults, or RNOFF behavior.
        """
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before configuring stormdrain runtime hook.")
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before configuring stormdrain runtime hook.")

        configured = self.dfs_dynamic_wave.configure_stormdrain_runtime_hook(
            drainage_path=drainage_path,
            expected_node_count=expected_node_count,
            expected_conduit_count=expected_conduit_count,
        )
        self.stormdrain_runtime_hook_config = {
            "drainage_path": drainage_path,
            "expected_node_count": expected_node_count,
            "expected_conduit_count": expected_conduit_count,
        }
        self.stormdrain_runtime_manifest = dict(configured)
        return dict(configured)

    def apply_stormdrain_runtime_hook(self, dt: float) -> Dict[str, Any]:
        """
        Run the configured stormdrain hook against current DFS topology state.

        The public entrypoint is used by focused smoke/oracle comparison tests.
        Normal DFS execution calls the same hook internally after surface
        forcing is staged.
        """
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before applying stormdrain runtime hook.")
        manifest = self.dfs_dynamic_wave.apply_stormdrain_runtime_hook(dt)
        self.stormdrain_runtime_manifest = dict(manifest)
        return dict(manifest)

    def get_stormdrain_runtime_diagnostics(self) -> Dict[str, Any]:
        """Return latest solver-level stormdrain runtime diagnostics."""
        if self.dfs_dynamic_wave is not None:
            self.stormdrain_runtime_manifest = self.dfs_dynamic_wave.get_stormdrain_runtime_manifest()
        return dict(self.stormdrain_runtime_manifest)

    def configure_precomputed_failure_schedule(
        self,
        *,
        tfail_s: np.ndarray,
        gindx: np.ndarray,
        fdepth_m: np.ndarray,
        taichi_field_feed_enabled: bool | None = None,
        source_staging_field_enabled: bool | None = None,
        source_staging_fast_consume_enabled: bool | None = None,
        source_staging_kernel_enabled: bool | None = None,
        source_staging_kernel_required_gates_active: bool | None = None,
    ) -> Dict[str, Any]:
        if self.fields is None:
            raise RuntimeError("Solver must be initialized before configuring a precomputed failure schedule.")
        if self.dfs_dynamic_wave is None:
            raise RuntimeError("DFS dynamic-wave solver must be initialized before configuring a failure schedule.")
        return self.dfs_dynamic_wave.configure_precomputed_failure_schedule(
            tfail_s=tfail_s,
            gindx=gindx,
            fdepth_m=fdepth_m,
            taichi_field_feed_enabled=taichi_field_feed_enabled,
            source_staging_field_enabled=source_staging_field_enabled,
            source_staging_fast_consume_enabled=source_staging_fast_consume_enabled,
            source_staging_kernel_enabled=source_staging_kernel_enabled,
            source_staging_kernel_required_gates_active=source_staging_kernel_required_gates_active,
        )

    def get_runtime_source_chain_diagnostics(self) -> Dict[str, Any]:
        """Return post-run source-chain diagnostics when DFS runtime is active."""
        if self.dfs_dynamic_wave is None:
            return {
                "schedule_runtime_diagnostics": {"configured": False},
                "rnoff_topoindex_runtime": self.get_rnoff_topoindex_runtime_diagnostics(),
                "stormdrain_runtime": self.get_stormdrain_runtime_diagnostics(),
                "scheduled_cell_count": 0,
                "consumed_count": 0,
                "fired_cell_count": 0,
                "failure_source_flow_depth_sum": 0.0,
                "failure_source_mass_sum": 0.0,
                "Cv_max": 0.0,
                "Cv_sum": 0.0,
                "erosion_rate_max": 0.0,
                "erosion_rate_sum": 0.0,
                "deposition_rate_max": 0.0,
                "deposition_rate_sum": 0.0,
                "Deposit_depth_sum": 0.0,
                "Erosion_depth_sum": 0.0,
                "Flow_depth_sum": 0.0,
            }
        diagnostics = self.dfs_dynamic_wave.get_runtime_source_chain_diagnostics()
        diagnostics["rnoff_topoindex_runtime"] = self.get_rnoff_topoindex_runtime_diagnostics()
        diagnostics["stormdrain_runtime"] = self.get_stormdrain_runtime_diagnostics()
        return diagnostics

    def _observe_numerical_step(
        self,
        step_info: Dict[str, Any],
        *,
        accepted: bool,
        attempted_dt: float,
        force_volume: bool = False,
    ) -> None:
        """Collect scalar retry/volume evidence without changing the solver.

        This is intentionally called after the existing physics step has made
        its accept/reject decision.  The values are used only for the final
        audit manifest and therefore cannot affect a retry, output, or state
        commit.
        """

        attempted_dt = float(attempted_dt)
        compute = getattr(self.config, "compute", None)
        observe_stride = max(1, int(getattr(compute, "numerical_observe_stride", 20) or 20))
        candidate_id = int(getattr(self, "dfs_candidate_step_id", 0) or 0)
        sample_volume = (
            force_volume
            or (not accepted)
            or (candidate_id <= 1)
            or (observe_stride <= 1)
            or (candidate_id % observe_stride == 0)
        )
        if sample_volume and self.dfs_dynamic_wave is not None:
            try:
                volume = self.dfs_dynamic_wave.get_volume_balance_snapshot()
                self.numerical_observe_count += 1
                relative_error = float(volume.get("relative_error", 0.0) or 0.0)
                if np.isfinite(relative_error):
                    self.numerical_max_abs_relative_error = max(
                        self.numerical_max_abs_relative_error,
                        abs(relative_error),
                    )
                    if accepted and abs(relative_error) > 1.0e-3:
                        self.numerical_volume_violation_count += 1
                else:
                    self.numerical_nonfinite_counts["volume_relative_error"] = (
                        self.numerical_nonfinite_counts.get("volume_relative_error", 0) + 1
                    )
            except Exception as exc:
                self.numerical_nonfinite_counts["volume_snapshot_error"] = (
                    self.numerical_nonfinite_counts.get("volume_snapshot_error", 0) + 1
                )
                logger.debug("Unable to capture numerical volume snapshot: %s", exc)

        if attempted_dt <= float(self.config.time.dt_min) * (1.0 + 1.0e-12):
            self.numerical_dt_min_hits += 1

        if accepted:
            used_dt = float(step_info.get("used_dt", attempted_dt))
            self.numerical_dt_history.append(used_dt)
            return

        first_reject = step_info.get("first_reject") or {}
        reason_name = str(first_reject.get("first_reject_reason_name") or "unknown")
        self.numerical_reject_reasons[reason_name] = (
            self.numerical_reject_reasons.get(reason_name, 0) + 1
        )
        if reason_name not in self.numerical_reject_examples:
            self.numerical_reject_examples[reason_name] = {
                "t_start_s": float(
                    first_reject.get(
                        "t_start_s",
                        self.time_stepper.t_current if self.time_stepper is not None else 0.0,
                    )
                    or (self.time_stepper.t_current if self.time_stepper is not None else 0.0)
                ),
                "dt_s": attempted_dt,
                "value": first_reject.get("value"),
                "threshold": first_reject.get("threshold"),
                "cell_id": first_reject.get("cell_id"),
                "neighbor_cell_id": first_reject.get("neighbor_cell_id"),
                "direction_one_based": first_reject.get("direction_one_based"),
            }

    def get_numerical_diagnostics(self, *, status: Optional[str] = None) -> Dict[str, Any]:
        """Build a JSON-safe numerical audit snapshot for the current run."""

        time_stepper = self.time_stepper
        stats = time_stepper.get_statistics() if time_stepper is not None else {}
        dt_values = np.asarray(self.numerical_dt_history, dtype=np.float64)
        if dt_values.size:
            dt_stats: Dict[str, Any] = {
                "accepted_min_s": float(np.min(dt_values)),
                "accepted_max_s": float(np.max(dt_values)),
                "accepted_mean_s": float(np.mean(dt_values)),
                "accepted_std_s": float(np.std(dt_values)),
            }
        else:
            dt_stats = {
                "accepted_min_s": None,
                "accepted_max_s": None,
                "accepted_mean_s": None,
                "accepted_std_s": None,
            }

        volume: Dict[str, Any] = {
            "rainfall_m3": 0.0,
            "inflow_m3": 0.0,
            "erosion_m3": 0.0,
            "failure_source_m3": 0.0,
            "infiltration_m3": 0.0,
            "outflow_m3": 0.0,
            "deposition_flux_m3": 0.0,
            "flow_storage_m3": 0.0,
            "deposit_storage_m3": 0.0,
            "source_total_m3": 0.0,
            "sink_and_storage_total_m3": 0.0,
            "denominator_m3": 0.0,
            "residual_m3": 0.0,
            "relative_error": 0.0,
            "within_retry_tolerance": True,
        }
        trigger_inventory = 0.0
        if self.dfs_dynamic_wave is not None:
            try:
                volume.update(self.dfs_dynamic_wave.get_volume_balance_snapshot())
            except Exception as exc:
                logger.debug("Unable to capture final numerical volume snapshot: %s", exc)
            try:
                trigger_grid = np.asarray(self.dfs_dynamic_wave.triggerslide_field.to_numpy(), dtype=np.float64)
                area_grid = np.asarray(self.fields.cell_area_cal.to_numpy(), dtype=np.float64)
                active_grid = np.asarray(self.fields.is_nodata.to_numpy(), dtype=np.int32) == 0
                finite = np.isfinite(trigger_grid) & np.isfinite(area_grid) & active_grid
                trigger_inventory = float(np.sum(np.maximum(trigger_grid[finite], 0.0) * area_grid[finite]))
            except Exception as exc:
                logger.debug("Unable to calculate trigger inventory: %s", exc)

        nonfinite_counts = dict(self.numerical_nonfinite_counts)
        if self.fields is not None:
            active_mask = np.asarray(self.fields.is_nodata.to_numpy(), dtype=np.int32) == 0
            for field_name in ("h", "u", "v", "rho", "Cv", "erosion_depth", "deposition_depth", "FS"):
                field = getattr(self.fields, field_name, None)
                if field is None:
                    continue
                try:
                    values = np.asarray(field.to_numpy())
                    nonfinite_counts[field_name] = int(np.count_nonzero(~np.isfinite(values[active_mask])))
                except Exception:
                    nonfinite_counts[field_name] = -1

        global_relative_error = float(volume.get("relative_error", 0.0) or 0.0)
        return {
            "schema_version": 1,
            "status": status or ("running" if time_stepper and not time_stepper.is_finished() else "completed"),
            "simulation": {
                "current_time_s": float(time_stepper.t_current) if time_stepper is not None else 0.0,
                "end_time_s": float(time_stepper.t_end) if time_stepper is not None else float(self.config.time.t_end),
                "output_count": int(time_stepper.output_count) if time_stepper is not None else 0,
            },
            "backend": dict(self.backend_snapshot),
            "time_integration": {
                "accepted_steps": int(self.dfs_accepted_step_id),
                "candidate_steps": int(self.dfs_candidate_step_id),
                "rejected_steps": int(time_stepper.rejected_steps) if time_stepper is not None else 0,
                "rejection_reasons": dict(self.numerical_reject_reasons),
                "rejection_examples": dict(self.numerical_reject_examples),
                "dt_min_configured_s": float(self.config.time.dt_min),
                "dt_max_configured_s": float(self.config.time.dt_max),
                "dt_min_hits": int(self.numerical_dt_min_hits),
                "dt": dt_stats,
                "time_stepper": {
                    "step_count": int(stats.get("step_count", 0) or 0),
                    "total_steps": int(stats.get("total_steps", 0) or 0),
                    "current_dt_s": float(stats.get("dt_current", 0.0) or 0.0),
                },
            },
            "local_conservation": {
                "tolerance": 1.0e-3,
                "max_abs_relative_error": float(self.numerical_max_abs_relative_error),
                "accepted_step_violation_count": int(self.numerical_volume_violation_count),
                "observe_stride": max(
                    1,
                    int(getattr(getattr(self.config, "compute", None), "numerical_observe_stride", 20) or 20),
                ),
                "observe_count": int(getattr(self, "numerical_observe_count", 0) or 0),
                "last_step": dict(volume),
            },
            "global_volume_ledger": {
                **volume,
                "tolerance": 1.0e-3,
                "passed": abs(global_relative_error) <= 1.0e-3,
                "trigger_inventory_available_m3": trigger_inventory,
                "trigger_inventory_role": "input inventory diagnostic; failure_source_m3 is the closure term",
                "drainage_m3": 0.0,
                "drainage_role": "no independent drainage volume counter is active in the current EDDA path",
            },
            "nonfinite_counts": nonfinite_counts,
            "classification": {
                "functional_e2e": None,
                "conservation_closure": abs(global_relative_error) <= 1.0e-3,
                "strict_code_parity": None,
                "discretization_convergence": "not_assessed",
            },
        }

    def _update_outflow_process_state(self, dt_used: float) -> None:
        observer = getattr(self, "outflow_process_observer", None)
        if not observer or not observer["cells"]:
            return
        if dt_used <= 0.0:
            return

        if self._use_fortran_dfs() and hasattr(
            self.dfs_dynamic_wave, "get_last_accepted_outflow_samples"
        ):
            last_sample = self.dfs_dynamic_wave.get_last_accepted_outflow_samples(
                observer["cells"], dt_used=dt_used
            )
        else:
            h = self.fields.h.to_numpy()
            rho = self.fields.rho.to_numpy()
            cell_area = float(self.fields.dx * self.fields.dy)
            rho_water = float(self.config.rheology.rho_water)
            rho_sediment = float(self.config.rheology.rho_sediment)
            density_span = rho_sediment - rho_water
            last_sample = []
            for cell in observer["cells"]:
                i = cell["i"]
                j = cell["j"]
                discharge = float(h[i, j] * cell_area / dt_used)
                cv = 0.0 if density_span <= 0.0 else max(
                    float((rho[i, j] - rho_water) / density_span), 0.0
                )
                last_sample.append(
                    {
                        "cell_id": int(cell["cell_id"]),
                        "discharge_cms": discharge,
                        "cv": cv,
                    }
                )

        time_hours = float(self.time_stepper.t_current / 3600.0)
        for sample in last_sample:
            cell_id = int(sample["cell_id"])
            discharge = float(sample["discharge_cms"])
            if discharge > observer["max_discharge"][cell_id]:
                observer["max_discharge"][cell_id] = discharge
                observer["max_time_hours"][cell_id] = time_hours

        observer["last_sample"] = last_sample

    def _record_outflow_process_output_sample(self) -> None:
        observer = getattr(self, "outflow_process_observer", None)
        if not observer or not observer["last_sample"]:
            return
        observer["samples"].append(
            {
                "time_hours": float(self.time_stepper.t_current / 3600.0),
                "cells": [dict(sample) for sample in observer["last_sample"]],
            }
        )

    def _export_outflow_process_text(self) -> Optional[Path]:
        plan = getattr(self, "edda_runtime_control_plan", None)
        if plan is not None and not plan.output_enabled(
            "save_outflow_process", compatibility_default=True
        ):
            return None
        observer = getattr(self, "outflow_process_observer", None)
        if not observer:
            return None
        if not observer["cells"]:
            return None
        if not self.outflow_process_observer["samples"]:
            return None

        output_path = self.output_dir / self.outflow_process_observer["output_filename"]
        output_path.parent.mkdir(parents=True, exist_ok=True)

        samples = self.outflow_process_observer["samples"]
        samples_by_cell = {
            int(cell["cell_id"]): [] for cell in self.outflow_process_observer["cells"]
        }
        for sample in samples:
            time_hours = float(sample["time_hours"])
            for cell_sample in sample["cells"]:
                samples_by_cell[int(cell_sample["cell_id"])].append(
                    {
                        "time_hours": time_hours,
                        "discharge_cms": float(cell_sample["discharge_cms"]),
                    }
                )

        with output_path.open("w", encoding="utf-8", newline="\n") as handle:
            for cell in self.outflow_process_observer["cells"]:
                cell_id = int(cell["cell_id"])
                max_q = self.outflow_process_observer["max_discharge"][cell_id]
                max_t = self.outflow_process_observer["max_time_hours"][cell_id]
                handle.write(
                    f"THE MAX Q AT OUTFLOW ELEMENT: {cell_id:6d}IS: {max_q:6.2f} CM/s AT TIME: {max_t:6.2f}\n"
                )
            for cell in self.outflow_process_observer["cells"]:
                cell_id = int(cell["cell_id"])
                handle.write(f"{'ELEMENT':<14}{'TIME (HRS)':<15}{'DISCHARGE (CMS)'}\n")
                cell_series = samples_by_cell[cell_id]
                for index, sample in enumerate(cell_series):
                    if index == 0:
                        handle.write(
                            f"{cell_id:6d}{sample['time_hours']:14.2f}{sample['discharge_cms']:15.2f}\n"
                        )
                    else:
                        handle.write(
                            f"{'':6}{sample['time_hours']:14.2f}{sample['discharge_cms']:15.2f}\n"
                        )

        return output_path

    def _collect_hydrograph_monitor_samples(self) -> List[Dict[str, float]]:
        observer = getattr(self, "hydrograph_monitor_observer", None)
        if not observer or not observer["cells"]:
            return []
        if self.dfs_dynamic_wave is None:
            return []

        qqt = self.dfs_dynamic_wave.fields.qqt_fortran.to_numpy()
        frhopredi2 = self.dfs_dynamic_wave.fields.frhopredi2.to_numpy()
        rho_water = float(self.config.rheology.rho_water)
        rho_sediment = float(self.config.rheology.rho_sediment)
        density_span = rho_sediment - rho_water

        samples: List[Dict[str, float]] = []
        for cell in observer["cells"]:
            i = int(cell["i"])
            j = int(cell["j"])
            discharge = 0.0
            for direction in range(qqt.shape[2]):
                face_outflow = -float(qqt[i, j, direction])
                if face_outflow > 0.0:
                    discharge += face_outflow
            if density_span > 0.0:
                cv = float((frhopredi2[i, j] - rho_water) / density_span)
            else:
                cv = 0.0
            if cv < 0.0:
                cv = 0.0

            samples.append(
                {
                    "cell_id": int(cell["cell_id"]),
                    "discharge_cms": discharge,
                    "cv": cv,
                }
            )

        return samples

    def _update_hydrograph_monitor_max_state(self, time_hours: float) -> None:
        observer = getattr(self, "hydrograph_monitor_observer", None)
        if not observer or not observer["cells"]:
            return

        for sample in self._collect_hydrograph_monitor_samples():
            cell_id = int(sample["cell_id"])
            discharge = float(sample["discharge_cms"])
            if discharge > observer["max_discharge"][cell_id]:
                observer["max_discharge"][cell_id] = discharge
                observer["max_time_hours"][cell_id] = float(time_hours)

    def _record_hydrograph_monitor_output_sample(self) -> None:
        observer = getattr(self, "hydrograph_monitor_observer", None)
        if not observer or not observer["cells"]:
            return

        samples = self._collect_hydrograph_monitor_samples()
        if not samples:
            return
        time_hours = float(self.time_stepper.t_current / 3600.0)
        observer["samples"].append({"time_hours": time_hours, "cells": samples})

    def _export_hydrograph_monitor_text(self) -> Optional[Path]:
        plan = getattr(self, "edda_runtime_control_plan", None)
        if plan is not None and plan.strict and not plan.extension_enabled(
            "save_hydrograph_cells",
            compatibility_default=False,
        ):
            return None
        observer = getattr(self, "hydrograph_monitor_observer", None)
        if not observer:
            return None
        if not observer["cells"] or not observer["samples"]:
            return None

        output_path = self.output_dir / observer["output_filename"]
        samples_by_cell = {int(cell["cell_id"]): [] for cell in observer["cells"]}
        for sample in observer["samples"]:
            time_hours = float(sample["time_hours"])
            for cell_sample in sample["cells"]:
                samples_by_cell[int(cell_sample["cell_id"])].append(
                    {
                        "time_hours": time_hours,
                        "discharge_cms": float(cell_sample["discharge_cms"]),
                        "cv": float(cell_sample["cv"]),
                    }
                )

        return write_hydrograph_file(
            output_path,
            cell_ids=[int(cell["cell_id"]) for cell in observer["cells"]],
            samples_by_cell=samples_by_cell,
            max_discharge={int(key): float(value) for key, value in observer["max_discharge"].items()},
            max_time_hours={int(key): float(value) for key, value in observer["max_time_hours"].items()},
        )

    def _initialize_flow_connectivity(self, nodata_mask_t: np.ndarray) -> None:
        """
        Build explicit 8-direction neighbor tables equivalent to original flodir.f90.

        The original Fortran code numbers valid cells row-major over the raster
        while skipping NoData cells, then stores 8-direction neighbor ids in
        order [N, NE, E, SE, S, SW, W, NW]. Here we reproduce that numbering and
        connectivity exactly, but keep Taichi storage in structured-grid form.
        """
        nx, ny = self.fields.nx, self.fields.ny

        cell_id = np.zeros((nx, ny), dtype=np.int32)
        next_id = 1
        for j in range(ny):
            for i in range(nx):
                if nodata_mask_t[i, j]:
                    continue
                cell_id[i, j] = next_id
                next_id += 1

        neighbor_offsets = (
            (0, -1),   # N
            (1, -1),   # NE
            (1, 0),    # E
            (1, 1),    # SE
            (0, 1),    # S
            (-1, 1),   # SW
            (-1, 0),   # W
            (-1, -1),  # NW
        )

        neighbor_id = np.zeros((nx, ny, 8), dtype=np.int32)
        neighbor_i = np.full((nx, ny, 8), -1, dtype=np.int32)
        neighbor_j = np.full((nx, ny, 8), -1, dtype=np.int32)

        for j in range(ny):
            for i in range(nx):
                if cell_id[i, j] == 0:
                    continue
                for d, (di, dj) in enumerate(neighbor_offsets):
                    ni = i + di
                    nj = j + dj
                    if ni < 0 or ni >= nx or nj < 0 or nj >= ny:
                        continue
                    if cell_id[ni, nj] == 0:
                        continue
                    neighbor_id[i, j, d] = cell_id[ni, nj]
                    neighbor_i[i, j, d] = ni
                    neighbor_j[i, j, d] = nj

        self.fields.set_flow_connectivity(cell_id, neighbor_id, neighbor_i, neighbor_j)
        logger.info("Initialized Fortran-equivalent 8-direction flow connectivity")

    def _initialize_boundary_conditions(self, nodata_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Initialize boundary conditions based on configuration.

        Args:
            nodata_mask: NoData mask array

        Returns:
            boundary_mask: Boolean array indicating boundary cells
            boundary_types: Integer array with boundary types (1=outflow)
        """
        ny, nx = self.fields.ny, self.fields.nx
        boundary_config = self.config.boundary_conditions

        if boundary_config is None:
            # Default: auto-detect boundaries
            logger.info("Using default boundary detection (grid edges + NoData)")
            return self._auto_detect_boundaries(nodata_mask)

        mode = boundary_config.mode

        if mode == "auto":
            logger.info("Auto-detecting boundaries...")
            return self._auto_detect_boundaries(nodata_mask)

        elif mode == "file":
            if boundary_config.boundary_file:
                logger.info(f"Loading boundaries from file: {boundary_config.boundary_file}")
                return self._load_boundary_from_file(boundary_config.boundary_file, (nx, ny))
            else:
                logger.warning("Boundary file not specified, using auto-detection")
                return self._auto_detect_boundaries(nodata_mask)

        elif mode == "manual":
            if boundary_config.manual_cells:
                logger.info(f"Using manual boundary cells: {len(boundary_config.manual_cells)} cells")
                return self._create_manual_boundaries(boundary_config.manual_cells, (nx, ny), nodata_mask)
            else:
                logger.warning("Manual cells not specified, using auto-detection")
                return self._auto_detect_boundaries(nodata_mask)

        else:
            logger.warning(f"Unknown boundary mode: {mode}, using auto-detection")
            return self._auto_detect_boundaries(nodata_mask)

    def _auto_detect_boundaries(self, nodata_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Automatically detect boundary cells (grid edges + NoData).

        Args:
            nodata_mask: NoData mask array

        Returns:
            boundary_mask: Boolean array indicating boundary cells
            boundary_types: Integer array with boundary types
        """
        ny, nx = self.fields.ny, self.fields.nx
        boundary = np.zeros((nx, ny), dtype=np.int32)

        # Mark grid edges as boundaries
        boundary[0, :] = 1
        boundary[-1, :] = 1
        boundary[:, 0] = 1
        boundary[:, -1] = 1

        # Include NoData cells if configured
        if self.config.boundary_conditions and self.config.boundary_conditions.include_nodata:
            boundary[nodata_mask == 1] = 1

        # Default boundary type: Outflow (type 1)
        boundary_types = np.ones_like(boundary, dtype=np.int32)

        num_boundaries = np.sum(boundary)
        logger.info(f"Detected {num_boundaries} boundary cells ({100.0 * num_boundaries / boundary.size:.2f}%)")

        return boundary, boundary_types

    def _load_boundary_from_file(self, boundary_file: str, grid_shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Load boundary conditions from file (.shp or .tif).

        Args:
            boundary_file: Path to boundary file
            grid_shape: Grid shape (nx, ny)

        Returns:
            boundary_mask: Boolean array indicating boundary cells
            boundary_types: Integer array with boundary types
        """
        nx, ny = grid_shape
        file_path = Path(boundary_file)

        if file_path.suffix.lower() in ['.shp', '.shx', '.dbf']:
            # Load from Shapefile
            logger.info("Loading boundary from Shapefile...")
            return self._load_boundary_from_shapefile(boundary_file, grid_shape)

        elif file_path.suffix.lower() in ['.tif', '.tiff']:
            # Load from GeoTIFF
            logger.info("Loading boundary from GeoTIFF...")
            from edda.io.dem_reader import DEMReader
            reader = DEMReader(boundary_file)
            boundary_data, _ = reader.read()

            # Convert to binary mask
            boundary = (boundary_data > 0).astype(np.int32).T  # Transpose to match (nx, ny)
            boundary_types = np.ones_like(boundary, dtype=np.int32)

            return boundary, boundary_types

        else:
            logger.error(f"Unsupported boundary file format: {file_path.suffix}")
            logger.info("Falling back to auto-detection")
            return self._auto_detect_boundaries(np.zeros((nx, ny), dtype=np.int32))

    def _load_boundary_from_shapefile(self, shapefile_path: str, grid_shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Load boundary conditions from Shapefile.

        Args:
            shapefile_path: Path to shapefile
            grid_shape: Grid shape (nx, ny)

        Returns:
            boundary_mask: Boolean array indicating boundary cells
            boundary_types: Integer array with boundary types
        """
        try:
            import geopandas as gpd
            from rasterio import features
            from rasterio.transform import from_bounds

            nx, ny = grid_shape

            # Read shapefile
            gdf = gpd.read_file(shapefile_path)

            # Get bounds from DEM metadata (assuming it's available)
            # For now, create a simple transform
            # TODO: Get actual transform from DEM metadata
            bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
            transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], nx, ny)

            # Rasterize shapefile
            shapes = ((geom, 1) for geom in gdf.geometry)
            boundary = features.rasterize(
                shapes,
                out_shape=(ny, nx),
                transform=transform,
                fill=0,
                dtype=np.int32
            ).T  # Transpose to match (nx, ny)

            boundary_types = np.ones_like(boundary, dtype=np.int32)

            num_boundaries = np.sum(boundary)
            logger.info(f"Loaded {num_boundaries} boundary cells from shapefile")

            return boundary, boundary_types

        except ImportError:
            logger.error("geopandas not installed. Cannot load shapefile.")
            logger.info("Install with: pip install geopandas")
            return self._auto_detect_boundaries(np.zeros(grid_shape, dtype=np.int32))

        except Exception as e:
            logger.error(f"Failed to load shapefile: {e}")
            return self._auto_detect_boundaries(np.zeros(grid_shape, dtype=np.int32))

    def _create_manual_boundaries(self, manual_cells: list, grid_shape: Tuple[int, int], nodata_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create boundary mask from manually selected cells.

        Args:
            manual_cells: List of (i, j) tuples
            grid_shape: Grid shape (nx, ny)
            nodata_mask: NoData mask array

        Returns:
            boundary_mask: Boolean array indicating boundary cells
            boundary_types: Integer array with boundary types
        """
        nx, ny = grid_shape
        boundary = np.zeros((nx, ny), dtype=np.int32)

        # Mark manual cells
        for i, j in manual_cells:
            if 0 <= i < nx and 0 <= j < ny:
                boundary[i, j] = 1

        # Optionally include NoData
        if self.config.boundary_conditions and self.config.boundary_conditions.include_nodata:
            boundary[nodata_mask == 1] = 1

        boundary_types = np.ones_like(boundary, dtype=np.int32)

        num_boundaries = np.sum(boundary)
        logger.info(f"Created {num_boundaries} manual boundary cells")

        return boundary, boundary_types

    def _initialize_spatial_zones(self):
        """
        Initialize spatial zone system from zone file.

        Reads zone raster file and maps zone-specific parameters to spatial fields.
        """
        zone_config = self.config.spatial_zones

        if not zone_config.zone_file:
            logger.warning("Spatial zones enabled but no zone file specified. Using uniform parameters.")
            self._initialize_uniform_parameters()
            return

        try:
            # Read zone raster file
            zone_reader = ZoneReader(zone_config.zone_file)
            zone_grid, zone_metadata = zone_reader.read_zone_grid()

            # Validate zones against configuration
            zone_reader.validate_zones(zone_config.zones)

            # Get zone statistics
            zone_stats = zone_reader.get_zone_statistics()
            for zone_id, stats in zone_stats.items():
                logger.info(f"  Zone {zone_id}: {stats['cell_count']} cells ({stats['percentage']:.1f}%)")

            # Map zone parameters to spatial fields
            zone_mask, zone_params = zone_reader.apply_zone_parameters(
                zone_config.zones,
                grid_shape=(self.fields.nx, self.fields.ny)
            )

            # Apply to Taichi fields
            self.fields.set_zone_parameters(zone_mask, zone_params)

            # Seed erodible thickness from soil depth unless zfil (ltstar<0)
            # will replace both ltstar_field and inierodithick, matching
            # edda main program.F90:79-81,174-190 (ltstar starts at 0).
            erodible_np = self.fields.depth_field.to_numpy()
            self.fields.erodible_thickness.from_numpy(erodible_np)

            logger.info("Spatial zone system initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize spatial zones: {e}")
            logger.warning("Falling back to uniform parameters")
            self._initialize_uniform_parameters()

    def _initialize_uniform_parameters(self):
        """
        Initialize uniform parameters from configuration (no spatial zones).

        Sets all spatial parameter fields to uniform values from config.
        """
        logger.info("Initializing uniform parameters from configuration")

        # Create parameter arrays with uniform values
        nx, ny = self.fields.nx, self.fields.ny

        # Hydrology parameters
        K_sat = np.full((nx, ny), self.config.hydrology.K_sat, dtype=self.numpy_float_dtype)
        theta_s = np.full((nx, ny), self.config.hydrology.theta_s, dtype=self.numpy_float_dtype)
        theta_i = np.full((nx, ny), self.config.hydrology.theta_i, dtype=self.numpy_float_dtype)
        psi_f = np.full((nx, ny), self.config.hydrology.psi_f, dtype=self.numpy_float_dtype)

        # Soil parameters
        c = np.full((nx, ny), self.config.soil.c, dtype=self.numpy_float_dtype)
        phi = np.full((nx, ny), self.config.soil.phi, dtype=self.numpy_float_dtype)
        gamma_s = np.full((nx, ny), self.config.soil.gamma_s, dtype=self.numpy_float_dtype)
        gamma_w = np.full((nx, ny), self.config.soil.gamma_w, dtype=self.numpy_float_dtype)
        depth = np.full((nx, ny), self.config.soil.depth, dtype=self.numpy_float_dtype)

        # Rheology parameters
        n_manning = np.full((nx, ny), self.config.rheology.n_manning, dtype=self.numpy_float_dtype)
        alpha1 = np.full((nx, ny), self.config.rheology.alpha1, dtype=self.numpy_float_dtype)
        beta1 = np.full((nx, ny), self.config.rheology.beta1, dtype=self.numpy_float_dtype)
        alpha2 = np.full((nx, ny), self.config.rheology.alpha2, dtype=self.numpy_float_dtype)
        beta2 = np.full((nx, ny), self.config.rheology.beta2, dtype=self.numpy_float_dtype)

        # Set to Taichi fields
        self.fields.K_sat_field.from_numpy(K_sat)
        self.fields.theta_s_field.from_numpy(theta_s)
        self.fields.theta_i_field.from_numpy(theta_i)
        self.fields.psi_f_field.from_numpy(psi_f)

        self.fields.c_field.from_numpy(c)
        self.fields.phi_field.from_numpy(phi)
        self.fields.gamma_s_field.from_numpy(gamma_s)
        self.fields.gamma_w_field.from_numpy(gamma_w)
        self.fields.depth_field.from_numpy(depth)

        self.fields.n_manning_field.from_numpy(n_manning)
        self.fields.alpha1_field.from_numpy(alpha1)
        self.fields.beta1_field.from_numpy(beta1)
        self.fields.alpha2_field.from_numpy(alpha2)
        self.fields.beta2_field.from_numpy(beta2)

        # Erosion parameter
        kero = np.full((nx, ny), self.config.erosion.k_erosion, dtype=self.numpy_float_dtype)
        ctao = np.full((nx, ny), self.config.erosion.ctao, dtype=self.numpy_float_dtype)
        self.fields.kero_field.from_numpy(kero)
        self.fields.ctao_field.from_numpy(ctao)

        # Double-layer parameters (from config if available)
        dl = self.config.soil.double_layer
        if dl and dl.enabled:
            alpha_top = np.full((nx, ny), dl.top_layer.alpha, dtype=self.numpy_float_dtype)
            alpha_bottom = np.full((nx, ny), dl.bottom_layer.alpha, dtype=self.numpy_float_dtype)
            K_sat_top = np.full((nx, ny), dl.top_layer.K_sat, dtype=self.numpy_float_dtype)
            K_sat_bottom = np.full((nx, ny), dl.bottom_layer.K_sat, dtype=self.numpy_float_dtype)
            theta_sat_top = np.full((nx, ny), dl.top_layer.theta_sat, dtype=self.numpy_float_dtype)
            theta_sat_bottom = np.full((nx, ny), dl.bottom_layer.theta_sat, dtype=self.numpy_float_dtype)
            theta_res_top = np.full((nx, ny), dl.top_layer.theta_res, dtype=self.numpy_float_dtype)
            theta_res_bottom = np.full((nx, ny), dl.bottom_layer.theta_res, dtype=self.numpy_float_dtype)
            phib = np.full((nx, ny), dl.top_layer.phib, dtype=self.numpy_float_dtype)
            ltstar = np.full((nx, ny), dl.ltstar, dtype=self.numpy_float_dtype)
            lbstar = np.full((nx, ny), dl.lbstar, dtype=self.numpy_float_dtype)

            self.fields.alpha_top_field.from_numpy(alpha_top)
            self.fields.alpha_bottom_field.from_numpy(alpha_bottom)
            self.fields.K_sat_top_field.from_numpy(K_sat_top)
            self.fields.K_sat_bottom_field.from_numpy(K_sat_bottom)
            self.fields.theta_sat_top_field.from_numpy(theta_sat_top)
            self.fields.theta_sat_bottom_field.from_numpy(theta_sat_bottom)
            self.fields.theta_res_top_field.from_numpy(theta_res_top)
            self.fields.theta_res_bottom_field.from_numpy(theta_res_bottom)
            self.fields.phib_field.from_numpy(phib)
            self.fields.ltstar_field.from_numpy(ltstar)
            self.fields.lbstar_field.from_numpy(lbstar)

        # Seed erodible thickness from soil depth; apply_native_runtime_inputs
        # may later replace this with ltstar_field (glacier.asc) when ltstar < 0.
        erodible_np = self.fields.depth_field.to_numpy()
        self.fields.erodible_thickness.from_numpy(erodible_np)

        logger.info("Uniform parameters initialized")

    def run(self):
        """Run the simulation."""
        if self.fields is None:
            raise RuntimeError("Solver not initialized. Call initialize() first.")

        logger.info("=" * 60)
        logger.info("Starting EDDA simulation")
        logger.info("=" * 60)

        self._last_output_time_written = None

        # Create progress bar (can be disabled for batch/benchmark runs)
        disable_tqdm = os.getenv("TQDM_DISABLE", "").strip().lower() in {"1", "true", "yes", "on"}
        pbar = tqdm(
            total=100,
            desc="Simulation",
            unit="%",
            bar_format="{l_bar}{bar}| {n:.1f}/{total_fmt} [{elapsed}<{remaining}]",
            disable=disable_tqdm
        )

        try:
            self._start_async_output_writer()
            # Main time loop
            while not self.time_stepper.is_finished():
                # Get current time and time step
                t = self.time_stepper.t_current
                dt_candidate = self.time_stepper.dt_current
                # Match dfs.F90 literally: first test the candidate step against
                # the next output time (`ttout`), then against the simulation
                # end time (`simul`). Reversing that order changes the hidden
                # `tempdt` carry semantics when `t_end` happens to coincide with
                # an output boundary.
                t_next = t + dt_candidate
                next_output_time = self.time_stepper.t_last_output + self.time_stepper.dt_output
                if t_next > next_output_time:
                    # dfs.F90 persists `tempdt` across retries and across accepted
                    # non-output steps until the next output block reuses it.
                    if self._use_fortran_dfs():
                        self.fortran_tempdt = dt_candidate
                    t_next = next_output_time
                if t_next > self.time_stepper.t_end:
                    t_next = self.time_stepper.t_end
                dt_candidate = t_next - t
                if dt_candidate <= 0.0:
                    break

                retry_attempt_id = 0
                while True:
                    self.time_stepper.dt_current = dt_candidate

                    # Update rainfall for the candidate interval.
                    if (
                        self._run_control_enabled(
                            "simulate_rainfall", compatibility_default=True
                        )
                        and self.rainfall_reader
                    ):
                        rainfall = self._get_rainfall_field_for_interval(t, t + dt_candidate)
                        self._apply_rainfall(rainfall)

                    self.dfs_candidate_step_id += 1
                    if (
                        self.dfs_dynamic_wave is not None
                        and hasattr(self.dfs_dynamic_wave, "set_momentum_faceflux_lifecycle_metadata")
                    ):
                        self.dfs_dynamic_wave.set_momentum_faceflux_lifecycle_metadata(
                            accepted_step_id=self.dfs_accepted_step_id + 1,
                            candidate_step_id=self.dfs_candidate_step_id,
                            retry_attempt_id=retry_attempt_id,
                            rejected_step_status=0,
                            accepted_predictor_state_id=self.dfs_accepted_step_id + 1,
                            previous_predictor_carryover_state_id=self.dfs_accepted_step_id,
                        )

                    # Physics sequence
                    step_info = self._physics_step(dt_candidate)
                    self._observe_numerical_step(
                        step_info,
                        accepted=bool(step_info.get("accepted", True)),
                        attempted_dt=dt_candidate,
                        force_volume=bool(
                            t + dt_candidate >= next_output_time - 1.0e-6
                            or t + dt_candidate >= float(self.time_stepper.t_end) - 1.0e-6
                        ),
                    )
                    trace_candidate = self._step_lifecycle_trace_in_window(t, t + dt_candidate)

                    if not step_info.get("accepted", True):
                        suggested_dt = float(step_info.get("suggested_dt", dt_candidate))
                        next_dt = float(step_info.get("next_dt", suggested_dt))
                        first_reject = step_info.get("first_reject", {})
                        if trace_candidate:
                            self._record_step_lifecycle_trace(
                                {
                                    "event": "rejected",
                                    "t_start": float(t),
                                    "dt_attempt": float(dt_candidate),
                                    "t_attempt_end": float(t + dt_candidate),
                                    "next_output_time": float(next_output_time),
                                    "t_end": float(self.time_stepper.t_end),
                                    "candidate_step_id": int(self.dfs_candidate_step_id),
                                    "accepted_step_id_before": int(self.dfs_accepted_step_id),
                                    "accepted_step_id_target": int(self.dfs_accepted_step_id + 1),
                                    "retry_attempt_id": int(retry_attempt_id),
                                    "suggested_dt": suggested_dt,
                                    "next_dt": next_dt,
                                    "time_stepper_rejected_steps_before": int(self.time_stepper.rejected_steps),
                                    "fortran_tempdt_before": float(self.fortran_tempdt),
                                    "first_reject": first_reject,
                                }
                            )
                        retry_attempt_id += 1
                        dt_candidate = self.time_stepper.reject_step(step_info.get("suggested_dt"))
                        remaining_to_output = next_output_time - t
                        remaining_total = self.time_stepper.t_end - t
                        if dt_candidate > remaining_to_output:
                            dt_candidate = remaining_to_output
                        if dt_candidate > remaining_total:
                            dt_candidate = remaining_total
                        if dt_candidate <= 0.0:
                            raise RuntimeError("Dynamic-wave step rejection reduced dt to a non-positive value")
                        continue

                    used_dt = float(step_info.get("used_dt", dt_candidate))
                    self.dfs_accepted_step_id += 1

                    # Advance time with the dt that was actually accepted.
                    self._update_hydrograph_monitor_max_state(
                        time_hours=float(self.time_stepper.t_current / 3600.0)
                    )
                    self.time_stepper.advance(used_dt)
                    self._update_outflow_process_state(used_dt)
                    break

                # Output results if needed
                did_output = False
                if self.time_stepper.should_output():
                    self._record_outflow_process_output_sample()
                    self._record_hydrograph_monitor_output_sample()
                    self._output_results()
                    self._last_output_time_written = float(self.time_stepper.t_current)
                    self.time_stepper.mark_output()
                    did_output = True

                # Prepare the next-step dt exactly as the original DFS solver
                # does, even when the current run stops at this output/checkpoint
                # boundary. This keeps restart checkpoints continuation-ready.
                if self._use_fortran_dfs():
                    self.time_stepper.dt_current = float(step_info.get("next_dt", self.time_stepper.dt_current))
                    if did_output and self.fortran_tempdt > self.time_stepper.dt_current:
                        self.time_stepper.dt_current = self.fortran_tempdt
                elif not self.time_stepper.is_finished():
                    max_wave_speed = self.shallow_water.compute_max_wave_speed()
                    self.time_stepper.adapt_time_step(max_wave_speed)
                if trace_candidate:
                    self._record_step_lifecycle_trace(
                        {
                            "event": "accepted",
                            "t_start": float(t),
                            "dt_attempt": float(dt_candidate),
                            "used_dt": float(used_dt),
                            "t_after": float(self.time_stepper.t_current),
                            "next_output_time": float(next_output_time),
                            "did_output": bool(did_output),
                            "candidate_step_id": int(self.dfs_candidate_step_id),
                            "accepted_step_id": int(self.dfs_accepted_step_id),
                            "retry_attempt_id": int(retry_attempt_id),
                            "suggested_dt": float(step_info.get("suggested_dt", self.time_stepper.dt_current)),
                            "next_dt": float(step_info.get("next_dt", self.time_stepper.dt_current)),
                            "dt_current_after_prepare": float(self.time_stepper.dt_current),
                            "time_stepper_step_count": int(self.time_stepper.step_count),
                            "time_stepper_rejected_steps": int(self.time_stepper.rejected_steps),
                            "fortran_tempdt_after": float(self.fortran_tempdt),
                            "first_reject": step_info.get("first_reject", {}),
                        }
                    )

                # Update progress
                progress = self.time_stepper.get_progress()
                pbar.n = progress
                pbar.refresh()

                # Call progress callback if provided
                if self.progress_callback:
                    self.progress_callback(self.time_stepper.get_time_info())

        except KeyboardInterrupt:
            logger.warning("Simulation interrupted by user")
        except Exception as e:
            logger.error(f"Simulation error: {e}", exc_info=True)
            raise
        finally:
            pbar.close()
            self._stop_async_output_writer()

        # Final output is needed only when the simulation did not already emit
        # this exact accepted time at an output boundary.
        last_output_time = getattr(self, "_last_output_time_written", None)
        if last_output_time is None or not np.isclose(
            float(last_output_time), float(self.time_stepper.t_current), rtol=0.0, atol=1.0e-9
        ):
            self._output_results()
            self._last_output_time_written = float(self.time_stepper.t_current)

        # Log statistics
        self.time_stepper.log_statistics()

        logger.info("=" * 60)
        logger.info("Simulation complete")
        logger.info("=" * 60)

    def _apply_boundary_conditions_before_flow(self):
        """
        Apply boundary conditions before flow computation.

        This matches original EDDA lines 220-221 and 236-237, where outflow
        boundaries are applied after rainfall/inflow and after prediction step,
        but before velocity computation.
        """
        apply_outflow_boundaries_kernel(self.fields)

    def _use_fortran_dfs(self) -> bool:
        """
        Route debris-flow / double-layer production cases to the Fortran-aligned
        full dynamic-wave solver.
        """
        if self.edda_runtime_control_plan.strict:
            if not self.edda_runtime_control_plan.run_enabled("simulate_debris_flow"):
                raise RuntimeError(
                    "edda_wfs_unsupported: strict simulate_debris_flow=false cannot use the unvalidated WFS path"
                )
            return self.dfs_dynamic_wave is not None
        return (
            self.dfs_dynamic_wave is not None
            and self.double_layer is not None
            and self.config.soil.double_layer is not None
            and self.config.soil.double_layer.enabled
        )

    def _physics_step(self, dt: float):
        """
        Execute one physics time step.

        Args:
            dt: Time step size
        """
        # 1. Hydrology / pore pressure / factor of safety.
        # For the Fortran DFS path, the double-layer model is advanced inside
        # `DFSDynamicWaveSolver.step()` after `tempir` is available, matching
        # original dfs.F90 ordering.
        use_fortran_dfs = self._use_fortran_dfs()
        simulate_shallow_landslide = self._run_control_enabled(
            "simulate_shallow_landslide", compatibility_default=True
        )
        if use_fortran_dfs and self.double_layer and self.config.soil.double_layer.enabled:
            pass
        elif self.double_layer and self.config.soil.double_layer.enabled:
            rainfall_np = self.fields.rainfall.to_numpy()
            self.double_layer.solve_richards_equation(dt, rainfall_np)
            self.double_layer.compute_pore_pressure()
            self.double_layer.find_minimum_fs()
        else:
            # Single-layer hydrology / stability path
            self.hydrology.step(dt)
            if simulate_shallow_landslide:
                self.stability.step(
                    check_failure=False,
                    Cv_failure=self.config.rheology.Cv_max * 0.85
                )

        # 2. Refresh density state needed by source-term evaluation.
        # The Fortran-aligned DFS path carries `frho`/`Cv` as transported
        # state inside `DFSDynamicWaveSolver.step()`. Recomputing `rho` from
        # `Cv` here is a non-EDDA outer-layer intervention, so keep it only for
        # the legacy modular solver path.
        if not use_fortran_dfs:
            self.rheology.update_properties()

        if use_fortran_dfs:
            if simulate_shallow_landslide and not (
                self.double_layer and self.config.soil.double_layer.enabled
            ):
                self.stability.populate_failure_source_terms(
                    Cv_failure=self.config.rheology.Cv_max * 0.85,
                    rho_sediment=self.config.rheology.rho_sediment,
                    rho_water=self.config.rheology.rho_water,
                )

            self.dfs_dynamic_wave.set_current_time(self.time_stepper.t_current)
            step_info = self.dfs_dynamic_wave.step(dt)
            if step_info.get("accepted", False) and not self.edda_runtime_control_plan.strict:
                # Preserve the historical control-free direct API contract.
                # Strict EDDA plans use only the sidecar-backed DFS mask inside
                # DFSDynamicWaveSolver and must not leak generic DEM boundaries.
                apply_outflow_boundaries_kernel(self.fields)
            return step_info

        # 3. Compute erosion / deposition from the same pre-update state, then apply.
        self.erosion.compute_rates()
        self.deposition.compute_rates(dt)
        self.erosion.apply_rates(dt)
        self.deposition.apply_rates(dt)

        # 4. Mobilize unstable soil after erosion / deposition source terms.
        if self.double_layer and self.config.soil.double_layer.enabled:
            self.double_layer.check_failure_and_mobilize(self.config.rheology.Cv_max)
        else:
            self.stability.mobilize_failures(
                Cv_failure=self.config.rheology.Cv_max * 0.85
            )

        # 5. Prepare flow coefficients for the shallow-water solve.
        self.rheology.prepare_for_flow()

        # Apply boundary conditions before flow computation.
        self._apply_boundary_conditions_before_flow()

        # 6. Shallow water transport / momentum solve.
        self.shallow_water.step(dt)

        # Apply boundary conditions after flow computation.
        apply_outflow_boundaries_kernel(self.fields)

        # 7. Refresh transported state and Froude limiter without reapplying friction.
        self.rheology.finalize_after_flow(limitfr=self.config.rheology.limitfr)

        # Final boundary cleanup after state synchronization.
        apply_outflow_boundaries_kernel(self.fields)
        return {
            "accepted": True,
            "used_dt": dt,
            "next_dt": self.time_stepper.dt_current,
        }

    def _get_rainfall_field_for_interval(self, t_start: float, t_end: float) -> np.ndarray:
        """
        Build rainfall field for [t_start, t_end] using interval-weighted forcing.

        Returns:
            Rainfall field in m/s with shape (nx, ny).
        """
        if self.rainfall_reader is None:
            return np.zeros((self.fields.nx, self.fields.ny), dtype=self.numpy_float_dtype)

        rainfall_cfg = self.config.rainfall
        spatial_dt_hours = rainfall_cfg.time_step_hours if rainfall_cfg else 1.0

        spatial = self.rainfall_reader.get_spatial_interval_average_rainfall(
            t_start,
            t_end,
            dt_hours=spatial_dt_hours
        )
        if spatial is not None:
            # Raster data are usually (rows, cols)=(ny, nx); Taichi fields are (nx, ny).
            if spatial.shape == (self.fields.ny, self.fields.nx):
                spatial = spatial.T
            elif spatial.shape != (self.fields.nx, self.fields.ny):
                raise ValueError(
                    f"Spatial rainfall shape mismatch: got {spatial.shape}, "
                    f"expected {(self.fields.nx, self.fields.ny)} or {(self.fields.ny, self.fields.nx)}"
                )
            return spatial.astype(self.numpy_float_dtype, copy=False)

        rain_scalar = self.rainfall_reader.get_interval_average_rainfall(t_start, t_end)
        return np.full((self.fields.nx, self.fields.ny), rain_scalar, dtype=self.numpy_float_dtype)

    def _apply_rainfall(self, rainfall: Union[float, np.ndarray]):
        """
        Apply rainfall to the domain.

        Args:
            rainfall: Rainfall intensity scalar (m/s) or spatial field (nx, ny) in m/s
        """
        if np.isscalar(rainfall):
            rainfall_np = np.full(
                (self.fields.nx, self.fields.ny),
                float(rainfall),
                dtype=self.numpy_float_dtype
            )
        else:
            rainfall_np = np.asarray(rainfall, dtype=self.numpy_float_dtype)
            if rainfall_np.shape == (self.fields.ny, self.fields.nx):
                rainfall_np = rainfall_np.T
            if rainfall_np.shape != (self.fields.nx, self.fields.ny):
                raise ValueError(
                    f"Rainfall field shape mismatch: got {rainfall_np.shape}, "
                    f"expected {(self.fields.nx, self.fields.ny)}"
                )
        self.fields.rainfall.from_numpy(rainfall_np)

    def _output_results(self):
        """Output current simulation state."""
        t = self.time_stepper.t_current
        output_count = self.time_stepper.output_count

        logger.info(f"Writing output #{output_count} at t={t:.2f}s")

        # Get current state.  Periodic writers only need the EDDA output-family
        # fields; pulling the 60+ diagnostic arrays every `tout` is the main
        # D2H cost on Chamoli-size grids.
        state = self.fields.get_full_state(
            include_fields=self.PERIODIC_OUTPUT_FIELDS,
            exclude_fields=self.OUTPUT_STATE_EXCLUDED_FIELDS,
        )
        state['erosion_depth_fortran_output'] = self._build_fortran_erosion_depth_output(state)

        # Store the full state history only for offline workflows that request
        # in-memory time series. Web/API RuntimeSession jobs write outputs to
        # disk and disable this flag so memory stays bounded during long runs.
        if getattr(self, "retain_output_history", True):
            self.results.append({
                'time': t,
                'state': state
            })

        # Original EDDA output-family controls schedule their own periodic
        # writers.  The generic GeoTIFF convenience flag must not suppress a
        # strict EDDA family that is explicitly enabled.
        plan = getattr(self, "edda_runtime_control_plan", None)
        periodic_edda_controls = (
            "save_fs_min_grid",
            "save_flow_depth",
            "save_max_flow_depth",
            "save_flow_velocity",
            "save_max_flow_velocity",
            "save_erosion_depth",
            "save_deposition_depth",
            "save_total_depth",
            "save_max_solid_depth",
            "save_volumetric_sediment_concentration",
        )
        write_edda_text = bool(self.config.save_intermediate)
        if plan is not None and plan.strict:
            write_edda_text = any(
                plan.output_enabled(key, compatibility_default=False)
                for key in periodic_edda_controls
            )

        # Export to files if requested by either independent surface.
        if self.config.save_intermediate or write_edda_text:
            filename_base = f"result_{output_count:04d}"

            # Get NoData mask
            nodata_mask = state['is_nodata']
            nodata_value = self.export_metadata.get('nodata_value', -9999.0)

            # Export flow depth with NoData mask
            # Transpose from Taichi (nx, ny)=(cols, rows) to GeoTIFF (rows, cols)
            h_export = state['h'].T.copy()
            h_export[nodata_mask.T == 1] = nodata_value
            write_geotiff = self._write_geotiff_frames_enabled()
            if self.config.save_intermediate and write_geotiff:
                self._enqueue_or_write_grid(
                    kind="geotiff",
                    path=str(self.output_dir / f"{filename_base}_depth.tif"),
                    data=h_export,
                    nodata_value=nodata_value,
                )

            # Export flow velocity with original EDDA writer semantics.
            velocity = self._build_fortran_flow_velocity_output(state).copy()
            velocity[nodata_mask.T == 1] = nodata_value
            if self.config.save_intermediate and write_geotiff:
                self._enqueue_or_write_grid(
                    kind="geotiff",
                    path=str(self.output_dir / f"{filename_base}_velocity.tif"),
                    data=velocity,
                    nodata_value=nodata_value,
                )

            # Export concentration with original EDDA writer semantics:
            # dfs.F90 writes `cv(i)` but zeros cells with `fh(i)<0.005`.
            Cv_export = self._build_fortran_volumetric_sediment_output(state).T.copy()
            Cv_export[nodata_mask.T == 1] = nodata_value
            if self.config.save_intermediate and write_geotiff:
                self._enqueue_or_write_grid(
                    kind="geotiff",
                    path=str(self.output_dir / f"{filename_base}_concentration.tif"),
                    data=Cv_export,
                    nodata_value=nodata_value,
                )
            if write_edda_text:
                self._export_taichi_named_edda_text_outputs(
                    state=state,
                    t=t,
                    h_export=h_export,
                    velocity_export=velocity,
                    cv_export=Cv_export,
                    nodata_mask=nodata_mask.T,
                    nodata_value=nodata_value,
                )

        # Call output callback if provided
        if self.output_callback:
            self.output_callback(t, state)

    @staticmethod
    def _format_edda_output_time(t: float) -> str:
        """Format checkpoint time like original EDDA result names: `600.0`."""
        return f"{float(t):.1f}"

    def _update_output_max_cache(self, attr_name: str, current: np.ndarray) -> np.ndarray:
        cached = getattr(self, attr_name, None)
        if cached is None or cached.shape != current.shape:
            next_value = current.copy()
        else:
            next_value = np.maximum(cached, current)
        setattr(self, attr_name, next_value.copy())
        return next_value

    def _write_edda_text_grid(
        self,
        original_stem: str,
        t: float,
        data: np.ndarray,
        nodata_mask: np.ndarray,
        nodata_value: float,
    ) -> None:
        """Write an EDDA-style ASCII grid using Taichi naming.

        The file stem follows the original EDDA result convention with only the
        `EDDA` token replaced by `Taichi`.
        """
        data_to_write = np.asarray(data, dtype=np.float64).copy()
        if data_to_write.shape != nodata_mask.shape:
            raise ValueError(
                f"Output family {original_stem} shape mismatch: "
                f"data={data_to_write.shape}, nodata={nodata_mask.shape}"
            )
        data_to_write[nodata_mask == 1] = nodata_value
        filename = f"{original_stem.replace('EDDA', 'Taichi')}_{self._format_edda_output_time(t)}.txt"
        self._enqueue_or_write_grid(
            kind="ascii",
            path=str(self.output_dir / filename),
            data=data_to_write,
            nodata_value=nodata_value,
        )

    def _export_taichi_named_edda_text_outputs(
        self,
        *,
        state: Dict[str, Any],
        t: float,
        h_export: np.ndarray,
        velocity_export: np.ndarray,
        cv_export: np.ndarray,
        nodata_mask: np.ndarray,
        nodata_value: float,
    ) -> None:
        """Export original EDDA result families with `EDDA` renamed to `Taichi`.

        This is an output-format compatibility layer only; it does not change
        solver state, equations, update order, source terms, or time stepping.
        """
        plan = getattr(self, "edda_runtime_control_plan", None)

        def output_enabled(key: str) -> bool:
            return True if plan is None else plan.output_enabled(key, compatibility_default=True)

        def run_enabled(key: str) -> bool:
            return True if plan is None else plan.run_enabled(key, compatibility_default=True)

        z_bed = np.asarray(state['z_bed'], dtype=np.float64)
        z_original = np.asarray(state['z_original'], dtype=np.float64)
        deposition_export = np.maximum(z_bed - z_original, 0.0).T.copy()
        erosion_export = np.asarray(state['erosion_depth_fortran_output'], dtype=np.float64).T.copy()
        total_depth_export = (
            np.asarray(state['h'], dtype=np.float64) + z_bed - z_original
        ).T.copy()
        # Accepted-step extrema are a strict EDDA/DFS contract.  The older
        # control-free direct API may run the modular solver, where these fields
        # exist but are not maintained; preserve its checkpoint-cache behavior.
        use_accepted_maxima = bool(plan is not None and plan.strict)
        max_depth_state = state.get('max_flow_depth') if use_accepted_maxima else None
        max_depth_export = (
            np.asarray(max_depth_state, dtype=np.float64).T.copy()
            if max_depth_state is not None
            else self._update_output_max_cache("_edda_text_max_flow_depth", h_export)
        )
        max_velocity_state = state.get('max_flow_velocity') if use_accepted_maxima else None
        max_velocity_export = (
            np.asarray(max_velocity_state, dtype=np.float64).T.copy()
            if max_velocity_state is not None
            else self._update_output_max_cache("_edda_text_max_flow_velocity", velocity_export)
        )
        max_solid_state = state.get('max_solid_depth') if use_accepted_maxima else None
        if max_solid_state is None:
            solid_depth_export = h_export * np.clip(cv_export, 0.0, None)
            max_solid_depth_export = self._update_output_max_cache(
                "_edda_text_max_solid_depth", solid_depth_export
            )
        else:
            max_solid_depth_export = np.asarray(max_solid_state, dtype=np.float64).T.copy()
        max_solid_depth_export = np.where(
            max_solid_depth_export <= 0.005, 0.0, max_solid_depth_export
        )

        fdepth = np.asarray(state.get('fdepth', np.zeros_like(state['h'])), dtype=np.float64).T.copy()
        gindx = None
        if self.dfs_dynamic_wave is not None:
            gindx = getattr(self.dfs_dynamic_wave, "precomputed_failure_gindx", None)
        if gindx is not None and np.asarray(gindx).shape == np.asarray(state['h']).shape:
            gindx_export = np.asarray(gindx, dtype=np.float64).T.copy()
        else:
            gindx_export = np.where(fdepth > 0.0, 1.0, 0.0)
        ls_scar = gindx_export
        failure_depth_export = np.where(gindx_export == 1.0, fdepth, 0.0)

        families: Dict[str, np.ndarray] = {}
        if output_enabled("save_flow_depth"):
            families["Flow_depth_EDDA"] = h_export
        if output_enabled("save_flow_velocity"):
            families["Flow_velocity_EDDA"] = velocity_export
        if output_enabled("save_max_flow_depth"):
            families["Max_flow_depth_EDDA"] = max_depth_export
        if output_enabled("save_max_flow_velocity"):
            families["Max_flow_velocity_EDDA"] = max_velocity_export
        if output_enabled("save_erosion_depth") and run_enabled("simulate_erosion"):
            families["Erosion_depth_EDDA"] = erosion_export
        if output_enabled("save_deposition_depth") and run_enabled(
            "simulate_water_and_solid_separately"
        ):
            families["Deposit_depth_EDDA"] = deposition_export
        if output_enabled("save_total_depth") and run_enabled(
            "simulate_water_and_solid_separately"
        ):
            families["Total_depth_EDDA"] = total_depth_export
        if output_enabled("save_volumetric_sediment_concentration"):
            families["Volumetric_sediment_conceEDDA"] = cv_export
        # Chamoli/BJ dfs.F90 write LS_Scar/faildph whenever fsminsave is true,
        # independent of fssimul. With fssimul=F the arrays stay zeros.
        if output_enabled("save_fs_min_grid"):
            families["LS_ScarEDDA"] = ls_scar
            families["faildphEDDA"] = failure_depth_export
        if output_enabled("save_max_solid_depth"):
            families["MaxsoliddepthEDDA"] = max_solid_depth_export
        chamoli_regime = (
            getattr(getattr(self.config, "hydrology", None), "dfs_manningbar_variant", "")
            == "debrisflowmanning_cvtol"
        )
        if chamoli_regime and output_enabled("save_flow_depth"):
            families["SFdepthEDDA"] = np.asarray(
                state.get("sfh", np.zeros_like(state["h"])), dtype=np.float64
            ).T.copy()
            families["DFdepthEDDA"] = np.asarray(
                state.get("dfh", np.zeros_like(state["h"])), dtype=np.float64
            ).T.copy()
            families["FFdepthEDDA"] = np.asarray(
                state.get("ffh", np.zeros_like(state["h"])), dtype=np.float64
            ).T.copy()
        if chamoli_regime and output_enabled("save_max_flow_depth"):
            families["MaxSFdepthEDDA"] = np.asarray(
                state.get("maxsfh", np.zeros_like(state["h"])), dtype=np.float64
            ).T.copy()
            families["MaxDFdepthEDDA"] = np.asarray(
                state.get("maxdfh", np.zeros_like(state["h"])), dtype=np.float64
            ).T.copy()
            families["MaxFFdepthEDDA"] = np.asarray(
                state.get("maxffh", np.zeros_like(state["h"])), dtype=np.float64
            ).T.copy()

        for original_stem, data in families.items():
            self._write_edda_text_grid(original_stem, t, data, nodata_mask, nodata_value)

    def _build_fortran_erosion_depth_output(self, state: Dict[str, Any]) -> np.ndarray:
        """
        Build the original EDDA checkpoint `Erosion_depth_*` output field.

        dfs.F90 writes `eleori-ele`, thresholds values below 0.001 to zero,
        and masks cells with `gindx == 1`.  The cumulative `erosion_depth`
        field remains the internal accepted-writeback accumulator and is not
        overwritten here.
        """
        z_original = np.asarray(state['z_original'], dtype=np.float64)
        z_bed = np.asarray(state['z_bed'], dtype=np.float64)
        erosion_output = np.maximum(z_original - z_bed, 0.0)
        erosion_output = np.where(erosion_output < 0.001, 0.0, erosion_output)
        if self.dfs_dynamic_wave is not None and self.dfs_dynamic_wave.precomputed_failure_gindx is not None:
            gindx = np.asarray(self.dfs_dynamic_wave.precomputed_failure_gindx, dtype=np.int32)
            if gindx.shape == erosion_output.shape:
                erosion_output = np.where(gindx == 1, 0.0, erosion_output)
        return erosion_output

    @staticmethod
    def _build_fortran_flow_velocity_output(state: Dict[str, Any]) -> np.ndarray:
        """
        Build the original EDDA checkpoint `Flow_velocity_*` scalar output field.

        EDDA writes the scalar current flow velocity from the first four
        directional face velocities:

            tfg(i)=0.5*(abs(fv(i,1))+abs(fv(i,2))+abs(fv(i,3))+abs(fv(i,4)))

        The internal `u`/`v` vectors remain runtime diagnostics and are not the
        original scalar writer. Returned shape is GeoTIFF layout (rows, cols).
        """
        fv = np.asarray(state['fv_fortran'], dtype=np.float64)
        if fv.ndim != 3:
            raise ValueError(f"fv_fortran must be 3D, got shape {fv.shape}")
        if fv.shape[-1] == 8:
            directional = fv.transpose(1, 0, 2)
        elif fv.shape[0] == 8:
            directional = fv.transpose(2, 1, 0)
        else:
            raise ValueError(f"fv_fortran must contain 8 directions, got shape {fv.shape}")
        return 0.5 * (
            np.abs(directional[:, :, 0])
            + np.abs(directional[:, :, 1])
            + np.abs(directional[:, :, 2])
            + np.abs(directional[:, :, 3])
        )

    @staticmethod
    def _build_fortran_volumetric_sediment_output(state: Dict[str, Any]) -> np.ndarray:
        """
        Build the original EDDA checkpoint `Volumetric_sediment_*` output field.

        dfs.F90 writes the committed `cv(i)` field and applies only a shallow
        flow-depth writer mask:

            tfg(i)=cv(i)
            if(fh(i)<0.005) tfg(i)=0.

        This keeps internal Cv/rho transport untouched while aligning the
        exported GeoTIFF with the original output interpretation.
        """
        cv = np.asarray(state['Cv'], dtype=np.float64)
        h = np.asarray(state['h'], dtype=np.float64)
        return np.where(h < 0.005, 0.0, cv)

    def get_results(self) -> list:
        """
        Get simulation results.

        Returns:
            List of result dictionaries
        """
        return self.results

    def export_final_results(self, format: str = 'geotiff'):
        """
        Export final simulation results.

        Args:
            format: Output format ('geotiff', 'netcdf', 'csv')
        """
        logger.info(f"Exporting final results in {format} format...")
        self.flush_output_writer()

        final_state = self.fields.get_full_state(
            include_fields=self.PERIODIC_OUTPUT_FIELDS,
            exclude_fields=self.OUTPUT_STATE_EXCLUDED_FIELDS,
        )
        nodata_mask = final_state['is_nodata'].T  # Transpose to (rows, cols) for GeoTIFF
        nodata_value = self.export_metadata.get('nodata_value', -9999.0)

        if format == 'geotiff':
            # Export final depth with NoData mask
            # Transpose from Taichi (nx, ny)=(cols, rows) to GeoTIFF (rows, cols)
            h_export = final_state['h'].T.copy()
            h_export[nodata_mask == 1] = nodata_value
            exporter = ResultExporter(
                data=h_export,
                transform=self.export_metadata.get('transform'),
                crs=self.export_metadata.get('crs'),
                nodata_value=nodata_value
            )
            exporter.to_geotiff(str(self.output_dir / "final_depth.tif"))

            # Export original EDDA `Erosion_depth_*` semantics, not the
            # cumulative accepted-writeback bookkeeping field.
            erosion_export = self._build_fortran_erosion_depth_output(final_state).T.copy()
            erosion_export[nodata_mask == 1] = nodata_value
            exporter = ResultExporter(
                data=erosion_export,
                transform=self.export_metadata.get('transform'),
                crs=self.export_metadata.get('crs'),
                nodata_value=nodata_value
            )
            exporter.to_geotiff(str(self.output_dir / "final_erosion.tif"))

            # Match the EDDA-Taichi CUDA `Deposit_depth` output family.
            deposition_export = final_state['deposition_depth'].T.copy()
            deposition_export[nodata_mask == 1] = nodata_value
            exporter = ResultExporter(
                data=deposition_export,
                transform=self.export_metadata.get('transform'),
                crs=self.export_metadata.get('crs'),
                nodata_value=nodata_value
            )
            exporter.to_geotiff(str(self.output_dir / "final_deposition.tif"))

        elif format == 'netcdf':
            # Export time series
            times = [r['time'] for r in self.results]
            # Transpose each time step from (cols, rows) to (rows, cols)
            depths = np.array([r['state']['h'].T for r in self.results])

            # Apply NoData mask to time series
            for t in range(len(depths)):
                depths[t][nodata_mask == 1] = nodata_value

            exporter = ResultExporter(
                data=depths,
                transform=self.export_metadata.get('transform'),
                crs=self.export_metadata.get('crs'),
                nodata_value=nodata_value
            )
            exporter.to_netcdf(
                str(self.output_dir / 'timeseries.nc'),
                times=times,
                variable_name='flow_depth'
            )

        self._export_outflow_process_text()
        self._export_hydrograph_monitor_text()
        self._export_list_z_p_fs_text()
        logger.info("Export complete")

    def _export_list_z_p_fs_text(self) -> Optional[Path]:
        """Write the EDDA `list_z_p_fs_*` text artifact with Taichi naming.

        The reference NO.5 case ships this file as a header-only stability
        listing. Emitting the same stable artifact name keeps the result family
        complete without changing runtime equations or safety-factor logic.
        """
        plan = getattr(self, "edda_runtime_control_plan", None)
        if plan is not None and plan.strict:
            # `-2` is rejected by the semantic preflight because the detailed
            # six-column UNSFIN body is not implemented.  Only the supported
            # original normal-header mode (`-1`) may reach this writer.
            if plan.output_value("pressure_head_fs_listing_flag") != -1:
                return None

        output_path = self.output_dir / "list_z_p_fs_Taichi.txt"
        output_path.write_text(
            "TRIGRS depth profiles at each cell\n"
            "Finite depth no-flow boundary\n"
            "Cell Number, Slope angle, Step#, Time\n"
            "Z         P         FS\n",
            encoding="utf-8",
        )
        return output_path

    @staticmethod
    def _iter_taichi_fields(container):
        """Yield `(name, field)` pairs for Taichi fields stored on a container."""
        for name, value in vars(container).items():
            if hasattr(value, "to_numpy") and hasattr(value, "from_numpy"):
                yield name, value

    @staticmethod
    def _restore_taichi_field(field, array: np.ndarray) -> None:
        """Restore a Taichi field from a NumPy array, handling scalar fields."""
        if getattr(field, "shape", None) == ():
            field[None] = np.asarray(array).item()
            return
        field.from_numpy(np.asarray(array))

    def save_state(self, output_file: str) -> None:
        """
        Save a full restart checkpoint for research-grade windowed reruns.

        The checkpoint contains:
        - all Taichi fields on `EDDAFields`
        - all Taichi fields on the DFS solver
        - all Taichi fields on the double-layer model (if enabled)
        - auxiliary Taichi fields on supporting physics solvers
        - non-Taichi restart arrays required by the original DFS path
        - full `TimeStepper` state
        """
        if self.fields is None or self.time_stepper is None:
            raise RuntimeError("Solver not initialized. Call initialize() before save_state().")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        arrays = {}
        for name, field in self._iter_taichi_fields(self.fields):
            arrays[f"fields__{name}"] = field.to_numpy()

        if self.dfs_dynamic_wave is not None:
            for name, field in self._iter_taichi_fields(self.dfs_dynamic_wave):
                arrays[f"dfs__{name}"] = field.to_numpy()

        if self.double_layer is not None:
            for name, field in self._iter_taichi_fields(self.double_layer):
                arrays[f"double_layer__{name}"] = field.to_numpy()

        if self.rheology is not None:
            for name, field in self._iter_taichi_fields(self.rheology):
                arrays[f"rheology__{name}"] = field.to_numpy()
            arrays["rheology__fhmax"] = np.asarray(self.rheology.fhmax)

        if self.shallow_water is not None:
            for name, field in self._iter_taichi_fields(self.shallow_water):
                arrays[f"shallow_water__{name}"] = field.to_numpy()

        if self.dfs_dynamic_wave is not None and self.dfs_dynamic_wave.initial_rikzero_field is not None:
            arrays["dfs_np__initial_rikzero_field"] = np.asarray(
                self.dfs_dynamic_wave.initial_rikzero_field,
                dtype=self.numpy_float_dtype,
            )

        arrays["time__t_start"] = np.asarray(self.time_stepper.t_start)
        arrays["time__t_end"] = np.asarray(self.time_stepper.t_end)
        arrays["time__dt_initial"] = np.asarray(self.time_stepper.dt_initial)
        arrays["time__dt_min"] = np.asarray(self.time_stepper.dt_min)
        arrays["time__dt_max"] = np.asarray(self.time_stepper.dt_max)
        arrays["time__dt_output"] = np.asarray(self.time_stepper.dt_output)
        arrays["time__CFL"] = np.asarray(self.time_stepper.CFL)
        arrays["time__dx"] = np.asarray(self.time_stepper.dx)
        arrays["time__dy"] = np.asarray(self.time_stepper.dy)
        arrays["time__t_current"] = np.asarray(self.time_stepper.t_current)
        arrays["time__dt_current"] = np.asarray(self.time_stepper.dt_current)
        arrays["time__step_count"] = np.asarray(self.time_stepper.step_count)
        arrays["time__output_count"] = np.asarray(self.time_stepper.output_count)
        arrays["time__t_last_output"] = np.asarray(self.time_stepper.t_last_output)
        arrays["time__total_steps"] = np.asarray(self.time_stepper.total_steps)
        arrays["time__rejected_steps"] = np.asarray(self.time_stepper.rejected_steps)
        arrays["time__dt_history"] = np.asarray(self.time_stepper.dt_history, dtype=self.numpy_float_dtype)
        arrays["solver__fortran_tempdt"] = np.asarray(self.fortran_tempdt)

        np.savez_compressed(output_path, **arrays)
        logger.info(f"Saved restart checkpoint: {output_path}")

    def load_state(
        self,
        input_file: str,
        *,
        override_t_end: Optional[float] = None,
        override_dt_output: Optional[float] = None,
    ) -> None:
        """
        Load a restart checkpoint previously written by `save_state`.

        Args:
            input_file: Checkpoint `.npz` path
            override_t_end: Optional replacement final simulation time
            override_dt_output: Optional replacement output interval
        """
        if self.fields is None or self.time_stepper is None:
            raise RuntimeError("Solver not initialized. Call initialize() before load_state().")

        input_path = Path(input_file)
        restored_flow_connectivity = False
        flow_connectivity_fields = {
            "cell_id",
            "flow_neighbor_id",
            "flow_neighbor_i",
            "flow_neighbor_j",
        }
        with np.load(input_path, allow_pickle=False) as checkpoint:
            for key in checkpoint.files:
                if key.startswith("fields__"):
                    name = key.split("__", 1)[1]
                    self._restore_taichi_field(getattr(self.fields, name), checkpoint[key])
                    if name in flow_connectivity_fields:
                        restored_flow_connectivity = True
                elif key.startswith("dfs__") and self.dfs_dynamic_wave is not None:
                    name = key.split("__", 1)[1]
                    self._restore_taichi_field(getattr(self.dfs_dynamic_wave, name), checkpoint[key])
                elif key.startswith("double_layer__") and self.double_layer is not None:
                    name = key.split("__", 1)[1]
                    self._restore_taichi_field(getattr(self.double_layer, name), checkpoint[key])
                elif key.startswith("rheology__") and self.rheology is not None:
                    name = key.split("__", 1)[1]
                    if name == "fhmax":
                        self.rheology.fhmax = float(np.asarray(checkpoint[key]).item())
                    else:
                        self._restore_taichi_field(getattr(self.rheology, name), checkpoint[key])
                elif key.startswith("shallow_water__") and self.shallow_water is not None:
                    name = key.split("__", 1)[1]
                    self._restore_taichi_field(getattr(self.shallow_water, name), checkpoint[key])
                elif key == "dfs_np__initial_rikzero_field" and self.dfs_dynamic_wave is not None:
                    self.dfs_dynamic_wave.initial_rikzero_field = checkpoint[key].astype(
                        self.numpy_float_dtype,
                        copy=True,
                    )

            self.time_stepper.t_start = float(np.asarray(checkpoint["time__t_start"]).item())
            self.time_stepper.t_end = float(np.asarray(checkpoint["time__t_end"]).item())
            self.time_stepper.dt_initial = float(np.asarray(checkpoint["time__dt_initial"]).item())
            self.time_stepper.dt_min = float(np.asarray(checkpoint["time__dt_min"]).item())
            self.time_stepper.dt_max = float(np.asarray(checkpoint["time__dt_max"]).item())
            self.time_stepper.dt_output = float(np.asarray(checkpoint["time__dt_output"]).item())
            self.time_stepper.CFL = float(np.asarray(checkpoint["time__CFL"]).item())
            self.time_stepper.dx = float(np.asarray(checkpoint["time__dx"]).item())
            self.time_stepper.dy = float(np.asarray(checkpoint["time__dy"]).item())
            self.time_stepper.t_current = float(np.asarray(checkpoint["time__t_current"]).item())
            self.time_stepper.dt_current = float(np.asarray(checkpoint["time__dt_current"]).item())
            self.time_stepper.step_count = int(np.asarray(checkpoint["time__step_count"]).item())
            self.time_stepper.output_count = int(np.asarray(checkpoint["time__output_count"]).item())
            self.time_stepper.t_last_output = float(np.asarray(checkpoint["time__t_last_output"]).item())
            self.time_stepper.total_steps = int(np.asarray(checkpoint["time__total_steps"]).item())
            self.time_stepper.rejected_steps = int(np.asarray(checkpoint["time__rejected_steps"]).item())
            self.time_stepper.dt_history = checkpoint["time__dt_history"].astype(np.float64, copy=False).tolist()
            if "solver__fortran_tempdt" in checkpoint:
                self.fortran_tempdt = float(np.asarray(checkpoint["solver__fortran_tempdt"]).item())
            else:
                self.fortran_tempdt = 0.0

        if restored_flow_connectivity:
            mark_changed = getattr(self.fields, "mark_flow_connectivity_changed", None)
            if callable(mark_changed):
                mark_changed()
            invalidate_cache = getattr(
                self.dfs_dynamic_wave,
                "_invalidate_flow_connectivity_host_cache",
                None,
            )
            if callable(invalidate_cache):
                invalidate_cache()

        if override_t_end is not None:
            self.time_stepper.t_end = float(override_t_end)
            self.config.time.t_end = float(override_t_end)
        if override_dt_output is not None:
            self.time_stepper.dt_output = float(override_dt_output)
            self.config.time.dt_output = float(override_dt_output)

        self.results = []
        logger.info(f"Loaded restart checkpoint: {input_path}")

    def set_progress_callback(self, callback: Callable):
        """
        Set callback function for progress updates.

        Args:
            callback: Function(time_info: dict) -> None
        """
        self.progress_callback = callback

    def _write_geotiff_frames_enabled(self) -> bool:
        compute = getattr(self.config, "compute", None)
        return bool(getattr(compute, "write_geotiff_frames", True))

    def _start_async_output_writer(self) -> None:
        compute = getattr(self.config, "compute", None)
        if not bool(getattr(compute, "async_output", False)):
            return
        if self._async_output_writer is not None:
            return
        writer = AsyncResultWriter(max_queued_frames=4)
        writer.start()
        self._async_output_writer = writer
        logger.info("Async result writer started (bounded queue=4)")

    def flush_output_writer(self) -> None:
        writer = getattr(self, "_async_output_writer", None)
        if writer is not None:
            writer.flush()

    def _stop_async_output_writer(self) -> None:
        writer = getattr(self, "_async_output_writer", None)
        if writer is None:
            return
        try:
            writer.close()
        finally:
            self._async_output_writer = None

    def _enqueue_or_write_grid(
        self,
        *,
        kind: str,
        path: str,
        data: np.ndarray,
        nodata_value: float,
    ) -> None:
        writer = getattr(self, "_async_output_writer", None)
        if writer is None:
            exporter = ResultExporter(
                data=data,
                transform=self.export_metadata.get("transform"),
                crs=self.export_metadata.get("crs"),
                nodata_value=nodata_value,
            )
            if kind == "geotiff":
                exporter.to_geotiff(path)
            elif kind == "ascii":
                exporter.to_ascii_grid(path)
            else:
                raise ValueError(f"Unsupported result write kind: {kind}")
            return
        writer.submit(
            GridWriteJob(
                kind=kind,
                path=path,
                data=np.array(data, copy=True),
                transform=self.export_metadata.get("transform"),
                crs=self.export_metadata.get("crs"),
                nodata_value=float(nodata_value),
            )
        )

    def set_output_callback(self, callback: Callable):
        """
        Set callback function for output events.

        Args:
            callback: Function(time: float, state: dict) -> None
        """
        self.output_callback = callback


def run_simulation(config_file: str):
    """
    Convenience function to run simulation from config file.

    Args:
        config_file: Path to YAML configuration file
    """
    # Load configuration
    config = SimulationConfig.from_yaml(config_file)

    # Create and run solver
    solver = EDDASolver(config)
    solver.initialize()
    solver.run()
    solver.export_final_results(format=config.output_format)

    return solver


if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run simulation
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = "config_example.yaml"

    logger.info(f"Running simulation with config: {config_file}")
    solver = run_simulation(config_file)
    logger.info("Simulation finished successfully")
