from __future__ import annotations

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_tau_component_decomposition_exposes_current_components_and_variants():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    components = record["tau_components"]
    assert components["sfmanning_current"]["sum"] > 0.0
    assert components["sfmiu_current"]["sum"] > 0.0
    assert components["absubar_current"]["max"] > 0.0

    variants = record["tau_variants"]
    assert {
        "A_current_active",
        "B_sfy_scalar_depth_weighted_cvbar",
        "C_sfy_zero_cvbar_lte_cvtol",
        "D_sfy_local_cv_recomputed",
    }.issubset(set(variants))
    assert variants["A_current_active"]["count_all_erosion_gates_true"] > 0
