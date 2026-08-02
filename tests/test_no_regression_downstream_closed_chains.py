from __future__ import annotations

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_downstream_closed_chain_diagnostics_still_expose_taoc_writeback_and_tau_terms():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    assert record["count_tau_gt_taoc_active"] > 0
    assert record["erorate_clamped"]["sum"] > 0.0
    assert "sfmiu_absubar_variants" in record
    assert "sfmanning_variants" in record
    assert "erosion_depth_increment_sum_expected" in record
