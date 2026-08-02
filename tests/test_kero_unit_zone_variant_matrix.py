from __future__ import annotations

import csv

from tests.comparison.run_paired_erosion_gate_diagnostic import _write_kero_zone_unit_decomposition_artifacts
from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_kero_unit_zone_variant_artifact_writes_matrix(tmp_path):
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver.enable_erosion_step_diagnostics(True, clear=True)
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    solver.erosion_step_diagnostics.append(
        solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)
    )

    artifact = _write_kero_zone_unit_decomposition_artifacts(
        solver,
        "20a",
        tmp_path,
        artifact_suffix="_unit",
    )

    assert artifact["variant_aggregate"]["A_active_current"]["predicted_erosion_increment_sum_0_600"] > 0.0
    assert artifact["variant_aggregate"]["D_kero_percent_style_div_100"]["source_valid"] is False
    assert "J_fortran_eleori_minus_ele_mask" in artifact["output_interpretation_final_step"]

    with open(artifact["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["variant"] for row in rows} == {
        "A_active_current",
        "B_kero_per_hour_div_3600",
        "C_kero_per_minute_div_60",
        "D_kero_percent_style_div_100",
        "E_kero_milli_style_div_1000",
        "F_zone_index_shift_minus_1",
        "G_zone_index_shift_plus_1",
        "H_top_layer_kero_only",
        "I_raw_native_zone_kero_table",
    }

    with open(artifact["top_cells_csv_path"], newline="", encoding="utf-8") as handle:
        top_rows = list(csv.DictReader(handle))
    assert {row["category"] for row in top_rows}
