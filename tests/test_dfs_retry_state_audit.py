"""Executable regressions for the September 2026 EDDA lifecycle audit.

The two-attempt test uses source statements from Chamoli dfs.F90:312-327,
342-359. It is a reduced oracle, not a full Chamoli trajectory fixture.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from edda.backend.backend_manager import initialize_taichi
from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver
from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
from edda.solver.edda_solver import EDDASolver
from tests.test_dfs_dynamic_wave import _build_config, _build_fields
from tests.test_checkpoint_restart import _build_config as _restart_config, _write_ascii_dem


def _solver():
    # Exercise the real f64/fast_math=False runtime. Merely declaring f64
    # fields leaves Taichi's lazy default runtime at f32, rounding .fill()
    # values and making strict oracle tests depend on collection order.
    initialize_taichi(backend="cpu", use_double_precision=True)
    cfg = _build_config(
        face_flux_variant="arithmetic_mean_chamoli",
        absubar_variant="signed_mean_chamoli",
        manningbar_variant="debrisflowmanning_cvtol",
        cvlimit_variant="tan_slo_unit_clamp_chamoli",
        sfdf_classify_cv_variant="predicted_step_cv_chamoli",
    )
    fields = _build_fields()
    return DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))


@pytest.mark.parametrize("stage", [
    "_stage_surface_forcing_direct_rain_plus_storage",
    "_stage_surface_forcing",
])
def test_rejected_attempt_cv_is_carried_into_retry_infiltration(stage):
    solver = _solver()
    f = solver.fields
    f.h.fill(1.0)
    f.Cv.fill(0.325)
    f.rho.fill(1000.0 + 0.325 * 1650.0)
    f.K_sat_top_field.fill(10.0)
    f.cvlimit_temp.fill(0.0)
    # First candidate removes 0.5 water depth, leaving Cv = Cvstar.
    getattr(solver, stage)(0.1, 1000.0, 0.65)
    np.testing.assert_allclose(f.fhpredi1.to_numpy(), 0.5, atol=1e-12)
    solver._compute_source_rates(0.1, 1000.0, 2650.0, 0.65, 0.0, 1, 0)
    # Reject BEFORE commit. dfs.F90 retains source-stage cv, not accepted cv.
    # At dt/2 its available free water is now zero, so ir=0 and h_pred=1.
    getattr(solver, stage)(0.05, 1000.0, 0.65)
    np.testing.assert_allclose(f.fhpredi1.to_numpy(), 1.0, atol=1e-12)
    np.testing.assert_allclose(f.Cv.to_numpy(), 0.325, atol=1e-12)


def test_source_controls_off_do_not_create_retry_cv_assignment():
    solver = _solver()
    f = solver.fields
    f.h.fill(1.0)
    f.Cv.fill(0.325)
    f.rho.fill(1536.25)
    f.K_sat_top_field.fill(10.0)
    stage = solver._stage_surface_forcing_direct_rain_plus_storage
    stage(0.1, 1000.0, 0.65)
    solver._compute_source_rates(0.1, 1000.0, 2650.0, 0.65, 0.0, 0, 0)
    stage(0.05, 1000.0, 0.65)
    np.testing.assert_allclose(f.fhpredi1.to_numpy(), 0.5, atol=1e-12)


def test_cfl_reject_never_runs_classification_or_drainage(monkeypatch):
    solver = _solver()
    classify = Mock()
    drain = Mock()
    monkeypatch.setattr(solver, "_classify_sfdf_pre_outflow", lambda *args: classify(*args))
    monkeypatch.setattr(solver, "apply_stormdrain_runtime_hook", lambda *args: drain(*args))
    before = solver.fields.maxffh.to_numpy().copy()
    result = solver.step(2.0)
    assert result["accepted"] is False
    assert solver.cfl_reject_fortran_order[None] < 2147483647
    classify.assert_not_called()
    drain.assert_not_called()
    np.testing.assert_array_equal(solver.fields.maxffh.to_numpy(), before)


def test_depth_reject_never_runs_classification_or_drainage(monkeypatch):
    solver = _solver()
    classify, drain = Mock(), Mock()
    monkeypatch.setattr(solver, "_compute_edge_fluxes", lambda *args: None)
    def reject_depth(*args):
        solver.reject_flag[None] = 1
    monkeypatch.setattr(solver, "_accumulate_and_check", reject_depth)
    monkeypatch.setattr(solver, "_classify_sfdf_pre_outflow", lambda *args: classify(*args))
    monkeypatch.setattr(solver, "apply_stormdrain_runtime_hook", lambda *args: drain(*args))
    result = solver.step(0.01)
    assert result["accepted"] is False
    classify.assert_not_called()
    drain.assert_not_called()


def _initialized(tmp_path: Path, name: str):
    dem = tmp_path / "dem.asc"
    _write_ascii_dem(dem)
    result = EDDASolver(_restart_config(dem, tmp_path / name))
    result.initialize()
    return result


def test_checkpoint_restores_cvbar_and_one_shot_trigger(tmp_path):
    a = _initialized(tmp_path, "a")
    a.dfs_dynamic_wave.legacy_previous_face_cvbar_scalar = 0.275
    a.dfs_dynamic_wave.slide1 = 0
    a.dfs_dynamic_wave.isslidetriggered = 1
    a.dfs_dynamic_wave.last_accepted_outflow_dt = 0.125
    a.time_stepper.t_current = 4.0
    a.time_stepper.total_steps = 12
    a.time_stepper.rejected_steps = 3
    checkpoint = tmp_path / "restart.npz"
    a.save_state(str(checkpoint))
    b = _initialized(tmp_path, "b")
    b.load_state(str(checkpoint))
    assert b.dfs_dynamic_wave.legacy_previous_face_cvbar_scalar == 0.275
    assert b.dfs_dynamic_wave.slide1 == 0
    assert b.dfs_dynamic_wave.isslidetriggered == 1
    assert b.dfs_dynamic_wave.last_accepted_outflow_dt == 0.125


def test_attempt_exhaustion_is_not_reported_as_complete(tmp_path, monkeypatch):
    solver = _initialized(tmp_path, "capped")
    solver.time_stepper.t_end = 2.0
    solver.time_stepper.dt_min = 1.0
    solver.time_stepper.dt_current = 1.0
    solver.time_stepper.dt_max = 1.0
    solver.time_stepper.dt_output = 2.0
    monkeypatch.setattr(solver, "_physics_step", lambda dt: {
        "accepted": False, "used_dt": dt, "suggested_dt": 1.0,
    })
    monkeypatch.setattr(solver, "_observe_numerical_step", lambda *a, **kw: None)
    monkeypatch.setattr(solver, "_output_results", lambda: None)
    with pytest.raises(RuntimeError, match="maxnts"):
        solver.run()
    assert solver.time_stepper.t_current == 0.0
    assert solver.stopped_for_maxnts


def test_invalid_zone_file_must_not_fall_back_to_uniform(tmp_path):
    solver = EDDASolver.__new__(EDDASolver)
    solver.config = SimpleNamespace(spatial_zones=SimpleNamespace(
        zone_file=str(tmp_path / "missing.asc"), zones={}
    ))
    solver._initialize_uniform_parameters = Mock()
    with pytest.raises((RuntimeError, ValueError), match="[Zz]one|spatial"):
        solver._initialize_spatial_zones()
    solver._initialize_uniform_parameters.assert_not_called()


def test_volume_reject_preserves_the_original_pre_reject_classification(monkeypatch):
    """F5 must remain intact: volume rejection is downstream of classification."""
    solver = _solver()
    classify, drain = Mock(), Mock()
    monkeypatch.setattr(solver, "_compute_edge_fluxes", lambda *args: None)
    monkeypatch.setattr(solver, "_accumulate_and_check", lambda *args: None)
    monkeypatch.setattr(solver, "_classify_sfdf_pre_outflow", lambda *args: classify(*args))
    monkeypatch.setattr(solver, "apply_stormdrain_runtime_hook", lambda *args: drain(*args))
    def reject_volume(*args):
        solver.reject_flag[None] = 1
    monkeypatch.setattr(solver, "_finalize_volume_balance", reject_volume)
    result = solver.step(0.01)
    assert not result["accepted"]
    assert result["rejected_stage"] == "volume"
    classify.assert_called_once()
    drain.assert_called_once()


def test_acceptance_replaces_retry_cv_with_committed_cv():
    solver = _solver()
    f = solver.fields
    solver.source_cv_carry.fill(0.65)
    solver.source_cv_carry_valid.fill(1)
    f.fhpredi2.fill(1.0)
    f.frhopredi2.fill(1000.0 + 0.2 * 1650.0)
    solver._commit_step(0.1, 0.1, 1000.0, 2650.0, 0.65)
    assert not np.any(solver.source_cv_carry_valid.to_numpy())
    f.K_sat_top_field.fill(10.0)
    solver._stage_surface_forcing_direct_rain_plus_storage(0.1, 1000.0, 0.65)
    np.testing.assert_allclose(f.fhw.to_numpy(), 1.0 - 0.2 / 0.65, atol=1e-12)


def test_restart_metadata_restores_schedule_and_rejects_legacy(tmp_path):
    from edda.solver.restart_metadata import (
        export_dfs_host_state, validate_dfs_host_state, restore_dfs_host_state,
    )
    a = _solver()
    shape = (a.fields.nx, a.fields.ny)
    a.configure_precomputed_failure_schedule(
        tfail_s=np.ones(shape), gindx=np.ones(shape, dtype=np.int32),
        fdepth_m=np.full(shape, 0.25), taichi_field_feed_enabled=False,
        source_staging_field_enabled=False, source_staging_fast_consume_enabled=False,
        source_staging_kernel_enabled=False, source_staging_kernel_required_gates_active=False,
    )
    a.precomputed_failure_fired[0, 0] = True
    state = export_dfs_host_state(a)
    for name in ("source_cv_carry", "source_cv_carry_valid"):
        state["dfs__" + name] = getattr(a, name).to_numpy()
    b = _solver()
    restore_dfs_host_state(b, validate_dfs_host_state(b, state))
    np.testing.assert_array_equal(b.precomputed_failure_fired, a.precomputed_failure_fired)
    np.testing.assert_array_equal(b.precomputed_failure_tfail, a.precomputed_failure_tfail)
    np.testing.assert_array_equal(b.precomputed_failure_fdepth, a.precomputed_failure_fdepth)
    assert b.precomputed_failure_schedule_info["committed_fired_count"] == 1
    state.pop("dfs_host__version")
    with pytest.raises(ValueError, match="legacy DFS checkpoint"):
        validate_dfs_host_state(b, state)


def test_checkpoint_configuration_mismatch_is_rejected_before_state_write(tmp_path):
    a = _initialized(tmp_path, "config_a")
    checkpoint = tmp_path / "restart.npz"
    a.save_state(str(checkpoint))
    b = _initialized(tmp_path, "config_b")
    b.config.rheology.rho_sediment = 2700.0
    b.fields.h.fill(7.0)
    with pytest.raises(ValueError, match="configuration"):
        b.load_state(str(checkpoint))
    np.testing.assert_array_equal(b.fields.h.to_numpy(), 7.0)


def test_retry_cv_matches_compiled_reduced_fortran_oracle(tmp_path):
    import shutil
    import subprocess
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("Reduced Fortran oracle requires gfortran; Taichi contract tests still run")
    source = Path(__file__).parent / "fixtures" / "edda_retry_cv_oracle.f90"
    binary = tmp_path / "retry-oracle"
    subprocess.run([compiler, "-O0", "-fno-fast-math", str(source), "-o", str(binary)],
                   check=True, capture_output=True, text=True, timeout=30)
    output = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
    expected = np.asarray([[float(x) for x in line.split()] for line in output.stdout.splitlines()])
    solver = _solver()
    f = solver.fields
    f.h.fill(1.0)
    f.Cv.fill(0.325)
    f.rho.fill(1536.25)
    f.K_sat_top_field.fill(10.0)
    f.cvlimit_temp.fill(0.0)
    for row, dt in zip(expected, (0.1, 0.05), strict=True):
        solver._stage_surface_forcing_direct_rain_plus_storage(dt, 1000.0, 0.65)
        solver._compute_source_rates(dt, 1000.0, 2650.0, 0.65, 0.0, 1, 0)
        np.testing.assert_allclose(f.fhpredi1.to_numpy(), row[1], rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(solver.source_cv_carry.to_numpy(), row[2], rtol=1e-12, atol=1e-12)
