"""
Flow rheology models for EDDA simulation.

This module implements rheology models for both clear water flow
(Manning formula) and debris flow (quadratic model), with dynamic
updates of mixture density, yield stress, and viscosity.
"""
import taichi as ti
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edda.core.fields import EDDAFields
    from edda.config.sim_config import RheologyParams


@ti.kernel
def update_mixture_density(
    fields: ti.template(),
    rho_water: ti.f32,
    rho_sediment: ti.f32,
):
    """
    Update mixture density based on sediment concentration.

    Mixture density is calculated as:
    rho = rho_water * (1 - Cv) + rho_sediment * Cv

    Args:
        fields: EDDAFields instance
        rho_water: Water density (kg/m³)
        rho_sediment: Sediment density (kg/m³)
    """
    for i, j in fields.rho:
        if fields.is_nodata[i, j]:
            continue

        Cv = fields.Cv[i, j]

        # Ensure Cv is within valid range [0, 1]
        if Cv < 0.0:
            Cv = 0.0
        elif Cv > 1.0:
            Cv = 1.0

        # Calculate mixture density
        fields.rho[i, j] = rho_water * (1.0 - Cv) + rho_sediment * Cv

    # Apply boundary conditions: outflow boundaries have rho = rhow (line 285 in original EDDA)
    for i, j in fields.rho:
        if fields.is_boundary[i, j]:
            bc_type = fields.boundary_type[i, j]
            if bc_type == 1:  # Outflow boundary
                fields.rho[i, j] = rho_water


@ti.kernel
def update_rheology_parameters(
    fields: ti.template(),
    rho_sediment: ti.f32,
    g: ti.f32,
):
    """
    Update yield stress and viscosity for debris flow using quadratic model with spatial parameters.

    For debris flow (Cv >= 0.2), the quadratic model gives:
    tau_y = alpha1 * rho_s * g * exp(beta1 * Cv)
    mu = alpha2 * rho_s * exp(beta2 * Cv)

    where:
    - tau_y: yield stress (Pa)
    - mu: dynamic viscosity (Pa·s)
    - rho_s: sediment density (kg/m³)
    - g: gravitational acceleration (m/s²)
    - Cv: volumetric sediment concentration
    - alpha1, beta1, alpha2, beta2: empirical parameters from spatial fields

    Args:
        fields: EDDAFields instance
        rho_sediment: Sediment density (kg/m³)
        g: Gravitational acceleration (m/s²)
    """
    for i, j in fields.tau_y:
        if fields.is_nodata[i, j]:
            continue

        Cv = fields.Cv[i, j]

        # Ensure Cv is within valid range
        if Cv < 0.0:
            Cv = 0.0
        elif Cv > 1.0:
            Cv = 1.0

        # Read spatial rheology parameters for this cell
        alpha1 = fields.alpha1_field[i, j]
        beta1 = fields.beta1_field[i, j]
        alpha2 = fields.alpha2_field[i, j]
        beta2 = fields.beta2_field[i, j]

        # Calculate yield stress using quadratic model
        # tau_y = alpha1 * rho_s * g * exp(beta1 * Cv)
        fields.tau_y[i, j] = alpha1 * rho_sediment * g * ti.exp(beta1 * Cv)

        # Calculate dynamic viscosity using quadratic model
        # mu = alpha2 * rho_s * exp(beta2 * Cv)
        fields.mu[i, j] = alpha2 * rho_sediment * ti.exp(beta2 * Cv)


@ti.kernel
def compute_manning_friction(
    fields: ti.template(),
    n_manning: ti.f32,
    g: ti.f32,
    dt: ti.f32,
):
    """
    Compute friction using Manning formula for clear water flow (Cv < 0.2).

    Manning friction slope:
    S_f = (n² * v²) / (h^(4/3))

    Friction force per unit mass:
    F_friction = -g * S_f * (v / |v|)

    Args:
        fields: EDDAFields instance
        n_manning: Manning roughness coefficient
        g: Gravitational acceleration (m/s²)
        dt: Time step (s)
    """
    for i, j in fields.h:
        if fields.is_nodata[i, j]:
            continue

        h = fields.h[i, j]
        u = fields.u[i, j]
        v = fields.v[i, j]

        # Skip if no flow
        if h < 1e-6:
            continue

        # Calculate velocity magnitude
        vel_mag = ti.sqrt(u * u + v * v)

        # Skip if velocity is negligible
        if vel_mag < 1e-6:
            continue

        # Calculate Manning friction slope
        # S_f = (n² * v²) / (h^(4/3))
        h_pow = ti.pow(h, 4.0 / 3.0)
        S_f = (n_manning * n_manning * vel_mag * vel_mag) / h_pow

        # Calculate friction force magnitude
        F_mag = g * S_f

        # Apply friction to velocity (implicit method for stability)
        # v_new = v / (1 + F * dt / v)
        factor = 1.0 / (1.0 + F_mag * dt / vel_mag)

        fields.u[i, j] = u * factor
        fields.v[i, j] = v * factor


@ti.kernel
def compute_debris_flow_friction(
    fields: ti.template(),
    g: ti.f32,
    dt: ti.f32,
):
    """
    Compute friction for debris flow (Cv >= 0.2) using Bingham rheology.

    For Bingham fluid:
    tau = tau_y + mu * (du/dz)

    Simplified for shallow flow:
    tau_b = tau_y + (mu * v) / h

    Args:
        fields: EDDAFields instance
        g: Gravitational acceleration (m/s²)
        dt: Time step (s)
    """
    for i, j in fields.h:
        if fields.is_nodata[i, j]:
            continue

        h = fields.h[i, j]
        u = fields.u[i, j]
        v = fields.v[i, j]
        rho = fields.rho[i, j]
        tau_y = fields.tau_y[i, j]
        mu = fields.mu[i, j]

        # Skip if no flow
        if h < 1e-6:
            continue

        # Calculate velocity magnitude
        vel_mag = ti.sqrt(u * u + v * v)

        # Skip if velocity is negligible
        if vel_mag < 1e-6:
            continue

        # Calculate bed shear stress
        # tau_b = tau_y + (mu * v) / h
        tau_b = tau_y + (mu * vel_mag) / h

        # Calculate friction force per unit mass
        # F = tau_b / (rho * h)
        F_mag = tau_b / (rho * h)

        # Apply friction to velocity (implicit method)
        factor = 1.0 / (1.0 + F_mag * dt / vel_mag)

        fields.u[i, j] = u * factor
        fields.v[i, j] = v * factor


@ti.kernel
def adjust_manning_coefficient(
    fields: ti.template(),
    manning: ti.template(),
    manning_ori: ti.template(),
    fhmax: ti.f32,
):
    """
    Dynamically adjust Manning coefficient based on flow depth.

    For h < fhmax (typically 1.0 m):
        manning = manning_ori * 1.5 * exp(-0.4 * h / fhmax)
    Otherwise:
        manning = manning_ori

    Reference: wfs.F90:307-330

    Args:
        fields: EDDAFields instance
        manning: Current Manning coefficient field
        manning_ori: Original Manning coefficient field
        fhmax: Maximum flow depth threshold (m)
    """
    for i, j in manning:
        if fields.is_nodata[i, j]:
            continue

        h = fields.h[i, j]

        if h < fhmax:
            manning[i, j] = manning_ori[i, j] * 1.5 * ti.exp(-0.4 * h / fhmax)
        else:
            manning[i, j] = manning_ori[i, j]


@ti.data_oriented
class RheologyModel:
    """
    Rheology model manager for flow friction and material properties.
    """

    def __init__(self, fields: 'EDDAFields', params: 'RheologyParams'):
        """
        Initialize rheology model.

        Args:
            fields: EDDAFields instance
            params: RheologyParams configuration
        """
        self.fields = fields
        self.params = params
        self.g = 9.81  # Gravitational acceleration (m/s²)

        # Manning coefficient fields for dynamic adjustment
        self.manning = ti.field(dtype=fields.fp, shape=(fields.nx, fields.ny))
        self.manning_ori = ti.field(dtype=fields.fp, shape=(fields.nx, fields.ny))
        self.fhmax = 1.0  # Maximum flow depth threshold for Manning adjustment (m)

        # Initialize Manning coefficients
        self._initialize_manning()

    @ti.kernel
    def _initialize_manning(self):
        """Initialize Manning coefficient fields from spatial fields."""
        for i, j in self.manning:
            n_manning_local = self.fields.n_manning_field[i, j]
            self.manning[i, j] = n_manning_local
            self.manning_ori[i, j] = n_manning_local

    def update_properties(self):
        """
        Update mixture density and rheological properties with spatial parameters.
        """
        # Update mixture density
        update_mixture_density(
            self.fields,
            self.params.rho_water,
            self.params.rho_sediment,
        )

        # Update yield stress and viscosity for debris flow using spatial parameters
        update_rheology_parameters(
            self.fields,
            self.params.rho_sediment,
            self.g,
        )

    def prepare_for_flow(self):
        """
        Synchronize Manning and material properties before the transport solve.

        This intentionally avoids applying an extra friction impulse. The
        shallow-water Newton-Raphson solve already accounts for Manning-based
        momentum resistance, so pre-flow preparation should only refresh the
        coefficients and material state used by that solve.
        """
        adjust_manning_coefficient(
            self.fields,
            self.manning,
            self.manning_ori,
            self.fhmax
        )
        self.update_properties()

    def apply_friction(self, dt: float):
        """
        Apply friction based on flow type (clear water or debris flow).

        Args:
            dt: Time step (s)
        """
        # Apply friction separately for clear water and debris flow
        # This is done in a single pass by checking Cv threshold
        self._apply_friction_combined(dt)

    @ti.kernel
    def _apply_friction_combined(self, dt: ti.f32):
        """
        Apply friction for both clear water and debris flow in one kernel.

        Args:
            dt: Time step (s)
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            h = self.fields.h[i, j]
            u = self.fields.u[i, j]
            v = self.fields.v[i, j]
            Cv = self.fields.Cv[i, j]

            # Skip if no flow
            if h < 1e-6:
                continue

            # Calculate velocity magnitude
            vel_mag = ti.sqrt(u * u + v * v)

            # Skip if velocity is negligible
            if vel_mag < 1e-6:
                continue

            # Choose friction model based on concentration threshold
            F_mag = 0.0
            if Cv < self.params.Cv_threshold:
                # Clear water flow: Manning formula with dynamic coefficient
                n_manning_local = self.manning[i, j]
                h_pow = ti.pow(h, 4.0 / 3.0)
                S_f = (n_manning_local * n_manning_local * vel_mag * vel_mag) / h_pow
                F_mag = self.g * S_f
            else:
                # Debris flow: Bingham rheology
                rho = self.fields.rho[i, j]
                tau_y = self.fields.tau_y[i, j]
                mu = self.fields.mu[i, j]
                tau_b = tau_y + (mu * vel_mag) / h
                F_mag = tau_b / (rho * h)

            # Apply friction (implicit method for stability)
            factor = 1.0 / (1.0 + F_mag * dt / vel_mag)

            self.fields.u[i, j] = u * factor
            self.fields.v[i, j] = v * factor

    @ti.kernel
    def limit_froude_number(self, limitfr: ti.f32):
        """
        Limit Froude number by adjusting Manning coefficient.

        If Froude number exceeds limitfr, increase Manning coefficient.
        If below limitfr, decrease Manning coefficient back to original.

        Reference: wfs.F90:390-420

        Args:
            limitfr: Froude number limit (typically 0.8-1.0)
        """
        for i, j in self.manning:
            if self.fields.is_nodata[i, j]:
                continue

            h = self.fields.h[i, j]
            u = self.fields.u[i, j]
            v = self.fields.v[i, j]

            # Skip if no flow
            if h < 1e-6:
                continue

            # Calculate velocity magnitude
            vel_mag = ti.sqrt(u * u + v * v)

            # Calculate Froude number
            currentfr = vel_mag / ti.sqrt(self.g * h)

            if currentfr > limitfr:
                # Increase Manning coefficient to reduce velocity
                dmanning = (self.manning[i, j] - self.manning_ori[i, j]) / self.manning_ori[i, j]

                if dmanning < 0.002:
                    self.manning[i, j] = self.manning[i, j] + 0.0002
                elif dmanning < 0.005:
                    self.manning[i, j] = self.manning[i, j] + 0.0001
                elif dmanning < 0.01:
                    self.manning[i, j] = self.manning[i, j] + 0.00002
                else:
                    self.manning[i, j] = self.manning[i, j] + 0.000002
            else:
                # Decrease Manning coefficient back to original
                self.manning[i, j] = self.manning[i, j] - 0.0001
                if self.manning[i, j] < self.manning_ori[i, j]:
                    self.manning[i, j] = self.manning_ori[i, j]

    def finalize_after_flow(self, limitfr: float = 0.9):
        """
        Refresh post-transport material properties and update the Froude limiter.

        This keeps density / rheology outputs synchronized with the transported
        state while avoiding a second friction application after the NR solve.
        """
        self.update_properties()
        self.limit_froude_number(limitfr)

    def step(self, dt: float, limitfr: float = 0.9):
        """
        Perform one time step of rheology calculation.

        Args:
            dt: Time step (s)
            limitfr: Froude number limit (default 0.9)
        """
        # Adjust Manning coefficient based on flow depth
        self.prepare_for_flow()

        # Apply friction
        self.apply_friction(dt)

        # Limit Froude number by adjusting Manning coefficient
        self.limit_froude_number(limitfr)
