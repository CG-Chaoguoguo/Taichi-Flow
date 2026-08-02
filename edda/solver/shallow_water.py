"""
Shallow water equation solver using HLLC Riemann solver.

Solves the 2D shallow water equations with 8-direction flow:
    鈭俬/鈭倀 + 鈭?hu)/鈭倄 + 鈭?hv)/鈭倅 = S_h
    鈭?hu)/鈭倀 + 鈭?hu虏+gh虏/2)/鈭倄 + 鈭?huv)/鈭倅 = S_u
    鈭?hv)/鈭倀 + 鈭?huv)/鈭倄 + 鈭?hv虏+gh虏/2)/鈭倅 = S_v

where:
    h = flow depth
    u, v = velocity components
    g = gravitational acceleration
    S_h, S_u, S_v = source terms
"""
import taichi as ti
import numpy as np
from typing import Tuple
from edda.core.fields import EDDAFields


# Constants
GRAVITY = 9.81  # m/s虏
EPSILON = 1e-10  # Small number to avoid division by zero

# Newton-Raphson alignment constants (matched to original EDDA wfs.F90)
NR_DRY_TOL = 0.03
NR_VELOCITY_LIMIT = 3.5
NR_FHMAX = 1.0

# Define struct for flux values
@ti.dataclass
class Flux:
    h: float
    hu: float
    hv: float



@ti.func
def compute_S_L(h_L: float, u_L: float, h_R: float, u_R: float) -> float:
    """Compute left wave speed."""
    c_L = ti.sqrt(GRAVITY * ti.max(h_L, EPSILON))
    c_R = ti.sqrt(GRAVITY * ti.max(h_R, EPSILON))
    return ti.min(u_L - c_L, u_R - c_R)

@ti.func
def compute_S_R(h_L: float, u_L: float, h_R: float, u_R: float) -> float:
    """Compute right wave speed."""
    c_L = ti.sqrt(GRAVITY * ti.max(h_L, EPSILON))
    c_R = ti.sqrt(GRAVITY * ti.max(h_R, EPSILON))
    return ti.max(u_L + c_L, u_R + c_R)

@ti.func
def compute_S_star(h_L: float, u_L: float, h_R: float, u_R: float, S_L: float, S_R: float) -> float:
    """Compute contact wave speed."""
    numerator = S_R * h_R * (u_R - S_R) - S_L * h_L * (u_L - S_L)
    denominator = h_R * (u_R - S_R) - h_L * (u_L - S_L)

    S_star = 0.5 * (u_L + u_R)
    if ti.abs(denominator) > EPSILON:
        S_star = numerator / denominator

    return S_star


@ti.func
def hllc_flux(
    h_L: float, u_L: float, v_L: float,
    h_R: float, u_R: float, v_R: float,
    direction: int
) -> Flux:
    """
    Compute HLLC flux for shallow water equations.

    Args:
        h_L, u_L, v_L: Left state (depth, x-velocity, y-velocity)
        h_R, u_R, v_R: Right state
        direction: 0 for x-direction, 1 for y-direction

    Returns:
        Flux struct containing F_h, F_hu, F_hv
    """
    # Select velocity component based on direction.
    # Initialize defaults first for Taichi compatibility.
    u_n_L = u_L
    u_n_R = u_R
    u_t_L = v_L
    u_t_R = v_R
    if direction == 1:  # y-direction
        u_n_L = v_L
        u_n_R = v_R
        u_t_L = u_L
        u_t_R = u_R

    # Compute wave speeds
    S_L = compute_S_L(h_L, u_n_L, h_R, u_n_R)
    S_R = compute_S_R(h_L, u_n_L, h_R, u_n_R)
    S_star = compute_S_star(h_L, u_n_L, h_R, u_n_R, S_L, S_R)

    # Left state flux
    F_L_h = h_L * u_n_L
    F_L_hu = h_L * u_n_L * u_n_L + 0.5 * GRAVITY * h_L * h_L
    F_L_hv = h_L * u_n_L * u_t_L

    # Right state flux
    F_R_h = h_R * u_n_R
    F_R_hu = h_R * u_n_R * u_n_R + 0.5 * GRAVITY * h_R * h_R
    F_R_hv = h_R * u_n_R * u_t_R

    # HLLC flux calculation
    F_h = 0.0
    F_hu = 0.0
    F_hv = 0.0

    if S_L >= 0.0:
        # Left state
        F_h = F_L_h
        F_hu = F_L_hu
        F_hv = F_L_hv
    elif S_R <= 0.0:
        # Right state
        F_h = F_R_h
        F_hu = F_R_hu
        F_hv = F_R_hv
    elif S_star >= 0.0:
        # Left star state
        factor = (S_L - u_n_L) / (S_L - S_star)
        h_star = h_L * factor
        F_h = F_L_h + S_L * (h_star - h_L)
        F_hu = F_L_hu + S_L * (h_star * S_star - h_L * u_n_L)
        F_hv = F_L_hv + S_L * (h_star * u_t_L - h_L * u_t_L)
    else:
        # Right star state
        factor = (S_R - u_n_R) / (S_R - S_star)
        h_star = h_R * factor
        F_h = F_R_h + S_R * (h_star - h_R)
        F_hu = F_R_hu + S_R * (h_star * S_star - h_R * u_n_R)
        F_hv = F_R_hv + S_R * (h_star * u_t_R - h_R * u_t_R)

    # Convert back to x-y coordinates
    F_out_h = F_h
    F_out_hu = F_hu
    F_out_hv = F_hv
    if direction == 1:
        # Swap hu and hv for y-direction
        F_out_hu = F_hv
        F_out_hv = F_hu

    return Flux(h=F_out_h, hu=F_out_hu, hv=F_out_hv)


@ti.data_oriented
class ShallowWaterSolver:
    """
    Shallow water equation solver with 8-direction flow.
    Uses HLLC Riemann solver for flux calculation.
    """

    def __init__(self, fields: EDDAFields):
        """
        Initialize shallow water solver.

        Args:
            fields: EDDAFields instance containing simulation variables
        """
        self.fields = fields
        self.nx = fields.nx
        self.ny = fields.ny
        self.dx = fields.dx
        self.dy = fields.dy

        fp = fields.fp

        # Temporary fields for updates
        self.h_new = ti.field(dtype=fp, shape=(self.nx, self.ny))
        self.hu_new = ti.field(dtype=fp, shape=(self.nx, self.ny))
        self.hv_new = ti.field(dtype=fp, shape=(self.nx, self.ny))
        self.hCv_new = ti.field(dtype=fp, shape=(self.nx, self.ny))  # Sediment transport

        # Velocity prediction fields for Newton-Raphson solver (8 directions)
        self.v_pred = ti.field(dtype=fp, shape=(self.nx, self.ny, 8))
        self.v_prev = ti.field(dtype=fp, shape=(self.nx, self.ny, 8))

        # Manning coefficient fields (passed from rheology model)
        self.manning = None  # Will be set by rheology model

    @ti.kernel
    def compute_fluxes_8dir(self):
        """
        Compute fluxes in 8 directions using HLLC solver.
        Directions: E, W, N, S, NE, NW, SE, SW
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] or self.fields.is_boundary[i, j]:
                continue

            h_c = self.fields.h[i, j]
            u_c = self.fields.u[i, j]
            v_c = self.fields.v[i, j]

            # East (0)
            if i < self.nx - 1 and not self.fields.is_nodata[i + 1, j]:
                h_R = self.fields.h[i + 1, j]
                u_R = self.fields.u[i + 1, j]
                v_R = self.fields.v[i + 1, j]
                flux = hllc_flux(h_c, u_c, v_c, h_R, u_R, v_R, 0)
                self.fields.flux_h[i, j, 0] = flux.h
                self.fields.flux_hu[i, j, 0] = flux.hu
                self.fields.flux_hv[i, j, 0] = flux.hv

            # West (1)
            if i > 0 and not self.fields.is_nodata[i - 1, j]:
                h_L = self.fields.h[i - 1, j]
                u_L = self.fields.u[i - 1, j]
                v_L = self.fields.v[i - 1, j]
                flux = hllc_flux(h_L, u_L, v_L, h_c, u_c, v_c, 0)
                self.fields.flux_h[i, j, 1] = -flux.h
                self.fields.flux_hu[i, j, 1] = -flux.hu
                self.fields.flux_hv[i, j, 1] = -flux.hv

            # North (2)
            if j < self.ny - 1 and not self.fields.is_nodata[i, j + 1]:
                h_R = self.fields.h[i, j + 1]
                u_R = self.fields.u[i, j + 1]
                v_R = self.fields.v[i, j + 1]
                flux = hllc_flux(h_c, u_c, v_c, h_R, u_R, v_R, 1)
                self.fields.flux_h[i, j, 2] = flux.h
                self.fields.flux_hu[i, j, 2] = flux.hu
                self.fields.flux_hv[i, j, 2] = flux.hv

            # South (3)
            if j > 0 and not self.fields.is_nodata[i, j - 1]:
                h_L = self.fields.h[i, j - 1]
                u_L = self.fields.u[i, j - 1]
                v_L = self.fields.v[i, j - 1]
                flux = hllc_flux(h_L, u_L, v_L, h_c, u_c, v_c, 1)
                self.fields.flux_h[i, j, 3] = -flux.h
                self.fields.flux_hu[i, j, 3] = -flux.hu
                self.fields.flux_hv[i, j, 3] = -flux.hv

            # Diagonal directions with proper velocity projection
            # Diagonal distance factor: 1/sqrt(2)
            sqrt2 = 1.41421356237
            inv_sqrt2 = 0.70710678118

            # NE (4) - Northeast direction
            if i < self.nx - 1 and j < self.ny - 1 and not self.fields.is_nodata[i + 1, j + 1]:
                h_R = self.fields.h[i + 1, j + 1]
                u_R = self.fields.u[i + 1, j + 1]
                v_R = self.fields.v[i + 1, j + 1]

                # Project velocities onto diagonal (45 degrees)
                # Normal direction: u_n = (u + v) / sqrt(2)
                # Tangent direction: u_t = (v - u) / sqrt(2)
                u_n_L = (u_c + v_c) * inv_sqrt2
                u_t_L = (v_c - u_c) * inv_sqrt2
                u_n_R = (u_R + v_R) * inv_sqrt2
                u_t_R = (v_R - u_R) * inv_sqrt2

                # Compute HLLC flux in rotated frame
                flux = hllc_flux(h_c, u_n_L, u_t_L, h_R, u_n_R, u_t_R, 0)

                # Project flux back to x-y coordinates
                # F_x = (F_n - F_t) / sqrt(2)
                # F_y = (F_n + F_t) / sqrt(2)
                self.fields.flux_h[i, j, 4] = flux.h
                self.fields.flux_hu[i, j, 4] = (flux.hu - flux.hv) * inv_sqrt2
                self.fields.flux_hv[i, j, 4] = (flux.hu + flux.hv) * inv_sqrt2

            # NW (5) - Northwest direction
            if i > 0 and j < self.ny - 1 and not self.fields.is_nodata[i - 1, j + 1]:
                h_R = self.fields.h[i - 1, j + 1]
                u_R = self.fields.u[i - 1, j + 1]
                v_R = self.fields.v[i - 1, j + 1]

                # Project velocities onto diagonal (135 degrees)
                # Normal direction: u_n = (-u + v) / sqrt(2)
                # Tangent direction: u_t = (u + v) / sqrt(2)
                u_n_L = (-u_c + v_c) * inv_sqrt2
                u_t_L = (u_c + v_c) * inv_sqrt2
                u_n_R = (-u_R + v_R) * inv_sqrt2
                u_t_R = (u_R + v_R) * inv_sqrt2

                # Compute HLLC flux in rotated frame
                flux = hllc_flux(h_c, u_n_L, u_t_L, h_R, u_n_R, u_t_R, 0)

                # Project flux back to x-y coordinates
                # F_x = (-F_n - F_t) / sqrt(2)
                # F_y = (F_n - F_t) / sqrt(2)
                self.fields.flux_h[i, j, 5] = flux.h
                self.fields.flux_hu[i, j, 5] = (-flux.hu - flux.hv) * inv_sqrt2
                self.fields.flux_hv[i, j, 5] = (flux.hu - flux.hv) * inv_sqrt2

            # SE (6) - Southeast direction
            if i < self.nx - 1 and j > 0 and not self.fields.is_nodata[i + 1, j - 1]:
                h_R = self.fields.h[i + 1, j - 1]
                u_R = self.fields.u[i + 1, j - 1]
                v_R = self.fields.v[i + 1, j - 1]

                # Project velocities onto diagonal (-45 degrees)
                # Normal direction: u_n = (u - v) / sqrt(2)
                # Tangent direction: u_t = (u + v) / sqrt(2)
                u_n_L = (u_c - v_c) * inv_sqrt2
                u_t_L = (u_c + v_c) * inv_sqrt2
                u_n_R = (u_R - v_R) * inv_sqrt2
                u_t_R = (u_R + v_R) * inv_sqrt2

                # Compute HLLC flux in rotated frame
                flux = hllc_flux(h_c, u_n_L, u_t_L, h_R, u_n_R, u_t_R, 0)

                # Project flux back to x-y coordinates
                # F_x = (F_n + F_t) / sqrt(2)
                # F_y = (-F_n + F_t) / sqrt(2)
                self.fields.flux_h[i, j, 6] = flux.h
                self.fields.flux_hu[i, j, 6] = (flux.hu + flux.hv) * inv_sqrt2
                self.fields.flux_hv[i, j, 6] = (-flux.hu + flux.hv) * inv_sqrt2

            # SW (7) - Southwest direction
            if i > 0 and j > 0 and not self.fields.is_nodata[i - 1, j - 1]:
                h_R = self.fields.h[i - 1, j - 1]
                u_R = self.fields.u[i - 1, j - 1]
                v_R = self.fields.v[i - 1, j - 1]

                # Project velocities onto diagonal (-135 degrees)
                # Normal direction: u_n = (-u - v) / sqrt(2)
                # Tangent direction: u_t = (v - u) / sqrt(2)
                u_n_L = (-u_c - v_c) * inv_sqrt2
                u_t_L = (v_c - u_c) * inv_sqrt2
                u_n_R = (-u_R - v_R) * inv_sqrt2
                u_t_R = (v_R - u_R) * inv_sqrt2

                # Compute HLLC flux in rotated frame
                flux = hllc_flux(h_c, u_n_L, u_t_L, h_R, u_n_R, u_t_R, 0)

                # Project flux back to x-y coordinates
                # F_x = (-F_n + F_t) / sqrt(2)
                # F_y = (-F_n - F_t) / sqrt(2)
                self.fields.flux_h[i, j, 7] = flux.h
                self.fields.flux_hu[i, j, 7] = (-flux.hu + flux.hv) * inv_sqrt2
                self.fields.flux_hv[i, j, 7] = (-flux.hu - flux.hv) * inv_sqrt2

    @ti.kernel
    def update_conservative(self, dt: float):
        """
        Update conservative variables using computed fluxes.

        Args:
            dt: Time step size
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] or self.fields.is_boundary[i, j]:
                continue

            # Sum fluxes by direction
            # x-direction: East (0) and West (1)
            dh_x = self.fields.flux_h[i, j, 0] + self.fields.flux_h[i, j, 1]
            dhu_x = self.fields.flux_hu[i, j, 0] + self.fields.flux_hu[i, j, 1]
            dhv_x = self.fields.flux_hv[i, j, 0] + self.fields.flux_hv[i, j, 1]

            # y-direction: North (2) and South (3)
            dh_y = self.fields.flux_h[i, j, 2] + self.fields.flux_h[i, j, 3]
            dhu_y = self.fields.flux_hu[i, j, 2] + self.fields.flux_hu[i, j, 3]
            dhv_y = self.fields.flux_hv[i, j, 2] + self.fields.flux_hv[i, j, 3]

            # Diagonal directions with proper distance factor
            # Diagonal distance = dx * sqrt(2)
            sqrt2 = 1.41421356237
            dx_diag = self.dx * sqrt2

            dh_diag = 0.0
            dhu_diag = 0.0
            dhv_diag = 0.0
            for d in range(4, 8):
                dh_diag += self.fields.flux_h[i, j, d]
                dhu_diag += self.fields.flux_hu[i, j, d]
                dhv_diag += self.fields.flux_hv[i, j, d]

            # Update with source terms
            h_old = self.fields.h[i, j]
            hu_old = h_old * self.fields.u[i, j]
            hv_old = h_old * self.fields.v[i, j]

            # Bed slope source terms
            S_x = -GRAVITY * h_old * self.fields.slope_x[i, j]
            S_y = -GRAVITY * h_old * self.fields.slope_y[i, j]

            # Conservative update (flux divergence)
            # Main directions use dx/dy, diagonal directions use dx*sqrt(2)
            h_new = h_old - dt * (dh_x / self.dx + dh_y / self.dy + dh_diag / dx_diag)
            hu_new = hu_old - dt * (dhu_x / self.dx + dhu_y / self.dy + dhu_diag / dx_diag) + dt * S_x
            hv_new = hv_old - dt * (dhv_x / self.dx + dhv_y / self.dy + dhv_diag / dx_diag) + dt * S_y

            # Sediment transport (conservative variable h*Cv)
            hCv_old = h_old * self.fields.Cv[i, j]
            dhCv_x = self.fields.flux_hCv[i, j, 0] + self.fields.flux_hCv[i, j, 1]
            dhCv_y = self.fields.flux_hCv[i, j, 2] + self.fields.flux_hCv[i, j, 3]
            dhCv_diag = 0.0
            for d in range(4, 8):
                dhCv_diag += self.fields.flux_hCv[i, j, d]
            hCv_new = hCv_old - dt * (dhCv_x / self.dx + dhCv_y / self.dy + dhCv_diag / dx_diag)

            # Store in temporary fields
            self.h_new[i, j] = ti.max(h_new, 0.0)
            self.hu_new[i, j] = hu_new
            self.hv_new[i, j] = hv_new
            self.hCv_new[i, j] = ti.max(hCv_new, 0.0)

    @ti.kernel
    def apply_updates(self):
        """Apply updates from temporary fields to main fields."""
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            h_new = self.h_new[i, j]
            self.fields.h[i, j] = h_new

            # Update velocities
            if h_new > EPSILON:
                self.fields.u[i, j] = self.hu_new[i, j] / h_new
                self.fields.v[i, j] = self.hv_new[i, j] / h_new
                # Update Cv from advected h*Cv
                self.fields.Cv[i, j] = ti.min(self.hCv_new[i, j] / h_new, 0.65)
            else:
                self.fields.u[i, j] = 0.0
                self.fields.v[i, j] = 0.0
                self.fields.Cv[i, j] = 0.0

        # Apply boundary conditions after update (matching original EDDA line 284-285)
        for i, j in self.fields.h:
            if self.fields.is_boundary[i, j]:
                bc_type = self.fields.boundary_type[i, j]
                if bc_type == 1:  # Outflow boundary
                    self.fields.h[i, j] = 0.0
                    self.fields.u[i, j] = 0.0
                    self.fields.v[i, j] = 0.0
                    self.fields.Cv[i, j] = 0.0
                    # rho will be set to rhow in rheology module

    def step(self, dt: float):
        """
        Advance shallow water equations by one time step.

        Full sequence matching original EDDA:
        1. Compute HLLC fluxes in 8 directions (including sediment transport)
        2. Update conservative variables (h, hu, hv, hCv)
        3. Apply updates and boundary conditions
        4. Newton-Raphson velocity correction (with Manning friction, convective acceleration)

        Args:
            dt: Time step size
        """
        self.compute_fluxes_8dir()
        self.compute_sediment_fluxes()
        self.update_conservative(dt)
        self.apply_updates()  # Boundary conditions are applied inside this method

        # Newton-Raphson velocity correction with Manning friction
        if self.manning is not None:
            self.solve_velocity_newton_raphson(self.manning, dt, 6, 1e-3)
            self.apply_nr_velocities()

    @ti.kernel
    def compute_sediment_fluxes(self):
        """
        Compute sediment transport fluxes in 8 directions.

        Sediment concentration Cv is advected as a conservative variable (h*Cv)
        alongside the flow, matching original EDDA behavior.
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] or self.fields.is_boundary[i, j]:
                continue

            h_c = self.fields.h[i, j]
            Cv_c = self.fields.Cv[i, j]

            # Upwind scheme for sediment transport
            for d in range(8):
                flux_h = self.fields.flux_h[i, j, d]
                # Upwind: use local Cv if flux is outgoing, neighbor Cv if incoming
                if flux_h >= 0.0:
                    self.fields.flux_hCv[i, j, d] = flux_h * Cv_c
                else:
                    # Get neighbor Cv based on direction
                    ni = i
                    nj = j
                    if d == 0:    # East
                        ni = i + 1
                    elif d == 1:  # West
                        ni = i - 1
                    elif d == 2:  # North
                        nj = j + 1
                    elif d == 3:  # South
                        nj = j - 1
                    elif d == 4:  # NE
                        ni = i + 1
                        nj = j + 1
                    elif d == 5:  # NW
                        ni = i - 1
                        nj = j + 1
                    elif d == 6:  # SE
                        ni = i + 1
                        nj = j - 1
                    elif d == 7:  # SW
                        ni = i - 1
                        nj = j - 1

                    if 0 <= ni < self.nx and 0 <= nj < self.ny and not self.fields.is_nodata[ni, nj]:
                        self.fields.flux_hCv[i, j, d] = flux_h * self.fields.Cv[ni, nj]
                    else:
                        self.fields.flux_hCv[i, j, d] = flux_h * Cv_c

    @ti.kernel
    def apply_nr_velocities(self):
        """
        Apply Newton-Raphson corrected velocities back to u, v fields.

        Converts 8-direction velocities from v_pred back to (u, v) components
        using weighted averaging. Main directions contribute weight 1.0,
        diagonal directions contribute weight 1/sqrt(2) to each component.
        """
        inv_sqrt2 = 0.70710678118

        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] or self.fields.is_boundary[i, j]:
                continue

            h = self.fields.h[i, j]
            if h < EPSILON:
                continue

            # Reconstruct u, v from 8-direction velocities with proper weights
            # Main directions: weight 1.0 for their primary component
            # Diagonal directions: weight inv_sqrt2 for each component
            u_sum = 0.0
            v_sum = 0.0
            weight_u = 0.0
            weight_v = 0.0

            # East (0): positive u, weight 1.0
            v_e = self.v_pred[i, j, 0]
            if ti.abs(v_e) <= NR_VELOCITY_LIMIT:
                u_sum += v_e
                weight_u += 1.0

            # West (1): negative u, weight 1.0
            v_w = self.v_pred[i, j, 1]
            if ti.abs(v_w) <= NR_VELOCITY_LIMIT:
                u_sum -= v_w
                weight_u += 1.0

            # North (2): positive v, weight 1.0
            v_n = self.v_pred[i, j, 2]
            if ti.abs(v_n) <= NR_VELOCITY_LIMIT:
                v_sum += v_n
                weight_v += 1.0

            # South (3): negative v, weight 1.0
            v_s = self.v_pred[i, j, 3]
            if ti.abs(v_s) <= NR_VELOCITY_LIMIT:
                v_sum -= v_s
                weight_v += 1.0

            # NE (4): u_ne = (u+v)/sqrt2 鈫?contributes inv_sqrt2 to both u and v
            v_ne = self.v_pred[i, j, 4]
            if ti.abs(v_ne) <= NR_VELOCITY_LIMIT:
                u_sum += v_ne * inv_sqrt2 * inv_sqrt2
                v_sum += v_ne * inv_sqrt2 * inv_sqrt2
                weight_u += inv_sqrt2
                weight_v += inv_sqrt2

            # NW (5): u_nw = (-u+v)/sqrt2 鈫?contributes inv_sqrt2 to both
            v_nw = self.v_pred[i, j, 5]
            if ti.abs(v_nw) <= NR_VELOCITY_LIMIT:
                u_sum -= v_nw * inv_sqrt2 * inv_sqrt2
                v_sum += v_nw * inv_sqrt2 * inv_sqrt2
                weight_u += inv_sqrt2
                weight_v += inv_sqrt2

            # SE (6): u_se = (u-v)/sqrt2 鈫?contributes inv_sqrt2 to both
            v_se = self.v_pred[i, j, 6]
            if ti.abs(v_se) <= NR_VELOCITY_LIMIT:
                u_sum += v_se * inv_sqrt2 * inv_sqrt2
                v_sum -= v_se * inv_sqrt2 * inv_sqrt2
                weight_u += inv_sqrt2
                weight_v += inv_sqrt2

            # SW (7): u_sw = (-u-v)/sqrt2 鈫?contributes inv_sqrt2 to both
            v_sw = self.v_pred[i, j, 7]
            if ti.abs(v_sw) <= NR_VELOCITY_LIMIT:
                u_sum -= v_sw * inv_sqrt2 * inv_sqrt2
                v_sum -= v_sw * inv_sqrt2 * inv_sqrt2
                weight_u += inv_sqrt2
                weight_v += inv_sqrt2

            # Weighted average
            if weight_u > 0.0:
                self.fields.u[i, j] = u_sum / weight_u
            else:
                self.fields.u[i, j] = 0.0
            if weight_v > 0.0:
                self.fields.v[i, j] = v_sum / weight_v
            else:
                self.fields.v[i, j] = 0.0

    @ti.kernel
    def compute_max_wave_speed(self) -> float:
        """
        Compute maximum wave speed for CFL condition.

        Returns:
            Maximum wave speed in the domain
        """
        max_speed = 0.0

        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue

            h = self.fields.h[i, j]
            u = self.fields.u[i, j]
            v = self.fields.v[i, j]

            # Align with original EDDA wet-cell handling and NR velocity gate:
            # ignore near-dry cells and cap extreme velocity spikes for CFL estimate.
            if h > NR_DRY_TOL:
                vel = ti.sqrt(u * u + v * v)
                if vel > NR_VELOCITY_LIMIT:
                    vel = NR_VELOCITY_LIMIT
                c = ti.sqrt(GRAVITY * h)
                speed = vel + c
                if speed > max_speed:
                    max_speed = speed

        return max_speed

    @ti.kernel
    def solve_velocity_newton_raphson(
        self,
        manning: ti.template(),
        dt: ti.f32,
        max_iter: ti.i32,
        tol: ti.f32
    ):
        """
        Solve for velocities using Newton-Raphson iteration with convective acceleration.

        This implements the iterative velocity solver from original EDDA (wfs.F90:345-380).
        The method solves the momentum equation including:
        - Manning friction term
        - Convective acceleration
        - Bed slope
        - Temporal acceleration

        The equation solved is:
        f(v) = v|v|n²/h^(4/3) + (v-v_old)/(g*dt) + convv/(g*dx) + S_i + grad = 0

        where:
        - v: velocity in direction i
        - n: Manning coefficient
        - h: flow depth
        - convv: convective acceleration term
        - S_i: bed slope
        - grad: water surface gradient

        Args:
            manning: Manning coefficient field
            dt: Time step (s)
            max_iter: Maximum number of iterations (default 6)
            tol: Convergence tolerance (default 1e-4)
        """
        eps = 1e-10
        sqrt2 = 1.41421356237
        celsiz = self.dx

        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j] or self.fields.is_boundary[i, j]:
                for d in ti.static(range(8)):
                    self.v_pred[i, j, d] = 0.0
                    self.v_prev[i, j, d] = 0.0
                continue

            h_i = self.fields.h[i, j]
            z_i = self.fields.z_bed[i, j]

            if h_i < eps:
                for d in ti.static(range(8)):
                    self.v_pred[i, j, d] = 0.0
                    self.v_prev[i, j, d] = 0.0
                continue

            # Keep previous directional velocities as opposite-direction reference.
            for d in ti.static(range(8)):
                self.v_pred[i, j, d] = self.v_prev[i, j, d]

            # Solve each direction independently.
            for direction in range(8):
                ni = i
                nj = j
                if direction == 0:      # East
                    ni = i + 1
                elif direction == 1:    # West
                    ni = i - 1
                elif direction == 2:    # North
                    nj = j + 1
                elif direction == 3:    # South
                    nj = j - 1
                elif direction == 4:    # NE
                    ni = i + 1
                    nj = j + 1
                elif direction == 5:    # NW
                    ni = i - 1
                    nj = j + 1
                elif direction == 6:    # SE
                    ni = i + 1
                    nj = j - 1
                else:                   # SW
                    ni = i - 1
                    nj = j - 1

                valid_neighbor = 1
                if ni < 0 or ni >= self.nx or nj < 0 or nj >= self.ny:
                    valid_neighbor = 0
                elif self.fields.is_nodata[ni, nj] == 1:
                    valid_neighbor = 0

                if valid_neighbor == 0:
                    self.v_pred[i, j, direction] = 0.0
                    self.v_prev[i, j, direction] = 0.0
                    continue

                h_n = self.fields.h[ni, nj]
                z_n = self.fields.z_bed[ni, nj]

                hi = h_i + z_i
                hn = h_n + z_n

                ds = celsiz
                if direction >= 4:
                    ds = celsiz * sqrt2

                dz = z_n - z_i
                dh = h_n - h_i

                # Match original EDDA: si = sin(atan(dz/ds)), gd = dh/ds.
                si = dz / ti.sqrt(ds * ds + dz * dz + eps)
                gd = dh / ds

                if ((h_i <= NR_DRY_TOL and hi >= hn) or (h_n <= NR_DRY_TOL and hn >= hi)):
                    self.v_pred[i, j, direction] = 0.0
                    self.v_prev[i, j, direction] = 0.0
                    continue

                ybar = 0.5 * (h_i + h_n)
                if ybar <= NR_DRY_TOL:
                    self.v_pred[i, j, direction] = 0.0
                    self.v_prev[i, j, direction] = 0.0
                    continue

                # Match original EDDA depth-adjusted and pair-averaged Manning.
                manningi = manning[i, j]
                if h_i < NR_FHMAX:
                    manningi = manningi * 1.5 * ti.exp(-0.4 * h_i / NR_FHMAX)

                manningn = manning[ni, nj]
                if h_n < NR_FHMAX:
                    manningn = manningn * 1.5 * ti.exp(-0.4 * h_n / NR_FHMAX)

                manningbar = 0.5 * (ti.abs(manningi) + ti.abs(manningn))
                h_pow = ti.pow(ybar, 4.0 / 3.0)

                driving = si + gd
                v_est = 0.0
                if manningbar > eps and ti.abs(driving) > eps:
                    v_est = ti.sqrt(h_pow / (manningbar * manningbar) * ti.abs(driving))
                    # Fortran SIGN(fvesti, -(si+gd))
                    if driving > 0.0:
                        v_est = -v_est

                v_prev_local = self.v_prev[i, j, direction]

                # Original EDDA skips unstable direction updates when |fvesti|>3.5.
                # Keep previous bounded value to avoid injecting non-physical spikes.
                if ti.abs(v_est) > NR_VELOCITY_LIMIT:
                    v_safe = v_prev_local
                    if ti.abs(v_safe) > NR_VELOCITY_LIMIT:
                        v_safe = 0.0
                    self.v_pred[i, j, direction] = v_safe
                    self.v_prev[i, j, direction] = v_safe
                    continue

                v_old = v_prev_local
                v_current = v_est

                for _ in range(max_iter):
                    opposite_dir = 0
                    if direction == 0:
                        opposite_dir = 1
                    elif direction == 1:
                        opposite_dir = 0
                    elif direction == 2:
                        opposite_dir = 3
                    elif direction == 3:
                        opposite_dir = 2
                    elif direction == 4:
                        opposite_dir = 7
                    elif direction == 5:
                        opposite_dir = 6
                    elif direction == 6:
                        opposite_dir = 5
                    else:
                        opposite_dir = 4

                    v_opposite = self.v_pred[i, j, opposite_dir]
                    convv = (v_current + v_opposite) * v_current
                    localvdiff = 2.0 * v_current + v_opposite

                    celsiz_factor = 1.0
                    if direction >= 4:
                        celsiz_factor = sqrt2

                    ffv = (
                        v_current * ti.abs(v_current) * manningbar * manningbar / h_pow +
                        (v_current - v_old) / (GRAVITY * dt) +
                        convv / (GRAVITY * celsiz * celsiz_factor) +
                        si + gd
                    )

                    # Keep derivative form matched to original EDDA implementation.
                    ffvprime = (
                        ti.abs(v_current) * manningbar * manningbar / h_pow +
                        1.0 / (GRAVITY * dt) +
                        localvdiff / (GRAVITY * celsiz * celsiz_factor)
                    )

                    if ti.abs(ffvprime) < eps:
                        break

                    v_new = v_current - ffv / ffvprime

                    if ti.abs(v_new - v_current) <= tol * ti.abs(v_current):
                        v_current = v_new
                        break

                    v_current = v_new

                if ti.abs(v_current) > NR_VELOCITY_LIMIT:
                    v_current = v_prev_local
                    if ti.abs(v_current) > NR_VELOCITY_LIMIT:
                        v_current = 0.0

                self.v_pred[i, j, direction] = v_current
                self.v_prev[i, j, direction] = v_current

    def get_fortran_velocity_scalar(self) -> np.ndarray:
        """
        Build velocity scalar comparable to original EDDA `fvsave` output.

        Original EDDA writes:
            0.5 * (|fv(i,1)| + |fv(i,2)| + |fv(i,3)| + |fv(i,4)|)
        with direction order [N, NE, E, SE, S, SW, W, NW].

        Internal Taichi order is [E, W, N, S, NE, NW, SE, SW], so:
            N -> 2, NE -> 4, E -> 0, SE -> 6.
        """
        vdir = self.v_pred.to_numpy()
        return 0.5 * (
            np.abs(vdir[:, :, 2]) +
            np.abs(vdir[:, :, 4]) +
            np.abs(vdir[:, :, 0]) +
            np.abs(vdir[:, :, 6])
        )

    def set_manning_field(self, manning_field):
        """
        Set the Manning coefficient field from rheology model.

        Args:
            manning_field: Manning coefficient Taichi field
        """
        self.manning = manning_field

