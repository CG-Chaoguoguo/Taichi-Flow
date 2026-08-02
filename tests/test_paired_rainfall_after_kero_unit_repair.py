from __future__ import annotations

from tests.comparison.run_paired_erosion_gate_diagnostic import _write_kero_zone_unit_decomposition_artifacts
from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_kero_unit_phase_keeps_variants_diagnostics_only(tmp_path):
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver.enable_erosion_step_diagnostics(True, clear=True)
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    solver.erosion_step_diagnostics.append(
        solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)
    )

    artifact = _write_kero_zone_unit_decomposition_artifacts(solver, "20a", tmp_path)

    assert artifact["variant_aggregate"]["A_active_current"]["source_valid"] is True
    assert artifact["variant_aggregate"]["B_kero_per_hour_div_3600"]["source_valid"] is False
    assert artifact["variant_aggregate"]["D_kero_percent_style_div_100"]["source_valid"] is False
