"""
Erosion model for EDDA simulation.

This module implements bed erosion based on excess shear stress,
following the original EDDA formulation with concentration limits,
Mohr-Coulomb failure criterion, and erodible layer tracking.
"""
import taichi as ti
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edda.core.fields import EDDAFields
    from edda.config.sim_config import ErosionParams

DEG2RAD = 0.017453292519943295  # pi/180


@ti.kernel
def compute_cvlimit(
    fields: ti.template(),
    rho_water: ti.f32,
    rho_sediment: ti.f32,
    cvstar: ti.f32,
):
    """
    Compute concentration limit (cvlimit) for each cell.
    Reads phi from spatial field (zone-aware).
    Reference: dfs.F90:143-145
    """
    for i, j in fields.h:
        if fields.is_nodata[i, j]:
            continue

        tan_slope = fields.slope_mag[i, j]
        phi_rad = fields.phi_field[i, j] * DEG2RAD
        tan_phi = ti.tan(phi_rad)

        cvlimit = cvstar
        if tan_slope < 0.0:
            cvlimit = 0.0
        else:
            denominator = (rho_sediment - rho_water) * (tan_phi - tan_slope)
            if ti.abs(denominator) < 1e-10:
                cvlimit = cvstar
            else:
                cvlimit = rho_water * tan_slope / denominator
                if cvlimit < 0.15:
                    cvlimit = 6.7 * cvlimit * cvlimit
                if cvlimit < 0.0 or cvlimit > cvstar:
                    cvlimit = cvstar

        fields.cvlimit_temp[i, j] = cvlimit


@ti.kernel
def compute_bed_shear_stress(
    fields: ti.template(),
    g: ti.f32,
    manningb: ti.f32,
    manningm: ti.f32,
    kresis: ti.f32,
    cs: ti.f32,
):
    """
    Compute bed shear stress. Reads alpha1/beta1/alpha2/beta2/n_manning/phi from spatial fields.
    Reference: dfs.F90:331-362
    """
    for i, j in fields.h:
        if fields.is_nodata[i, j]:
            fields.tau_temp[i, j] = 0.0
            continue

        h = fields.h[i, j]
        u = fields.u[i, j]
        v = fields.v[i, j]
        Cv = fields.Cv[i, j]
        rho = fields.rho[i, j]

        if h < 1e-6:
            fields.tau_temp[i, j] = 0.0
            continue

        vel_mag = ti.sqrt(u * u + v * v)
        slope_x = fields.slope_x[i, j]
        slope_y = fields.slope_y[i, j]
        tan_slope = ti.sqrt(slope_x * slope_x + slope_y * slope_y)
        slope_angle = ti.atan2(tan_slope, 1.0)

        # Read from spatial fields
        phi_rad = fields.phi_field[i, j] * DEG2RAD
        tan_phi = ti.tan(phi_rad)
        n_manning = fields.n_manning_field[i, j]
        alpha1 = fields.alpha1_field[i, j]
        beta1 = fields.beta1_field[i, j]
        alpha2 = fields.alpha2_field[i, j]
        beta2 = fields.beta2_field[i, j]

        gamma_deb = rho * g
        normfriccoe = ti.cos(slope_angle) * ti.cos(slope_angle) * tan_phi

        # Yield stress slope
        cvtol = 0.1
        sfy = 0.0
        if Cv > cvtol:
            if slope_angle > 0.17453292519943295:  # > 10 degrees
                sfy = (1.0 - cs) * Cv * (rho - 1000.0) / rho * normfriccoe
            else:
                sfy = alpha1 * ti.exp(beta1 * Cv) / rho / g / h

        # Viscous friction slope
        miudebris = 0.0
        if Cv <= 0.1:
            miudebris = 0.001 + Cv / 0.1 * (alpha2 * ti.exp(beta2 * 0.1) - 0.001)
        else:
            miudebris = alpha2 * ti.exp(beta2 * Cv)
        coemiu = kresis * miudebris / 8.0 / gamma_deb / (h * h)
        sfmiu = coemiu * vel_mag

        # Manning friction slope
        manningbar = n_manning
        if Cv > cvtol:
            manningbar = n_manning * manningb * ti.exp(manningm * Cv)
        coemanning = manningbar * manningbar / ti.pow(h, 1.333)
        sfmanning = coemanning * vel_mag * vel_mag

        tau = (sfmanning + sfy + sfmiu) * gamma_deb * h
        fields.tau_temp[i, j] = tau


@ti.kernel
def compute_erosion_rate(
    fields: ti.template(),
    g: ti.f32,
    rho_water: ti.f32,
    rho_sediment: ti.f32,
    cvstar: ti.f32,
    h_min: ti.f32,
):
    """
    Compute erosion rate. Reads k_erosion and c from spatial fields.
    Reference: dfs.F90:365-366
    """
    for i, j in fields.erosion_rate:
        if fields.is_nodata[i, j]:
            fields.erosion_rate[i, j] = 0.0
            continue

        h = fields.h[i, j]
        Cv = fields.Cv[i, j]
        rho = fields.rho[i, j]
        cvlimit = fields.cvlimit_temp[i, j]
        tau = fields.tau_temp[i, j]

        if h < h_min or Cv >= cvlimit:
            fields.erosion_rate[i, j] = 0.0
            continue

        # Read from spatial fields
        phi_rad = fields.phi_field[i, j] * DEG2RAD
        tan_phi = ti.tan(phi_rad)
        k_erosion = fields.kero_field[i, j]
        c_cohesion = fields.c_field[i, j]

        # Critical shear stress (Mohr-Coulomb)
        taoc = c_cohesion + rho * g * h * tan_phi

        E = 0.0
        if tau > taoc:
            E = k_erosion * (tau - taoc)

        fields.erosion_rate[i, j] = E


@ti.kernel
def apply_erosion(
    fields: ti.template(),
    dt: ti.f32,
    rho_sediment: ti.f32,
    rho_water: ti.f32,
    cvstar: ti.f32,
):
    """
    Apply erosion with erodible layer tracking and density-correct mass conservation.
    Reference: dfs.F90:382-392
    """
    for i, j in fields.erosion_rate:
        if fields.is_nodata[i, j]:
            continue

        E = fields.erosion_rate[i, j]
        if E <= 0.0:
            continue

        h = fields.h[i, j]
        Cv = fields.Cv[i, j]
        rho = fields.rho[i, j]

        if h < 1e-6:
            continue

        # Recompute cvlimit for density limit check
        slope_x = fields.slope_x[i, j]
        slope_y = fields.slope_y[i, j]
        tan_slope = ti.sqrt(slope_x * slope_x + slope_y * slope_y)
        phi_rad = fields.phi_field[i, j] * DEG2RAD
        tan_phi = ti.tan(phi_rad)

        cvlimit = cvstar
        if tan_slope >= 0.0:
            denominator = (rho_sediment - rho_water) * (tan_phi - tan_slope)
            if ti.abs(denominator) > 1e-10:
                cvlimit = rho_water * tan_slope / denominator
                if cvlimit < 0.15:
                    cvlimit = 6.7 * cvlimit * cvlimit
                if cvlimit < 0.0 or cvlimit > cvstar:
                    cvlimit = cvstar

        rholimit = cvlimit * (rho_sediment - rho_water) + rho_water

        # FIX 4c: Erosion density using rho_ero mass conservation
        rho_ero = cvstar * (rho_sediment - rho_water) + rho_water

        # Limit erosion rate to not exceed cvlimit
        rho_new = (rho * h + E * dt * rho_ero) / (h + E * dt)
        if rho_new > rholimit:
            E = (rholimit - rho) * h / (rho_ero - rholimit) / dt
            if E < 0.0:
                E = 0.0

        dz_erosion = E * dt

        # FIX 4b: Erodible layer tracking (replaces 0.1*h limit)
        available = fields.erodible_thickness[i, j] + fields.depo_thickness[i, j]
        if dz_erosion > available:
            dz_erosion = available
            if dt > 0.0:
                E = dz_erosion / dt

        if dz_erosion <= 0.0:
            continue

        # Update erodible/depo layers
        if dz_erosion <= fields.depo_thickness[i, j]:
            fields.depo_thickness[i, j] -= dz_erosion
        else:
            remaining = dz_erosion - fields.depo_thickness[i, j]
            fields.depo_thickness[i, j] = 0.0
            fields.erodible_thickness[i, j] -= remaining

        # Update bed elevation
        fields.z_bed[i, j] -= dz_erosion
        fields.erosion_depth[i, j] += dz_erosion

        # FIX 4c: Density-correct Cv update
        rho_new_actual = (rho * h + rho_ero * dz_erosion) / (h + dz_erosion)
        Cv_new = (rho_new_actual - rho_water) / (rho_sediment - rho_water)
        if Cv_new > cvstar:
            Cv_new = cvstar
        if Cv_new < 0.0:
            Cv_new = 0.0

        fields.h[i, j] = h + dz_erosion
        fields.Cv[i, j] = Cv_new
        fields.rho[i, j] = rho_new_actual


class ErosionModel:
    """Erosion model manager for bed erosion processes."""

    def __init__(
        self,
        fields: 'EDDAFields',
        tau_c: float = 10.0,
        k_erosion: float = 1e-5,
        rho_sediment: float = 2650.0,
        rho_water: float = 1000.0,
        alpha1: float = 0.0765,
        beta1: float = 10.11,
        alpha2: float = 0.0538,
        beta2: float = 17.48,
        n_manning: float = 0.03,
        cvstar: float = 0.65,
        phi: float = 30.0,
    ):
        self.fields = fields
        self.rho_sediment = rho_sediment
        self.rho_water = rho_water
        self.cvstar = cvstar
        self.g = 9.81

        # Original EDDA parameters (not per-cell, used as kernel args)
        self.manningb = 0.0538
        self.manningm = 6.0896
        self.kresis = 8.0
        self.cs = 0.9

    def compute_rates(self):
        """
        Compute erosion-related source terms without modifying the flow state.

        Keeping rate evaluation separate from application lets the main solver
        align more closely with original EDDA, where erosion/deposition rates
        are both determined from the same pre-update state before being applied.
        """
        compute_cvlimit(
            self.fields, self.rho_water, self.rho_sediment, self.cvstar,
        )
        compute_bed_shear_stress(
            self.fields, self.g,
            self.manningb, self.manningm, self.kresis, self.cs,
        )
        compute_erosion_rate(
            self.fields, self.g,
            self.rho_water, self.rho_sediment, self.cvstar,
            0.015,  # Minimum flow depth
        )

    def apply_rates(self, dt: float):
        """Apply the precomputed erosion rate to the state variables."""
        apply_erosion(
            self.fields, dt,
            self.rho_sediment, self.rho_water, self.cvstar,
        )

    def step(self, dt: float):
        """Perform one time step of erosion calculation."""
        self.compute_rates()
        self.apply_rates(dt)

    def get_erosion_depth(self) -> np.ndarray:
        return self.fields.erosion_depth.to_numpy()

    def get_erosion_rate(self) -> np.ndarray:
        return self.fields.erosion_rate.to_numpy()
