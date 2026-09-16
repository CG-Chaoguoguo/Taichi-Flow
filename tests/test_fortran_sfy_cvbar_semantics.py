from __future__ import annotations

import numpy as np

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def test_diagnostics_model_fortran_scalar_cvbar_sfy_as_what_if_not_active_formula():
    solver = build_two_cell_erosion_solver(cv=0.25, erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    record = solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)

    variants = record["tau_variants"]
    active = variants["A_current_active"]
    zero_sfy = variants["C_sfy_zero_cvbar_lte_cvtol"]
    local_recomputed = variants["D_sfy_local_cv_recomputed"]

    # Variant C follows the Fortran branch that disables sfy when scalar cvbar <= cvtol.
    # It must be diagnostics-only and should not exceed the active tau/erosion prediction.
    assert zero_sfy["predicted_erosion_increment_sum"] <= active["predicted_erosion_increment_sum"]
    assert local_recomputed["count_all_erosion_gates_true"] == active["count_all_erosion_gates_true"]
    assert record["cvbar_candidates"]["source_note"]


def test_stale_scalar_cvbar_is_the_only_sfy_path():
    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)
    cfg = solver.config

    solver.legacy_previous_face_cvbar_scalar = 0.0
    solver._compute_source_rates(
        0.25,
        cfg.rheology.rho_water,
        cfg.rheology.rho_sediment,
        cfg.rheology.Cv_max,
        erosion_cvbar_override=0.0,
    )
    tau_zero = solver.fields.tau_temp.to_numpy().copy()
    taoc_zero = solver.fields.taoc_fortran_temp.to_numpy().copy()

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)
    solver.legacy_previous_face_cvbar_scalar = 0.65
    solver._compute_source_rates(
        0.25,
        cfg.rheology.rho_water,
        cfg.rheology.rho_sediment,
        cfg.rheology.Cv_max,
        erosion_cvbar_override=0.65,
    )
    tau_scalar = solver.fields.tau_temp.to_numpy()
    taoc_scalar = solver.fields.taoc_fortran_temp.to_numpy()

    assert np.all(tau_scalar > tau_zero)
    np.testing.assert_allclose(taoc_scalar, taoc_zero)
    assert not hasattr(solver, "legacy_cvbar_erosion_parity")
    assert not hasattr(solver, "experimental_cvbar_erosion_parity")
    assert not hasattr(solver, "cvbar_erosion_parity_enabled")


def test_cvbar_env_switches_are_removed(monkeypatch):
    monkeypatch.setenv("EDDA_LEGACY_CVBAR_EROSION_PARITY", "0")
    monkeypatch.setenv("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY", "1")
    monkeypatch.delenv("EDDA_LEGACY_PARITY_MODE", raising=False)

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)
    assert not hasattr(solver, "cvbar_erosion_parity_enabled")
    assert hasattr(solver, "legacy_previous_face_cvbar_scalar")
