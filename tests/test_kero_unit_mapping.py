from __future__ import annotations

import pytest

from tests.test_erosion_rate_fortran_formula import build_two_cell_erosion_solver


def _diagnostic_record():
    solver = build_two_cell_erosion_solver(erodible_thickness=10.0)
    cfg = solver.config
    solver._compute_source_rates(0.25, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    return solver._make_erosion_step_diagnostic_record(t_start=0.0, dt_used=0.25)


def test_kero_unit_variants_are_diagnostics_only_and_scale_predictably():
    record = _diagnostic_record()
    variants = record["kero_unit_zone_variants"]

    active = variants["A_active_current"]
    per_minute = variants["C_kero_per_minute_div_60"]
    percent_style = variants["D_kero_percent_style_div_100"]
    milli_style = variants["E_kero_milli_style_div_1000"]

    assert active["source_valid"] is True
    assert percent_style["source_valid"] is False
    assert active["predicted_erosion_increment_sum"] > 0.0
    assert per_minute["predicted_erosion_increment_sum"] == pytest.approx(
        active["predicted_erosion_increment_sum"] / 60.0
    )
    assert percent_style["predicted_erosion_increment_sum"] == pytest.approx(
        active["predicted_erosion_increment_sum"] / 100.0
    )
    assert milli_style["predicted_erosion_increment_sum"] == pytest.approx(
        active["predicted_erosion_increment_sum"] / 1000.0
    )


def test_erorate_recomputes_from_kero_times_tau_minus_taoc():
    record = _diagnostic_record()
    recomputed = record["tau_components"]["erorate_raw_recomputed_from_kero_tau"]

    assert recomputed["sum"] == pytest.approx(record["erorate_raw"]["sum"])
    assert recomputed["max"] == pytest.approx(record["erorate_raw"]["max"])
