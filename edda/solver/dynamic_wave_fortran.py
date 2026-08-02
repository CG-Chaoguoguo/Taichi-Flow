"""
Workspace helpers for a research-grade port of the original EDDA dynamic-wave solver.

This module does not yet replace the production flow solver. Its purpose is to
provide a clean, Fortran-aligned staging area for the eventual port of
`wfs.F90` and `dfs.F90`, preserving:

- original 8-direction order: [N, NE, E, SE, S, SW, W, NW]
- explicit neighbor pairing equivalent to `flodir.f90`
- dedicated intermediate arrays for predicted depth, density, face velocity,
  hydraulic width, discharge volume, and mass discharge

Keeping these data structures separate from the current HLLC-based solver makes
it possible to port the original finite-difference / dynamic-wave algorithm
without silently mixing two different numerical schemes.
"""

import taichi as ti

from edda.core.fields import EDDAFields
from edda.solver.fortran_literals import (
    DFS_CVLIMIT_BREAK,
    DFS_CVLIMIT_QUADRATIC_COEFF,
    FORTRAN_DEG2RAD,
    FORTRAN_SQRT2,
)


FORTRAN_DIR_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
FORTRAN_OPPOSITE_DIR = (4, 5, 6, 7, 0, 1, 2, 3)
SQRT2 = FORTRAN_SQRT2


@ti.data_oriented
class FortranDynamicWaveWorkspace:
    """
    Structured-grid workspace mirroring original EDDA dynamic-wave arrays.

    The actual solver port will consume the fields already stored on
    ``EDDAFields``. This wrapper only centralizes direction metadata and common
    reset/copy operations so the forthcoming solver implementation can stay
    close to the Fortran control flow.
    """

    def __init__(self, fields: EDDAFields):
        self.fields = fields
        self.nx = fields.nx
        self.ny = fields.ny

    @staticmethod
    def direction_name(direction: int) -> str:
        return FORTRAN_DIR_NAMES[direction]

    @staticmethod
    def opposite_direction(direction: int) -> int:
        return FORTRAN_OPPOSITE_DIR[direction]

    @ti.kernel
    def reset_step_workspace(self):
        """
        Reset per-step work arrays that correspond to wfs/dfs temporary vectors.
        """
        for i, j in self.fields.tempri:
            self.fields.tempri[i, j] = 0.0
            self.fields.tempinflowh[i, j] = 0.0
            self.fields.tempinflowrho[i, j] = 0.0
            self.fields.fhw[i, j] = 0.0
            self.fields.fhpredi1[i, j] = 0.0
            self.fields.frhopredi1[i, j] = 0.0
            self.fields.tempele[i, j] = 0.0
            self.fields.tempfsh_flow[i, j] = 0.0
            self.fields.tempfsrho_flow[i, j] = 0.0
            self.fields.fhpredi[i, j] = 0.0
            self.fields.frhopredi[i, j] = 0.0
            self.fields.fhpredi2[i, j] = 0.0
            self.fields.frhopredi2[i, j] = 0.0
            self.fields.qtnet_fortran[i, j] = 0.0
            self.fields.qmassnet_fortran[i, j] = 0.0
            self.fields.absubar_temp[i, j] = 0.0
            self.fields.tau_temp[i, j] = 0.0
            self.fields.rhodepo_temp[i, j] = 0.0
            self.fields.temp_erodible_thickness[i, j] = self.fields.erodible_thickness[i, j]
            self.fields.temp_depo_thickness[i, j] = self.fields.depo_thickness[i, j]

        for i, j, d in self.fields.fv_fortran:
            self.fields.fv_pred_fortran[i, j, d] = 0.0
            self.fields.qq_fortran[i, j, d] = 0.0
            self.fields.qqt_fortran[i, j, d] = 0.0
            self.fields.qqmass_fortran[i, j, d] = 0.0
            self.fields.fybar_fortran[i, j, d] = 0.0

    @ti.kernel
    def seed_predictors_from_state(self):
        """
        Copy the current transported state into the Fortran-aligned predictor fields.

        This mirrors the starting point used in both `wfs.F90` and `dfs.F90`
        before source-term-specific updates are applied.
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                continue
            self.fields.tempele[i, j] = self.fields.z_bed[i, j]
            self.fields.fhpredi1[i, j] = self.fields.h[i, j]
            self.fields.frhopredi1[i, j] = self.fields.rho[i, j]
            self.fields.fhpredi[i, j] = self.fields.h[i, j]
            self.fields.frhopredi[i, j] = self.fields.rho[i, j]
            self.fields.fhpredi2[i, j] = self.fields.h[i, j]
            self.fields.frhopredi2[i, j] = self.fields.rho[i, j]

    @ti.kernel
    def compute_bed_slope_limiter(self, rho_water: ti.f64, rho_sediment: ti.f64, cvstar: ti.f64):
        """
        Reproduce the directional slope / cvlimit update from dfs.F90:120-150.

        ``tanslo_fortran`` stores the max value of the original `tanslodir`
        vector over the 8 Fortran directions.  The original dfs.F90 resets
        `tanslodir=0.` for each cell, then only overwrites entries whose
        neighbor exists. Missing-neighbor directions therefore remain explicit
        zero candidates in `maxval(tanslodir)`.  This kernel preserves that
        detail while still allowing a negative max when all 8 directions exist
        and all water-surface gradients are negative.

        Important executable detail:
        In the supplied `dfs.F90`, `slo(i)=atan(tanslo)` is assigned before
        the `tanslo(i)<0.` branch executes `cvlimit(i)=0.; cycle`.  Negative
        dynamic slope therefore remains visible to later erosion / face-flux
        consumers, while `rholimit(i)` keeps its previous value.  Keep that
        behavior here by storing the negative `tanslo_fortran` and only
        updating `rholimit_temp` on the non-negative branch.
        """
        for i, j in self.fields.h:
            if self.fields.is_nodata[i, j]:
                self.fields.tanslo_fortran[i, j] = 0.0
                self.fields.cvlimit_temp[i, j] = cvstar
                continue

            hi = self.fields.h[i, j] + self.fields.z_bed[i, j]
            max_grad = -1.0e20
            has_missing_neighbor = 0

            for d in ti.static(range(8)):
                ni = self.fields.flow_neighbor_i[i, j, d]
                nj = self.fields.flow_neighbor_j[i, j, d]
                if ni >= 0 and nj >= 0:
                    hn = self.fields.h[ni, nj] + self.fields.z_bed[ni, nj]
                    ds = self.fields.dx
                    if d == 1 or d == 3 or d == 5 or d == 7:
                        ds = self.fields.dx * SQRT2

                    grad = (hi - hn) / ds
                    if grad > max_grad:
                        max_grad = grad
                else:
                    has_missing_neighbor = 1

            if has_missing_neighbor == 1 and max_grad < 0.0:
                max_grad = 0.0

            if max_grad < 0.0:
                self.fields.tanslo_fortran[i, j] = max_grad
                self.fields.cvlimit_temp[i, j] = 0.0
                continue

            self.fields.tanslo_fortran[i, j] = max_grad

            phi_rad = self.fields.phi_field[i, j] * FORTRAN_DEG2RAD
            tan_phi = ti.tan(phi_rad)
            tan_slo = max_grad

            denominator = (rho_sediment - rho_water) * (tan_phi - tan_slo)
            cvlimit = cvstar
            if denominator == 0.0:
                cvlimit = cvstar
            else:
                cvlimit = rho_water * tan_slo / denominator
                if cvlimit < DFS_CVLIMIT_BREAK:
                    cvlimit = DFS_CVLIMIT_QUADRATIC_COEFF * cvlimit * cvlimit
                if cvlimit < 0.0 or cvlimit > cvstar:
                    cvlimit = cvstar

            self.fields.cvlimit_temp[i, j] = cvlimit
            self.fields.rholimit_temp[i, j] = cvlimit * (rho_sediment - rho_water) + rho_water

    @ti.kernel
    def compute_bed_slope_limiter_with_carry(
        self,
        carry: ti.template(),
        rho_water: ti.f64,
        rho_sediment: ti.f64,
        cvstar: ti.f64,
    ):
        """
        Experimental literal port of the supplied `dfs.F90` `tanslodir` behavior.

        The source declares `tanslodir(maxdirection)` once and never clears it
        inside the main-cell loop. Missing-neighbor directions therefore keep
        the previous cell's value, and the array also persists across accepted
        steps. This kernel serializes the row-major traversal and reproduces
        that carry-over literally.
        """
        ti.loop_config(serialize=True)
        for linear in range(self.nx * self.ny):
            j = linear // self.nx
            i = linear - j * self.nx

            if self.fields.is_nodata[i, j]:
                self.fields.tanslo_fortran[i, j] = 0.0
                self.fields.cvlimit_temp[i, j] = cvstar
                continue

            hi = self.fields.h[i, j] + self.fields.z_bed[i, j]
            for d in ti.static(range(8)):
                ni = self.fields.flow_neighbor_i[i, j, d]
                nj = self.fields.flow_neighbor_j[i, j, d]
                if ni >= 0 and nj >= 0:
                    hn = self.fields.h[ni, nj] + self.fields.z_bed[ni, nj]
                    ds = self.fields.dx
                    if d == 1 or d == 3 or d == 5 or d == 7:
                        ds = self.fields.dx * SQRT2
                    carry[d] = (hi - hn) / ds

            max_grad = carry[0]
            for d in ti.static(range(1, 8)):
                if carry[d] > max_grad:
                    max_grad = carry[d]

            if max_grad < 0.0:
                self.fields.tanslo_fortran[i, j] = max_grad
                self.fields.cvlimit_temp[i, j] = 0.0
                continue

            self.fields.tanslo_fortran[i, j] = max_grad

            phi_rad = self.fields.phi_field[i, j] * FORTRAN_DEG2RAD
            tan_phi = ti.tan(phi_rad)
            tan_slo = max_grad

            denominator = (rho_sediment - rho_water) * (tan_phi - tan_slo)
            cvlimit = cvstar
            if denominator != 0.0:
                cvlimit = rho_water * tan_slo / denominator
                if cvlimit < DFS_CVLIMIT_BREAK:
                    cvlimit = DFS_CVLIMIT_QUADRATIC_COEFF * cvlimit * cvlimit
                if cvlimit < 0.0 or cvlimit > cvstar:
                    cvlimit = cvstar

            self.fields.cvlimit_temp[i, j] = cvlimit
            self.fields.rholimit_temp[i, j] = cvlimit * (rho_sediment - rho_water) + rho_water
