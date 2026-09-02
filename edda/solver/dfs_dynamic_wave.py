"""
Research-grade port of the original EDDA full dynamic-wave (`dfs.F90`) solver.

This solver keeps the production flow state on the Fortran-aligned 8-direction
workspace (`fv_fortran`, `qq*`, `fhpredi*`, `frhopredi*`) and exposes an
accept/retry contract so the caller can reproduce original EDDA's fixed-step
decrease / increase logic without mutating the accepted state on rejected steps.
"""

import hashlib
import os
from typing import Any

import numpy as np
import taichi as ti

from edda.config.edda_runtime_plan import EddaRuntimeControlPlan, build_runtime_control_plan
from edda.config.sim_config import SimulationConfig
from edda.core.fields import EDDAFields
from edda.io.topoindex_sidecar import (
    load_topoindex_sidecars,
    RNOFF_TOPOINDEX_RUNTIME_FLAG,
    rnoff_topoindex_runtime_enabled,
    run_rnoff_topoindex_runtime_consumer,
)
from edda.io.stormdrain_reader import (
    STORMDRAIN_RUNTIME_FLAG,
    run_stormdrain_runtime_consumer,
    stormdrain_runtime_enabled,
)
from edda.solver.dynamic_wave_fortran import FORTRAN_OPPOSITE_DIR, FortranDynamicWaveWorkspace
from edda.solver.fortran_literals import (
    DFS_ARTIVIS_COEFF,
    DFS_CFL_COEFF,
    DFS_CVLIMIT_BREAK,
    DFS_CVLIMIT_QUADRATIC_COEFF,
    DFS_CVTOL,
    DFS_DPFHTEST_OUTFLOW,
    DFS_EROSION_DEPTH_TRIGGER,
    DFS_GRAV,
    DFS_LAMBDA_EXP,
    DFS_MANNING_EXP,
    DFS_MANNINGB,
    DFS_MANNINGM,
    DFS_MIU_BASE,
    DFS_SLOPE_BRANCH,
    DFS_TOL,
    DFS_TWO_THIRDS,
    DFS_VOLUME_REL_TOL,
    FORTRAN_DEG2RAD,
    FORTRAN_INV_SQRT2,
    FORTRAN_SQRT2,
    INFR_TOLERR,
)


SQRT2 = FORTRAN_SQRT2
INV_SQRT2 = FORTRAN_INV_SQRT2
DEG2RAD = FORTRAN_DEG2RAD
# Original EDDA sets the global double-precision epsilon as `eps=1.d-18`
# in `edda main program.F90`. The DFS production path uses that threshold
# directly for zero/non-zero branching, so keep the same value here.
EPS = 1.0e-18
# Original dfs.F90 constants:
#   tol   = 0.01
#   cvtol = 0.1
TOL = DFS_TOL
CVTOL = DFS_CVTOL

MOMENTUM_FACEFLUX_PROBE_MAX_ROWS = 16
# Default-off momentum diagnostics can produce more than 512 writer rows for
# one bounded hotspot window after coupled face-owner/source staging repairs.
# Keep enough rows to avoid ring-buffer overwrite before first-divergence
# analysis; this field is only allocated/consumed by explicit probe runs.
MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS = 16384
RNOFF_PERIOD_PRECOMPUTE_ENV = "EDDA_EXPERIMENT_RNOFF_PERIOD_PRECOMPUTE"
RNOFF_TOPOINDEX_PERIOD_GPU_KERNEL_ENV = "EDDA_EXPERIMENT_RNOFF_TOPOINDEX_PERIOD_GPU_KERNEL"
DFS_ORIGINAL_PREDICTOR_RETRY_GATES_ENV = "EDDA_EXPERIMENT_DFS_ORIGINAL_PREDICTOR_RETRY_GATES"
DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT_ENV = (
    "EDDA_EXPERIMENT_DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT"
)
DFS_FACE_GATE_TOL_EPS_ENV = "EDDA_EXPERIMENT_DFS_FACE_GATE_TOL_EPS"
DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV = "EDDA_EXPERIMENT_DFS_FORTRAN_FACE_OWNER_MAX_CELL"
DFS_CVLIMIT_SEED_CVSTAR_CLAMP_ENV = "EDDA_EXPERIMENT_DFS_CVLIMIT_SEED_CVSTAR_CLAMP"
DFS_ORIGINAL_LIVE_MOVING_THIN_FACE_GATE_COMPAT_ENV = (
    "EDDA_EXPERIMENT_DFS_ORIGINAL_LIVE_MOVING_THIN_FACE_GATE_COMPAT"
)

FIRST_REJECT_NONE = 0
FIRST_REJECT_CFL = 1
FIRST_REJECT_DEPTH_CHANGE = 2
FIRST_REJECT_VOLUME = 3
FIRST_REJECT_LOW_DENSITY = 4
FIRST_REJECT_NEGATIVE_DEPTH = 5

MFP_INT_VALID = 0
MFP_INT_WRITER_KIND = 1
MFP_INT_SOURCE_I = 2
MFP_INT_SOURCE_J = 3
MFP_INT_NEIGHBOR_I = 4
MFP_INT_NEIGHBOR_J = 5
MFP_INT_TARGET_I = 6
MFP_INT_TARGET_J = 7
MFP_INT_SOURCE_CELL_ID = 8
MFP_INT_NEIGHBOR_CELL_ID = 9
MFP_INT_TARGET_CELL_ID = 10
MFP_INT_DIRECTION = 11
MFP_INT_TARGET_DIRECTION = 12
MFP_INT_OPPOSITE_DIRECTION = 13
MFP_INT_GATE_BLOCKS_FACE = 14
MFP_INT_CLAMP_STATUS = 15
MFP_INT_SIGN_FLIP_STATUS = 16
MFP_INT_ACCEPTED_STEP_ID = 17
MFP_INT_CANDIDATE_STEP_ID = 18
MFP_INT_RETRY_ATTEMPT_ID = 19
MFP_INT_REJECTED_STEP_STATUS = 20
MFP_INT_SOURCE_ENTRY_MARKER_ID = 21
MFP_INT_ASSIGNMENT_LOOP_MARKER_ID = 22
MFP_INT_ACCEPTED_PREDICTOR_STATE_ID = 23
MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID = 24
MFP_INT_COUNT = 25

MFP_FLOAT_T_START = 0
MFP_FLOAT_DT = 1
MFP_FLOAT_HI = 2
MFP_FLOAT_HN = 3
MFP_FLOAT_HBAR = 4
MFP_FLOAT_YBAR = 5
MFP_FLOAT_FHPREDI1_SOURCE = 6
MFP_FLOAT_FHPREDI1_NEIGHBOR = 7
MFP_FLOAT_FRHOPREDI1_SOURCE = 8
MFP_FLOAT_FRHOPREDI1_NEIGHBOR = 9
MFP_FLOAT_CV_SOURCE = 10
MFP_FLOAT_CV_NEIGHBOR = 11
MFP_FLOAT_CVBAR = 12
MFP_FLOAT_FRHOBAR = 13
MFP_FLOAT_GAMMADEB = 14
MFP_FLOAT_MANNINGBAR = 15
MFP_FLOAT_MIUBAR = 16
MFP_FLOAT_GRAD = 17
MFP_FLOAT_SFY = 18
MFP_FLOAT_SFMIU = 19
MFP_FLOAT_SFMANNING = 20
MFP_FLOAT_SF = 21
MFP_FLOAT_LOCALVDIFF = 22
MFP_FLOAT_ARTIVIS = 23
MFP_FLOAT_VDIFF_TERM = 24
MFP_FLOAT_DV = 25
MFP_FLOAT_FV_BEFORE = 26
MFP_FLOAT_FVPREDI_BEFORE_CLAMP = 27
MFP_FLOAT_FVPREDI_AFTER_CLAMP = 28
MFP_FLOAT_FVLIMIT = 29
MFP_FLOAT_QQT = 30
MFP_FLOAT_QQ = 31
MFP_FLOAT_QQMASS = 32
MFP_FLOAT_FRHOFLUX = 33
MFP_FLOAT_YFLUX = 34
MFP_FLOAT_WIDTH = 35
MFP_FLOAT_DT0 = 36
MFP_FLOAT_SOURCE_DEPTH_RATE = 37
MFP_FLOAT_ERORATE = 38
MFP_FLOAT_DEPORATE = 39
MFP_FLOAT_OPERAND_FV_NEIGHBOR_SAME_DIRECTION = 40
MFP_FLOAT_OPERAND_FV_SOURCE_OPPOSITE_DIRECTION = 41
MFP_FLOAT_QTNET = 42
MFP_FLOAT_QNET = 43
MFP_FLOAT_QMASSNET = 44
MFP_FLOAT_FHPREDI2_TARGET = 45
MFP_FLOAT_FRHOPREDI2_TARGET = 46
MFP_FLOAT_COUNT = 47


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


DFS_SOURCE_STAGING_FIELD_ENV = "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_FIELD"
DFS_SOURCE_STAGING_FAST_CONSUME_ENV = "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_FAST_CONSUME"
DFS_SOURCE_STAGING_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_KERNEL"
DFS_FACE_FLUX_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_FACE_FLUX_KERNEL"
DFS_QNET_QMASSNET_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_QNET_QMASSNET_KERNEL"
DFS_QNET_QMASSNET_MUTATE_ENV = "EDDA_EXPERIMENT_DFS_QNET_QMASSNET_MUTATE"
DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_PREDICTOR_DIAGNOSTIC_KERNEL"
DFS_PREDICTOR_MUTATE_ENV = "EDDA_EXPERIMENT_DFS_PREDICTOR_MUTATE"
DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_H_CV_RHO_DIAGNOSTIC_KERNEL"
DFS_H_CV_RHO_MUTATE_ENV = "EDDA_EXPERIMENT_DFS_H_CV_RHO_MUTATE"
DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL"
DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV = (
    "EDDA_EXPERIMENT_DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL"
)
DFS_EROSION_DEPOSITION_MUTATE_ENV = "EDDA_EXPERIMENT_DFS_EROSION_DEPOSITION_MUTATE"
RNOFF_GPU_FIELD_FEED_ENV = "EDDA_EXPERIMENT_RNOFF_GPU_FIELD_FEED"
RNOFF_NATIVE_UNSFIN_FEED_ENV = "EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED"
NATIVE_UNSFIN_RUNTIME_FEED_ENV = "EDDA_NATIVE_UNSFIN_RUNTIME_FEED"
PROJECT_CUDA_BACKEND_STAGE1_ENV = "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE1"
PROJECT_CUDA_BACKEND_STAGE2_ENV = "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE2"
GPU_ONLY_PRODUCTION_SMOKE_ENV = "EDDA_EXPERIMENT_GPU_ONLY_PRODUCTION_SMOKE"


MFP_INT_FIELD_NAMES = (
    "valid",
    "writer_kind",
    "source_i",
    "source_j",
    "neighbor_i",
    "neighbor_j",
    "target_i",
    "target_j",
    "source_cell_id",
    "neighbor_cell_id",
    "target_cell_id",
    "direction",
    "target_direction",
    "opposite_direction",
    "gate_blocks_face",
    "clamp_status",
    "sign_flip_status",
    "accepted_step_id",
    "candidate_step_id",
    "retry_attempt_id",
    "rejected_step_status",
    "source_entry_marker_id",
    "assignment_loop_marker_id",
    "accepted_predictor_state_id",
    "previous_predictor_carryover_state_id",
)

MFP_FLOAT_FIELD_NAMES = (
    "t_start_s",
    "dt_s",
    "hi",
    "hn",
    "hbar",
    "ybar",
    "fhpredi1_source",
    "fhpredi1_neighbor",
    "frhopredi1_source",
    "frhopredi1_neighbor",
    "cv_source",
    "cv_neighbor",
    "cvbar",
    "frhobar",
    "gammadeb",
    "manningbar",
    "miubar",
    "grad",
    "sfy",
    "sfmiu",
    "sfmanning",
    "sf",
    "localvdiff",
    "artivis",
    "vdiff_term",
    "dv",
    "fv_before",
    "fvpredi_before_clamp",
    "fvpredi_after_clamp",
    "fvlimit",
    "qqt",
    "qq",
    "qqmass",
    "frhoflux",
    "yflux",
    "width",
    "dt0",
    "source_depth_rate",
    "erorate",
    "deporate",
    "operand_fv_neighbor_same_direction",
    "operand_fv_source_opposite_direction",
    "qtnet",
    "qnet",
    "qmassnet",
    "fhpredi2_target",
    "frhopredi2_target",
)


@ti.func
def _is_outflow(fields: ti.template(), i: ti.i32, j: ti.i32) -> ti.i32:
    # Original EDDA sets `outflow(i)=.true.` only for cells listed by
    # `outflow.txt` when `outflowsimul` is active, then DFS consumes that
    # logical array in the predictor and post-balance zeroing branches.
    # Generic DEM boundary cells are not part of this Fortran `outflow(i)`
    # array, even though the current solver keeps boundary metadata for other
    # code paths.
    return 1 if fields.dfs_outflow_mask[i, j] == 1 else 0


@ti.func
def _signed_magnitude(magnitude: ti.f64, sign_src: ti.f64) -> ti.f64:
    return magnitude if sign_src >= 0.0 else -magnitude


@ti.func
def _direction_spacing(dx: ti.f64, direction: ti.i32) -> ti.f64:
    ds = dx
    if direction == 1 or direction == 3 or direction == 5 or direction == 7:
        ds = dx * SQRT2
    return ds


@ti.func
def _direction_width(dx: ti.f64, direction: ti.i32) -> ti.f64:
    width = dx * 0.5
    if direction == 1 or direction == 3 or direction == 5 or direction == 7:
        width = dx / SQRT2
    return width


def _green_ampt_average_infiltration_rate(
    cinow: float,
    inflx: float,
    dt: float,
    ksti: float,
    psiti: float,
    delth: float,
    tolerr: float = INFR_TOLERR,
) -> tuple[float, float]:
    """
    Literal single-cell port of `infr.F90`.

    Returns:
        fave: average infiltration rate during `dt`
        tempci: cumulative infiltration at the end of `dt`

    Inference:
    When `tempcinext<=0`, the Fortran expression for `ftemp` would divide by
    zero. The limiting physical behavior for zero available water is zero
    infiltration, so this port treats that case as `ftemp=+inf`, which keeps
    the branch on the "no runoff throughout the interval" path with `fave=0`.
    """
    if dt <= 0.0:
        return 0.0, cinow

    if cinow == 0.0:
        fnow = 100.0
    else:
        fnow = ksti * (psiti * delth + cinow) / cinow

    if fnow <= inflx:
        tempcinext = cinow
        dci = 1.0
        while abs(dci) >= tolerr:
            cinext = cinow + psiti * delth * np.log((tempcinext + psiti * delth) / (cinow + psiti * delth)) + ksti * dt
            dci = cinext - tempcinext
            tempcinext = cinext
        return (cinext - cinow) / dt, cinext

    tempcinext = cinow + inflx * dt
    if tempcinext <= 0.0:
        ftemp = np.inf
    else:
        ftemp = ksti * (psiti * delth + tempcinext) / tempcinext

    if ftemp <= inflx:
        cip = ksti * psiti * delth / (inflx - ksti)
        dtp = (cip - cinow) / inflx
        dci = 1.0
        tempcinext = ksti
        while abs(dci) >= tolerr:
            cinext = cip + psiti * delth * np.log((tempcinext + psiti * delth) / (cip + psiti * delth)) + ksti * (dt - dtp)
            dci = cinext - tempcinext
            tempcinext = cinext
        return (cinext - cinow) / dt, cinext

    return inflx, tempcinext


@ti.data_oriented
class DFSDynamicWaveSolver:
    """CUDA/CPU Taichi implementation of EDDA's `dfs.F90` production path."""

    def __init__(
        self,
        fields: EDDAFields,
        config: SimulationConfig,
        workspace: FortranDynamicWaveWorkspace,
        *,
        runtime_control_plan: EddaRuntimeControlPlan | None = None,
    ):
        self.fields = fields
        self.config = config
        self.workspace = workspace
        self.runtime_control_plan = runtime_control_plan or build_runtime_control_plan(config)
        self.simulate_rainfall = self.runtime_control_plan.run_enabled(
            "simulate_rainfall", compatibility_default=True
        )
        self.simulate_infiltration = self.runtime_control_plan.run_enabled(
            "simulate_infiltration", compatibility_default=True
        )
        self.simulate_outflow_cell = self.runtime_control_plan.run_enabled(
            "simulate_outflow_cell", compatibility_default=True
        )
        self.simulate_shallow_landslide = self.runtime_control_plan.run_enabled(
            "simulate_shallow_landslide", compatibility_default=True
        )
        self.simulate_erosion = self.runtime_control_plan.run_enabled(
            "simulate_erosion", compatibility_default=True
        )
        self.simulate_separate_deposition = self.runtime_control_plan.run_enabled(
            "simulate_water_and_solid_separately", compatibility_default=True
        )

        self.fp = fields.fp
        self.g = DFS_GRAV
        self.rhow = float(config.rheology.rho_water)
        self.rhos = float(config.rheology.rho_sediment)
        self.cvstar = float(config.rheology.Cv_max)
        self.limitfr = float(config.rheology.limitfr)
        self.kresis = float(config.rheology.kresis)
        self.cs = float(config.rheology.cs)
        self.manningb = DFS_MANNINGB
        self.manningm = DFS_MANNINGM
        self.d50 = float(config.erosion.d50)
        self.coedepo = float(config.erosion.coedepo)
        self.dt_min = float(config.time.dt_min)
        self.dt_max = float(config.time.dt_max)
        self.dt_increase = float(config.time.dt_increase)
        self.dt_decrease = float(config.time.dt_decrease)
        self.toldh = float(config.time.toldh)
        self.toldhp = float(config.time.toldhp)
        self.depthwt0 = float(config.hydrology.depthwt_initial)
        self.rizero0 = float(config.hydrology.rizero_initial)
        self.depthwt0_field = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.rizero0_field = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.triggerslide_field = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.slide1 = 1
        self.isslidetriggered = 0
        self.triggerslide_enabled = False
        self.cvlandslide = float(getattr(config.rheology, "cvlandslide", None) or 0.0)
        self.debrisflowmanning = float(
            getattr(config.rheology, "debrisflowmanning", None)
            or config.rheology.n_manning
        )
        self.dfs_manningbar_variant = str(
            getattr(config.hydrology, "dfs_manningbar_variant", "exponential_cv")
        )
        self.dfs_dry_face_velocity_variant = str(
            getattr(config.hydrology, "dfs_dry_face_velocity_variant", "keep_velocity_bj")
        )
        self.dfs_artivis_variant = str(
            getattr(config.hydrology, "dfs_artivis_variant", "depth_ratio_bj")
        )
        self.dfs_absubar_variant = str(
            getattr(config.hydrology, "dfs_absubar_variant", "max_component_bj")
        )

        self.reject_flag = ti.field(dtype=ti.i32, shape=())
        self.suggested_dt = ti.field(dtype=self.fp, shape=())
        self.max_wave_speed = ti.field(dtype=self.fp, shape=())
        self.step_result_pack = ti.field(dtype=self.fp, shape=4)
        self.volume_snapshot_pack = ti.field(dtype=self.fp, shape=12)
        self._rholimit_seeded = False
        self._momentum_probe_enabled_host = False
        self._momentum_probe_lightweight_host = False
        self._rainfall_zeroed = False
        self.capture_depo_velocity_snapshots = _env_flag("EDDA_CAPTURE_DEPO_VELOCITY")
        self.sync_legacy_directional_velocity = _env_flag("EDDA_SYNC_LEGACY_DIRECTIONAL_VELOCITY")
        # Observational volume-balance scalars.  These mirror the values used
        # by the existing retry gate; they are persisted for post-run audit
        # but never feed back into the candidate-step decision.
        self.volume_error = ti.field(dtype=self.fp, shape=())
        self.volume_relative_error = ti.field(dtype=self.fp, shape=())
        self.volume_denominator = ti.field(dtype=self.fp, shape=())
        self.experimental_first_reject_short_circuit = _env_flag("EDDA_EXPERIMENT_FIRST_REJECT_SHORT_CIRCUIT")
        # Source-backed original EDDA semantics. The env flag is retained only
        # for explicit ablation (`0`), not as a candidate gate.
        self.original_predictor_retry_gates_enabled = _env_flag(
            DFS_ORIGINAL_PREDICTOR_RETRY_GATES_ENV, default=True
        )
        # Original dfs.F90 keeps the depth-change retry gate active:
        #
        #   if(flexible(i) ==0. .or. rigid(i) == 0.) then
        #       if (dfhtest>toldh .and. dpfhtest>toldhp) then
        #           dt=dt-dtd
        #           goto 1000
        #       end if
        #   end if
        #
        # The ifort compatibility switch is retained only as an explicit
        # ablation for stale intermediate-oracle experiments. It must not be
        # active by default for original-live CUDA parity runs.
        self.ifort_inactive_barrier_depth_gate_compat_enabled = _env_flag(
            DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT_ENV, default=False
        )
        self.legacy_parity_mode = _env_flag("EDDA_LEGACY_PARITY_MODE")
        # Source-backed original EDDA semantics.  The active dfs.F90 erosion
        # branch consumes the scalar `cvbar` carried from the previous
        # face-flux lifecycle rather than recomputing sfy from the local cell
        # `cv`.  Keep this default-on for original-live parity; the env flag is
        # retained only for explicit ablation (`0`).
        self.legacy_cvbar_erosion_parity = self.legacy_parity_mode or _env_flag(
            "EDDA_LEGACY_CVBAR_EROSION_PARITY", default=True
        )
        self.experimental_cvbar_erosion_parity = _env_flag("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY")
        self.cvbar_erosion_parity_enabled = (
            self.legacy_cvbar_erosion_parity or self.experimental_cvbar_erosion_parity
        )
        self.legacy_previous_face_cvbar_scalar = 0.0
        self._legacy_fortran_order_face_pairs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None
        self.first_reject_count = ti.field(dtype=ti.i32, shape=())
        self.first_reject_reason = ti.field(dtype=ti.i32, shape=())
        self.first_reject_source_i = ti.field(dtype=ti.i32, shape=())
        self.first_reject_source_j = ti.field(dtype=ti.i32, shape=())
        self.first_reject_neighbor_i = ti.field(dtype=ti.i32, shape=())
        self.first_reject_neighbor_j = ti.field(dtype=ti.i32, shape=())
        self.first_reject_cell_id = ti.field(dtype=ti.i32, shape=())
        self.first_reject_neighbor_cell_id = ti.field(dtype=ti.i32, shape=())
        self.first_reject_direction = ti.field(dtype=ti.i32, shape=())
        self.first_reject_t_start = ti.field(dtype=self.fp, shape=())
        self.first_reject_dt = ti.field(dtype=self.fp, shape=())
        self.first_reject_value = ti.field(dtype=self.fp, shape=())
        self.first_reject_threshold = ti.field(dtype=self.fp, shape=())
        self.experimental_first_reject_early_return_count = ti.field(dtype=ti.i32, shape=())
        self.totaloutflowvolume = ti.field(dtype=self.fp, shape=())
        self.totalinfilvolume = ti.field(dtype=self.fp, shape=())
        self.totalinflowvolume = ti.field(dtype=self.fp, shape=())
        self.totalrivolume = ti.field(dtype=self.fp, shape=())
        self.totalerosionvolume = ti.field(dtype=self.fp, shape=())
        self.totalfsvolume = ti.field(dtype=self.fp, shape=())
        self.totaldepovolume = ti.field(dtype=self.fp, shape=())
        self.acc_outflowvolume = ti.field(dtype=self.fp, shape=())
        self.acc_infilvolume = ti.field(dtype=self.fp, shape=())
        self.acc_inflowvolume = ti.field(dtype=self.fp, shape=())
        self.acc_rivolume = ti.field(dtype=self.fp, shape=())
        self.acc_erosionvolume = ti.field(dtype=self.fp, shape=())
        self.acc_fsvolume = ti.field(dtype=self.fp, shape=())
        self.acc_depovolume = ti.field(dtype=self.fp, shape=())
        self.acc_flowvolume = ti.field(dtype=self.fp, shape=())
        self.acc_depositvolume = ti.field(dtype=self.fp, shape=())
        self.cand_totaloutflowvolume = ti.field(dtype=self.fp, shape=())
        self.cand_totalinfilvolume = ti.field(dtype=self.fp, shape=())
        self.cand_totalinflowvolume = ti.field(dtype=self.fp, shape=())
        self.cand_totalrivolume = ti.field(dtype=self.fp, shape=())
        self.cand_totalerosionvolume = ti.field(dtype=self.fp, shape=())
        self.cand_totalfsvolume = ti.field(dtype=self.fp, shape=())
        self.cand_totaldepovolume = ti.field(dtype=self.fp, shape=())
        # `dfs.F90` records `fhpredi2(outflowcell)` and its discharge before
        # zeroing the selected outflow cells.  Keep candidate and accepted
        # snapshots separate so a rejected retry cannot overwrite the last
        # accepted OUTNQ state.
        self.outflow_candidate_depth = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.outflow_candidate_density = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.outflow_accepted_depth = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.outflow_accepted_density = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.last_accepted_outflow_dt = 0.0
        self.double_layer_model = None
        self.initial_rikzero_field = None
        self.numpy_float_dtype = np.float64 if self.fp == ti.f64 else np.float32
        self.use_background_flux = bool(
            self.runtime_control_plan.run_controls.get(
                "background_flux_offset",
                getattr(config.hydrology, "use_background_flux_offset", False),
            )
        )
        self.use_transient_green_ampt = bool(getattr(config.hydrology, "use_transient_green_ampt_in_dfs", False))
        self.dfs_infiltration_variant = str(getattr(config.hydrology, "dfs_infiltration_variant", "tol_clipped_fhw"))
        self.dfs_face_flux_variant = str(getattr(config.hydrology, "dfs_face_flux_variant", "both_thin_weighted"))
        self.dfs_face_gate_tol_eps = max(0.0, _env_float(DFS_FACE_GATE_TOL_EPS_ENV, 0.0))
        face_owner_raw = os.environ.get(DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV)
        self.fortran_face_owner_max_cell_enabled = (
            False
            if face_owner_raw is None
            else face_owner_raw.strip().lower() not in {"0", "false", "no", "off"}
        )
        self.original_live_moving_thin_face_gate_compat_enabled = _env_flag(
            DFS_ORIGINAL_LIVE_MOVING_THIN_FACE_GATE_COMPAT_ENV
        )
        self.dfs_face_flux_kernel_gate_enabled = _env_flag(DFS_FACE_FLUX_KERNEL_ENV)
        self.dfs_qnet_qmassnet_kernel_gate_enabled = _env_flag(DFS_QNET_QMASSNET_KERNEL_ENV)
        self.dfs_qnet_qmassnet_mutate_gate_enabled = _env_flag(DFS_QNET_QMASSNET_MUTATE_ENV)
        self.dfs_predictor_diagnostic_kernel_gate_enabled = _env_flag(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV)
        self.dfs_predictor_mutate_gate_enabled = _env_flag(DFS_PREDICTOR_MUTATE_ENV)
        self.dfs_h_cv_rho_diagnostic_kernel_gate_enabled = _env_flag(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV)
        self.dfs_h_cv_rho_mutate_gate_enabled = _env_flag(DFS_H_CV_RHO_MUTATE_ENV)
        self.gpu_only_production_smoke_gate_enabled = _env_flag(GPU_ONLY_PRODUCTION_SMOKE_ENV)
        self.project_cuda_backend_stage2_gate_enabled = (
            _env_flag(PROJECT_CUDA_BACKEND_STAGE2_ENV)
            or self.gpu_only_production_smoke_gate_enabled
        )
        self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled = (
            _env_flag(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV)
            or self.project_cuda_backend_stage2_gate_enabled
        )
        self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled = (
            _env_flag(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV)
            or self.project_cuda_backend_stage2_gate_enabled
        )
        self.dfs_erosion_deposition_mutate_gate_enabled = (
            _env_flag(DFS_EROSION_DEPOSITION_MUTATE_ENV)
            or self.project_cuda_backend_stage2_gate_enabled
        )
        self.dfs_failure_source_variant = str(getattr(config.hydrology, "dfs_failure_source_variant", "live_doublelayer_in_dfs"))
        self.use_fortran_absubar_velocity_state = bool(
            getattr(config.hydrology, "use_fortran_absubar_velocity_state", False)
        )
        self.use_tol_subtracted_inflx = bool(getattr(config.hydrology, "use_tol_subtracted_inflx_in_dfs", False))
        self.use_tanslodir_carry_quirk = bool(getattr(config.compute, "use_tanslodir_carry_quirk", False))
        self.cvlimit_seed_cvstar_clamp_enabled = _env_flag(DFS_CVLIMIT_SEED_CVSTAR_CLAMP_ENV)
        self._ci_candidate: np.ndarray | None = None
        self._flow_connectivity_host_cache: dict[str, np.ndarray] | None = None
        self._flow_connectivity_host_cache_version: int | None = None
        self._flow_connectivity_host_cache_refresh_count = 0
        self.current_time = 0.0
        self.rnoff_topoindex_hook_config: dict[str, object] | None = None
        self.rnoff_period_precompute_ir_field = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.rnoff_period_precompute_active = ti.field(dtype=ti.i32, shape=())
        self.rnoff_period_precompute_ir_grid: np.ndarray | None = None
        self.rnoff_topoindex_period_gpu_kernel_gate_enabled = _env_flag(RNOFF_TOPOINDEX_PERIOD_GPU_KERNEL_ENV)
        self.rnoff_topoindex_period_gpu_kernel_loaded = False
        self.rnoff_topoindex_period_gpu_kernel_blocked_reason: str | None = None
        self.rnoff_topoindex_gpu_imax = ti.field(dtype=ti.i32, shape=())
        self.rnoff_topoindex_gpu_dsc_count = ti.field(dtype=ti.i32, shape=())
        self.rnoff_topoindex_gpu_nxt_field = None
        self.rnoff_topoindex_gpu_indx_field = None
        self.rnoff_topoindex_gpu_dsctr_field = None
        self.rnoff_topoindex_gpu_dsc_field = None
        self.rnoff_topoindex_gpu_wf_field = None
        self.rnoff_topoindex_gpu_rideb_by_cell = None
        self.rnoff_topoindex_gpu_kst_by_cell = None
        self.rnoff_topoindex_gpu_depth_by_cell = None
        self.rnoff_topoindex_gpu_rizero_by_cell = None
        self.rnoff_topoindex_gpu_ro_by_cell = None
        self.rnoff_topoindex_gpu_rik_by_cell = None
        self.rnoff_topoindex_gpu_ir_by_cell = None
        self.rnoff_period_precompute_manifest: dict[str, object] = {
            "rnoff_period_precompute_enabled": False,
            "rnoff_period_precompute_active": False,
            "default_off_verified": True,
            "changed_field_names": [],
            "fail_closed": False,
            "blocked_reason": None,
        }
        self.rnoff_topoindex_runtime_manifest: dict[str, object] = {
            "rnoff_topoindex_runtime_enabled": False,
            "rnoff_topoindex_branch_active": False,
            "changed_field_names": [],
            "blocked_reason": None,
            "fail_closed": False,
        }
        self.rnoff_topoindex_period_summaries: list[dict[str, object]] = []
        self.rnoff_topoindex_ro_state: np.ndarray | None = None
        self.rnoff_topoindex_rik_state: np.ndarray | None = None
        self.stormdrain_hook_config: dict[str, object] | None = None
        self.stormdrain_runtime_manifest: dict[str, object] = {
            "stormdrain_runtime_enabled": False,
            "stormdrain_branch_active": False,
            "changed_field_names": [],
            "blocked_reason": None,
            "fail_closed": False,
        }
        self.stormdrain_period_summaries: list[dict[str, object]] = []
        self.collect_erosion_step_diagnostics = False
        self.erosion_step_top_cell_limit = 50
        self.erosion_step_tracked_cell_ids: set[int] = set()
        self.erosion_step_diagnostics: list[dict[str, object]] = []
        self.stage_trace_enabled = False
        self.stage_trace_window_start = -np.inf
        self.stage_trace_window_end = np.inf
        self.stage_trace_target_cells: list[int] = []
        self.stage_trace_target_indices: list[tuple[int, int, int]] = []
        self.stage_trace_records: list[dict[str, object]] = []
        self.face_flux_kernel_qq = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny, 8))
        self.face_flux_kernel_qqmass = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny, 8))
        self.face_flux_kernel_fvpred = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny, 8))
        self.face_flux_kernel_valid_mask = ti.field(dtype=ti.i32, shape=(fields.nx, fields.ny, 8))
        self.face_flux_kernel_info = self._default_face_flux_kernel_info()
        self.qnet_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.qmassnet_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.qnet_qmassnet_diag_cell_mask = ti.field(dtype=ti.i32, shape=(fields.nx, fields.ny))
        self.qnet_qmassnet_kernel_info = self._default_qnet_qmassnet_kernel_info()
        self.qnet_qmassnet_mutation_info = self._default_qnet_qmassnet_mutation_info()
        self.fhpredi2_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.frhopredi2_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.predictor_diag_cell_mask = ti.field(dtype=ti.i32, shape=(fields.nx, fields.ny))
        self.predictor_kernel_info = self._default_predictor_kernel_info()
        self.predictor_mutation_info = self._default_predictor_mutation_info()
        self.h_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.Cv_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.rho_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
        self.h_cv_rho_diag_cell_mask = ti.field(dtype=ti.i32, shape=(fields.nx, fields.ny))
        self.h_cv_rho_kernel_info = self._default_h_cv_rho_kernel_info()
        self.h_cv_rho_mutation_info = self._default_h_cv_rho_mutation_info()
        self.erorate_diag_kernel = None
        self.deporate_diag_kernel = None
        self.erosion_depth_diag_kernel = None
        self.deposition_depth_diag_kernel = None
        self.erosion_deposition_diag_cell_mask = None
        self.source_depth_rate_diag_kernel = None
        self.z_bed_candidate_diag_kernel = None
        self.erosion_depth_delta_diag_kernel = None
        self.deposition_depth_delta_diag_kernel = None
        self.erosion_depth_candidate_diag_kernel = None
        self.deposition_depth_candidate_diag_kernel = None
        self.deep_state_diag_cell_mask = None
        if (
            self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled
            or self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            or self.dfs_erosion_deposition_mutate_gate_enabled
        ):
            self.erorate_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.deporate_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.erosion_depth_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.deposition_depth_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.erosion_deposition_diag_cell_mask = ti.field(dtype=ti.i32, shape=(fields.nx, fields.ny))
            self.source_depth_rate_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.z_bed_candidate_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.erosion_depth_delta_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.deposition_depth_delta_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.erosion_depth_candidate_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.deposition_depth_candidate_diag_kernel = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny))
            self.deep_state_diag_cell_mask = ti.field(dtype=ti.i32, shape=(fields.nx, fields.ny))
        self.erosion_deposition_kernel_info = self._default_erosion_deposition_kernel_info()
        self.erosion_deposition_deep_state_kernel_info = (
            self._default_erosion_deposition_deep_state_kernel_info()
        )
        self.erosion_deposition_mutation_info = self._default_erosion_deposition_mutation_info()
        self.momentum_faceflux_probe_enabled = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_lightweight = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_target_cell_id = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_target_direction = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_count = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_consumed_probe_count = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_history_count = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_assignment_history_count = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_t_start = ti.field(dtype=self.fp, shape=())
        self.momentum_faceflux_probe_dt = ti.field(dtype=self.fp, shape=())
        self.momentum_faceflux_probe_accepted_step_id = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_candidate_step_id = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_retry_attempt_id = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_rejected_step_status = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_accepted_predictor_state_id = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_previous_predictor_carryover_state_id = ti.field(dtype=ti.i32, shape=())
        self.momentum_faceflux_probe_int = ti.field(
            dtype=ti.i32,
            shape=(MOMENTUM_FACEFLUX_PROBE_MAX_ROWS, MFP_INT_COUNT),
        )
        self.momentum_faceflux_probe_float = ti.field(
            dtype=self.fp,
            shape=(MOMENTUM_FACEFLUX_PROBE_MAX_ROWS, MFP_FLOAT_COUNT),
        )
        self.momentum_faceflux_consumed_probe_int = ti.field(
            dtype=ti.i32,
            shape=(MOMENTUM_FACEFLUX_PROBE_MAX_ROWS, MFP_INT_COUNT),
        )
        self.momentum_faceflux_consumed_probe_float = ti.field(
            dtype=self.fp,
            shape=(MOMENTUM_FACEFLUX_PROBE_MAX_ROWS, MFP_FLOAT_COUNT),
        )
        self.momentum_faceflux_history_int = ti.field(
            dtype=ti.i32,
            shape=(MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS, MFP_INT_COUNT),
        )
        self.momentum_faceflux_history_float = ti.field(
            dtype=self.fp,
            shape=(MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS, MFP_FLOAT_COUNT),
        )
        self.momentum_faceflux_assignment_history_int = ti.field(
            dtype=ti.i32,
            shape=(MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS, MFP_INT_COUNT),
        )
        self.momentum_faceflux_assignment_history_float = ti.field(
            dtype=self.fp,
            shape=(MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS, MFP_FLOAT_COUNT),
        )
        self.inflow_hydrographs: list[dict[str, object]] = []
        self.inflow_denominator_config: dict[str, object] = {
            "variant": str(getattr(config.hydrology, "inflow_denominator_variant", "CELLAREA") or "CELLAREA").upper(),
            "source": None,
            "basis": None,
            "direction": getattr(config.hydrology, "inflow_denominator_direction", None),
            "fv_value": getattr(config.hydrology, "inflow_denominator_fv_value", None),
        }
        self.inflow_last_stage_diagnostics: dict[str, object] = {
            "configured_cell_count": 0,
            "inflow_denominator_variant": self.inflow_denominator_config["variant"],
            "sample_count": 0,
            "samples": [],
        }
        self.precomputed_failure_tfail: np.ndarray | None = None
        self.precomputed_failure_gindx: np.ndarray | None = None
        self.precomputed_failure_fdepth: np.ndarray | None = None
        self.precomputed_failure_fired: np.ndarray | None = None
        self.precomputed_failure_tfail_field = None
        self.precomputed_failure_gindx_field = None
        self.precomputed_failure_fdepth_field = None
        self.precomputed_failure_committed_fire_mask_field = None
        self.precomputed_failure_candidate_fire_mask_field = None
        self.precomputed_failure_source_depth_staging_field = None
        self.precomputed_failure_source_density_staging_field = None
        self.precomputed_failure_candidate_count_field = ti.field(dtype=ti.i32, shape=())
        self.precomputed_failure_candidate_depth_sum_field = ti.field(dtype=self.fp, shape=())
        self.precomputed_failure_candidate_mass_sum_field = ti.field(dtype=self.fp, shape=())
        self._precomputed_failure_field_shape: tuple[int, int] | None = None
        self._precomputed_failure_fast_consume_validated = False
        self._precomputed_failure_candidate_fired: np.ndarray | None = None
        self._precomputed_failure_candidate_cell_count = 0
        self._precomputed_failure_candidate_depth_sum = 0.0
        self._precomputed_failure_candidate_mass_sum = 0.0
        self._precomputed_failure_candidate_window_end: float | None = None
        self.precomputed_failure_schedule_info: dict[str, object] = {
            "configured": False,
            "scheduled_cell_count": 0,
            "fired_cell_count": 0,
            "gindx_zero_no_feed_count": 0,
            "inactive_no_feed_count": 0,
            "candidate_fired_count": 0,
            "committed_fired_count": 0,
            "duplicate_fire_count": 0,
            "rejected_step_discard_count": 0,
            "total_staged_cell_count": 0,
            "total_staged_depth_sum": 0.0,
            "total_staged_mass_sum": 0.0,
            "crossing_count_by_checkpoint": {},
            "last_staged_cell_count": 0,
            "last_staged_depth_sum": 0.0,
            "last_staged_mass_sum": 0.0,
            "last_window_start_s": None,
            "last_window_end_s": None,
            "dfs_source_staging_field_gate_enabled": False,
            "dfs_source_staging_field_active": False,
            "source_staging_field_roundtrip_ok": None,
            "source_staging_cpu_vs_taichi_match": None,
            "dfs_source_staging_fast_consume_gate_enabled": False,
            "dfs_source_staging_fast_consume_active": False,
            "parity_validation_mode": "cpu",
            "parity_validation_once_per_configure": False,
            "per_stage_parity_download_disabled": False,
            "source_staging_device_consumed": False,
            "cpu_fallback_active": False,
            "parity_download_count": 0,
            "candidate_stage_count": 0,
            "schedule_configure_count": 0,
            "dfs_source_staging_field_fallback_reason": None,
            "source_staging_depth_max_abs_error": None,
            "source_staging_density_max_abs_error": None,
            "source_staging_candidate_mask_mismatch_count": None,
            "dfs_source_staging_fast_consume_gate_enabled": False,
            "dfs_source_staging_fast_consume_active": False,
            "parity_validation_mode": "cpu",
            "parity_validation_once_per_configure": False,
            "per_stage_parity_download_disabled": False,
            "source_staging_device_consumed": False,
            "cpu_fallback_active": False,
            "transfer_bytes_h2d": 0,
            "transfer_bytes_d2h": 0,
            "parity_download_count": 0,
            "schedule_configure_count": 0,
            "candidate_stage_count": 0,
            "dfs_source_staging_kernel_gate_enabled": False,
            "dfs_source_staging_kernel_required_gates_active": False,
            "dfs_source_staging_kernel_active": False,
            "source_staging_kernel_vs_cpu_match": None,
            "kernel_fallback_active": False,
            "kernel_fallback_reason": None,
            "kernel_candidate_stage_count": 0,
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": 0,
            "schedule_consumed_by_dfs": False,
            "final_state_mutated": False,
            "rnoff_gpu_field_feed_gate_enabled": False,
            "rnoff_gpu_field_feed_active": False,
            "schedule_buffer_uploaded_to_taichi": False,
            "taichi_schedule_buffer_roundtrip_ok": None,
            "taichi_schedule_buffer_shape": None,
            "taichi_schedule_buffer_dtype": None,
            "taichi_schedule_buffer_fallback_reason": None,
            "taichi_schedule_buffer_max_abs_error_tfail": None,
            "taichi_schedule_buffer_max_abs_error_fdepth": None,
            "taichi_schedule_buffer_gindx_mismatch_count": None,
        }
        self.rnoff_provider_shadow_schedule_info: dict[str, object] = {
            "shadow_schedule_loaded": False,
            "shadow_schedule_row_count": 0,
            "shadow_active_row_count": 0,
            "shadow_crossing_count": 0,
            "shadow_candidate_stage_count": 0,
            "shadow_rejected_discard_count": 0,
            "shadow_accepted_commit_count": 0,
            "shadow_duplicate_fire_count": 0,
            "shadow_final_state_mutated": False,
            "schedule_consumed_by_dfs": False,
            "changed_field_names": [],
            "fallback_reason": None,
            "events": [],
        }
        self.rholimit_initialized = ti.field(dtype=ti.i32, shape=())
        self.tanslodir_carry = ti.field(dtype=self.fp, shape=8)

        # Directional velocity exported in original Fortran order:
        # [N, NE, E, SE, S, SW, W, NW]
        self.vdir_legacy = ti.field(dtype=self.fp, shape=(fields.nx, fields.ny, 8))
        self.depthwt0_field.from_numpy(
            np.full((fields.nx, fields.ny), self.depthwt0, dtype=self.numpy_float_dtype)
        )
        self.rizero0_field.from_numpy(
            np.full((fields.nx, fields.ny), self.rizero0, dtype=self.numpy_float_dtype)
        )
        self.triggerslide_field.from_numpy(
            np.zeros((fields.nx, fields.ny), dtype=self.numpy_float_dtype)
        )
        self.outflow_candidate_depth.fill(0.0)
        self.outflow_candidate_density.fill(self.rhow)
        self.outflow_accepted_depth.fill(0.0)
        self.outflow_accepted_density.fill(self.rhow)

    def get_last_accepted_outflow_samples(
        self,
        cells: list[dict[str, int]],
        *,
        dt_used: float | None = None,
    ) -> list[dict[str, float]]:
        """Return original-order OUTNQ samples from the accepted pre-clear state."""
        sample_dt = self.last_accepted_outflow_dt if dt_used is None else float(dt_used)
        if sample_dt <= 0.0:
            return []

        density_span = self.rhos - self.rhow
        samples: list[dict[str, float]] = []
        for cell in cells:
            i = int(cell["i"])
            j = int(cell["j"])
            depth = float(self.outflow_accepted_depth[i, j])
            density = float(self.outflow_accepted_density[i, j])
            cell_area = float(self.fields.cell_area_cal[i, j])
            cv = 0.0 if density_span <= 0.0 else max((density - self.rhow) / density_span, 0.0)
            samples.append(
                {
                    "cell_id": int(cell["cell_id"]),
                    "predictor_depth": depth,
                    "predictor_density": density,
                    "discharge_cms": depth * cell_area / sample_dt,
                    "cv": cv,
                }
            )
        return samples

    def set_double_layer_model(self, double_layer_model) -> None:
        self.double_layer_model = double_layer_model

    def set_initial_rikzero_field(self, rikzero_field: np.ndarray) -> None:
        if rikzero_field is None:
            self.initial_rikzero_field = None
            return
        self.initial_rikzero_field = np.asarray(rikzero_field, dtype=self.numpy_float_dtype)

    def set_initial_depthwt_field(self, depthwt_field: np.ndarray | None) -> None:
        if depthwt_field is None:
            self.depthwt0_field.from_numpy(
                np.full((self.fields.nx, self.fields.ny), self.depthwt0, dtype=self.numpy_float_dtype)
            )
            return
        depthwt_np = np.asarray(depthwt_field, dtype=self.numpy_float_dtype)
        if depthwt_np.shape != (self.fields.nx, self.fields.ny):
            raise ValueError(
                f"Initial depthwt field shape {depthwt_np.shape} does not match solver shape {(self.fields.nx, self.fields.ny)}."
            )
        self.depthwt0_field.from_numpy(depthwt_np)

    def set_triggerslide_field(self, trigger_field: np.ndarray | None) -> None:
        """Load original `triggerslide` grid. Independent of `fssimul`.

        Fortran: `edda main program.F90` always reads the raster; `dfs.F90:103`
        copies it to `temptriggerslide`, then `dfs.F90:559-564` adds it once
        when `slide1==1 .and. tnow>0`.
        """
        if trigger_field is None:
            self.triggerslide_field.from_numpy(
                np.zeros((self.fields.nx, self.fields.ny), dtype=self.numpy_float_dtype)
            )
            self.triggerslide_enabled = False
            return
        trigger_np = np.asarray(trigger_field, dtype=self.numpy_float_dtype)
        if trigger_np.shape != (self.fields.nx, self.fields.ny):
            raise ValueError(
                f"Triggering-slide field shape {trigger_np.shape} does not match solver shape {(self.fields.nx, self.fields.ny)}."
            )
        self.triggerslide_field.from_numpy(trigger_np)
        self.triggerslide_enabled = True
        self.slide1 = 1
        self.isslidetriggered = 0

    def set_initial_rizero_field(self, rizero_field: np.ndarray | None) -> None:
        if rizero_field is None:
            self.rizero0_field.from_numpy(
                np.full((self.fields.nx, self.fields.ny), self.rizero0, dtype=self.numpy_float_dtype)
            )
            return
        rizero_np = np.asarray(rizero_field, dtype=self.numpy_float_dtype)
        if rizero_np.shape != (self.fields.nx, self.fields.ny):
            raise ValueError(
                f"Initial rizero field shape {rizero_np.shape} does not match solver shape {(self.fields.nx, self.fields.ny)}."
            )
        self.rizero0_field.from_numpy(rizero_np)

    def configure_rnoff_topoindex_runtime_hook(
        self,
        *,
        nxtfil: str | os.PathLike | None,
        ndxfil: str | os.PathLike | None,
        dscfil: str | os.PathLike | None,
        wffil: str | os.PathLike | None,
        imax: int | None = None,
    ) -> dict[str, object]:
        """Configure the default-off RNOFF/TopoIndex runtime hook.

        Configuration alone does not load sidecars or mutate fields. The hook
        remains inert unless ``EDDA_EXPERIMENT_RNOFF_TOPOINDEX=1`` is set.
        """
        active_imax = self._active_cell_count()
        hook_imax = int(imax if imax is not None else active_imax)
        self.rnoff_topoindex_hook_config = {
            "nxtfil": None if nxtfil is None else str(nxtfil),
            "ndxfil": None if ndxfil is None else str(ndxfil),
            "dscfil": None if dscfil is None else str(dscfil),
            "wffil": None if wffil is None else str(wffil),
            "imax": hook_imax,
            "active_cell_count": active_imax,
            "feature_flag": f"{RNOFF_TOPOINDEX_RUNTIME_FLAG}=1",
        }
        self.rnoff_topoindex_runtime_manifest = {
            "rnoff_topoindex_available": all(
                self.rnoff_topoindex_hook_config.get(name) for name in ("nxtfil", "ndxfil", "dscfil", "wffil")
            ),
            "rnoff_topoindex_selected": rnoff_topoindex_runtime_enabled(),
            "rnoff_topoindex_runtime_enabled": rnoff_topoindex_runtime_enabled(),
            "rnoff_topoindex_branch_active": False,
            "sidecar_shape_validated": False,
            "changed_field_names": [],
            "blocked_reason": None,
            "fail_closed": False,
            "default_off_verified": not rnoff_topoindex_runtime_enabled(),
            "active_cell_count": active_imax,
            "imax": hook_imax,
        }
        return dict(self.rnoff_topoindex_runtime_manifest)

    def get_rnoff_topoindex_runtime_manifest(self) -> dict[str, object]:
        """Return the latest RNOFF/TopoIndex hook diagnostics."""
        return dict(self.rnoff_topoindex_runtime_manifest)

    def _ensure_rnoff_topoindex_period_gpu_fields(self) -> bool:
        if self.rnoff_topoindex_period_gpu_kernel_loaded:
            return True
        if self.rnoff_topoindex_hook_config is None:
            self.rnoff_topoindex_period_gpu_kernel_blocked_reason = "RNOFF_TOPOINDEX_HOOK_CONFIG_MISSING"
            return False

        try:
            active_imax = self._active_cell_count()
            imax = int(self.rnoff_topoindex_hook_config.get("imax") or active_imax)
            if imax != active_imax:
                imax = active_imax
            sidecars = load_topoindex_sidecars(
                nxtfil=self.rnoff_topoindex_hook_config.get("nxtfil") or "",
                ndxfil=self.rnoff_topoindex_hook_config.get("ndxfil") or "",
                dscfil=self.rnoff_topoindex_hook_config.get("dscfil") or "",
                wffil=self.rnoff_topoindex_hook_config.get("wffil") or "",
                imax=imax,
            )
        except Exception as exc:
            self.rnoff_topoindex_period_gpu_kernel_blocked_reason = str(exc)
            return False

        self.rnoff_topoindex_gpu_imax[None] = int(sidecars.imax)
        self.rnoff_topoindex_gpu_dsc_count[None] = int(len(sidecars.dsc) - 1)
        scalar_shape = int(len(sidecars.nxt))
        dsctr_shape = int(len(sidecars.dsctr))
        dsc_shape = int(len(sidecars.dsc))
        self.rnoff_topoindex_gpu_nxt_field = ti.field(dtype=ti.i32, shape=scalar_shape)
        self.rnoff_topoindex_gpu_indx_field = ti.field(dtype=ti.i32, shape=scalar_shape)
        self.rnoff_topoindex_gpu_dsctr_field = ti.field(dtype=ti.i32, shape=dsctr_shape)
        self.rnoff_topoindex_gpu_dsc_field = ti.field(dtype=ti.i32, shape=dsc_shape)
        self.rnoff_topoindex_gpu_wf_field = ti.field(dtype=self.fp, shape=dsc_shape)
        self.rnoff_topoindex_gpu_rideb_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)
        self.rnoff_topoindex_gpu_kst_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)
        self.rnoff_topoindex_gpu_depth_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)
        self.rnoff_topoindex_gpu_rizero_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)
        self.rnoff_topoindex_gpu_ro_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)
        self.rnoff_topoindex_gpu_rik_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)
        self.rnoff_topoindex_gpu_ir_by_cell = ti.field(dtype=self.fp, shape=scalar_shape)

        self.rnoff_topoindex_gpu_nxt_field.from_numpy(np.asarray(sidecars.nxt, dtype=np.int32))
        self.rnoff_topoindex_gpu_indx_field.from_numpy(np.asarray(sidecars.indx, dtype=np.int32))
        self.rnoff_topoindex_gpu_dsctr_field.from_numpy(np.asarray(sidecars.dsctr, dtype=np.int32))
        self.rnoff_topoindex_gpu_dsc_field.from_numpy(np.asarray(sidecars.dsc, dtype=np.int32))
        self.rnoff_topoindex_gpu_wf_field.from_numpy(np.asarray(sidecars.wf, dtype=self.numpy_float_dtype))
        self.rnoff_topoindex_period_gpu_kernel_loaded = True
        self.rnoff_topoindex_period_gpu_kernel_blocked_reason = None
        return True

    def configure_stormdrain_runtime_hook(
        self,
        *,
        drainage_path: str | os.PathLike | None,
        expected_node_count: int | None = None,
        expected_conduit_count: int | None = None,
    ) -> dict[str, object]:
        """Configure the default-off stormdrain topology hook.

        The hook is diagnostic-only in this phase. It validates original
        ``drainage.txt`` topology behind ``EDDA_EXPERIMENT_STORMDRAIN=1`` and
        does not alter DFS equations, face connectivity, hydrograph staging, or
        other runtime fields.
        """
        active_imax = self._active_cell_count()
        self.stormdrain_hook_config = {
            "drainage_path": None if drainage_path is None else str(drainage_path),
            "expected_node_count": expected_node_count,
            "expected_conduit_count": expected_conduit_count,
            "imax": active_imax,
            "active_cell_count": active_imax,
            "feature_flag": f"{STORMDRAIN_RUNTIME_FLAG}=1",
        }
        selected = stormdrain_runtime_enabled()
        self.stormdrain_runtime_manifest = {
            "stormdrain_available": bool(drainage_path) and os.path.isfile(str(drainage_path)),
            "stormdrain_selected": selected,
            "stormdrain_runtime_enabled": selected,
            "stormdrain_branch_active": False,
            "drainage_topology_validated": False,
            "changed_field_names": [],
            "blocked_reason": None,
            "fail_closed": False,
            "default_off_verified": not selected,
            "drainage_path": None if drainage_path is None else str(drainage_path),
            "active_cell_count": active_imax,
            "imax": active_imax,
            "expected_node_count": expected_node_count,
            "expected_conduit_count": expected_conduit_count,
            "mutation_contract": {
                "dfs_equations_changed": False,
                "dfs_face_connectivity_changed": False,
                "hydrograph_exporter_changed": False,
                "inflow_denominator_changed": False,
                "native_unsfin_schedule_changed": False,
                "rnoff_behavior_changed": False,
            },
        }
        return dict(self.stormdrain_runtime_manifest)

    def get_stormdrain_runtime_manifest(self) -> dict[str, object]:
        """Return the latest stormdrain hook diagnostics."""
        return dict(self.stormdrain_runtime_manifest)

    def _active_cell_count(self) -> int:
        cell_id = self._get_flow_connectivity_numpy_cached()["cell_id"]
        return int(np.count_nonzero(cell_id > 0))

    def _invalidate_flow_connectivity_host_cache(self) -> None:
        """Invalidate cached immutable host snapshots for topology/index fields."""
        self._flow_connectivity_host_cache = None
        self._flow_connectivity_host_cache_version = None
        self._legacy_fortran_order_face_pairs = None

    def _get_flow_connectivity_numpy_cached(self) -> dict[str, np.ndarray]:
        """Return immutable host snapshots for static cell/connectivity fields.

        These arrays are written during grid/connectivity initialization and are
        not part of accepted/rejected dynamic DFS state. Dynamic fields such as
        h/Cv/rho/infiltration/erosion are intentionally excluded from this cache.
        """
        version_getter = getattr(self.fields, "flow_connectivity_version", None)
        version = int(version_getter()) if callable(version_getter) else None
        if (
            self._flow_connectivity_host_cache is None
            or self._flow_connectivity_host_cache_version != version
        ):
            cache = {
                "cell_id": np.ascontiguousarray(self.fields.cell_id.to_numpy()),
                "flow_neighbor_id": np.ascontiguousarray(self.fields.flow_neighbor_id.to_numpy()),
                "flow_neighbor_i": np.ascontiguousarray(self.fields.flow_neighbor_i.to_numpy()),
                "flow_neighbor_j": np.ascontiguousarray(self.fields.flow_neighbor_j.to_numpy()),
            }
            for array in cache.values():
                array.setflags(write=False)
            self._flow_connectivity_host_cache = cache
            self._flow_connectivity_host_cache_version = version
            self._flow_connectivity_host_cache_refresh_count += 1
        return self._flow_connectivity_host_cache

    def _flow_connectivity_hash(self) -> str:
        digest = hashlib.sha256()
        cache = self._get_flow_connectivity_numpy_cached()
        for name in ("cell_id", "flow_neighbor_id", "flow_neighbor_i", "flow_neighbor_j"):
            array = cache[name]
            digest.update(array.dtype.str.encode("ascii"))
            digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
            digest.update(array.tobytes())
        return digest.hexdigest()

    @staticmethod
    def _one_based_from_grid(grid: np.ndarray, cell_id_grid: np.ndarray, *, imax: int, name: str) -> list[float]:
        values = [0.0] * (imax + 1)
        mask = cell_id_grid > 0
        ids = cell_id_grid[mask].astype(np.int64, copy=False)
        if ids.size != imax:
            raise ValueError(f"{name} active-cell count {ids.size} does not match imax {imax}")
        max_cell_id = int(ids.max()) if ids.size else 0
        if max_cell_id > imax:
            raise ValueError(f"{name} active-cell id exceeds imax {imax}")
        grid_values = grid[mask]
        for cell_id, value in zip(ids, grid_values):
            values[int(cell_id)] = float(value)
        return values

    @staticmethod
    def _grid_from_cell_values(
        values_by_cell: dict[str, float] | dict[int, float],
        cell_id_grid: np.ndarray,
        *,
        dtype: np.dtype,
    ) -> np.ndarray:
        result = np.zeros(cell_id_grid.shape, dtype=dtype)
        for raw_cell_id, value in values_by_cell.items():
            cell_id = int(raw_cell_id)
            if cell_id <= 0:
                continue
            result[cell_id_grid == cell_id] = float(value)
        return result

    def apply_rnoff_topoindex_runtime_hook(
        self,
        dt: float,
        *,
        rideb_grid_override: np.ndarray | None = None,
        environ: dict[str, str] | None = None,
        mutate_infiltration: bool = True,
        hook_stage: str = "late_hook",
    ) -> dict[str, object]:
        """Apply the configured RNOFF/TopoIndex hook to staged DFS fields.

        The hook is default-off. With the flag unset it returns direct fallback
        diagnostics and leaves all runtime fields untouched. With the flag set,
        it delegates to the source-backed TopoIndex helper and mutates only the
        staged infiltration field plus diagnostic ro/rik arrays.
        """
        if (
            hook_stage == "late_hook"
            and bool(self.rnoff_period_precompute_manifest.get("rnoff_period_precompute_enabled", False))
        ):
            manifest = dict(self.rnoff_topoindex_runtime_manifest)
            manifest.update(
                {
                    "rnoff_late_hook_skipped_due_period_precompute": True,
                    "rnoff_topoindex_runtime_enabled": False,
                    "rnoff_topoindex_branch_active": False,
                    "changed_field_names": [],
                    "fail_closed": False,
                    "blocked_reason": None,
                }
            )
            self.rnoff_topoindex_runtime_manifest = manifest
            return dict(manifest)

        if self.rnoff_topoindex_hook_config is None:
            return dict(self.rnoff_topoindex_runtime_manifest)

        config = self.rnoff_topoindex_hook_config
        cell_id_grid = self._get_flow_connectivity_numpy_cached()["cell_id"].astype(np.int32, copy=False)
        active_imax = int(np.count_nonzero(cell_id_grid > 0))
        imax = int(config.get("imax") or active_imax)
        if active_imax != imax:
            imax = active_imax

        dfs_hash_before = self._flow_connectivity_hash()
        if rideb_grid_override is None:
            rideb_grid = self.fields.tempri.to_numpy().astype(np.float64, copy=False)
        else:
            rideb_grid = np.asarray(rideb_grid_override, dtype=np.float64)
        if self.use_transient_green_ampt:
            kst_grid = self.fields.K_sat_field.to_numpy().astype(np.float64, copy=False)
        else:
            kst_grid = self.fields.K_sat_top_field.to_numpy().astype(np.float64, copy=False)
        depth_grid = self.depthwt0_field.to_numpy().astype(np.float64, copy=False)
        rizero_grid = self.rizero0_field.to_numpy().astype(np.float64, copy=False)

        rideb = self._one_based_from_grid(rideb_grid, cell_id_grid, imax=imax, name="rideb")
        kst = self._one_based_from_grid(kst_grid, cell_id_grid, imax=imax, name="kst")
        depth = self._one_based_from_grid(depth_grid, cell_id_grid, imax=imax, name="depth")
        rizero = self._one_based_from_grid(rizero_grid, cell_id_grid, imax=imax, name="rizero")

        manifest = run_rnoff_topoindex_runtime_consumer(
            nxtfil=config.get("nxtfil"),
            ndxfil=config.get("ndxfil"),
            dscfil=config.get("dscfil"),
            wffil=config.get("wffil"),
            imax=imax,
            rideb=rideb,
            kst=kst,
            depth=depth,
            rizero=rizero,
            environ=environ,
        )
        dfs_hash_after = self._flow_connectivity_hash()
        manifest.update(
            {
                "dt": float(dt),
                "hook_stage": hook_stage,
                "mutate_infiltration": bool(mutate_infiltration),
                "active_cell_count": active_imax,
                "imax": imax,
                "dfs_connectivity_hash_before": dfs_hash_before,
                "dfs_connectivity_hash_after": dfs_hash_after,
                "dfs_connectivity_changed": dfs_hash_before != dfs_hash_after,
                "native_unsfin_schedule_changed": False,
                "hydrograph_exporter_changed": False,
                "inflow_denominator_changed": False,
            }
        )

        if (
            manifest.get("rnoff_topoindex_runtime_enabled")
            and manifest.get("rnoff_topoindex_branch_active")
            and not manifest.get("fail_closed")
        ):
            ir_grid = self._grid_from_cell_values(
                manifest["ir_after"],
                cell_id_grid,
                dtype=self.numpy_float_dtype,
            )
            if mutate_infiltration:
                self.fields.infiltration.from_numpy(ir_grid)
            else:
                self.rnoff_period_precompute_ir_grid = ir_grid.astype(self.numpy_float_dtype, copy=False)
                self.rnoff_period_precompute_ir_field.from_numpy(self.rnoff_period_precompute_ir_grid)
                self.rnoff_period_precompute_active[None] = 1
            ro_state = np.zeros(imax + 1, dtype=np.float64)
            rik_state = np.zeros(imax + 1, dtype=np.float64)
            for raw_cell_id, value in manifest["ro_after"].items():
                ro_state[int(raw_cell_id)] = float(value)
            for raw_cell_id, value in manifest["rik_after"].items():
                rik_state[int(raw_cell_id)] = float(value)
            self.rnoff_topoindex_ro_state = ro_state
            self.rnoff_topoindex_rik_state = rik_state

        self.rnoff_topoindex_runtime_manifest = manifest
        self.rnoff_topoindex_period_summaries.append(
            {
                "dt": float(dt),
                "rnoff_topoindex_runtime_enabled": bool(manifest.get("rnoff_topoindex_runtime_enabled")),
                "rnoff_topoindex_branch_active": bool(manifest.get("rnoff_topoindex_branch_active")),
                "sidecar_shape_validated": bool(manifest.get("sidecar_shape_validated")),
                "fail_closed": bool(manifest.get("fail_closed")),
                "blocked_reason": manifest.get("blocked_reason"),
                "changed_field_names": list(manifest.get("changed_field_names") or []),
                "dfs_connectivity_changed": bool(manifest.get("dfs_connectivity_changed")),
                "totals": manifest.get("totals", {}),
            }
        )
        return manifest

    def apply_rnoff_period_precompute(self, dt: float) -> dict[str, object]:
        """Compute source-aligned RNOFF period state before DFS surface staging.

        The original EDDA sequence computes RNOFF before optional UNSFIN and
        before DFS/WFS.  This default-off path uses the same validated
        RNOFF/TopoIndex runtime consumer, but it consumes rainfall (`rideb`)
        directly and stores the period `ir` in a scratch Taichi field so surface
        staging can recompute `fhpredi1/frhopredi1` from the precomputed result.
        """
        enabled = _env_flag(RNOFF_PERIOD_PRECOMPUTE_ENV) or _env_flag(GPU_ONLY_PRODUCTION_SMOKE_ENV)
        if not enabled:
            self.rnoff_period_precompute_active[None] = 0
            self.rnoff_period_precompute_ir_grid = None
            self.rnoff_period_precompute_manifest = {
                "rnoff_period_precompute_enabled": False,
                "rnoff_period_precompute_active": False,
                "default_off_verified": True,
                "changed_field_names": [],
                "fail_closed": False,
                "blocked_reason": None,
            }
            return dict(self.rnoff_period_precompute_manifest)

        if self.use_transient_green_ampt:
            self.rnoff_period_precompute_active[None] = 0
            self.rnoff_period_precompute_ir_grid = None
            self.rnoff_period_precompute_manifest = {
                "rnoff_period_precompute_enabled": True,
                "rnoff_period_precompute_active": False,
                "default_off_verified": False,
                "changed_field_names": [],
                "fail_closed": True,
                "blocked_reason": "RNOFF_PERIOD_PRECOMPUTE_TRANSIENT_GREEN_AMPT_UNSUPPORTED",
            }
            return dict(self.rnoff_period_precompute_manifest)

        if self.rnoff_topoindex_hook_config is None:
            self.rnoff_period_precompute_active[None] = 0
            self.rnoff_period_precompute_manifest = {
                "rnoff_period_precompute_enabled": True,
                "rnoff_period_precompute_active": False,
                "default_off_verified": False,
                "changed_field_names": [],
                "fail_closed": True,
                "blocked_reason": "RNOFF_TOPOINDEX_HOOK_CONFIG_MISSING",
            }
            return dict(self.rnoff_period_precompute_manifest)

        if _env_flag(RNOFF_TOPOINDEX_PERIOD_GPU_KERNEL_ENV):
            manifest = self._apply_rnoff_period_precompute_gpu_kernel(dt)
            self.rnoff_period_precompute_manifest = dict(manifest)
            return dict(manifest)

        rainfall_grid = self.fields.rainfall.to_numpy().astype(np.float64, copy=False)
        manifest = self.apply_rnoff_topoindex_runtime_hook(
            dt,
            rideb_grid_override=rainfall_grid,
            environ={RNOFF_TOPOINDEX_RUNTIME_FLAG: "1"},
            mutate_infiltration=False,
            hook_stage="period_precompute",
        )
        active = bool(
            manifest.get("rnoff_topoindex_runtime_enabled")
            and manifest.get("rnoff_topoindex_branch_active")
            and not manifest.get("fail_closed")
        )
        if not active:
            self.rnoff_period_precompute_active[None] = 0
            self.rnoff_period_precompute_ir_grid = None
        manifest.update(
            {
                "rnoff_period_precompute_enabled": True,
                "rnoff_period_precompute_active": active,
                "rnoff_period_precompute_env": RNOFF_PERIOD_PRECOMPUTE_ENV,
                "default_off_verified": False,
                "production_changed_field_names": [],
                "diagnostic_output_fields": list(manifest.get("changed_field_names") or []),
            }
        )
        self.rnoff_period_precompute_manifest = dict(manifest)
        return dict(manifest)

    def _apply_rnoff_period_precompute_gpu_kernel(self, dt: float) -> dict[str, object]:
        loaded = self._ensure_rnoff_topoindex_period_gpu_fields()
        if not loaded:
            manifest = {
                "rnoff_period_precompute_enabled": True,
                "rnoff_period_precompute_active": False,
                "rnoff_topoindex_runtime_enabled": True,
                "rnoff_topoindex_branch_active": False,
                "hook_stage": "period_precompute",
                "mutate_infiltration": False,
                "changed_field_names": [],
                "production_changed_field_names": [],
                "diagnostic_output_fields": [],
                "fail_closed": True,
                "blocked_reason": self.rnoff_topoindex_period_gpu_kernel_blocked_reason,
                "rnoff_topoindex_period_gpu_kernel_gate_enabled": True,
                "rnoff_topoindex_period_gpu_kernel_active": False,
                "host_runtime_consumer_used": False,
            }
            self.rnoff_period_precompute_active[None] = 0
            return manifest

        self._rnoff_topoindex_period_gpu_prepare_inputs()
        self._rnoff_topoindex_period_gpu_route()
        self._rnoff_topoindex_period_gpu_write_ir_grid()
        self.rnoff_period_precompute_active[None] = 1
        self.rnoff_period_precompute_ir_grid = None
        manifest = {
            "rnoff_period_precompute_enabled": True,
            "rnoff_period_precompute_active": True,
            "rnoff_topoindex_runtime_enabled": True,
            "rnoff_topoindex_branch_active": True,
            "sidecar_shape_validated": True,
            "hook_stage": "period_precompute",
            "mutate_infiltration": False,
            "active_cell_count": int(self.rnoff_topoindex_gpu_imax[None]),
            "imax": int(self.rnoff_topoindex_gpu_imax[None]),
            "dt": float(dt),
            "changed_field_names": ["ir", "rik", "ro"],
            "diagnostic_output_fields": ["ir", "rik", "ro"],
            "production_changed_field_names": [],
            "period_precompute_ir_resident_field": True,
            "rnoff_topoindex_period_gpu_kernel_gate_enabled": True,
            "rnoff_topoindex_period_gpu_kernel_active": True,
            "host_runtime_consumer_used": False,
            "default_off_verified": False,
            "fail_closed": False,
            "blocked_reason": None,
        }
        self.rnoff_topoindex_runtime_manifest = dict(manifest)
        self.rnoff_topoindex_period_summaries.append(
            {
                "dt": float(dt),
                "rnoff_topoindex_runtime_enabled": True,
                "rnoff_topoindex_branch_active": True,
                "sidecar_shape_validated": True,
                "fail_closed": False,
                "blocked_reason": None,
                "changed_field_names": ["ir", "rik", "ro"],
                "dfs_connectivity_changed": False,
                "host_runtime_consumer_used": False,
                "rnoff_topoindex_period_gpu_kernel_active": True,
            }
        )
        return manifest

    @ti.kernel
    def _rnoff_topoindex_period_gpu_prepare_inputs(self):
        for cell_id in range(self.rnoff_topoindex_gpu_imax[None] + 1):
            self.rnoff_topoindex_gpu_rideb_by_cell[cell_id] = 0.0
            self.rnoff_topoindex_gpu_kst_by_cell[cell_id] = 0.0
            self.rnoff_topoindex_gpu_depth_by_cell[cell_id] = 0.0
            self.rnoff_topoindex_gpu_rizero_by_cell[cell_id] = 0.0
            self.rnoff_topoindex_gpu_ro_by_cell[cell_id] = 0.0
            self.rnoff_topoindex_gpu_rik_by_cell[cell_id] = 0.0
            self.rnoff_topoindex_gpu_ir_by_cell[cell_id] = 0.0

        for i, j in self.fields.h:
            cell_id = self.fields.cell_id[i, j]
            if self.fields.is_nodata[i, j] == 0 and cell_id > 0:
                self.rnoff_topoindex_gpu_rideb_by_cell[cell_id] = self.fields.rainfall[i, j]
                self.rnoff_topoindex_gpu_kst_by_cell[cell_id] = self.fields.K_sat_top_field[i, j]
                self.rnoff_topoindex_gpu_depth_by_cell[cell_id] = self.depthwt0_field[i, j]
                self.rnoff_topoindex_gpu_rizero_by_cell[cell_id] = self.rizero0_field[i, j]
                self.rnoff_topoindex_gpu_ir_by_cell[cell_id] = self.fields.K_sat_top_field[i, j]

    @ti.kernel
    def _rnoff_topoindex_period_gpu_route(self):
        ti.loop_config(serialize=True)
        for order_index in range(1, self.rnoff_topoindex_gpu_imax[None] + 1):
            cell_id = self.rnoff_topoindex_gpu_indx_field[order_index]
            next_cell = self.rnoff_topoindex_gpu_nxt_field[cell_id]
            inflx = self.rnoff_topoindex_gpu_ro_by_cell[cell_id] + self.rnoff_topoindex_gpu_rideb_by_cell[cell_id]
            kst_value = self.rnoff_topoindex_gpu_kst_by_cell[cell_id]
            rnof = 0.0

            if self.rnoff_topoindex_gpu_depth_by_cell[cell_id] == 0.0 and self.rnoff_topoindex_gpu_rizero_by_cell[cell_id] < 0.0:
                self.rnoff_topoindex_gpu_ir_by_cell[cell_id] = 0.0
                self.rnoff_topoindex_gpu_rik_by_cell[cell_id] = 0.0
                rnof = inflx - self.rnoff_topoindex_gpu_rizero_by_cell[cell_id]
                self.rnoff_topoindex_gpu_ro_by_cell[cell_id] = rnof
                for entry in range(
                    self.rnoff_topoindex_gpu_dsctr_field[cell_id],
                    self.rnoff_topoindex_gpu_dsctr_field[cell_id + 1],
                ):
                    target = self.rnoff_topoindex_gpu_dsc_field[entry]
                    weight = self.rnoff_topoindex_gpu_wf_field[entry]
                    if target == cell_id:
                        self.rnoff_topoindex_gpu_ro_by_cell[target] += rnof * (weight - 1.0)
                    else:
                        self.rnoff_topoindex_gpu_ro_by_cell[target] += rnof * weight
            elif kst_value < inflx:
                self.rnoff_topoindex_gpu_rik_by_cell[cell_id] = 1.0
                rnof = inflx - kst_value
                self.rnoff_topoindex_gpu_ro_by_cell[cell_id] = rnof
                for entry in range(
                    self.rnoff_topoindex_gpu_dsctr_field[cell_id],
                    self.rnoff_topoindex_gpu_dsctr_field[cell_id + 1],
                ):
                    target = self.rnoff_topoindex_gpu_dsc_field[entry]
                    weight = self.rnoff_topoindex_gpu_wf_field[entry]
                    if target == cell_id:
                        self.rnoff_topoindex_gpu_ro_by_cell[target] += rnof * (weight - 1.0)
                    else:
                        self.rnoff_topoindex_gpu_ro_by_cell[target] += rnof * weight
            else:
                self.rnoff_topoindex_gpu_ir_by_cell[cell_id] = inflx
                if kst_value > 0.0:
                    self.rnoff_topoindex_gpu_rik_by_cell[cell_id] = inflx / kst_value
                else:
                    self.rnoff_topoindex_gpu_rik_by_cell[cell_id] = 0.0
                self.rnoff_topoindex_gpu_ro_by_cell[cell_id] = 0.0
                self.rnoff_topoindex_gpu_ro_by_cell[next_cell] += rnof

    @ti.kernel
    def _rnoff_topoindex_period_gpu_write_ir_grid(self):
        for i, j in self.fields.h:
            cell_id = self.fields.cell_id[i, j]
            if self.fields.is_nodata[i, j] == 0 and cell_id > 0:
                self.rnoff_period_precompute_ir_field[i, j] = self.rnoff_topoindex_gpu_ir_by_cell[cell_id]
            else:
                self.rnoff_period_precompute_ir_field[i, j] = 0.0

    @ti.kernel
    def _apply_rnoff_period_precompute_surface_staging_kernel(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
    ):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.infiltration[i, j] = 0.0
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water
                continue

            ir = self.rnoff_period_precompute_ir_field[i, j]
            self.fields.infiltration[i, j] = ir

            fhpredi1 = self.fields.h[i, j] + (self.fields.tempri[i, j] - ir) * dt + self.fields.tempinflowh[i, j]
            if fhpredi1 <= 0.0:
                fhpredi1 = 0.0
            self.fields.fhpredi1[i, j] = fhpredi1

            if fhpredi1 <= EPS:
                self.fields.frhopredi1[i, j] = rho_water
            else:
                mass = (
                    self.fields.rho[i, j] * self.fields.h[i, j]
                    + (self.fields.tempri[i, j] - ir) * dt * rho_water
                    + self.fields.tempinflowh[i, j] * self.fields.tempinflowrho[i, j]
                )
                self.fields.frhopredi1[i, j] = mass / fhpredi1

            if _is_outflow(self.fields, i, j) == 1:
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water

    def apply_rnoff_period_precompute_to_surface_staging(self, dt: float) -> dict[str, object]:
        """Apply period-precomputed RNOFF `ir` to staged DFS source fields."""
        manifest = dict(self.rnoff_period_precompute_manifest)
        if not bool(manifest.get("rnoff_period_precompute_active", False)):
            manifest.update(
                {
                    "period_precompute_applied_to_surface_staging": False,
                    "fhpredi1_frhopredi1_recomputed_after_period_precompute": False,
                }
            )
            self.rnoff_period_precompute_manifest = dict(manifest)
            return dict(manifest)

        self._apply_rnoff_period_precompute_surface_staging_kernel(float(dt), self.rhow)
        manifest.update(
            {
                "period_precompute_applied_to_surface_staging": True,
                "fhpredi1_frhopredi1_recomputed_after_period_precompute": True,
                "production_changed_field_names": ["infiltration", "fhpredi1", "frhopredi1"],
            }
        )
        self.rnoff_period_precompute_manifest = dict(manifest)
        return dict(manifest)

    def apply_stormdrain_runtime_hook(self, dt: float) -> dict[str, object]:
        """Apply the configured default-off stormdrain exchange hook.

        The hook mirrors the source-backed ``dfs.F90`` drainage exchange point:
        it consumes staged ``fhpredi2`` after face-flux accumulation, subtracts
        node intake, records a first-step dry-network ``dwflow`` diagnostic, and
        adds return volume when present. It remains inert unless
        ``EDDA_EXPERIMENT_STORMDRAIN=1`` is set.
        """
        if self.stormdrain_hook_config is None:
            return dict(self.stormdrain_runtime_manifest)

        config = self.stormdrain_hook_config
        cell_id_grid = self._get_flow_connectivity_numpy_cached()["cell_id"].astype(np.int32, copy=False)
        active_imax = self._active_cell_count()
        dfs_hash_before = self._flow_connectivity_hash()
        fhpredi2_grid = self.fields.fhpredi2.to_numpy().astype(np.float64, copy=False)
        fhpredi2 = self._one_based_from_grid(fhpredi2_grid, cell_id_grid, imax=active_imax, name="fhpredi2")
        manifest = run_stormdrain_runtime_consumer(
            drainage_path=config.get("drainage_path"),
            imax=active_imax,
            fhpredi2=fhpredi2,
            cell_area=float(self.fields.dx * self.fields.dy),
            dt=float(dt),
            tnow=float(self.current_time),
            tnext=float(self.current_time + dt),
            ttout=float(self.current_time + dt),
            expected_node_count=config.get("expected_node_count"),
            expected_conduit_count=config.get("expected_conduit_count"),
        )
        if (
            manifest.get("stormdrain_runtime_enabled")
            and manifest.get("stormdrain_branch_active")
            and not manifest.get("fail_closed")
        ):
            fh_after = self._grid_from_cell_values(
                manifest.get("fh_after_by_cell", {}),
                cell_id_grid,
                dtype=self.numpy_float_dtype,
            )
            self.fields.fhpredi2.from_numpy(fh_after)
        dfs_hash_after = self._flow_connectivity_hash()
        manifest.update(
            {
                "dt": float(dt),
                "active_cell_count": active_imax,
                "imax": active_imax,
                "dfs_connectivity_hash_before": dfs_hash_before,
                "dfs_connectivity_hash_after": dfs_hash_after,
                "dfs_connectivity_changed": dfs_hash_before != dfs_hash_after,
                "native_unsfin_schedule_changed": False,
                "hydrograph_exporter_changed": False,
                "inflow_denominator_changed": False,
                "dfs_equations_changed": False,
                "rnoff_behavior_changed": False,
            }
        )
        mutation_contract = dict(manifest.get("mutation_contract") or {})
        mutation_contract.update(
            {
                "dfs_equations_changed": False,
                "dfs_face_connectivity_changed": bool(manifest["dfs_connectivity_changed"]),
                "hydrograph_exporter_changed": False,
                "inflow_denominator_changed": False,
                "native_unsfin_schedule_changed": False,
                "rnoff_behavior_changed": False,
            }
        )
        manifest["mutation_contract"] = mutation_contract

        self.stormdrain_runtime_manifest = manifest
        self.stormdrain_period_summaries.append(
            {
                "dt": float(dt),
                "stormdrain_runtime_enabled": bool(manifest.get("stormdrain_runtime_enabled")),
                "stormdrain_branch_active": bool(manifest.get("stormdrain_branch_active")),
                "drainage_topology_validated": bool(
                    manifest.get("drainage_topology_validated") or manifest.get("topology_loaded")
                ),
                "fail_closed": bool(manifest.get("fail_closed")),
                "blocked_reason": manifest.get("blocked_reason"),
                "changed_field_names": list(manifest.get("changed_field_names") or []),
                "dfs_connectivity_changed": bool(manifest.get("dfs_connectivity_changed")),
                "node_count": int(manifest.get("node_count", 0) or 0),
                "conduit_count": int(manifest.get("conduit_count", 0) or 0),
            }
        )
        return manifest

    def set_current_time(self, current_time: float) -> None:
        self.current_time = float(current_time)

    def enable_erosion_step_diagnostics(
        self,
        enabled: bool = True,
        *,
        top_cell_limit: int = 50,
        tracked_cell_ids: list[int] | tuple[int, ...] | set[int] | None = None,
        clear: bool = True,
    ) -> None:
        """Enable observational accepted-step erosion diagnostics.

        This is intentionally opt-in. It synchronizes Taichi fields to NumPy on
        accepted steps and must not be enabled in production runs unless a
        caller explicitly asks for diagnostic artifacts.
        """
        self.collect_erosion_step_diagnostics = bool(enabled)
        self.erosion_step_top_cell_limit = max(0, int(top_cell_limit))
        self.erosion_step_tracked_cell_ids = {int(cell_id) for cell_id in (tracked_cell_ids or [])}
        if clear:
            self.erosion_step_diagnostics = []

    def get_erosion_step_diagnostics(self) -> list[dict[str, object]]:
        return list(self.erosion_step_diagnostics)

    def configure_stage_trace(
        self,
        *,
        enabled: bool,
        target_cell_ids: list[int] | tuple[int, ...],
        window_start_s: float,
        window_end_s: float,
        clear: bool = True,
    ) -> dict[str, object]:
        """Configure disabled-by-default DFS stage tracing.

        This is a diagnostics-only recorder. It samples existing fields between
        the established DFS kernels and does not participate in the numerical
        update.
        """
        self.stage_trace_enabled = bool(enabled)
        self.stage_trace_window_start = float(window_start_s)
        self.stage_trace_window_end = float(window_end_s)
        self.stage_trace_target_cells = [int(cell_id) for cell_id in target_cell_ids]
        if clear:
            self.stage_trace_records.clear()

        cell_ids = np.asarray(self._get_flow_connectivity_numpy_cached()["cell_id"], dtype=np.int64)
        targets: list[tuple[int, int, int]] = []
        for cell_id in self.stage_trace_target_cells:
            matches = np.argwhere(cell_ids == cell_id)
            if matches.shape[0] != 1:
                raise ValueError(f"expected one grid location for cell {cell_id}, found {matches.shape[0]}")
            i, j = int(matches[0, 0]), int(matches[0, 1])
            targets.append((cell_id, i, j))
        self.stage_trace_target_indices = targets
        return {
            "enabled": self.stage_trace_enabled,
            "target_cell_ids": list(self.stage_trace_target_cells),
            "target_count": len(self.stage_trace_target_indices),
            "window_start_s": self.stage_trace_window_start,
            "window_end_s": self.stage_trace_window_end,
        }

    def get_stage_trace_records(self) -> list[dict[str, object]]:
        return list(self.stage_trace_records)

    def _stage_trace_window_active(self, dt_used: float) -> bool:
        if not self.stage_trace_enabled:
            return False
        if not self.stage_trace_target_indices:
            return False
        t_start = float(self.current_time)
        t_end = t_start + float(dt_used)
        return t_end >= self.stage_trace_window_start and t_start <= self.stage_trace_window_end

    def _record_stage_trace(
        self,
        stage: str,
        dt_used: float,
        *,
        event: str,
        commit_time: bool = False,
        display_dt: float | None = None,
        face_flux: bool = False,
    ) -> None:
        if not self._stage_trace_window_active(dt_used):
            return

        t_start = float(self.current_time)
        t_end = t_start + float(dt_used)
        if commit_time:
            tnow = t_end
            tnext = t_end
        else:
            tnow = t_start
            tnext = t_end
        dt_display = float(dt_used if display_dt is None else display_dt)
        nt = int(self.momentum_faceflux_probe_candidate_step_id[None])

        h = self.fields.h.to_numpy()
        rho = self.fields.rho.to_numpy()
        cv = self.fields.Cv.to_numpy()
        tempfsh = self.fields.tempfsh_flow.to_numpy()
        tempfsrho = self.fields.tempfsrho_flow.to_numpy()
        fhpredi1 = self.fields.fhpredi1.to_numpy()
        frhopredi1 = self.fields.frhopredi1.to_numpy()
        fhpredi = self.fields.fhpredi.to_numpy()
        frhopredi = self.fields.frhopredi.to_numpy()
        tempele = self.fields.tempele.to_numpy()
        erorate = self.fields.erorate_clamped_temp.to_numpy()
        deporate = self.fields.deporate_clamped_temp.to_numpy()
        fvpred = self.fields.fv_pred_fortran.to_numpy()
        qq = self.fields.qq_fortran.to_numpy()
        qqmass = self.fields.qqmass_fortran.to_numpy()
        qnet = self.fields.qnet_fortran.to_numpy()
        qmassnet = self.fields.qmassnet_fortran.to_numpy()
        fhpredi2 = self.fields.fhpredi2.to_numpy()
        frhopredi2 = self.fields.frhopredi2.to_numpy()
        fybar = self.fields.fybar_fortran.to_numpy()

        for cell_id, i, j in self.stage_trace_target_indices:
            directions = range(8) if face_flux else (None,)
            for direction in directions:
                if direction is None:
                    dir_value = 0
                    fvpred_value = 0.0
                    qq_value = 0.0
                    qqmass_value = 0.0
                    hbar_value = 0.0
                else:
                    dir_value = int(direction) + 1
                    fvpred_value = float(fvpred[i, j, direction])
                    qq_value = float(qq[i, j, direction])
                    qqmass_value = float(qqmass[i, j, direction])
                    hbar_value = float(fybar[i, j, direction])

                fhpredi_value = float(fhpredi[i, j])
                fhpredi2_value = float(fhpredi2[i, j])
                dfhtest = abs(fhpredi2_value - fhpredi_value)
                if fhpredi_value != 0.0:
                    dpfhtest = abs((fhpredi2_value - fhpredi_value) / fhpredi_value)
                elif dfhtest > 0.0:
                    dpfhtest = 1.0e12
                else:
                    dpfhtest = 0.0
                source_depth_rate = 0.0
                if dt_used > 0.0:
                    source_depth_rate = (
                        float(tempfsh[i, j]) / float(dt_used)
                        + float(erorate[i, j])
                        + float(deporate[i, j])
                    )

                self.stage_trace_records.append(
                    {
                        "stage": stage,
                        "nt": nt,
                        "tnow": tnow,
                        "tnext": tnext,
                        "dt": dt_display,
                        "cell": int(cell_id),
                        "dir": dir_value,
                        "nq": 0,
                        "event": event,
                        "fh": float(h[i, j]),
                        "frho": float(rho[i, j]),
                        "cv": float(cv[i, j]),
                        "tempfsh": float(tempfsh[i, j]),
                        "tempfsrho": float(tempfsrho[i, j]),
                        "fhpredi1": float(fhpredi1[i, j]),
                        "frhopredi1": float(frhopredi1[i, j]),
                        "fhpredi": fhpredi_value,
                        "frhopredi": float(frhopredi[i, j]),
                        "tempele": float(tempele[i, j]),
                        "erorate": float(erorate[i, j]),
                        "deporate": float(deporate[i, j]),
                        "source_depth_rate": source_depth_rate,
                        "hbar": hbar_value,
                        "cvbar": 0.0,
                        "frhobar": 0.0,
                        "sfy": 0.0,
                        "sfmiu": 0.0,
                        "sfmanning": 0.0,
                        "sf": 0.0,
                        "fvpredi": fvpred_value,
                        "qq": qq_value,
                        "qqmass": qqmass_value,
                        "qnet": float(qnet[i, j]) if stage in {"POST_FLUX", "RETRY_CHECK", "COMMIT"} else 0.0,
                        "qmassnet": float(qmassnet[i, j]) if stage in {"POST_FLUX", "RETRY_CHECK", "COMMIT"} else 0.0,
                        "fhpredi2": fhpredi2_value,
                        "frhopredi2": float(frhopredi2[i, j]),
                        "dfhtest": dfhtest,
                        "dpfhtest": dpfhtest,
                    }
                )

    def get_first_reject_diagnostics(self) -> dict[str, object]:
        reason = int(self.first_reject_reason[None])
        reason_name = {
            FIRST_REJECT_NONE: None,
            FIRST_REJECT_CFL: "CFL",
            FIRST_REJECT_DEPTH_CHANGE: "depth_change",
            FIRST_REJECT_VOLUME: "volume",
            FIRST_REJECT_LOW_DENSITY: "low_density",
            FIRST_REJECT_NEGATIVE_DEPTH: "negative_depth",
        }.get(reason, "unknown")
        return {
            "experiment_flag": "EDDA_EXPERIMENT_FIRST_REJECT_SHORT_CIRCUIT",
            "experiment_enabled": bool(self.experimental_first_reject_short_circuit),
            "predictor_retry_gates_flag": DFS_ORIGINAL_PREDICTOR_RETRY_GATES_ENV,
            "predictor_retry_gates_enabled": bool(self.original_predictor_retry_gates_enabled),
            "ifort_inactive_barrier_depth_gate_compat_flag": DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT_ENV,
            "ifort_inactive_barrier_depth_gate_compat_enabled": bool(
                self.ifort_inactive_barrier_depth_gate_compat_enabled
            ),
            "first_reject_count": int(self.first_reject_count[None]),
            "first_reject_reason": reason,
            "first_reject_reason_name": reason_name,
            "source_i": int(self.first_reject_source_i[None]),
            "source_j": int(self.first_reject_source_j[None]),
            "neighbor_i": int(self.first_reject_neighbor_i[None]),
            "neighbor_j": int(self.first_reject_neighbor_j[None]),
            "cell_id": int(self.first_reject_cell_id[None]),
            "neighbor_cell_id": int(self.first_reject_neighbor_cell_id[None]),
            "direction_zero_based": int(self.first_reject_direction[None]),
            "direction_one_based": int(self.first_reject_direction[None]) + 1
            if int(self.first_reject_direction[None]) >= 0
            else None,
            "t_start_s": float(self.first_reject_t_start[None]),
            "dt_s": float(self.first_reject_dt[None]),
            "value": float(self.first_reject_value[None]),
            "threshold": float(self.first_reject_threshold[None]),
            "early_return_count": int(self.experimental_first_reject_early_return_count[None]),
        }

    def get_volume_balance_snapshot(self) -> dict[str, float | bool]:
        """Return accepted cumulative volumes and the last candidate balance.

        The scalar fields are the same values already used by
        ``_finalize_volume_balance``.  Reading them on the host is deliberately
        kept outside the Taichi kernels so this method remains observational.
        ``acc_flowvolume`` and ``acc_depositvolume`` are the current accepted
        storage values because the accumulators are reset at the start of each
        candidate step and committed only after a successful retry check.
        """

        self._pack_volume_balance_snapshot()
        pack = np.asarray(self.volume_snapshot_pack.to_numpy(), dtype=np.float64)
        rainfall = float(pack[0])
        inflow = float(pack[1])
        erosion = float(pack[2])
        failure_source = float(pack[3])
        infiltration = float(pack[4])
        outflow = float(pack[5])
        deposition_flux = float(pack[6])
        flow_storage = float(pack[7])
        deposit_storage = float(pack[8])
        denominator = float(pack[9])
        residual = float(pack[10])
        relative_error = float(pack[11])

        return {
            "rainfall_m3": rainfall,
            "inflow_m3": inflow,
            "erosion_m3": erosion,
            "failure_source_m3": failure_source,
            "infiltration_m3": infiltration,
            "outflow_m3": outflow,
            "deposition_flux_m3": deposition_flux,
            "flow_storage_m3": flow_storage,
            "deposit_storage_m3": deposit_storage,
            "source_total_m3": rainfall + inflow + erosion + failure_source,
            "sink_and_storage_total_m3": (
                infiltration + outflow + flow_storage + deposit_storage
            ),
            "denominator_m3": denominator,
            "residual_m3": residual,
            "relative_error": relative_error,
            "within_retry_tolerance": abs(relative_error) <= DFS_VOLUME_REL_TOL,
        }

    @ti.kernel
    def _pack_volume_balance_snapshot(self):
        self.volume_snapshot_pack[0] = self.totalrivolume[None]
        self.volume_snapshot_pack[1] = self.totalinflowvolume[None]
        self.volume_snapshot_pack[2] = self.totalerosionvolume[None]
        self.volume_snapshot_pack[3] = self.totalfsvolume[None]
        self.volume_snapshot_pack[4] = self.totalinfilvolume[None]
        self.volume_snapshot_pack[5] = self.totaloutflowvolume[None]
        self.volume_snapshot_pack[6] = self.totaldepovolume[None]
        self.volume_snapshot_pack[7] = self.acc_flowvolume[None]
        self.volume_snapshot_pack[8] = self.acc_depositvolume[None]
        self.volume_snapshot_pack[9] = self.volume_denominator[None]
        self.volume_snapshot_pack[10] = self.volume_error[None]
        self.volume_snapshot_pack[11] = self.volume_relative_error[None]

    def enable_momentum_faceflux_tracked_probe(
        self,
        *,
        enabled: bool = True,
        target_cell_id: int = 35978,
        target_direction: int = 5,
        lightweight: bool = True,
        clear: bool = True,
    ) -> None:
        """Enable tracked scalar momentum/face-flux diagnostics for one face."""
        self.momentum_faceflux_probe_enabled[None] = 1 if enabled else 0
        self.momentum_faceflux_probe_lightweight[None] = 1 if lightweight else 0
        self._momentum_probe_enabled_host = bool(enabled)
        self._momentum_probe_lightweight_host = bool(lightweight)
        self.momentum_faceflux_probe_target_cell_id[None] = int(target_cell_id)
        self.momentum_faceflux_probe_target_direction[None] = int(target_direction)
        if clear:
            self._reset_momentum_faceflux_tracked_probe()
            self._reset_momentum_faceflux_consumed_probe()
            self._reset_momentum_faceflux_history_probe()
            self._reset_momentum_faceflux_assignment_history_probe()

    def set_momentum_faceflux_lifecycle_metadata(
        self,
        *,
        accepted_step_id: int,
        candidate_step_id: int,
        retry_attempt_id: int,
        rejected_step_status: int = 0,
        accepted_predictor_state_id: int,
        previous_predictor_carryover_state_id: int,
    ) -> None:
        """Attach accepted/retry lifecycle ids to tracked scalar diagnostics.

        These ids are diagnostics-only. They do not participate in the solver
        formula or accepted-state mutation.
        """
        self.momentum_faceflux_probe_accepted_step_id[None] = int(accepted_step_id)
        self.momentum_faceflux_probe_candidate_step_id[None] = int(candidate_step_id)
        self.momentum_faceflux_probe_retry_attempt_id[None] = int(retry_attempt_id)
        self.momentum_faceflux_probe_rejected_step_status[None] = int(rejected_step_status)
        self.momentum_faceflux_probe_accepted_predictor_state_id[None] = int(accepted_predictor_state_id)
        self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None] = int(
            previous_predictor_carryover_state_id
        )

    def get_momentum_faceflux_tracked_probe_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []

        def _read_int_rows(field: ti.template(), max_rows: int) -> np.ndarray:
            return np.asarray(field.to_numpy()[:max_rows, :MFP_INT_COUNT], dtype=np.int64)

        def _read_float_rows(field: ti.template(), max_rows: int) -> np.ndarray:
            return np.asarray(field.to_numpy()[:max_rows, :MFP_FLOAT_COUNT], dtype=np.float64)

        def _append_records(
            *,
            scope: str,
            count_value: int,
            int_rows: np.ndarray,
            float_rows: np.ndarray,
            max_rows: int,
        ) -> None:
            count = min(int(count_value), max_rows)
            for row_index in range(count):
                if int_rows[row_index, MFP_INT_VALID] == 0:
                    continue
                record: dict[str, object] = {"row_index": int(row_index), "record_scope": scope}
                for idx, name in enumerate(MFP_INT_FIELD_NAMES):
                    record[name] = int(int_rows[row_index, idx])
                for idx, name in enumerate(MFP_FLOAT_FIELD_NAMES):
                    record[name] = float(float_rows[row_index, idx])
                writer_kind = int(record.get("writer_kind", 0))
                record["writer_kind_name"] = {
                    1: "direct_target_face",
                    2: "mirrored_opposite_target_face",
                    3: "source_entry_actual_face_state",
                    4: "source_entry_mirrored_opposite_face_state",
                    5: "assignment_mirrored_opposite_face_state",
                    6: "post_accumulate_target_cell_state",
                    7: "gate_blocked_target_face",
                }.get(writer_kind, "unknown")
                records.append(record)

        _append_records(
            scope="source_entry_consumed_previous_face_predictor",
            count_value=int(self.momentum_faceflux_consumed_probe_count[None]),
            int_rows=_read_int_rows(self.momentum_faceflux_consumed_probe_int, MOMENTUM_FACEFLUX_PROBE_MAX_ROWS),
            float_rows=_read_float_rows(self.momentum_faceflux_consumed_probe_float, MOMENTUM_FACEFLUX_PROBE_MAX_ROWS),
            max_rows=MOMENTUM_FACEFLUX_PROBE_MAX_ROWS,
        )
        _append_records(
            scope="current_step_face_predictor_after_source_branch",
            count_value=int(self.momentum_faceflux_probe_count[None]),
            int_rows=_read_int_rows(self.momentum_faceflux_probe_int, MOMENTUM_FACEFLUX_PROBE_MAX_ROWS),
            float_rows=_read_float_rows(self.momentum_faceflux_probe_float, MOMENTUM_FACEFLUX_PROBE_MAX_ROWS),
            max_rows=MOMENTUM_FACEFLUX_PROBE_MAX_ROWS,
        )
        _append_records(
            scope="source_entry_preceding_history",
            count_value=int(self.momentum_faceflux_history_count[None]),
            int_rows=_read_int_rows(self.momentum_faceflux_history_int, MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS),
            float_rows=_read_float_rows(self.momentum_faceflux_history_float, MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS),
            max_rows=MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS,
        )
        _append_records(
            scope="assignment_interval_history",
            count_value=int(self.momentum_faceflux_assignment_history_count[None]),
            int_rows=_read_int_rows(self.momentum_faceflux_assignment_history_int, MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS),
            float_rows=_read_float_rows(self.momentum_faceflux_assignment_history_float, MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS),
            max_rows=MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS,
        )
        return records

    @ti.kernel
    def _reset_momentum_faceflux_consumed_probe(self):
        self.momentum_faceflux_consumed_probe_count[None] = 0
        for row, col in self.momentum_faceflux_consumed_probe_int:
            self.momentum_faceflux_consumed_probe_int[row, col] = 0
        for row, col in self.momentum_faceflux_consumed_probe_float:
            self.momentum_faceflux_consumed_probe_float[row, col] = 0.0

    @ti.kernel
    def _reset_first_reject_diagnostics(self, t_start: ti.f64, dt: ti.f64):
        self.first_reject_count[None] = 0
        self.first_reject_reason[None] = FIRST_REJECT_NONE
        self.first_reject_source_i[None] = -1
        self.first_reject_source_j[None] = -1
        self.first_reject_neighbor_i[None] = -1
        self.first_reject_neighbor_j[None] = -1
        self.first_reject_cell_id[None] = -1
        self.first_reject_neighbor_cell_id[None] = -1
        self.first_reject_direction[None] = -1
        self.first_reject_t_start[None] = t_start
        self.first_reject_dt[None] = dt
        self.first_reject_value[None] = 0.0
        self.first_reject_threshold[None] = 0.0

    @ti.func
    def _record_first_reject(
        self,
        reason: ti.i32,
        source_i: ti.i32,
        source_j: ti.i32,
        neighbor_i: ti.i32,
        neighbor_j: ti.i32,
        direction: ti.i32,
        value: ti.f64,
        threshold: ti.f64,
    ):
        old_count = ti.atomic_add(self.first_reject_count[None], 1)
        if old_count == 0:
            self.first_reject_reason[None] = reason
            self.first_reject_source_i[None] = source_i
            self.first_reject_source_j[None] = source_j
            self.first_reject_neighbor_i[None] = neighbor_i
            self.first_reject_neighbor_j[None] = neighbor_j
            self.first_reject_direction[None] = direction
            self.first_reject_value[None] = value
            self.first_reject_threshold[None] = threshold
            self.first_reject_cell_id[None] = -1
            self.first_reject_neighbor_cell_id[None] = -1
            if source_i >= 0 and source_j >= 0:
                self.first_reject_cell_id[None] = self.fields.cell_id[source_i, source_j]
            if neighbor_i >= 0 and neighbor_j >= 0:
                self.first_reject_neighbor_cell_id[None] = self.fields.cell_id[neighbor_i, neighbor_j]

    @ti.kernel
    def _reset_momentum_faceflux_history_probe(self):
        self.momentum_faceflux_history_count[None] = 0
        for row, col in self.momentum_faceflux_history_int:
            self.momentum_faceflux_history_int[row, col] = 0
        for row, col in self.momentum_faceflux_history_float:
            self.momentum_faceflux_history_float[row, col] = 0.0

    @ti.kernel
    def _reset_momentum_faceflux_assignment_history_probe(self):
        self.momentum_faceflux_assignment_history_count[None] = 0
        for row, col in self.momentum_faceflux_assignment_history_int:
            self.momentum_faceflux_assignment_history_int[row, col] = 0
        for row, col in self.momentum_faceflux_assignment_history_float:
            self.momentum_faceflux_assignment_history_float[row, col] = 0.0

    @ti.kernel
    def _capture_momentum_faceflux_source_entry_consumed_probe(self):
        self.momentum_faceflux_consumed_probe_count[None] = 0
        if self.momentum_faceflux_probe_enabled[None] != 0:
            for row in range(MOMENTUM_FACEFLUX_PROBE_MAX_ROWS):
                if self.momentum_faceflux_probe_int[row, MFP_INT_VALID] != 0:
                    out_row = ti.atomic_add(self.momentum_faceflux_consumed_probe_count[None], 1)
                    if out_row < MOMENTUM_FACEFLUX_PROBE_MAX_ROWS:
                        for col in ti.static(range(MFP_INT_COUNT)):
                            self.momentum_faceflux_consumed_probe_int[out_row, col] = self.momentum_faceflux_probe_int[row, col]
                        for col in ti.static(range(MFP_FLOAT_COUNT)):
                            self.momentum_faceflux_consumed_probe_float[out_row, col] = self.momentum_faceflux_probe_float[row, col]

    @ti.kernel
    def _capture_momentum_faceflux_source_entry_state_probe(self):
        self.momentum_faceflux_consumed_probe_count[None] = 0
        target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
        target_direction = self.momentum_faceflux_probe_target_direction[None]
        for i, j in self.fields.h:
            if (
                self.momentum_faceflux_probe_enabled[None] != 0
                and self.fields.is_nodata[i, j] == 0
                and self.fields.cell_id[i, j] == target_cell_id
                and target_direction >= 0
            ):
                ni = self.fields.flow_neighbor_i[i, j, target_direction]
                nj = self.fields.flow_neighbor_j[i, j, target_direction]
                if ni >= 0 and nj >= 0:
                    out_row = ti.atomic_add(self.momentum_faceflux_consumed_probe_count[None], 1)
                    if out_row < MOMENTUM_FACEFLUX_PROBE_MAX_ROWS:
                        opposite_direction = (target_direction + 4) % 8
                        fv_state = self.fields.fv_fortran[i, j, target_direction]
                        hi = self.fields.z_bed[i, j] + self.fields.fhpredi1[i, j]
                        hn = self.fields.z_bed[ni, nj] + self.fields.fhpredi1[ni, nj]
                        hbar = 0.5 * (self.fields.fhpredi1[i, j] + self.fields.fhpredi1[ni, nj])

                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_VALID] = 1
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_WRITER_KIND] = 3
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_I] = i
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_J] = j
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_NEIGHBOR_I] = ni
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_NEIGHBOR_J] = nj
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_I] = i
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_J] = j
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[i, j]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[ni, nj]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[i, j]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_DIRECTION] = target_direction
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_DIRECTION] = target_direction
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_OPPOSITE_DIRECTION] = opposite_direction
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_GATE_BLOCKS_FACE] = 0
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_CLAMP_STATUS] = 0
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SIGN_FLIP_STATUS] = 0
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_ENTRY_MARKER_ID] = 1
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_ASSIGNMENT_LOOP_MARKER_ID] = 0
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]

                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_HI] = hi
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_HN] = hn
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_HBAR] = hbar
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_YBAR] = hbar
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FHPREDI1_SOURCE] = self.fields.fhpredi1[i, j]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = self.fields.fhpredi1[ni, nj]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FRHOPREDI1_SOURCE] = self.fields.frhopredi1[i, j]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FRHOPREDI1_NEIGHBOR] = self.fields.frhopredi1[ni, nj]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_CV_SOURCE] = self.fields.Cv[i, j]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_CV_NEIGHBOR] = self.fields.Cv[ni, nj]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FV_BEFORE] = fv_state
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FVPREDI_BEFORE_CLAMP] = fv_state
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = fv_state
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_OPERAND_FV_NEIGHBOR_SAME_DIRECTION] = self.fields.fv_fortran[ni, nj, target_direction]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_OPERAND_FV_SOURCE_OPPOSITE_DIRECTION] = self.fields.fv_fortran[i, j, opposite_direction]

                        history_total_row = ti.atomic_add(self.momentum_faceflux_history_count[None], 1)
                        history_row = history_total_row % MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS
                        for col in ti.static(range(MFP_INT_COUNT)):
                            self.momentum_faceflux_history_int[history_row, col] = self.momentum_faceflux_consumed_probe_int[out_row, col]
                        for col in ti.static(range(MFP_FLOAT_COUNT)):
                            self.momentum_faceflux_history_float[history_row, col] = self.momentum_faceflux_consumed_probe_float[out_row, col]

                        mirror_row = ti.atomic_add(self.momentum_faceflux_consumed_probe_count[None], 1)
                        if mirror_row < MOMENTUM_FACEFLUX_PROBE_MAX_ROWS:
                            mirror_state = self.fields.fv_fortran[ni, nj, opposite_direction]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_VALID] = 1
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_WRITER_KIND] = 4
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_SOURCE_I] = i
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_SOURCE_J] = j
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_NEIGHBOR_I] = ni
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_NEIGHBOR_J] = nj
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_TARGET_I] = ni
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_TARGET_J] = nj
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[i, j]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[ni, nj]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[ni, nj]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_DIRECTION] = opposite_direction
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_TARGET_DIRECTION] = target_direction
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_OPPOSITE_DIRECTION] = target_direction
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_GATE_BLOCKS_FACE] = 0
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_CLAMP_STATUS] = 0
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_SIGN_FLIP_STATUS] = 0
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_SOURCE_ENTRY_MARKER_ID] = 1
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_ASSIGNMENT_LOOP_MARKER_ID] = 0
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
                            self.momentum_faceflux_consumed_probe_int[mirror_row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]
                            for col in ti.static(range(MFP_FLOAT_COUNT)):
                                self.momentum_faceflux_consumed_probe_float[mirror_row, col] = self.momentum_faceflux_consumed_probe_float[out_row, col]
                            self.momentum_faceflux_consumed_probe_float[mirror_row, MFP_FLOAT_FV_BEFORE] = mirror_state
                            self.momentum_faceflux_consumed_probe_float[mirror_row, MFP_FLOAT_FVPREDI_BEFORE_CLAMP] = mirror_state
                            self.momentum_faceflux_consumed_probe_float[mirror_row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = mirror_state

                            mirror_history_total_row = ti.atomic_add(self.momentum_faceflux_history_count[None], 1)
                            mirror_history_row = mirror_history_total_row % MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS
                            for col in ti.static(range(MFP_INT_COUNT)):
                                self.momentum_faceflux_history_int[mirror_history_row, col] = self.momentum_faceflux_consumed_probe_int[mirror_row, col]
                            for col in ti.static(range(MFP_FLOAT_COUNT)):
                                self.momentum_faceflux_history_float[mirror_history_row, col] = self.momentum_faceflux_consumed_probe_float[mirror_row, col]

    @ti.kernel
    def _capture_momentum_faceflux_source_entry_state_probe_lightweight(self):
        self.momentum_faceflux_consumed_probe_count[None] = 0
        target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
        target_direction = self.momentum_faceflux_probe_target_direction[None]
        for i, j in self.fields.h:
            if (
                self.momentum_faceflux_probe_enabled[None] != 0
                and self.fields.is_nodata[i, j] == 0
                and self.fields.cell_id[i, j] == target_cell_id
                and target_direction >= 0
            ):
                ni = self.fields.flow_neighbor_i[i, j, target_direction]
                nj = self.fields.flow_neighbor_j[i, j, target_direction]
                if ni >= 0 and nj >= 0:
                    out_row = ti.atomic_add(self.momentum_faceflux_consumed_probe_count[None], 1)
                    if out_row < MOMENTUM_FACEFLUX_PROBE_MAX_ROWS:
                        opposite_direction = (target_direction + 4) % 8
                        fv_state = self.fields.fv_fortran[i, j, target_direction]
                        hi = self.fields.z_bed[i, j] + self.fields.fhpredi1[i, j]
                        hn = self.fields.z_bed[ni, nj] + self.fields.fhpredi1[ni, nj]
                        hbar = 0.5 * (self.fields.fhpredi1[i, j] + self.fields.fhpredi1[ni, nj])

                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_VALID] = 1
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_WRITER_KIND] = 3
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_I] = i
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_J] = j
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_NEIGHBOR_I] = ni
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_NEIGHBOR_J] = nj
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_I] = i
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_J] = j
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[i, j]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[ni, nj]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[i, j]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_DIRECTION] = target_direction
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_TARGET_DIRECTION] = target_direction
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_OPPOSITE_DIRECTION] = opposite_direction
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_SOURCE_ENTRY_MARKER_ID] = 1
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
                        self.momentum_faceflux_consumed_probe_int[out_row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]

                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_HI] = hi
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_HN] = hn
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_HBAR] = hbar
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_YBAR] = hbar
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FHPREDI1_SOURCE] = self.fields.fhpredi1[i, j]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = self.fields.fhpredi1[ni, nj]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FRHOPREDI1_SOURCE] = self.fields.frhopredi1[i, j]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FRHOPREDI1_NEIGHBOR] = self.fields.frhopredi1[ni, nj]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FV_BEFORE] = fv_state
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FVPREDI_BEFORE_CLAMP] = fv_state
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = fv_state
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_OPERAND_FV_NEIGHBOR_SAME_DIRECTION] = self.fields.fv_fortran[ni, nj, target_direction]
                        self.momentum_faceflux_consumed_probe_float[out_row, MFP_FLOAT_OPERAND_FV_SOURCE_OPPOSITE_DIRECTION] = self.fields.fv_fortran[i, j, opposite_direction]

                        history_total_row = ti.atomic_add(self.momentum_faceflux_history_count[None], 1)
                        history_row = history_total_row % MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS
                        self.momentum_faceflux_history_int[history_row, MFP_INT_VALID] = 1
                        self.momentum_faceflux_history_int[history_row, MFP_INT_WRITER_KIND] = 3
                        self.momentum_faceflux_history_int[history_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[i, j]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[ni, nj]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[i, j]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_DIRECTION] = target_direction
                        self.momentum_faceflux_history_int[history_row, MFP_INT_TARGET_DIRECTION] = target_direction
                        self.momentum_faceflux_history_int[history_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
                        self.momentum_faceflux_history_int[history_row, MFP_INT_SOURCE_ENTRY_MARKER_ID] = 1
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_HI] = hi
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_HN] = hn
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_FHPREDI1_SOURCE] = self.fields.fhpredi1[i, j]
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = self.fields.fhpredi1[ni, nj]
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_FV_BEFORE] = fv_state
                        self.momentum_faceflux_history_float[history_row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = fv_state

    @ti.kernel
    def _capture_momentum_faceflux_post_edge_lightweight(self, dt: ti.f64, limitfr: ti.f64):
        target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
        target_direction = self.momentum_faceflux_probe_target_direction[None]
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] == 0:
                for d in ti.static(range(8)):
                    ni = self.fields.flow_neighbor_i[i, j, d]
                    nj = self.fields.flow_neighbor_j[i, j, d]
                    if ni >= 0 and nj >= 0 and self.fields.cell_id[ni, nj] > self.fields.cell_id[i, j]:
                        opp = ti.static(FORTRAN_OPPOSITE_DIR[d])
                        if (
                            self.fields.cell_id[i, j] == target_cell_id
                            and (target_direction < 0 or d == target_direction)
                        ) or (
                            self.fields.cell_id[ni, nj] == target_cell_id
                            and (target_direction < 0 or opp == target_direction)
                        ):
                            hi = self.fields.fhpredi[i, j] + self.fields.tempele[i, j]
                            hn = self.fields.fhpredi[ni, nj] + self.fields.tempele[ni, nj]
                            hbar = 0.5 * (self.fields.fhpredi[i, j] + self.fields.fhpredi[ni, nj])
                            ybar = self.fields.fybar_fortran[i, j, d]
                            if ybar == 0.0:
                                ybar = hbar
                            fvlimit = 0.0
                            if ybar > 0.0:
                                fvlimit = limitfr * ti.sqrt(self.g * ybar)

                            if (
                                self.fields.cell_id[i, j] == target_cell_id
                                and (target_direction < 0 or d == target_direction)
                            ):
                                fv_before = self.fields.fv_fortran[i, j, d]
                                fv_after = self.fields.fv_pred_fortran[i, j, d]
                                clamp_status = 0
                                if fvlimit > 0.0 and ti.abs(fv_after) >= fvlimit * (1.0 - 1.0e-10):
                                    clamp_status = 1
                                self._record_momentum_faceflux_probe_lightweight(
                                    1,
                                    i,
                                    j,
                                    ni,
                                    nj,
                                    i,
                                    j,
                                    d,
                                    opp,
                                    0,
                                    clamp_status,
                                    0,
                                    hi,
                                    hn,
                                    hbar,
                                    ybar,
                                    self.fields.fhpredi[i, j],
                                    self.fields.fhpredi[ni, nj],
                                    self.fields.frhopredi[i, j],
                                    self.fields.frhopredi[ni, nj],
                                    fv_after - fv_before,
                                    fv_before,
                                    fv_after,
                                    fv_after,
                                    fvlimit,
                                    self.fields.qqt_fortran[i, j, d],
                                    self.fields.qq_fortran[i, j, d],
                                    self.fields.qqmass_fortran[i, j, d],
                                    0.0,
                                    ybar,
                                    _direction_width(self.fields.dx, d),
                                    0.0,
                                )

                            if (
                                self.fields.cell_id[ni, nj] == target_cell_id
                                and (target_direction < 0 or opp == target_direction)
                            ):
                                fv_before = self.fields.fv_fortran[ni, nj, opp]
                                fv_after = self.fields.fv_pred_fortran[ni, nj, opp]
                                clamp_status = 0
                                if fvlimit > 0.0 and ti.abs(fv_after) >= fvlimit * (1.0 - 1.0e-10):
                                    clamp_status = 1
                                self._record_momentum_faceflux_probe_lightweight(
                                    2,
                                    i,
                                    j,
                                    ni,
                                    nj,
                                    ni,
                                    nj,
                                    d,
                                    opp,
                                    0,
                                    clamp_status,
                                    0,
                                    hi,
                                    hn,
                                    hbar,
                                    ybar,
                                    self.fields.fhpredi[i, j],
                                    self.fields.fhpredi[ni, nj],
                                    self.fields.frhopredi[i, j],
                                    self.fields.frhopredi[ni, nj],
                                    fv_after - fv_before,
                                    fv_before,
                                    fv_after,
                                    fv_after,
                                    fvlimit,
                                    self.fields.qqt_fortran[ni, nj, opp],
                                    self.fields.qq_fortran[ni, nj, opp],
                                    self.fields.qqmass_fortran[ni, nj, opp],
                                    0.0,
                                    ybar,
                                    _direction_width(self.fields.dx, d),
                                    0.0,
                                )

    @ti.kernel
    def _reset_momentum_faceflux_tracked_probe(self):
        self.momentum_faceflux_probe_count[None] = 0
        for row, col in self.momentum_faceflux_probe_int:
            self.momentum_faceflux_probe_int[row, col] = 0
        for row, col in self.momentum_faceflux_probe_float:
            self.momentum_faceflux_probe_float[row, col] = 0.0

    @ti.kernel
    def _mark_momentum_faceflux_probe_rejected_status(self, rejected_status: ti.i32):
        candidate_step_id = self.momentum_faceflux_probe_candidate_step_id[None]
        for row in range(MOMENTUM_FACEFLUX_PROBE_MAX_ROWS):
            if self.momentum_faceflux_probe_int[row, MFP_INT_VALID] != 0:
                self.momentum_faceflux_probe_int[row, MFP_INT_REJECTED_STEP_STATUS] = rejected_status
            if self.momentum_faceflux_consumed_probe_int[row, MFP_INT_VALID] != 0:
                self.momentum_faceflux_consumed_probe_int[row, MFP_INT_REJECTED_STEP_STATUS] = rejected_status
        for row in range(MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS):
            if (
                self.momentum_faceflux_history_int[row, MFP_INT_VALID] != 0
                and self.momentum_faceflux_history_int[row, MFP_INT_CANDIDATE_STEP_ID] == candidate_step_id
            ):
                self.momentum_faceflux_history_int[row, MFP_INT_REJECTED_STEP_STATUS] = rejected_status
            if (
                self.momentum_faceflux_assignment_history_int[row, MFP_INT_VALID] != 0
                and self.momentum_faceflux_assignment_history_int[row, MFP_INT_CANDIDATE_STEP_ID] == candidate_step_id
            ):
                self.momentum_faceflux_assignment_history_int[row, MFP_INT_REJECTED_STEP_STATUS] = rejected_status

    @ti.func
    def _record_momentum_faceflux_probe(
        self,
        writer_kind: ti.i32,
        source_i: ti.i32,
        source_j: ti.i32,
        neighbor_i: ti.i32,
        neighbor_j: ti.i32,
        target_i: ti.i32,
        target_j: ti.i32,
        direction: ti.i32,
        opposite_direction: ti.i32,
        gate_blocks_face: ti.i32,
        clamp_status: ti.i32,
        sign_flip_status: ti.i32,
        hi: ti.f64,
        hn: ti.f64,
        hbar: ti.f64,
        ybar: ti.f64,
        fhpredi1_source: ti.f64,
        fhpredi1_neighbor: ti.f64,
        frhopredi1_source: ti.f64,
        frhopredi1_neighbor: ti.f64,
        cv_source: ti.f64,
        cv_neighbor: ti.f64,
        cvbar: ti.f64,
        frhobar: ti.f64,
        gammadeb: ti.f64,
        manningbar: ti.f64,
        miubar: ti.f64,
        grad: ti.f64,
        sfy: ti.f64,
        sfmiu: ti.f64,
        sfmanning: ti.f64,
        sf: ti.f64,
        localvdiff: ti.f64,
        artivis: ti.f64,
        vdiff_term: ti.f64,
        dv: ti.f64,
        fv_before: ti.f64,
        fvpredi_before_clamp: ti.f64,
        fvpredi_after_clamp: ti.f64,
        fvlimit: ti.f64,
        qqt: ti.f64,
        qq: ti.f64,
        qqmass: ti.f64,
        frhoflux: ti.f64,
        yflux: ti.f64,
        width: ti.f64,
        dt0: ti.f64,
        source_depth_rate: ti.f64,
        erorate: ti.f64,
        deporate: ti.f64,
    ):
        row = ti.atomic_add(self.momentum_faceflux_probe_count[None], 1)
        if row < MOMENTUM_FACEFLUX_PROBE_MAX_ROWS:
            self.momentum_faceflux_probe_int[row, MFP_INT_VALID] = 1
            self.momentum_faceflux_probe_int[row, MFP_INT_WRITER_KIND] = writer_kind
            self.momentum_faceflux_probe_int[row, MFP_INT_SOURCE_I] = source_i
            self.momentum_faceflux_probe_int[row, MFP_INT_SOURCE_J] = source_j
            self.momentum_faceflux_probe_int[row, MFP_INT_NEIGHBOR_I] = neighbor_i
            self.momentum_faceflux_probe_int[row, MFP_INT_NEIGHBOR_J] = neighbor_j
            self.momentum_faceflux_probe_int[row, MFP_INT_TARGET_I] = target_i
            self.momentum_faceflux_probe_int[row, MFP_INT_TARGET_J] = target_j
            self.momentum_faceflux_probe_int[row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[source_i, source_j]
            self.momentum_faceflux_probe_int[row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[neighbor_i, neighbor_j]
            self.momentum_faceflux_probe_int[row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[target_i, target_j]
            self.momentum_faceflux_probe_int[row, MFP_INT_DIRECTION] = direction
            self.momentum_faceflux_probe_int[row, MFP_INT_TARGET_DIRECTION] = self.momentum_faceflux_probe_target_direction[None]
            self.momentum_faceflux_probe_int[row, MFP_INT_OPPOSITE_DIRECTION] = opposite_direction
            self.momentum_faceflux_probe_int[row, MFP_INT_GATE_BLOCKS_FACE] = gate_blocks_face
            self.momentum_faceflux_probe_int[row, MFP_INT_CLAMP_STATUS] = clamp_status
            self.momentum_faceflux_probe_int[row, MFP_INT_SIGN_FLIP_STATUS] = sign_flip_status
            self.momentum_faceflux_probe_int[row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
            self.momentum_faceflux_probe_int[row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
            self.momentum_faceflux_probe_int[row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
            self.momentum_faceflux_probe_int[row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
            self.momentum_faceflux_probe_int[row, MFP_INT_SOURCE_ENTRY_MARKER_ID] = 0
            self.momentum_faceflux_probe_int[row, MFP_INT_ASSIGNMENT_LOOP_MARKER_ID] = 1
            self.momentum_faceflux_probe_int[row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
            self.momentum_faceflux_probe_int[row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]

            self.momentum_faceflux_probe_float[row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_HI] = hi
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_HN] = hn
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_HBAR] = hbar
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_YBAR] = ybar
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FHPREDI1_SOURCE] = fhpredi1_source
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = fhpredi1_neighbor
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FRHOPREDI1_SOURCE] = frhopredi1_source
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FRHOPREDI1_NEIGHBOR] = frhopredi1_neighbor
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_CV_SOURCE] = cv_source
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_CV_NEIGHBOR] = cv_neighbor
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_CVBAR] = cvbar
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FRHOBAR] = frhobar
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_GAMMADEB] = gammadeb
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_MANNINGBAR] = manningbar
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_MIUBAR] = miubar
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_GRAD] = grad
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_SFY] = sfy
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_SFMIU] = sfmiu
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_SFMANNING] = sfmanning
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_SF] = sf
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_LOCALVDIFF] = localvdiff
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_ARTIVIS] = artivis
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_VDIFF_TERM] = vdiff_term
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_DV] = dv
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FV_BEFORE] = fv_before
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FVPREDI_BEFORE_CLAMP] = fvpredi_before_clamp
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = fvpredi_after_clamp
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FVLIMIT] = fvlimit
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_QQT] = qqt
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_QQ] = qq
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_QQMASS] = qqmass
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_FRHOFLUX] = frhoflux
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_YFLUX] = yflux
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_WIDTH] = width
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_DT0] = dt0
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_SOURCE_DEPTH_RATE] = source_depth_rate
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_ERORATE] = erorate
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_DEPORATE] = deporate
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_OPERAND_FV_NEIGHBOR_SAME_DIRECTION] = self.fields.fv_fortran[neighbor_i, neighbor_j, direction]
            self.momentum_faceflux_probe_float[row, MFP_FLOAT_OPERAND_FV_SOURCE_OPPOSITE_DIRECTION] = self.fields.fv_fortran[source_i, source_j, opposite_direction]

            history_total_row = ti.atomic_add(self.momentum_faceflux_assignment_history_count[None], 1)
            history_row = history_total_row % MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_VALID] = 1
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_WRITER_KIND] = writer_kind
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_I] = source_i
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_J] = source_j
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_NEIGHBOR_I] = neighbor_i
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_NEIGHBOR_J] = neighbor_j
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_I] = target_i
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_J] = target_j
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[source_i, source_j]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[neighbor_i, neighbor_j]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[target_i, target_j]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_DIRECTION] = direction
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_DIRECTION] = self.momentum_faceflux_probe_target_direction[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_OPPOSITE_DIRECTION] = opposite_direction
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_GATE_BLOCKS_FACE] = gate_blocks_face
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_CLAMP_STATUS] = clamp_status
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SIGN_FLIP_STATUS] = sign_flip_status
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ASSIGNMENT_LOOP_MARKER_ID] = 1
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_HI] = hi
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_HN] = hn
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_HBAR] = hbar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_YBAR] = ybar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI1_SOURCE] = fhpredi1_source
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = fhpredi1_neighbor
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOPREDI1_SOURCE] = frhopredi1_source
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOPREDI1_NEIGHBOR] = frhopredi1_neighbor
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_CV_SOURCE] = cv_source
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_CV_NEIGHBOR] = cv_neighbor
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_CVBAR] = cvbar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOBAR] = frhobar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_GAMMADEB] = gammadeb
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_MANNINGBAR] = manningbar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_MIUBAR] = miubar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_GRAD] = grad
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SFY] = sfy
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SFMIU] = sfmiu
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SFMANNING] = sfmanning
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SF] = sf
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_LOCALVDIFF] = localvdiff
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_ARTIVIS] = artivis
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_VDIFF_TERM] = vdiff_term
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DV] = dv
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FV_BEFORE] = fv_before
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FVPREDI_BEFORE_CLAMP] = fvpredi_before_clamp
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = fvpredi_after_clamp
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FVLIMIT] = fvlimit
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QQT] = qqt
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QQ] = qq
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QQMASS] = qqmass
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOFLUX] = frhoflux
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_YFLUX] = yflux
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_WIDTH] = width
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DT0] = dt0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_OPERAND_FV_NEIGHBOR_SAME_DIRECTION] = self.fields.fv_fortran[neighbor_i, neighbor_j, direction]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_OPERAND_FV_SOURCE_OPPOSITE_DIRECTION] = self.fields.fv_fortran[source_i, source_j, opposite_direction]

    @ti.func
    def _record_momentum_faceflux_probe_lightweight(
        self,
        writer_kind: ti.i32,
        source_i: ti.i32,
        source_j: ti.i32,
        neighbor_i: ti.i32,
        neighbor_j: ti.i32,
        target_i: ti.i32,
        target_j: ti.i32,
        direction: ti.i32,
        opposite_direction: ti.i32,
        gate_blocks_face: ti.i32,
        clamp_status: ti.i32,
        sign_flip_status: ti.i32,
        hi: ti.f64,
        hn: ti.f64,
        hbar: ti.f64,
        ybar: ti.f64,
        fhpredi1_source: ti.f64,
        fhpredi1_neighbor: ti.f64,
        frhopredi1_source: ti.f64,
        frhopredi1_neighbor: ti.f64,
        dv: ti.f64,
        fv_before: ti.f64,
        fvpredi_before_clamp: ti.f64,
        fvpredi_after_clamp: ti.f64,
        fvlimit: ti.f64,
        qqt: ti.f64,
        qq: ti.f64,
        qqmass: ti.f64,
        frhoflux: ti.f64,
        yflux: ti.f64,
        width: ti.f64,
        dt0: ti.f64,
    ):
        history_total_row = ti.atomic_add(self.momentum_faceflux_assignment_history_count[None], 1)
        if history_total_row >= 0:
            history_row = history_total_row % MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_VALID] = 1
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_WRITER_KIND] = writer_kind
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_I] = source_i
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_J] = source_j
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_NEIGHBOR_I] = neighbor_i
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_NEIGHBOR_J] = neighbor_j
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_I] = target_i
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_J] = target_j
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[source_i, source_j]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_NEIGHBOR_CELL_ID] = self.fields.cell_id[neighbor_i, neighbor_j]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[target_i, target_j]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_DIRECTION] = direction
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_DIRECTION] = self.momentum_faceflux_probe_target_direction[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_OPPOSITE_DIRECTION] = opposite_direction
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_GATE_BLOCKS_FACE] = gate_blocks_face
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_CLAMP_STATUS] = clamp_status
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SIGN_FLIP_STATUS] = sign_flip_status
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_ENTRY_MARKER_ID] = 0
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ASSIGNMENT_LOOP_MARKER_ID] = 1
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
            self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]

            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_HI] = hi
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_HN] = hn
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_HBAR] = hbar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_YBAR] = ybar
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI1_SOURCE] = fhpredi1_source
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = fhpredi1_neighbor
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOPREDI1_SOURCE] = frhopredi1_source
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOPREDI1_NEIGHBOR] = frhopredi1_neighbor
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_CV_SOURCE] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_CV_NEIGHBOR] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_CVBAR] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOBAR] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_GAMMADEB] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_MANNINGBAR] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_MIUBAR] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_GRAD] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SFY] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SFMIU] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SFMANNING] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SF] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_LOCALVDIFF] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_ARTIVIS] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_VDIFF_TERM] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DV] = dv
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FV_BEFORE] = fv_before
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FVPREDI_BEFORE_CLAMP] = fvpredi_before_clamp
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FVPREDI_AFTER_CLAMP] = fvpredi_after_clamp
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FVLIMIT] = fvlimit
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QQT] = qqt
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QQ] = qq
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QQMASS] = qqmass
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOFLUX] = frhoflux
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_YFLUX] = yflux
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_WIDTH] = width
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DT0] = dt0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_SOURCE_DEPTH_RATE] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_ERORATE] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DEPORATE] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_OPERAND_FV_NEIGHBOR_SAME_DIRECTION] = self.fields.fv_fortran[neighbor_i, neighbor_j, direction]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_OPERAND_FV_SOURCE_OPPOSITE_DIRECTION] = self.fields.fv_fortran[source_i, source_j, opposite_direction]
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QTNET] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QNET] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QMASSNET] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI2_TARGET] = 0.0
            self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOPREDI2_TARGET] = 0.0

    @ti.kernel
    def _capture_momentum_faceflux_post_accumulate_probe(self):
        target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
        target_direction = self.momentum_faceflux_probe_target_direction[None]
        for i, j in self.fields.h:
            if (
                self.momentum_faceflux_probe_enabled[None] != 0
                and self.fields.is_nodata[i, j] == 0
                and self.fields.cell_id[i, j] == target_cell_id
            ):
                row = ti.atomic_add(self.momentum_faceflux_assignment_history_count[None], 1)
                history_row = row % MOMENTUM_FACEFLUX_HISTORY_MAX_ROWS
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_VALID] = 1
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_WRITER_KIND] = 6
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_I] = i
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_J] = j
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_I] = i
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_J] = j
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_SOURCE_CELL_ID] = self.fields.cell_id[i, j]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_CELL_ID] = self.fields.cell_id[i, j]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_DIRECTION] = target_direction
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_TARGET_DIRECTION] = target_direction
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ACCEPTED_STEP_ID] = self.momentum_faceflux_probe_accepted_step_id[None]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_CANDIDATE_STEP_ID] = self.momentum_faceflux_probe_candidate_step_id[None]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_RETRY_ATTEMPT_ID] = self.momentum_faceflux_probe_retry_attempt_id[None]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_REJECTED_STEP_STATUS] = self.momentum_faceflux_probe_rejected_step_status[None]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ASSIGNMENT_LOOP_MARKER_ID] = 2
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_ACCEPTED_PREDICTOR_STATE_ID] = self.momentum_faceflux_probe_accepted_predictor_state_id[None]
                self.momentum_faceflux_assignment_history_int[history_row, MFP_INT_PREVIOUS_PREDICTOR_CARRYOVER_STATE_ID] = self.momentum_faceflux_probe_previous_predictor_carryover_state_id[None]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_T_START] = self.momentum_faceflux_probe_t_start[None]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_DT] = self.momentum_faceflux_probe_dt[None]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI1_SOURCE] = self.fields.fhpredi1[i, j]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI1_NEIGHBOR] = self.fields.fhpredi[i, j]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QTNET] = self.fields.qtnet_fortran[i, j]
                qnet = 0.0
                for d in ti.static(range(8)):
                    qnet -= self.fields.qq_fortran[i, j, d]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QNET] = qnet
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_QMASSNET] = self.fields.qmassnet_fortran[i, j]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FHPREDI2_TARGET] = self.fields.fhpredi2[i, j]
                self.momentum_faceflux_assignment_history_float[history_row, MFP_FLOAT_FRHOPREDI2_TARGET] = self.fields.frhopredi2[i, j]

    @staticmethod
    def _step_diag_stats(values: np.ndarray, mask: np.ndarray) -> dict[str, float]:
        arr = np.asarray(values, dtype=np.float64)
        valid = mask & np.isfinite(arr)
        if not np.any(valid):
            return {"sum": 0.0, "max": 0.0, "min": 0.0}
        selected = arr[valid]
        return {
            "sum": float(np.sum(selected)),
            "max": float(np.max(selected)),
            "min": float(np.min(selected)),
        }

    def _make_erosion_step_diagnostic_record(self, *, t_start: float, dt_used: float) -> dict[str, object]:
        """Collect pre-commit source-rate/writeback diagnostics for one accepted step."""
        state = self.fields.get_full_state()
        active_mask = ~np.asarray(state["is_nodata"], dtype=bool)

        tau = np.asarray(state["tau_temp"], dtype=np.float64)
        taoc_active = np.asarray(state["taoc_temp"], dtype=np.float64)
        taoc_old = np.asarray(state["taoc_old_temp"], dtype=np.float64)
        erorate_raw = np.asarray(state["erorate_raw_temp"], dtype=np.float64)
        erorate_rholimit = np.asarray(state["erorate_rholimit_clamped_temp"], dtype=np.float64)
        erorate_clamped = np.asarray(state["erorate_clamped_temp"], dtype=np.float64)
        deporate_raw = np.asarray(state["deporate_raw_temp"], dtype=np.float64)
        deporate_clamped = np.asarray(state["deporate_clamped_temp"], dtype=np.float64)
        fhpredi1 = np.asarray(state["fhpredi1"], dtype=np.float64)
        frhopredi1 = np.asarray(state["frhopredi1"], dtype=np.float64)
        h_current = np.asarray(state["h"], dtype=np.float64)
        cv_accepted = np.asarray(state["Cv"], dtype=np.float64)
        cvlimit = np.asarray(state["cvlimit_temp"], dtype=np.float64)
        ctao = np.asarray(state["ctao_field"], dtype=np.float64)
        phi_deg = np.asarray(self.fields.phi_field.to_numpy(), dtype=np.float64)
        alpha1 = np.asarray(self.fields.alpha1_field.to_numpy(), dtype=np.float64)
        beta1 = np.asarray(self.fields.beta1_field.to_numpy(), dtype=np.float64)
        alpha2 = np.asarray(self.fields.alpha2_field.to_numpy(), dtype=np.float64)
        beta2 = np.asarray(self.fields.beta2_field.to_numpy(), dtype=np.float64)
        manning = np.asarray(self.fields.n_manning_field.to_numpy(), dtype=np.float64)
        kero = np.asarray(self.fields.kero_field.to_numpy(), dtype=np.float64)
        absubar = np.asarray(state["absubar_temp"], dtype=np.float64)
        fv_accepted = np.asarray(state["fv_fortran"], dtype=np.float64)
        fv_candidate = np.asarray(self.fields.fv_pred_fortran.to_numpy(), dtype=np.float64)
        tanslo_dynamic = np.asarray(state["tanslo_fortran"], dtype=np.float64)
        slope = np.arctan(tanslo_dynamic)
        tempfsh = np.asarray(state["tempfsh_flow"], dtype=np.float64)
        tempfsrho = np.asarray(state["tempfsrho_flow"], dtype=np.float64)
        erosion_depth = np.asarray(state["erosion_depth"], dtype=np.float64)
        deposition_depth = np.asarray(state["deposition_depth"], dtype=np.float64)
        flow_depth = np.asarray(state["h"], dtype=np.float64)
        cell_id = np.asarray(state["cell_id"], dtype=np.int32)
        zone_id_current = np.asarray(state.get("zone_id", np.zeros_like(cell_id)), dtype=np.int32)
        z_original = np.asarray(state["z_original"], dtype=np.float64)
        tempele = np.asarray(state["tempele"], dtype=np.float64)
        rholimit_clamp = np.asarray(state["rholimit_clamp_temp"], dtype=np.int32)
        erodible_clamp = np.asarray(state["erodible_clamp_temp"], dtype=np.int32)
        if self.precomputed_failure_gindx is not None:
            gindx_output_mask = np.asarray(self.precomputed_failure_gindx, dtype=np.int32) > 0
        else:
            gindx_output_mask = np.zeros_like(active_mask, dtype=bool)

        cv_local = np.zeros_like(fhpredi1, dtype=np.float64)
        denom = self.rhos - self.rhow
        if denom != 0.0:
            cv_local = np.where(fhpredi1 > EPS, (frhopredi1 - self.rhow) / denom, 0.0)
        cv_local = np.where(cv_local > 0.0, cv_local, 0.0)
        tan_phi = np.tan(np.deg2rad(phi_deg))
        cos_slope_sq = np.cos(slope) ** 2
        normfriccoe = cos_slope_sq * tan_phi
        taoc_local_cv = ctao + (1.0 - self.cs) * cv_local * denom * self.g * h_current * cos_slope_sq * tan_phi
        taoc_local_cv_fhpredi1 = ctao + (1.0 - self.cs) * cv_local * denom * self.g * fhpredi1 * cos_slope_sq * tan_phi

        wet_weight = np.where(active_mask & (fhpredi1 > 0.0), fhpredi1, 0.0)
        wet_weight_sum = float(np.sum(wet_weight))
        cvbar_depth_weighted = float(np.sum(cv_local * wet_weight) / wet_weight_sum) if wet_weight_sum > 0.0 else 0.0

        safe_fh = np.where(np.abs(fhpredi1) > EPS, fhpredi1, np.nan)
        safe_frho = np.where(np.abs(frhopredi1) > EPS, frhopredi1, np.nan)
        gammadeb = frhopredi1 * self.g

        def _absubar_components_from_fv(fv_array: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            """Match dfs.F90 absubar from 8-direction velocities (0-based directions)."""
            vorth_x = 0.5 * (np.abs(fv_array[:, :, 0]) + np.abs(fv_array[:, :, 4]))
            vorth_y = 0.5 * (np.abs(fv_array[:, :, 2]) + np.abs(fv_array[:, :, 6]))
            vorth = np.sqrt(vorth_x * vorth_x + vorth_y * vorth_y)
            vcomp_x = 0.5 * (np.abs(fv_array[:, :, 3]) + np.abs(fv_array[:, :, 7]))
            vcomp_y = 0.5 * (np.abs(fv_array[:, :, 1]) + np.abs(fv_array[:, :, 5]))
            vcomp = np.sqrt(vcomp_x * vcomp_x + vcomp_y * vcomp_y)
            return np.maximum(vorth, vcomp), vorth, vcomp

        def _absubar_from_fv(fv_array: np.ndarray) -> np.ndarray:
            return _absubar_components_from_fv(fv_array)[0]

        fvpredi2_candidate = 0.5 * (fv_accepted + fv_candidate)
        absubar_accepted_only, vorth_accepted_only, vcomp_accepted_only = _absubar_components_from_fv(fv_accepted)
        absubar_candidate_only, vorth_candidate_only, vcomp_candidate_only = _absubar_components_from_fv(fv_candidate)
        absubar_fortran_fvpredi2, vorth_fortran_fvpredi2, vcomp_fortran_fvpredi2 = _absubar_components_from_fv(
            fvpredi2_candidate
        )
        # In the paired NO.5 dfs.F90, `fvpredi=0.` is reset before the
        # erosion/deposition branch, so `fvpredi2=0.5*(fv+fvpredi)` evaluates
        # from half of the accepted directional velocity before flux prediction.
        absubar_fortran_preflux, vorth_fortran_preflux, vcomp_fortran_preflux = _absubar_components_from_fv(
            0.5 * fv_accepted
        )

        def _sfy_from_cvbar(cvbar_source: np.ndarray | float) -> np.ndarray:
            cvbar_array = np.asarray(cvbar_source, dtype=np.float64)
            if cvbar_array.shape == ():
                cvbar_array = np.full_like(cv_local, float(cvbar_array), dtype=np.float64)
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                steep = (1.0 - self.cs) * cvbar_array * denom / safe_frho * normfriccoe
                fan = alpha1 * np.exp(beta1 * cvbar_array) / safe_frho / self.g / safe_fh
            sfy = np.where(cvbar_array <= CVTOL, 0.0, np.where(slope > DFS_SLOPE_BRANCH, steep, fan))
            return np.where(np.isfinite(sfy), sfy, 0.0)

        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            miudebris = np.where(
                cv_local <= 0.1,
                DFS_MIU_BASE + cv_local / 0.1 * (alpha2 * np.exp(beta2 * 0.1) - DFS_MIU_BASE),
                alpha2 * np.exp(beta2 * cv_local),
            )
            miudebris_fortran_exact = np.where(
                cv_local <= 0.1,
                DFS_MIU_BASE + cv_local / 0.1 * (alpha2 * np.exp(beta2 * 0.1) - DFS_MIU_BASE),
                alpha2 * np.exp(beta2 * cv_local),
            )
            coemiu_current = self.kresis * miudebris / 8.0 / gammadeb / (safe_fh * safe_fh)
            coemiu_fortran_exact = self.kresis * miudebris_fortran_exact / 8.0 / gammadeb / (safe_fh * safe_fh)
            sfmiu_current = coemiu_current * absubar
            sfmiu_absubar_fortran_fvpredi2 = coemiu_fortran_exact * absubar_fortran_fvpredi2
            sfmiu_absubar_fortran_preflux = coemiu_fortran_exact * absubar_fortran_preflux
            sfmiu_absubar_accepted_only = coemiu_fortran_exact * absubar_accepted_only
            sfmiu_absubar_candidate_only = coemiu_fortran_exact * absubar_candidate_only
            sfmiu_absubar_squared_audit = coemiu_fortran_exact * absubar * absubar
            manningbar = np.where(
                cv_local > CVTOL,
                manning * self.manningb * np.exp(self.manningm * cv_local),
                manning,
            )
            raw_native_manning = np.full_like(manning, float(getattr(self.config.rheology, "n_manning", 0.0)))
            manningbar_raw_native = np.where(
                cv_local > CVTOL,
                raw_native_manning * self.manningb * np.exp(self.manningm * cv_local),
                raw_native_manning,
            )
            manningbar_no_cv_correction = manning
            sfmanning_current = manningbar * manningbar / np.power(safe_fh, DFS_MANNING_EXP) * absubar * absubar
            sfmanning_absubar_fortran_fvpredi2 = (
                manningbar * manningbar / np.power(safe_fh, DFS_MANNING_EXP) * absubar_fortran_fvpredi2 * absubar_fortran_fvpredi2
            )
            sfmanning_absubar_fortran_preflux = (
                manningbar * manningbar / np.power(safe_fh, DFS_MANNING_EXP) * absubar_fortran_preflux * absubar_fortran_preflux
            )
            sfmanning_absubar_accepted_only = (
                manningbar * manningbar / np.power(safe_fh, DFS_MANNING_EXP) * absubar_accepted_only * absubar_accepted_only
            )
            sfmanning_absubar_candidate_only = (
                manningbar * manningbar / np.power(safe_fh, DFS_MANNING_EXP) * absubar_candidate_only * absubar_candidate_only
            )
            sfmanning_absubar_linear_audit = (
                manningbar * manningbar / np.power(safe_fh, DFS_MANNING_EXP) * absubar
            )
            sfmanning_depth_exponent_fortran = (
                manningbar * manningbar / np.power(safe_fh, 1.333) * absubar * absubar
            )
            sfmanning_raw_native_manning_source = (
                manningbar_raw_native
                * manningbar_raw_native
                / np.power(safe_fh, DFS_MANNING_EXP)
                * absubar
                * absubar
            )
            sfmanning_no_cv_correction = (
                manningbar_no_cv_correction
                * manningbar_no_cv_correction
                / np.power(safe_fh, DFS_MANNING_EXP)
                * absubar
                * absubar
            )
        sfmiu_current = np.where(np.isfinite(sfmiu_current), sfmiu_current, 0.0)
        miudebris = np.where(np.isfinite(miudebris), miudebris, 0.0)
        miudebris_fortran_exact = np.where(np.isfinite(miudebris_fortran_exact), miudebris_fortran_exact, 0.0)
        coemiu_current = np.where(np.isfinite(coemiu_current), coemiu_current, 0.0)
        coemiu_fortran_exact = np.where(np.isfinite(coemiu_fortran_exact), coemiu_fortran_exact, 0.0)
        sfmiu_absubar_fortran_fvpredi2 = np.where(np.isfinite(sfmiu_absubar_fortran_fvpredi2), sfmiu_absubar_fortran_fvpredi2, 0.0)
        sfmiu_absubar_fortran_preflux = np.where(np.isfinite(sfmiu_absubar_fortran_preflux), sfmiu_absubar_fortran_preflux, 0.0)
        sfmiu_absubar_accepted_only = np.where(np.isfinite(sfmiu_absubar_accepted_only), sfmiu_absubar_accepted_only, 0.0)
        sfmiu_absubar_candidate_only = np.where(np.isfinite(sfmiu_absubar_candidate_only), sfmiu_absubar_candidate_only, 0.0)
        sfmiu_absubar_squared_audit = np.where(np.isfinite(sfmiu_absubar_squared_audit), sfmiu_absubar_squared_audit, 0.0)
        sfmanning_current = np.where(np.isfinite(sfmanning_current), sfmanning_current, 0.0)
        sfmanning_absubar_fortran_fvpredi2 = np.where(np.isfinite(sfmanning_absubar_fortran_fvpredi2), sfmanning_absubar_fortran_fvpredi2, 0.0)
        sfmanning_absubar_fortran_preflux = np.where(np.isfinite(sfmanning_absubar_fortran_preflux), sfmanning_absubar_fortran_preflux, 0.0)
        sfmanning_absubar_accepted_only = np.where(np.isfinite(sfmanning_absubar_accepted_only), sfmanning_absubar_accepted_only, 0.0)
        sfmanning_absubar_candidate_only = np.where(np.isfinite(sfmanning_absubar_candidate_only), sfmanning_absubar_candidate_only, 0.0)
        sfmanning_absubar_linear_audit = np.where(np.isfinite(sfmanning_absubar_linear_audit), sfmanning_absubar_linear_audit, 0.0)
        sfmanning_depth_exponent_fortran = np.where(np.isfinite(sfmanning_depth_exponent_fortran), sfmanning_depth_exponent_fortran, 0.0)
        sfmanning_raw_native_manning_source = np.where(np.isfinite(sfmanning_raw_native_manning_source), sfmanning_raw_native_manning_source, 0.0)
        sfmanning_no_cv_correction = np.where(np.isfinite(sfmanning_no_cv_correction), sfmanning_no_cv_correction, 0.0)

        sfy_current = _sfy_from_cvbar(cv_local)
        sfy_scalar_cvbar = _sfy_from_cvbar(cvbar_depth_weighted)
        sfy_zero = np.zeros_like(sfy_current)

        def _tau_from_components(
            *,
            sfy: np.ndarray,
            sfmiu: np.ndarray,
            sfmanning: np.ndarray = sfmanning_current,
        ) -> np.ndarray:
            return (sfmanning + sfy + sfmiu) * gammadeb * fhpredi1

        def _tau_from_sfy(sfy: np.ndarray) -> np.ndarray:
            return _tau_from_components(sfy=sfy, sfmiu=sfmiu_current, sfmanning=sfmanning_current)

        tau_local_cv_recomputed = _tau_from_sfy(sfy_current)
        tau_scalar_cvbar = _tau_from_sfy(sfy_scalar_cvbar)
        tau_zero_sfy = _tau_from_sfy(sfy_zero)
        tau_absubar_fortran_fvpredi2 = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_absubar_fortran_fvpredi2,
            sfmanning=sfmanning_absubar_fortran_fvpredi2,
        )
        tau_absubar_fortran_preflux = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_absubar_fortran_preflux,
            sfmanning=sfmanning_absubar_fortran_preflux,
        )
        tau_absubar_accepted_only = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_absubar_accepted_only,
            sfmanning=sfmanning_absubar_accepted_only,
        )
        tau_absubar_candidate_only = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_absubar_candidate_only,
            sfmanning=sfmanning_absubar_candidate_only,
        )
        tau_miudebris_fortran_exact = _tau_from_components(
            sfy=sfy_current,
            sfmiu=coemiu_fortran_exact * absubar,
            sfmanning=sfmanning_current,
        )
        tau_sfmiu_squared_audit = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_absubar_squared_audit,
            sfmanning=sfmanning_current,
        )
        tau_sfmiu_disabled = _tau_from_components(
            sfy=sfy_current,
            sfmiu=np.zeros_like(sfmiu_current),
            sfmanning=sfmanning_current,
        )
        tau_sfmanning_only = _tau_from_components(
            sfy=np.zeros_like(sfy_current),
            sfmiu=np.zeros_like(sfmiu_current),
            sfmanning=sfmanning_current,
        )
        tau_sfmanning_disabled = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=np.zeros_like(sfmanning_current),
        )
        tau_sfmanning_fortran_fvpredi2 = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_absubar_fortran_fvpredi2,
        )
        tau_sfmanning_accepted_velocity = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_absubar_accepted_only,
        )
        tau_sfmanning_candidate_velocity = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_absubar_candidate_only,
        )
        tau_sfmanning_linear_absubar = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_absubar_linear_audit,
        )
        tau_sfmanning_depth_exponent_fortran = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_depth_exponent_fortran,
        )
        tau_sfmanning_raw_native_manning = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_raw_native_manning_source,
        )
        tau_sfmanning_no_cv_correction = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_no_cv_correction,
        )
        tau_original_decisions_fortran_sfmanning = _tau_from_components(
            sfy=sfy_current,
            sfmiu=sfmiu_current,
            sfmanning=sfmanning_absubar_fortran_fvpredi2,
        )

        cv_gate = active_mask & (cv_local < cvlimit)
        depth_gate = active_mask & (fhpredi1 > DFS_EROSION_DEPTH_TRIGGER)
        tau_gt_active = active_mask & (tau > taoc_active)
        tau_gt_old = active_mask & (tau > taoc_old)
        tau_gt_local_cv = active_mask & (tau > taoc_local_cv)
        tau_gt_local_cv_fhpredi1 = active_mask & (tau > taoc_local_cv_fhpredi1)
        all_gate_active = cv_gate & depth_gate & tau_gt_active
        all_gate_old = cv_gate & depth_gate & tau_gt_old
        all_gate_local_cv = cv_gate & depth_gate & tau_gt_local_cv
        all_gate_local_cv_fhpredi1 = cv_gate & depth_gate & tau_gt_local_cv_fhpredi1

        def _variant_stats(name: str, tau_variant: np.ndarray) -> dict[str, object]:
            tau_gt = active_mask & (tau_variant > taoc_active)
            all_gate = cv_gate & depth_gate & tau_gt
            raw = np.where(all_gate, kero * np.maximum(tau_variant - taoc_active, 0.0), 0.0)
            return {
                "name": name,
                "count_tau_gt_taoc": int(np.count_nonzero(tau_gt)),
                "count_all_erosion_gates_true": int(np.count_nonzero(all_gate)),
                "positive_erosion_cell_count": int(np.count_nonzero(raw > 1.0e-14)),
                "erorate_raw_sum": float(np.sum(raw[active_mask])),
                "erorate_raw_max": float(np.max(raw[active_mask])) if np.any(active_mask) else 0.0,
                "predicted_erosion_increment_sum": float(np.sum(raw[active_mask]) * float(dt_used)),
                "overlap_with_active_gate_count": int(np.count_nonzero(all_gate & all_gate_active)),
                "tau": self._step_diag_stats(tau_variant, active_mask),
                "tau_minus_taoc": self._step_diag_stats(tau_variant - taoc_active, active_mask),
            }

        tau_variants = {
            "A_current_active": _variant_stats("A_current_active", tau),
            "B_sfy_scalar_depth_weighted_cvbar": _variant_stats(
                "B_sfy_scalar_depth_weighted_cvbar", tau_scalar_cvbar
            ),
            "C_sfy_zero_cvbar_lte_cvtol": _variant_stats("C_sfy_zero_cvbar_lte_cvtol", tau_zero_sfy),
            "D_sfy_local_cv_recomputed": _variant_stats("D_sfy_local_cv_recomputed", tau_local_cv_recomputed),
        }
        sfmiu_absubar_variants = {
            "A_active_current_sfmiu": _variant_stats("A_active_current_sfmiu", tau),
            "B_absubar_fortran_fvpredi2_candidate": _variant_stats(
                "B_absubar_fortran_fvpredi2_candidate", tau_absubar_fortran_fvpredi2
            ),
            "B2_absubar_fortran_preflux_velocity_state": _variant_stats(
                "B2_absubar_fortran_preflux_velocity_state", tau_absubar_fortran_preflux
            ),
            "C_absubar_accepted_velocity_only": _variant_stats(
                "C_absubar_accepted_velocity_only", tau_absubar_accepted_only
            ),
            "D_absubar_candidate_velocity_only": _variant_stats(
                "D_absubar_candidate_velocity_only", tau_absubar_candidate_only
            ),
            "E_miudebris_exact_fortran_branch": _variant_stats(
                "E_miudebris_exact_fortran_branch", tau_miudebris_fortran_exact
            ),
            "F_sfmiu_absubar_squared_audit": _variant_stats(
                "F_sfmiu_absubar_squared_audit", tau_sfmiu_squared_audit
            ),
            "G_sfmiu_disabled": _variant_stats("G_sfmiu_disabled", tau_sfmiu_disabled),
            "H_sfmanning_only_tau": _variant_stats("H_sfmanning_only_tau", tau_sfmanning_only),
        }
        sfmanning_variants = {
            "A_active_current_tau": _variant_stats("A_active_current_tau", tau),
            "B_sfmanning_disabled": _variant_stats("B_sfmanning_disabled", tau_sfmanning_disabled),
            "C_sfmanning_only_current": _variant_stats("C_sfmanning_only_current", tau_sfmanning_only),
            "D_sfmanning_fortran_fvpredi2_absubar": _variant_stats(
                "D_sfmanning_fortran_fvpredi2_absubar", tau_sfmanning_fortran_fvpredi2
            ),
            "E_sfmanning_accepted_velocity": _variant_stats(
                "E_sfmanning_accepted_velocity", tau_sfmanning_accepted_velocity
            ),
            "F_sfmanning_candidate_velocity": _variant_stats(
                "F_sfmanning_candidate_velocity", tau_sfmanning_candidate_velocity
            ),
            "G_sfmanning_absubar_linear_audit": _variant_stats(
                "G_sfmanning_absubar_linear_audit", tau_sfmanning_linear_absubar
            ),
            "H_sfmanning_fortran_depth_exponent": _variant_stats(
                "H_sfmanning_fortran_depth_exponent", tau_sfmanning_depth_exponent_fortran
            ),
            "I_sfmanning_raw_native_manning_source": _variant_stats(
                "I_sfmanning_raw_native_manning_source", tau_sfmanning_raw_native_manning
            ),
            "J_sfmanning_cv_correction_disabled_audit": _variant_stats(
                "J_sfmanning_cv_correction_disabled_audit", tau_sfmanning_no_cv_correction
            ),
            "K_original_sfy_sfmiu_plus_fortran_sfmanning": _variant_stats(
                "K_original_sfy_sfmiu_plus_fortran_sfmanning", tau_original_decisions_fortran_sfmanning
            ),
        }

        raw_erorate_recomputed = np.where(
            all_gate_active, kero * np.maximum(tau - taoc_active, 0.0), 0.0
        )
        zone_ids = sorted(getattr(getattr(self.config, "spatial_zones", None), "zones", {}).keys())
        zone_id_raw_candidate = np.full_like(zone_id_current, -1, dtype=np.int32)
        kero_zone_table_value = np.zeros_like(kero, dtype=np.float64)
        for remapped_index, raw_zone_id in enumerate(zone_ids):
            zone_mask = zone_id_current == remapped_index
            zone_id_raw_candidate = np.where(zone_mask, int(raw_zone_id), zone_id_raw_candidate)
            zone_params = self.config.spatial_zones.zones[raw_zone_id]
            kero_zone_table_value = np.where(zone_mask, float(zone_params.kero), kero_zone_table_value)

        def _kero_from_remapped_index(remapped_index: np.ndarray) -> np.ndarray:
            candidate = np.zeros_like(kero, dtype=np.float64)
            for zone_index, raw_zone_id in enumerate(zone_ids):
                zone_params = self.config.spatial_zones.zones[raw_zone_id]
                candidate = np.where(remapped_index == zone_index, float(zone_params.kero), candidate)
            return candidate

        def _kero_variant_stats(
            name: str,
            kero_variant: np.ndarray,
            *,
            source_valid: bool,
            audit_note: str,
        ) -> dict[str, object]:
            raw = np.where(all_gate_active, kero_variant * np.maximum(tau - taoc_active, 0.0), 0.0)
            return {
                "name": name,
                "source_valid": bool(source_valid),
                "audit_note": audit_note,
                "count_tau_gt_taoc": int(np.count_nonzero(tau_gt_active)),
                "count_all_erosion_gates_true": int(np.count_nonzero(all_gate_active)),
                "positive_erosion_cell_count": int(np.count_nonzero(raw > 1.0e-14)),
                "erorate_raw_sum": float(np.sum(raw[active_mask])),
                "erorate_raw_max": float(np.max(raw[active_mask])) if np.any(active_mask) else 0.0,
                "predicted_erosion_increment_sum": float(np.sum(raw[active_mask]) * float(dt_used)),
                "kero": self._step_diag_stats(kero_variant, active_mask),
            }

        kero_unit_zone_variants = {
            "A_active_current": _kero_variant_stats(
                "A_active_current",
                kero,
                source_valid=True,
                audit_note="Active current kero field from zone/material mapping.",
            ),
            "B_kero_per_hour_div_3600": _kero_variant_stats(
                "B_kero_per_hour_div_3600",
                kero / 3600.0,
                source_valid=False,
                audit_note="Audit-only time-unit probe; Fortran source has not shown this conversion.",
            ),
            "C_kero_per_minute_div_60": _kero_variant_stats(
                "C_kero_per_minute_div_60",
                kero / 60.0,
                source_valid=False,
                audit_note="Audit-only time-unit probe; Fortran source has not shown this conversion.",
            ),
            "D_kero_percent_style_div_100": _kero_variant_stats(
                "D_kero_percent_style_div_100",
                kero / 100.0,
                source_valid=False,
                audit_note="Audit-only percent-style unit probe; not a production candidate without input-unit evidence.",
            ),
            "E_kero_milli_style_div_1000": _kero_variant_stats(
                "E_kero_milli_style_div_1000",
                kero / 1000.0,
                source_valid=False,
                audit_note="Audit-only milli-style unit probe; not a production candidate without input-unit evidence.",
            ),
            "F_zone_index_shift_minus_1": _kero_variant_stats(
                "F_zone_index_shift_minus_1",
                _kero_from_remapped_index(zone_id_current - 1),
                source_valid=False,
                audit_note="Audit-only off-by-one probe.",
            ),
            "G_zone_index_shift_plus_1": _kero_variant_stats(
                "G_zone_index_shift_plus_1",
                _kero_from_remapped_index(zone_id_current + 1),
                source_valid=False,
                audit_note="Audit-only off-by-one probe.",
            ),
            "H_top_layer_kero_only": _kero_variant_stats(
                "H_top_layer_kero_only",
                kero_zone_table_value,
                source_valid=True,
                audit_note="Top-layer zone table kero remapped through current zone_id.",
            ),
            "I_raw_native_zone_kero_table": _kero_variant_stats(
                "I_raw_native_zone_kero_table",
                kero_zone_table_value,
                source_valid=True,
                audit_note="Raw native zone/material table recomputation using current remap.",
            ),
        }

        erosion_output_current_raw_after_step = erosion_depth + raw_erorate_recomputed * float(dt_used)
        erosion_output_eleori_minus_tempele = z_original - tempele
        erosion_output_positive = np.maximum(erosion_output_eleori_minus_tempele, 0.0)
        erosion_output_thresholded = np.where(erosion_output_positive < 0.001, 0.0, erosion_output_positive)
        erosion_output_fortran_equivalent = np.where(gindx_output_mask, 0.0, erosion_output_thresholded)
        erosion_output_interpretation_variants = {
            "A_current_raw_erosion_depth_after_step": {
                "source_valid": True,
                "audit_note": "Current accumulated erosion_depth after this accepted step.",
                **self._step_diag_stats(erosion_output_current_raw_after_step, active_mask),
                "positive_erosion_cell_count": int(
                    np.count_nonzero(active_mask & (erosion_output_current_raw_after_step > 1.0e-14))
                ),
            },
            "J_fortran_eleori_minus_ele_mask": {
                "source_valid": True,
                "audit_note": "Fortran checkpoint writer uses eleori-ele, thresholds <0.001, and masks gindx==1.",
                **self._step_diag_stats(erosion_output_fortran_equivalent, active_mask),
                "positive_erosion_cell_count": int(
                    np.count_nonzero(active_mask & (erosion_output_fortran_equivalent > 1.0e-14))
                ),
            },
            "K_threshold_only": {
                "source_valid": True,
                "audit_note": "Fortran threshold without gindx mask, used to separate threshold from failure-cell masking.",
                **self._step_diag_stats(erosion_output_thresholded, active_mask),
                "positive_erosion_cell_count": int(
                    np.count_nonzero(active_mask & (erosion_output_thresholded > 1.0e-14))
                ),
            },
        }

        erosion_increment = erorate_clamped * float(dt_used)
        deposition_increment = np.abs(deporate_clamped) * float(dt_used)
        top_cells: list[dict[str, object]] = []
        candidate_mask = active_mask & (
            (np.abs(erosion_increment) > 1.0e-14)
            | (np.abs(erorate_raw) > 1.0e-14)
            | (np.abs(tempfsh) > 1.0e-12)
            | tau_gt_active
            | tau_gt_local_cv
            | (np.abs(deporate_clamped) > 1.0e-14)
        )
        flat_indices = np.flatnonzero(candidate_mask.ravel())
        if flat_indices.size and self.erosion_step_top_cell_limit > 0:
            score = (
                np.abs(erosion_increment) * 1.0e6
                + np.maximum(tau - taoc_active, 0.0)
                + np.maximum(tau - taoc_local_cv, 0.0)
                + np.abs(tempfsh) * 1.0e2
                + deposition_increment * 1.0e5
            )
            order = np.argsort(score.ravel()[flat_indices])[::-1]
            for flat in flat_indices[order[: self.erosion_step_top_cell_limit]]:
                i, j = np.unravel_index(int(flat), tau.shape)
                top_cells.append(
                    {
                        "i": int(i),
                        "j": int(j),
                        "cell_id": int(cell_id[i, j]),
                        "zone_id_current": int(zone_id_current[i, j]),
                        "zone_id_raw_raster": int(zone_id_raw_candidate[i, j]),
                        "zone_id_fortran_candidate": int(zone_id_raw_candidate[i, j]),
                        "tau": float(tau[i, j]),
                        "taoc_active": float(taoc_active[i, j]),
                        "taoc_old": float(taoc_old[i, j]),
                        "taoc_with_local_cv": float(taoc_local_cv[i, j]),
                        "taoc_with_local_cv_and_fhpredi1": float(taoc_local_cv_fhpredi1[i, j]),
                        "tau_minus_taoc_active": float(tau[i, j] - taoc_active[i, j]),
                        "tau_minus_taoc_with_local_cv": float(tau[i, j] - taoc_local_cv[i, j]),
                        "sfy_current": float(sfy_current[i, j]),
                        "sfy_scalar_depth_weighted_cvbar": float(sfy_scalar_cvbar[i, j]),
                        "sfmiu_current": float(sfmiu_current[i, j]),
                        "sfmiu_absubar_fortran_fvpredi2": float(sfmiu_absubar_fortran_fvpredi2[i, j]),
                        "sfmiu_absubar_fortran_preflux": float(sfmiu_absubar_fortran_preflux[i, j]),
                        "sfmiu_absubar_accepted_only": float(sfmiu_absubar_accepted_only[i, j]),
                        "sfmiu_absubar_candidate_only": float(sfmiu_absubar_candidate_only[i, j]),
                        "sfmiu_absubar_squared_audit": float(sfmiu_absubar_squared_audit[i, j]),
                        "sfmanning_current": float(sfmanning_current[i, j]),
                        "sfmanning_absubar_fortran_fvpredi2": float(sfmanning_absubar_fortran_fvpredi2[i, j]),
                        "sfmanning_absubar_fortran_preflux": float(sfmanning_absubar_fortran_preflux[i, j]),
                        "sfmanning_absubar_accepted_only": float(sfmanning_absubar_accepted_only[i, j]),
                        "sfmanning_absubar_candidate_only": float(sfmanning_absubar_candidate_only[i, j]),
                        "sfmanning_absubar_linear_audit": float(sfmanning_absubar_linear_audit[i, j]),
                        "sfmanning_depth_exponent_fortran": float(sfmanning_depth_exponent_fortran[i, j]),
                        "sfmanning_raw_native_manning_source": float(sfmanning_raw_native_manning_source[i, j]),
                        "sfmanning_no_cv_correction": float(sfmanning_no_cv_correction[i, j]),
                        "gammadeb_current": float(gammadeb[i, j]),
                        "manning_field": float(manning[i, j]),
                        "manning_raw_native_config": float(raw_native_manning[i, j]),
                        "manningbar_current": float(manningbar[i, j]),
                        "manningbar_raw_native": float(manningbar_raw_native[i, j]),
                        "manningbar_no_cv_correction": float(manningbar_no_cv_correction[i, j]),
                        "manning_source": "n_manning_field",
                        "manning_zone_or_fallback_source": "runtime_input_manifest.manning_source",
                        "kero_current": float(kero[i, j]),
                        "kero_zone_table_value": float(kero_zone_table_value[i, j]),
                        "kresis": float(self.kresis),
                        "alpha2": float(alpha2[i, j]),
                        "beta2": float(beta2[i, j]),
                        "miudebris_current": float(miudebris[i, j]),
                        "miudebris_fortran_exact": float(miudebris_fortran_exact[i, j]),
                        "coemiu_current": float(coemiu_current[i, j]),
                        "absubar_current": float(absubar[i, j]),
                        "absubar_fortran_fvpredi2_candidate": float(absubar_fortran_fvpredi2[i, j]),
                        "absubar_fortran_preflux_velocity_state": float(absubar_fortran_preflux[i, j]),
                        "absubar_active_source": (
                            "fortran_preflux_fvpredi2_half_accepted"
                            if self.use_fortran_absubar_velocity_state
                            else "accepted_fv_fortran"
                        ),
                        "absubar_accepted_velocity_only": float(absubar_accepted_only[i, j]),
                        "absubar_candidate_velocity_only": float(absubar_candidate_only[i, j]),
                        "absubar_current_squared": float(absubar[i, j] * absubar[i, j]),
                        "vorth_accepted_velocity": float(vorth_accepted_only[i, j]),
                        "vcomp_accepted_velocity": float(vcomp_accepted_only[i, j]),
                        "vorth_candidate_velocity": float(vorth_candidate_only[i, j]),
                        "vcomp_candidate_velocity": float(vcomp_candidate_only[i, j]),
                        "vorth_fortran_fvpredi2": float(vorth_fortran_fvpredi2[i, j]),
                        "vcomp_fortran_fvpredi2": float(vcomp_fortran_fvpredi2[i, j]),
                        "vorth_fortran_preflux": float(vorth_fortran_preflux[i, j]),
                        "vcomp_fortran_preflux": float(vcomp_fortran_preflux[i, j]),
                        "tau_variant_absubar_fortran_preflux_velocity_state": float(tau_absubar_fortran_preflux[i, j]),
                        "tau_variant_sfy_scalar_depth_weighted_cvbar": float(tau_scalar_cvbar[i, j]),
                        "tau_variant_sfy_zero_cvbar_lte_cvtol": float(tau_zero_sfy[i, j]),
                        "tau_variant_sfy_local_cv_recomputed": float(tau_local_cv_recomputed[i, j]),
                        "tau_variant_absubar_fortran_fvpredi2_candidate": float(tau_absubar_fortran_fvpredi2[i, j]),
                        "tau_variant_absubar_accepted_velocity_only": float(tau_absubar_accepted_only[i, j]),
                        "tau_variant_absubar_candidate_velocity_only": float(tau_absubar_candidate_only[i, j]),
                        "tau_variant_sfmiu_disabled": float(tau_sfmiu_disabled[i, j]),
                        "tau_variant_sfmanning_only": float(tau_sfmanning_only[i, j]),
                        "tau_variant_sfmanning_disabled": float(tau_sfmanning_disabled[i, j]),
                        "tau_variant_sfmanning_fortran_fvpredi2": float(tau_sfmanning_fortran_fvpredi2[i, j]),
                        "tau_variant_sfmanning_linear_absubar": float(tau_sfmanning_linear_absubar[i, j]),
                        "tau_variant_sfmanning_raw_native_manning": float(tau_sfmanning_raw_native_manning[i, j]),
                        "tau_variant_sfmanning_no_cv_correction": float(tau_sfmanning_no_cv_correction[i, j]),
                        "cv_local": float(cv_local[i, j]),
                        "cv_accepted": float(cv_accepted[i, j]),
                        "cvbar_candidate_depth_weighted_global": float(cvbar_depth_weighted),
                        "cvlimit": float(cvlimit[i, j]),
                        "fhpredi1": float(fhpredi1[i, j]),
                        "frhopredi1": float(frhopredi1[i, j]),
                        "h_current": float(h_current[i, j]),
                        "erorate_raw": float(erorate_raw[i, j]),
                        "erorate_raw_recomputed_from_kero_tau": float(raw_erorate_recomputed[i, j]),
                        "dt_current": float(dt_used),
                        "erod_increment_from_raw": float(raw_erorate_recomputed[i, j] * float(dt_used)),
                        "Erosion_depth_increment_actual": float(erosion_increment[i, j]),
                        "erosion_output_eleori_minus_ele": float(erosion_output_eleori_minus_tempele[i, j]),
                        "erosion_output_fortran_equivalent": float(erosion_output_fortran_equivalent[i, j]),
                        "gindx_output_mask": bool(gindx_output_mask[i, j]),
                        "erorate_after_rholimit_clamp": float(erorate_rholimit[i, j]),
                        "erorate_clamped": float(erorate_clamped[i, j]),
                        "erosion_increment": float(erosion_increment[i, j]),
                        "deporate_raw": float(deporate_raw[i, j]),
                        "deporate_clamped": float(deporate_clamped[i, j]),
                        "deposition_increment": float(deposition_increment[i, j]),
                        "tempfsh": float(tempfsh[i, j]),
                        "tempfsrho": float(tempfsrho[i, j]),
                        "rholimit_clamp": int(rholimit_clamp[i, j]),
                        "erodible_clamp": int(erodible_clamp[i, j]),
                    }
                )

        def _top_cells_by_metric(metric: np.ndarray, metric_name: str) -> list[dict[str, object]]:
            if self.erosion_step_top_cell_limit <= 0 or not np.any(active_mask):
                return []
            values = np.where(active_mask, metric, -np.inf)
            flat = np.flatnonzero(np.isfinite(values.ravel()))
            if flat.size == 0:
                return []
            order = np.argsort(values.ravel()[flat])[::-1]
            rows: list[dict[str, object]] = []
            for flat_index in flat[order[: self.erosion_step_top_cell_limit]]:
                i, j = np.unravel_index(int(flat_index), metric.shape)
                rows.append(
                    {
                        "i": int(i),
                        "j": int(j),
                        "cell_id": int(cell_id[i, j]),
                        "zone_id_current": int(zone_id_current[i, j]),
                        "zone_id_raw_raster": int(zone_id_raw_candidate[i, j]),
                        metric_name: float(metric[i, j]),
                        "sfmiu_current": float(sfmiu_current[i, j]),
                        "sfmanning_current": float(sfmanning_current[i, j]),
                        "sfmanning_absubar_fortran_fvpredi2": float(sfmanning_absubar_fortran_fvpredi2[i, j]),
                        "tau_minus_taoc_active": float(tau[i, j] - taoc_active[i, j]),
                        "erorate_raw": float(erorate_raw[i, j]),
                        "absubar_current": float(absubar[i, j]),
                        "absubar_current_squared": float(absubar[i, j] * absubar[i, j]),
                        "absubar_fortran_fvpredi2_candidate": float(absubar_fortran_fvpredi2[i, j]),
                        "absubar_candidate_velocity_only": float(absubar_candidate_only[i, j]),
                        "manning_field": float(manning[i, j]),
                        "kero_current": float(kero[i, j]),
                        "kero_zone_table_value": float(kero_zone_table_value[i, j]),
                        "manning_raw_native_config": float(raw_native_manning[i, j]),
                        "manningbar_current": float(manningbar[i, j]),
                        "miudebris_current": float(miudebris[i, j]),
                        "fhpredi1": float(fhpredi1[i, j]),
                        "frhopredi1": float(frhopredi1[i, j]),
                        "gammadeb": float(gammadeb[i, j]),
                        "cv_local": float(cv_local[i, j]),
                        "taoc_active": float(taoc_active[i, j]),
                        "erorate_raw_recomputed_from_kero_tau": float(raw_erorate_recomputed[i, j]),
                        "erosion_output_eleori_minus_ele": float(erosion_output_eleori_minus_tempele[i, j]),
                        "erosion_output_fortran_equivalent": float(erosion_output_fortran_equivalent[i, j]),
                    }
                )
            return rows

        def _tracked_cell_payload(i: int, j: int) -> dict[str, object]:
            return {
                "i": int(i),
                "j": int(j),
                "cell_id": int(cell_id[i, j]),
                "tracked_reason": "requested_cell_id",
                "active_cell": bool(active_mask[i, j]),
                "zone_id_current": int(zone_id_current[i, j]),
                "zone_id_raw_raster": int(zone_id_raw_candidate[i, j]),
                "zone_id_fortran_candidate": int(zone_id_raw_candidate[i, j]),
                "cv_local": float(cv_local[i, j]),
                "cv_accepted": float(cv_accepted[i, j]),
                "cvlimit": float(cvlimit[i, j]),
                "fhpredi1": float(fhpredi1[i, j]),
                "frhopredi1": float(frhopredi1[i, j]),
                "fhpredi_after_source_merge": float(state["fhpredi"][i, j]),
                "frhopredi_after_source_merge": float(state["frhopredi"][i, j]),
                "fhpredi2_after_qnet": float(state["fhpredi2"][i, j]),
                "frhopredi2_after_qmassnet": float(state["frhopredi2"][i, j]),
                "source_merge_depth_increment": float(state["fhpredi"][i, j] - fhpredi1[i, j]),
                "qnet_depth_increment": float(state["fhpredi2"][i, j] - state["fhpredi"][i, j]),
                "accepted_commit_depth_delta": float(state["fhpredi2"][i, j] - h_current[i, j]),
                "h_current": float(h_current[i, j]),
                "tau": float(tau[i, j]),
                "taoc_active": float(taoc_active[i, j]),
                "taoc_old": float(taoc_old[i, j]),
                "taoc_with_local_cv": float(taoc_local_cv[i, j]),
                "taoc_with_local_cv_and_fhpredi1": float(taoc_local_cv_fhpredi1[i, j]),
                "tau_minus_taoc_active": float(tau[i, j] - taoc_active[i, j]),
                "kero_current": float(kero[i, j]),
                "kero_zone_table_value": float(kero_zone_table_value[i, j]),
                "manning_field": float(manning[i, j]),
                "manning_raw_native_config": float(raw_native_manning[i, j]),
                "manningbar_current": float(manningbar[i, j]),
                "manningbar_raw_native": float(manningbar_raw_native[i, j]),
                "manningbar_no_cv_correction": float(manningbar_no_cv_correction[i, j]),
                "slope_rad": float(slope[i, j]),
                "dynamic_tanslo": float(tanslo_dynamic[i, j]),
                "absubar_current": float(absubar[i, j]),
                "absubar_fortran_fvpredi2_candidate": float(absubar_fortran_fvpredi2[i, j]),
                "fvpredi2_fortran_candidate": [
                    float(value) for value in np.asarray(fvpredi2_candidate[i, j, :], dtype=np.float64).tolist()
                ],
                "vorth_accepted_velocity": float(vorth_accepted_only[i, j]),
                "vcomp_accepted_velocity": float(vcomp_accepted_only[i, j]),
                "vorth_candidate_velocity": float(vorth_candidate_only[i, j]),
                "vcomp_candidate_velocity": float(vcomp_candidate_only[i, j]),
                "vorth_fortran_fvpredi2": float(vorth_fortran_fvpredi2[i, j]),
                "vcomp_fortran_fvpredi2": float(vcomp_fortran_fvpredi2[i, j]),
                "cvbar_candidate_depth_weighted_global": float(cvbar_depth_weighted),
                "miudebris_current": float(miudebris[i, j]),
                "miudebris_fortran_exact": float(miudebris_fortran_exact[i, j]),
                "coemiu_current": float(coemiu_current[i, j]),
                "coemiu_fortran_exact": float(coemiu_fortran_exact[i, j]),
                "coemanning_current": float(
                    manningbar[i, j]
                    * manningbar[i, j]
                    / np.power(max(float(fhpredi1[i, j]), EPS), DFS_MANNING_EXP)
                ),
                "coemanning_fortran_literal_depth": float(
                    manningbar[i, j] * manningbar[i, j] / np.power(max(float(fhpredi1[i, j]), EPS), 1.333)
                ),
                "sfy_current": float(sfy_current[i, j]),
                "sfmiu_current": float(sfmiu_current[i, j]),
                "sfmanning_current": float(sfmanning_current[i, j]),
                "gammadeb_current": float(gammadeb[i, j]),
                "erorate_raw": float(erorate_raw[i, j]),
                "erorate_raw_recomputed_from_kero_tau": float(raw_erorate_recomputed[i, j]),
                "erorate_after_rholimit_clamp": float(erorate_rholimit[i, j]),
                "erorate_clamped": float(erorate_clamped[i, j]),
                "deporate_raw": float(deporate_raw[i, j]),
                "deporate_clamped": float(deporate_clamped[i, j]),
                "erosion_increment": float(erosion_increment[i, j]),
                "deposition_increment": float(deposition_increment[i, j]),
                "eleori_minus_ele": float(erosion_output_eleori_minus_tempele[i, j]),
                "tempele": float(tempele[i, j]),
                "eleori_or_z_original": float(z_original[i, j]),
                "erosion_output_fortran_equivalent": float(erosion_output_fortran_equivalent[i, j]),
                "gindx_output_mask": bool(gindx_output_mask[i, j]),
                "output_threshold_pass": bool(erosion_output_positive[i, j] >= 0.001),
                "all_erosion_gate_active": bool(all_gate_active[i, j]),
                "cv_gate": bool(cv_gate[i, j]),
                "depth_gate": bool(depth_gate[i, j]),
                "tau_gt_taoc_active": bool(tau_gt_active[i, j]),
                "tempfsh": float(tempfsh[i, j]),
                "tempfsrho": float(tempfsrho[i, j]),
                "rholimit_clamp": int(rholimit_clamp[i, j]),
                "erodible_clamp": int(erodible_clamp[i, j]),
                "dt_current": float(dt_used),
            }

        tracked_cells: list[dict[str, object]] = []
        if self.erosion_step_tracked_cell_ids:
            cell_id_to_indices = {
                int(cell_id[i, j]): (int(i), int(j))
                for i, j in zip(*np.where(active_mask))
            }
            for requested_id in sorted(self.erosion_step_tracked_cell_ids):
                indices = cell_id_to_indices.get(int(requested_id))
                if indices is None:
                    tracked_cells.append(
                        {
                            "cell_id": int(requested_id),
                            "tracked_reason": "requested_cell_id",
                            "status": "not_found_in_active_mask",
                        }
                    )
                    continue
                tracked_cells.append(_tracked_cell_payload(*indices))

        return {
            "t_start_s": float(t_start),
            "t_end_s": float(t_start + dt_used),
            "dt_s": float(dt_used),
            "active_cell_count": int(np.count_nonzero(active_mask)),
            "count_cv_lt_cvlimit": int(np.count_nonzero(cv_gate)),
            "count_fhpredi1_gt_0_05": int(np.count_nonzero(depth_gate)),
            "count_tau_gt_taoc_active": int(np.count_nonzero(tau_gt_active)),
            "count_tau_gt_taoc_old": int(np.count_nonzero(tau_gt_old)),
            "count_tau_gt_taoc_with_local_cv": int(np.count_nonzero(tau_gt_local_cv)),
            "count_tau_gt_taoc_with_local_cv_and_fhpredi1": int(np.count_nonzero(tau_gt_local_cv_fhpredi1)),
            "count_all_erosion_gates_true_active": int(np.count_nonzero(all_gate_active)),
            "count_all_erosion_gates_true_old": int(np.count_nonzero(all_gate_old)),
            "count_all_erosion_gates_true_with_local_cv": int(np.count_nonzero(all_gate_local_cv)),
            "count_all_erosion_gates_true_with_local_cv_and_fhpredi1": int(np.count_nonzero(all_gate_local_cv_fhpredi1)),
            "count_rholimit_clamp": int(np.count_nonzero(active_mask & (rholimit_clamp != 0))),
            "count_erodible_clamp": int(np.count_nonzero(active_mask & (erodible_clamp != 0))),
            "cvbar_candidates": {
                "depth_weighted_global": float(cvbar_depth_weighted),
                "zero": 0.0,
                "source_note": (
                    "Fortran erosion loop uses scalar cvbar before the face loop assigns it in the same vv iteration; "
                    "depth_weighted_global is a diagnostics-only candidate, not an asserted source-equivalent scalar."
                ),
            },
            "tau_components": {
                "sfy_current": self._step_diag_stats(sfy_current, active_mask),
                "sfy_scalar_depth_weighted_cvbar": self._step_diag_stats(sfy_scalar_cvbar, active_mask),
                "sfy_zero_cvbar_lte_cvtol": self._step_diag_stats(sfy_zero, active_mask),
                "sfmiu_current": self._step_diag_stats(sfmiu_current, active_mask),
                "sfmiu_absubar_fortran_fvpredi2": self._step_diag_stats(sfmiu_absubar_fortran_fvpredi2, active_mask),
                "sfmiu_absubar_fortran_preflux": self._step_diag_stats(sfmiu_absubar_fortran_preflux, active_mask),
                "sfmiu_absubar_accepted_only": self._step_diag_stats(sfmiu_absubar_accepted_only, active_mask),
                "sfmiu_absubar_candidate_only": self._step_diag_stats(sfmiu_absubar_candidate_only, active_mask),
                "sfmiu_absubar_squared_audit": self._step_diag_stats(sfmiu_absubar_squared_audit, active_mask),
                "sfmanning_current": self._step_diag_stats(sfmanning_current, active_mask),
                "sfmanning_absubar_fortran_fvpredi2": self._step_diag_stats(sfmanning_absubar_fortran_fvpredi2, active_mask),
                "sfmanning_absubar_fortran_preflux": self._step_diag_stats(sfmanning_absubar_fortran_preflux, active_mask),
                "sfmanning_absubar_accepted_only": self._step_diag_stats(sfmanning_absubar_accepted_only, active_mask),
                "sfmanning_absubar_candidate_only": self._step_diag_stats(sfmanning_absubar_candidate_only, active_mask),
                "sfmanning_absubar_linear_audit": self._step_diag_stats(sfmanning_absubar_linear_audit, active_mask),
                "sfmanning_depth_exponent_fortran": self._step_diag_stats(sfmanning_depth_exponent_fortran, active_mask),
                "sfmanning_raw_native_manning_source": self._step_diag_stats(sfmanning_raw_native_manning_source, active_mask),
                "sfmanning_no_cv_correction": self._step_diag_stats(sfmanning_no_cv_correction, active_mask),
                "gammadeb_current": self._step_diag_stats(gammadeb, active_mask),
                "manning_field": self._step_diag_stats(manning, active_mask),
                "manning_raw_native_config": self._step_diag_stats(raw_native_manning, active_mask),
                "manningbar_current": self._step_diag_stats(manningbar, active_mask),
                "manningbar_raw_native": self._step_diag_stats(manningbar_raw_native, active_mask),
                "manningbar_no_cv_correction": self._step_diag_stats(manningbar_no_cv_correction, active_mask),
                "absubar_current": self._step_diag_stats(absubar, active_mask),
                "absubar_fortran_fvpredi2_candidate": self._step_diag_stats(absubar_fortran_fvpredi2, active_mask),
                "absubar_fortran_preflux_velocity_state": self._step_diag_stats(absubar_fortran_preflux, active_mask),
                "absubar_accepted_velocity_only": self._step_diag_stats(absubar_accepted_only, active_mask),
                "absubar_candidate_velocity_only": self._step_diag_stats(absubar_candidate_only, active_mask),
                "cv_local": self._step_diag_stats(cv_local, active_mask),
                "miudebris_current": self._step_diag_stats(miudebris, active_mask),
                "miudebris_fortran_exact": self._step_diag_stats(miudebris_fortran_exact, active_mask),
                "coemiu_current": self._step_diag_stats(coemiu_current, active_mask),
                "zone_id_current": self._step_diag_stats(zone_id_current, active_mask),
                "zone_id_raw_raster": self._step_diag_stats(zone_id_raw_candidate, active_mask),
                "kero_current": self._step_diag_stats(kero, active_mask),
                "kero_zone_table_value": self._step_diag_stats(kero_zone_table_value, active_mask),
                "erorate_raw_recomputed_from_kero_tau": self._step_diag_stats(
                    raw_erorate_recomputed, active_mask
                ),
                "erosion_output_current_raw_after_step": self._step_diag_stats(
                    erosion_output_current_raw_after_step, active_mask
                ),
                "erosion_output_eleori_minus_ele": self._step_diag_stats(
                    erosion_output_eleori_minus_tempele, active_mask
                ),
                "erosion_output_fortran_equivalent": self._step_diag_stats(
                    erosion_output_fortran_equivalent, active_mask
                ),
            },
            "tau_variants": tau_variants,
            "sfmiu_absubar_variants": sfmiu_absubar_variants,
            "sfmanning_variants": sfmanning_variants,
            "kero_unit_zone_variants": kero_unit_zone_variants,
            "erosion_output_interpretation_variants": erosion_output_interpretation_variants,
            "sfmiu_absubar_parameters": {
                "kresis": float(self.kresis),
                "alpha2": self._step_diag_stats(alpha2, active_mask),
                "beta2": self._step_diag_stats(beta2, active_mask),
            },
            "sfmanning_parameters": {
                "manning_source": "n_manning_field",
                "manning_zone_or_fallback_source": "runtime_input_manifest.manning_source",
                "manningb": float(self.manningb),
                "manningm": float(self.manningm),
                "depth_exponent_current": float(DFS_MANNING_EXP),
                "depth_exponent_fortran_literal": 1.333,
            },
            "sfmiu_absubar_top_cells": {
                "top_50_sfmiu_cells": _top_cells_by_metric(sfmiu_current, "sfmiu_metric"),
                "top_50_tau_minus_taoc_cells": _top_cells_by_metric(tau - taoc_active, "tau_minus_taoc_metric"),
                "top_50_erorate_raw_cells": _top_cells_by_metric(erorate_raw, "erorate_raw_metric"),
                "top_50_absubar_cells": _top_cells_by_metric(absubar, "absubar_metric"),
                "top_50_miudebris_cells": _top_cells_by_metric(miudebris, "miudebris_metric"),
            },
            "sfmanning_top_cells": {
                "top_50_sfmanning_cells": _top_cells_by_metric(sfmanning_current, "sfmanning_metric"),
                "top_50_tau_minus_taoc_cells": _top_cells_by_metric(tau - taoc_active, "tau_minus_taoc_metric"),
                "top_50_erorate_raw_cells": _top_cells_by_metric(erorate_raw, "erorate_raw_metric"),
                "top_50_absubar_squared_cells": _top_cells_by_metric(absubar * absubar, "absubar_squared_metric"),
                "top_50_manning_cells": _top_cells_by_metric(manning, "manning_metric"),
                "top_50_shallow_depth_amplification_cells": _top_cells_by_metric(
                    np.where(np.abs(fhpredi1) > EPS, 1.0 / np.power(np.maximum(fhpredi1, EPS), DFS_MANNING_EXP), 0.0),
                    "shallow_depth_amplification_metric",
                ),
            },
            "kero_zone_unit_top_cells": {
                "top_50_erorate_raw_cells": _top_cells_by_metric(erorate_raw, "erorate_raw_metric"),
                "top_50_Erosion_depth_cells": _top_cells_by_metric(erosion_depth, "Erosion_depth_metric"),
                "top_50_tau_minus_taoc_cells": _top_cells_by_metric(tau - taoc_active, "tau_minus_taoc_metric"),
                "top_50_kero_cells": _top_cells_by_metric(kero, "kero_metric"),
                "top_50_cells_by_zone_contribution": _top_cells_by_metric(
                    np.where(active_mask, kero * np.maximum(tau - taoc_active, 0.0), 0.0),
                    "zone_contribution_metric",
                ),
            },
            "tracked_cells": tracked_cells,
            "tau": self._step_diag_stats(tau, active_mask),
            "taoc_active": self._step_diag_stats(taoc_active, active_mask),
            "taoc_old": self._step_diag_stats(taoc_old, active_mask),
            "taoc_with_local_cv": self._step_diag_stats(taoc_local_cv, active_mask),
            "taoc_with_local_cv_and_fhpredi1": self._step_diag_stats(taoc_local_cv_fhpredi1, active_mask),
            "tau_minus_taoc_active": self._step_diag_stats(tau - taoc_active, active_mask),
            "tau_minus_taoc_with_local_cv": self._step_diag_stats(tau - taoc_local_cv, active_mask),
            "erorate_raw": self._step_diag_stats(erorate_raw, active_mask),
            "erorate_after_rholimit_clamp": self._step_diag_stats(erorate_rholimit, active_mask),
            "erorate_clamped": self._step_diag_stats(erorate_clamped, active_mask),
            "deporate_raw_abs": self._step_diag_stats(np.abs(deporate_raw), active_mask),
            "deporate_clamped_abs": self._step_diag_stats(np.abs(deporate_clamped), active_mask),
            "erosion_depth_increment_sum_expected": float(np.sum(erosion_increment[active_mask])),
            "deposition_depth_increment_sum_expected": float(np.sum(deposition_increment[active_mask])),
            "failure_source_flow_depth_sum": float(np.sum(tempfsh[active_mask])),
            "failure_source_mass_sum": float(np.sum((tempfsh * tempfsrho)[active_mask])),
            "Cv_max": self._step_diag_stats(cv_accepted, active_mask)["max"],
            "Cv_sum": self._step_diag_stats(cv_accepted, active_mask)["sum"],
            "Flow_depth_sum": float(np.sum(flow_depth[active_mask])),
            "Erosion_depth_sum_before_commit": float(np.sum(erosion_depth[active_mask])),
            "Deposit_depth_sum_before_commit": float(np.sum(deposition_depth[active_mask])),
            "top_cells": top_cells,
        }

    def configure_inflow_hydrographs(
        self,
        hydrographs: list[dict[str, object]],
        *,
        denominator_variant: str | None = None,
        denominator_source: str | None = None,
        denominator_basis: str | None = None,
        denominator_direction: int | None = None,
        denominator_fv_value: float | None = None,
    ) -> None:
        configured: list[dict[str, object]] = []
        for hydrograph in hydrographs:
            configured.append(
                {
                    "cell_id": int(hydrograph["cell_id"]),
                    "i": int(hydrograph["i"]),
                    "j": int(hydrograph["j"]),
                    "times_s": np.asarray(hydrograph.get("times_s") or [], dtype=np.float64),
                    "discharges_m3s": np.asarray(hydrograph.get("discharges_m3s") or [], dtype=np.float64),
                    "cvs": np.asarray(hydrograph.get("cvs") or [], dtype=np.float64),
                }
            )
        self.inflow_hydrographs = configured
        if denominator_variant:
            self.inflow_denominator_config["variant"] = str(denominator_variant).upper()
        if denominator_source is not None:
            self.inflow_denominator_config["source"] = denominator_source
        if denominator_basis is not None:
            self.inflow_denominator_config["basis"] = denominator_basis
        if denominator_direction is not None:
            self.inflow_denominator_config["direction"] = int(denominator_direction)
        if denominator_fv_value is not None:
            self.inflow_denominator_config["fv_value"] = float(denominator_fv_value)
        self.inflow_last_stage_diagnostics = {
            "configured_cell_count": len(configured),
            "inflow_denominator_variant": self.inflow_denominator_config["variant"],
            "sample_count": 0,
            "samples": [],
        }

    def _clear_precomputed_failure_schedule_taichi_fields(self) -> None:
        self.precomputed_failure_tfail_field = None
        self.precomputed_failure_gindx_field = None
        self.precomputed_failure_fdepth_field = None
        self.precomputed_failure_committed_fire_mask_field = None
        self.precomputed_failure_candidate_fire_mask_field = None
        self.precomputed_failure_source_depth_staging_field = None
        self.precomputed_failure_source_density_staging_field = None
        self._precomputed_failure_field_shape = None
        self._precomputed_failure_fast_consume_validated = False

    def _upload_precomputed_failure_schedule_to_taichi(self, expected_shape: tuple[int, int]) -> None:
        if (
            self.precomputed_failure_tfail is None
            or self.precomputed_failure_gindx is None
            or self.precomputed_failure_fdepth is None
        ):
            self.precomputed_failure_schedule_info.update(
                {
                    "dfs_source_staging_field_active": False,
                    "source_staging_field_roundtrip_ok": False,
                    "source_staging_cpu_vs_taichi_match": False,
                    "dfs_source_staging_field_fallback_reason": "PRECOMPUTED_FAILURE_SCHEDULE_NOT_CONFIGURED",
                    "rnoff_gpu_field_feed_active": False,
                    "schedule_buffer_uploaded_to_taichi": False,
                    "taichi_schedule_buffer_roundtrip_ok": False,
                    "taichi_schedule_buffer_fallback_reason": "PRECOMPUTED_FAILURE_SCHEDULE_NOT_CONFIGURED",
                }
            )
            self._clear_precomputed_failure_schedule_taichi_fields()
            return

        try:
            if (
                self._precomputed_failure_field_shape != expected_shape
                or self.precomputed_failure_tfail_field is None
                or self.precomputed_failure_gindx_field is None
                or self.precomputed_failure_fdepth_field is None
                or self.precomputed_failure_committed_fire_mask_field is None
                or self.precomputed_failure_candidate_fire_mask_field is None
                or self.precomputed_failure_source_depth_staging_field is None
                or self.precomputed_failure_source_density_staging_field is None
            ):
                self.precomputed_failure_tfail_field = ti.field(dtype=ti.f64, shape=expected_shape)
                self.precomputed_failure_gindx_field = ti.field(dtype=ti.i32, shape=expected_shape)
                self.precomputed_failure_fdepth_field = ti.field(dtype=ti.f64, shape=expected_shape)
                self.precomputed_failure_committed_fire_mask_field = ti.field(dtype=ti.i32, shape=expected_shape)
                self.precomputed_failure_candidate_fire_mask_field = ti.field(dtype=ti.i32, shape=expected_shape)
                self.precomputed_failure_source_depth_staging_field = ti.field(dtype=self.fp, shape=expected_shape)
                self.precomputed_failure_source_density_staging_field = ti.field(dtype=self.fp, shape=expected_shape)
                self._precomputed_failure_field_shape = expected_shape

            tfail_cpu = np.asarray(self.precomputed_failure_tfail, dtype=np.float64)
            gindx_cpu = np.asarray(self.precomputed_failure_gindx, dtype=np.int32)
            fdepth_cpu = np.asarray(self.precomputed_failure_fdepth, dtype=np.float64)
            zeros_i32 = np.zeros(expected_shape, dtype=np.int32)
            zeros_fp = np.zeros(expected_shape, dtype=self.numpy_float_dtype)

            self.precomputed_failure_tfail_field.from_numpy(tfail_cpu)
            self.precomputed_failure_gindx_field.from_numpy(gindx_cpu)
            self.precomputed_failure_fdepth_field.from_numpy(fdepth_cpu)
            self.precomputed_failure_committed_fire_mask_field.from_numpy(zeros_i32)
            self.precomputed_failure_candidate_fire_mask_field.from_numpy(zeros_i32)
            self.precomputed_failure_source_depth_staging_field.from_numpy(zeros_fp)
            self.precomputed_failure_source_density_staging_field.from_numpy(zeros_fp)
            self.precomputed_failure_candidate_count_field[None] = 0
            self.precomputed_failure_candidate_depth_sum_field[None] = 0.0
            self.precomputed_failure_candidate_mass_sum_field[None] = 0.0
            self._precomputed_failure_fast_consume_validated = False

            tfail_rt = self.precomputed_failure_tfail_field.to_numpy().astype(np.float64, copy=False)
            gindx_rt = self.precomputed_failure_gindx_field.to_numpy().astype(np.int32, copy=False)
            fdepth_rt = self.precomputed_failure_fdepth_field.to_numpy().astype(np.float64, copy=False)

            tfail_error = float(np.max(np.abs(tfail_rt - tfail_cpu))) if tfail_cpu.size else 0.0
            fdepth_error = float(np.max(np.abs(fdepth_rt - fdepth_cpu))) if fdepth_cpu.size else 0.0
            gindx_mismatch_count = int(np.count_nonzero(gindx_rt != gindx_cpu))
            roundtrip_ok = (
                bool(np.array_equal(tfail_rt, tfail_cpu))
                and bool(np.array_equal(gindx_rt, gindx_cpu))
                and bool(np.array_equal(fdepth_rt, fdepth_cpu))
            )
            fallback_reason = None if roundtrip_ok else "TAICHI_SCHEDULE_BUFFER_ROUNDTRIP_MISMATCH"
            self.precomputed_failure_schedule_info.update(
                {
                    "rnoff_gpu_field_feed_active": roundtrip_ok,
                    "schedule_buffer_uploaded_to_taichi": True,
                    "taichi_schedule_buffer_roundtrip_ok": roundtrip_ok,
                    "taichi_schedule_buffer_shape": list(expected_shape),
                    "taichi_schedule_buffer_dtype": {
                        "tfail": "ti.f64",
                        "gindx": "ti.i32",
                        "fdepth": "ti.f64",
                    },
                    "taichi_schedule_buffer_fallback_reason": fallback_reason,
                    "taichi_schedule_buffer_max_abs_error_tfail": tfail_error,
                    "taichi_schedule_buffer_max_abs_error_fdepth": fdepth_error,
                    "taichi_schedule_buffer_gindx_mismatch_count": gindx_mismatch_count,
                }
            )
        except Exception as exc:
            self.precomputed_failure_schedule_info.update(
                {
                    "dfs_source_staging_field_active": False,
                    "source_staging_field_roundtrip_ok": False,
                    "source_staging_cpu_vs_taichi_match": False,
                    "dfs_source_staging_field_fallback_reason": f"TAICHI_SCHEDULE_BUFFER_UPLOAD_FAILED: {exc!r}",
                    "rnoff_gpu_field_feed_active": False,
                    "schedule_buffer_uploaded_to_taichi": False,
                    "taichi_schedule_buffer_roundtrip_ok": False,
                    "taichi_schedule_buffer_shape": list(expected_shape),
                    "taichi_schedule_buffer_dtype": {
                        "tfail": "ti.f64",
                        "gindx": "ti.i32",
                        "fdepth": "ti.f64",
                    },
                    "taichi_schedule_buffer_fallback_reason": f"TAICHI_SCHEDULE_BUFFER_UPLOAD_FAILED: {exc!r}",
                    "taichi_schedule_buffer_max_abs_error_tfail": None,
                    "taichi_schedule_buffer_max_abs_error_fdepth": None,
                    "taichi_schedule_buffer_gindx_mismatch_count": None,
                }
            )
            self._clear_precomputed_failure_schedule_taichi_fields()

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
    ) -> dict[str, object]:
        """
        Configure original EDDA `unsfin -> tfail/gindx/fdepth` staging.

        This only supplies the precomputed schedule to DFS. It does not change
        the downstream equations that already consume `tempfsh/tempfsrho`.
        """
        expected_shape = (self.fields.nx, self.fields.ny)
        tfail_np = np.asarray(tfail_s, dtype=np.float64)
        gindx_np = np.asarray(gindx, dtype=np.int32)
        fdepth_np = np.asarray(fdepth_m, dtype=np.float64)
        for name, arr in {
            "tfail_s": tfail_np,
            "gindx": gindx_np,
            "fdepth_m": fdepth_np,
        }.items():
            if arr.shape != expected_shape:
                raise ValueError(f"{name} shape {arr.shape} does not match solver shape {expected_shape}.")

        active = (gindx_np > 0) & (fdepth_np > 0.0) & np.isfinite(tfail_np)
        gindx_zero_no_feed_count = int(np.count_nonzero((gindx_np <= 0) & (fdepth_np > 0.0)))
        inactive_no_feed_count = int(np.count_nonzero(~active))
        self.precomputed_failure_tfail = np.where(active, tfail_np, 0.0)
        self.precomputed_failure_gindx = np.where(active, 1, 0).astype(np.int32, copy=False)
        self.precomputed_failure_fdepth = np.where(active, fdepth_np, 0.0).astype(np.float64, copy=False)
        self.precomputed_failure_fired = np.zeros(expected_shape, dtype=bool)
        self._precomputed_failure_candidate_fired = np.zeros(expected_shape, dtype=bool)
        self._precomputed_failure_candidate_cell_count = 0
        self._precomputed_failure_candidate_depth_sum = 0.0
        self._precomputed_failure_candidate_mass_sum = 0.0
        self._precomputed_failure_candidate_window_end = None
        project_cuda_backend_stage1_enabled = _env_flag(PROJECT_CUDA_BACKEND_STAGE1_ENV) or _env_flag(
            GPU_ONLY_PRODUCTION_SMOKE_ENV
        )
        field_feed_gate_enabled = (
            _env_flag(RNOFF_GPU_FIELD_FEED_ENV)
            if taichi_field_feed_enabled is None
            else bool(taichi_field_feed_enabled)
        ) or project_cuda_backend_stage1_enabled
        source_staging_gate_enabled = (
            _env_flag(DFS_SOURCE_STAGING_FIELD_ENV)
            if source_staging_field_enabled is None
            else bool(source_staging_field_enabled)
        ) or project_cuda_backend_stage1_enabled
        fast_consume_gate_enabled = (
            _env_flag(DFS_SOURCE_STAGING_FAST_CONSUME_ENV)
            if source_staging_fast_consume_enabled is None
            else bool(source_staging_fast_consume_enabled)
        ) or project_cuda_backend_stage1_enabled
        kernel_gate_enabled = (
            _env_flag(DFS_SOURCE_STAGING_KERNEL_ENV)
            if source_staging_kernel_enabled is None
            else bool(source_staging_kernel_enabled)
        )
        computed_kernel_required_gates_active = (
            _env_flag(RNOFF_TOPOINDEX_RUNTIME_FLAG)
            and _env_flag(RNOFF_NATIVE_UNSFIN_FEED_ENV)
            and _env_flag(NATIVE_UNSFIN_RUNTIME_FEED_ENV)
            and field_feed_gate_enabled
            and source_staging_gate_enabled
            and fast_consume_gate_enabled
        )
        kernel_required_gates_active = (
            computed_kernel_required_gates_active
            if source_staging_kernel_required_gates_active is None
            else bool(source_staging_kernel_required_gates_active)
        )
        source_staging_fallback_reason = None
        if not source_staging_gate_enabled:
            source_staging_fallback_reason = "DFS_SOURCE_STAGING_FIELD_GATE_NOT_SET"
        elif not field_feed_gate_enabled:
            source_staging_fallback_reason = "RNOFF_GPU_FIELD_FEED_NOT_ACTIVE"
        kernel_fallback_reason = "DFS_SOURCE_STAGING_KERNEL_GATE_NOT_SET"
        if kernel_gate_enabled:
            if not kernel_required_gates_active:
                kernel_fallback_reason = "DFS_SOURCE_STAGING_KERNEL_REQUIRED_GATES_NOT_ACTIVE"
            elif source_staging_fallback_reason is not None:
                kernel_fallback_reason = source_staging_fallback_reason
            else:
                kernel_fallback_reason = "SOURCE_STAGING_FAST_CONSUME_NOT_VALIDATED"
        schedule_configure_count = int(self.precomputed_failure_schedule_info.get("schedule_configure_count", 0) or 0) + 1
        self.precomputed_failure_schedule_info = {
            "configured": True,
            "scheduled_cell_count": int(np.count_nonzero(active)),
            "gindx_zero_no_feed_count": gindx_zero_no_feed_count,
            "inactive_no_feed_count": inactive_no_feed_count,
            "fired_cell_count": 0,
            "candidate_fired_count": 0,
            "committed_fired_count": 0,
            "duplicate_fire_count": 0,
            "rejected_step_discard_count": 0,
            "total_staged_cell_count": 0,
            "total_staged_depth_sum": 0.0,
            "total_staged_mass_sum": 0.0,
            "crossing_count_by_checkpoint": {},
            "last_staged_cell_count": 0,
            "last_staged_depth_sum": 0.0,
            "last_staged_mass_sum": 0.0,
            "last_window_start_s": None,
            "last_window_end_s": None,
            "dfs_source_staging_field_gate_enabled": source_staging_gate_enabled,
            "dfs_source_staging_field_active": False,
            "source_staging_field_roundtrip_ok": None,
            "source_staging_cpu_vs_taichi_match": None,
            "dfs_source_staging_field_fallback_reason": source_staging_fallback_reason,
            "source_staging_depth_max_abs_error": None,
            "source_staging_density_max_abs_error": None,
            "source_staging_candidate_mask_mismatch_count": None,
            "dfs_source_staging_fast_consume_gate_enabled": fast_consume_gate_enabled,
            "dfs_source_staging_fast_consume_active": False,
            "parity_validation_mode": "per_stage" if source_staging_gate_enabled else "cpu",
            "parity_validation_once_per_configure": False,
            "per_stage_parity_download_disabled": False,
            "source_staging_device_consumed": False,
            "cpu_fallback_active": False,
            "transfer_bytes_h2d": 0,
            "transfer_bytes_d2h": 0,
            "parity_download_count": 0,
            "schedule_configure_count": schedule_configure_count,
            "candidate_stage_count": 0,
            "project_cuda_backend_stage1_gate_enabled": project_cuda_backend_stage1_enabled,
            "project_cuda_backend_stage1_active": False,
            "cuda_backend_stage1_active": False,
            "dfs_source_staging_kernel_gate_enabled": kernel_gate_enabled,
            "dfs_source_staging_kernel_required_gates_active": kernel_required_gates_active,
            "dfs_source_staging_kernel_active": False,
            "source_staging_kernel_vs_cpu_match": None,
            "kernel_fallback_active": bool(kernel_gate_enabled and kernel_fallback_reason is not None),
            "kernel_fallback_reason": kernel_fallback_reason,
            "kernel_candidate_stage_count": 0,
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": 0,
            "schedule_consumed_by_dfs": int(np.count_nonzero(active)) > 0,
            "final_state_mutated": int(np.count_nonzero(active)) > 0,
            "rnoff_gpu_field_feed_gate_enabled": field_feed_gate_enabled,
            "rnoff_gpu_field_feed_active": False,
            "schedule_buffer_uploaded_to_taichi": False,
            "taichi_schedule_buffer_roundtrip_ok": None,
            "taichi_schedule_buffer_shape": None,
            "taichi_schedule_buffer_dtype": None,
            "taichi_schedule_buffer_fallback_reason": None,
            "taichi_schedule_buffer_max_abs_error_tfail": None,
            "taichi_schedule_buffer_max_abs_error_fdepth": None,
            "taichi_schedule_buffer_gindx_mismatch_count": None,
        }
        if field_feed_gate_enabled:
            self._upload_precomputed_failure_schedule_to_taichi(expected_shape)
            schedule_bytes = int(np.asarray(self.precomputed_failure_tfail).nbytes) + int(
                np.asarray(self.precomputed_failure_gindx).nbytes
            ) + int(np.asarray(self.precomputed_failure_fdepth).nbytes)
            self.precomputed_failure_schedule_info["transfer_bytes_h2d"] = schedule_bytes
            if source_staging_gate_enabled:
                if self.precomputed_failure_schedule_info.get("rnoff_gpu_field_feed_active") is True:
                    self.precomputed_failure_schedule_info.update(
                        {
                            "dfs_source_staging_field_active": True,
                            "parity_validation_mode": (
                                "first_stage_then_fast_consume" if fast_consume_gate_enabled else "per_stage"
                            ),
                            "parity_validation_once_per_configure": bool(fast_consume_gate_enabled),
                            "dfs_source_staging_field_fallback_reason": None,
                            "kernel_fallback_reason": (
                                "SOURCE_STAGING_FAST_CONSUME_NOT_VALIDATED"
                                if kernel_gate_enabled and kernel_required_gates_active and fast_consume_gate_enabled
                                else self.precomputed_failure_schedule_info.get("kernel_fallback_reason")
                            ),
                        }
                    )
                else:
                    self.precomputed_failure_schedule_info.update(
                        {
                            "dfs_source_staging_field_active": False,
                            "dfs_source_staging_field_fallback_reason": (
                                self.precomputed_failure_schedule_info.get("taichi_schedule_buffer_fallback_reason")
                                or "RNOFF_GPU_FIELD_FEED_NOT_ACTIVE"
                            ),
                            "dfs_source_staging_kernel_active": False,
                            "kernel_fallback_active": bool(kernel_gate_enabled),
                            "kernel_fallback_reason": (
                                self.precomputed_failure_schedule_info.get("taichi_schedule_buffer_fallback_reason")
                                or "RNOFF_GPU_FIELD_FEED_NOT_ACTIVE"
                            ),
                        }
                    )
            else:
                self.precomputed_failure_schedule_info.update(
                    {
                        "dfs_source_staging_field_active": False,
                        "dfs_source_staging_field_fallback_reason": "DFS_SOURCE_STAGING_FIELD_GATE_NOT_SET",
                        "dfs_source_staging_kernel_active": False,
                        "kernel_fallback_active": bool(kernel_gate_enabled),
                        "kernel_fallback_reason": "DFS_SOURCE_STAGING_FIELD_GATE_NOT_SET",
                    }
                )
        else:
            self._clear_precomputed_failure_schedule_taichi_fields()
        project_cuda_backend_stage1_active = (
            project_cuda_backend_stage1_enabled
            and bool(self.precomputed_failure_schedule_info.get("rnoff_gpu_field_feed_active", False))
            and bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_field_active", False))
            and bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_fast_consume_gate_enabled", False))
        )
        self.precomputed_failure_schedule_info.update(
            {
                "project_cuda_backend_stage1_active": project_cuda_backend_stage1_active,
                "cuda_backend_stage1_active": project_cuda_backend_stage1_active,
            }
        )
        return dict(self.precomputed_failure_schedule_info)

    def get_precomputed_failure_schedule_diagnostics(self) -> dict[str, object]:
        return dict(self.precomputed_failure_schedule_info)

    def _default_face_flux_kernel_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_face_flux_kernel_gate_enabled:
            fallback_reason = "DFS_FACE_FLUX_KERNEL_GATE_NOT_SET"
        return {
            "dfs_face_flux_kernel_gate_enabled": bool(self.dfs_face_flux_kernel_gate_enabled),
            "dfs_face_flux_kernel_active": False,
            "dfs_face_flux_kernel_mode": "diagnostic_mirror",
            "face_flux_candidate_subset": None,
            "face_flux_full_formula_recomputed": False,
            "face_flux_valid_mask_recomputed": False,
            "face_flux_opposite_mirror_recomputed": False,
            "face_flux_cpu_vs_kernel_match": None,
            "face_flux_kernel_fallback_active": False,
            "face_flux_kernel_fallback_reason": fallback_reason,
            "face_flux_compared_count": 0,
            "face_flux_max_abs_error": None,
            "face_flux_mismatch_count": 0,
            "face_flux_fv_pred_mismatch_count": 0,
            "face_flux_qq_mismatch_count": 0,
            "face_flux_qqmass_mismatch_count": 0,
            "face_flux_mask_mismatch_count": 0,
            "face_flux_kernel_h2d_bytes": 0,
            "face_flux_kernel_d2h_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_face_flux_kernel_diagnostics(self) -> dict[str, object]:
        return dict(self.face_flux_kernel_info)

    def _default_qnet_qmassnet_kernel_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_qnet_qmassnet_kernel_gate_enabled:
            fallback_reason = "DFS_QNET_QMASSNET_KERNEL_GATE_NOT_SET"
        return {
            "dfs_qnet_qmassnet_kernel_gate_enabled": bool(self.dfs_qnet_qmassnet_kernel_gate_enabled),
            "dfs_qnet_qmassnet_kernel_active": False,
            "dfs_qnet_qmassnet_kernel_mode": "diagnostic_accumulation",
            "qnet_qmassnet_cpu_vs_kernel_match": None,
            "qnet_qmassnet_kernel_fallback_active": False,
            "qnet_qmassnet_kernel_fallback_reason": fallback_reason,
            "qnet_qmassnet_compared_cell_count": 0,
            "qnet_qmassnet_active_cell_count": 0,
            "qnet_qmassnet_compared_face_count": 0,
            "qnet_qmassnet_max_abs_error_qnet": None,
            "qnet_qmassnet_max_abs_error_qmassnet": None,
            "qnet_qmassnet_mismatch_count": 0,
            "qnet_qmassnet_qnet_mismatch_count": 0,
            "qnet_qmassnet_qmassnet_mismatch_count": 0,
            "qnet_qmassnet_cell_mask_mismatch_count": 0,
            "qnet_qmassnet_kernel_h2d_bytes": 0,
            "qnet_qmassnet_kernel_d2h_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_qnet_qmassnet_kernel_diagnostics(self) -> dict[str, object]:
        return dict(self.qnet_qmassnet_kernel_info)

    def _default_erosion_deposition_kernel_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled:
            fallback_reason = "DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_GATE_NOT_SET"
        return {
            "dfs_erosion_deposition_diagnostic_kernel_gate_enabled": bool(
                self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled
            ),
            "dfs_erosion_deposition_diagnostic_kernel_active": False,
            "dfs_erosion_deposition_diagnostic_kernel_mode": "diagnostic_bookkeeping_mirror",
            "project_cuda_backend_stage2_gate_enabled": bool(self.project_cuda_backend_stage2_gate_enabled),
            "project_cuda_backend_stage2_active": False,
            "cuda_backend_stage2_component": "erosion_deposition_rate_diagnostic",
            "erosion_deposition_cpu_vs_kernel_match": None,
            "erosion_deposition_kernel_fallback_active": False,
            "erosion_deposition_kernel_fallback_reason": fallback_reason,
            "erosion_deposition_compared_cell_count": 0,
            "erosion_deposition_cell_mask_mismatch_count": 0,
            "erosion_deposition_mismatch_count": 0,
            "erorate_mismatch_count": 0,
            "deporate_mismatch_count": 0,
            "erosion_depth_delta_mismatch_count": 0,
            "deposition_depth_delta_mismatch_count": 0,
            "source_depth_rate_mismatch_count": 0,
            "z_bed_candidate_mismatch_count": 0,
            "max_abs_error_erorate": None,
            "max_abs_error_deporate": None,
            "max_abs_error_erosion_depth_delta": None,
            "max_abs_error_deposition_depth_delta": None,
            "max_abs_error_source_depth_rate": None,
            "max_abs_error_z_bed_candidate": None,
            "scratch_buffer_names": [] if not self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled else [
                "erorate_diag_kernel",
                "deporate_diag_kernel",
                "erosion_depth_diag_kernel",
                "deposition_depth_diag_kernel",
                "erosion_deposition_diag_cell_mask",
                "source_depth_rate_diag_kernel",
                "z_bed_candidate_diag_kernel",
            ],
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": 0,
            "diagnostic_abs_tolerance": 1.0e-12,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_erosion_deposition_kernel_diagnostics(self) -> dict[str, object]:
        return dict(self.erosion_deposition_kernel_info)

    def _default_erosion_deposition_deep_state_kernel_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled:
            fallback_reason = "DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_GATE_NOT_SET"
        return {
            "dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled": bool(
                self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            ),
            "dfs_erosion_deposition_deep_state_diagnostic_kernel_active": False,
            "dfs_erosion_deposition_deep_state_diagnostic_kernel_mode": "diagnostic_deep_state_bookkeeping_mirror",
            "project_cuda_backend_stage2_gate_enabled": bool(self.project_cuda_backend_stage2_gate_enabled),
            "project_cuda_backend_stage2_active": False,
            "cuda_backend_stage2_component": "erosion_deposition_deep_state_diagnostic",
            "deep_state_cpu_vs_kernel_match": None,
            "deep_state_kernel_fallback_active": False,
            "deep_state_kernel_fallback_reason": fallback_reason,
            "deep_state_compared_cell_count": 0,
            "deep_state_cell_mask_mismatch_count": 0,
            "deep_state_mismatch_count": 0,
            "erosion_depth_delta_mismatch_count": 0,
            "deposition_depth_delta_mismatch_count": 0,
            "source_depth_rate_mismatch_count": 0,
            "z_bed_candidate_mismatch_count": 0,
            "erosion_depth_candidate_mismatch_count": 0,
            "deposition_depth_candidate_mismatch_count": 0,
            "max_abs_error_erosion_depth_delta": None,
            "max_abs_error_deposition_depth_delta": None,
            "max_abs_error_source_depth_rate": None,
            "max_abs_error_z_bed_candidate": None,
            "max_abs_error_erosion_depth_candidate": None,
            "max_abs_error_deposition_depth_candidate": None,
            "scratch_buffer_names": []
            if not self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            else [
                "erosion_depth_delta_diag_kernel",
                "deposition_depth_delta_diag_kernel",
                "source_depth_rate_diag_kernel",
                "z_bed_candidate_diag_kernel",
                "erosion_depth_candidate_diag_kernel",
                "deposition_depth_candidate_diag_kernel",
                "deep_state_diag_cell_mask",
            ],
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": 0,
            "diagnostic_abs_tolerance": 1.0e-12,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_erosion_deposition_deep_state_kernel_diagnostics(self) -> dict[str, object]:
        return dict(self.erosion_deposition_deep_state_kernel_info)

    def _default_erosion_deposition_mutation_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_erosion_deposition_mutate_gate_enabled:
            fallback_reason = "DFS_EROSION_DEPOSITION_MUTATE_GATE_NOT_SET"
        return {
            "dfs_erosion_deposition_mutation_gate_enabled": bool(
                self.dfs_erosion_deposition_mutate_gate_enabled
            ),
            "dfs_erosion_deposition_mutation_active": False,
            "dfs_erosion_deposition_mutation_mode": "validated_writeback",
            "project_cuda_backend_stage2_gate_enabled": bool(self.project_cuda_backend_stage2_gate_enabled),
            "project_cuda_backend_stage2_active": False,
            "cuda_backend_stage2_component": "erosion_deposition_rate_validated_writeback",
            "erosion_deposition_mutation_cpu_vs_kernel_match": None,
            "erosion_deposition_mutation_fallback_active": False,
            "erosion_deposition_mutation_fallback_reason": fallback_reason,
            "erosion_deposition_mutation_candidate_prepared": False,
            "erosion_deposition_mutation_compared_cell_count": 0,
            "erosion_deposition_mutation_writeback_count": 0,
            "erosion_deposition_mutation_mismatch_count": 0,
            "erorate_mutation_mismatch_count": 0,
            "deporate_mutation_mismatch_count": 0,
            "erosion_deposition_mutation_cell_mask_mismatch_count": 0,
            "erorate_mutation_max_abs_error": 0.0,
            "deporate_mutation_max_abs_error": 0.0,
            "erosion_deposition_mutation_abs_tolerance": 1.0e-12,
            "erosion_deposition_mutation_d2h_bytes": 0,
            "erosion_deposition_mutation_h2d_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_erosion_deposition_mutation_diagnostics(self) -> dict[str, object]:
        return dict(self.erosion_deposition_mutation_info)

    def _run_qnet_qmassnet_kernel_diagnostic_if_enabled(self) -> None:
        self.qnet_qmassnet_kernel_info = self._default_qnet_qmassnet_kernel_info()
        if not self.dfs_qnet_qmassnet_kernel_gate_enabled:
            return

        self._diagnostic_qnet_qmassnet_accumulation_kernel()
        qnet_cpu = np.asarray(self.fields.qnet_fortran.to_numpy())
        qmassnet_cpu = np.asarray(self.fields.qmassnet_fortran.to_numpy())
        cell_id = np.asarray(self.fields.cell_id.to_numpy())
        nodata = np.asarray(self.fields.is_nodata.to_numpy()).astype(bool)
        expected_cell_mask = ((cell_id > 0) & (~nodata)).astype(np.int32)
        valid_face_mask = ((cell_id[:, :, None] > 0) & (np.asarray(self.fields.flow_neighbor_id.to_numpy()) > 0)).astype(bool)
        qnet_kernel = np.asarray(self.qnet_diag_kernel.to_numpy())
        qmassnet_kernel = np.asarray(self.qmassnet_diag_kernel.to_numpy())
        cell_mask_kernel = np.asarray(self.qnet_qmassnet_diag_cell_mask.to_numpy())

        cell_mask_mismatch_count = int(np.count_nonzero(cell_mask_kernel != expected_cell_mask))
        compare_mask = expected_cell_mask.astype(bool)
        compared_cell_count = int(np.count_nonzero(compare_mask))
        compared_face_count = int(np.count_nonzero(valid_face_mask))
        max_abs_error_qnet = 0.0
        max_abs_error_qmassnet = 0.0
        qnet_mismatch_count = 0
        qmassnet_mismatch_count = 0
        if compared_cell_count:
            qnet_errors = np.abs(qnet_kernel[compare_mask] - qnet_cpu[compare_mask])
            qmassnet_errors = np.abs(qmassnet_kernel[compare_mask] - qmassnet_cpu[compare_mask])
            max_abs_error_qnet = float(qnet_errors.max(initial=0.0))
            max_abs_error_qmassnet = float(qmassnet_errors.max(initial=0.0))
            qnet_mismatch_count = int(np.count_nonzero(qnet_errors > 0.0))
            qmassnet_mismatch_count = int(np.count_nonzero(qmassnet_errors > 0.0))

        mismatch_count = qnet_mismatch_count + qmassnet_mismatch_count
        matched = mismatch_count == 0 and cell_mask_mismatch_count == 0
        self.qnet_qmassnet_kernel_info = {
            "dfs_qnet_qmassnet_kernel_gate_enabled": True,
            "dfs_qnet_qmassnet_kernel_active": bool(matched),
            "dfs_qnet_qmassnet_kernel_mode": "diagnostic_accumulation",
            "qnet_qmassnet_cpu_vs_kernel_match": bool(matched),
            "qnet_qmassnet_kernel_fallback_active": not matched,
            "qnet_qmassnet_kernel_fallback_reason": None if matched else "QNET_QMASSNET_DIAGNOSTIC_KERNEL_MISMATCH",
            "qnet_qmassnet_compared_cell_count": compared_cell_count,
            "qnet_qmassnet_active_cell_count": compared_cell_count,
            "qnet_qmassnet_compared_face_count": compared_face_count,
            "qnet_qmassnet_max_abs_error_qnet": max_abs_error_qnet,
            "qnet_qmassnet_max_abs_error_qmassnet": max_abs_error_qmassnet,
            "qnet_qmassnet_mismatch_count": mismatch_count,
            "qnet_qmassnet_qnet_mismatch_count": qnet_mismatch_count,
            "qnet_qmassnet_qmassnet_mismatch_count": qmassnet_mismatch_count,
            "qnet_qmassnet_cell_mask_mismatch_count": cell_mask_mismatch_count,
            "qnet_qmassnet_kernel_h2d_bytes": 0,
            "qnet_qmassnet_kernel_d2h_bytes": int(
                qnet_kernel.nbytes + qmassnet_kernel.nbytes + cell_mask_kernel.nbytes
            ),
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    @ti.kernel
    def _diagnostic_qnet_qmassnet_accumulation_kernel(self):
        for i, j in self.fields.h:
            self.qnet_diag_kernel[i, j] = 0.0
            self.qmassnet_diag_kernel[i, j] = 0.0
            self.qnet_qmassnet_diag_cell_mask[i, j] = 0
            if not self.fields.is_nodata[i, j] and self.fields.cell_id[i, j] > 0:
                qnet = 0.0
                qmassnet = 0.0
                for d in ti.static(range(8)):
                    qnet -= self.fields.qq_fortran[i, j, d]
                    qmassnet -= self.fields.qqmass_fortran[i, j, d]
                self.qnet_diag_kernel[i, j] = qnet
                self.qmassnet_diag_kernel[i, j] = qmassnet
                self.qnet_qmassnet_diag_cell_mask[i, j] = 1

    def _run_erosion_deposition_kernel_diagnostic_if_enabled(self, dt: float) -> None:
        self.erosion_deposition_kernel_info = self._default_erosion_deposition_kernel_info()
        self.erosion_deposition_deep_state_kernel_info = (
            self._default_erosion_deposition_deep_state_kernel_info()
        )
        candidate_required = (
            self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled
            or self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            or self.dfs_erosion_deposition_mutate_gate_enabled
        )
        if not candidate_required:
            return
        if (
            self.erorate_diag_kernel is None
            or self.deporate_diag_kernel is None
            or self.erosion_depth_diag_kernel is None
            or self.deposition_depth_diag_kernel is None
            or self.erosion_deposition_diag_cell_mask is None
            or self.source_depth_rate_diag_kernel is None
            or self.z_bed_candidate_diag_kernel is None
            or self.erosion_depth_delta_diag_kernel is None
            or self.deposition_depth_delta_diag_kernel is None
            or self.erosion_depth_candidate_diag_kernel is None
            or self.deposition_depth_candidate_diag_kernel is None
            or self.deep_state_diag_cell_mask is None
        ):
            self.erosion_deposition_kernel_info.update(
                {
                    "erosion_deposition_kernel_fallback_active": True,
                    "erosion_deposition_kernel_fallback_reason": "EROSION_DEPOSITION_DIAGNOSTIC_BUFFERS_NOT_ALLOCATED",
                }
            )
            if self.dfs_erosion_deposition_mutate_gate_enabled:
                self.erosion_deposition_mutation_info.update(
                    {
                        "erosion_deposition_mutation_fallback_active": True,
                        "erosion_deposition_mutation_fallback_reason": "EROSION_DEPOSITION_DIAGNOSTIC_BUFFERS_NOT_ALLOCATED",
                    }
                )
            if self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled:
                self.erosion_deposition_deep_state_kernel_info.update(
                    {
                        "deep_state_kernel_fallback_active": True,
                        "deep_state_kernel_fallback_reason": "EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_BUFFERS_NOT_ALLOCATED",
                    }
                )
            return

        self._diagnostic_erosion_deposition_bookkeeping_kernel(float(dt))
        active_mask = ~np.asarray(self.fields.is_nodata.to_numpy(), dtype=bool)
        erorate_cpu = np.asarray(self.fields.erosion_rate.to_numpy(), dtype=np.float64)
        deporate_cpu = np.asarray(self.fields.deposition_rate.to_numpy(), dtype=np.float64)
        erosion_depth_delta_cpu = erorate_cpu * float(dt)
        deposition_depth_delta_cpu = np.abs(deporate_cpu) * float(dt)
        source_depth_rate_cpu = np.asarray(self.fields.tempfsh_flow.to_numpy(), dtype=np.float64) / float(dt)
        source_depth_rate_cpu = source_depth_rate_cpu + erorate_cpu + deporate_cpu
        z_bed_candidate_cpu = np.asarray(self.fields.tempele.to_numpy(), dtype=np.float64)
        erosion_depth_candidate_cpu = (
            np.asarray(self.fields.erosion_depth.to_numpy(), dtype=np.float64) + erosion_depth_delta_cpu
        )
        deposition_depth_candidate_cpu = (
            np.asarray(self.fields.deposition_depth.to_numpy(), dtype=np.float64) + deposition_depth_delta_cpu
        )

        erorate_kernel = np.asarray(self.erorate_diag_kernel.to_numpy(), dtype=np.float64)
        deporate_kernel = np.asarray(self.deporate_diag_kernel.to_numpy(), dtype=np.float64)
        erosion_depth_kernel = np.asarray(self.erosion_depth_diag_kernel.to_numpy(), dtype=np.float64)
        deposition_depth_kernel = np.asarray(self.deposition_depth_diag_kernel.to_numpy(), dtype=np.float64)
        source_depth_rate_kernel = np.asarray(self.source_depth_rate_diag_kernel.to_numpy(), dtype=np.float64)
        z_bed_candidate_kernel = np.asarray(self.z_bed_candidate_diag_kernel.to_numpy(), dtype=np.float64)
        mask_kernel = np.asarray(self.erosion_deposition_diag_cell_mask.to_numpy(), dtype=np.int32)
        erosion_depth_delta_kernel = np.asarray(self.erosion_depth_delta_diag_kernel.to_numpy(), dtype=np.float64)
        deposition_depth_delta_kernel = np.asarray(
            self.deposition_depth_delta_diag_kernel.to_numpy(), dtype=np.float64
        )
        erosion_depth_candidate_kernel = np.asarray(
            self.erosion_depth_candidate_diag_kernel.to_numpy(), dtype=np.float64
        )
        deposition_depth_candidate_kernel = np.asarray(
            self.deposition_depth_candidate_diag_kernel.to_numpy(), dtype=np.float64
        )
        deep_mask_kernel = np.asarray(self.deep_state_diag_cell_mask.to_numpy(), dtype=np.int32)
        expected_mask = active_mask.astype(np.int32)
        compare_mask = active_mask

        diagnostic_abs_tolerance = 1.0e-12

        def _errors(kernel: np.ndarray, cpu: np.ndarray) -> tuple[float, int]:
            if not np.any(compare_mask):
                return 0.0, 0
            err = np.abs(kernel[compare_mask] - cpu[compare_mask])
            return float(err.max(initial=0.0)), int(np.count_nonzero(err > diagnostic_abs_tolerance))

        erorate_max, erorate_mismatch = _errors(erorate_kernel, erorate_cpu)
        deporate_max, deporate_mismatch = _errors(deporate_kernel, deporate_cpu)
        erosion_depth_max, erosion_depth_mismatch = _errors(erosion_depth_kernel, erosion_depth_delta_cpu)
        deposition_depth_max, deposition_depth_mismatch = _errors(deposition_depth_kernel, deposition_depth_delta_cpu)
        source_depth_max, source_depth_mismatch = _errors(source_depth_rate_kernel, source_depth_rate_cpu)
        z_bed_max, z_bed_mismatch = _errors(z_bed_candidate_kernel, z_bed_candidate_cpu)
        deep_erosion_delta_max, deep_erosion_delta_mismatch = _errors(
            erosion_depth_delta_kernel, erosion_depth_delta_cpu
        )
        deep_deposition_delta_max, deep_deposition_delta_mismatch = _errors(
            deposition_depth_delta_kernel, deposition_depth_delta_cpu
        )
        deep_source_depth_max, deep_source_depth_mismatch = _errors(
            source_depth_rate_kernel, source_depth_rate_cpu
        )
        deep_z_bed_max, deep_z_bed_mismatch = _errors(z_bed_candidate_kernel, z_bed_candidate_cpu)
        erosion_depth_candidate_max, erosion_depth_candidate_mismatch = _errors(
            erosion_depth_candidate_kernel, erosion_depth_candidate_cpu
        )
        deposition_depth_candidate_max, deposition_depth_candidate_mismatch = _errors(
            deposition_depth_candidate_kernel, deposition_depth_candidate_cpu
        )
        mask_mismatch = int(np.count_nonzero(mask_kernel != expected_mask))
        deep_mask_mismatch = int(np.count_nonzero(deep_mask_kernel != expected_mask))
        mismatch_count = (
            erorate_mismatch
            + deporate_mismatch
            + erosion_depth_mismatch
            + deposition_depth_mismatch
            + source_depth_mismatch
            + z_bed_mismatch
        )
        matched = mismatch_count == 0 and mask_mismatch == 0
        deep_mismatch_count = (
            deep_erosion_delta_mismatch
            + deep_deposition_delta_mismatch
            + deep_source_depth_mismatch
            + deep_z_bed_mismatch
            + erosion_depth_candidate_mismatch
            + deposition_depth_candidate_mismatch
        )
        deep_matched = deep_mismatch_count == 0 and deep_mask_mismatch == 0
        self.erosion_deposition_kernel_info = {
            "dfs_erosion_deposition_diagnostic_kernel_gate_enabled": bool(
                self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled
            ),
            "dfs_erosion_deposition_diagnostic_kernel_active": bool(
                matched and self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled
            ),
            "dfs_erosion_deposition_diagnostic_kernel_mode": "diagnostic_bookkeeping_mirror",
            "project_cuda_backend_stage2_gate_enabled": bool(self.project_cuda_backend_stage2_gate_enabled),
            "project_cuda_backend_stage2_active": bool(
                self.project_cuda_backend_stage2_gate_enabled
                and matched
                and self.dfs_erosion_deposition_diagnostic_kernel_gate_enabled
            ),
            "cuda_backend_stage2_component": "erosion_deposition_rate_diagnostic",
            "erosion_deposition_cpu_vs_kernel_match": bool(matched),
            "erosion_deposition_kernel_fallback_active": not matched,
            "erosion_deposition_kernel_fallback_reason": None
            if matched
            else "EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_MISMATCH",
            "erosion_deposition_compared_cell_count": int(np.count_nonzero(compare_mask)),
            "erosion_deposition_cell_mask_mismatch_count": mask_mismatch,
            "erosion_deposition_mismatch_count": mismatch_count,
            "erorate_mismatch_count": erorate_mismatch,
            "deporate_mismatch_count": deporate_mismatch,
            "erosion_depth_delta_mismatch_count": erosion_depth_mismatch,
            "deposition_depth_delta_mismatch_count": deposition_depth_mismatch,
            "source_depth_rate_mismatch_count": source_depth_mismatch,
            "z_bed_candidate_mismatch_count": z_bed_mismatch,
            "max_abs_error_erorate": erorate_max,
            "max_abs_error_deporate": deporate_max,
            "max_abs_error_erosion_depth_delta": erosion_depth_max,
            "max_abs_error_deposition_depth_delta": deposition_depth_max,
            "max_abs_error_source_depth_rate": source_depth_max,
            "max_abs_error_z_bed_candidate": z_bed_max,
            "scratch_buffer_names": [
                "erorate_diag_kernel",
                "deporate_diag_kernel",
                "erosion_depth_diag_kernel",
                "deposition_depth_diag_kernel",
                "erosion_deposition_diag_cell_mask",
                "source_depth_rate_diag_kernel",
                "z_bed_candidate_diag_kernel",
            ],
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": int(
                erorate_kernel.nbytes
                + deporate_kernel.nbytes
                + erosion_depth_kernel.nbytes
                + deposition_depth_kernel.nbytes
                + source_depth_rate_kernel.nbytes
                + z_bed_candidate_kernel.nbytes
                + mask_kernel.nbytes
            ),
            "diagnostic_abs_tolerance": diagnostic_abs_tolerance,
            "final_state_mutated": False,
            "changed_field_names": [],
        }
        self.erosion_deposition_deep_state_kernel_info = {
            "dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled": bool(
                self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            ),
            "dfs_erosion_deposition_deep_state_diagnostic_kernel_active": bool(
                deep_matched and self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            ),
            "dfs_erosion_deposition_deep_state_diagnostic_kernel_mode": "diagnostic_deep_state_bookkeeping_mirror",
            "project_cuda_backend_stage2_gate_enabled": bool(self.project_cuda_backend_stage2_gate_enabled),
            "project_cuda_backend_stage2_active": bool(
                self.project_cuda_backend_stage2_gate_enabled
                and deep_matched
                and self.dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled
            ),
            "cuda_backend_stage2_component": "erosion_deposition_deep_state_diagnostic",
            "deep_state_cpu_vs_kernel_match": bool(deep_matched),
            "deep_state_kernel_fallback_active": not deep_matched,
            "deep_state_kernel_fallback_reason": None
            if deep_matched
            else "EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_MISMATCH",
            "deep_state_compared_cell_count": int(np.count_nonzero(compare_mask)),
            "deep_state_cell_mask_mismatch_count": deep_mask_mismatch,
            "deep_state_mismatch_count": deep_mismatch_count,
            "erosion_depth_delta_mismatch_count": deep_erosion_delta_mismatch,
            "deposition_depth_delta_mismatch_count": deep_deposition_delta_mismatch,
            "source_depth_rate_mismatch_count": deep_source_depth_mismatch,
            "z_bed_candidate_mismatch_count": deep_z_bed_mismatch,
            "erosion_depth_candidate_mismatch_count": erosion_depth_candidate_mismatch,
            "deposition_depth_candidate_mismatch_count": deposition_depth_candidate_mismatch,
            "max_abs_error_erosion_depth_delta": deep_erosion_delta_max,
            "max_abs_error_deposition_depth_delta": deep_deposition_delta_max,
            "max_abs_error_source_depth_rate": deep_source_depth_max,
            "max_abs_error_z_bed_candidate": deep_z_bed_max,
            "max_abs_error_erosion_depth_candidate": erosion_depth_candidate_max,
            "max_abs_error_deposition_depth_candidate": deposition_depth_candidate_max,
            "scratch_buffer_names": [
                "erosion_depth_delta_diag_kernel",
                "deposition_depth_delta_diag_kernel",
                "source_depth_rate_diag_kernel",
                "z_bed_candidate_diag_kernel",
                "erosion_depth_candidate_diag_kernel",
                "deposition_depth_candidate_diag_kernel",
                "deep_state_diag_cell_mask",
            ],
            "kernel_h2d_bytes": 0,
            "kernel_d2h_bytes": int(
                erosion_depth_delta_kernel.nbytes
                + deposition_depth_delta_kernel.nbytes
                + source_depth_rate_kernel.nbytes
                + z_bed_candidate_kernel.nbytes
                + erosion_depth_candidate_kernel.nbytes
                + deposition_depth_candidate_kernel.nbytes
                + deep_mask_kernel.nbytes
            ),
            "diagnostic_abs_tolerance": diagnostic_abs_tolerance,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def _run_erosion_deposition_mutation_if_enabled(self) -> None:
        self.erosion_deposition_mutation_info = self._default_erosion_deposition_mutation_info()
        if not self.dfs_erosion_deposition_mutate_gate_enabled:
            return
        if (
            self.erorate_diag_kernel is None
            or self.deporate_diag_kernel is None
            or self.erosion_deposition_diag_cell_mask is None
        ):
            self.erosion_deposition_mutation_info.update(
                {
                    "erosion_deposition_mutation_fallback_active": True,
                    "erosion_deposition_mutation_fallback_reason": "EROSION_DEPOSITION_DIAGNOSTIC_BUFFERS_NOT_ALLOCATED",
                }
            )
            return

        candidate_match = self.erosion_deposition_kernel_info.get("erosion_deposition_cpu_vs_kernel_match")
        if candidate_match is None:
            self.erosion_deposition_mutation_info.update(
                {
                    "erosion_deposition_mutation_fallback_active": True,
                    "erosion_deposition_mutation_fallback_reason": "EROSION_DEPOSITION_MUTATION_CANDIDATE_NOT_PREPARED",
                }
            )
            return

        tolerance = float(self.erosion_deposition_mutation_info["erosion_deposition_mutation_abs_tolerance"])
        active_mask = ~np.asarray(self.fields.is_nodata.to_numpy(), dtype=bool)
        erorate_cpu = np.asarray(self.fields.erosion_rate.to_numpy(), dtype=np.float64)
        deporate_cpu = np.asarray(self.fields.deposition_rate.to_numpy(), dtype=np.float64)
        erorate_kernel = np.asarray(self.erorate_diag_kernel.to_numpy(), dtype=np.float64)
        deporate_kernel = np.asarray(self.deporate_diag_kernel.to_numpy(), dtype=np.float64)
        mask_kernel = np.asarray(self.erosion_deposition_diag_cell_mask.to_numpy(), dtype=np.int32)
        expected_mask = active_mask.astype(np.int32)
        compared_cells = int(np.count_nonzero(active_mask))
        mask_mismatch = int(np.count_nonzero(mask_kernel != expected_mask))

        erorate_max = 0.0
        deporate_max = 0.0
        erorate_mismatch = 0
        deporate_mismatch = 0
        if compared_cells:
            erorate_errors = np.abs(erorate_kernel[active_mask] - erorate_cpu[active_mask])
            deporate_errors = np.abs(deporate_kernel[active_mask] - deporate_cpu[active_mask])
            erorate_max = float(erorate_errors.max(initial=0.0))
            deporate_max = float(deporate_errors.max(initial=0.0))
            erorate_mismatch = int(np.count_nonzero(erorate_errors > tolerance))
            deporate_mismatch = int(np.count_nonzero(deporate_errors > tolerance))

        mismatch_count = erorate_mismatch + deporate_mismatch + mask_mismatch
        matched = mismatch_count == 0
        if matched:
            self._write_erosion_deposition_mutation_kernel()

        self.erosion_deposition_mutation_info = {
            "dfs_erosion_deposition_mutation_gate_enabled": True,
            "dfs_erosion_deposition_mutation_active": bool(matched),
            "dfs_erosion_deposition_mutation_mode": "validated_writeback",
            "project_cuda_backend_stage2_gate_enabled": bool(self.project_cuda_backend_stage2_gate_enabled),
            "project_cuda_backend_stage2_active": bool(self.project_cuda_backend_stage2_gate_enabled and matched),
            "cuda_backend_stage2_component": "erosion_deposition_rate_validated_writeback",
            "erosion_deposition_mutation_cpu_vs_kernel_match": bool(matched),
            "erosion_deposition_mutation_fallback_active": not matched,
            "erosion_deposition_mutation_fallback_reason": None
            if matched
            else "EROSION_DEPOSITION_MUTATION_VALIDATION_MISMATCH",
            "erosion_deposition_mutation_candidate_prepared": True,
            "erosion_deposition_mutation_compared_cell_count": compared_cells,
            "erosion_deposition_mutation_writeback_count": compared_cells if matched else 0,
            "erosion_deposition_mutation_mismatch_count": mismatch_count,
            "erorate_mutation_mismatch_count": erorate_mismatch,
            "deporate_mutation_mismatch_count": deporate_mismatch,
            "erosion_deposition_mutation_cell_mask_mismatch_count": mask_mismatch,
            "erorate_mutation_max_abs_error": erorate_max,
            "deporate_mutation_max_abs_error": deporate_max,
            "erosion_deposition_mutation_abs_tolerance": tolerance,
            "erosion_deposition_mutation_d2h_bytes": int(
                erorate_cpu.nbytes
                + deporate_cpu.nbytes
                + erorate_kernel.nbytes
                + deporate_kernel.nbytes
                + mask_kernel.nbytes
            ),
            "erosion_deposition_mutation_h2d_bytes": 0,
            "final_state_mutated": bool(matched),
            "changed_field_names": ["erosion_rate", "deposition_rate"] if matched else [],
        }

    @ti.kernel
    def _diagnostic_erosion_deposition_bookkeeping_kernel(self, dt: ti.f64):
        for i, j in self.fields.h:
            self.erorate_diag_kernel[i, j] = 0.0
            self.deporate_diag_kernel[i, j] = 0.0
            self.erosion_depth_diag_kernel[i, j] = 0.0
            self.deposition_depth_diag_kernel[i, j] = 0.0
            self.source_depth_rate_diag_kernel[i, j] = 0.0
            self.z_bed_candidate_diag_kernel[i, j] = 0.0
            self.erosion_deposition_diag_cell_mask[i, j] = 0
            self.erosion_depth_delta_diag_kernel[i, j] = 0.0
            self.deposition_depth_delta_diag_kernel[i, j] = 0.0
            self.erosion_depth_candidate_diag_kernel[i, j] = 0.0
            self.deposition_depth_candidate_diag_kernel[i, j] = 0.0
            self.deep_state_diag_cell_mask[i, j] = 0
            if not self.fields.is_nodata[i, j]:
                erorate = self.fields.erosion_rate[i, j]
                deporate = self.fields.deposition_rate[i, j]
                erosion_depth_delta = erorate * dt
                deposition_depth_delta = ti.abs(deporate) * dt
                self.erorate_diag_kernel[i, j] = erorate
                self.deporate_diag_kernel[i, j] = deporate
                self.erosion_depth_diag_kernel[i, j] = erosion_depth_delta
                self.deposition_depth_diag_kernel[i, j] = deposition_depth_delta
                self.source_depth_rate_diag_kernel[i, j] = self.fields.tempfsh_flow[i, j] / dt + erorate + deporate
                self.z_bed_candidate_diag_kernel[i, j] = self.fields.tempele[i, j]
                self.erosion_deposition_diag_cell_mask[i, j] = 1
                self.erosion_depth_delta_diag_kernel[i, j] = erosion_depth_delta
                self.deposition_depth_delta_diag_kernel[i, j] = deposition_depth_delta
                self.erosion_depth_candidate_diag_kernel[i, j] = (
                    self.fields.erosion_depth[i, j] + erosion_depth_delta
                )
                self.deposition_depth_candidate_diag_kernel[i, j] = (
                    self.fields.deposition_depth[i, j] + deposition_depth_delta
                )
                self.deep_state_diag_cell_mask[i, j] = 1

    @ti.kernel
    def _write_erosion_deposition_mutation_kernel(self):
        for i, j in self.fields.h:
            if self.erosion_deposition_diag_cell_mask[i, j] == 1:
                self.fields.erosion_rate[i, j] = self.erorate_diag_kernel[i, j]
                self.fields.deposition_rate[i, j] = self.deporate_diag_kernel[i, j]

    def _default_qnet_qmassnet_mutation_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_qnet_qmassnet_mutate_gate_enabled:
            fallback_reason = "DFS_QNET_QMASSNET_MUTATE_GATE_NOT_SET"
        return {
            "dfs_qnet_qmassnet_mutation_gate_enabled": bool(self.dfs_qnet_qmassnet_mutate_gate_enabled),
            "dfs_qnet_qmassnet_mutation_active": False,
            "dfs_qnet_qmassnet_mutation_mode": "validated_writeback",
            "qnet_qmassnet_mutation_cpu_vs_kernel_match": None,
            "qnet_qmassnet_mutation_fallback_active": False,
            "qnet_qmassnet_mutation_fallback_reason": fallback_reason,
            "qnet_qmassnet_mutation_compared_cell_count": 0,
            "qnet_qmassnet_mutation_active_cell_count": 0,
            "qnet_qmassnet_mutation_compared_face_count": 0,
            "qnet_qmassnet_mutation_max_abs_error_qnet": None,
            "qnet_qmassnet_mutation_max_abs_error_qmassnet": None,
            "qnet_qmassnet_mutation_mismatch_count": 0,
            "qnet_qmassnet_mutation_qnet_mismatch_count": 0,
            "qnet_qmassnet_mutation_qmassnet_mismatch_count": 0,
            "qnet_qmassnet_mutation_cell_mask_mismatch_count": 0,
            "qnet_qmassnet_mutation_h2d_bytes": 0,
            "qnet_qmassnet_mutation_d2h_bytes": 0,
            "qnet_qmassnet_mutation_writeback_count": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_qnet_qmassnet_mutation_diagnostics(self) -> dict[str, object]:
        return dict(self.qnet_qmassnet_mutation_info)

    def _run_qnet_qmassnet_mutation_if_enabled(self) -> None:
        self.qnet_qmassnet_mutation_info = self._default_qnet_qmassnet_mutation_info()
        if not self.dfs_qnet_qmassnet_mutate_gate_enabled:
            return

        self._diagnostic_qnet_qmassnet_accumulation_kernel()
        qnet_cpu = np.asarray(self.fields.qnet_fortran.to_numpy())
        qmassnet_cpu = np.asarray(self.fields.qmassnet_fortran.to_numpy())
        cell_id = np.asarray(self.fields.cell_id.to_numpy())
        nodata = np.asarray(self.fields.is_nodata.to_numpy()).astype(bool)
        expected_cell_mask = ((cell_id > 0) & (~nodata)).astype(np.int32)
        valid_face_mask = ((cell_id[:, :, None] > 0) & (np.asarray(self.fields.flow_neighbor_id.to_numpy()) > 0)).astype(bool)
        qnet_kernel = np.asarray(self.qnet_diag_kernel.to_numpy())
        qmassnet_kernel = np.asarray(self.qmassnet_diag_kernel.to_numpy())
        cell_mask_kernel = np.asarray(self.qnet_qmassnet_diag_cell_mask.to_numpy())

        cell_mask_mismatch_count = int(np.count_nonzero(cell_mask_kernel != expected_cell_mask))
        compare_mask = expected_cell_mask.astype(bool)
        compared_cell_count = int(np.count_nonzero(compare_mask))
        compared_face_count = int(np.count_nonzero(valid_face_mask))
        max_abs_error_qnet = 0.0
        max_abs_error_qmassnet = 0.0
        qnet_mismatch_count = 0
        qmassnet_mismatch_count = 0
        if compared_cell_count:
            qnet_errors = np.abs(qnet_kernel[compare_mask] - qnet_cpu[compare_mask])
            qmassnet_errors = np.abs(qmassnet_kernel[compare_mask] - qmassnet_cpu[compare_mask])
            max_abs_error_qnet = float(qnet_errors.max(initial=0.0))
            max_abs_error_qmassnet = float(qmassnet_errors.max(initial=0.0))
            qnet_mismatch_count = int(np.count_nonzero(qnet_errors > 0.0))
            qmassnet_mismatch_count = int(np.count_nonzero(qmassnet_errors > 0.0))

        mismatch_count = qnet_mismatch_count + qmassnet_mismatch_count
        matched = mismatch_count == 0 and cell_mask_mismatch_count == 0
        if matched:
            self._write_qnet_qmassnet_mutation_kernel()

        self.qnet_qmassnet_mutation_info = {
            "dfs_qnet_qmassnet_mutation_gate_enabled": True,
            "dfs_qnet_qmassnet_mutation_active": bool(matched),
            "dfs_qnet_qmassnet_mutation_mode": "validated_writeback",
            "qnet_qmassnet_mutation_cpu_vs_kernel_match": bool(matched),
            "qnet_qmassnet_mutation_fallback_active": not matched,
            "qnet_qmassnet_mutation_fallback_reason": None if matched else "QNET_QMASSNET_MUTATION_KERNEL_MISMATCH",
            "qnet_qmassnet_mutation_compared_cell_count": compared_cell_count,
            "qnet_qmassnet_mutation_active_cell_count": compared_cell_count,
            "qnet_qmassnet_mutation_compared_face_count": compared_face_count,
            "qnet_qmassnet_mutation_max_abs_error_qnet": max_abs_error_qnet,
            "qnet_qmassnet_mutation_max_abs_error_qmassnet": max_abs_error_qmassnet,
            "qnet_qmassnet_mutation_mismatch_count": mismatch_count,
            "qnet_qmassnet_mutation_qnet_mismatch_count": qnet_mismatch_count,
            "qnet_qmassnet_mutation_qmassnet_mismatch_count": qmassnet_mismatch_count,
            "qnet_qmassnet_mutation_cell_mask_mismatch_count": cell_mask_mismatch_count,
            "qnet_qmassnet_mutation_h2d_bytes": 0,
            "qnet_qmassnet_mutation_d2h_bytes": int(
                qnet_cpu.nbytes
                + qmassnet_cpu.nbytes
                + qnet_kernel.nbytes
                + qmassnet_kernel.nbytes
                + cell_mask_kernel.nbytes
            ),
            "qnet_qmassnet_mutation_writeback_count": compared_cell_count if matched else 0,
            "final_state_mutated": False,
            "changed_field_names": ["qnet_fortran", "qmassnet_fortran"] if matched else [],
        }

    @ti.kernel
    def _write_qnet_qmassnet_mutation_kernel(self):
        for i, j in self.fields.h:
            self.fields.qnet_fortran[i, j] = self.qnet_diag_kernel[i, j]
            self.fields.qmassnet_fortran[i, j] = self.qmassnet_diag_kernel[i, j]

    def _default_predictor_kernel_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_predictor_diagnostic_kernel_gate_enabled:
            fallback_reason = "DFS_PREDICTOR_DIAGNOSTIC_KERNEL_GATE_NOT_SET"
        return {
            "dfs_predictor_diagnostic_kernel_gate_enabled": bool(
                self.dfs_predictor_diagnostic_kernel_gate_enabled
            ),
            "dfs_predictor_diagnostic_kernel_active": False,
            "dfs_predictor_diagnostic_kernel_mode": "diagnostic_predictor_update",
            "predictor_cpu_vs_kernel_match": None,
            "predictor_kernel_fallback_active": False,
            "predictor_kernel_fallback_reason": fallback_reason,
            "predictor_compared_cell_count": 0,
            "predictor_active_cell_count": 0,
            "predictor_max_abs_error_fhpredi2": None,
            "predictor_max_abs_error_frhopredi2": None,
            "predictor_mismatch_count": 0,
            "predictor_fhpredi2_mismatch_count": 0,
            "predictor_frhopredi2_mismatch_count": 0,
            "predictor_exact_mismatch_count": 0,
            "predictor_exact_fhpredi2_mismatch_count": 0,
            "predictor_exact_frhopredi2_mismatch_count": 0,
            "predictor_cell_mask_mismatch_count": 0,
            "predictor_tolerance_rtol": 1.0e-12,
            "predictor_tolerance_atol": 1.0e-12,
            "predictor_kernel_h2d_bytes": 0,
            "predictor_kernel_d2h_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_predictor_kernel_diagnostics(self) -> dict[str, object]:
        return dict(self.predictor_kernel_info)

    def _default_predictor_mutation_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_predictor_mutate_gate_enabled:
            fallback_reason = "DFS_PREDICTOR_MUTATE_GATE_NOT_SET"
        return {
            "dfs_predictor_mutation_gate_enabled": bool(self.dfs_predictor_mutate_gate_enabled),
            "dfs_predictor_mutation_active": False,
            "dfs_predictor_mutation_mode": "validated_writeback",
            "predictor_mutation_cpu_vs_kernel_match": None,
            "predictor_mutation_fallback_active": False,
            "predictor_mutation_fallback_reason": fallback_reason,
            "predictor_mutation_compared_cells": 0,
            "predictor_mutation_writeback_count": 0,
            "predictor_mutation_mismatch_count": 0,
            "predictor_mutation_fhpredi2_mismatch_count": 0,
            "predictor_mutation_frhopredi2_mismatch_count": 0,
            "predictor_mutation_cell_mask_mismatch_count": 0,
            "predictor_mutation_exact_mismatch_count": 0,
            "predictor_mutation_exact_fhpredi2_mismatch_count": 0,
            "predictor_mutation_exact_frhopredi2_mismatch_count": 0,
            "predictor_mutation_max_abs_error_fhpredi2": 0.0,
            "predictor_mutation_max_abs_error_frhopredi2": 0.0,
            "predictor_mutation_rtol": 1e-9,
            "predictor_mutation_atol": 1e-12,
            "predictor_mutation_h2d_bytes": 0,
            "predictor_mutation_d2h_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_predictor_mutation_diagnostics(self) -> dict[str, object]:
        return dict(self.predictor_mutation_info)

    def _default_h_cv_rho_kernel_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_h_cv_rho_diagnostic_kernel_gate_enabled:
            fallback_reason = "DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_GATE_NOT_SET"
        return {
            "dfs_h_cv_rho_diagnostic_kernel_gate_enabled": bool(self.dfs_h_cv_rho_diagnostic_kernel_gate_enabled),
            "dfs_h_cv_rho_diagnostic_kernel_active": False,
            "dfs_h_cv_rho_diagnostic_kernel_mode": "diagnostic_precommit_candidate_update",
            "h_cv_rho_cpu_vs_kernel_match": None,
            "h_cv_rho_kernel_fallback_active": False,
            "h_cv_rho_kernel_fallback_reason": fallback_reason,
            "h_cv_rho_precommit_candidate_prepared": False,
            "h_cv_rho_compared_cell_count": 0,
            "h_cv_rho_mismatch_count": 0,
            "h_mismatch_count": 0,
            "Cv_mismatch_count": 0,
            "rho_mismatch_count": 0,
            "h_cv_rho_cell_mask_mismatch_count": 0,
            "h_exact_mismatch_count": 0,
            "Cv_exact_mismatch_count": 0,
            "rho_exact_mismatch_count": 0,
            "h_cv_rho_exact_mismatch_count": 0,
            "h_max_abs_error": 0.0,
            "Cv_max_abs_error": 0.0,
            "rho_max_abs_error": 0.0,
            "h_cv_rho_tolerance_rtol": 1e-12,
            "h_cv_rho_tolerance_atol": 1e-12,
            "h_cv_rho_d2h_bytes": 0,
            "h_cv_rho_h2d_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_h_cv_rho_kernel_diagnostics(self) -> dict[str, object]:
        return dict(self.h_cv_rho_kernel_info)

    def _default_h_cv_rho_mutation_info(self) -> dict[str, object]:
        fallback_reason = None
        if not self.dfs_h_cv_rho_mutate_gate_enabled:
            fallback_reason = "DFS_H_CV_RHO_MUTATE_GATE_NOT_SET"
        return {
            "dfs_h_cv_rho_mutation_gate_enabled": bool(self.dfs_h_cv_rho_mutate_gate_enabled),
            "dfs_h_cv_rho_mutation_active": False,
            "dfs_h_cv_rho_mutation_mode": "validated_writeback",
            "h_cv_rho_mutation_cpu_vs_kernel_match": None,
            "h_cv_rho_mutation_fallback_active": False,
            "h_cv_rho_mutation_fallback_reason": fallback_reason,
            "h_cv_rho_mutation_precommit_candidate_prepared": False,
            "h_cv_rho_mutation_compared_cell_count": 0,
            "h_cv_rho_mutation_writeback_count": 0,
            "h_cv_rho_mutation_mismatch_count": 0,
            "h_mutation_mismatch_count": 0,
            "Cv_mutation_mismatch_count": 0,
            "rho_mutation_mismatch_count": 0,
            "h_cv_rho_mutation_cell_mask_mismatch_count": 0,
            "h_mutation_exact_mismatch_count": 0,
            "Cv_mutation_exact_mismatch_count": 0,
            "rho_mutation_exact_mismatch_count": 0,
            "h_cv_rho_mutation_exact_mismatch_count": 0,
            "h_mutation_max_abs_error": 0.0,
            "Cv_mutation_max_abs_error": 0.0,
            "rho_mutation_max_abs_error": 0.0,
            "h_cv_rho_mutation_rtol": 1e-9,
            "h_cv_rho_mutation_atol": 1e-12,
            "h_cv_rho_mutation_d2h_bytes": 0,
            "h_cv_rho_mutation_h2d_bytes": 0,
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    def get_h_cv_rho_mutation_diagnostics(self) -> dict[str, object]:
        return dict(self.h_cv_rho_mutation_info)

    @ti.kernel
    def _diagnostic_h_cv_rho_update_kernel(
        self,
        rho_water: ti.f64,
        rho_sediment: ti.f64,
    ):
        denom = rho_sediment - rho_water
        for i, j in self.fields.h:
            self.h_diag_kernel[i, j] = 0.0
            self.Cv_diag_kernel[i, j] = 0.0
            self.rho_diag_kernel[i, j] = rho_water
            self.h_cv_rho_diag_cell_mask[i, j] = 0
            if not self.fields.is_nodata[i, j]:
                h_candidate = self.fields.fhpredi2[i, j]
                rho_candidate = self.fields.frhopredi2[i, j]
                Cv_candidate = rho_candidate - rho_water
                if denom != 0.0:
                    Cv_candidate = (rho_candidate - rho_water) / denom
                else:
                    Cv_candidate = 0.0
                if h_candidate < EPS:
                    h_candidate = 0.0
                self.h_diag_kernel[i, j] = h_candidate
                self.Cv_diag_kernel[i, j] = Cv_candidate
                self.rho_diag_kernel[i, j] = rho_candidate
                self.h_cv_rho_diag_cell_mask[i, j] = 1

    def _prepare_h_cv_rho_diagnostic_if_enabled(self) -> None:
        self.h_cv_rho_kernel_info = self._default_h_cv_rho_kernel_info()
        if not self.dfs_h_cv_rho_diagnostic_kernel_gate_enabled:
            return
        self._diagnostic_h_cv_rho_update_kernel(self.rhow, self.rhos)
        self.h_cv_rho_kernel_info.update(
            {
                "dfs_h_cv_rho_diagnostic_kernel_active": True,
                "h_cv_rho_kernel_fallback_active": False,
                "h_cv_rho_kernel_fallback_reason": None,
                "h_cv_rho_precommit_candidate_prepared": True,
                "final_state_mutated": False,
                "changed_field_names": [],
            }
        )

    def _prepare_h_cv_rho_mutation_if_enabled(self) -> None:
        self.h_cv_rho_mutation_info = self._default_h_cv_rho_mutation_info()
        if not self.dfs_h_cv_rho_mutate_gate_enabled:
            return
        self._diagnostic_h_cv_rho_update_kernel(self.rhow, self.rhos)
        self.h_cv_rho_mutation_info.update(
            {
                "dfs_h_cv_rho_mutation_active": False,
                "h_cv_rho_mutation_fallback_active": False,
                "h_cv_rho_mutation_fallback_reason": None,
                "h_cv_rho_mutation_precommit_candidate_prepared": True,
                "final_state_mutated": False,
                "changed_field_names": [],
            }
        )

    def _finalize_h_cv_rho_diagnostic_if_enabled(self) -> None:
        if not self.dfs_h_cv_rho_diagnostic_kernel_gate_enabled:
            return

        rtol = float(self.h_cv_rho_kernel_info["h_cv_rho_tolerance_rtol"])
        atol = float(self.h_cv_rho_kernel_info["h_cv_rho_tolerance_atol"])
        h_ref = self.fields.h.to_numpy()
        Cv_ref = self.fields.Cv.to_numpy()
        rho_ref = self.fields.rho.to_numpy()
        h_diag = self.h_diag_kernel.to_numpy()
        Cv_diag = self.Cv_diag_kernel.to_numpy()
        rho_diag = self.rho_diag_kernel.to_numpy()
        mask_diag = self.h_cv_rho_diag_cell_mask.to_numpy()
        cell_ids = self.fields.cell_id.to_numpy()

        active_mask = cell_ids > 0
        diag_mask = mask_diag == 1
        mask_mismatch = int(np.count_nonzero(active_mask != diag_mask))
        compared_cells = int(np.count_nonzero(active_mask))

        h_abs = np.abs(h_ref - h_diag)
        Cv_abs = np.abs(Cv_ref - Cv_diag)
        rho_abs = np.abs(rho_ref - rho_diag)
        h_close = np.isclose(h_ref, h_diag, rtol=rtol, atol=atol)
        Cv_close = np.isclose(Cv_ref, Cv_diag, rtol=rtol, atol=atol)
        rho_close = np.isclose(rho_ref, rho_diag, rtol=rtol, atol=atol)
        h_mismatch = int(np.count_nonzero(active_mask & ~h_close))
        Cv_mismatch = int(np.count_nonzero(active_mask & ~Cv_close))
        rho_mismatch = int(np.count_nonzero(active_mask & ~rho_close))
        mismatch_count = h_mismatch + Cv_mismatch + rho_mismatch + mask_mismatch
        exact_h_mismatch = int(np.count_nonzero(active_mask & (h_ref != h_diag)))
        exact_Cv_mismatch = int(np.count_nonzero(active_mask & (Cv_ref != Cv_diag)))
        exact_rho_mismatch = int(np.count_nonzero(active_mask & (rho_ref != rho_diag)))
        max_h = float(np.max(h_abs[active_mask])) if compared_cells else 0.0
        max_Cv = float(np.max(Cv_abs[active_mask])) if compared_cells else 0.0
        max_rho = float(np.max(rho_abs[active_mask])) if compared_cells else 0.0
        matched = mismatch_count == 0

        self.h_cv_rho_kernel_info.update(
            {
                "dfs_h_cv_rho_diagnostic_kernel_active": matched,
                "h_cv_rho_cpu_vs_kernel_match": matched,
                "h_cv_rho_kernel_fallback_active": not matched,
                "h_cv_rho_kernel_fallback_reason": None
                if matched
                else "H_CV_RHO_DIAGNOSTIC_KERNEL_MISMATCH",
                "h_cv_rho_precommit_candidate_prepared": True,
                "h_cv_rho_compared_cell_count": compared_cells,
                "h_cv_rho_mismatch_count": mismatch_count,
                "h_mismatch_count": h_mismatch,
                "Cv_mismatch_count": Cv_mismatch,
                "rho_mismatch_count": rho_mismatch,
                "h_cv_rho_cell_mask_mismatch_count": mask_mismatch,
                "h_exact_mismatch_count": exact_h_mismatch,
                "Cv_exact_mismatch_count": exact_Cv_mismatch,
                "rho_exact_mismatch_count": exact_rho_mismatch,
                "h_cv_rho_exact_mismatch_count": exact_h_mismatch
                + exact_Cv_mismatch
                + exact_rho_mismatch,
                "h_max_abs_error": max_h,
                "Cv_max_abs_error": max_Cv,
                "rho_max_abs_error": max_rho,
                "h_cv_rho_d2h_bytes": int(
                    h_ref.nbytes
                    + Cv_ref.nbytes
                    + rho_ref.nbytes
                    + h_diag.nbytes
                    + Cv_diag.nbytes
                    + rho_diag.nbytes
                    + mask_diag.nbytes
                ),
                "h_cv_rho_h2d_bytes": int(
                    self.fields.fhpredi2.to_numpy().nbytes
                    + self.fields.frhopredi2.to_numpy().nbytes
                ),
                "final_state_mutated": False,
                "changed_field_names": [],
            }
        )

    def _run_h_cv_rho_mutation_if_enabled(self) -> None:
        if not self.dfs_h_cv_rho_mutate_gate_enabled:
            return

        rtol = float(self.h_cv_rho_mutation_info["h_cv_rho_mutation_rtol"])
        atol = float(self.h_cv_rho_mutation_info["h_cv_rho_mutation_atol"])
        h_ref = self.fields.h.to_numpy()
        Cv_ref = self.fields.Cv.to_numpy()
        rho_ref = self.fields.rho.to_numpy()
        h_kernel = self.h_diag_kernel.to_numpy()
        Cv_kernel = self.Cv_diag_kernel.to_numpy()
        rho_kernel = self.rho_diag_kernel.to_numpy()
        mask_kernel = self.h_cv_rho_diag_cell_mask.to_numpy()
        nodata = self.fields.is_nodata.to_numpy().astype(bool)

        expected_mask = ~nodata
        kernel_mask = mask_kernel == 1
        mask_mismatch = int(np.count_nonzero(expected_mask != kernel_mask))
        compared_cells = int(np.count_nonzero(expected_mask))

        h_abs = np.abs(h_ref - h_kernel)
        Cv_abs = np.abs(Cv_ref - Cv_kernel)
        rho_abs = np.abs(rho_ref - rho_kernel)
        h_close = np.isclose(h_ref, h_kernel, rtol=rtol, atol=atol)
        Cv_close = np.isclose(Cv_ref, Cv_kernel, rtol=rtol, atol=atol)
        rho_close = np.isclose(rho_ref, rho_kernel, rtol=rtol, atol=atol)
        h_mismatch = int(np.count_nonzero(expected_mask & ~h_close))
        Cv_mismatch = int(np.count_nonzero(expected_mask & ~Cv_close))
        rho_mismatch = int(np.count_nonzero(expected_mask & ~rho_close))
        mismatch_count = h_mismatch + Cv_mismatch + rho_mismatch + mask_mismatch
        exact_h_mismatch = int(np.count_nonzero(expected_mask & (h_ref != h_kernel)))
        exact_Cv_mismatch = int(np.count_nonzero(expected_mask & (Cv_ref != Cv_kernel)))
        exact_rho_mismatch = int(np.count_nonzero(expected_mask & (rho_ref != rho_kernel)))
        max_h = float(np.max(h_abs[expected_mask])) if compared_cells else 0.0
        max_Cv = float(np.max(Cv_abs[expected_mask])) if compared_cells else 0.0
        max_rho = float(np.max(rho_abs[expected_mask])) if compared_cells else 0.0
        matched = mismatch_count == 0
        if matched:
            self._write_h_cv_rho_mutation_kernel()

        self.h_cv_rho_mutation_info.update(
            {
                "dfs_h_cv_rho_mutation_active": bool(matched),
                "h_cv_rho_mutation_cpu_vs_kernel_match": bool(matched),
                "h_cv_rho_mutation_fallback_active": not matched,
                "h_cv_rho_mutation_fallback_reason": None
                if matched
                else "H_CV_RHO_MUTATION_KERNEL_MISMATCH",
                "h_cv_rho_mutation_precommit_candidate_prepared": True,
                "h_cv_rho_mutation_compared_cell_count": compared_cells,
                "h_cv_rho_mutation_writeback_count": compared_cells if matched else 0,
                "h_cv_rho_mutation_mismatch_count": mismatch_count,
                "h_mutation_mismatch_count": h_mismatch,
                "Cv_mutation_mismatch_count": Cv_mismatch,
                "rho_mutation_mismatch_count": rho_mismatch,
                "h_cv_rho_mutation_cell_mask_mismatch_count": mask_mismatch,
                "h_mutation_exact_mismatch_count": exact_h_mismatch,
                "Cv_mutation_exact_mismatch_count": exact_Cv_mismatch,
                "rho_mutation_exact_mismatch_count": exact_rho_mismatch,
                "h_cv_rho_mutation_exact_mismatch_count": exact_h_mismatch
                + exact_Cv_mismatch
                + exact_rho_mismatch,
                "h_mutation_max_abs_error": max_h,
                "Cv_mutation_max_abs_error": max_Cv,
                "rho_mutation_max_abs_error": max_rho,
                "h_cv_rho_mutation_d2h_bytes": int(
                    h_ref.nbytes
                    + Cv_ref.nbytes
                    + rho_ref.nbytes
                    + h_kernel.nbytes
                    + Cv_kernel.nbytes
                    + rho_kernel.nbytes
                    + mask_kernel.nbytes
                ),
                "h_cv_rho_mutation_h2d_bytes": int(
                    self.fields.fhpredi2.to_numpy().nbytes
                    + self.fields.frhopredi2.to_numpy().nbytes
                ),
                "final_state_mutated": bool(matched),
                "changed_field_names": ["h", "Cv", "rho"] if matched else [],
            }
        )

    @ti.kernel
    def _write_h_cv_rho_mutation_kernel(self):
        for i, j in self.fields.h:
            if self.h_cv_rho_diag_cell_mask[i, j] == 1:
                self.fields.h[i, j] = self.h_diag_kernel[i, j]
                self.fields.Cv[i, j] = self.Cv_diag_kernel[i, j]
                self.fields.rho[i, j] = self.rho_diag_kernel[i, j]

    def _run_predictor_diagnostic_if_enabled(self) -> None:
        self.predictor_kernel_info = self._default_predictor_kernel_info()
        if not self.dfs_predictor_diagnostic_kernel_gate_enabled:
            return

        self._diagnostic_predictor_update_kernel(self.rhow)
        fhpredi2_cpu = np.asarray(self.fields.fhpredi2.to_numpy())
        frhopredi2_cpu = np.asarray(self.fields.frhopredi2.to_numpy())
        cell_id = np.asarray(self.fields.cell_id.to_numpy())
        nodata = np.asarray(self.fields.is_nodata.to_numpy()).astype(bool)
        expected_cell_mask = ((cell_id > 0) & (~nodata)).astype(np.int32)
        fhpredi2_kernel = np.asarray(self.fhpredi2_diag_kernel.to_numpy())
        frhopredi2_kernel = np.asarray(self.frhopredi2_diag_kernel.to_numpy())
        cell_mask_kernel = np.asarray(self.predictor_diag_cell_mask.to_numpy())

        cell_mask_mismatch_count = int(np.count_nonzero(cell_mask_kernel != expected_cell_mask))
        compare_mask = expected_cell_mask.astype(bool)
        compared_cell_count = int(np.count_nonzero(compare_mask))
        max_abs_error_fhpredi2 = 0.0
        max_abs_error_frhopredi2 = 0.0
        fhpredi2_mismatch_count = 0
        frhopredi2_mismatch_count = 0
        fhpredi2_exact_mismatch_count = 0
        frhopredi2_exact_mismatch_count = 0
        predictor_rtol = 1.0e-12
        predictor_atol = 1.0e-12
        if compared_cell_count:
            fhpredi2_errors = np.abs(fhpredi2_kernel[compare_mask] - fhpredi2_cpu[compare_mask])
            frhopredi2_errors = np.abs(frhopredi2_kernel[compare_mask] - frhopredi2_cpu[compare_mask])
            max_abs_error_fhpredi2 = float(fhpredi2_errors.max(initial=0.0))
            max_abs_error_frhopredi2 = float(frhopredi2_errors.max(initial=0.0))
            fhpredi2_exact_mismatch_count = int(np.count_nonzero(fhpredi2_errors > 0.0))
            frhopredi2_exact_mismatch_count = int(np.count_nonzero(frhopredi2_errors > 0.0))
            fhpredi2_mismatch_count = int(
                np.count_nonzero(
                    ~np.isclose(
                        fhpredi2_kernel[compare_mask],
                        fhpredi2_cpu[compare_mask],
                        rtol=predictor_rtol,
                        atol=predictor_atol,
                    )
                )
            )
            frhopredi2_mismatch_count = int(
                np.count_nonzero(
                    ~np.isclose(
                        frhopredi2_kernel[compare_mask],
                        frhopredi2_cpu[compare_mask],
                        rtol=predictor_rtol,
                        atol=predictor_atol,
                    )
                )
            )

        mismatch_count = fhpredi2_mismatch_count + frhopredi2_mismatch_count
        exact_mismatch_count = fhpredi2_exact_mismatch_count + frhopredi2_exact_mismatch_count
        matched = mismatch_count == 0 and cell_mask_mismatch_count == 0
        self.predictor_kernel_info = {
            "dfs_predictor_diagnostic_kernel_gate_enabled": True,
            "dfs_predictor_diagnostic_kernel_active": bool(matched),
            "dfs_predictor_diagnostic_kernel_mode": "diagnostic_predictor_update",
            "predictor_cpu_vs_kernel_match": bool(matched),
            "predictor_kernel_fallback_active": not matched,
            "predictor_kernel_fallback_reason": None if matched else "PREDICTOR_DIAGNOSTIC_KERNEL_MISMATCH",
            "predictor_compared_cell_count": compared_cell_count,
            "predictor_active_cell_count": compared_cell_count,
            "predictor_max_abs_error_fhpredi2": max_abs_error_fhpredi2,
            "predictor_max_abs_error_frhopredi2": max_abs_error_frhopredi2,
            "predictor_mismatch_count": mismatch_count,
            "predictor_fhpredi2_mismatch_count": fhpredi2_mismatch_count,
            "predictor_frhopredi2_mismatch_count": frhopredi2_mismatch_count,
            "predictor_exact_mismatch_count": exact_mismatch_count,
            "predictor_exact_fhpredi2_mismatch_count": fhpredi2_exact_mismatch_count,
            "predictor_exact_frhopredi2_mismatch_count": frhopredi2_exact_mismatch_count,
            "predictor_cell_mask_mismatch_count": cell_mask_mismatch_count,
            "predictor_tolerance_rtol": predictor_rtol,
            "predictor_tolerance_atol": predictor_atol,
            "predictor_kernel_h2d_bytes": 0,
            "predictor_kernel_d2h_bytes": int(
                fhpredi2_cpu.nbytes
                + frhopredi2_cpu.nbytes
                + fhpredi2_kernel.nbytes
                + frhopredi2_kernel.nbytes
                + cell_mask_kernel.nbytes
            ),
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    @ti.kernel
    def _diagnostic_predictor_update_kernel(self, rho_water: ti.f64):
        for i, j in self.fields.h:
            self.fhpredi2_diag_kernel[i, j] = 0.0
            self.frhopredi2_diag_kernel[i, j] = rho_water
            self.predictor_diag_cell_mask[i, j] = 0
            if not self.fields.is_nodata[i, j] and self.fields.cell_id[i, j] > 0:
                cellarea = self.fields.cell_area_cal[i, j]
                fhpredi2 = self.fields.fhpredi[i, j] + self.fields.qnet_fortran[i, j] / cellarea
                frhopredi2 = rho_water
                if fhpredi2 != 0.0:
                    frhopredi2 = (
                        self.fields.frhopredi[i, j] * self.fields.fhpredi[i, j] * cellarea
                        + self.fields.qmassnet_fortran[i, j]
                    ) / fhpredi2 / cellarea
                if fhpredi2 <= 0.0 or frhopredi2 < 995.0:
                    fhpredi2 = 0.0
                    frhopredi2 = rho_water
                self.fhpredi2_diag_kernel[i, j] = fhpredi2
                self.frhopredi2_diag_kernel[i, j] = frhopredi2
                self.predictor_diag_cell_mask[i, j] = 1

    def _run_predictor_mutation_if_enabled(self) -> None:
        self.predictor_mutation_info = self._default_predictor_mutation_info()
        if not self.dfs_predictor_mutate_gate_enabled:
            return

        self._diagnostic_predictor_update_kernel(self.rhow)
        fhpredi2_cpu = np.asarray(self.fields.fhpredi2.to_numpy())
        frhopredi2_cpu = np.asarray(self.fields.frhopredi2.to_numpy())
        cell_id = np.asarray(self.fields.cell_id.to_numpy())
        fhpredi2_kernel = np.asarray(self.fhpredi2_diag_kernel.to_numpy())
        frhopredi2_kernel = np.asarray(self.frhopredi2_diag_kernel.to_numpy())
        cell_mask = np.asarray(self.predictor_diag_cell_mask.to_numpy())

        active_mask = cell_id > 0
        kernel_active_mask = cell_mask == 1
        mask_mismatch_count = int(np.count_nonzero(active_mask != kernel_active_mask))
        compared_cells = int(np.count_nonzero(active_mask))
        predictor_rtol = 1e-9
        predictor_atol = 1e-12

        fhpredi2_close = np.isclose(
            fhpredi2_kernel,
            fhpredi2_cpu,
            rtol=predictor_rtol,
            atol=predictor_atol,
        )
        frhopredi2_close = np.isclose(
            frhopredi2_kernel,
            frhopredi2_cpu,
            rtol=predictor_rtol,
            atol=predictor_atol,
        )
        fhpredi2_exact = fhpredi2_kernel == fhpredi2_cpu
        frhopredi2_exact = frhopredi2_kernel == frhopredi2_cpu
        fhpredi2_mismatch_count = int(np.count_nonzero(active_mask & ~fhpredi2_close))
        frhopredi2_mismatch_count = int(np.count_nonzero(active_mask & ~frhopredi2_close))
        exact_fhpredi2_mismatch_count = int(np.count_nonzero(active_mask & ~fhpredi2_exact))
        exact_frhopredi2_mismatch_count = int(np.count_nonzero(active_mask & ~frhopredi2_exact))
        mismatch_count = fhpredi2_mismatch_count + frhopredi2_mismatch_count
        exact_mismatch_count = exact_fhpredi2_mismatch_count + exact_frhopredi2_mismatch_count
        if compared_cells:
            max_fhpredi2 = float(np.max(np.abs(fhpredi2_kernel[active_mask] - fhpredi2_cpu[active_mask])))
            max_frhopredi2 = float(np.max(np.abs(frhopredi2_kernel[active_mask] - frhopredi2_cpu[active_mask])))
        else:
            max_fhpredi2 = 0.0
            max_frhopredi2 = 0.0

        matched = mismatch_count == 0 and mask_mismatch_count == 0
        if matched:
            self._write_predictor_mutation_kernel()

        field_bytes = int(fhpredi2_cpu.nbytes)
        self.predictor_mutation_info = {
            "dfs_predictor_mutation_gate_enabled": True,
            "dfs_predictor_mutation_active": bool(matched),
            "dfs_predictor_mutation_mode": "validated_writeback",
            "predictor_mutation_cpu_vs_kernel_match": bool(matched),
            "predictor_mutation_fallback_active": not matched,
            "predictor_mutation_fallback_reason": None if matched else "PREDICTOR_MUTATION_KERNEL_MISMATCH",
            "predictor_mutation_compared_cells": compared_cells,
            "predictor_mutation_writeback_count": compared_cells if matched else 0,
            "predictor_mutation_mismatch_count": mismatch_count,
            "predictor_mutation_fhpredi2_mismatch_count": fhpredi2_mismatch_count,
            "predictor_mutation_frhopredi2_mismatch_count": frhopredi2_mismatch_count,
            "predictor_mutation_cell_mask_mismatch_count": mask_mismatch_count,
            "predictor_mutation_exact_mismatch_count": exact_mismatch_count,
            "predictor_mutation_exact_fhpredi2_mismatch_count": exact_fhpredi2_mismatch_count,
            "predictor_mutation_exact_frhopredi2_mismatch_count": exact_frhopredi2_mismatch_count,
            "predictor_mutation_max_abs_error_fhpredi2": max_fhpredi2,
            "predictor_mutation_max_abs_error_frhopredi2": max_frhopredi2,
            "predictor_mutation_rtol": predictor_rtol,
            "predictor_mutation_atol": predictor_atol,
            "predictor_mutation_h2d_bytes": field_bytes * 4,
            "predictor_mutation_d2h_bytes": int(
                fhpredi2_cpu.nbytes
                + frhopredi2_cpu.nbytes
                + fhpredi2_kernel.nbytes
                + frhopredi2_kernel.nbytes
                + cell_mask.nbytes
            ),
            "final_state_mutated": False,
            "changed_field_names": ["fhpredi2", "frhopredi2"] if matched else [],
        }

    @ti.kernel
    def _write_predictor_mutation_kernel(self):
        for i, j in self.fields.h:
            if self.predictor_diag_cell_mask[i, j] == 1:
                self.fields.fhpredi2[i, j] = self.fhpredi2_diag_kernel[i, j]
                self.fields.frhopredi2[i, j] = self.frhopredi2_diag_kernel[i, j]

    def _run_face_flux_kernel_diagnostic_if_enabled(self) -> None:
        self.face_flux_kernel_info = self._default_face_flux_kernel_info()
        if not self.dfs_face_flux_kernel_gate_enabled:
            return

        self._candidate_face_flux_recompute_kernel()
        qq_cpu = np.asarray(self.fields.qq_fortran.to_numpy())
        qqmass_cpu = np.asarray(self.fields.qqmass_fortran.to_numpy())
        fvpred_cpu = np.asarray(self.fields.fv_pred_fortran.to_numpy())
        neighbor_id = np.asarray(self.fields.flow_neighbor_id.to_numpy())
        cell_id = np.asarray(self.fields.cell_id.to_numpy())
        valid_cpu = ((cell_id[:, :, None] > 0) & (neighbor_id > 0)).astype(np.int32)
        qq_kernel = np.asarray(self.face_flux_kernel_qq.to_numpy())
        qqmass_kernel = np.asarray(self.face_flux_kernel_qqmass.to_numpy())
        fvpred_kernel = np.asarray(self.face_flux_kernel_fvpred.to_numpy())
        valid_kernel = np.asarray(self.face_flux_kernel_valid_mask.to_numpy())

        mask_mismatch = valid_kernel != valid_cpu
        compare_mask = valid_cpu.astype(bool)
        compared_count = int(np.count_nonzero(compare_mask))
        max_abs_error = 0.0
        mismatch_count = 0
        fvpred_mismatch_count = 0
        qq_mismatch_count = 0
        qqmass_mismatch_count = 0
        if compared_count:
            qq_errors = np.abs(qq_kernel[compare_mask] - qq_cpu[compare_mask])
            qqmass_errors = np.abs(qqmass_kernel[compare_mask] - qqmass_cpu[compare_mask])
            fvpred_errors = np.abs(fvpred_kernel[compare_mask] - fvpred_cpu[compare_mask])
            errors = [qq_errors, qqmass_errors, fvpred_errors]
            max_abs_error = float(max(float(err.max(initial=0.0)) for err in errors))
            qq_mismatch_count = int(np.count_nonzero(qq_errors > 0.0))
            qqmass_mismatch_count = int(np.count_nonzero(qqmass_errors > 0.0))
            fvpred_mismatch_count = int(np.count_nonzero(fvpred_errors > 0.0))
            mismatch_count = qq_mismatch_count + qqmass_mismatch_count + fvpred_mismatch_count

        mask_mismatch_count = int(np.count_nonzero(mask_mismatch))
        matched = mismatch_count == 0 and mask_mismatch_count == 0
        self.face_flux_kernel_info = {
            "dfs_face_flux_kernel_gate_enabled": True,
            "dfs_face_flux_kernel_active": bool(matched),
            "dfs_face_flux_kernel_mode": "candidate_mask_and_mirror",
            "face_flux_candidate_subset": "valid_mask_and_opposite_face_mirror",
            "face_flux_full_formula_recomputed": False,
            "face_flux_valid_mask_recomputed": True,
            "face_flux_opposite_mirror_recomputed": True,
            "face_flux_cpu_vs_kernel_match": bool(matched),
            "face_flux_kernel_fallback_active": not matched,
            "face_flux_kernel_fallback_reason": None if matched else "FACE_FLUX_CANDIDATE_KERNEL_MISMATCH",
            "face_flux_compared_count": compared_count,
            "face_flux_max_abs_error": max_abs_error,
            "face_flux_mismatch_count": mismatch_count,
            "face_flux_fv_pred_mismatch_count": fvpred_mismatch_count,
            "face_flux_qq_mismatch_count": qq_mismatch_count,
            "face_flux_qqmass_mismatch_count": qqmass_mismatch_count,
            "face_flux_mask_mismatch_count": mask_mismatch_count,
            "face_flux_kernel_h2d_bytes": 0,
            "face_flux_kernel_d2h_bytes": int(
                qq_kernel.nbytes + qqmass_kernel.nbytes + fvpred_kernel.nbytes + valid_kernel.nbytes
            ),
            "final_state_mutated": False,
            "changed_field_names": [],
        }

    @ti.kernel
    def _mirror_face_flux_diagnostic_kernel(self):
        for i, j, d in self.fields.qq_fortran:
            valid = 0
            if self.fields.cell_id[i, j] > 0 and self.fields.flow_neighbor_id[i, j, d] > 0:
                valid = 1
            self.face_flux_kernel_valid_mask[i, j, d] = valid
            self.face_flux_kernel_qq[i, j, d] = self.fields.qq_fortran[i, j, d]
            self.face_flux_kernel_qqmass[i, j, d] = self.fields.qqmass_fortran[i, j, d]
            self.face_flux_kernel_fvpred[i, j, d] = self.fields.fv_pred_fortran[i, j, d]

    @ti.kernel
    def _candidate_face_flux_recompute_kernel(self):
        for i, j in self.fields.h:
            for d in ti.static(range(8)):
                valid = 0
                self.face_flux_kernel_qq[i, j, d] = 0.0
                self.face_flux_kernel_qqmass[i, j, d] = 0.0
                self.face_flux_kernel_fvpred[i, j, d] = 0.0

                if self.fields.cell_id[i, j] > 0 and self.fields.flow_neighbor_id[i, j, d] > 0:
                    valid = 1
                    ni = self.fields.flow_neighbor_i[i, j, d]
                    nj = self.fields.flow_neighbor_j[i, j, d]
                    if ni >= 0 and nj >= 0 and self.fields.cell_id[ni, nj] > 0:
                        if self.fields.cell_id[ni, nj] > self.fields.cell_id[i, j]:
                            self.face_flux_kernel_qq[i, j, d] = self.fields.qq_fortran[i, j, d]
                            self.face_flux_kernel_qqmass[i, j, d] = self.fields.qqmass_fortran[i, j, d]
                            self.face_flux_kernel_fvpred[i, j, d] = self.fields.fv_pred_fortran[i, j, d]
                        else:
                            opp = ti.static(FORTRAN_OPPOSITE_DIR[d])
                            self.face_flux_kernel_qq[i, j, d] = -self.fields.qq_fortran[ni, nj, opp]
                            self.face_flux_kernel_qqmass[i, j, d] = -self.fields.qqmass_fortran[ni, nj, opp]
                            self.face_flux_kernel_fvpred[i, j, d] = -self.fields.fv_pred_fortran[ni, nj, opp]

                self.face_flux_kernel_valid_mask[i, j, d] = valid

    @staticmethod
    def _shadow_row_float(row: dict[str, object], names: tuple[str, ...], default: float = 0.0) -> float:
        for name in names:
            value = row.get(name)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return float(default)

    @staticmethod
    def _shadow_row_int(row: dict[str, object], names: tuple[str, ...], default: int = 0) -> int:
        for name in names:
            value = row.get(name)
            if value is None or value == "":
                continue
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
        return int(default)

    def run_rnoff_provider_schedule_shadow_lifecycle(
        self,
        schedule_rows: list[dict[str, object]],
        *,
        t_start_s: float = 0.0,
        t_end_s: float | None = None,
        source_meta: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Preview RNOFF provider schedule lifecycle without DFS runtime feed.

        This mirrors the existing precomputed schedule crossing and duplicate
        predicates, but it only updates shadow diagnostics. It never calls
        ``configure_precomputed_failure_schedule`` and never writes DFS fields,
        source terms, production fire markers, or accepted state.
        """
        rows = [dict(row) for row in schedule_rows]
        row_count = len(rows)
        tfail = np.asarray(
            [self._shadow_row_float(row, ("tfail", "tfail_s"), default=np.nan) for row in rows],
            dtype=np.float64,
        )
        gindx = np.asarray(
            [self._shadow_row_int(row, ("gindx",), default=0) for row in rows],
            dtype=np.int32,
        )
        fdepth = np.asarray(
            [self._shadow_row_float(row, ("fdepth", "fdepth_m"), default=0.0) for row in rows],
            dtype=np.float64,
        )
        cell_ids = [
            self._shadow_row_int(row, ("one_based_cell_id", "cell_id"), default=index + 1)
            for index, row in enumerate(rows)
        ]

        active = (gindx > 0) & (fdepth > 0.0) & np.isfinite(tfail)
        if t_end_s is None:
            positive_tfail = tfail[active & (tfail >= float(t_start_s))]
            if positive_tfail.size:
                t_end = float(np.max(positive_tfail)) + 1.0e-9
            else:
                t_end = float(t_start_s)
        else:
            t_end = float(t_end_s)
        t_start = float(t_start_s)

        fired = np.zeros(row_count, dtype=bool)
        crosses = active & (t_start <= tfail) & (t_end > tfail)
        duplicate = active & fired & crosses
        duplicate_indices = np.flatnonzero(duplicate)
        candidate = crosses & ~fired
        candidate_indices = np.flatnonzero(candidate)
        discard_count = int(candidate_indices.size)

        accepted_candidate = active & (t_start <= tfail) & (t_end > tfail) & ~fired
        accepted_indices = np.flatnonzero(accepted_candidate)
        fired[accepted_candidate] = True

        events: list[dict[str, object]] = []
        for idx in candidate_indices:
            events.append(
                {
                    "phase": "candidate_stage",
                    "one_based_cell_id": int(cell_ids[idx]),
                    "tfail": float(tfail[idx]),
                    "gindx": int(gindx[idx]),
                    "fdepth": float(fdepth[idx]),
                    "event_type": rows[idx].get("event_type"),
                    "branch": rows[idx].get("branch"),
                }
            )
        for idx in candidate_indices:
            events.append(
                {
                    "phase": "rejected_discard",
                    "one_based_cell_id": int(cell_ids[idx]),
                    "tfail": float(tfail[idx]),
                    "gindx": int(gindx[idx]),
                    "fdepth": float(fdepth[idx]),
                    "event_type": rows[idx].get("event_type"),
                    "branch": rows[idx].get("branch"),
                }
            )
        for idx in accepted_indices:
            events.append(
                {
                    "phase": "accepted_commit",
                    "one_based_cell_id": int(cell_ids[idx]),
                    "tfail": float(tfail[idx]),
                    "gindx": int(gindx[idx]),
                    "fdepth": float(fdepth[idx]),
                    "event_type": rows[idx].get("event_type"),
                    "branch": rows[idx].get("branch"),
                }
            )
        for idx in duplicate_indices:
            events.append(
                {
                    "phase": "duplicate_prevented",
                    "one_based_cell_id": int(cell_ids[idx]),
                    "tfail": float(tfail[idx]),
                    "gindx": int(gindx[idx]),
                    "fdepth": float(fdepth[idx]),
                    "event_type": rows[idx].get("event_type"),
                    "branch": rows[idx].get("branch"),
                }
            )

        info = {
            "shadow_schedule_loaded": row_count > 0,
            "shadow_schedule_row_count": row_count,
            "shadow_active_row_count": int(np.count_nonzero(active)),
            "shadow_crossing_count": int(np.count_nonzero(crosses)),
            "shadow_candidate_stage_count": int(candidate_indices.size),
            "shadow_rejected_discard_count": discard_count,
            "shadow_accepted_commit_count": int(accepted_indices.size),
            "shadow_duplicate_fire_count": int(duplicate_indices.size),
            "shadow_window_start_s": t_start,
            "shadow_window_end_s": t_end,
            "shadow_candidate_depth_sum": float(np.sum(fdepth[candidate])) if row_count else 0.0,
            "shadow_accepted_depth_sum": float(np.sum(fdepth[accepted_candidate])) if row_count else 0.0,
            "shadow_final_state_mutated": False,
            "schedule_consumed_by_dfs": False,
            "changed_field_names": [],
            "fallback_reason": None,
            "source_meta": dict(source_meta or {}),
            "events": events,
        }
        self.rnoff_provider_shadow_schedule_info = dict(info)
        return dict(info)

    def get_rnoff_provider_schedule_shadow_diagnostics(self) -> dict[str, object]:
        return dict(self.rnoff_provider_shadow_schedule_info)

    @staticmethod
    def _finite_masked_stats(arr: np.ndarray, active_mask: np.ndarray) -> dict[str, float]:
        values = np.asarray(arr, dtype=np.float64)
        valid = active_mask & np.isfinite(values)
        if not np.any(valid):
            return {"sum": 0.0, "max": 0.0}
        selected = values[valid]
        return {
            "sum": float(np.sum(selected)),
            "max": float(np.max(selected)),
        }

    def get_runtime_source_chain_diagnostics(self) -> dict[str, object]:
        """Return post-run diagnostics for failure-source -> solids chain.

        These diagnostics are observational only. They do not alter the DFS
        equations or accepted-step control flow.
        """
        state = self.fields.get_full_state()
        active_mask = ~np.asarray(state["is_nodata"], dtype=bool)

        h_stats = self._finite_masked_stats(state["h"], active_mask)
        cv_stats = self._finite_masked_stats(state["Cv"], active_mask)
        erosion_rate = self.fields.erosion_rate.to_numpy()
        deposition_rate = self.fields.deposition_rate.to_numpy()
        erosion_rate_stats = self._finite_masked_stats(erosion_rate, active_mask)
        deposition_rate_abs_stats = self._finite_masked_stats(np.abs(deposition_rate), active_mask)
        erosion_depth_stats = self._finite_masked_stats(state["erosion_depth"], active_mask)
        deposition_depth_stats = self._finite_masked_stats(state["deposition_depth"], active_mask)
        tempfsh_stats = self._finite_masked_stats(state["tempfsh_flow"], active_mask)
        tempfsrho = np.asarray(state["tempfsrho_flow"], dtype=np.float64)
        tempfsh = np.asarray(state["tempfsh_flow"], dtype=np.float64)
        temp_mass_stats = self._finite_masked_stats(tempfsh * tempfsrho, active_mask)
        erosion_gate = np.asarray(state["erosion_gate_temp"], dtype=np.int32)
        tau_gt_taoc_old = np.asarray(state["tau_gt_taoc_old_temp"], dtype=np.int32)
        tau_gt_taoc_fortran = np.asarray(state["tau_gt_taoc_fortran_temp"], dtype=np.int32)
        all_gate_old = np.asarray(state["all_erosion_gate_old_temp"], dtype=np.int32)
        all_gate_fortran = np.asarray(state["all_erosion_gate_fortran_temp"], dtype=np.int32)
        deposition_gate = np.asarray(state["deposition_gate_temp"], dtype=np.int32)
        rholimit_clamp = np.asarray(state["rholimit_clamp_temp"], dtype=np.int32)
        erodible_clamp = np.asarray(state["erodible_clamp_temp"], dtype=np.int32)
        erorate_raw_stats = self._finite_masked_stats(state["erorate_raw_temp"], active_mask)
        erorate_clamped_stats = self._finite_masked_stats(state["erorate_clamped_temp"], active_mask)
        deporate_raw_stats = self._finite_masked_stats(np.abs(state["deporate_raw_temp"]), active_mask)
        deporate_clamped_stats = self._finite_masked_stats(np.abs(state["deporate_clamped_temp"]), active_mask)

        schedule_info = dict(self.precomputed_failure_schedule_info)
        inflow_info = dict(self.inflow_last_stage_diagnostics)
        stormdrain_info = dict(self.stormdrain_runtime_manifest)
        return {
            "schedule_runtime_diagnostics": schedule_info,
            "inflow_forcing_diagnostics": inflow_info,
            "stormdrain_runtime": stormdrain_info,
            "scheduled_cell_count": int(schedule_info.get("scheduled_cell_count", 0) or 0),
            "consumed_count": int(schedule_info.get("scheduled_cell_count", 0) or 0),
            "fired_cell_count": int(schedule_info.get("fired_cell_count", 0) or 0),
            "candidate_fired_count": int(schedule_info.get("candidate_fired_count", 0) or 0),
            "committed_fired_count": int(schedule_info.get("committed_fired_count", 0) or 0),
            "duplicate_fire_count": int(schedule_info.get("duplicate_fire_count", 0) or 0),
            "rejected_step_discard_count": int(schedule_info.get("rejected_step_discard_count", 0) or 0),
            "crossing_count_by_checkpoint": schedule_info.get("crossing_count_by_checkpoint", {}),
            "last_staged_cell_count": int(schedule_info.get("last_staged_cell_count", 0) or 0),
            "last_staged_depth_sum": float(schedule_info.get("last_staged_depth_sum", 0.0) or 0.0),
            "last_staged_mass_sum": float(schedule_info.get("last_staged_mass_sum", 0.0) or 0.0),
            "failure_source_flow_depth_sum": float(schedule_info.get("total_staged_depth_sum", 0.0) or 0.0),
            "failure_source_mass_sum": float(schedule_info.get("total_staged_mass_sum", 0.0) or 0.0),
            "active_step_tempfsh_sum": tempfsh_stats["sum"],
            "active_step_tempfsh_max": tempfsh_stats["max"],
            "active_step_tempfs_mass_sum": temp_mass_stats["sum"],
            "Cv_max": cv_stats["max"],
            "Cv_sum": cv_stats["sum"],
            "erosion_rate_max": erosion_rate_stats["max"],
            "erosion_rate_sum": erosion_rate_stats["sum"],
            "deposition_rate_max": deposition_rate_abs_stats["max"],
            "deposition_rate_sum": deposition_rate_abs_stats["sum"],
            "erosion_gate_count": int(np.count_nonzero(active_mask & (erosion_gate != 0))),
            "count_tau_gt_taoc_old": int(np.count_nonzero(active_mask & (tau_gt_taoc_old != 0))),
            "count_tau_gt_taoc_fortran": int(np.count_nonzero(active_mask & (tau_gt_taoc_fortran != 0))),
            "count_all_erosion_gates_true_old": int(np.count_nonzero(active_mask & (all_gate_old != 0))),
            "count_all_erosion_gates_true_fortran": int(np.count_nonzero(active_mask & (all_gate_fortran != 0))),
            "deposition_gate_count": int(np.count_nonzero(active_mask & (deposition_gate != 0))),
            "rholimit_clamp_count": int(np.count_nonzero(active_mask & (rholimit_clamp != 0))),
            "erodible_clamp_count": int(np.count_nonzero(active_mask & (erodible_clamp != 0))),
            "erorate_raw_max": erorate_raw_stats["max"],
            "erorate_raw_sum": erorate_raw_stats["sum"],
            "erorate_clamped_max": erorate_clamped_stats["max"],
            "erorate_clamped_sum": erorate_clamped_stats["sum"],
            "deporate_raw_abs_max": deporate_raw_stats["max"],
            "deporate_raw_abs_sum": deporate_raw_stats["sum"],
            "deporate_clamped_abs_max": deporate_clamped_stats["max"],
            "deporate_clamped_abs_sum": deporate_clamped_stats["sum"],
            "Deposit_depth_sum": deposition_depth_stats["sum"],
            "Erosion_depth_sum": erosion_depth_stats["sum"],
            "Flow_depth_sum": h_stats["sum"],
        }

    def _inflow_denominator_for_cell(self, hydrograph: dict[str, object]) -> tuple[float, dict[str, object]]:
        variant = str(self.inflow_denominator_config.get("variant") or "CELLAREA").upper()
        cellarea = float(self.fields.dx * self.fields.dy)
        celsiz = float(self.fields.dx)
        if abs(float(self.fields.dx) - float(self.fields.dy)) > 1.0e-9:
            raise ValueError("Original inflow denominator variants require square cells (dx == dy).")

        if variant == "CELSIZ_DIRECTIONAL_VELOCITY":
            fv_value = self.inflow_denominator_config.get("fv_value")
            direction = self.inflow_denominator_config.get("direction")
            if fv_value is None or direction is None:
                raise ValueError("CELSIZ_DIRECTIONAL_VELOCITY inflow denominator requires source-backed fv direction and value.")
            fv_component = float(fv_value)
            if fv_component <= 0.0:
                raise ValueError("CELSIZ_DIRECTIONAL_VELOCITY inflow denominator requires a positive fv component.")
            denominator = celsiz * fv_component
            return denominator, {
                "variant": variant,
                "denominator_value": denominator,
                "celsiz": celsiz,
                "cellarea": cellarea,
                "fv_direction_if_used": int(direction),
                "fv_component_if_used": fv_component,
            }

        if variant in {"CELLAREA", "CELLAREACAL"}:
            cellareacal_multiplier = float(hydrograph.get("cellareacal_multiplier", 1.0) or 1.0)
            denominator = cellarea * cellareacal_multiplier if variant == "CELLAREACAL" else cellarea
            return denominator, {
                "variant": variant,
                "denominator_value": denominator,
                "celsiz": celsiz,
                "cellarea": cellarea,
                "fv_direction_if_used": None,
                "fv_component_if_used": None,
                "cellareacal_multiplier": cellareacal_multiplier,
            }

        raise ValueError(f"Unsupported inflow denominator variant `{variant}`.")

    def get_inflow_forcing_diagnostics(self) -> dict[str, object]:
        return dict(self.inflow_last_stage_diagnostics)

    def _build_inflow_stage_arrays(self, t_start: float, dt: float) -> tuple[np.ndarray, np.ndarray]:
        tempinflowh = np.zeros((self.fields.nx, self.fields.ny), dtype=np.float64)
        tempinflowrho = np.zeros((self.fields.nx, self.fields.ny), dtype=np.float64)
        if not self.inflow_hydrographs or dt <= 0.0:
            return tempinflowh, tempinflowrho

        tnext = t_start + dt
        diagnostics_samples: list[dict[str, object]] = []
        staged_depth_sum = 0.0
        for hydrograph in self.inflow_hydrographs:
            times = hydrograph["times_s"]
            discharges = hydrograph["discharges_m3s"]
            cvs = hydrograph["cvs"]
            if len(times) < 2 or len(discharges) < 2 or len(cvs) < 2:
                continue
            if t_start >= times[-1]:
                continue

            stage_h = 0.0
            stage_rho = 0.0
            sample_discharge = 0.0
            denominator, denominator_diag = self._inflow_denominator_for_cell(hydrograph)
            for idx in range(len(times) - 1):
                if times[idx] <= t_start and tnext <= times[idx + 1]:
                    sample_discharge = float(discharges[idx + 1])
                    stage_h = sample_discharge * dt / denominator
                    stage_rho = (self.rhos - self.rhow) * cvs[idx + 1] + self.rhow
                    break
                if t_start <= times[idx + 1] <= tnext:
                    if idx <= len(times) - 3:
                        sample_discharge = float(discharges[idx + 1])
                        stage_h = (
                            (times[idx + 1] - t_start) * discharges[idx + 1]
                            + (tnext - times[idx + 1]) * discharges[idx + 2]
                        ) / denominator
                        stage_rho = (self.rhos - self.rhow) * cvs[idx + 1] + self.rhow
                    else:
                        sample_discharge = float(discharges[idx + 1])
                        stage_h = (times[idx + 1] - t_start) * discharges[idx + 1] / denominator
                        stage_rho = (self.rhos - self.rhow) * cvs[idx + 1] + self.rhow
                    break

            if stage_h == 0.0 and stage_rho == 0.0:
                continue
            tempinflowh[hydrograph["i"], hydrograph["j"]] = stage_h
            tempinflowrho[hydrograph["i"], hydrograph["j"]] = stage_rho
            staged_depth_sum += float(stage_h)
            if len(diagnostics_samples) < 10:
                diagnostics_samples.append(
                    {
                        "cell_id": int(hydrograph["cell_id"]),
                        "i": int(hydrograph["i"]),
                        "j": int(hydrograph["j"]),
                        "t_start_s": float(t_start),
                        "tnext_s": float(tnext),
                        "dt_s": float(dt),
                        "discharge_m3s": sample_discharge,
                        "stage_h": float(stage_h),
                        "stage_rho": float(stage_rho),
                        **denominator_diag,
                    }
                )
        self.inflow_last_stage_diagnostics = {
            "configured_cell_count": len(self.inflow_hydrographs),
            "inflow_denominator_variant": self.inflow_denominator_config.get("variant"),
            "denominator_source": self.inflow_denominator_config.get("source"),
            "denominator_basis": self.inflow_denominator_config.get("basis"),
            "sample_count": len(diagnostics_samples),
            "staged_depth_sum": staged_depth_sum,
            "samples": diagnostics_samples,
        }
        return tempinflowh, tempinflowrho

    def _stage_inflow_forcing(self, dt: float) -> None:
        tempinflowh, tempinflowrho = self._build_inflow_stage_arrays(self.current_time, dt)
        self.fields.tempinflowh.from_numpy(tempinflowh.astype(self.numpy_float_dtype, copy=False))
        self.fields.tempinflowrho.from_numpy(tempinflowrho.astype(self.numpy_float_dtype, copy=False))
        if str(self.inflow_denominator_config.get("variant") or "").upper() == "CELSIZ_DIRECTIONAL_VELOCITY":
            direction = self.inflow_denominator_config.get("direction")
            fv_value = self.inflow_denominator_config.get("fv_value")
            if direction is None or fv_value is None:
                raise ValueError("CELSIZ_DIRECTIONAL_VELOCITY inflow forcing requires source-backed fv direction and value.")
            direction_index = int(direction) - 1
            if direction_index < 0 or direction_index >= 8:
                raise ValueError("CELSIZ_DIRECTIONAL_VELOCITY inflow direction must be in Fortran one-based range 1..8.")
            fv_component = float(fv_value)
            if fv_component <= 0.0:
                raise ValueError("CELSIZ_DIRECTIONAL_VELOCITY inflow fv component must be positive.")

            # dfs.F90 assigns `fv(i,4)=5` while staging active inflow forcing,
            # before source-rate and face-flux calculations.  The velocity is
            # therefore an input to the same-step momentum stencil, not only a
            # denominator used to convert discharge into depth.
            fv_state = np.asarray(self.fields.fv_fortran.to_numpy(), dtype=np.float64)
            injected_count = 0
            for hydrograph in self.inflow_hydrographs:
                i = int(hydrograph["i"])
                j = int(hydrograph["j"])
                if tempinflowh[i, j] != 0.0 or tempinflowrho[i, j] != 0.0:
                    fv_state[i, j, direction_index] = fv_component
                    injected_count += 1
            self.fields.fv_fortran.from_numpy(fv_state.astype(self.numpy_float_dtype, copy=False))
            self.inflow_last_stage_diagnostics["directional_velocity_injected_count"] = injected_count
            self.inflow_last_stage_diagnostics["directional_velocity_direction"] = int(direction)
            self.inflow_last_stage_diagnostics["directional_velocity_value"] = fv_component

    def _ensure_legacy_fortran_order_face_pairs(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self._legacy_fortran_order_face_pairs is not None:
            return self._legacy_fortran_order_face_pairs

        connectivity = self._get_flow_connectivity_numpy_cached()
        cell_id = np.asarray(connectivity["cell_id"], dtype=np.int64)
        active = ~np.asarray(self.fields.is_nodata.to_numpy(), dtype=bool)
        if self.runtime_control_plan.strict:
            excluded_source_mask = np.asarray(
                self.fields.dfs_outflow_mask.to_numpy(), dtype=np.int32
            )
        else:
            excluded_source_mask = np.asarray(
                self.fields.boundary_type.to_numpy(), dtype=np.int32
            ) == 1
        neighbor_i = np.asarray(connectivity["flow_neighbor_i"], dtype=np.int32)
        neighbor_j = np.asarray(connectivity["flow_neighbor_j"], dtype=np.int32)
        neighbor_id = np.asarray(connectivity["flow_neighbor_id"], dtype=np.int64)

        source_i: list[int] = []
        source_j: list[int] = []
        target_i: list[int] = []
        target_j: list[int] = []
        active_indices = sorted(
            ((int(cell_id[i, j]), int(i), int(j)) for i, j in zip(*np.where(active))),
            key=lambda item: item[0],
        )
        for source_cell_id, i, j in active_indices:
            if excluded_source_mask[i, j]:
                continue
            for direction in range(8):
                ni = int(neighbor_i[i, j, direction])
                nj = int(neighbor_j[i, j, direction])
                if ni < 0 or nj < 0:
                    continue
                if int(neighbor_id[i, j, direction]) <= 0:
                    continue
                if int(cell_id[ni, nj]) < source_cell_id:
                    continue
                source_i.append(i)
                source_j.append(j)
                target_i.append(ni)
                target_j.append(nj)

        self._legacy_fortran_order_face_pairs = (
            np.asarray(source_i, dtype=np.intp),
            np.asarray(source_j, dtype=np.intp),
            np.asarray(target_i, dtype=np.intp),
            np.asarray(target_j, dtype=np.intp),
        )
        return self._legacy_fortran_order_face_pairs

    def _update_legacy_previous_face_cvbar_scalar(self) -> None:
        source_i, source_j, target_i, target_j = self._ensure_legacy_fortran_order_face_pairs()
        if source_i.size == 0:
            return
        fhpredi = np.asarray(self.fields.fhpredi.to_numpy(), dtype=np.float64)
        frhopredi = np.asarray(self.fields.frhopredi.to_numpy(), dtype=np.float64)
        cell_area = np.asarray(self.fields.cell_area_cal.to_numpy(), dtype=np.float64)
        h_source = fhpredi[source_i, source_j]
        h_target = fhpredi[target_i, target_j]
        area_source = cell_area[source_i, source_j]
        area_target = cell_area[target_i, target_j]
        denominator = h_source + h_target
        valid = (denominator != 0.0) & ~((h_source <= TOL) & (h_target <= TOL))
        if not np.any(valid):
            return
        last_index = int(np.flatnonzero(valid)[-1])
        cv_source = (frhopredi[source_i[last_index], source_j[last_index]] - self.rhow) / (self.rhos - self.rhow)
        cv_target = (frhopredi[target_i[last_index], target_j[last_index]] - self.rhow) / (self.rhos - self.rhow)
        cv_source = max(float(cv_source), 0.0)
        cv_target = max(float(cv_target), 0.0)
        if self.dfs_face_flux_variant == "arithmetic_mean_chamoli":
            area_sum = float(area_source[last_index] + area_target[last_index])
            if area_sum <= 0.0:
                return
            self.legacy_previous_face_cvbar_scalar = (
                cv_source * float(area_source[last_index]) + cv_target * float(area_target[last_index])
            ) / area_sum
            return
        if self.dfs_face_flux_variant == "asymmetric_head_guard":
            self.legacy_previous_face_cvbar_scalar = 0.5 * (cv_source + cv_target)
            return
        # both_thin_weighted / default: depth-weighted Cv matching BJ face flux.
        para_source = cv_source * float(h_source[last_index])
        para_target = cv_target * float(h_target[last_index])
        self.legacy_previous_face_cvbar_scalar = (para_source + para_target) / float(denominator[last_index])

    def step(self, dt: float) -> dict:
        """Perform one DFS step on workspace state without partial main-state commits."""
        if not self.simulate_outflow_cell:
            # Enforce the frozen control even if a checkpoint or external
            # caller supplied a stale sidecar mask after initialization.
            self.fields.dfs_outflow_mask.fill(0)
        if not self._rholimit_seeded:
            if self.rholimit_initialized[None] == 0:
                self._zero_tanslodir_carry()
                self._seed_initial_rholimit_from_input_slope(self.rhow, self.rhos, self.cvstar)
                self.rholimit_initialized[None] = 1
            self._rholimit_seeded = True
        self.workspace.reset_step_workspace()
        if self.use_tanslodir_carry_quirk:
            self.workspace.compute_bed_slope_limiter_with_carry(
                self.tanslodir_carry, self.rhow, self.rhos, self.cvstar
            )
        else:
            self.workspace.compute_bed_slope_limiter(self.rhow, self.rhos, self.cvstar)
        self._ci_candidate = None

        dt_used = float(dt)
        dt_reject = dt_used - self.dt_decrease if self.dt_decrease > 0.0 else dt_used * 0.5
        if dt_reject < self.dt_min:
            dt_reject = self.dt_min

        self._reset_candidate_step_scalars(dt_reject, self.current_time, dt_used)
        if not self.simulate_rainfall:
            if not self._rainfall_zeroed:
                self._zero_rainfall_forcing()
                self._rainfall_zeroed = True
        else:
            self._rainfall_zeroed = False
        self._stage_inflow_forcing(dt_used)
        rnoff_period_precompute_manifest = self.apply_rnoff_period_precompute(dt_used)

        if not self.simulate_infiltration:
            self._stage_surface_forcing_without_infiltration(dt_used, self.rhow, self.cvstar)
        elif self.dfs_infiltration_variant == "direct_rain_plus_storage":
            self._stage_surface_forcing_direct_rain_plus_storage(dt_used, self.rhow, self.cvstar)
        elif self.use_transient_green_ampt:
            self._stage_surface_forcing_green_ampt(dt_used, self.rhow, self.cvstar)
        else:
            self._stage_surface_forcing(dt_used, self.rhow, self.cvstar)
        if self.simulate_infiltration:
            if bool(rnoff_period_precompute_manifest.get("rnoff_period_precompute_enabled", False)):
                self.apply_rnoff_period_precompute_to_surface_staging(dt_used)
            else:
                self.apply_rnoff_topoindex_runtime_hook(dt_used)
        self._record_stage_trace("STEP_START", dt_used, event="STEP_START")
        if self.capture_depo_velocity_snapshots:
            self._capture_depo_velocity_source_entry()
        momentum_probe_enabled = bool(self._momentum_probe_enabled_host)
        momentum_probe_lightweight = bool(self._momentum_probe_lightweight_host)
        if momentum_probe_enabled:
            self.momentum_faceflux_probe_t_start[None] = self.current_time
            self.momentum_faceflux_probe_dt[None] = dt_used
            if momentum_probe_lightweight:
                self._capture_momentum_faceflux_source_entry_state_probe_lightweight()
            else:
                self._capture_momentum_faceflux_source_entry_state_probe()
        if self.capture_depo_velocity_snapshots:
            self._capture_depo_velocity_pre_source_branch()
        self._compute_source_rates(
            dt_used,
            self.rhow,
            self.rhos,
            self.cvstar,
            1 if self.cvbar_erosion_parity_enabled else 0,
            self.legacy_previous_face_cvbar_scalar,
            1 if self.simulate_erosion else 0,
            1 if self.simulate_separate_deposition else 0,
        )
        if self.simulate_shallow_landslide:
            self._advance_double_layer_failure_sources(dt_used)
        else:
            self._zero_failure_source_staging()
        if self.triggerslide_enabled and self.slide1 == 1 and self.current_time > 0.0:
            self._apply_triggerslide_one_shot(self.rhow, self.rhos, self.cvlandslide)
            self.isslidetriggered = 1
        self._record_stage_trace("SOURCE_STAGING", dt_used, event="POST_SOURCE_STAGING")
        self._merge_source_terms(dt_used, self.rhow, self.rhos, self.cvstar)
        self._run_erosion_deposition_kernel_diagnostic_if_enabled(dt_used)
        self._run_erosion_deposition_mutation_if_enabled()
        self._record_stage_trace("POST_SOURCE_MERGE", dt_used, event="POST_SOURCE_MERGE")
        if self.capture_depo_velocity_snapshots:
            self._capture_depo_velocity_before_face_flux()
        if momentum_probe_enabled:
            self.momentum_faceflux_probe_t_start[None] = self.current_time
            self.momentum_faceflux_probe_dt[None] = dt_used
            self._reset_momentum_faceflux_tracked_probe()
        # Lightweight momentum probes must still enter the edge-flux kernel so
        # they can distinguish source-equivalent face gates from post-edge zero
        # states. The `probe_lightweight` template keeps the heavy full-record
        # branch disabled.
        edge_flux_probe_enabled = momentum_probe_enabled
        self._compute_edge_fluxes(
            dt_used,
            self.rhow,
            self.rhos,
            self.limitfr,
            edge_flux_probe_enabled,
            momentum_probe_lightweight,
        )
        self._record_stage_trace("FACE_FLUX", dt_used, event="FACE_FLUX_NQ", face_flux=True)
        self._run_face_flux_kernel_diagnostic_if_enabled()
        if self.cvbar_erosion_parity_enabled:
            self._update_legacy_previous_face_cvbar_scalar()
        if self.experimental_first_reject_short_circuit:
            accepted_early, suggested_dt, max_wave_speed = self._read_step_result_pack()
            if not accepted_early:
                self.experimental_first_reject_early_return_count[None] = (
                    int(self.experimental_first_reject_early_return_count[None]) + 1
                )
                if momentum_probe_enabled:
                    self._mark_momentum_faceflux_probe_rejected_status(1)
                if self.simulate_shallow_landslide and self.double_layer_model is not None:
                    self.double_layer_model.restore_richards_committed_state()
                self._ci_candidate = None
                self._discard_precomputed_failure_candidate()
                return {
                    "accepted": False,
                    "used_dt": dt_used,
                    "suggested_dt": suggested_dt,
                    "next_dt": suggested_dt,
                    "max_wave_speed": max_wave_speed,
                    "experimental_first_reject_short_circuit": True,
                    "first_reject": self.get_first_reject_diagnostics(),
                }
        if momentum_probe_enabled and momentum_probe_lightweight:
            self._capture_momentum_faceflux_post_edge_lightweight(dt_used, self.limitfr)
        if self.capture_depo_velocity_snapshots:
            self._capture_depo_velocity_after_face_flux()
        self._accumulate_and_check(dt_used, self.rhow, self.toldh, self.toldhp)
        self._run_qnet_qmassnet_kernel_diagnostic_if_enabled()
        self._run_qnet_qmassnet_mutation_if_enabled()
        self._run_predictor_diagnostic_if_enabled()
        self._run_predictor_mutation_if_enabled()
        self._record_stage_trace("POST_FLUX", dt_used, event="POST_FLUX")
        if momentum_probe_enabled:
            self._capture_momentum_faceflux_post_accumulate_probe()
        self.apply_stormdrain_runtime_hook(dt_used)
        self._accumulate_volume_balance(dt_used)
        self._finalize_volume_balance(dt_used)
        self._capture_outflow_candidate_before_clear(self.rhow)
        self._apply_post_balance_outflow(self.rhow)

        accepted, suggested_dt, max_wave_speed = self._read_step_result_pack()
        self._record_stage_trace(
            "RETRY_CHECK",
            dt_used,
            event="RETRY_CHECK_ACCEPTED" if accepted else "RETRY_CHECK_REJECTED",
        )
        if momentum_probe_enabled:
            self._mark_momentum_faceflux_probe_rejected_status(0 if accepted else 1)
        if not accepted:
            if self.simulate_shallow_landslide and self.double_layer_model is not None:
                # `dfs.F90` retries rejected dynamic-wave steps from the previously
                # accepted Richards state. Only the temporary candidate arrays are
                # advanced inside the rejected step; the committed `kkt/kkb`
                # fields remain unchanged until acceptance.
                self.double_layer_model.restore_richards_committed_state()
            self._ci_candidate = None
            self._discard_precomputed_failure_candidate()
            return {
                "accepted": False,
                "used_dt": dt_used,
                "suggested_dt": suggested_dt,
                "next_dt": suggested_dt,
                "max_wave_speed": max_wave_speed,
                "experimental_first_reject_short_circuit": False,
                "first_reject": self.get_first_reject_diagnostics(),
            }

        dt_next = dt_used + self.dt_increase if self.dt_increase > 0.0 else dt_used
        if dt_next > self.dt_max:
            dt_next = self.dt_max

        erosion_diag_record: dict[str, object] | None = None
        if self.collect_erosion_step_diagnostics:
            erosion_diag_record = self._make_erosion_step_diagnostic_record(t_start=self.current_time, dt_used=dt_used)

        self._prepare_h_cv_rho_diagnostic_if_enabled()
        self._prepare_h_cv_rho_mutation_if_enabled()
        self._commit_accepted_outflow_candidate()
        self.last_accepted_outflow_dt = dt_used
        self._commit_step(dt_used, dt_next, self.rhow, self.rhos, self.cvstar)
        self._finalize_h_cv_rho_diagnostic_if_enabled()
        self._run_h_cv_rho_mutation_if_enabled()
        self._record_stage_trace(
            "COMMIT",
            dt_used,
            event="COMMIT_ACCEPTED",
            commit_time=True,
            display_dt=dt_next,
        )
        if erosion_diag_record is not None:
            active_mask = ~np.asarray(self.fields.is_nodata.to_numpy(), dtype=bool)
            erosion_sum_after = float(np.sum(self.fields.erosion_depth.to_numpy()[active_mask]))
            deposit_sum_after = float(np.sum(self.fields.deposition_depth.to_numpy()[active_mask]))
            erosion_before = float(erosion_diag_record["Erosion_depth_sum_before_commit"])
            deposit_before = float(erosion_diag_record["Deposit_depth_sum_before_commit"])
            erosion_diag_record["Erosion_depth_sum_after_commit"] = erosion_sum_after
            erosion_diag_record["Deposit_depth_sum_after_commit"] = deposit_sum_after
            erosion_diag_record["actual_Erosion_depth_increment_sum"] = erosion_sum_after - erosion_before
            erosion_diag_record["actual_Deposit_depth_increment_sum"] = deposit_sum_after - deposit_before
            erosion_diag_record["erosion_writeback_residual_sum"] = (
                erosion_diag_record["actual_Erosion_depth_increment_sum"]
                - float(erosion_diag_record["erosion_depth_increment_sum_expected"])
            )
            erosion_diag_record["deposition_writeback_residual_sum"] = (
                erosion_diag_record["actual_Deposit_depth_increment_sum"]
                - float(erosion_diag_record["deposition_depth_increment_sum_expected"])
            )
            self.erosion_step_diagnostics.append(erosion_diag_record)
        if self.simulate_shallow_landslide:
            self._commit_precomputed_failure_schedule()
        if self.isslidetriggered == 1:
            self.slide1 = 0
        self._commit_cumulative_infiltration()
        self._sync_uv_from_fortran_velocity()
        if self.sync_legacy_directional_velocity:
            self._sync_legacy_directional_velocity()

        return {
            "accepted": True,
            "used_dt": dt_used,
            "suggested_dt": float(dt_next),
            "next_dt": float(dt_next),
            "max_wave_speed": max_wave_speed,
            "experimental_first_reject_short_circuit": False,
            "first_reject": {},
        }

    def _read_step_result_pack(self) -> tuple[bool, float, float]:
        self._pack_step_result_scalars()
        pack = np.asarray(self.step_result_pack.to_numpy(), dtype=np.float64)
        return int(pack[0]) == 0, float(pack[1]), float(pack[2])

    @ti.kernel
    def _reset_candidate_step_scalars(self, dt_reject: ti.f64, t_start: ti.f64, dt_used: ti.f64):
        self.reject_flag[None] = 0
        self.suggested_dt[None] = dt_reject
        self.max_wave_speed[None] = 0.0
        self.first_reject_count[None] = 0
        self.first_reject_reason[None] = FIRST_REJECT_NONE
        self.first_reject_source_i[None] = -1
        self.first_reject_source_j[None] = -1
        self.first_reject_neighbor_i[None] = -1
        self.first_reject_neighbor_j[None] = -1
        self.first_reject_cell_id[None] = -1
        self.first_reject_neighbor_cell_id[None] = -1
        self.first_reject_direction[None] = -1
        self.first_reject_t_start[None] = t_start
        self.first_reject_dt[None] = dt_used
        self.first_reject_value[None] = 0.0
        self.first_reject_threshold[None] = 0.0

    @ti.kernel
    def _pack_step_result_scalars(self):
        self.step_result_pack[0] = ti.cast(self.reject_flag[None], ti.f64)
        self.step_result_pack[1] = self.suggested_dt[None]
        self.step_result_pack[2] = self.max_wave_speed[None]

    @ti.kernel
    def _zero_rainfall_forcing(self):
        for i, j in self.fields.rainfall:
            self.fields.rainfall[i, j] = 0.0

    @ti.kernel
    def _zero_failure_source_staging(self):
        for i, j in self.fields.tempfsh_flow:
            self.fields.tempfsh_flow[i, j] = 0.0
            self.fields.tempfsrho_flow[i, j] = 0.0

    @ti.kernel
    def _apply_triggerslide_one_shot(self, rho_water: ti.f64, rho_sediment: ti.f64, cvlandslide: ti.f64):
        """Original `dfs.F90:559-564` one-shot triggering-slide injection.

        if (slide1==1 .and. tnow>0) then
            tempfsh(:)=tempfsh(:)+temptriggerslide(:)
            tempfsrho(:)=(rhos-rhow)*cvlandslide+rhow
            eleori(:)=ele(:)-tempfsh(:)
            isslidetriggered=1
        end if
        """
        for i, j in self.fields.tempfsh_flow:
            if self.fields.is_nodata[i, j]:
                continue
            self.fields.tempfsh_flow[i, j] = self.fields.tempfsh_flow[i, j] + self.triggerslide_field[i, j]
            self.fields.tempfsrho_flow[i, j] = (rho_sediment - rho_water) * cvlandslide + rho_water
            self.fields.z_original[i, j] = self.fields.z_bed[i, j] - self.fields.tempfsh_flow[i, j]

    @ti.kernel
    def _stage_surface_forcing_without_infiltration(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        cvstar: ti.f64,
    ):
        """Original `infilsimul=.false.` branch: `ir=0`, then normal mass staging."""
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.infiltration[i, j] = 0.0
                self.fields.tempri[i, j] = 0.0
                self.fields.tempinflowh[i, j] = 0.0
                self.fields.tempinflowrho[i, j] = 0.0
                self.fields.fhw[i, j] = 0.0
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water
                continue

            self.fields.tempri[i, j] = self.fields.rainfall[i, j]
            self.fields.infiltration[i, j] = 0.0
            self.fields.fhw[i, j] = (
                self.fields.h[i, j] * (1.0 - self.fields.Cv[i, j] / cvstar)
                + self.fields.tempri[i, j] * dt
                + self.fields.tempinflowh[i, j]
            )
            fhpredi1 = (
                self.fields.h[i, j]
                + self.fields.tempri[i, j] * dt
                + self.fields.tempinflowh[i, j]
            )
            if fhpredi1 <= 0.0:
                fhpredi1 = 0.0
            self.fields.fhpredi1[i, j] = fhpredi1
            if fhpredi1 <= EPS:
                self.fields.frhopredi1[i, j] = rho_water
            else:
                mass = (
                    self.fields.rho[i, j] * self.fields.h[i, j]
                    + self.fields.tempri[i, j] * dt * rho_water
                    + self.fields.tempinflowh[i, j] * self.fields.tempinflowrho[i, j]
                )
                self.fields.frhopredi1[i, j] = mass / fhpredi1
            if _is_outflow(self.fields, i, j) == 1:
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water

    @ti.kernel
    def _capture_depo_velocity_source_entry(self):
        for i, j in self.fields.h:
            for d in ti.static(range(8)):
                value = 0.0
                if self.fields.is_nodata[i, j] == 0:
                    value = self.fields.fv_fortran[i, j, d]
                self.fields.depo_velocity_source_entry[i, j, d] = value

    @ti.kernel
    def _capture_depo_velocity_pre_source_branch(self):
        for i, j in self.fields.h:
            for d in ti.static(range(8)):
                value = 0.0
                if self.fields.is_nodata[i, j] == 0:
                    value = self.fields.fv_fortran[i, j, d]
                self.fields.depo_velocity_pre_source_branch[i, j, d] = value

    @ti.kernel
    def _capture_depo_velocity_before_face_flux(self):
        for i, j in self.fields.h:
            for d in ti.static(range(8)):
                value = 0.0
                if self.fields.is_nodata[i, j] == 0:
                    value = self.fields.fv_fortran[i, j, d]
                self.fields.depo_velocity_before_face_flux[i, j, d] = value

    @ti.kernel
    def _capture_depo_velocity_after_face_flux(self):
        for i, j in self.fields.h:
            for d in ti.static(range(8)):
                value = 0.0
                if self.fields.is_nodata[i, j] == 0:
                    value = self.fields.fv_pred_fortran[i, j, d]
                self.fields.depo_velocity_after_face_flux[i, j, d] = value

    @ti.kernel
    def _zero_tanslodir_carry(self):
        for d in self.tanslodir_carry:
            self.tanslodir_carry[d] = 0.0

    @ti.kernel
    def _seed_initial_rholimit_from_input_slope(
        self,
        rho_water: ti.f64,
        rho_sediment: ti.f64,
        cvstar: ti.f64,
    ):
        """
        Seed the persistent DFS `rholimit(i)` array from the input slope grid.

        The supplied `dfs.F90` initializes `cvlimit/rholimit` once before the
        main loop using `slo(i)`, then only updates `rholimit(i)` inside the
        main loop when `tanslo(i)>=0`. Cells with `tanslo(i)<0.` therefore keep
        their previous `rholimit(i)` value instead of snapping back to
        `rho_water`.
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.rholimit_temp[i, j] = rho_water
                continue

            tan_slo = ti.tan(self.fields.slope_angle[i, j])
            tan_phi = ti.tan(self.fields.phi_field[i, j] * DEG2RAD)
            denominator = (rho_sediment - rho_water) * (tan_phi - tan_slo)

            cvlimit = cvstar
            if denominator != 0.0:
                cvlimit = rho_water * tan_slo / denominator
                if cvlimit < DFS_CVLIMIT_BREAK:
                    cvlimit = DFS_CVLIMIT_QUADRATIC_COEFF * cvlimit * cvlimit
                # This one-time seed is an EDDA-Taichi compatibility layer, not
                # a visible statement in dfs.F90. Keep the historical default
                # unless the explicit experiment is requested; the dynamic
                # per-step cvlimit update already uses the source-backed
                # `> cvstar` clamp in dynamic_wave_fortran.py.
                invalid_cvlimit = cvlimit < 0.0 or cvlimit > 1.0
                if ti.static(self.cvlimit_seed_cvstar_clamp_enabled):
                    invalid_cvlimit = cvlimit < 0.0 or cvlimit > cvstar
                if invalid_cvlimit:
                    cvlimit = cvstar

            self.fields.rholimit_temp[i, j] = cvlimit * (rho_sediment - rho_water) + rho_water

    def _stage_surface_forcing_green_ampt(
        self,
        dt: float,
        rho_water: float,
        cvstar: float,
    ) -> None:
        """
        Experimental exact port of the active `dfs.F90 + infr.F90` staging path.

        This path follows the supplied DFS source literally:

        - `fhw = fh*(1-cv/cvstar) + tempinflowh + tempri*dt`
        - `inflx = (fhw - tol) / dt`
        - `where (inflx<0.) inflx=0.`
        - `where (cv>0.1) inflx=0.`
        - `call infr(...)`

        It stays opt-in until the real-case comparison confirms whether this is
        the correct production route for the reference outputs.
        """
        h = self.fields.h.to_numpy().astype(np.float64, copy=False)
        rho = self.fields.rho.to_numpy().astype(np.float64, copy=False)
        rainfall = self.fields.rainfall.to_numpy().astype(np.float64, copy=False)
        nodata = self.fields.is_nodata.to_numpy().astype(bool, copy=False)
        if self.runtime_control_plan.strict:
            outflow = self.fields.dfs_outflow_mask.to_numpy() == 1
        else:
            outflow = self.fields.boundary_type.to_numpy() == 1

        kst = self.fields.K_sat_field.to_numpy().astype(np.float64, copy=False)
        theta_s = self.fields.theta_s_field.to_numpy().astype(np.float64, copy=False)
        theta_i = self.fields.theta_i_field.to_numpy().astype(np.float64, copy=False)
        psi_f = self.fields.psi_f_field.to_numpy().astype(np.float64, copy=False)
        ci = self.fields.F_cumulative.to_numpy().astype(np.float64, copy=False)
        depthwt = self.depthwt0_field.to_numpy().astype(np.float64, copy=False)
        rizero = self.rizero0_field.to_numpy().astype(np.float64, copy=False)

        tempri = rainfall.copy()
        tempinflowh, tempinflowrho = self._build_inflow_stage_arrays(self.current_time, dt)

        cv = self.fields.Cv.to_numpy().astype(np.float64, copy=False).copy()
        cv[nodata] = 0.0

        fhw = h * (1.0 - cv / cvstar) + tempri * dt + tempinflowh

        inflx = np.zeros_like(h)
        if dt > 0.0:
            inflx = (fhw - TOL) / dt
        inflx[inflix := inflx < 0.0] = 0.0
        inflx[cv > CVTOL] = 0.0

        infiltration = np.zeros_like(h)
        ci_next = ci.copy()
        valid = ~nodata
        exfiltration_mask = valid & np.isclose(depthwt, 0.0) & (rizero < 0.0)
        psid = psi_f * (theta_s - theta_i)
        mask = valid & ~exfiltration_mask

        if np.any(mask):
            cinow = ci[mask]
            inflx_m = inflx[mask]
            kst_m = kst[mask]
            psid_m = psid[mask]

            fnow = np.full_like(cinow, 100.0)
            cinow_nonzero = cinow != 0.0
            fnow[cinow_nonzero] = kst_m[cinow_nonzero] * (psid_m[cinow_nonzero] + cinow[cinow_nonzero]) / cinow[cinow_nonzero]

            fave = np.zeros_like(cinow)
            tempci = cinow.copy()

            runoff_begin = fnow <= inflx_m
            if np.any(runoff_begin):
                cinow_rb = cinow[runoff_begin]
                kst_rb = kst_m[runoff_begin]
                psid_rb = psid_m[runoff_begin]
                temp_rb = cinow_rb.copy()
                dci_rb = np.ones_like(temp_rb)
                denom = cinow_rb + psid_rb
                while np.max(np.abs(dci_rb)) >= INFR_TOLERR:
                    cinext_rb = cinow_rb + psid_rb * np.log((temp_rb + psid_rb) / denom) + kst_rb * dt
                    dci_rb = cinext_rb - temp_rb
                    temp_rb = cinext_rb
                fave[runoff_begin] = (temp_rb - cinow_rb) / dt
                tempci[runoff_begin] = temp_rb

            no_runoff_begin = ~runoff_begin
            if np.any(no_runoff_begin):
                cinow_nr = cinow[no_runoff_begin]
                inflx_nr = inflx_m[no_runoff_begin]
                kst_nr = kst_m[no_runoff_begin]
                psid_nr = psid_m[no_runoff_begin]

                tempcinext_nr = cinow_nr + inflx_nr * dt
                ftemp_nr = np.full_like(tempcinext_nr, np.inf)
                positive = tempcinext_nr > 0.0
                ftemp_nr[positive] = kst_nr[positive] * (psid_nr[positive] + tempcinext_nr[positive]) / tempcinext_nr[positive]

                runoff_during = ftemp_nr <= inflx_nr
                if np.any(runoff_during):
                    cinow_rd = cinow_nr[runoff_during]
                    inflx_rd = inflx_nr[runoff_during]
                    kst_rd = kst_nr[runoff_during]
                    psid_rd = psid_nr[runoff_during]

                    cip = kst_rd * psid_rd / (inflx_rd - kst_rd)
                    dtp = (cip - cinow_rd) / inflx_rd
                    temp_rd = kst_rd.copy()
                    dci_rd = np.ones_like(temp_rd)
                    denom = cip + psid_rd
                    while np.max(np.abs(dci_rd)) >= INFR_TOLERR:
                        cinext_rd = cip + psid_rd * np.log((temp_rd + psid_rd) / denom) + kst_rd * (dt - dtp)
                        dci_rd = cinext_rd - temp_rd
                        temp_rd = cinext_rd

                    tmp_fave = fave[no_runoff_begin]
                    tmp_ci = tempci[no_runoff_begin]
                    tmp_fave[runoff_during] = (temp_rd - cinow_rd) / dt
                    tmp_ci[runoff_during] = temp_rd
                    fave[no_runoff_begin] = tmp_fave
                    tempci[no_runoff_begin] = tmp_ci

                no_runoff_all = ~runoff_during
                if np.any(no_runoff_all):
                    tmp_fave = fave[no_runoff_begin]
                    tmp_ci = tempci[no_runoff_begin]
                    tmp_fave[no_runoff_all] = inflx_nr[no_runoff_all]
                    tmp_ci[no_runoff_all] = tempcinext_nr[no_runoff_all]
                    fave[no_runoff_begin] = tmp_fave
                    tempci[no_runoff_begin] = tmp_ci

            infiltration[mask] = fave
            ci_next[mask] = tempci

        fhpredi1 = h + (tempri - infiltration) * dt + tempinflowh
        fhpredi1[fhpredi1 <= 0.0] = 0.0

        frhopredi1 = np.full_like(h, rho_water)
        positive_depth = fhpredi1 > EPS
        if np.any(positive_depth):
            mass = rho * h + (tempri - infiltration) * dt * rho_water + tempinflowh * tempinflowrho
            frhopredi1[positive_depth] = mass[positive_depth] / fhpredi1[positive_depth]

        fhpredi1[outflow] = 0.0
        frhopredi1[outflow] = rho_water
        infiltration[nodata] = 0.0
        fhw[nodata] = 0.0
        ci_next[nodata] = ci[nodata]

        self.fields.tempri.from_numpy(tempri.astype(self.numpy_float_dtype, copy=False))
        self.fields.tempinflowh.from_numpy(tempinflowh.astype(self.numpy_float_dtype, copy=False))
        self.fields.tempinflowrho.from_numpy(tempinflowrho.astype(self.numpy_float_dtype, copy=False))
        self.fields.fhw.from_numpy(fhw.astype(self.numpy_float_dtype, copy=False))
        self.fields.infiltration.from_numpy(infiltration.astype(self.numpy_float_dtype, copy=False))
        self.fields.fhpredi1.from_numpy(fhpredi1.astype(self.numpy_float_dtype, copy=False))
        self.fields.frhopredi1.from_numpy(frhopredi1.astype(self.numpy_float_dtype, copy=False))
        self._ci_candidate = ci_next.astype(self.numpy_float_dtype, copy=False)

    @ti.kernel
    def _stage_surface_forcing_direct_rain_plus_storage(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        cvstar: ti.f64,
    ):
        """
        Port of the NO.5 / NO.8 / Test31 bundled `dfs.F90` infiltration staging:

        - `fhw = fh*(1-cv/cvstar)`
        - `inflx = tempri + (tempinflowh + fhw) / dt`
        - `ir = min(kst, inflx)` except for the water-table-at-surface exfiltration branch

        This differs from the EntireBanzigou-style `tol_clipped_fhw` staging and
        is selected only when the native case bundles the matching `dfs.F90`
        source signature.
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.infiltration[i, j] = 0.0
                self.fields.tempri[i, j] = 0.0
                self.fields.tempinflowh[i, j] = 0.0
                self.fields.tempinflowrho[i, j] = 0.0
                self.fields.fhw[i, j] = 0.0
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water
                continue

            self.fields.tempri[i, j] = self.fields.rainfall[i, j]
            cv = self.fields.Cv[i, j]

            fhw = self.fields.h[i, j] * (1.0 - cv / cvstar)
            self.fields.fhw[i, j] = fhw

            inflx = 0.0
            if dt > 0.0:
                inflx = self.fields.tempri[i, j] + (self.fields.tempinflowh[i, j] + fhw) / dt

            ir = 0.0
            depthwt0 = self.depthwt0_field[i, j]
            rizero0 = self.rizero0_field[i, j]
            if depthwt0 == 0.0 and rizero0 < 0.0:
                ir = 0.0
            else:
                kst = self.fields.K_sat_top_field[i, j]
                if kst < inflx:
                    ir = kst
                else:
                    ir = inflx
            self.fields.infiltration[i, j] = ir

            fhpredi1 = self.fields.h[i, j] + (self.fields.tempri[i, j] - ir) * dt + self.fields.tempinflowh[i, j]
            if fhpredi1 <= 0.0:
                fhpredi1 = 0.0
            self.fields.fhpredi1[i, j] = fhpredi1

            if fhpredi1 <= EPS:
                self.fields.frhopredi1[i, j] = rho_water
            else:
                mass = (
                    self.fields.rho[i, j] * self.fields.h[i, j]
                    + (self.fields.tempri[i, j] - ir) * dt * rho_water
                    + self.fields.tempinflowh[i, j] * self.fields.tempinflowrho[i, j]
                )
                self.fields.frhopredi1[i, j] = mass / fhpredi1

            if _is_outflow(self.fields, i, j) == 1:
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water

    def _commit_cumulative_infiltration(self) -> None:
        if self._ci_candidate is not None:
            self.fields.F_cumulative.from_numpy(self._ci_candidate)
            self._ci_candidate = None

    def _advance_double_layer_failure_sources(self, dt: float) -> None:
        """
        Advance the original EDDA double-layer failure model using `tempir`.

        In dfs.F90 the double-layer model is called after `ir` has been staged,
        with `tempir=ir` and an optional background-flux offset.
        """
        if self.dfs_failure_source_variant == "precomputed_unsfin_schedule":
            self._stage_precomputed_failure_sources(dt)
            return
        if self.double_layer_model is None:
            return

        tempir = self.fields.infiltration.to_numpy().astype(np.float64, copy=False)
        if self.use_background_flux:
            if self.initial_rikzero_field is None:
                raise RuntimeError("Background-flux offset is enabled but initial rikzero field was not provided")
            kst = self.fields.K_sat_top_field.to_numpy().astype(np.float64, copy=False)
            fallback = kst * self.initial_rikzero_field.astype(np.float64, copy=False)
            # Match dfs.F90 literally: `if (tempir(i)==0.) tempir(i)=...`
            tempir = np.where(tempir == 0.0, fallback, tempir)

        tempir = tempir.astype(self.numpy_float_dtype, copy=False)
        self.double_layer_model.solve_richards_equation(dt, tempir)
        self.double_layer_model.compute_pore_pressure()
        self.double_layer_model.find_minimum_fs()
        self.double_layer_model.populate_failure_source_terms(
            cvstar=self.cvstar,
            rho_sediment=self.rhos,
            rho_water=self.rhow,
        )

    def _precomputed_failure_field_staging_ready(self) -> bool:
        return (
            bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_field_gate_enabled", False))
            and bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_field_active", False))
            and bool(self.precomputed_failure_schedule_info.get("rnoff_gpu_field_feed_active", False))
            and bool(self.precomputed_failure_schedule_info.get("taichi_schedule_buffer_roundtrip_ok", False))
            and self.precomputed_failure_tfail_field is not None
            and self.precomputed_failure_gindx_field is not None
            and self.precomputed_failure_fdepth_field is not None
            and self.precomputed_failure_committed_fire_mask_field is not None
            and self.precomputed_failure_candidate_fire_mask_field is not None
            and self.precomputed_failure_source_depth_staging_field is not None
            and self.precomputed_failure_source_density_staging_field is not None
        )

    def _precomputed_failure_kernel_blocked_reason(self) -> str | None:
        if not bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_kernel_gate_enabled", False)):
            return "DFS_SOURCE_STAGING_KERNEL_GATE_NOT_SET"
        if not bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_kernel_required_gates_active", False)):
            return "DFS_SOURCE_STAGING_KERNEL_REQUIRED_GATES_NOT_ACTIVE"
        if not bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_fast_consume_gate_enabled", False)):
            return "DFS_SOURCE_STAGING_FAST_CONSUME_GATE_NOT_SET"
        if not self._precomputed_failure_field_staging_ready():
            return "DFS_SOURCE_STAGING_VALIDATED_FIELDS_NOT_READY"
        if (
            not bool(self._precomputed_failure_fast_consume_validated)
            or self.precomputed_failure_schedule_info.get("source_staging_cpu_vs_taichi_match") is not True
        ):
            return "SOURCE_STAGING_FAST_CONSUME_NOT_VALIDATED"
        return None

    def _precomputed_failure_kernel_staging_ready(self) -> bool:
        return self._precomputed_failure_kernel_blocked_reason() is None

    @ti.kernel
    def _reset_precomputed_failure_source_staging_field_kernel(self):
        self.precomputed_failure_candidate_count_field[None] = 0
        self.precomputed_failure_candidate_depth_sum_field[None] = 0.0
        self.precomputed_failure_candidate_mass_sum_field[None] = 0.0
        for i, j in self.fields.h:
            self.fields.tempfsh_flow[i, j] = 0.0
            self.fields.tempfsrho_flow[i, j] = 0.0
            self.precomputed_failure_candidate_fire_mask_field[i, j] = 0
            self.precomputed_failure_source_depth_staging_field[i, j] = 0.0
            self.precomputed_failure_source_density_staging_field[i, j] = 0.0

    @ti.kernel
    def _stage_precomputed_failure_sources_field_kernel(
        self,
        t_start: ti.f64,
        dt: ti.f64,
        source_rho: ti.f64,
    ):
        t_end = t_start + dt
        for i, j in self.fields.h:
            staged_depth = 0.0
            staged_rho = 0.0
            if (
                self.precomputed_failure_gindx_field[i, j] > 0
                and self.precomputed_failure_committed_fire_mask_field[i, j] == 0
                and t_start <= self.precomputed_failure_tfail_field[i, j]
                and t_end > self.precomputed_failure_tfail_field[i, j]
            ):
                staged_depth = ti.min(
                    self.fields.erodible_thickness[i, j],
                    self.precomputed_failure_fdepth_field[i, j],
                )
                if staged_depth <= 0.0:
                    staged_depth = 0.0
                else:
                    staged_rho = source_rho

            self.fields.tempfsh_flow[i, j] = staged_depth
            self.fields.tempfsrho_flow[i, j] = staged_rho
            self.precomputed_failure_source_depth_staging_field[i, j] = staged_depth
            self.precomputed_failure_source_density_staging_field[i, j] = staged_rho
            if staged_depth > 0.0:
                self.precomputed_failure_candidate_fire_mask_field[i, j] = 1
                ti.atomic_add(self.precomputed_failure_candidate_count_field[None], 1)
                ti.atomic_add(self.precomputed_failure_candidate_depth_sum_field[None], staged_depth)
                ti.atomic_add(self.precomputed_failure_candidate_mass_sum_field[None], staged_depth * staged_rho)

    @ti.kernel
    def _commit_precomputed_failure_candidate_field_kernel(self):
        for i, j in self.fields.h:
            if self.precomputed_failure_candidate_fire_mask_field[i, j] > 0:
                self.precomputed_failure_committed_fire_mask_field[i, j] = 1
            self.precomputed_failure_candidate_fire_mask_field[i, j] = 0

    def _stage_precomputed_failure_sources(self, dt: float) -> None:
        zeros = np.zeros((self.fields.nx, self.fields.ny), dtype=self.numpy_float_dtype)
        if (
            self.precomputed_failure_tfail is None
            or self.precomputed_failure_gindx is None
            or self.precomputed_failure_fdepth is None
            or self.precomputed_failure_fired is None
        ):
            self.fields.tempfsh_flow.from_numpy(zeros)
            self.fields.tempfsrho_flow.from_numpy(zeros)
            self._precomputed_failure_candidate_fired = None
            self._precomputed_failure_candidate_cell_count = 0
            self._precomputed_failure_candidate_depth_sum = 0.0
            self._precomputed_failure_candidate_mass_sum = 0.0
            self._precomputed_failure_candidate_window_end = None
            self.precomputed_failure_schedule_info.update(
                {
                    "candidate_fired_count": 0,
                    "last_staged_cell_count": 0,
                    "last_staged_depth_sum": 0.0,
                    "last_staged_mass_sum": 0.0,
                    "last_window_start_s": float(self.current_time),
                    "last_window_end_s": float(self.current_time + dt),
                }
            )
            return

        t_start = float(self.current_time)
        t_end = t_start + float(dt)
        if self._precomputed_failure_field_staging_ready():
            self.precomputed_failure_schedule_info["candidate_stage_count"] = (
                int(self.precomputed_failure_schedule_info.get("candidate_stage_count", 0) or 0) + 1
            )
            active = self.precomputed_failure_gindx > 0
            unfired = ~self.precomputed_failure_fired
            crosses = (t_start <= self.precomputed_failure_tfail) & (t_end > self.precomputed_failure_tfail)
            duplicate_count = int(np.count_nonzero(active & self.precomputed_failure_fired & crosses))
            source_rho_value = (self.rhos - self.rhow) * self.cvstar + self.rhow
            fast_gate = bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_fast_consume_gate_enabled", False))
            fast_ready = fast_gate and bool(self._precomputed_failure_fast_consume_validated)
            kernel_ready = fast_ready and self._precomputed_failure_kernel_staging_ready()

            self._reset_precomputed_failure_source_staging_field_kernel()
            self._stage_precomputed_failure_sources_field_kernel(t_start, float(dt), source_rho_value)
            if kernel_ready:
                staged_mask = active & unfired & crosses
                erodible = self.fields.erodible_thickness.to_numpy().astype(np.float64, copy=False)
                expected_depth = np.where(staged_mask, np.minimum(erodible, self.precomputed_failure_fdepth), 0.0)
                expected_depth = np.where(expected_depth > 0.0, expected_depth, 0.0)
                expected_rho = np.where(expected_depth > 0.0, source_rho_value, 0.0)
                expected_mask = expected_depth > 0.0
                expected_count = int(np.count_nonzero(expected_mask))
                expected_depth_sum = float(np.sum(expected_depth))
                expected_mass_sum = float(np.sum(expected_depth * expected_rho))
                kernel_count = int(self.precomputed_failure_candidate_count_field[None])
                kernel_depth_sum = float(self.precomputed_failure_candidate_depth_sum_field[None])
                kernel_mass_sum = float(self.precomputed_failure_candidate_mass_sum_field[None])
                scalar_bytes = np.dtype(np.int32).itemsize + (2 * np.dtype(np.float64).itemsize)
                kernel_d2h_bytes = int(erodible.nbytes) + int(scalar_bytes)
                kernel_match = (
                    kernel_count == expected_count
                    and bool(np.isclose(kernel_depth_sum, expected_depth_sum, rtol=1.0e-12, atol=1.0e-12))
                    and bool(np.isclose(kernel_mass_sum, expected_mass_sum, rtol=1.0e-12, atol=1.0e-12))
                )
                self.precomputed_failure_schedule_info["kernel_candidate_stage_count"] = (
                    int(self.precomputed_failure_schedule_info.get("kernel_candidate_stage_count", 0) or 0) + 1
                )
                self.precomputed_failure_schedule_info["kernel_d2h_bytes"] = (
                    int(self.precomputed_failure_schedule_info.get("kernel_d2h_bytes", 0) or 0) + kernel_d2h_bytes
                )
                self.precomputed_failure_schedule_info["transfer_bytes_d2h"] = (
                    int(self.precomputed_failure_schedule_info.get("transfer_bytes_d2h", 0) or 0) + kernel_d2h_bytes
                )
                if not kernel_match:
                    self.fields.tempfsh_flow.from_numpy(expected_depth.astype(self.numpy_float_dtype, copy=False))
                    self.fields.tempfsrho_flow.from_numpy(expected_rho.astype(self.numpy_float_dtype, copy=False))
                    self._precomputed_failure_fast_consume_validated = False
                    candidate_fired = expected_mask
                    staged_count = expected_count
                    staged_depth_sum = expected_depth_sum
                    staged_mass_sum = expected_mass_sum
                    self.precomputed_failure_schedule_info.update(
                        {
                            "dfs_source_staging_field_active": False,
                            "dfs_source_staging_fast_consume_active": False,
                            "dfs_source_staging_kernel_active": False,
                            "source_staging_kernel_vs_cpu_match": False,
                            "kernel_fallback_active": True,
                            "kernel_fallback_reason": "SOURCE_STAGING_KERNEL_CPU_MISMATCH",
                            "cpu_fallback_active": True,
                            "per_stage_parity_download_disabled": False,
                            "source_staging_device_consumed": False,
                        }
                    )
                else:
                    candidate_fired = expected_mask
                    staged_count = expected_count
                    staged_depth_sum = expected_depth_sum
                    staged_mass_sum = expected_mass_sum
                    self.precomputed_failure_schedule_info.update(
                        {
                            "dfs_source_staging_fast_consume_active": True,
                            "dfs_source_staging_kernel_active": True,
                            "source_staging_kernel_vs_cpu_match": True,
                            "kernel_fallback_active": False,
                            "kernel_fallback_reason": None,
                            "per_stage_parity_download_disabled": True,
                            "source_staging_device_consumed": True,
                            "cpu_fallback_active": False,
                            "parity_validation_mode": "first_stage_then_fast_consume",
                        }
                    )
            elif fast_ready:
                candidate_mask_i32 = self.precomputed_failure_candidate_fire_mask_field.to_numpy().astype(
                    np.int32,
                    copy=False,
                )
                candidate_fired = candidate_mask_i32 > 0
                staged_count = int(self.precomputed_failure_candidate_count_field[None])
                staged_depth_sum = float(self.precomputed_failure_candidate_depth_sum_field[None])
                staged_mass_sum = float(self.precomputed_failure_candidate_mass_sum_field[None])
                kernel_blocked_reason = self._precomputed_failure_kernel_blocked_reason()
                self.precomputed_failure_schedule_info.update(
                    {
                        "dfs_source_staging_fast_consume_active": True,
                        "dfs_source_staging_kernel_active": False,
                        "per_stage_parity_download_disabled": True,
                        "source_staging_device_consumed": True,
                        "cpu_fallback_active": False,
                        "parity_validation_mode": "first_stage_then_fast_consume",
                        "kernel_fallback_active": bool(
                            self.precomputed_failure_schedule_info.get("dfs_source_staging_kernel_gate_enabled", False)
                            and kernel_blocked_reason is not None
                        ),
                        "kernel_fallback_reason": (
                            kernel_blocked_reason
                            if bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_kernel_gate_enabled", False))
                            else self.precomputed_failure_schedule_info.get("kernel_fallback_reason")
                        ),
                        "transfer_bytes_d2h": int(
                            self.precomputed_failure_schedule_info.get("transfer_bytes_d2h", 0) or 0
                        )
                        + int(candidate_mask_i32.nbytes),
                    }
                )
            else:
                staged_mask = active & unfired & crosses
                erodible = self.fields.erodible_thickness.to_numpy().astype(np.float64, copy=False)
                expected_depth = np.where(staged_mask, np.minimum(erodible, self.precomputed_failure_fdepth), 0.0)
                expected_depth = np.where(expected_depth > 0.0, expected_depth, 0.0)
                expected_rho = np.where(expected_depth > 0.0, source_rho_value, 0.0)
                parity_download_bytes = int(erodible.nbytes)
                self.precomputed_failure_schedule_info["parity_download_count"] = (
                    int(self.precomputed_failure_schedule_info.get("parity_download_count", 0) or 0) + 1
                )
                field_depth = self.precomputed_failure_source_depth_staging_field.to_numpy().astype(
                    np.float64,
                    copy=False,
                )
                field_rho = self.precomputed_failure_source_density_staging_field.to_numpy().astype(
                    np.float64,
                    copy=False,
                )
                parity_download_bytes += int(field_depth.nbytes) + int(field_rho.nbytes)
                self.precomputed_failure_schedule_info["transfer_bytes_d2h"] = (
                    int(self.precomputed_failure_schedule_info.get("transfer_bytes_d2h", 0) or 0)
                    + parity_download_bytes
                )
                field_mask = field_depth > 0.0
                expected_mask = expected_depth > 0.0
                depth_error = float(np.max(np.abs(field_depth - expected_depth))) if expected_depth.size else 0.0
                rho_error = float(np.max(np.abs(field_rho - expected_rho))) if expected_rho.size else 0.0
                mask_mismatch_count = int(np.count_nonzero(field_mask != expected_mask))
                source_match = (
                    bool(np.array_equal(field_depth, expected_depth))
                    and bool(np.array_equal(field_rho, expected_rho))
                    and mask_mismatch_count == 0
                )
                if not source_match:
                    self.fields.tempfsh_flow.from_numpy(expected_depth.astype(self.numpy_float_dtype, copy=False))
                    self.fields.tempfsrho_flow.from_numpy(expected_rho.astype(self.numpy_float_dtype, copy=False))
                    self._precomputed_failure_fast_consume_validated = False
                    self.precomputed_failure_schedule_info.update(
                        {
                            "dfs_source_staging_field_active": False,
                            "dfs_source_staging_fast_consume_active": False,
                            "source_staging_field_roundtrip_ok": False,
                            "source_staging_cpu_vs_taichi_match": False,
                            "cpu_fallback_active": True,
                            "dfs_source_staging_field_fallback_reason": "SOURCE_STAGING_CPU_TAICHI_MISMATCH",
                            "source_staging_depth_max_abs_error": depth_error,
                            "source_staging_density_max_abs_error": rho_error,
                            "source_staging_candidate_mask_mismatch_count": mask_mismatch_count,
                        }
                    )
                    staged_depth = expected_depth
                    staged_rho = expected_rho
                    candidate_fired = expected_mask
                else:
                    staged_depth = field_depth
                    staged_rho = field_rho
                    candidate_fired = field_mask
                    if fast_gate:
                        self._precomputed_failure_fast_consume_validated = True
                        if bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_kernel_gate_enabled", False)):
                            kernel_blocked_reason = self._precomputed_failure_kernel_blocked_reason()
                            self.precomputed_failure_schedule_info.update(
                                {
                                    "kernel_fallback_active": bool(kernel_blocked_reason is not None),
                                    "kernel_fallback_reason": kernel_blocked_reason,
                                }
                            )
                    self.precomputed_failure_schedule_info.update(
                        {
                            "source_staging_field_roundtrip_ok": True,
                            "source_staging_cpu_vs_taichi_match": True,
                            "dfs_source_staging_field_fallback_reason": None,
                            "source_staging_depth_max_abs_error": depth_error,
                            "source_staging_density_max_abs_error": rho_error,
                            "source_staging_candidate_mask_mismatch_count": mask_mismatch_count,
                        }
                    )
                staged_count = int(np.count_nonzero(candidate_fired))
                staged_depth_sum = float(np.sum(staged_depth))
                staged_mass_sum = float(np.sum(staged_depth * staged_rho))
            self._precomputed_failure_candidate_fired = candidate_fired
            self._precomputed_failure_candidate_cell_count = staged_count
            self._precomputed_failure_candidate_depth_sum = staged_depth_sum
            self._precomputed_failure_candidate_mass_sum = staged_mass_sum
            self._precomputed_failure_candidate_window_end = t_end
            self.precomputed_failure_schedule_info.update(
                {
                    "candidate_fired_count": staged_count,
                    "duplicate_fire_count": int(self.precomputed_failure_schedule_info.get("duplicate_fire_count", 0) or 0) + duplicate_count,
                    "last_staged_cell_count": staged_count,
                    "last_staged_depth_sum": staged_depth_sum,
                    "last_staged_mass_sum": staged_mass_sum,
                    "last_window_start_s": t_start,
                    "last_window_end_s": t_end,
                }
            )
            return

        active = self.precomputed_failure_gindx > 0
        unfired = ~self.precomputed_failure_fired
        crosses = (t_start <= self.precomputed_failure_tfail) & (t_end > self.precomputed_failure_tfail)
        duplicate_count = int(np.count_nonzero(active & self.precomputed_failure_fired & crosses))
        staged_mask = active & unfired & crosses

        erodible = self.fields.erodible_thickness.to_numpy().astype(np.float64, copy=False)
        staged_depth = np.where(staged_mask, np.minimum(erodible, self.precomputed_failure_fdepth), 0.0)
        staged_depth = np.where(staged_depth > 0.0, staged_depth, 0.0)
        staged_rho = np.where(staged_depth > 0.0, (self.rhos - self.rhow) * self.cvstar + self.rhow, 0.0)

        self.fields.tempfsh_flow.from_numpy(staged_depth.astype(self.numpy_float_dtype, copy=False))
        self.fields.tempfsrho_flow.from_numpy(staged_rho.astype(self.numpy_float_dtype, copy=False))
        self._precomputed_failure_candidate_fired = staged_depth > 0.0
        staged_count = int(np.count_nonzero(self._precomputed_failure_candidate_fired))
        staged_depth_sum = float(np.sum(staged_depth))
        staged_mass_sum = float(np.sum(staged_depth * staged_rho))
        self._precomputed_failure_candidate_cell_count = staged_count
        self._precomputed_failure_candidate_depth_sum = staged_depth_sum
        self._precomputed_failure_candidate_mass_sum = staged_mass_sum
        self._precomputed_failure_candidate_window_end = t_end
        self.precomputed_failure_schedule_info.update(
            {
                "candidate_fired_count": staged_count,
                "duplicate_fire_count": int(self.precomputed_failure_schedule_info.get("duplicate_fire_count", 0) or 0) + duplicate_count,
                "last_staged_cell_count": staged_count,
                "last_staged_depth_sum": staged_depth_sum,
                "last_staged_mass_sum": staged_mass_sum,
                "last_window_start_s": t_start,
                "last_window_end_s": t_end,
            }
        )

    def _discard_precomputed_failure_candidate(self) -> None:
        if self._precomputed_failure_candidate_fired is None:
            return
        discarded_count = int(self._precomputed_failure_candidate_cell_count)
        self.precomputed_failure_schedule_info.update(
            {
                "candidate_fired_count": 0,
                "rejected_step_discard_count": int(self.precomputed_failure_schedule_info.get("rejected_step_discard_count", 0) or 0) + discarded_count,
                "dfs_source_staging_kernel_active": False,
            }
        )
        self._precomputed_failure_candidate_fired = None
        self._precomputed_failure_candidate_cell_count = 0
        self._precomputed_failure_candidate_depth_sum = 0.0
        self._precomputed_failure_candidate_mass_sum = 0.0
        self._precomputed_failure_candidate_window_end = None

    def _commit_precomputed_failure_schedule(self) -> None:
        if self.precomputed_failure_fired is None or self._precomputed_failure_candidate_fired is None:
            return
        staged_count = int(self._precomputed_failure_candidate_cell_count)
        staged_depth_sum = float(self._precomputed_failure_candidate_depth_sum)
        staged_mass_sum = float(self._precomputed_failure_candidate_mass_sum)
        if staged_count > 0:
            crossing_counts = dict(self.precomputed_failure_schedule_info.get("crossing_count_by_checkpoint", {}) or {})
            window_end = self._precomputed_failure_candidate_window_end
            checkpoint_key = f"{float(window_end):.6f}" if window_end is not None else "unknown"
            crossing_counts[checkpoint_key] = int(crossing_counts.get(checkpoint_key, 0)) + staged_count
            self.precomputed_failure_schedule_info.update(
                {
                    "total_staged_cell_count": int(self.precomputed_failure_schedule_info.get("total_staged_cell_count", 0) or 0) + staged_count,
                    "total_staged_depth_sum": float(self.precomputed_failure_schedule_info.get("total_staged_depth_sum", 0.0) or 0.0) + staged_depth_sum,
                    "total_staged_mass_sum": float(self.precomputed_failure_schedule_info.get("total_staged_mass_sum", 0.0) or 0.0) + staged_mass_sum,
                    "crossing_count_by_checkpoint": crossing_counts,
                }
            )
        self.precomputed_failure_fired |= self._precomputed_failure_candidate_fired
        if self.precomputed_failure_committed_fire_mask_field is not None:
            if bool(self.precomputed_failure_schedule_info.get("dfs_source_staging_kernel_active", False)):
                self._commit_precomputed_failure_candidate_field_kernel()
            else:
                self.precomputed_failure_committed_fire_mask_field.from_numpy(
                    self.precomputed_failure_fired.astype(np.int32, copy=False)
                )
        fired_count = int(np.count_nonzero(self.precomputed_failure_fired))
        self.precomputed_failure_schedule_info["fired_cell_count"] = fired_count
        self.precomputed_failure_schedule_info["committed_fired_count"] = fired_count
        self.precomputed_failure_schedule_info["candidate_fired_count"] = 0
        self._precomputed_failure_candidate_fired = None
        self._precomputed_failure_candidate_cell_count = 0
        self._precomputed_failure_candidate_depth_sum = 0.0
        self._precomputed_failure_candidate_mass_sum = 0.0
        self._precomputed_failure_candidate_window_end = None

    @ti.kernel
    def _stage_surface_forcing(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        cvstar: ti.f64,
    ):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.infiltration[i, j] = 0.0
                self.fields.tempri[i, j] = 0.0
                self.fields.tempinflowh[i, j] = 0.0
                self.fields.tempinflowrho[i, j] = 0.0
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water
                continue

            self.fields.tempri[i, j] = self.fields.rainfall[i, j]

            # Match dfs.F90 literally: `fhw` is staged from the persisted `cv`
            # array committed at the end of the previous accepted step, rather
            # than re-deriving concentration from `rho/h` inside this step.
            cv = self.fields.Cv[i, j]

            fhw = self.fields.h[i, j] * (1.0 - cv / cvstar) + self.fields.tempri[i, j] * dt + self.fields.tempinflowh[i, j]
            if fhw < TOL:
                fhw = 0.0
            self.fields.fhw[i, j] = fhw

            inflx = 0.0
            if dt > 0.0:
                if self.use_tol_subtracted_inflx:
                    inflx = (fhw - TOL) / dt
                    if inflx < 0.0:
                        inflx = 0.0
                    if cv > CVTOL:
                        inflx = 0.0
                else:
                    inflx = fhw / dt

            ir = 0.0
            depthwt0 = self.depthwt0_field[i, j]
            rizero0 = self.rizero0_field[i, j]
            if depthwt0 == 0.0 and rizero0 < 0.0:
                ir = 0.0
            else:
                kst = self.fields.K_sat_top_field[i, j]
                if kst < inflx:
                    ir = kst
                else:
                    ir = inflx
            self.fields.infiltration[i, j] = ir

            fhpredi1 = self.fields.h[i, j] + (self.fields.tempri[i, j] - ir) * dt + self.fields.tempinflowh[i, j]
            if fhpredi1 <= 0.0:
                fhpredi1 = 0.0
            self.fields.fhpredi1[i, j] = fhpredi1

            if fhpredi1 <= EPS:
                self.fields.frhopredi1[i, j] = rho_water
            else:
                mass = (
                    self.fields.rho[i, j] * self.fields.h[i, j]
                    + (self.fields.tempri[i, j] - ir) * dt * rho_water
                    + self.fields.tempinflowh[i, j] * self.fields.tempinflowrho[i, j]
                )
                self.fields.frhopredi1[i, j] = mass / fhpredi1

            if _is_outflow(self.fields, i, j) == 1:
                self.fields.fhpredi1[i, j] = 0.0
                self.fields.frhopredi1[i, j] = rho_water

    def _compute_source_rates(
        self,
        dt: float,
        rho_water: float,
        rho_sediment: float,
        cvstar: float,
        erosion_cvbar_override_enabled: int = 0,
        erosion_cvbar_override: float = 0.0,
        simulate_erosion: int = 1,
        simulate_separate_deposition: int = 1,
    ) -> None:
        self._compute_source_rates_kernel(
            dt,
            rho_water,
            rho_sediment,
            cvstar,
            int(erosion_cvbar_override_enabled),
            float(erosion_cvbar_override),
            int(simulate_erosion),
            int(simulate_separate_deposition),
        )

    @ti.kernel
    def _compute_source_rates_kernel(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        rho_sediment: ti.f64,
        cvstar: ti.f64,
        erosion_cvbar_override_enabled: ti.i32,
        erosion_cvbar_override: ti.f64,
        simulate_erosion: ti.i32,
        simulate_separate_deposition: ti.i32,
    ):
        rhodepo_cvstar = cvstar * (rho_sediment - rho_water) + rho_water

        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.erosion_rate[i, j] = 0.0
                self.fields.deposition_rate[i, j] = 0.0
                self.fields.absubar_temp[i, j] = 0.0
                self.fields.absubar_vorth_temp[i, j] = 0.0
                self.fields.absubar_vcomp_temp[i, j] = 0.0
                self.fields.absubar_velocity_state_scale_temp[i, j] = 0.0
                self.fields.absubar_selected_is_vorth_temp[i, j] = 0
                self.fields.rhodepo_temp[i, j] = rhodepo_cvstar
                self.fields.tau_temp[i, j] = 0.0
                self.fields.taoc_temp[i, j] = 0.0
                self.fields.taoc_old_temp[i, j] = 0.0
                self.fields.taoc_fortran_temp[i, j] = 0.0
                self.fields.taoc_delta_temp[i, j] = 0.0
                self.fields.tau_minus_taoc_old_temp[i, j] = 0.0
                self.fields.tau_minus_taoc_fortran_temp[i, j] = 0.0
                self.fields.erorate_raw_temp[i, j] = 0.0
                self.fields.erorate_rholimit_clamped_temp[i, j] = 0.0
                self.fields.erorate_clamped_temp[i, j] = 0.0
                self.fields.deporate_raw_temp[i, j] = 0.0
                self.fields.deporate_clamped_temp[i, j] = 0.0
                self.fields.erosion_gate_temp[i, j] = 0
                self.fields.tau_gt_taoc_old_temp[i, j] = 0
                self.fields.tau_gt_taoc_fortran_temp[i, j] = 0
                self.fields.all_erosion_gate_old_temp[i, j] = 0
                self.fields.all_erosion_gate_fortran_temp[i, j] = 0
                self.fields.deposition_gate_temp[i, j] = 0
                self.fields.rholimit_clamp_temp[i, j] = 0
                self.fields.erodible_clamp_temp[i, j] = 0
                self.fields.temp_erodible_thickness[i, j] = self.fields.erodible_thickness[i, j]
                self.fields.temp_depo_thickness[i, j] = self.fields.depo_thickness[i, j]
                for d in ti.static(range(8)):
                    self.fields.absubar_fv_used_temp[i, j, d] = 0.0
                    self.fields.depo_velocity_branch_fv[i, j, d] = 0.0
                    self.fields.depo_velocity_branch_fvpredi[i, j, d] = 0.0
                    self.fields.depo_velocity_branch_fvpredi2[i, j, d] = 0.0
                continue

            cvlimit = self.fields.cvlimit_temp[i, j]
            rholimit = self.fields.rholimit_temp[i, j]
            self.fields.tau_temp[i, j] = 0.0
            self.fields.taoc_temp[i, j] = 0.0
            self.fields.taoc_old_temp[i, j] = 0.0
            self.fields.taoc_fortran_temp[i, j] = 0.0
            self.fields.taoc_delta_temp[i, j] = 0.0
            self.fields.tau_minus_taoc_old_temp[i, j] = 0.0
            self.fields.tau_minus_taoc_fortran_temp[i, j] = 0.0
            self.fields.erorate_raw_temp[i, j] = 0.0
            self.fields.erorate_rholimit_clamped_temp[i, j] = 0.0
            self.fields.erorate_clamped_temp[i, j] = 0.0
            self.fields.deporate_raw_temp[i, j] = 0.0
            self.fields.deporate_clamped_temp[i, j] = 0.0
            self.fields.erosion_gate_temp[i, j] = 0
            self.fields.tau_gt_taoc_old_temp[i, j] = 0
            self.fields.tau_gt_taoc_fortran_temp[i, j] = 0
            self.fields.all_erosion_gate_old_temp[i, j] = 0
            self.fields.all_erosion_gate_fortran_temp[i, j] = 0
            self.fields.deposition_gate_temp[i, j] = 0
            self.fields.rholimit_clamp_temp[i, j] = 0
            self.fields.erodible_clamp_temp[i, j] = 0
            self.fields.temp_erodible_thickness[i, j] = self.fields.erodible_thickness[i, j]
            self.fields.temp_depo_thickness[i, j] = self.fields.depo_thickness[i, j]
            self.fields.absubar_vorth_temp[i, j] = 0.0
            self.fields.absubar_vcomp_temp[i, j] = 0.0
            self.fields.absubar_velocity_state_scale_temp[i, j] = 0.0
            self.fields.absubar_selected_is_vorth_temp[i, j] = 0

            cv = 0.0
            if rho_sediment > rho_water and self.fields.fhpredi1[i, j] > EPS:
                cv = (self.fields.frhopredi1[i, j] - rho_water) / (rho_sediment - rho_water)
            if cv < 0.0:
                cv = 0.0

            fv0 = self.fields.fv_fortran[i, j, 0]
            fv1 = self.fields.fv_fortran[i, j, 1]
            fv2 = self.fields.fv_fortran[i, j, 2]
            fv3 = self.fields.fv_fortran[i, j, 3]
            fv4 = self.fields.fv_fortran[i, j, 4]
            fv5 = self.fields.fv_fortran[i, j, 5]
            fv6 = self.fields.fv_fortran[i, j, 6]
            fv7 = self.fields.fv_fortran[i, j, 7]
            velocity_state_scale = 1.0
            vorth = 0.0
            vcomp = 0.0
            absubar = 0.0
            if ti.static(self.dfs_absubar_variant == "signed_mean_chamoli"):
                # Chamoli dfs.F90:209-212 reconstructs a signed Cartesian speed
                # from raw accepted `fv` (no fvpredi2 0.5 scale) with the
                # Fortran literal 0.707 on diagonals.
                diag = 0.707
                vx = (fv4 - fv0) * 0.5 + (fv3 - fv7) * 0.5 * diag + (fv5 - fv1) * 0.5 * diag
                vy = (fv2 - fv6) * 0.5 + (fv3 - fv7) * 0.5 * diag - (fv5 - fv1) * 0.5 * diag
                absubar = ti.sqrt(vx * vx + vy * vy)
                vorth = absubar
            else:
                if ti.static(self.use_fortran_absubar_velocity_state):
                    # dfs.F90 resets fvpredi before the source-rate branch and
                    # computes fvpredi2=0.5*(fv+fvpredi), so vvmax=1 uses 0.5*fv.
                    velocity_state_scale = 0.5
                fv0 = velocity_state_scale * fv0
                fv1 = velocity_state_scale * fv1
                fv2 = velocity_state_scale * fv2
                fv3 = velocity_state_scale * fv3
                fv4 = velocity_state_scale * fv4
                fv5 = velocity_state_scale * fv5
                fv6 = velocity_state_scale * fv6
                fv7 = velocity_state_scale * fv7
                vorth_x = 0.5 * (ti.abs(fv0) + ti.abs(fv4))
                vorth_y = 0.5 * (ti.abs(fv2) + ti.abs(fv6))
                vorth = ti.sqrt(vorth_x * vorth_x + vorth_y * vorth_y)
                vcomp_x = 0.5 * (ti.abs(fv3) + ti.abs(fv7))
                vcomp_y = 0.5 * (ti.abs(fv1) + ti.abs(fv5))
                vcomp = ti.sqrt(vcomp_x * vcomp_x + vcomp_y * vcomp_y)
                absubar = vorth
                if vcomp > absubar:
                    absubar = vcomp
            self.fields.absubar_temp[i, j] = absubar
            self.fields.absubar_vorth_temp[i, j] = vorth
            self.fields.absubar_vcomp_temp[i, j] = vcomp
            self.fields.absubar_velocity_state_scale_temp[i, j] = velocity_state_scale
            self.fields.absubar_selected_is_vorth_temp[i, j] = 1
            if vcomp > vorth:
                self.fields.absubar_selected_is_vorth_temp[i, j] = 0
            self.fields.absubar_fv_used_temp[i, j, 0] = fv0
            self.fields.absubar_fv_used_temp[i, j, 1] = fv1
            self.fields.absubar_fv_used_temp[i, j, 2] = fv2
            self.fields.absubar_fv_used_temp[i, j, 3] = fv3
            self.fields.absubar_fv_used_temp[i, j, 4] = fv4
            self.fields.absubar_fv_used_temp[i, j, 5] = fv5
            self.fields.absubar_fv_used_temp[i, j, 6] = fv6
            self.fields.absubar_fv_used_temp[i, j, 7] = fv7
            self.fields.depo_velocity_branch_fv[i, j, 0] = self.fields.fv_fortran[i, j, 0]
            self.fields.depo_velocity_branch_fv[i, j, 1] = self.fields.fv_fortran[i, j, 1]
            self.fields.depo_velocity_branch_fv[i, j, 2] = self.fields.fv_fortran[i, j, 2]
            self.fields.depo_velocity_branch_fv[i, j, 3] = self.fields.fv_fortran[i, j, 3]
            self.fields.depo_velocity_branch_fv[i, j, 4] = self.fields.fv_fortran[i, j, 4]
            self.fields.depo_velocity_branch_fv[i, j, 5] = self.fields.fv_fortran[i, j, 5]
            self.fields.depo_velocity_branch_fv[i, j, 6] = self.fields.fv_fortran[i, j, 6]
            self.fields.depo_velocity_branch_fv[i, j, 7] = self.fields.fv_fortran[i, j, 7]
            for d in ti.static(range(8)):
                # dfs.F90 zeros `fvpredi` before source-rate evaluation for
                # vvmax=1. The active branch may still use a scaled `fv`, so
                # the branch `fvpredi2` snapshot records exactly what this
                # current source-rate branch consumed.
                self.fields.depo_velocity_branch_fvpredi[i, j, d] = 0.0
            self.fields.depo_velocity_branch_fvpredi2[i, j, 0] = fv0
            self.fields.depo_velocity_branch_fvpredi2[i, j, 1] = fv1
            self.fields.depo_velocity_branch_fvpredi2[i, j, 2] = fv2
            self.fields.depo_velocity_branch_fvpredi2[i, j, 3] = fv3
            self.fields.depo_velocity_branch_fvpredi2[i, j, 4] = fv4
            self.fields.depo_velocity_branch_fvpredi2[i, j, 5] = fv5
            self.fields.depo_velocity_branch_fvpredi2[i, j, 6] = fv6
            self.fields.depo_velocity_branch_fvpredi2[i, j, 7] = fv7

            fvdepo = 0.0
            if cv > 0.0:
                # Match dfs.F90 literally: `(cvstar/cv(i))**0.333-1`
                lambdainverse = ti.pow(cvstar / cv, DFS_LAMBDA_EXP) - 1.0
                phi_rad = self.fields.phi_field[i, j] * DEG2RAD
                tanthetae = cv * (rho_sediment - rho_water) * ti.tan(phi_rad) / (cv * (rho_sediment - rho_water) + rho_water)
                sinthetae = ti.sin(ti.atan2(tanthetae, 1.0))
                if self.d50 > 0.0:
                    fvdepo = (
                        2.0 / 5.0 / self.d50
                        * ti.sqrt(self.g * sinthetae * self.fields.frhopredi1[i, j] / DFS_ARTIVIS_COEFF / rho_sediment)
                        * lambdainverse
                        * ti.pow(self.fields.fhpredi1[i, j], 1.5)
                    )

            erorate = 0.0
            if cv < cvlimit and self.fields.fhpredi1[i, j] > TOL:
                gammadeb = self.fields.frhopredi1[i, j] * self.g
                phi_rad = self.fields.phi_field[i, j] * DEG2RAD
                # dfs.F90 mutates `slo(i)=atan(tanslo)` from the current water
                # surface gradient before the erosion branch, then reuses that
                # dynamic slope in both yield-stress and taoc calculations.
                slo_dynamic = ti.atan2(self.fields.tanslo_fortran[i, j], 1.0)
                normfriccoe = ti.cos(slo_dynamic) ** 2 * ti.tan(phi_rad)

                sfy = 0.0
                sfy_cv = cv
                if erosion_cvbar_override_enabled != 0:
                    sfy_cv = erosion_cvbar_override
                if sfy_cv > CVTOL:
                    if slo_dynamic > DFS_SLOPE_BRANCH:
                        sfy = (1.0 - self.cs) * sfy_cv * (rho_sediment - rho_water) / self.fields.frhopredi1[i, j] * normfriccoe
                    else:
                        sfy = (
                            self.fields.alpha1_field[i, j]
                            * ti.exp(self.fields.beta1_field[i, j] * sfy_cv)
                            / self.fields.frhopredi1[i, j]
                            / self.g
                            / self.fields.fhpredi1[i, j]
                        )

                miudebris = DFS_MIU_BASE + cv / CVTOL * (
                    self.fields.alpha2_field[i, j] * ti.exp(self.fields.beta2_field[i, j] * CVTOL) - DFS_MIU_BASE
                )
                if cv > CVTOL:
                    miudebris = self.fields.alpha2_field[i, j] * ti.exp(self.fields.beta2_field[i, j] * cv)

                coemiu = self.kresis * miudebris / 8.0 / gammadeb / (self.fields.fhpredi1[i, j] * self.fields.fhpredi1[i, j])
                sfmiu = coemiu * absubar

                manningbar = self.fields.n_manning_field[i, j]
                if cv > CVTOL:
                    if ti.static(self.dfs_manningbar_variant == "debrisflowmanning_cvtol"):
                        manningbar = self.debrisflowmanning
                    else:
                        manningbar = manningbar * self.manningb * ti.exp(self.manningm * cv)
                # Match dfs.F90 literally: `manningbar**2./fhpredi1(i)**1.333`
                coemanning = manningbar * manningbar / ti.pow(self.fields.fhpredi1[i, j], DFS_MANNING_EXP)
                sfmanning = coemanning * absubar * absubar

                tao = (sfmanning + sfy + sfmiu) * gammadeb * self.fields.fhpredi1[i, j]
                taoc_old = self.fields.c_field[i, j] + self.fields.frhopredi1[i, j] * self.g * self.fields.fhpredi1[i, j] * ti.tan(phi_rad)
                taoc = (
                    self.fields.ctao_field[i, j]
                    + (1.0 - self.cs)
                    * cv
                    * (rho_sediment - rho_water)
                    * self.g
                    * self.fields.h[i, j]
                    * ti.cos(slo_dynamic)
                    * ti.cos(slo_dynamic)
                    * ti.tan(phi_rad)
                )
                self.fields.tau_temp[i, j] = tao
                self.fields.taoc_temp[i, j] = taoc
                self.fields.taoc_old_temp[i, j] = taoc_old
                self.fields.taoc_fortran_temp[i, j] = taoc
                self.fields.taoc_delta_temp[i, j] = taoc - taoc_old
                self.fields.tau_minus_taoc_old_temp[i, j] = tao - taoc_old
                self.fields.tau_minus_taoc_fortran_temp[i, j] = tao - taoc
                if tao > taoc_old:
                    self.fields.tau_gt_taoc_old_temp[i, j] = 1
                if tao > taoc:
                    self.fields.tau_gt_taoc_fortran_temp[i, j] = 1
                if cv < cvlimit and self.fields.fhpredi1[i, j] > DFS_EROSION_DEPTH_TRIGGER and tao > taoc_old:
                    self.fields.all_erosion_gate_old_temp[i, j] = 1
                if cv < cvlimit and self.fields.fhpredi1[i, j] > DFS_EROSION_DEPTH_TRIGGER and tao > taoc:
                    self.fields.all_erosion_gate_fortran_temp[i, j] = 1
                if self.fields.fhpredi1[i, j] > DFS_EROSION_DEPTH_TRIGGER and tao > taoc:
                    self.fields.erosion_gate_temp[i, j] = 1
                    erorate = self.fields.kero_field[i, j] * (tao - taoc)
                self.fields.erorate_raw_temp[i, j] = erorate

                # Chamoli dfs.F90:444 rhoero=cvero(zo); BJ dfs.F90:102 rhoero=cvstar.
                cvero_local = self.fields.cvero_field[i, j]
                if cvero_local < 0.0:
                    cvero_local = cvstar
                rhoero = cvero_local * (rho_sediment - rho_water) + rho_water

                if (self.fields.frhopredi1[i, j] * self.fields.fhpredi1[i, j] + erorate * dt * rhoero) > (rholimit * (self.fields.fhpredi1[i, j] + erorate * dt)):
                    denominator = rhoero - rholimit
                    if denominator != 0.0 and dt != 0.0:
                        self.fields.rholimit_clamp_temp[i, j] = 1
                        erorate = (rholimit - self.fields.frhopredi1[i, j]) * self.fields.fhpredi1[i, j] / denominator / dt
                self.fields.erorate_rholimit_clamped_temp[i, j] = erorate

                if erorate * dt <= self.fields.erodible_thickness[i, j]:
                    self.fields.temp_erodible_thickness[i, j] = self.fields.erodible_thickness[i, j] - erorate * dt
                else:
                    self.fields.erodible_clamp_temp[i, j] = 1
                    if dt > 0.0:
                        erorate = self.fields.erodible_thickness[i, j] / dt
                    self.fields.temp_erodible_thickness[i, j] = 0.0
                self.fields.erorate_clamped_temp[i, j] = erorate

            deporate = 0.0
            # Chamoli dfs.F90:113 rhodepo starts from cvstar even when rhoero uses cvero.
            rhodepo = rhodepo_cvstar
            if cv > cvlimit and absubar < DFS_TWO_THIRDS * fvdepo:
                self.fields.deposition_gate_temp[i, j] = 1
                deporate = self.coedepo * (1.0 - 1.5 * absubar / fvdepo) * (cvlimit - cv) / cvstar * absubar
                self.fields.deporate_raw_temp[i, j] = deporate
                if ti.abs(deporate * dt) > self.fields.fhpredi1[i, j] and dt > 0.0:
                    deporate = -self.fields.fhpredi1[i, j] / dt
                if ti.abs(deporate * dt * rhodepo) > self.fields.fhpredi1[i, j] * self.fields.frhopredi1[i, j]:
                    denominator = deporate * dt
                    if denominator != 0.0:
                        rhodepo = -self.fields.fhpredi1[i, j] * self.fields.frhopredi1[i, j] / denominator
                if (self.fields.frhopredi1[i, j] * self.fields.fhpredi1[i, j] + deporate * dt * rhodepo) < (rho_water * (self.fields.fhpredi1[i, j] + deporate * dt)):
                    denominator = rhodepo - rho_water
                    if denominator != 0.0 and dt != 0.0:
                        deporate = (rho_water - self.fields.frhopredi1[i, j]) * self.fields.fhpredi1[i, j] / denominator / dt
                self.fields.temp_depo_thickness[i, j] = self.fields.depo_thickness[i, j] + ti.abs(deporate * dt)
                self.fields.deporate_clamped_temp[i, j] = deporate

            if simulate_erosion == 0:
                erorate = 0.0
                self.fields.erosion_gate_temp[i, j] = 0
                self.fields.erorate_raw_temp[i, j] = 0.0
                self.fields.erorate_rholimit_clamped_temp[i, j] = 0.0
                self.fields.erorate_clamped_temp[i, j] = 0.0
                self.fields.temp_erodible_thickness[i, j] = self.fields.erodible_thickness[i, j]
            if simulate_separate_deposition == 0:
                deporate = 0.0
                self.fields.deposition_gate_temp[i, j] = 0
                self.fields.deporate_raw_temp[i, j] = 0.0
                self.fields.deporate_clamped_temp[i, j] = 0.0
                self.fields.temp_depo_thickness[i, j] = self.fields.depo_thickness[i, j]

            self.fields.erosion_rate[i, j] = erorate
            self.fields.deposition_rate[i, j] = deporate
            self.fields.rhodepo_temp[i, j] = rhodepo

    @ti.kernel
    def _merge_source_terms(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        rho_sediment: ti.f64,
        cvstar: ti.f64,
    ):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.tempele[i, j] = self.fields.z_bed[i, j]
                self.fields.fhpredi[i, j] = 0.0
                self.fields.frhopredi[i, j] = rho_water
                continue

            self.fields.tempele[i, j] = (
                self.fields.z_bed[i, j]
                - self.fields.erosion_rate[i, j] * dt
                + ti.abs(self.fields.deposition_rate[i, j]) * dt
                - self.fields.tempfsh_flow[i, j]
            )

            fhpredi = (
                self.fields.fhpredi1[i, j]
                + (self.fields.erosion_rate[i, j] + self.fields.deposition_rate[i, j]) * dt
                + self.fields.tempfsh_flow[i, j]
            )
            if fhpredi <= 0.0:
                self.fields.fhpredi[i, j] = 0.0
                self.fields.frhopredi[i, j] = rho_water
            else:
                self.fields.fhpredi[i, j] = fhpredi
                # Chamoli dfs.F90:572 uses per-cell cvero for the erosion mass term.
                cvero_local = self.fields.cvero_field[i, j]
                if cvero_local < 0.0:
                    cvero_local = cvstar
                rhoero = cvero_local * (rho_sediment - rho_water) + rho_water
                mass = (
                    self.fields.frhopredi1[i, j] * self.fields.fhpredi1[i, j]
                    + self.fields.erosion_rate[i, j] * dt * rhoero
                    + self.fields.deposition_rate[i, j] * dt * self.fields.rhodepo_temp[i, j]
                    + self.fields.tempfsh_flow[i, j] * self.fields.tempfsrho_flow[i, j]
                )
                self.fields.frhopredi[i, j] = mass / fhpredi
                if self.fields.fhpredi[i, j] <= EPS:
                    self.fields.frhopredi[i, j] = rho_water

            if _is_outflow(self.fields, i, j) == 1:
                self.fields.fhpredi[i, j] = 0.0
                self.fields.frhopredi[i, j] = rho_water

    @ti.kernel
    def _compute_edge_fluxes(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        rho_sediment: ti.f64,
        limitfr: ti.f64,
        probe_enabled: ti.template(),
        probe_lightweight: ti.template(),
    ):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            for d in ti.static(range(8)):
                self.fields.fv_pred_fortran[i, j, d] = 0.0
                self.fields.qq_fortran[i, j, d] = 0.0
                self.fields.qqt_fortran[i, j, d] = 0.0
                self.fields.qqmass_fortran[i, j, d] = 0.0
                self.fields.fybar_fortran[i, j, d] = 0.0

        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            for d in ti.static(range(8)):
                ni = self.fields.flow_neighbor_i[i, j, d]
                nj = self.fields.flow_neighbor_j[i, j, d]
                if ni >= 0 and nj >= 0:
                    # Active dfs.F90 source uses:
                    #
                    #   nq=fp(i,ii)
                    #   if (nq<i) cycle
                    #
                    # Therefore the lower-index cell computes the shared face
                    # and mirrors flux/velocity to the neighbor's opposite
                    # face.  The old max/later-cell branch is retained only
                    # for archaeology/ablation via explicit
                    # EDDA_EXPERIMENT_DFS_FORTRAN_FACE_OWNER_MAX_CELL=1.
                    face_owner_active = self.fields.cell_id[ni, nj] > self.fields.cell_id[i, j]
                    if ti.static(self.fortran_face_owner_max_cell_enabled):
                        face_owner_active = self.fields.cell_id[i, j] > self.fields.cell_id[ni, nj]
                    if face_owner_active:
                        opp = ti.static(FORTRAN_OPPOSITE_DIR[d])
                        dt0 = 0.0

                        hi = self.fields.fhpredi[i, j] + self.fields.tempele[i, j]
                        hn = self.fields.fhpredi[ni, nj] + self.fields.tempele[ni, nj]
                        use_both_thin_weighted = ti.static(self.dfs_face_flux_variant == "both_thin_weighted")
                        use_arithmetic_mean_chamoli = ti.static(
                            self.dfs_face_flux_variant == "arithmetic_mean_chamoli"
                        )
                        use_both_thin_gate = ti.static(use_both_thin_weighted or use_arithmetic_mean_chamoli)
                        use_weighted_hbar = ti.static(use_both_thin_weighted or use_arithmetic_mean_chamoli)
                        use_uniform_diagonal_width = ti.static(
                            use_both_thin_weighted or use_arithmetic_mean_chamoli
                        )
                        face_gate_tol = TOL + ti.static(self.dfs_face_gate_tol_eps)

                        gate_blocks_face = False
                        if ti.static(self.original_live_moving_thin_face_gate_compat_enabled):
                            # Original-live 1s 20a evidence at the first large
                            # velocity divergence (2619s, cell 44637) follows
                            # the moving-thin face gate preserved in dfs.F90 as
                            # the alternate condition:
                            #
                            #   if ((fhpredi(i)<=tol .and. hi>=hn) .or.
                            #       (fhpredi(nq)<=tol .and. hn>=hi)) cycle
                            #
                            # Keep the source-backed weighted hbar/cvbar/frhobar
                            # calculations for active faces, but use the
                            # original-live moving-thin gate when this explicit
                            # compatibility flag is enabled.
                            gate_blocks_face = (
                                (self.fields.fhpredi[i, j] <= face_gate_tol and hi >= hn)
                                or (self.fields.fhpredi[ni, nj] <= face_gate_tol and hn >= hi)
                            )
                        elif ti.static(use_both_thin_gate):
                            gate_blocks_face = (
                                self.fields.fhpredi[i, j] <= face_gate_tol
                                and self.fields.fhpredi[ni, nj] <= face_gate_tol
                            )
                        else:
                            gate_blocks_face = (
                                (self.fields.fhpredi[i, j] <= face_gate_tol and hi >= hn)
                                or (self.fields.fhpredi[ni, nj] <= face_gate_tol and hn >= hi)
                            )

                        if gate_blocks_face:
                            if ti.static(probe_enabled):
                                target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
                                target_direction = self.momentum_faceflux_probe_target_direction[None]
                                if (
                                    self.fields.cell_id[i, j] == target_cell_id
                                    and (target_direction < 0 or d == target_direction)
                                ):
                                    self._record_momentum_faceflux_probe_lightweight(
                                        7,
                                        i,
                                        j,
                                        ni,
                                        nj,
                                        i,
                                        j,
                                        d,
                                        opp,
                                        1,
                                        0,
                                        0,
                                        hi,
                                        hn,
                                        0.0,
                                        0.0,
                                        self.fields.fhpredi[i, j],
                                        self.fields.fhpredi[ni, nj],
                                        self.fields.frhopredi[i, j],
                                        self.fields.frhopredi[ni, nj],
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                    )
                                if (
                                    self.fields.cell_id[ni, nj] == target_cell_id
                                    and (target_direction < 0 or opp == target_direction)
                                ):
                                    self._record_momentum_faceflux_probe_lightweight(
                                        7,
                                        i,
                                        j,
                                        ni,
                                        nj,
                                        ni,
                                        nj,
                                        d,
                                        opp,
                                        1,
                                        0,
                                        0,
                                        hi,
                                        hn,
                                        0.0,
                                        0.0,
                                        self.fields.fhpredi[i, j],
                                        self.fields.fhpredi[ni, nj],
                                        self.fields.frhopredi[i, j],
                                        self.fields.frhopredi[ni, nj],
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                        0.0,
                                    )

                        if not gate_blocks_face:
                            ds = _direction_spacing(self.fields.dx, d)
                            # Keep the same arithmetic grouping used by
                            # dfs.F90. In thin-front cells, even tiny grouping
                            # changes can move a face across the `tol` gate a
                            # step earlier or later.
                            grad = 0.0
                            if d == 0 or d == 2 or d == 4 or d == 6:
                                grad = (hn - hi) / self.fields.dx
                            else:
                                grad = (hn - hi) / self.fields.dx / SQRT2
                            area_i = self.fields.cell_area_cal[i, j]
                            area_n = self.fields.cell_area_cal[ni, nj]
                            hbar = 0.5 * (self.fields.fhpredi[i, j] + self.fields.fhpredi[ni, nj])
                            if ti.static(use_weighted_hbar):
                                hbar = (
                                    self.fields.fhpredi[i, j] * area_i
                                    + self.fields.fhpredi[ni, nj] * area_n
                                ) / (area_i + area_n)
                            ybar = hbar
                            self.fields.fybar_fortran[i, j, d] = ybar

                            fvpred = 0.0
                            frhoflux = rho_water
                            cv_source = 0.0
                            cv_neighbor = 0.0
                            cvbar = 0.0
                            miubar = 0.0
                            manningbar = 0.0
                            frhobar = rho_water
                            gammadeb = rho_water * self.g
                            sfy = 0.0
                            sfmiu = 0.0
                            sfmanning = 0.0
                            sf = 0.0
                            localvdiff = 0.0
                            artivis = 0.0
                            vdiff_term = 0.0
                            dv = 0.0
                            fv_old = self.fields.fv_fortran[i, j, d]
                            fvpred_before_clamp = 0.0
                            clamp_status = 0
                            sign_flip_status = 0
                            fvlimit = 0.0
                            yflux = 0.0
                            width = 0.0
                            qqt = 0.0
                            qq = 0.0
                            qqmass = 0.0
                            source_depth_rate = 0.0
                            if ybar != 0.0:
                                cv_source = (self.fields.frhopredi[i, j] - rho_water) / (rho_sediment - rho_water)
                                cv_neighbor = (self.fields.frhopredi[ni, nj] - rho_water) / (rho_sediment - rho_water)
                                if cv_source < 0.0:
                                    cv_source = 0.0
                                if cv_neighbor < 0.0:
                                    cv_neighbor = 0.0

                                cvbar = 0.5 * (cv_source + cv_neighbor)
                                if ti.static(use_both_thin_weighted):
                                    parai = cv_source * self.fields.fhpredi[i, j]
                                    paran = cv_neighbor * self.fields.fhpredi[ni, nj]
                                    depth_area = (
                                        self.fields.fhpredi[i, j] * area_i
                                        + self.fields.fhpredi[ni, nj] * area_n
                                    )
                                    if depth_area > 0.0:
                                        cvbar = (parai * area_i + paran * area_n) / depth_area
                                elif ti.static(use_arithmetic_mean_chamoli):
                                    # Chamoli dfs.F90:634 — area-mean Cv without depth weighting.
                                    cvbar = (cv_source * area_i + cv_neighbor * area_n) / (area_i + area_n)

                                miubar = DFS_MIU_BASE + cvbar / CVTOL * (
                                    self.fields.alpha2_field[i, j] * ti.exp(self.fields.beta2_field[i, j] * CVTOL) - DFS_MIU_BASE
                                )
                                if cvbar >= CVTOL:
                                    miubar = self.fields.alpha2_field[i, j] * ti.exp(self.fields.beta2_field[i, j] * cvbar)

                                manningbar = 0.5 * (ti.abs(self.fields.n_manning_field[i, j]) + ti.abs(self.fields.n_manning_field[ni, nj]))
                                if cvbar > CVTOL:
                                    if ti.static(self.dfs_manningbar_variant != "debrisflowmanning_cvtol"):
                                        manningbar = manningbar * self.manningb * ti.exp(self.manningm * cvbar)

                                frhobar = 0.5 * (self.fields.frhopredi[i, j] + self.fields.frhopredi[ni, nj])
                                if ti.static(use_both_thin_weighted):
                                    depth_area = (
                                        self.fields.fhpredi[i, j] * area_i
                                        + self.fields.fhpredi[ni, nj] * area_n
                                    )
                                    if depth_area > 0.0:
                                        frhobar = (
                                            self.fields.frhopredi[i, j] * self.fields.fhpredi[i, j] * area_i
                                            + self.fields.frhopredi[ni, nj] * self.fields.fhpredi[ni, nj] * area_n
                                        ) / depth_area
                                # arithmetic_mean_chamoli and asymmetric keep 0.5*(ρi+ρnq).
                                if frhobar < rho_water:
                                    frhobar = rho_water
                                gammadeb = frhobar * self.g

                                cosslope = ti.cos(ti.atan2(ti.abs(grad), 1.0))
                                normfric_i = cosslope * cosslope * ti.tan(self.fields.phi_field[i, j] * DEG2RAD)
                                normfric_n = cosslope * cosslope * ti.tan(self.fields.phi_field[ni, nj] * DEG2RAD)
                                normfric_bar = 0.5 * (normfric_i + normfric_n)

                                if cvbar > CVTOL:
                                    # dfs.F90 uses the dynamic `slo(i)` updated
                                    # from the current water-surface gradient,
                                    # not the static input slope angle, to
                                    # select the yield-stress branch.
                                    slo_dynamic = ti.atan2(self.fields.tanslo_fortran[i, j], 1.0)
                                    if slo_dynamic > DFS_SLOPE_BRANCH:
                                        sfy = (1.0 - self.cs) * cvbar * (rho_sediment - rho_water) / frhobar * normfric_bar
                                    else:
                                        sfy = self.fields.alpha1_field[i, j] * ti.exp(self.fields.beta1_field[i, j] * cvbar) / frhobar / self.g / ybar

                                # Match dfs.F90 literally:
                                # `if (sfy>=abs(grad) .and. abs(fv(i,ii))<=eps) then`
                                if sfy >= ti.abs(grad) and ti.abs(fv_old) <= EPS:
                                    fvpred = 0.0
                                else:
                                    sfmiu = self.kresis * miubar / (8.0 * frhobar * self.g * ybar * ybar) * ti.abs(fv_old)
                                    # Match dfs.F90 literally: `manningbar**2./ybar**1.333*abs(fv(i,ii))**2.`
                                    sfmanning = manningbar * manningbar / ti.pow(ybar, DFS_MANNING_EXP) * ti.abs(fv_old) * ti.abs(fv_old)
                                    sf = sfy + sfmiu + sfmanning
                                    if fv_old == 0.0:
                                        sf = _signed_magnitude(sf, -grad)
                                    else:
                                        sf = _signed_magnitude(sf, fv_old)

                                    localvdiff = 0.5 * (self.fields.fv_fortran[ni, nj, d] + self.fields.fv_fortran[i, j, opp])
                                    artivis = self.fields.fv_fortran[ni, nj, d] - 2.0 * self.fields.fv_fortran[i, j, d] - self.fields.fv_fortran[i, j, opp]

                                    vdiff_term = 0.0
                                    if d == 0 or d == 2 or d == 4 or d == 6:
                                        vdiff_term = fv_old * localvdiff / self.fields.dx / self.g
                                    else:
                                        vdiff_term = fv_old * localvdiff / self.fields.dx / self.g / SQRT2

                                    source_depth_rate = (
                                        self.fields.tempfsh_flow[i, j] / dt
                                        + self.fields.erosion_rate[i, j]
                                        + self.fields.deposition_rate[i, j]
                                    )
                                    artivis_weight = (
                                        DFS_ARTIVIS_COEFF
                                        * ti.abs(self.fields.fhpredi[i, j] - self.fields.fhpredi[ni, nj])
                                        / (self.fields.fhpredi[i, j] + self.fields.fhpredi[ni, nj])
                                    )
                                    if ti.static(self.dfs_artivis_variant == "velocity_ratio_chamoli"):
                                        fv_neighbor = self.fields.fv_fortran[ni, nj, d]
                                        artivis_weight = (
                                            DFS_ARTIVIS_COEFF
                                            * ti.abs(fv_neighbor - fv_old)
                                            / (ti.abs(fv_neighbor) + ti.abs(fv_old) + 1.0)
                                        )
                                        if not (d == 0 or d == 2 or d == 4 or d == 6):
                                            artivis_weight = artivis_weight / SQRT2
                                    dv = (
                                        (-grad - sf - vdiff_term) * self.g * dt
                                        + artivis_weight * artivis
                                        - fv_old * source_depth_rate * dt / ybar
                                    )
                                    fvpred = dv + fv_old

                                    if ti.static(self.dfs_dry_face_velocity_variant == "zero_dry_face_chamoli"):
                                        # Chamoli dfs.F90:736-737, after fvpredi=dv+fv and
                                        # before the sign-reversal check.
                                        if fvpred < 0.0 and self.fields.fhpredi[ni, nj] <= TOL:
                                            fvpred = 0.0
                                        if fvpred > 0.0 and self.fields.fhpredi[i, j] <= TOL:
                                            fvpred = 0.0

                                    if fv_old * fvpred < 0.0:
                                        dt0 = -fv_old / (dv / dt)
                                        sign_flip_status = 1
                                        if sfy >= ti.abs(grad):
                                            fvpred = 0.0
                                        else:
                                            sfy = _signed_magnitude(sfy, -grad)
                                            fvpred = (-grad - sfy) * self.g * (dt - dt0)

                                fvlimit = limitfr * ti.sqrt(self.g * ybar)
                                fvpred_before_clamp = fvpred
                                if ti.abs(fvpred) > fvlimit:
                                    fvpred = _signed_magnitude(fvlimit, fvpred)
                                    clamp_status = 1

                                self.fields.fv_pred_fortran[i, j, d] = fvpred

                                vel = ti.abs(fvpred)
                                wave = vel + ti.sqrt(self.g * ybar)
                                ti.atomic_max(self.max_wave_speed[None], wave)

                                # In dfs.F90 the statement `if (vel>3.5) then continue`
                                # uses Fortran `continue`, which is a no-op, not loop control.
                                # The original solver therefore still computes CFL tests,
                                # discharge, and mirrored opposite-face states for large
                                # velocities. Keep that exact control flow here.
                                if d == 0 or d == 2 or d == 4 or d == 6:
                                    dttest = DFS_CFL_COEFF * self.fields.dx / (vel + ti.sqrt(self.g * ybar))
                                    if dt > dttest:
                                        self.reject_flag[None] = 1
                                        self._record_first_reject(FIRST_REJECT_CFL, i, j, ni, nj, d, dt, dttest)
                                else:
                                    dttest = DFS_CFL_COEFF * self.fields.dx * SQRT2 / (vel + ti.sqrt(self.g * ybar))
                                    if dt > dttest:
                                        self.reject_flag[None] = 1
                                        self._record_first_reject(FIRST_REJECT_CFL, i, j, ni, nj, d, dt, dttest)

                                yflux = 0.0
                                if fvpred >= 0.0:
                                    yflux = ti.min(self.fields.fhpredi[i, j], hbar)
                                    frhoflux = self.fields.frhopredi[i, j]
                                else:
                                    yflux = ti.min(self.fields.fhpredi[ni, nj], hbar)
                                    frhoflux = self.fields.frhopredi[ni, nj]
                                width = _direction_width(self.fields.dx, d)
                                if ti.static(use_uniform_diagonal_width):
                                    width = self.fields.dx * (SQRT2 - 1.0)
                                qqt = fvpred * yflux * width
                                qq = qqt * (dt - dt0)
                                qqmass = frhoflux * qq

                                if ti.static(probe_enabled and probe_lightweight):
                                    target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
                                    target_direction = self.momentum_faceflux_probe_target_direction[None]
                                    if (
                                        self.fields.cell_id[i, j] == target_cell_id
                                        and (target_direction < 0 or d == target_direction)
                                    ):
                                        self._record_momentum_faceflux_probe_lightweight(
                                            1,
                                            i,
                                            j,
                                            ni,
                                            nj,
                                            i,
                                            j,
                                            d,
                                            opp,
                                            0,
                                            clamp_status,
                                            sign_flip_status,
                                            hi,
                                            hn,
                                            hbar,
                                            ybar,
                                            self.fields.fhpredi[i, j],
                                            self.fields.fhpredi[ni, nj],
                                            self.fields.frhopredi[i, j],
                                            self.fields.frhopredi[ni, nj],
                                            dv,
                                            fv_old,
                                            fvpred_before_clamp,
                                            fvpred,
                                            fvlimit,
                                            qqt,
                                            qq,
                                            qqmass,
                                            frhoflux,
                                            yflux,
                                            width,
                                            dt0,
                                        )
                                    if (
                                        self.fields.cell_id[ni, nj] == target_cell_id
                                        and (target_direction < 0 or opp == target_direction)
                                    ):
                                        self._record_momentum_faceflux_probe_lightweight(
                                            2,
                                            i,
                                            j,
                                            ni,
                                            nj,
                                            ni,
                                            nj,
                                            d,
                                            opp,
                                            0,
                                            clamp_status,
                                            sign_flip_status,
                                            hi,
                                            hn,
                                            hbar,
                                            ybar,
                                            self.fields.fhpredi[i, j],
                                            self.fields.fhpredi[ni, nj],
                                            self.fields.frhopredi[i, j],
                                            self.fields.frhopredi[ni, nj],
                                            dv,
                                            fv_old,
                                            fvpred_before_clamp,
                                            -fvpred,
                                            fvlimit,
                                            -qqt,
                                            -qq,
                                            -qqmass,
                                            frhoflux,
                                            yflux,
                                            width,
                                            dt0,
                                        )

                                if ti.static(probe_enabled and not probe_lightweight):
                                    target_cell_id = self.momentum_faceflux_probe_target_cell_id[None]
                                    target_direction = self.momentum_faceflux_probe_target_direction[None]
                                    if (
                                        self.fields.cell_id[i, j] == target_cell_id
                                        and (target_direction < 0 or d == target_direction)
                                    ):
                                        self._record_momentum_faceflux_probe(
                                            1,
                                            i,
                                            j,
                                            ni,
                                            nj,
                                            i,
                                            j,
                                            d,
                                            opp,
                                            0,
                                            clamp_status,
                                            sign_flip_status,
                                            hi,
                                            hn,
                                            hbar,
                                            ybar,
                                            self.fields.fhpredi[i, j],
                                            self.fields.fhpredi[ni, nj],
                                            self.fields.frhopredi[i, j],
                                            self.fields.frhopredi[ni, nj],
                                            cv_source,
                                            cv_neighbor,
                                            cvbar,
                                            frhobar,
                                            gammadeb,
                                            manningbar,
                                            miubar,
                                            grad,
                                            sfy,
                                            sfmiu,
                                            sfmanning,
                                            sf,
                                            localvdiff,
                                            artivis,
                                            vdiff_term,
                                            dv,
                                            fv_old,
                                            fvpred_before_clamp,
                                            fvpred,
                                            fvlimit,
                                            qqt,
                                            qq,
                                            qqmass,
                                            frhoflux,
                                            yflux,
                                            width,
                                            dt0,
                                            source_depth_rate,
                                            self.fields.erosion_rate[i, j],
                                            self.fields.deposition_rate[i, j],
                                        )
                                        self._record_momentum_faceflux_probe(
                                            5,
                                            i,
                                            j,
                                            ni,
                                            nj,
                                            ni,
                                            nj,
                                            opp,
                                            d,
                                            0,
                                            clamp_status,
                                            sign_flip_status,
                                            hi,
                                            hn,
                                            hbar,
                                            ybar,
                                            self.fields.fhpredi[i, j],
                                            self.fields.fhpredi[ni, nj],
                                            self.fields.frhopredi[i, j],
                                            self.fields.frhopredi[ni, nj],
                                            cv_source,
                                            cv_neighbor,
                                            cvbar,
                                            frhobar,
                                            gammadeb,
                                            manningbar,
                                            miubar,
                                            grad,
                                            sfy,
                                            sfmiu,
                                            sfmanning,
                                            sf,
                                            localvdiff,
                                            artivis,
                                            vdiff_term,
                                            dv,
                                            self.fields.fv_fortran[ni, nj, opp],
                                            -fvpred_before_clamp,
                                            -fvpred,
                                            fvlimit,
                                            -qqt,
                                            -qq,
                                            -qqmass,
                                            frhoflux,
                                            yflux,
                                            width,
                                            dt0,
                                            source_depth_rate,
                                            self.fields.erosion_rate[i, j],
                                            self.fields.deposition_rate[i, j],
                                        )
                                    if (
                                        self.fields.cell_id[ni, nj] == target_cell_id
                                        and (target_direction < 0 or opp == target_direction)
                                    ):
                                        self._record_momentum_faceflux_probe(
                                            2,
                                            i,
                                            j,
                                            ni,
                                            nj,
                                            ni,
                                            nj,
                                            d,
                                            opp,
                                            0,
                                            clamp_status,
                                            sign_flip_status,
                                            hi,
                                            hn,
                                            hbar,
                                            ybar,
                                            self.fields.fhpredi[i, j],
                                            self.fields.fhpredi[ni, nj],
                                            self.fields.frhopredi[i, j],
                                            self.fields.frhopredi[ni, nj],
                                            cv_source,
                                            cv_neighbor,
                                            cvbar,
                                            frhobar,
                                            gammadeb,
                                            manningbar,
                                            miubar,
                                            grad,
                                            sfy,
                                            sfmiu,
                                            sfmanning,
                                            sf,
                                            localvdiff,
                                            artivis,
                                            vdiff_term,
                                            dv,
                                            fv_old,
                                            fvpred_before_clamp,
                                            -fvpred,
                                            fvlimit,
                                            -qqt,
                                            -qq,
                                            -qqmass,
                                            frhoflux,
                                            yflux,
                                            width,
                                            dt0,
                                            source_depth_rate,
                                            self.fields.erosion_rate[i, j],
                                            self.fields.deposition_rate[i, j],
                                        )

                                self.fields.qqt_fortran[i, j, d] = qqt
                                self.fields.qq_fortran[i, j, d] = qq
                                self.fields.qqmass_fortran[i, j, d] = qqmass

                                self.fields.fv_pred_fortran[ni, nj, opp] = -fvpred
                                self.fields.fybar_fortran[ni, nj, opp] = self.fields.fybar_fortran[i, j, d]
                                self.fields.qqt_fortran[ni, nj, opp] = -qqt
                                self.fields.qq_fortran[ni, nj, opp] = -qq
                                self.fields.qqmass_fortran[ni, nj, opp] = -qqmass

    @ti.kernel
    def _accumulate_and_check(
        self,
        dt: ti.f64,
        rho_water: ti.f64,
        toldh: ti.f64,
        toldhp: ti.f64,
    ):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.qtnet_fortran[i, j] = 0.0
                self.fields.qnet_fortran[i, j] = 0.0
                self.fields.qmassnet_fortran[i, j] = 0.0
                self.fields.fhpredi2[i, j] = 0.0
                self.fields.frhopredi2[i, j] = rho_water
                continue

            qtnet = 0.0
            qnet = 0.0
            qmassnet = 0.0
            for d in ti.static(range(8)):
                qtnet -= self.fields.qqt_fortran[i, j, d]
                qnet -= self.fields.qq_fortran[i, j, d]
                qmassnet -= self.fields.qqmass_fortran[i, j, d]

            self.fields.qtnet_fortran[i, j] = qtnet
            self.fields.qnet_fortran[i, j] = qnet
            self.fields.qmassnet_fortran[i, j] = qmassnet

            cellarea = self.fields.cell_area_cal[i, j]
            hinflow = qnet / cellarea
            fhpredi2 = self.fields.fhpredi[i, j] + hinflow
            self.fields.fhpredi2[i, j] = fhpredi2

            self.fields.frhopredi2[i, j] = (
                self.fields.frhopredi[i, j] * self.fields.fhpredi[i, j] * cellarea + qmassnet
            ) / fhpredi2 / cellarea

            # dfs.F90 clamps low-density/non-positive predictor states before
            # the following retry checks:
            #   if(fhpredi2(i)<=0. .or. frhopredi2(i)<995.0) then
            #       fhpredi2(i) = 0.; frhopredi2(i) = rhow
            #   end if
            #   if (frhopredi2(i)<995.0) then ... goto 1000
            #   if (fhpredi2(i)<0.) then ... goto 1000
            #
            # The later low-density/negative-depth checks remain in their
            # source position, but they must observe the post-clamp values.
            if self.fields.fhpredi2[i, j] <= 0.0 or self.fields.frhopredi2[i, j] < 995.0:
                self.fields.fhpredi2[i, j] = 0.0
                self.fields.frhopredi2[i, j] = rho_water

            if ti.static(self.original_predictor_retry_gates_enabled):
                if self.fields.frhopredi2[i, j] < 995.0:
                    self.reject_flag[None] = 1
                    self._record_first_reject(
                        FIRST_REJECT_LOW_DENSITY,
                        i,
                        j,
                        -1,
                        -1,
                        -1,
                        self.fields.frhopredi2[i, j],
                        995.0,
                    )
                if self.fields.fhpredi2[i, j] < 0.0:
                    self.reject_flag[None] = 1
                    self._record_first_reject(
                        FIRST_REJECT_NEGATIVE_DEPTH,
                        i,
                        j,
                        -1,
                        -1,
                        -1,
                        self.fields.fhpredi2[i, j],
                        0.0,
                    )
            dfhtest = ti.abs(self.fields.fhpredi2[i, j] - self.fields.fhpredi[i, j])
            dpfhtest = DFS_DPFHTEST_OUTFLOW
            if _is_outflow(self.fields, i, j) == 0:
                if self.fields.fhpredi[i, j] != 0.0:
                    dpfhtest = ti.abs((self.fields.fhpredi2[i, j] - self.fields.fhpredi[i, j]) / self.fields.fhpredi[i, j])
                elif dfhtest > 0.0:
                    dpfhtest = 1.0e12
                else:
                    dpfhtest = 0.0

            if ti.static(not self.ifort_inactive_barrier_depth_gate_compat_enabled):
                if dfhtest > toldh and dpfhtest > toldhp:
                    self.reject_flag[None] = 1
                    self._record_first_reject(FIRST_REJECT_DEPTH_CHANGE, i, j, -1, -1, -1, dfhtest, toldh)

    @ti.kernel
    def _reset_volume_balance_accumulators(self):
        self.acc_outflowvolume[None] = 0.0
        self.acc_infilvolume[None] = 0.0
        self.acc_inflowvolume[None] = 0.0
        self.acc_rivolume[None] = 0.0
        self.acc_erosionvolume[None] = 0.0
        self.acc_fsvolume[None] = 0.0
        self.acc_depovolume[None] = 0.0
        self.acc_flowvolume[None] = 0.0
        self.acc_depositvolume[None] = 0.0

    @ti.kernel
    def _accumulate_volume_balance(self, dt: ti.f64):
        self.acc_outflowvolume[None] = 0.0
        self.acc_infilvolume[None] = 0.0
        self.acc_inflowvolume[None] = 0.0
        self.acc_rivolume[None] = 0.0
        self.acc_erosionvolume[None] = 0.0
        self.acc_fsvolume[None] = 0.0
        self.acc_depovolume[None] = 0.0
        self.acc_flowvolume[None] = 0.0
        self.acc_depositvolume[None] = 0.0
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            cellarea = self.fields.cell_area_cal[i, j]
            outflow = _is_outflow(self.fields, i, j)
            if outflow == 1:
                ti.atomic_add(self.acc_outflowvolume[None], self.fields.fhpredi2[i, j] * cellarea)
            else:
                ti.atomic_add(self.acc_infilvolume[None], self.fields.infiltration[i, j] * dt * cellarea)
                ti.atomic_add(self.acc_inflowvolume[None], self.fields.tempinflowh[i, j] * cellarea)
                ti.atomic_add(self.acc_rivolume[None], self.fields.tempri[i, j] * dt * cellarea)
                ti.atomic_add(self.acc_erosionvolume[None], self.fields.erosion_rate[i, j] * dt * cellarea)
                ti.atomic_add(self.acc_fsvolume[None], self.fields.tempfsh_flow[i, j] * cellarea)
                ti.atomic_add(self.acc_depovolume[None], ti.abs(self.fields.deposition_rate[i, j]) * dt * cellarea)

            # Match dfs.F90 order: outflow storage is recorded first, then
            # outflow `fhpredi2` is zeroed before `tempflowvolume` is summed.
            # This is equivalent to excluding outflow cells from flow storage
            # in the conservation check while still counting them as outflow.
            if outflow == 0:
                ti.atomic_add(self.acc_flowvolume[None], self.fields.fhpredi2[i, j] * cellarea)

            ti.atomic_add(self.acc_depositvolume[None], self.fields.temp_depo_thickness[i, j] * cellarea)

    @ti.kernel
    def _finalize_volume_balance(self, dt: ti.f64):
        temprivolume = self.totalrivolume[None] + self.acc_rivolume[None]
        tempinflowvolume = self.totalinflowvolume[None] + self.acc_inflowvolume[None]
        temperosionvolume = self.totalerosionvolume[None] + self.acc_erosionvolume[None]
        tempfsvolume = self.totalfsvolume[None] + self.acc_fsvolume[None]
        tempinfilvolume = self.totalinfilvolume[None] + self.acc_infilvolume[None]
        tempoutflowvolume = self.totaloutflowvolume[None] + self.acc_outflowvolume[None]
        tempdepovolume = self.totaldepovolume[None] + self.acc_depovolume[None]
        tempflowvolume = self.acc_flowvolume[None]
        tempdepositvolume = self.acc_depositvolume[None]

        self.cand_totalrivolume[None] = temprivolume
        self.cand_totalinflowvolume[None] = tempinflowvolume
        self.cand_totalerosionvolume[None] = temperosionvolume
        self.cand_totalfsvolume[None] = tempfsvolume
        self.cand_totalinfilvolume[None] = tempinfilvolume
        self.cand_totaloutflowvolume[None] = tempoutflowvolume
        self.cand_totaldepovolume[None] = tempdepovolume

        denominator = temprivolume + tempinflowvolume + temperosionvolume + tempfsvolume
        volumeerror = 0.0
        volumerelaerror = 0.0
        if denominator > EPS:
            volumeerror = (
                temprivolume + tempinflowvolume + temperosionvolume + tempfsvolume
                - tempinfilvolume - tempoutflowvolume - tempflowvolume - tempdepositvolume
            )
            volumerelaerror = volumeerror / denominator
            if ti.abs(volumerelaerror) > DFS_VOLUME_REL_TOL:
                self.reject_flag[None] = 1
                self._record_first_reject(
                    FIRST_REJECT_VOLUME,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    ti.abs(volumerelaerror),
                    DFS_VOLUME_REL_TOL,
                )
                dt_reject = dt - self.dt_decrease
                if dt_reject < self.dt_min:
                    dt_reject = self.dt_min
                self.suggested_dt[None] = dt_reject

        # Keep these values observationally available to the Python lifecycle
        # and the persisted run diagnostics.  They are not read by any kernel
        # that changes the accept/reject decision.
        self.volume_denominator[None] = denominator
        self.volume_error[None] = volumeerror
        self.volume_relative_error[None] = volumerelaerror

    @ti.kernel
    def _capture_outflow_candidate_before_clear(self, rho_water: ti.f64):
        for i, j in self.fields.h:
            if _is_outflow(self.fields, i, j) == 1:
                self.outflow_candidate_depth[i, j] = self.fields.fhpredi2[i, j]
                self.outflow_candidate_density[i, j] = self.fields.frhopredi2[i, j]
            else:
                self.outflow_candidate_depth[i, j] = 0.0
                self.outflow_candidate_density[i, j] = rho_water

    @ti.kernel
    def _commit_accepted_outflow_candidate(self):
        for i, j in self.fields.h:
            self.outflow_accepted_depth[i, j] = self.outflow_candidate_depth[i, j]
            self.outflow_accepted_density[i, j] = self.outflow_candidate_density[i, j]

    @ti.kernel
    def _apply_post_balance_outflow(self, rho_water: ti.f64):
        for i, j in self.fields.h:
            if _is_outflow(self.fields, i, j) == 1:
                self.fields.fhpredi2[i, j] = 0.0
                self.fields.frhopredi2[i, j] = rho_water
            if self.fields.fhpredi2[i, j] < EPS:
                self.fields.frhopredi2[i, j] = rho_water

    @ti.kernel
    def _commit_volume_counters(self):
        self.totaloutflowvolume[None] = self.cand_totaloutflowvolume[None]
        self.totalinfilvolume[None] = self.cand_totalinfilvolume[None]
        self.totalinflowvolume[None] = self.cand_totalinflowvolume[None]
        self.totalrivolume[None] = self.cand_totalrivolume[None]
        self.totalerosionvolume[None] = self.cand_totalerosionvolume[None]
        self.totalfsvolume[None] = self.cand_totalfsvolume[None]
        self.totaldepovolume[None] = self.cand_totaldepovolume[None]

    @ti.kernel
    def _commit_step(
        self,
        dt: ti.f64,
        dt_next: ti.f64,
        rho_water: ti.f64,
        rho_sediment: ti.f64,
        cvstar: ti.f64,
    ):
        self.totaloutflowvolume[None] = self.cand_totaloutflowvolume[None]
        self.totalinfilvolume[None] = self.cand_totalinfilvolume[None]
        self.totalinflowvolume[None] = self.cand_totalinflowvolume[None]
        self.totalrivolume[None] = self.cand_totalrivolume[None]
        self.totalerosionvolume[None] = self.cand_totalerosionvolume[None]
        self.totalfsvolume[None] = self.cand_totalfsvolume[None]
        self.totaldepovolume[None] = self.cand_totaldepovolume[None]
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            self.fields.h[i, j] = self.fields.fhpredi2[i, j]
            self.fields.rho[i, j] = self.fields.frhopredi2[i, j]
            # Chamoli dfs.F90:1115-1133 classifies with the PREVIOUS accepted cv
            # against the NEW fhpredi2 depth, then dfs.F90:1284 updates cv.
            prev_cv = self.fields.Cv[i, j]
            # dfs.F90 commits frho/cv before the final shallow-depth fh reset:
            #   frho=frhopredi2
            #   cv=(frho-rhow)/(rhos-rhow)
            #   where(fh<eps) fh=0.
            # frhopredi2 was already set to rhow for fhpredi2<eps in
            # `_apply_post_balance_outflow`, so do not add an extra rho/Cv
            # reset here that the original production path does not have.
            self.fields.Cv[i, j] = (self.fields.rho[i, j] - rho_water) / (rho_sediment - rho_water)
            if self.fields.h[i, j] < EPS:
                self.fields.h[i, j] = 0.0

            self.fields.z_bed[i, j] = self.fields.tempele[i, j]
            self.fields.erosion_depth[i, j] += self.fields.erosion_rate[i, j] * dt
            self.fields.deposition_depth[i, j] += ti.abs(self.fields.deposition_rate[i, j]) * dt
            # Match dfs.F90 literally: after acceptance the solver increments
            # `dt` for the next step, then commits
            # `inierodithick=tempinierodithick+abs(deporate)*dt`.
            self.fields.erodible_thickness[i, j] = self.fields.temp_erodible_thickness[i, j] + ti.abs(self.fields.deposition_rate[i, j]) * dt_next
            self.fields.depo_thickness[i, j] = self.fields.temp_depo_thickness[i, j]

            local_max_velocity = self.fields.max_flow_velocity[i, j]
            for d in ti.static(range(8)):
                self.fields.fv_fortran[i, j, d] = self.fields.fv_pred_fortran[i, j, d]
                local_max_velocity = ti.max(local_max_velocity, ti.abs(self.fields.fv_fortran[i, j, d]))

            self.fields.max_flow_velocity[i, j] = local_max_velocity
            self.fields.max_flow_depth[i, j] = ti.max(self.fields.max_flow_depth[i, j], self.fields.h[i, j])
            solid_depth = ti.max(self.fields.h[i, j] * self.fields.Cv[i, j], 0.0)
            self.fields.max_solid_depth[i, j] = ti.max(
                self.fields.max_solid_depth[i, j], solid_depth
            )
            self.fields.total_depth[i, j] = self.fields.h[i, j] + self.fields.depo_thickness[i, j]
            if ti.static(self.dfs_manningbar_variant == "debrisflowmanning_cvtol"):
                # Chamoli dfs.F90:184-186 zeros class depths each step, then
                # :1115-1133 writes only the class matching the previous cv.
                local_h = self.fields.h[i, j]
                self.fields.sfh[i, j] = 0.0
                self.fields.dfh[i, j] = 0.0
                self.fields.ffh[i, j] = 0.0
                if prev_cv >= 0.5:
                    self.fields.sfh[i, j] = local_h
                    self.fields.maxsfh[i, j] = ti.max(self.fields.maxsfh[i, j], local_h)
                elif prev_cv >= 0.2:
                    self.fields.dfh[i, j] = local_h
                    self.fields.maxdfh[i, j] = ti.max(self.fields.maxdfh[i, j], local_h)
                else:
                    self.fields.ffh[i, j] = local_h
                    self.fields.maxffh[i, j] = ti.max(self.fields.maxffh[i, j], local_h)

    @ti.kernel
    def _sync_uv_from_fortran_velocity(self):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] or self.fields.h[i, j] <= EPS:
                self.fields.u[i, j] = 0.0
                self.fields.v[i, j] = 0.0
                continue

            u_sum = self.fields.fv_fortran[i, j, 2] - self.fields.fv_fortran[i, j, 6]
            v_sum = self.fields.fv_fortran[i, j, 0] - self.fields.fv_fortran[i, j, 4]
            weight_u = 2.0
            weight_v = 2.0

            u_sum += (self.fields.fv_fortran[i, j, 1] + self.fields.fv_fortran[i, j, 3] - self.fields.fv_fortran[i, j, 5] - self.fields.fv_fortran[i, j, 7]) * INV_SQRT2
            v_sum += (self.fields.fv_fortran[i, j, 1] - self.fields.fv_fortran[i, j, 3] - self.fields.fv_fortran[i, j, 5] + self.fields.fv_fortran[i, j, 7]) * INV_SQRT2
            weight_u += 4.0 * INV_SQRT2
            weight_v += 4.0 * INV_SQRT2

            self.fields.u[i, j] = u_sum / weight_u
            self.fields.v[i, j] = v_sum / weight_v

    @ti.kernel
    def _sync_legacy_directional_velocity(self):
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                for d in ti.static(range(8)):
                    self.vdir_legacy[i, j, d] = 0.0
                continue

            for d in ti.static(range(8)):
                self.vdir_legacy[i, j, d] = self.fields.fv_fortran[i, j, d]
