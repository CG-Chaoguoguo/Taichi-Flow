"""
Deposition model for EDDA simulation.

Implements sediment deposition following the original EDDA formulation (dfs.F90:400-428)
with velocity-based deposition criteria, density conservation, and erodible layer tracking.
"""
import taichi as ti
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edda.core.fields import EDDAFields
    from edda.config.sim_config import ErosionParams

DEG2RAD = 0.017453292519943295


@ti.kernel
def compute_deposition_rate(
    fields: ti.template(),
    g: ti.f32,
    rho_water: ti.f32,
    rho_sediment: ti.f32,
    cvstar: ti.f32,
    d50: ti.f32,
    coedepo: ti.f32,
    dt: ti.f32,
):
    """
    Compute deposition rate following original EDDA (dfs.F90:400-428).

    Deposition occurs when Cv > cvlimit AND velocity < 2/3 * fvdepo.
    """
    for i, j in fields.deposition_rate:
        if fields.is_nodata[i, j]:
            fields.deposition_rate[i, j] = 0.0
            continue

        h = fields.h[i, j]
        u = fields.u[i, j]
        v = fields.v[i, j]
        Cv = fields.Cv[i, j]
        rho = fields.rho[i, j]

        if h < 1e-6 or Cv < 1e-6:
            fields.deposition_rate[i, j] = 0.0
            continue

        vel_mag = ti.sqrt(u * u + v * v)
        cvlimit = fields.cvlimit_temp[i, j]

        # Read phi from spatial field
        phi_rad = fields.phi_field[i, j] * DEG2RAD
        tan_phi = ti.tan(phi_rad)

        # FIX 5a: Deposition velocity limit (dfs.F90:400-410)
        deporate = 0.0

        if Cv > 1e-6 and cvstar > Cv:
            lambdainverse = ti.pow(cvstar / Cv, 0.333) - 1.0

            # Equivalent slope angle from concentration
            tanthetae = Cv * (rho_sediment - rho_water) * tan_phi / (Cv * (rho_sediment - rho_water) + rho_water)
            sinthetae = ti.sin(ti.atan2(tanthetae, 1.0))

            # Deposition velocity limit
            fvdepo = 0.0
            if d50 > 1e-10 and rho_sediment > 1e-10 and sinthetae > 1e-10 and rho > 1e-10:
                fvdepo = 2.0 / 5.0 / d50 * ti.sqrt(g * sinthetae * rho / 0.02 / rho_sediment) * lambdainverse * ti.pow(h, 1.5)

            # Deposition condition: Cv > cvlimit AND vel < 2/3 * fvdepo
            if Cv > cvlimit and fvdepo > 1e-10 and vel_mag < 2.0 / 3.0 * fvdepo:
                deporate = coedepo * (1.0 - 1.5 * vel_mag / fvdepo) * (cvlimit - Cv) / cvstar * vel_mag

        # deporate is negative (removal from flow), make it positive for apply step
        if deporate > 0.0:
            deporate = 0.0  # Should be negative or zero
        deporate = ti.abs(deporate)

        # FIX 5b: Density conservation checks (dfs.F90:409-414)
        rhodepo = cvstar * (rho_sediment - rho_water) + rho_water

        if dt > 0.0 and deporate > 0.0:
            if deporate * dt > h:
                deporate = h / dt
            if deporate * dt * rhodepo > h * rho:
                if deporate * dt > 1e-10:
                    rhodepo = h * rho / (deporate * dt)
            if (rho * h - deporate * dt * rhodepo) < (rho_water * (h - deporate * dt)):
                if (rhodepo - rho_water) > 1e-10:
                    deporate = (rho_water - rho) * h / (rhodepo - rho_water) / dt
                    if deporate < 0.0:
                        deporate = 0.0

        fields.deposition_rate[i, j] = deporate


@ti.kernel
def apply_deposition(
    fields: ti.template(),
    dt: ti.f32,
    rho_sediment: ti.f32,
    rho_water: ti.f32,
    cvstar: ti.f32,
):
    """Apply deposition, update bed elevation, Cv, and erodible layer."""
    for i, j in fields.deposition_rate:
        if fields.is_nodata[i, j]:
            continue

        D = fields.deposition_rate[i, j]
        if D <= 0.0:
            continue

        h = fields.h[i, j]
        Cv = fields.Cv[i, j]
        rho = fields.rho[i, j]

        if h < 1e-6 or Cv < 1e-6:
            continue

        dz_deposition = D * dt

        # Limit to available sediment
        max_deposition = h * Cv
        if dz_deposition > max_deposition:
            dz_deposition = max_deposition

        # Update bed elevation
        fields.z_bed[i, j] += dz_deposition
        fields.deposition_depth[i, j] += dz_deposition

        # FIX 5c: Deposited material becomes erodible
        fields.depo_thickness[i, j] += dz_deposition

        # Update flow depth and concentration
        sediment_volume = Cv * h - dz_deposition
        if sediment_volume < 0.0:
            sediment_volume = 0.0

        h_new = h - dz_deposition
        if h_new < 1e-6:
            fields.h[i, j] = 0.0
            fields.Cv[i, j] = 0.0
            fields.u[i, j] = 0.0
            fields.v[i, j] = 0.0
        else:
            Cv_new = sediment_volume / h_new
            if Cv_new < 0.0:
                Cv_new = 0.0
            if Cv_new > cvstar:
                Cv_new = cvstar
            fields.h[i, j] = h_new
            fields.Cv[i, j] = Cv_new
            fields.rho[i, j] = Cv_new * (rho_sediment - rho_water) + rho_water


@ti.func
def calculate_settling_velocity(d50: ti.f32, rho_s: ti.f32, rho_w: ti.f32, nu: ti.f32) -> ti.f32:
    """Calculate settling velocity using Ferguson and Church (2004)."""
    g = 9.81
    R = (rho_s - rho_w) / rho_w
    D_star = d50 * ti.pow(R * g / (nu * nu), 1.0 / 3.0)
    C1 = 18.0
    C2 = 1.0
    w_s = (R * g * nu / d50) * (ti.sqrt(C1 * C1 + C2 * D_star * D_star * D_star) - C1)
    return w_s


class DepositionModel:
    """Deposition model manager following original EDDA formulation."""

    def __init__(
        self,
        fields: 'EDDAFields',
        params: 'ErosionParams',
        d50: float = 0.001,
        rho_sediment: float = 2650.0,
        rho_water: float = 1000.0,
        cvstar: float = 0.65,
        coedepo: float = 0.1,
    ):
        self.fields = fields
        self.params = params
        self.d50 = d50
        self.rho_sediment = rho_sediment
        self.rho_water = rho_water
        self.cvstar = cvstar
        self.coedepo = coedepo
        self.g = 9.81

    def compute_rates(self, dt: float):
        """
        Compute deposition rate from the current state without applying it yet.

        This keeps deposition evaluation synchronized with erosion evaluation,
        matching original EDDA's source-term staging more closely.
        """
        compute_deposition_rate(
            self.fields, self.g,
            self.rho_water, self.rho_sediment, self.cvstar,
            self.d50, self.coedepo, dt,
        )

    def apply_rates(self, dt: float):
        """Apply the precomputed deposition rate to the state variables."""
        apply_deposition(
            self.fields, dt,
            self.rho_sediment, self.rho_water, self.cvstar,
        )

    def step(self, dt: float):
        """Perform one time step of deposition calculation."""
        self.compute_rates(dt)
        self.apply_rates(dt)

    def get_deposition_depth(self) -> np.ndarray:
        return self.fields.deposition_depth.to_numpy()

    def get_deposition_rate(self) -> np.ndarray:
        return self.fields.deposition_rate.to_numpy()

    def set_settling_velocity(self, w_s: float):
        """Kept for backward compatibility."""
        pass
