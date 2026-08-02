from __future__ import annotations

import math

import numpy as np

from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver
from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
from edda.solver.fortran_literals import DFS_EROSION_DEPTH_TRIGGER
from tests.test_dfs_dynamic_wave import _build_config, _build_fields


def build_two_cell_erosion_solver(
    *,
    dynamic_slope_rad: float = 0.4,
    input_slope_rad: float = 0.01,
    ctao: float = 1.0,
    cv: float = 0.10,
    rholimit: float = 5000.0,
    erodible_thickness: float = 10.0,
    face_velocity: float = 100.0,
) -> DFSDynamicWaveSolver:
    cfg = _build_config()
    fields = _build_fields()
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))
    shape = (fields.nx, fields.ny)
    rho_water = cfg.rheology.rho_water
    rho_sediment = cfg.rheology.rho_sediment

    fields.h.from_numpy(np.full(shape, 0.4, dtype=np.float64))
    fields.fhpredi1.from_numpy(np.full(shape, 0.5, dtype=np.float64))
    fields.frhopredi1.from_numpy(
        np.full(shape, rho_water + cv * (rho_sediment - rho_water), dtype=np.float64)
    )
    fields.fv_fortran.from_numpy(np.full((shape[0], shape[1], 8), face_velocity, dtype=np.float64))
    fields.phi_field.from_numpy(np.full(shape, 24.0, dtype=np.float64))
    fields.slope_angle.from_numpy(np.full(shape, input_slope_rad, dtype=np.float64))
    fields.tanslo_fortran.from_numpy(np.full(shape, math.tan(dynamic_slope_rad), dtype=np.float64))
    fields.ctao_field.from_numpy(np.full(shape, ctao, dtype=np.float64))
    fields.c_field.from_numpy(np.full(shape, 1.0e7, dtype=np.float64))
    fields.cvlimit_temp.from_numpy(np.full(shape, cfg.rheology.Cv_max, dtype=np.float64))
    fields.rholimit_temp.from_numpy(np.full(shape, rholimit, dtype=np.float64))
    fields.erodible_thickness.from_numpy(np.full(shape, erodible_thickness, dtype=np.float64))
    fields.n_manning_field.from_numpy(np.full(shape, 0.05, dtype=np.float64))
    return solver


def test_taoc_uses_dynamic_fortran_slope_not_static_input_slope():
    solver = build_two_cell_erosion_solver(dynamic_slope_rad=0.4, input_slope_rad=0.01)
    fields = solver.fields
    cfg = solver.config

    solver._compute_source_rates(1.0, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)

    expected = (
        1.0
        + (1.0 - cfg.rheology.cs)
        * 0.10
        * (cfg.rheology.rho_sediment - cfg.rheology.rho_water)
        * solver.g
        * 0.4
        * math.cos(0.4) ** 2
        * math.tan(math.radians(24.0))
    )
    static_slope_result = (
        1.0
        + (1.0 - cfg.rheology.cs)
        * 0.10
        * (cfg.rheology.rho_sediment - cfg.rheology.rho_water)
        * solver.g
        * 0.4
        * math.cos(0.01) ** 2
        * math.tan(math.radians(24.0))
    )

    taoc = fields.taoc_temp.to_numpy()
    np.testing.assert_allclose(taoc, np.full((2, 1), expected), rtol=1.0e-5, atol=1.0e-5)
    assert not np.isclose(float(taoc[0, 0]), static_slope_result)


def test_erorate_respects_fortran_depth_trigger_literal():
    solver = build_two_cell_erosion_solver(dynamic_slope_rad=0.4, face_velocity=100.0)
    fields = solver.fields
    cfg = solver.config
    shape = (fields.nx, fields.ny)

    below_fortran_trigger = 0.039108871547125799
    assert below_fortran_trigger > 0.01
    assert below_fortran_trigger < DFS_EROSION_DEPTH_TRIGGER
    fields.fhpredi1.from_numpy(np.full(shape, below_fortran_trigger, dtype=np.float64))

    solver._compute_source_rates(1.0, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)

    np.testing.assert_allclose(fields.erorate_raw_temp.to_numpy(), np.zeros(shape), atol=0.0)
    assert np.count_nonzero(fields.erosion_gate_temp.to_numpy()) == 0
