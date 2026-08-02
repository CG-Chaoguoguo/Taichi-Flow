from __future__ import annotations

import numpy as np

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_rholimit_clamp_is_recorded_before_erodible_thickness_clamp():
    solver = build_two_cell_erosion_solver(rholimit=1200.0, erodible_thickness=0.01)
    cfg = solver.config

    solver._compute_source_rates(1.0, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)

    raw = solver.fields.erorate_raw_temp.to_numpy()
    after_rholimit = solver.fields.erorate_rholimit_clamped_temp.to_numpy()
    final = solver.fields.erorate_clamped_temp.to_numpy()

    assert int(np.sum(solver.fields.rholimit_clamp_temp.to_numpy())) == 2
    assert int(np.sum(solver.fields.erodible_clamp_temp.to_numpy())) == 2
    assert float(np.min(raw)) > float(np.max(after_rholimit))
    assert float(np.min(after_rholimit)) > float(np.max(final))
    np.testing.assert_allclose(final, np.full((2, 1), 0.01), rtol=1.0e-5, atol=1.0e-5)
