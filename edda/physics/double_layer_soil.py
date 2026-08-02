"""
Double-layer soil model with Richards equation solver.

This module implements the double-layer soil model from the original EDDA,
including:
- 26 sublayers for top and bottom layers
- Richards equation solver using Crank-Nicolson scheme
- Pore pressure and saturation computation
- Minimum factor of safety search
- Failure detection and soil mobilization

Reference: doublelayer.F90, inidoublelayer.F90 from original EDDA
"""
import taichi as ti
import numpy as np
from typing import Tuple
from edda.core.fields import EDDAFields
from edda.config.sim_config import DoubleLayerSoilParams

DEG2RAD = 0.017453292519943295  # pi/180


@ti.data_oriented
class DoubleLayerSoilModel:
    """
    Double-layer soil model with Richards equation solver.

    Implements the original EDDA double-layer model with:
    - Top layer: 26 sublayers with independent hydraulic properties
    - Bottom layer: 26 sublayers with independent hydraulic properties
    - Richards equation for infiltration (reads parameters from spatial fields)
    - Dynamic failure surface determination
    """

    def __init__(self, fields: EDDAFields, params: DoubleLayerSoilParams):
        self.fields = fields
        self.params = params
        self.nx = fields.nx
        self.ny = fields.ny
        self.fp = fields.fp

        # Constants
        # Use effective sublayer counts from config (bounded by allocated field capacity).
        self.NZST = max(1, min(fields.NZST, int(params.nzst)))
        self.NZSB = max(1, min(fields.NZSB, int(params.nzsb)))
        self.g = 9.81
        self.uww = float(params.uww) if float(params.uww) > 0.0 else 9800.0
        self.zmin = params.zmin
        self.finf = 10.0  # Large FS value used inside the FS formula
        self.finf_plus = self.finf + 1.0  # Original doublelayer.F90 sentinel for skipped cells
        self.slomin = float(params.min_slope_angle_deg) * DEG2RAD

        # Baseline sublayer thickness distribution (normalized, from inidoublelayer.F90:22-25)
        nudzt_base = np.array([
            0.01, 0.01, 0.01, 0.015, 0.015, 0.02, 0.03, 0.04,
            0.07, 0.07, 0.07, 0.07, 0.07, 0.07, 0.07, 0.07,
            0.07, 0.07, 0.04, 0.03, 0.02, 0.015, 0.015, 0.01,
            0.01, 0.01
        ], dtype=np.float64 if self.fp == ti.f64 else np.float32)

        nudzb_base = np.array([
            0.01, 0.01, 0.01, 0.015, 0.015, 0.02, 0.03, 0.04,
            0.07, 0.07, 0.07, 0.07, 0.07, 0.07, 0.07, 0.07,
            0.07, 0.07, 0.04, 0.03, 0.02, 0.015, 0.015, 0.01,
            0.01, 0.01
        ], dtype=np.float64 if self.fp == ti.f64 else np.float32)

        nudzt_np = np.zeros(26, dtype=nudzt_base.dtype)
        nudzb_np = np.zeros(26, dtype=nudzb_base.dtype)
        # Match original inidoublelayer.F90 literally: the hard-coded sublayer
        # weights are assigned directly, with no renormalization when nzst/nzsb
        # are smaller than 26.
        nudzt_np[:self.NZST] = nudzt_base[:self.NZST]
        nudzb_np[:self.NZSB] = nudzb_base[:self.NZSB]

        self.nudzt = ti.field(dtype=self.fp, shape=26)
        self.nudzb = ti.field(dtype=self.fp, shape=26)
        self.nudzt.from_numpy(nudzt_np)
        self.nudzb.from_numpy(nudzb_np)

        # Temporary arrays for Richards equation solver
        self.kkt1 = ti.field(dtype=self.fp, shape=(self.nx, self.ny, self.NZST + 1))
        self.kkt2 = ti.field(dtype=self.fp, shape=(self.nx, self.ny, self.NZST + 1))
        self.kkb1 = ti.field(dtype=self.fp, shape=(self.nx, self.ny, self.NZSB + 1))
        self.kkb2 = ti.field(dtype=self.fp, shape=(self.nx, self.ny, self.NZSB + 1))
        self.richards_stability_violation = ti.field(dtype=ti.i32, shape=())

    # ----------------------------------------------------------------
    # Initialization (inidoublelayer.F90)
    # ----------------------------------------------------------------
    def build_initial_rikzero_field(self, rizero_rate: float | np.ndarray) -> np.ndarray:
        """
        Build the normalized steady infiltration field `rikzero`.

        Reference: steady.f90. The initialization path uses:
        - `rikzero = rizero / kst`
        - if `rikzero >= cos(slope)^2`, clamp to `cos(slope)`
        """
        kst = self.fields.K_sat_top_field.to_numpy().astype(np.float64, copy=False)
        slope_angle = self.fields.slope_angle.to_numpy().astype(np.float64, copy=False)
        nodata = self.fields.is_nodata.to_numpy().astype(bool, copy=False)

        rikzero = np.zeros((self.nx, self.ny), dtype=np.float64)
        rizero_grid = None if np.isscalar(rizero_rate) else np.asarray(rizero_rate, dtype=np.float64)
        if rizero_grid is not None and rizero_grid.shape != (self.nx, self.ny):
            raise ValueError(
                f"Initial rizero grid shape {rizero_grid.shape} does not match solver field shape {(self.nx, self.ny)}."
            )
        valid = ~nodata

        zero_kst = valid & (kst == 0.0)
        rikzero[zero_kst] = 1.0

        nonzero_kst = valid & (kst != 0.0)
        if rizero_grid is None:
            rikzero[nonzero_kst] = float(rizero_rate) / kst[nonzero_kst]
        else:
            rikzero[nonzero_kst] = rizero_grid[nonzero_kst] / kst[nonzero_kst]

        slope = slope_angle[valid]
        cos_slope = np.cos(slope)
        limit = cos_slope * cos_slope
        rik_valid = rikzero[valid]
        rik_valid = np.where(rik_valid >= limit, cos_slope, rik_valid)
        rikzero[valid] = rik_valid

        dtype = np.float64 if self.fp == ti.f64 else np.float32
        return rikzero.astype(dtype, copy=False)

    def initialize_double_layer(self, rikzero: np.ndarray):
        """
        Initialize double-layer soil model.
        All parameters are read from spatial fields (supports zone system).
        Reference: inidoublelayer.F90:22-88
        """
        self._initialize_double_layer_kernel(rikzero)

    @ti.kernel
    def _initialize_double_layer_kernel(self, rikzero: ti.types.ndarray()):
        """Initialize double-layer model 鈥?reads all params from spatial fields."""
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                continue
            if self.fields.slope_angle[i, j] < self.slomin:
                continue

            # Read parameters from spatial fields (zone-aware)
            kst = self.fields.K_sat_top_field[i, j]
            alphat = self.fields.alpha_top_field[i, j]
            thsatt = self.fields.theta_sat_top_field[i, j]
            thresit = self.fields.theta_res_top_field[i, j]
            ksb = self.fields.K_sat_bottom_field[i, j]
            alphab = self.fields.alpha_bottom_field[i, j]
            thsatb = self.fields.theta_sat_bottom_field[i, j]
            thresib = self.fields.theta_res_bottom_field[i, j]
            ltstar = self.fields.ltstar_field[i, j]
            lbstar = self.fields.lbstar_field[i, j]

            # Store layer thicknesses
            self.fields.ltstar[i, j] = ltstar
            self.fields.lbstar[i, j] = lbstar

            slope = self.fields.slope_angle[i, j]
            cos_slope = ti.cos(slope)
            cos_slope_sq = cos_slope * cos_slope

            # Steady infiltration rate
            qat = rikzero[i, j]
            qab = qat * kst / ksb

            # Beta parameter (inidoublelayer.F90:37-39)
            beta_val = (alphab * ksb * (thsatt - thresit)) / (alphat * kst * (thsatb - thresib))
            self.fields.beta[i, j] = beta_val

            lt = alphat * ltstar * cos_slope_sq
            lb = alphab * lbstar * cos_slope_sq

            u0 = 0.0  # Initial condition at water table

            # Initialize top layer sublayers (inidoublelayer.F90:46-58)
            zz = 0.0
            for k in range(self.NZST + 1):
                if k < self.NZST:
                    self.fields.deltazt[i, j, k] = self.nudzt[k] * ltstar
                    self.fields.deltadzt[i, j, k] = alphat * self.fields.deltazt[i, j, k] * cos_slope_sq
                if k > 0:
                    zz += self.fields.deltazt[i, j, k - 1]
                self.fields.zt[i, j, k] = ltstar - zz

                dzt = alphat * self.fields.zt[i, j, k] * cos_slope_sq

                # FIX 2a: Correct kkt0 formula (original EDDA inidoublelayer.F90:54)
                # kkt0 = qat - (qat - (qab-(qab-exp(alphab*u0))*exp(-lb))^(alphat/alphab)) * exp(-dzt)
                exp_alphab_u0 = ti.exp(alphab * u0)
                term_bottom = qab - (qab - exp_alphab_u0) * ti.exp(-lb)
                term_power = ti.pow(term_bottom, alphat / alphab)
                term_top = qat - (qat - term_power) * ti.exp(-dzt)

                if term_top > 1e-10:
                    self.fields.kkt[i, j, k] = term_top
                else:
                    self.fields.kkt[i, j, k] = 1e-10

                self.kkt1[i, j, k] = self.fields.kkt[i, j, k]
                self.kkt2[i, j, k] = self.fields.kkt[i, j, k]

                # Pore pressure (inidoublelayer.F90:55)
                self.fields.pt[i, j, k] = (1.0 / alphat) * ti.log(self.fields.kkt[i, j, k])

                # Water content and saturation (inidoublelayer.F90:56-57)
                self.fields.thzt[i, j, k] = thresit + (thsatt - thresit) * ti.exp(alphat * self.fields.pt[i, j, k])
                self.fields.desatt[i, j, k] = self.fields.thzt[i, j, k] / thsatt
                # FIX 2d: Store initial saturation per sublayer (3D)
                self.fields.inidesatt[i, j, k] = self.fields.desatt[i, j, k]

            # Initialize bottom layer sublayers (inidoublelayer.F90:60-70)
            zz = 0.0
            for k in range(self.NZSB + 1):
                if k < self.NZSB:
                    self.fields.deltazb[i, j, k] = self.nudzb[k] * lbstar
                    self.fields.deltadzb[i, j, k] = alphab * self.fields.deltazb[i, j, k] * cos_slope_sq
                if k > 0:
                    zz += self.fields.deltazb[i, j, k - 1]
                self.fields.zb[i, j, k] = -zz

                dzb = alphab * self.fields.zb[i, j, k] * cos_slope_sq

                exp_alphab_u0 = ti.exp(alphab * u0)
                term_bottom_b = qab - (qab - exp_alphab_u0) * ti.exp(-(lb + dzb))

                if term_bottom_b > 1e-10:
                    self.fields.kkb[i, j, k] = term_bottom_b
                else:
                    self.fields.kkb[i, j, k] = 1e-10

                self.kkb1[i, j, k] = self.fields.kkb[i, j, k]
                self.kkb2[i, j, k] = self.fields.kkb[i, j, k]

                self.fields.pb[i, j, k] = (1.0 / alphab) * ti.log(self.fields.kkb[i, j, k])

                # Bottom layer saturation
                self.fields.thzb[i, j, k] = thresib + (thsatb - thresib) * ti.exp(alphab * self.fields.pb[i, j, k])
                self.fields.desatb[i, j, k] = self.fields.thzb[i, j, k] / thsatb
                self.fields.inidesatb[i, j, k] = self.fields.desatb[i, j, k]

    # ----------------------------------------------------------------
    # Richards equation solver (doublelayer.F90)
    # ----------------------------------------------------------------
    def solve_richards_equation(self, dt: float, infiltration_rate: np.ndarray):
        """
        Solve Richards equation using the original EDDA fixed `nt=5` substeps.
        Reference: doublelayer.F90:82-108
        """
        nt = 5
        dtn = dt / nt
        self.richards_stability_violation[None] = 0
        self._solve_richards_kernel(dtn, nt, infiltration_rate)
        if self.richards_stability_violation[None] != 0:
            raise RuntimeError(
                "doublelayer.F90 stability condition violated: dtp exceeds the "
                "first-sublayer limit with the original fixed nt=5 scheme"
            )

    def restore_richards_committed_state(self):
        """
        Restore the committed Richards state after a rejected DFS candidate step.

        Original `dfs.F90` retries a rejected step from the previously accepted
        `kkt/kkb` state because only `kkt2/kkb2` are candidate arrays inside the
        step. The Taichi port stages those committed values in `kkt1/kkb1` at the
        start of every Richards solve, so we can roll back to the same state
        without a host-side checkpoint.
        """
        self._restore_richards_committed_state_kernel()

    @ti.kernel
    def _restore_richards_committed_state_kernel(self):
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                continue
            for k in range(self.NZST + 1):
                self.fields.kkt[i, j, k] = self.kkt1[i, j, k]
            for k in range(self.NZSB + 1):
                self.fields.kkb[i, j, k] = self.kkb1[i, j, k]

    @ti.kernel
    def _solve_richards_kernel(
        self,
        dtn: ti.f64, nt: ti.i32, fave: ti.types.ndarray()
    ):
        """Solve Richards equation 鈥?reads all params from spatial fields."""
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                continue
            if self.fields.slope_angle[i, j] < self.slomin:
                continue
            if self.fields.is_failed[i, j] == 1:
                continue

            # Read parameters from spatial fields
            kst = self.fields.K_sat_top_field[i, j]
            alphat = self.fields.alpha_top_field[i, j]
            thsatt = self.fields.theta_sat_top_field[i, j]
            thresit = self.fields.theta_res_top_field[i, j]
            ksb = self.fields.K_sat_bottom_field[i, j]
            alphab = self.fields.alpha_bottom_field[i, j]
            thsatb = self.fields.theta_sat_bottom_field[i, j]
            thresib = self.fields.theta_res_bottom_field[i, j]

            slope = self.fields.slope_angle[i, j]
            cos_slope = ti.cos(slope)
            cos_slope_sq = cos_slope * cos_slope

            # doublelayer.F90 uses the actual infiltration rate `fave` (m/s)
            # for the transient Richards solve.
            qbt = 0.0
            qbb = 0.0
            if ti.abs(kst) > 1.0e-20:
                qbt = fave[i, j] / kst
            if ti.abs(ksb) > 1.0e-20:
                qbb = fave[i, j] / ksb

            # Time parameter (doublelayer.F90:63)
            dtp = alphab * ksb * dtn / (thsatb - thresib) * cos_slope_sq
            beta_val = self.fields.beta[i, j]
            if dtp > self.fields.deltadzt[i, j, 0] * self.fields.deltadzt[i, j, 0] / 2.0 or dtp > self.fields.deltadzb[i, j, 0] * self.fields.deltadzb[i, j, 0] / 2.0:
                self.richards_stability_violation[None] = 1

            # Copy current state to temporary arrays (once, before sub-stepping)
            for k in range(self.NZST + 1):
                self.kkt1[i, j, k] = self.fields.kkt[i, j, k]
            for k in range(self.NZSB + 1):
                self.kkb1[i, j, k] = self.fields.kkb[i, j, k]

            # Sub-timestep loop (doublelayer.F90:80-108)
            for m in range(nt):
                # Bottom layer - Crank-Nicolson scheme (doublelayer.F90:83-87)
                for k in range(1, self.NZSB):
                    dzb_j = self.fields.deltadzb[i, j, k]
                    dzb_jm1 = self.fields.deltadzb[i, j, k - 1]
                    term1 = dtp / (dzb_j + dzb_jm1) * (self.kkb1[i, j, k + 1] - self.kkb1[i, j, k - 1])
                    term2 = dtp / (dzb_jm1 * dzb_j * dzb_j) * (
                        dzb_jm1 * self.kkb1[i, j, k + 1] -
                        (dzb_j + dzb_jm1) * self.kkb1[i, j, k] +
                        dzb_j * self.kkb1[i, j, k - 1]
                    )
                    new_val = self.kkb1[i, j, k] + term1 + term2
                    if new_val > 1e-10:
                        self.kkb2[i, j, k] = new_val
                    else:
                        self.kkb2[i, j, k] = 1e-10

                # Top layer - Crank-Nicolson scheme with beta (doublelayer.F90:90-94)
                for k in range(1, self.NZST):
                    dzt_j = self.fields.deltadzt[i, j, k]
                    dzt_jm1 = self.fields.deltadzt[i, j, k - 1]
                    term1 = dtp / beta_val / (dzt_j + dzt_jm1) * (self.kkt1[i, j, k + 1] - self.kkt1[i, j, k - 1])
                    term2 = dtp / beta_val / (dzt_jm1 * dzt_j * dzt_j) * (
                        dzt_jm1 * self.kkt1[i, j, k + 1] -
                        (dzt_j + dzt_jm1) * self.kkt1[i, j, k] +
                        dzt_j * self.kkt1[i, j, k - 1]
                    )
                    new_val = self.kkt1[i, j, k] + term1 + term2
                    if new_val > 1e-10:
                        self.kkt2[i, j, k] = new_val
                    else:
                        self.kkt2[i, j, k] = 1e-10

                # FIX 2c: Surface BC uses current rainfall intensity
                dzt_1 = self.fields.deltadzt[i, j, 0]
                self.kkt2[i, j, 0] = (qbt * dzt_1 + self.kkt2[i, j, 1]) / (dzt_1 + 1.0)

                # Interface boundary condition (doublelayer.F90:102)
                dzt_nzst = self.fields.deltadzt[i, j, self.NZST - 1]
                dzb_1 = self.fields.deltadzb[i, j, 0]
                numerator = (ksb / dzb_1 * self.kkb2[i, j, 1] +
                            kst / dzt_nzst * self.kkt2[i, j, self.NZST - 1])
                denominator = (ksb / dzb_1 * (1.0 + dzb_1) +
                              kst / dzt_nzst * (1.0 - dzt_nzst))
                self.kkt2[i, j, self.NZST] = numerator / denominator
                self.kkb2[i, j, 0] = self.kkt2[i, j, self.NZST]
                # Match original doublelayer.F90 literally: the commented
                # assignments `kkt1=kkt2` and `kkb1=kkb2` remain disabled, so
                # each Richards sub-step reuses the same staged state.
            # Copy final result back to fields
            for k in range(self.NZST + 1):
                self.fields.kkt[i, j, k] = self.kkt2[i, j, k]
            for k in range(self.NZSB + 1):
                self.fields.kkb[i, j, k] = self.kkb2[i, j, k]

    # ----------------------------------------------------------------
    # Pore pressure computation (doublelayer.F90:118-120)
    # ----------------------------------------------------------------
    def compute_pore_pressure(self):
        """Compute pore pressure from hydraulic conductivity. Reads from spatial fields."""
        self._compute_pore_pressure_kernel()

    @ti.kernel
    def _compute_pore_pressure_kernel(self):
        """Compute pore pressure 鈥?reads all params from spatial fields."""
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                continue

            alphat = self.fields.alpha_top_field[i, j]
            thsatt = self.fields.theta_sat_top_field[i, j]
            thresit = self.fields.theta_res_top_field[i, j]
            alphab = self.fields.alpha_bottom_field[i, j]
            thsatb = self.fields.theta_sat_bottom_field[i, j]
            thresib = self.fields.theta_res_bottom_field[i, j]

            # Top layer
            for k in range(self.NZST + 1):
                self.fields.pt[i, j, k] = (1.0 / alphat) * ti.log(self.fields.kkt[i, j, k])
                self.fields.thzt[i, j, k] = thresit + (thsatt - thresit) * ti.exp(alphat * self.fields.pt[i, j, k])
                desat_val = self.fields.thzt[i, j, k] / thsatt
                if desat_val > 1.0:
                    self.fields.desatt[i, j, k] = 1.0
                elif desat_val < 0.0:
                    self.fields.desatt[i, j, k] = 0.0
                else:
                    self.fields.desatt[i, j, k] = desat_val

            # Bottom layer
            for k in range(self.NZSB + 1):
                self.fields.pb[i, j, k] = (1.0 / alphab) * ti.log(self.fields.kkb[i, j, k])
                self.fields.thzb[i, j, k] = thresib + (thsatb - thresib) * ti.exp(alphab * self.fields.pb[i, j, k])
                desat_val = self.fields.thzb[i, j, k] / thsatb
                if desat_val > 1.0:
                    self.fields.desatb[i, j, k] = 1.0
                elif desat_val < 0.0:
                    self.fields.desatb[i, j, k] = 0.0
                else:
                    self.fields.desatb[i, j, k] = desat_val

    # ----------------------------------------------------------------
    # Minimum factor of safety search (doublelayer.F90:116-167)
    # ----------------------------------------------------------------
    def find_minimum_fs(self):
        """Search all sublayers for minimum FS. Reads from spatial fields."""
        self._find_minimum_fs_kernel()

    @ti.kernel
    def _find_minimum_fs_kernel(self):
        """Find minimum factor of safety 鈥?reads all params from spatial fields."""
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                continue
            if self.fields.is_failed[i, j] == 1:
                continue
            if self.fields.slope_angle[i, j] < self.slomin:
                self.fields.zfmin[i, j] = self.fields.ltstar[i, j]
                self.fields.pmin[i, j] = 0.0
                self.fields.fdepth[i, j] = 0.0
                self.fields.FS[i, j] = self.finf_plus
                continue

            # FIX 3b: Read from spatial fields
            phit = self.fields.phi_field[i, j] * DEG2RAD
            phibt = self.fields.phib_field[i, j] * DEG2RAD
            ct = self.fields.c_field[i, j]
            if ct > 1.0e6:
                self.fields.zfmin[i, j] = self.fields.ltstar[i, j]
                self.fields.pmin[i, j] = 0.0
                self.fields.fdepth[i, j] = 0.0
                self.fields.FS[i, j] = self.finf_plus
                continue
            uwst = self.fields.gamma_s_field[i, j]
            alphat = self.fields.alpha_top_field[i, j]
            thsatt = self.fields.theta_sat_top_field[i, j]

            slope = self.fields.slope_angle[i, j]
            sin_slope = ti.sin(slope)
            cos_slope = ti.cos(slope)

            fft = ti.tan(phit) / ti.tan(slope)
            ltstar = self.fields.ltstar[i, j]

            fs_min = self.finf
            zfmin_val = ltstar
            pmin_val = 0.0
            fdepth_val = 0.0
            uwsum = 0.0
            has_desat_change = 0

            for k in range(self.NZST + 1):
                pt_val = self.fields.pt[i, j, k]
                desatt_val = self.fields.desatt[i, j, k]
                # FIX 2d: Read per-sublayer initial saturation
                inidesatt_val = self.fields.inidesatt[i, j, k]
                thzt_val = self.fields.thzt[i, j, k]
                zt_val = self.fields.zt[i, j, k]

                # Unit weight (doublelayer.F90:123-129)
                uwt1 = 0.0
                if pt_val < -1.0 / alphat:
                    uwt1 = (uwst / self.uww - thsatt + thzt_val) * self.uww
                else:
                    uwt1 = uwst

                uwsum += uwt1
                uwspt = uwsum / float(k + 1)

                depth = ltstar - zt_val

                # Cohesion component
                fsc = 0.0
                if depth > self.zmin:
                    fsc = ct / uwspt / depth / sin_slope / cos_slope
                else:
                    fsc = ct / uwspt / (depth + self.zmin) / sin_slope / cos_slope

                # Factor of safety
                fs = self.finf
                if depth > self.zmin:
                    fsw = 0.0
                    if pt_val < 0.0:
                        fsw = -pt_val * self.uww * ti.tan(phibt) / uwspt / depth / sin_slope / cos_slope
                    else:
                        fsw = -pt_val * self.uww * ti.tan(phit) / uwspt / depth / sin_slope / cos_slope
                    fs = fft + fsc + fsw

                if fs < fsc:
                    fs = fsc
                if fs > self.finf:
                    fs = self.finf
                if depth <= self.zmin:
                    fs = self.finf

                # Check saturation change > 5%
                if inidesatt_val > 1e-10:
                    if ti.abs((inidesatt_val - desatt_val) / inidesatt_val) > 0.05:
                        has_desat_change = 1
                        zfmin_val = zt_val
                        pmin_val = pt_val
                        fdepth_val = depth
                        if fs < fs_min:
                            fs_min = fs

            # Store results
            if has_desat_change == 0 or fdepth_val == 0.0:
                self.fields.zfmin[i, j] = ltstar
                self.fields.pmin[i, j] = self.fields.pt[i, j, 0]
                self.fields.fdepth[i, j] = 0.0
                self.fields.FS[i, j] = self.finf
            else:
                self.fields.zfmin[i, j] = zfmin_val
                self.fields.pmin[i, j] = pmin_val
                self.fields.fdepth[i, j] = fdepth_val
                self.fields.FS[i, j] = fs_min

    # ----------------------------------------------------------------
    # Failure and mobilization (doublelayer.F90:178-182)
    # ----------------------------------------------------------------
    def check_failure_and_mobilize(self, cvstar: float = 0.65):
        """Check for failure (FS < 1) and mobilize soil into flow."""
        rhos = 2650.0
        rhow = 1000.0
        self._check_failure_and_mobilize_kernel(cvstar, rhos, rhow)

    def populate_failure_source_terms(
        self,
        cvstar: float = 0.65,
        rho_sediment: float = 2650.0,
        rho_water: float = 1000.0,
    ):
        """
        Populate `tempfsh_flow/tempfsrho_flow` without mutating the transported state.

        This mirrors original `doublelayer.F90`, where the landslide contribution
        is staged into temporary source arrays and only coupled into flow after
        erosion/deposition have been evaluated.
        """
        self._populate_failure_source_terms_kernel(cvstar, rho_sediment, rho_water)

    @ti.kernel
    def _check_failure_and_mobilize_kernel(self, cvstar: ti.f64, rhos: ti.f64, rhow: ti.f64):
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                continue
            if self.fields.FS[i, j] < 1.0:
                self.fields.is_failed[i, j] = 1
                fdepth = self.fields.fdepth[i, j]

                # Mixture density of mobilized soil
                tempfsrho = (rhos - rhow) * cvstar + rhow

                # Mass conservation
                old_h = self.fields.h[i, j]
                old_mass = old_h * self.fields.Cv[i, j] * self.fields.rho[i, j]
                new_sediment_mass = fdepth * cvstar * tempfsrho
                total_mass = old_mass + new_sediment_mass
                new_h = old_h + fdepth

                self.fields.h[i, j] = new_h

                if new_h > 1e-6:
                    self.fields.Cv[i, j] = total_mass / (new_h * tempfsrho)
                    if self.fields.Cv[i, j] > cvstar:
                        self.fields.Cv[i, j] = cvstar
                    if self.fields.Cv[i, j] < 0.0:
                        self.fields.Cv[i, j] = 0.0

                self.fields.z_bed[i, j] -= fdepth
                self.fields.rho[i, j] = (rhos - rhow) * self.fields.Cv[i, j] + rhow

    @ti.kernel
    def _populate_failure_source_terms_kernel(
        self,
        cvstar: ti.f64,
        rhos: ti.f64,
        rhow: ti.f64,
    ):
        for i, j in ti.ndrange(self.nx, self.ny):
            if self.fields.is_nodata[i, j] == 1:
                self.fields.tempfsh_flow[i, j] = 0.0
                self.fields.tempfsrho_flow[i, j] = 0.0
                continue

            if self.fields.is_failed[i, j] == 1:
                self.fields.tempfsh_flow[i, j] = 0.0
                self.fields.tempfsrho_flow[i, j] = 0.0
                continue

            if self.fields.FS[i, j] < 1.0:
                self.fields.is_failed[i, j] = 1
                self.fields.tempfsh_flow[i, j] = self.fields.fdepth[i, j]
                self.fields.tempfsrho_flow[i, j] = (rhos - rhow) * cvstar + rhow
            else:
                self.fields.tempfsh_flow[i, j] = 0.0
                self.fields.tempfsrho_flow[i, j] = 0.0

    # ----------------------------------------------------------------
    # Main update cycle
    # ----------------------------------------------------------------
    def update(self, dt: float, rainfall_intensity: np.ndarray, cvstar: float = 0.65):
        """Complete update cycle for double-layer soil model."""
        self.solve_richards_equation(dt, rainfall_intensity)
        self.compute_pore_pressure()
        self.find_minimum_fs()
        self.check_failure_and_mobilize(cvstar)

