from __future__ import annotations

import numpy as np

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_erosion_writeback_matches_erorate_times_dt():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    fields = solver.fields
    dt = 0.25

    solver._compute_source_rates(dt, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    expected_increment = float(np.sum(fields.erorate_clamped_temp.to_numpy()) * dt)
    before = float(np.sum(fields.erosion_depth.to_numpy()))

    fields.fhpredi2.from_numpy(fields.h.to_numpy())
    fields.frhopredi2.from_numpy(fields.rho.to_numpy())
    fields.tempele.from_numpy(fields.z_bed.to_numpy())
    solver._commit_step(dt, dt, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)

    actual_increment = float(np.sum(fields.erosion_depth.to_numpy()) - before)
    assert expected_increment > 0.0
    np.testing.assert_allclose(actual_increment, expected_increment, rtol=1.0e-5, atol=1.0e-5)
