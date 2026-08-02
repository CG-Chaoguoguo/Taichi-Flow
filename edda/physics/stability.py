"""
Infinite slope stability analysis for EDDA simulation.

This module implements infinite slope stability analysis to calculate
the factor of safety based on pore water pressure and determine
landslide initiation when FS < 1.
"""
import taichi as ti
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edda.core.fields import EDDAFields
    from edda.config.sim_config import SoilParams


@ti.kernel
def compute_factor_of_safety(
    fields: ti.template(),
):
    """
    Compute factor of safety using infinite slope stability analysis with spatial parameters.

    The factor of safety for an infinite slope is:
    FS = (c + (gamma_s * z - u) * tan(phi)) / (gamma_s * z * sin(beta) * cos(beta))

    where:
    - c: cohesion (Pa) - from spatial field
    - phi: internal friction angle (radians) - from spatial field
    - gamma_s: soil unit weight (N/m³) - from spatial field
    - gamma_w: water unit weight (N/m³) - from spatial field
    - z: soil depth (m) - from spatial field
    - u: pore water pressure (Pa)
    - beta: slope angle (radians)

    Args:
        fields: EDDAFields instance containing simulation variables
    """
    PI_OVER_180 = 0.017453292519943295  # High precision π/180

    for i, j in fields.FS:
        # Skip boundary and nodata cells
        if fields.is_boundary[i, j] or fields.is_nodata[i, j]:
            fields.FS[i, j] = 10.0  # High FS for invalid cells
            continue

        # Calculate slope angle from slope components
        slope_x = fields.slope_x[i, j]
        slope_y = fields.slope_y[i, j]
        slope_magnitude = ti.sqrt(slope_x * slope_x + slope_y * slope_y)

        # Convert slope to angle (beta).
        # ti.atan is unavailable in some Taichi versions (e.g., 1.7.x),
        # so use atan2(y, x) for compatibility: atan(s) == atan2(s, 1).
        beta = ti.atan2(slope_magnitude, 1.0)

        # Skip nearly flat areas (slope < 0.01 or ~0.57 degrees)
        if slope_magnitude < 0.01:
            fields.FS[i, j] = 10.0
            continue

        # Read spatial parameters for this cell
        c = fields.c_field[i, j]
        phi_deg = fields.phi_field[i, j]
        phi_rad = phi_deg * PI_OVER_180
        gamma_s = fields.gamma_s_field[i, j]
        gamma_w = fields.gamma_w_field[i, j]
        soil_depth = fields.depth_field[i, j]

        # Get pore water pressure
        u = fields.psi[i, j]

        # Calculate normal stress
        sigma_n = gamma_s * soil_depth * ti.cos(beta) * ti.cos(beta)

        # Calculate effective stress
        sigma_eff = sigma_n - u

        # Calculate resisting force (numerator)
        # Resisting = c + sigma_eff * tan(phi)
        resisting = c + sigma_eff * ti.tan(phi_rad)

        # Calculate driving force (denominator)
        # Driving = gamma_s * z * sin(beta) * cos(beta)
        driving = gamma_s * soil_depth * ti.sin(beta) * ti.cos(beta)

        # Calculate factor of safety
        FS = 10.0  # default for negligible driving force
        if driving > 1e-6:
            FS = resisting / driving

        # Ensure FS is positive and bounded
        if FS < 0.0:
            FS = 0.0
        elif FS > 10.0:
            FS = 10.0

        fields.FS[i, j] = FS


@ti.kernel
def check_failure_and_mobilize(
    fields: ti.template(),
    Cv_failure: ti.f32,
):
    """
    Check for slope failure and mobilize sediment when FS < 1 with spatial parameters.

    When a cell fails (FS < 1), sediment is mobilized into the flow:
    - Set failure flag
    - Increase sediment concentration
    - Lower bed elevation

    Args:
        fields: EDDAFields instance
        Cv_failure: Sediment concentration upon failure (typically 0.5-0.6)
    """
    for i, j in fields.FS:
        # Skip boundary and nodata cells
        if fields.is_boundary[i, j] or fields.is_nodata[i, j]:
            continue

        # Check if already failed
        if fields.is_failed[i, j] == 1:
            continue

        # Check for failure condition
        if fields.FS[i, j] < 1.0:
            # Mark as failed
            fields.is_failed[i, j] = 1

            # Read failure depth from spatial field
            failure_depth = fields.depth_field[i, j]

            # Mobilize sediment into flow
            # If there's existing flow, add to it; otherwise create new flow
            h_current = fields.h[i, j]

            if h_current > 1e-6:
                # Add sediment to existing flow
                # New concentration is weighted average
                Cv_current = fields.Cv[i, j]
                h_new = h_current + failure_depth
                Cv_new = (Cv_current * h_current + Cv_failure * failure_depth) / h_new

                fields.h[i, j] = h_new
                fields.Cv[i, j] = Cv_new
            else:
                # Create new debris flow
                fields.h[i, j] = failure_depth
                fields.Cv[i, j] = Cv_failure
                fields.u[i, j] = 0.0
                fields.v[i, j] = 0.0

            # Lower bed elevation
            fields.z_bed[i, j] -= failure_depth


@ti.kernel
def reset_failure_flags(fields: ti.template()):
    """
    Reset failure flags for new simulation or time step.

    Args:
        fields: EDDAFields instance
    """
    for i, j in fields.is_failed:
        fields.is_failed[i, j] = 0


@ti.kernel
def populate_failure_source_terms(
    fields: ti.template(),
    Cv_failure: ti.f32,
    rho_sediment: ti.f32,
    rho_water: ti.f32,
):
    """
    Stage failure source terms without directly mutating h/Cv/z_bed.

    This is the single-layer analogue of original EDDA's `tempfsh/tempfsrho`
    treatment used by the double-layer landslide routine.
    """
    for i, j in fields.FS:
        if fields.is_boundary[i, j] or fields.is_nodata[i, j]:
            fields.is_failed[i, j] = 0
            fields.tempfsh_flow[i, j] = 0.0
            fields.tempfsrho_flow[i, j] = 0.0
            continue

        if fields.FS[i, j] < 1.0:
            fields.is_failed[i, j] = 1
            fields.tempfsh_flow[i, j] = fields.depth_field[i, j]
            fields.tempfsrho_flow[i, j] = (rho_sediment - rho_water) * Cv_failure + rho_water
        else:
            fields.is_failed[i, j] = 0
            fields.tempfsh_flow[i, j] = 0.0
            fields.tempfsrho_flow[i, j] = 0.0


class StabilityModel:
    """
    Slope stability model manager for infinite slope analysis.
    """

    def __init__(self, fields: 'EDDAFields', params: 'SoilParams'):
        """
        Initialize stability model.

        Args:
            fields: EDDAFields instance
            params: SoilParams configuration
        """
        self.fields = fields
        self.params = params

        # Convert friction angle from degrees to radians
        self.phi_rad = np.deg2rad(params.phi)

    def step(self, check_failure: bool = True, Cv_failure: float = 0.55):
        """
        Perform one time step of stability analysis with spatial parameters.

        Args:
            check_failure: Whether to check for failure and mobilize sediment
            Cv_failure: Sediment concentration upon failure
        """
        # Compute factor of safety using spatial parameters
        compute_factor_of_safety(self.fields)

        # Check for failure and mobilize sediment if requested
        if check_failure:
            check_failure_and_mobilize(
                self.fields,
                Cv_failure,
            )

    def mobilize_failures(self, Cv_failure: float = 0.55):
        """
        Mobilize cells that already satisfy the failure criterion.

        This allows the solver to match original EDDA sequencing more closely:
        compute pore-pressure / FS first, then apply erosion/deposition source terms,
        and only then inject landslide material into the flow state.
        """
        check_failure_and_mobilize(
            self.fields,
            Cv_failure,
        )

    def populate_failure_source_terms(
        self,
        Cv_failure: float = 0.55,
        rho_sediment: float = 2650.0,
        rho_water: float = 1000.0,
    ):
        """Populate landslide source terms without modifying transported state."""
        populate_failure_source_terms(
            self.fields,
            Cv_failure,
            rho_sediment,
            rho_water,
        )

    def reset_failures(self):
        """Reset all failure flags."""
        reset_failure_flags(self.fields)

    def get_failed_cells(self) -> np.ndarray:
        """
        Get array of failed cells.

        Returns:
            2D numpy array of failure flags (0 or 1)
        """
        return self.fields.is_failed.to_numpy()

    def get_factor_of_safety(self) -> np.ndarray:
        """
        Get factor of safety array.

        Returns:
            2D numpy array of factor of safety values
        """
        return self.fields.FS.to_numpy()
