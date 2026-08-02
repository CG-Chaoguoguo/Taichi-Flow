from __future__ import annotations

import csv

from tests.comparison.run_paired_erosion_gate_diagnostic import _write_tau_component_decomposition_artifacts
from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_tau_variant_gate_mask_artifact_writes_matrix(tmp_path):
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver.enable_erosion_step_diagnostics(True, clear=True)
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)
    solver.erosion_step_diagnostics.append(record)

    artifact = _write_tau_component_decomposition_artifacts(
        solver,
        "synthetic",
        tmp_path,
        artifact_suffix="_unit",
    )

    assert artifact["variant_aggregate"]["A_current_active"]["count_all_erosion_gates_true_sum"] > 0
    with open(artifact["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["variant"] for row in rows} == {
        "A_current_active",
        "B_sfy_scalar_depth_weighted_cvbar",
        "C_sfy_zero_cvbar_lte_cvtol",
        "D_sfy_local_cv_recomputed",
    }
