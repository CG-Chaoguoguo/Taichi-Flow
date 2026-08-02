from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from edda.solver.edda_solver import EDDASolver
from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_erosion_output_interpretation_variants_are_available():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    variants = record["erosion_output_interpretation_variants"]
    assert set(variants) == {
        "A_current_raw_erosion_depth_after_step",
        "J_fortran_eleori_minus_ele_mask",
        "K_threshold_only",
    }
    assert variants["J_fortran_eleori_minus_ele_mask"]["source_valid"] is True
    assert variants["K_threshold_only"]["source_valid"] is True
    assert variants["A_current_raw_erosion_depth_after_step"]["positive_erosion_cell_count"] > 0


def test_fortran_erosion_output_helper_uses_eleori_minus_ele_threshold_and_gindx_mask():
    solver = SimpleNamespace(
        dfs_dynamic_wave=SimpleNamespace(precomputed_failure_gindx=np.array([[0, 1], [0, 0]], dtype=np.int32))
    )
    state = {
        "z_original": np.array([[10.0, 10.0], [10.0, 10.0]], dtype=np.float64),
        "z_bed": np.array([[9.9, 9.8], [9.9995, 10.2]], dtype=np.float64),
    }

    output = EDDASolver._build_fortran_erosion_depth_output(solver, state)

    np.testing.assert_allclose(output, np.array([[0.1, 0.0], [0.0, 0.0]], dtype=np.float64))
