from __future__ import annotations

import csv

from tests.comparison.run_paired_erosion_gate_diagnostic import _write_sfmanning_decomposition_artifacts
from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_sfmanning_variant_artifact_writes_matrix(tmp_path):
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver.enable_erosion_step_diagnostics(True, clear=True)
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)
    solver.erosion_step_diagnostics.append(record)

    artifact = _write_sfmanning_decomposition_artifacts(
        solver,
        "20a",
        tmp_path,
        artifact_suffix="_unit",
    )

    assert artifact["variant_aggregate"]["A_active_current_tau"]["count_all_erosion_gates_true_sum"] > 0
    with open(artifact["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["variant"] for row in rows} == {
        "A_active_current_tau",
        "B_sfmanning_disabled",
        "C_sfmanning_only_current",
        "D_sfmanning_fortran_fvpredi2_absubar",
        "E_sfmanning_accepted_velocity",
        "F_sfmanning_candidate_velocity",
        "G_sfmanning_absubar_linear_audit",
        "H_sfmanning_fortran_depth_exponent",
        "I_sfmanning_raw_native_manning_source",
        "J_sfmanning_cv_correction_disabled_audit",
        "K_original_sfy_sfmiu_plus_fortran_sfmanning",
    }
    with open(artifact["top_cells_csv_path"], newline="", encoding="utf-8") as handle:
        top_rows = list(csv.DictReader(handle))
    assert {row["category"] for row in top_rows}
