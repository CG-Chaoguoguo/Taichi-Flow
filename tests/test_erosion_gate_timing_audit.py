from __future__ import annotations

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_erosion_step_diagnostic_record_contains_gate_and_writeback_fields():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=10.0, dt_used=0.25)

    assert record["t_start_s"] == 10.0
    assert record["dt_s"] == 0.25
    assert record["count_all_erosion_gates_true_active"] > 0
    assert record["count_all_erosion_gates_true_old"] == 0
    assert record["erosion_depth_increment_sum_expected"] > 0.0
    assert "erorate_after_rholimit_clamp" in record
    assert "top_cells" in record
    assert record["top_cells"]
