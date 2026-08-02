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


def test_experimental_cvbar_erosion_override_is_default_off_and_changes_sfy_only_when_enabled():
    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)
    cfg = solver.config

    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    tau_default = solver.fields.tau_temp.to_numpy().copy()
    taoc_default = solver.fields.taoc_fortran_temp.to_numpy().copy()

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)
    solver._compute_source_rates(
        0.25,
        cfg.rheology.rho_water,
        cfg.rheology.rho_sediment,
        cfg.rheology.Cv_max,
        erosion_cvbar_override_enabled=1,
        erosion_cvbar_override=0.65,
    )
    tau_override = solver.fields.tau_temp.to_numpy()
    taoc_override = solver.fields.taoc_fortran_temp.to_numpy()

    assert np.all(tau_override > tau_default)
    np.testing.assert_allclose(taoc_override, taoc_default)


def test_source_backed_cvbar_erosion_parity_defaults_on(monkeypatch):
    monkeypatch.delenv("EDDA_LEGACY_PARITY_MODE", raising=False)
    monkeypatch.delenv("EDDA_LEGACY_CVBAR_EROSION_PARITY", raising=False)
    monkeypatch.delenv("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY", raising=False)

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)

    assert solver.legacy_parity_mode is False
    assert solver.legacy_cvbar_erosion_parity is True
    assert solver.experimental_cvbar_erosion_parity is False
    assert solver.cvbar_erosion_parity_enabled is True


def test_source_backed_cvbar_erosion_parity_explicit_ablation(monkeypatch):
    monkeypatch.delenv("EDDA_LEGACY_PARITY_MODE", raising=False)
    monkeypatch.setenv("EDDA_LEGACY_CVBAR_EROSION_PARITY", "0")
    monkeypatch.delenv("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY", raising=False)

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)

    assert solver.legacy_parity_mode is False
    assert solver.legacy_cvbar_erosion_parity is False
    assert solver.experimental_cvbar_erosion_parity is False
    assert solver.cvbar_erosion_parity_enabled is False


def test_legacy_parity_mode_enables_proven_cvbar_semantic(monkeypatch):
    monkeypatch.setenv("EDDA_LEGACY_PARITY_MODE", "1")
    monkeypatch.delenv("EDDA_LEGACY_CVBAR_EROSION_PARITY", raising=False)
    monkeypatch.delenv("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY", raising=False)

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)

    assert solver.legacy_parity_mode is True
    assert solver.legacy_cvbar_erosion_parity is True
    assert solver.experimental_cvbar_erosion_parity is False
    assert solver.cvbar_erosion_parity_enabled is True


def test_legacy_cvbar_flag_can_enable_semantic_without_umbrella(monkeypatch):
    monkeypatch.delenv("EDDA_LEGACY_PARITY_MODE", raising=False)
    monkeypatch.setenv("EDDA_LEGACY_CVBAR_EROSION_PARITY", "1")
    monkeypatch.delenv("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY", raising=False)

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)

    assert solver.legacy_parity_mode is False
    assert solver.legacy_cvbar_erosion_parity is True
    assert solver.experimental_cvbar_erosion_parity is False
    assert solver.cvbar_erosion_parity_enabled is True


def test_experiment_cvbar_flag_remains_separate_from_legacy(monkeypatch):
    monkeypatch.delenv("EDDA_LEGACY_PARITY_MODE", raising=False)
    monkeypatch.setenv("EDDA_LEGACY_CVBAR_EROSION_PARITY", "0")
    monkeypatch.setenv("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY", "1")

    solver = build_two_cell_erosion_solver(cv=0.05, erodible_thickness=10.0)

    assert solver.legacy_parity_mode is False
    assert solver.legacy_cvbar_erosion_parity is False
    assert solver.experimental_cvbar_erosion_parity is True
    assert solver.cvbar_erosion_parity_enabled is True
