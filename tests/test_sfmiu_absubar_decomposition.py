from __future__ import annotations

import csv

from tests.comparison.run_paired_erosion_gate_diagnostic import _write_sfmiu_absubar_decomposition_artifacts
from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_sfmiu_absubar_decomposition_exposes_fortran_velocity_candidates():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    components = record["tau_components"]
    assert components["absubar_current"]["max"] > 0.0
    assert components["absubar_fortran_fvpredi2_candidate"]["max"] >= 0.0
    assert components["miudebris_fortran_exact"]["max"] > 0.0
    assert components["coemiu_current"]["max"] > 0.0

    variants = record["sfmiu_absubar_variants"]
    assert set(variants) == {
        "A_active_current_sfmiu",
        "B_absubar_fortran_fvpredi2_candidate",
        "C_absubar_accepted_velocity_only",
        "D_absubar_candidate_velocity_only",
        "E_miudebris_exact_fortran_branch",
        "F_sfmiu_absubar_squared_audit",
        "G_sfmiu_disabled",
        "H_sfmanning_only_tau",
    }
    assert variants["A_active_current_sfmiu"]["count_all_erosion_gates_true"] > 0


def test_fortran_miudebris_branch_uses_linear_blend_below_point_one():
    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    components = record["tau_components"]
    assert components["miudebris_fortran_exact"]["max"] > 0.001
    assert components["miudebris_fortran_exact"]["max"] == components["miudebris_current"]["max"]


def test_sfmiu_absubar_variant_artifact_writes_matrix(tmp_path):
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver.enable_erosion_step_diagnostics(True, clear=True)
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)
    solver.erosion_step_diagnostics.append(record)

    artifact = _write_sfmiu_absubar_decomposition_artifacts(
        solver,
        "20a",
        tmp_path,
        artifact_suffix="_unit",
    )

    assert artifact["variant_aggregate"]["A_active_current_sfmiu"]["count_all_erosion_gates_true_sum"] > 0
    with open(artifact["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["variant"] for row in rows} == {
        "A_active_current_sfmiu",
        "B_absubar_fortran_fvpredi2_candidate",
        "C_absubar_accepted_velocity_only",
        "D_absubar_candidate_velocity_only",
        "E_miudebris_exact_fortran_branch",
        "F_sfmiu_absubar_squared_audit",
        "G_sfmiu_disabled",
        "H_sfmanning_only_tau",
    }
    with open(artifact["top_cells_csv_path"], newline="", encoding="utf-8") as handle:
        top_rows = list(csv.DictReader(handle))
    assert {row["category"] for row in top_rows}
