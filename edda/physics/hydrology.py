"""
Green-Ampt infiltration model for EDDA simulation.

This module implements the Green-Ampt infiltration model to calculate
infiltration rate based on rainfall and soil properties, and updates
pore water pressure accordingly.
"""
import taichi as ti
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edda.core.fields import EDDAFields
    from edda.config.sim_config import HydrologyParams


@ti.kernel
def compute_infiltration(
    fields: ti.template(),
    dt: ti.f32,
    g: ti.f32,
):
    """
    Compute infiltration rate using Green-Ampt model with spatial parameters.

    The Green-Ampt model calculates infiltration rate as:
    f = K_sat * (1 + (psi_f * (theta_s - theta_i)) / F)

    where:
    - f: infiltration rate (m/s)
    - K_sat: saturated hydraulic conductivity (m/s) - from spatial field
    - psi_f: wetting front suction head (m) - from spatial field
    - theta_s: saturated water content - from spatial field
    - theta_i: initial water content - from spatial field
    - F: cumulative infiltration depth (m)

    Args:
        fields: EDDAFields instance containing simulation variables
        dt: Time step (s)
        g: Gravitational acceleration (m/s²)
    """
    for i, j in fields.rainfall:
        # Skip boundary and nodata cells
        if fields.is_boundary[i, j] or fields.is_nodata[i, j]:
            continue

        # Get rainfall intensity at this cell
        rain = fields.rainfall[i, j]

        # Also consider ponded water on surface as available for infiltration
        h_surface = fields.h[i, j]

        # If no rainfall and no ponded water, no infiltration
        if rain <= 0.0 and h_surface <= 0.0:
            fields.infiltration[i, j] = 0.0
            continue

        # Get cumulative infiltration
        F = fields.F_cumulative[i, j]

        # Avoid division by zero for initial infiltration
        if F < 1e-6:
            F = 1e-6

        # Read spatial parameters for this cell
        K_sat = fields.K_sat_field[i, j]
        theta_s = fields.theta_s_field[i, j]
        theta_i = fields.theta_i_field[i, j]
        psi_f = fields.psi_f_field[i, j]

        # Calculate potential infiltration rate using Green-Ampt equation
        delta_theta = theta_s - theta_i
        f_potential = K_sat * (1.0 + (psi_f * delta_theta) / F)

        # Available water = rainfall + ponded water / dt
        available_water = rain + h_surface / dt

        # Actual infiltration is minimum of potential and available water
        f_actual = ti.min(f_potential, available_water)

        # Update infiltration rate
        fields.infiltration[i, j] = f_actual

        # Update cumulative infiltration
        fields.F_cumulative[i, j] += f_actual * dt

        # *** CRITICAL FIX: Add excess rainfall to surface water depth ***
        # Excess = rainfall - infiltration (only from rainfall, not ponded water)
        excess = rain - ti.min(f_actual, rain)
        if excess > 0.0:
            fields.h[i, j] += excess * dt


@ti.kernel
def update_pore_pressure(
    fields: ti.template(),
):
    """
    Update pore water pressure based on infiltration with spatial parameters.

    Pore water pressure is calculated based on the degree of saturation
    from cumulative infiltration:

    psi = -gamma_w * (soil_depth - z_wt)

    where z_wt is the water table depth estimated from infiltration.

    Args:
        fields: EDDAFields instance containing simulation variables
    """
    for i, j in fields.psi:
        # Skip boundary and nodata cells
        if fields.is_boundary[i, j] or fields.is_nodata[i, j]:
            continue

        # Get cumulative infiltration
        F = fields.F_cumulative[i, j]

        # Read spatial parameters for this cell
        gamma_w = fields.gamma_w_field[i, j]
        soil_depth = fields.depth_field[i, j]
        theta_s = fields.theta_s_field[i, j]
        theta_i = fields.theta_i_field[i, j]

        # Estimate water table rise based on infiltration
        # Water fills pore space (theta_s - theta_i), so actual wetting front depth
        # is F / (theta_s - theta_i), not F directly
        delta_theta = theta_s - theta_i
        wetting_depth = 0.0
        if delta_theta > 1e-6:
            wetting_depth = F / delta_theta

        # Water table depth = soil depth - wetting front depth
        z_wt = soil_depth - wetting_depth

        # Ensure water table doesn't go below soil depth
        if z_wt < 0.0:
            z_wt = 0.0

        # Calculate pore water pressure (negative for unsaturated, positive for saturated)
        if z_wt > 0.0:
            # Unsaturated: negative pore pressure
            fields.psi[i, j] = -gamma_w * z_wt
        else:
            # Saturated: positive pore pressure
            fields.psi[i, j] = gamma_w * ti.abs(z_wt)


@ti.kernel
def set_rainfall_uniform(fields: ti.template(), rainfall_intensity: ti.f32):
    """
    Set uniform rainfall intensity across the domain.

    Args:
        fields: EDDAFields instance
        rainfall_intensity: Rainfall intensity (m/s)
    """
    for i, j in fields.rainfall:
        if not fields.is_nodata[i, j]:
            fields.rainfall[i, j] = rainfall_intensity


@ti.kernel
def set_rainfall_from_array(fields: ti.template(), rainfall_array: ti.types.ndarray()):
    """
    Set spatially variable rainfall from numpy array.

    Args:
        fields: EDDAFields instance
        rainfall_array: 2D numpy array of rainfall intensities (m/s)
    """
    for i, j in fields.rainfall:
        if not fields.is_nodata[i, j]:
            fields.rainfall[i, j] = rainfall_array[i, j]


class HydrologyModel:
    """
    Hydrology model manager for Green-Ampt infiltration.
    """

    def __init__(self, fields: 'EDDAFields', params: 'HydrologyParams'):
        """
        Initialize hydrology model.

        Args:
            fields: EDDAFields instance
            params: HydrologyParams configuration
        """
        self.fields = fields
        self.params = params
        self.g = 9.81  # Gravitational acceleration (m/s²)

    def step(self, dt: float):
        """
        Perform one time step of hydrology calculation.

        Args:
            dt: Time step (s)
        """
        # Compute infiltration using Green-Ampt model with spatial parameters
        compute_infiltration(
            self.fields,
            dt,
            self.g,
        )

        # Update pore water pressure with spatial parameters
        update_pore_pressure(self.fields)

    def set_uniform_rainfall(self, intensity: float):
        """
        Set uniform rainfall intensity.

        Args:
            intensity: Rainfall intensity (m/s or mm/hr converted to m/s)
        """
        set_rainfall_uniform(self.fields, intensity)

    def set_rainfall_array(self, rainfall_array: np.ndarray):
        """
        Set spatially variable rainfall.

        Args:
            rainfall_array: 2D numpy array of rainfall intensities (m/s)
        """
        set_rainfall_from_array(self.fields, rainfall_array)
