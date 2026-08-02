"""
Core Taichi field definitions for EDDA simulation.
"""
import taichi as ti
import numpy as np
from typing import Iterable, Tuple, Optional


def _ensure_taichi_initialized():
    """Ensure Taichi runtime is initialized before field allocation."""
    try:
        from taichi.lang import impl

        runtime = impl.get_runtime()
        if runtime.prog is None:
            ti.init(arch=ti.cpu)
    except Exception:
        # Fallback for Taichi versions where runtime internals differ.
        # If already initialized, ti.init() is a no-op/re-init managed by Taichi.
        ti.init(arch=ti.cpu)


@ti.data_oriented
class EDDAFields:
    """
    Taichi field container for EDDA simulation variables.
    All fields are stored on GPU/CPU depending on backend selection.
    """

    # Double-layer soil model constants
    NZST = 26  # Number of sublayers in top layer
    NZSB = 26  # Number of sublayers in bottom layer

    def __init__(self, nx: int, ny: int, dx: float, dy: float, fp_dtype=ti.f32):
        """
        Initialize EDDA fields.

        Args:
            nx: Number of grid cells in x direction
            ny: Number of grid cells in y direction
            dx: Grid spacing in x direction (m)
            dy: Grid spacing in y direction (m)
        """
        self.nx = nx
        self.ny = ny
        self.dx = float(dx)
        self.dy = float(dy)
        self.fp = fp_dtype
        self._flow_connectivity_version = 0

        _ensure_taichi_initialized()

        # Terrain and geometry
        self.z_bed = ti.field(dtype=self.fp, shape=(nx, ny))  # Bed elevation (m)
        self.z_original = ti.field(dtype=self.fp, shape=(nx, ny))  # Original bed elevation
        self.slope_x = ti.field(dtype=self.fp, shape=(nx, ny))  # Slope in x direction
        self.slope_y = ti.field(dtype=self.fp, shape=(nx, ny))  # Slope in y direction
        self.slope_mag = ti.field(dtype=self.fp, shape=(nx, ny))  # Slope magnitude (for compatibility with original EDDA)
        self.slope_angle = ti.field(dtype=self.fp, shape=(nx, ny))  # Slope angle in radians (original EDDA `slo`)

        # Flow variables
        self.h = ti.field(dtype=self.fp, shape=(nx, ny))  # Flow depth (m)
        self.u = ti.field(dtype=self.fp, shape=(nx, ny))  # Velocity in x direction (m/s)
        self.v = ti.field(dtype=self.fp, shape=(nx, ny))  # Velocity in y direction (m/s)
        self.Cv = ti.field(dtype=self.fp, shape=(nx, ny))  # Volumetric sediment concentration

        # Hydrology variables
        self.rainfall = ti.field(dtype=self.fp, shape=(nx, ny))  # Rainfall intensity (m/s)
        self.infiltration = ti.field(dtype=self.fp, shape=(nx, ny))  # Infiltration rate (m/s)
        self.psi = ti.field(dtype=self.fp, shape=(nx, ny))  # Pore water pressure (Pa)
        self.F_cumulative = ti.field(dtype=self.fp, shape=(nx, ny))  # Cumulative infiltration (m)

        # Stability variables
        self.FS = ti.field(dtype=self.fp, shape=(nx, ny))  # Factor of safety
        self.is_failed = ti.field(dtype=ti.i32, shape=(nx, ny))  # Failure flag (0/1)

        # Erosion and deposition
        self.erosion_rate = ti.field(dtype=self.fp, shape=(nx, ny))  # Erosion rate (m/s)
        self.deposition_rate = ti.field(dtype=self.fp, shape=(nx, ny))  # Deposition rate (m/s)
        self.erosion_depth = ti.field(dtype=self.fp, shape=(nx, ny))  # Cumulative erosion (m)
        self.deposition_depth = ti.field(dtype=self.fp, shape=(nx, ny))  # Cumulative deposition (m)
        # Dedicated temporary fields for erosion computation (avoid reusing erosion_rate/deposition_rate)
        self.cvlimit_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Concentration limit (temporary)
        self.tau_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Bed shear stress (temporary)
        self.taoc_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Active critical bed shear stress (temporary)
        self.taoc_old_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Previous current critical-shear formula
        self.taoc_fortran_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Fortran-equivalent critical-shear formula
        self.taoc_delta_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # taoc_fortran - taoc_old
        self.tau_minus_taoc_old_temp = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tau_minus_taoc_fortran_temp = ti.field(dtype=self.fp, shape=(nx, ny))
        self.rholimit_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Density limit from cvlimit
        self.absubar_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Speed used by dfs erosion/deposition source terms
        self.absubar_vorth_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Diagnostics: orthogonal branch velocity component
        self.absubar_vcomp_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Diagnostics: diagonal branch velocity component
        self.absubar_velocity_state_scale_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Diagnostics: fv scale used in source branch
        self.absubar_selected_is_vorth_temp = ti.field(dtype=ti.i32, shape=(nx, ny))  # Diagnostics: 1 when vorth selected
        self.absubar_fv_used_temp = ti.field(dtype=self.fp, shape=(nx, ny, 8))  # Diagnostics: fv components used for branch absubar
        self.rhodepo_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Deposition bulk density
        self.erorate_raw_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Erosion rate before clamp diagnostics
        self.erorate_rholimit_clamped_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # After density-limit clamp
        self.erorate_clamped_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Erosion rate after clamp diagnostics
        self.deporate_raw_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Deposition rate before clamp diagnostics
        self.deporate_clamped_temp = ti.field(dtype=self.fp, shape=(nx, ny))  # Deposition rate after clamp diagnostics
        self.erosion_gate_temp = ti.field(dtype=ti.i32, shape=(nx, ny))  # 1 when the erosion gate is open
        self.tau_gt_taoc_old_temp = ti.field(dtype=ti.i32, shape=(nx, ny))
        self.tau_gt_taoc_fortran_temp = ti.field(dtype=ti.i32, shape=(nx, ny))
        self.all_erosion_gate_old_temp = ti.field(dtype=ti.i32, shape=(nx, ny))
        self.all_erosion_gate_fortran_temp = ti.field(dtype=ti.i32, shape=(nx, ny))
        self.deposition_gate_temp = ti.field(dtype=ti.i32, shape=(nx, ny))  # 1 when the deposition gate is open
        self.rholimit_clamp_temp = ti.field(dtype=ti.i32, shape=(nx, ny))  # 1 when density-limit clamp changes erorate
        self.erodible_clamp_temp = ti.field(dtype=ti.i32, shape=(nx, ny))  # 1 when erodible-thickness clamp changes erorate

        # Rheology variables
        self.rho = ti.field(dtype=self.fp, shape=(nx, ny))  # Mixture density (kg/m³)
        self.tau_y = ti.field(dtype=self.fp, shape=(nx, ny))  # Yield stress (Pa)
        self.mu = ti.field(dtype=self.fp, shape=(nx, ny))  # Dynamic viscosity (Pa·s)

        # Boundary conditions
        self.is_boundary = ti.field(dtype=ti.i32, shape=(nx, ny))  # Boundary flag
        self.boundary_type = ti.field(dtype=ti.i32, shape=(nx, ny))  # Boundary type (0=internal, 1=outflow, 2=wall, 3=inflow)
        self.is_nodata = ti.field(dtype=ti.i32, shape=(nx, ny))  # NoData flag
        self.cell_id = ti.field(dtype=ti.i32, shape=(nx, ny))  # 1-based valid-cell numbering matching flodir.f90 row-major traversal
        self.cell_area_cal = ti.field(dtype=self.fp, shape=(nx, ny))  # Original EDDA `cellareacal = cellarea * (1 - arf)`
        self.dfs_outflow_mask = ti.field(dtype=ti.i32, shape=(nx, ny))  # Original EDDA `outflow(i)` sidecar mask

        # Explicit 8-direction connectivity in original EDDA / Fortran order:
        # [N, NE, E, SE, S, SW, W, NW]
        self.flow_neighbor_id = ti.field(dtype=ti.i32, shape=(nx, ny, 8))
        self.flow_neighbor_i = ti.field(dtype=ti.i32, shape=(nx, ny, 8))
        self.flow_neighbor_j = ti.field(dtype=ti.i32, shape=(nx, ny, 8))

        # Temporary fields for flux calculation
        self.flux_h = ti.field(dtype=self.fp, shape=(nx, ny, 8))  # Mass flux in 8 directions
        self.flux_hu = ti.field(dtype=self.fp, shape=(nx, ny, 8))  # x-momentum flux
        self.flux_hv = ti.field(dtype=self.fp, shape=(nx, ny, 8))  # y-momentum flux
        self.flux_hCv = ti.field(dtype=self.fp, shape=(nx, ny, 8))  # Sediment flux

        # Workspace for research-grade port of the original EDDA dynamic-wave solver.
        # These fields mirror the key 8-direction arrays from wfs.F90 / dfs.F90.
        self.fv_fortran = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.fv_pred_fortran = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        # Diagnostics-only deposition velocity lifecycle snapshots. These do
        # not feed the solver unless a future feature-gated repair explicitly
        # selects one of them.
        self.depo_velocity_source_entry = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.depo_velocity_pre_source_branch = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.depo_velocity_branch_fv = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.depo_velocity_branch_fvpredi = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.depo_velocity_branch_fvpredi2 = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.depo_velocity_before_face_flux = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.depo_velocity_after_face_flux = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.qq_fortran = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.qqt_fortran = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.qqmass_fortran = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.fybar_fortran = ti.field(dtype=self.fp, shape=(nx, ny, 8))
        self.tempri = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tempinflowh = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tempinflowrho = ti.field(dtype=self.fp, shape=(nx, ny))
        self.fhw = ti.field(dtype=self.fp, shape=(nx, ny))
        self.fhpredi1 = ti.field(dtype=self.fp, shape=(nx, ny))
        self.frhopredi1 = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tempele = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tempfsh_flow = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tempfsrho_flow = ti.field(dtype=self.fp, shape=(nx, ny))
        self.fhpredi = ti.field(dtype=self.fp, shape=(nx, ny))
        self.frhopredi = ti.field(dtype=self.fp, shape=(nx, ny))
        self.fhpredi2 = ti.field(dtype=self.fp, shape=(nx, ny))
        self.frhopredi2 = ti.field(dtype=self.fp, shape=(nx, ny))
        self.qtnet_fortran = ti.field(dtype=self.fp, shape=(nx, ny))
        self.qnet_fortran = ti.field(dtype=self.fp, shape=(nx, ny))
        self.qmassnet_fortran = ti.field(dtype=self.fp, shape=(nx, ny))
        self.tanslo_fortran = ti.field(dtype=self.fp, shape=(nx, ny))
        self.max_flow_depth = ti.field(dtype=self.fp, shape=(nx, ny))
        self.max_flow_velocity = ti.field(dtype=self.fp, shape=(nx, ny))
        self.total_depth = ti.field(dtype=self.fp, shape=(nx, ny))
        self.temp_erodible_thickness = ti.field(dtype=self.fp, shape=(nx, ny))
        self.temp_depo_thickness = ti.field(dtype=self.fp, shape=(nx, ny))

        # Double-layer soil model fields
        # Top layer sublayer fields (nx, ny, NZST+1)
        self.zt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer depth coordinates (m)
        self.kkt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer hydraulic conductivity (m/s)
        self.pt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer pore pressure (Pa)
        self.thzt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer moisture content
        self.desatt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer degree of saturation
        self.deltazt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer sublayer thickness (m)
        self.deltadzt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Top layer sublayer thickness change (m)

        # Bottom layer sublayer fields (nx, ny, NZSB+1)
        self.zb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer depth coordinates (m)
        self.kkb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer hydraulic conductivity (m/s)
        self.pb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer pore pressure (Pa)
        self.thzb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer moisture content
        self.desatb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer degree of saturation
        self.deltazb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer sublayer thickness (m)
        self.deltadzb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Bottom layer sublayer thickness change (m)

        # Initial state fields for double-layer model (3D: per sublayer)
        self.inidesatt = ti.field(dtype=self.fp, shape=(nx, ny, self.NZST + 1))  # Initial top layer degree of saturation
        self.inidesatb = ti.field(dtype=self.fp, shape=(nx, ny, self.NZSB + 1))  # Initial bottom layer degree of saturation

        # Double-layer parameters
        self.beta = ti.field(dtype=self.fp, shape=(nx, ny))  # Soil water retention parameter
        self.ltstar = ti.field(dtype=self.fp, shape=(nx, ny))  # Top layer thickness (m)
        self.lbstar = ti.field(dtype=self.fp, shape=(nx, ny))  # Bottom layer thickness (m)

        # Failure surface fields
        self.zfmin = ti.field(dtype=self.fp, shape=(nx, ny))  # Minimum failure depth (m)
        self.pmin = ti.field(dtype=self.fp, shape=(nx, ny))  # Minimum pore pressure at failure (Pa)
        self.fdepth = ti.field(dtype=self.fp, shape=(nx, ny))  # Failure depth (m)

        # Spatial zone system for heterogeneous soil parameters
        self.zone_id = ti.field(dtype=ti.i32, shape=(nx, ny))  # Zone ID for each grid cell

        # Spatial parameter fields (per grid cell)
        # Hydrology parameters
        self.K_sat_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Saturated hydraulic conductivity (m/s)
        self.theta_s_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Saturated water content
        self.theta_i_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Initial water content
        self.psi_f_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Wetting front suction head (m)

        # Soil parameters
        self.c_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Cohesion (Pa)
        self.phi_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Internal friction angle (degrees)
        self.gamma_s_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Soil unit weight (N/m³)
        self.gamma_w_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Water unit weight (N/m³)
        self.depth_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Soil depth (m)

        # Rheology parameters
        self.n_manning_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Manning roughness coefficient
        self.alpha1_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Quadratic model parameter α1
        self.beta1_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Quadratic model parameter β1
        self.alpha2_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Quadratic model parameter α2
        self.beta2_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Quadratic model parameter β2

        # Erodible layer tracking
        self.erodible_thickness = ti.field(dtype=self.fp, shape=(nx, ny))  # Available erodible soil thickness (m)
        self.depo_thickness = ti.field(dtype=self.fp, shape=(nx, ny))  # Deposited material thickness (m)

        # Per-cell erosion coefficient
        self.kero_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Erosion coefficient (m/s/Pa)
        self.ctao_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Original EDDA ctao erosion threshold term (Pa)

        # Double-layer spatial parameter fields (per grid cell, for zone support)
        self.alpha_top_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Van Genuchten alpha top (1/m)
        self.alpha_bottom_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Van Genuchten alpha bottom (1/m)
        self.K_sat_top_field = ti.field(dtype=self.fp, shape=(nx, ny))  # K_sat top layer (m/s)
        self.K_sat_bottom_field = ti.field(dtype=self.fp, shape=(nx, ny))  # K_sat bottom layer (m/s)
        self.theta_sat_top_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Saturated water content top
        self.theta_sat_bottom_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Saturated water content bottom
        self.theta_res_top_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Residual water content top
        self.theta_res_bottom_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Residual water content bottom
        self.phib_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Unsaturated shear strength angle (degrees)
        self.ltstar_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Top layer thickness (m) - spatial
        self.lbstar_field = ti.field(dtype=self.fp, shape=(nx, ny))  # Bottom layer thickness (m) - spatial

    @ti.kernel
    def initialize_from_numpy(self, z_bed_np: ti.types.ndarray()):
        """Initialize bed elevation from numpy array."""
        for i, j in self.z_bed:
            self.z_bed[i, j] = z_bed_np[i, j]
            self.z_original[i, j] = z_bed_np[i, j]

    @ti.kernel
    def set_nodata_mask(self, nodata_mask: ti.types.ndarray()):
        """Set NoData mask from numpy array."""
        for i, j in self.is_nodata:
            self.is_nodata[i, j] = nodata_mask[i, j]

    @ti.kernel
    def set_boundary_conditions(self, boundary_mask: ti.types.ndarray(), boundary_types: ti.types.ndarray()):
        """
        Set boundary conditions from numpy arrays.

        Args:
            boundary_mask: Boolean array indicating boundary cells (nx, ny)
            boundary_types: Integer array with boundary types (nx, ny)
                           0 = internal, 1 = outflow, 2 = wall, 3 = inflow
        """
        for i, j in self.is_boundary:
            self.is_boundary[i, j] = boundary_mask[i, j]
            self.boundary_type[i, j] = boundary_types[i, j]

    @ti.kernel
    def compute_slopes(self):
        """Compute terrain slopes using central differences."""
        MAX_SLOPE = 5.67  # tan(80 degrees) - limit extreme slopes

        for i, j in self.z_bed:
            if i > 0 and i < self.nx - 1 and not self.is_nodata[i, j]:
                slope_x_raw = (self.z_bed[i + 1, j] - self.z_bed[i - 1, j]) / (2.0 * self.dx)
                self.slope_x[i, j] = ti.max(ti.min(slope_x_raw, MAX_SLOPE), -MAX_SLOPE)
            if j > 0 and j < self.ny - 1 and not self.is_nodata[i, j]:
                slope_y_raw = (self.z_bed[i, j + 1] - self.z_bed[i, j - 1]) / (2.0 * self.dy)
                self.slope_y[i, j] = ti.max(ti.min(slope_y_raw, MAX_SLOPE), -MAX_SLOPE)

        # Compute slope magnitude
        for i, j in self.slope_mag:
            if not self.is_nodata[i, j]:
                self.slope_mag[i, j] = ti.sqrt(self.slope_x[i, j] * self.slope_x[i, j] +
                                               self.slope_y[i, j] * self.slope_y[i, j])
                self.slope_angle[i, j] = ti.atan2(self.slope_mag[i, j], 1.0)

    @ti.kernel
    def zero_flow_variables(self):
        """Initialize flow variables to zero."""
        for i, j in self.h:
            self.h[i, j] = 0.0
            self.u[i, j] = 0.0
            self.v[i, j] = 0.0
            self.Cv[i, j] = 0.0

    @ti.kernel
    def zero_hydrology_variables(self):
        """Initialize hydrology variables to zero."""
        for i, j in self.rainfall:
            self.rainfall[i, j] = 0.0
            self.infiltration[i, j] = 0.0
            self.psi[i, j] = 0.0
            self.F_cumulative[i, j] = 0.0

    @ti.kernel
    def zero_stability_variables(self):
        """Initialize stability variables."""
        for i, j in self.FS:
            self.FS[i, j] = 10.0  # High initial factor of safety
            self.is_failed[i, j] = 0

    @ti.kernel
    def zero_erosion_variables(self):
        """Initialize erosion/deposition variables to zero."""
        for i, j in self.erosion_rate:
            self.erosion_rate[i, j] = 0.0
            self.deposition_rate[i, j] = 0.0
            self.erosion_depth[i, j] = 0.0
            self.deposition_depth[i, j] = 0.0
            self.erodible_thickness[i, j] = 0.0
            self.depo_thickness[i, j] = 0.0
            self.cvlimit_temp[i, j] = 0.0
            self.tau_temp[i, j] = 0.0
            self.taoc_temp[i, j] = 0.0
            self.taoc_old_temp[i, j] = 0.0
            self.taoc_fortran_temp[i, j] = 0.0
            self.taoc_delta_temp[i, j] = 0.0
            self.tau_minus_taoc_old_temp[i, j] = 0.0
            self.tau_minus_taoc_fortran_temp[i, j] = 0.0
            self.rholimit_temp[i, j] = 0.0
            self.absubar_temp[i, j] = 0.0
            self.absubar_vorth_temp[i, j] = 0.0
            self.absubar_vcomp_temp[i, j] = 0.0
            self.absubar_velocity_state_scale_temp[i, j] = 0.0
            self.absubar_selected_is_vorth_temp[i, j] = 0
            self.rhodepo_temp[i, j] = 0.0
            self.erorate_raw_temp[i, j] = 0.0
            self.erorate_rholimit_clamped_temp[i, j] = 0.0
            self.erorate_clamped_temp[i, j] = 0.0
            self.deporate_raw_temp[i, j] = 0.0
            self.deporate_clamped_temp[i, j] = 0.0
            self.erosion_gate_temp[i, j] = 0
            self.tau_gt_taoc_old_temp[i, j] = 0
            self.tau_gt_taoc_fortran_temp[i, j] = 0
            self.all_erosion_gate_old_temp[i, j] = 0
            self.all_erosion_gate_fortran_temp[i, j] = 0
            self.deposition_gate_temp[i, j] = 0
            self.rholimit_clamp_temp[i, j] = 0
            self.erodible_clamp_temp[i, j] = 0
            for d in ti.static(range(8)):
                self.absubar_fv_used_temp[i, j, d] = 0.0

    @ti.kernel
    def zero_dynamic_wave_variables(self):
        """Initialize dynamic-wave workspace and explicit connectivity fields."""
        for i, j in self.cell_id:
            self.cell_id[i, j] = 0
            self.cell_area_cal[i, j] = self.dx * self.dy
            self.dfs_outflow_mask[i, j] = 0
            self.tempri[i, j] = 0.0
            self.tempinflowh[i, j] = 0.0
            self.tempinflowrho[i, j] = 0.0
            self.fhw[i, j] = 0.0
            self.fhpredi1[i, j] = 0.0
            self.frhopredi1[i, j] = 0.0
            self.tempele[i, j] = 0.0
            self.tempfsh_flow[i, j] = 0.0
            self.tempfsrho_flow[i, j] = 0.0
            self.fhpredi[i, j] = 0.0
            self.frhopredi[i, j] = 0.0
            self.fhpredi2[i, j] = 0.0
            self.frhopredi2[i, j] = 0.0
            self.qtnet_fortran[i, j] = 0.0
            self.qnet_fortran[i, j] = 0.0
            self.qmassnet_fortran[i, j] = 0.0
            self.tanslo_fortran[i, j] = 0.0
            self.max_flow_depth[i, j] = 0.0
            self.max_flow_velocity[i, j] = 0.0
            self.total_depth[i, j] = 0.0
            self.temp_erodible_thickness[i, j] = 0.0
            self.temp_depo_thickness[i, j] = 0.0

        for i, j, d in self.flow_neighbor_id:
            self.flow_neighbor_id[i, j, d] = 0
            self.flow_neighbor_i[i, j, d] = -1
            self.flow_neighbor_j[i, j, d] = -1
            self.fv_fortran[i, j, d] = 0.0
            self.fv_pred_fortran[i, j, d] = 0.0
            self.depo_velocity_source_entry[i, j, d] = 0.0
            self.depo_velocity_pre_source_branch[i, j, d] = 0.0
            self.depo_velocity_branch_fv[i, j, d] = 0.0
            self.depo_velocity_branch_fvpredi[i, j, d] = 0.0
            self.depo_velocity_branch_fvpredi2[i, j, d] = 0.0
            self.depo_velocity_before_face_flux[i, j, d] = 0.0
            self.depo_velocity_after_face_flux[i, j, d] = 0.0
            self.qq_fortran[i, j, d] = 0.0
            self.qqt_fortran[i, j, d] = 0.0
            self.qqmass_fortran[i, j, d] = 0.0
            self.fybar_fortran[i, j, d] = 0.0

    @ti.kernel
    def zero_doublelayer_variables(self):
        """Initialize double-layer soil model variables to zero."""
        # Initialize 3D fields for top layer
        for i, j, k in self.zt:
            self.zt[i, j, k] = 0.0
            self.kkt[i, j, k] = 0.0
            self.pt[i, j, k] = 0.0
            self.thzt[i, j, k] = 0.0
            self.desatt[i, j, k] = 0.0
            self.deltazt[i, j, k] = 0.0
            self.deltadzt[i, j, k] = 0.0

        # Initialize 3D fields for bottom layer
        for i, j, k in self.zb:
            self.zb[i, j, k] = 0.0
            self.kkb[i, j, k] = 0.0
            self.pb[i, j, k] = 0.0
            self.thzb[i, j, k] = 0.0
            self.desatb[i, j, k] = 0.0
            self.deltazb[i, j, k] = 0.0
            self.deltadzb[i, j, k] = 0.0

        # Initialize 3D initial saturation fields
        for i, j, k in self.inidesatt:
            self.inidesatt[i, j, k] = 0.0
        for i, j, k in self.inidesatb:
            self.inidesatb[i, j, k] = 0.0

        # Initialize 2D fields
        for i, j in self.beta:
            self.beta[i, j] = 0.0
            self.ltstar[i, j] = 0.0
            self.lbstar[i, j] = 0.0
            self.zfmin[i, j] = 0.0
            self.pmin[i, j] = 0.0
            self.fdepth[i, j] = 0.0

    @ti.kernel
    def zero_spatial_zone_variables(self):
        """Initialize spatial zone variables to default values."""
        for i, j in self.zone_id:
            self.zone_id[i, j] = 0  # Default zone ID

            # Initialize hydrology parameter fields
            self.K_sat_field[i, j] = 1e-5
            self.theta_s_field[i, j] = 0.45
            self.theta_i_field[i, j] = 0.20
            self.psi_f_field[i, j] = 0.10

            # Initialize soil parameter fields
            self.c_field[i, j] = 5000.0
            self.phi_field[i, j] = 30.0
            self.gamma_s_field[i, j] = 20000.0
            self.gamma_w_field[i, j] = 9800.0
            self.depth_field[i, j] = 2.0

            # Initialize rheology parameter fields
            self.n_manning_field[i, j] = 0.03
            self.alpha1_field[i, j] = 0.0765
            self.beta1_field[i, j] = 10.11
            self.alpha2_field[i, j] = 0.0538
            self.beta2_field[i, j] = 17.48

            # Initialize erosion parameter fields
            self.kero_field[i, j] = 1e-5
            self.ctao_field[i, j] = 10.0

            # Initialize double-layer spatial parameter fields
            self.alpha_top_field[i, j] = 2.0
            self.alpha_bottom_field[i, j] = 1.5
            self.K_sat_top_field[i, j] = 1e-5
            self.K_sat_bottom_field[i, j] = 5e-6
            self.theta_sat_top_field[i, j] = 0.45
            self.theta_sat_bottom_field[i, j] = 0.40
            self.theta_res_top_field[i, j] = 0.05
            self.theta_res_bottom_field[i, j] = 0.05
            self.phib_field[i, j] = 15.0
            self.ltstar_field[i, j] = 1.0
            self.lbstar_field[i, j] = 1.0

    @ti.kernel
    def set_zone_parameters(self, zone_mask: ti.types.ndarray(), zone_params: ti.types.ndarray()):
        """
        Set spatial zone parameters from numpy arrays.

        Args:
            zone_mask: Integer array with zone IDs (nx, ny)
            zone_params: Array with parameters for each zone (num_zones, num_params)
                        Order: K_sat, theta_s, theta_i, psi_f, c, phi, gamma_s, gamma_w, depth,
                               n_manning, alpha1, beta1, alpha2, beta2,
                               alpha_top, alpha_bottom, K_sat_top, K_sat_bottom,
                               theta_sat_top, theta_sat_bottom, theta_res_top, theta_res_bottom,
                               phib, kero, ltstar, lbstar, ctao
        """
        for i, j in self.zone_id:
            zone = zone_mask[i, j]
            self.zone_id[i, j] = zone

            if zone >= 0 and zone < zone_params.shape[0]:
                # Hydrology parameters
                self.K_sat_field[i, j] = zone_params[zone, 0]
                self.theta_s_field[i, j] = zone_params[zone, 1]
                self.theta_i_field[i, j] = zone_params[zone, 2]
                self.psi_f_field[i, j] = zone_params[zone, 3]

                # Soil parameters
                self.c_field[i, j] = zone_params[zone, 4]
                self.phi_field[i, j] = zone_params[zone, 5]
                self.gamma_s_field[i, j] = zone_params[zone, 6]
                self.gamma_w_field[i, j] = zone_params[zone, 7]
                self.depth_field[i, j] = zone_params[zone, 8]

                # Rheology parameters
                self.n_manning_field[i, j] = zone_params[zone, 9]
                self.alpha1_field[i, j] = zone_params[zone, 10]
                self.beta1_field[i, j] = zone_params[zone, 11]
                self.alpha2_field[i, j] = zone_params[zone, 12]
                self.beta2_field[i, j] = zone_params[zone, 13]

                # Double-layer parameters (columns 14-25, only if present)
                if zone_params.shape[1] > 14:
                    self.alpha_top_field[i, j] = zone_params[zone, 14]
                    self.alpha_bottom_field[i, j] = zone_params[zone, 15]
                    self.K_sat_top_field[i, j] = zone_params[zone, 16]
                    self.K_sat_bottom_field[i, j] = zone_params[zone, 17]
                    self.theta_sat_top_field[i, j] = zone_params[zone, 18]
                    self.theta_sat_bottom_field[i, j] = zone_params[zone, 19]
                    self.theta_res_top_field[i, j] = zone_params[zone, 20]
                    self.theta_res_bottom_field[i, j] = zone_params[zone, 21]
                    self.phib_field[i, j] = zone_params[zone, 22]
                    self.kero_field[i, j] = zone_params[zone, 23]
                    self.ltstar_field[i, j] = zone_params[zone, 24]
                    self.lbstar_field[i, j] = zone_params[zone, 25]
                    if zone_params.shape[1] > 26:
                        self.ctao_field[i, j] = zone_params[zone, 26]

    def initialize_all(self):
        """Initialize all variables to default values."""
        self.zero_flow_variables()
        self.zero_hydrology_variables()
        self.zero_stability_variables()
        self.zero_erosion_variables()
        self.zero_dynamic_wave_variables()
        self.zero_doublelayer_variables()
        self.zero_spatial_zone_variables()
        self.compute_slopes()
        self._flow_connectivity_version += 1

    @ti.kernel
    def _set_flow_connectivity_kernel(
        self,
        cell_id_np: ti.types.ndarray(),
        neighbor_id_np: ti.types.ndarray(),
        neighbor_i_np: ti.types.ndarray(),
        neighbor_j_np: ti.types.ndarray(),
    ):
        """
        Set explicit 8-direction connectivity matching original flodir.f90.

        All arrays use Taichi ordering (nx, ny, 8) but Fortran directional order:
        [N, NE, E, SE, S, SW, W, NW].
        """
        for i, j in self.cell_id:
            self.cell_id[i, j] = cell_id_np[i, j]
            for d in ti.static(range(8)):
                self.flow_neighbor_id[i, j, d] = neighbor_id_np[i, j, d]
                self.flow_neighbor_i[i, j, d] = neighbor_i_np[i, j, d]
                self.flow_neighbor_j[i, j, d] = neighbor_j_np[i, j, d]

    def set_flow_connectivity(
        self,
        cell_id_np: np.ndarray,
        neighbor_id_np: np.ndarray,
        neighbor_i_np: np.ndarray,
        neighbor_j_np: np.ndarray,
    ):
        """Set explicit flow connectivity and bump the immutable topology version."""
        self._set_flow_connectivity_kernel(cell_id_np, neighbor_id_np, neighbor_i_np, neighbor_j_np)
        self._flow_connectivity_version += 1

    def mark_flow_connectivity_changed(self):
        """Bump the host topology version after direct checkpoint restoration."""
        self._flow_connectivity_version += 1

    def flow_connectivity_version(self) -> int:
        """Return the host-side version for immutable flow topology/index arrays."""
        return self._flow_connectivity_version

    def to_numpy(self, field_name: str) -> np.ndarray:
        """Export a field to numpy array."""
        field = getattr(self, field_name)
        return field.to_numpy()

    def get_flow_state(self) -> dict:
        """Get current flow state as numpy arrays."""
        return {
            'h': self.h.to_numpy(),
            'u': self.u.to_numpy(),
            'v': self.v.to_numpy(),
            'Cv': self.Cv.to_numpy(),
            'z_bed': self.z_bed.to_numpy(),
        }

    def get_full_state(
        self,
        *,
        include_fields: Optional[Iterable[str]] = None,
        exclude_fields: Optional[Iterable[str]] = None,
    ) -> dict:
        """Get simulation state, optionally limited to a field subset."""
        include = set(include_fields) if include_fields is not None else None
        exclude = set(exclude_fields or ())
        field_attrs = (
            ('h', 'h'),
            ('u', 'u'),
            ('v', 'v'),
            ('Cv', 'Cv'),
            ('rho', 'rho'),
            ('z_bed', 'z_bed'),
            ('z_original', 'z_original'),
            ('cell_id', 'cell_id'),
            ('cell_area_cal', 'cell_area_cal'),
            ('dfs_outflow_mask', 'dfs_outflow_mask'),
            ('zone_id', 'zone_id'),
            ('erosion_depth', 'erosion_depth'),
            ('deposition_depth', 'deposition_depth'),
            ('depo_thickness', 'depo_thickness'),
            ('FS', 'FS'),
            ('psi', 'psi'),
            ('is_nodata', 'is_nodata'),
            ('fv_fortran', 'fv_fortran'),
            ('vdir', 'fv_fortran'),
            ('tanslo_fortran', 'tanslo_fortran'),
            ('slope_mag', 'slope_mag'),
            ('slope_angle', 'slope_angle'),
            ('max_flow_depth', 'max_flow_depth'),
            ('max_flow_velocity', 'max_flow_velocity'),
            ('total_depth', 'total_depth'),
            ('fdepth', 'fdepth'),
            ('ctao_field', 'ctao_field'),
            ('fhpredi1', 'fhpredi1'),
            ('frhopredi1', 'frhopredi1'),
            ('fhpredi', 'fhpredi'),
            ('frhopredi', 'frhopredi'),
            ('fhpredi2', 'fhpredi2'),
            ('frhopredi2', 'frhopredi2'),
            ('tempele', 'tempele'),
            ('tempfsh_flow', 'tempfsh_flow'),
            ('tempfsrho_flow', 'tempfsrho_flow'),
            ('qnet_fortran', 'qnet_fortran'),
            ('qtnet_fortran', 'qtnet_fortran'),
            ('qmassnet_fortran', 'qmassnet_fortran'),
            ('cvlimit_temp', 'cvlimit_temp'),
            ('tau_temp', 'tau_temp'),
            ('taoc_temp', 'taoc_temp'),
            ('taoc_old_temp', 'taoc_old_temp'),
            ('taoc_fortran_temp', 'taoc_fortran_temp'),
            ('taoc_delta_temp', 'taoc_delta_temp'),
            ('tau_minus_taoc_old_temp', 'tau_minus_taoc_old_temp'),
            ('tau_minus_taoc_fortran_temp', 'tau_minus_taoc_fortran_temp'),
            ('rholimit_temp', 'rholimit_temp'),
            ('absubar_temp', 'absubar_temp'),
            ('absubar_vorth_temp', 'absubar_vorth_temp'),
            ('absubar_vcomp_temp', 'absubar_vcomp_temp'),
            ('absubar_velocity_state_scale_temp', 'absubar_velocity_state_scale_temp'),
            ('absubar_selected_is_vorth_temp', 'absubar_selected_is_vorth_temp'),
            ('absubar_fv_used_temp', 'absubar_fv_used_temp'),
            ('rhodepo_temp', 'rhodepo_temp'),
            ('erorate_raw_temp', 'erorate_raw_temp'),
            ('erorate_rholimit_clamped_temp', 'erorate_rholimit_clamped_temp'),
            ('erorate_clamped_temp', 'erorate_clamped_temp'),
            ('deporate_raw_temp', 'deporate_raw_temp'),
            ('deporate_clamped_temp', 'deporate_clamped_temp'),
            ('erosion_gate_temp', 'erosion_gate_temp'),
            ('tau_gt_taoc_old_temp', 'tau_gt_taoc_old_temp'),
            ('tau_gt_taoc_fortran_temp', 'tau_gt_taoc_fortran_temp'),
            ('all_erosion_gate_old_temp', 'all_erosion_gate_old_temp'),
            ('all_erosion_gate_fortran_temp', 'all_erosion_gate_fortran_temp'),
            ('deposition_gate_temp', 'deposition_gate_temp'),
            ('rholimit_clamp_temp', 'rholimit_clamp_temp'),
            ('erodible_clamp_temp', 'erodible_clamp_temp'),
            ('pt', 'pt'),
            ('desatt', 'desatt'),
            ('inidesatt', 'inidesatt'),
        )
        state = {}
        for name, attr in field_attrs:
            if include is not None and name not in include:
                continue
            if name in exclude:
                continue
            state[name] = getattr(self, attr).to_numpy()
        return state
