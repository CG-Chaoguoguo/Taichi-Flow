from __future__ import annotations

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_zone_kero_mapping_fields_are_exposed_in_step_diagnostics():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    components = record["tau_components"]
    assert components["zone_id_current"]["max"] >= 0
    assert components["kero_current"]["max"] >= 0.0
    assert components["kero_zone_table_value"]["max"] >= 0.0

    top_cells = record["kero_zone_unit_top_cells"]["top_50_erorate_raw_cells"]
    assert top_cells
    first = top_cells[0]
    assert "zone_id_current" in first
    assert "zone_id_raw_raster" in first
    assert "kero_current" in first
    assert "kero_zone_table_value" in first
