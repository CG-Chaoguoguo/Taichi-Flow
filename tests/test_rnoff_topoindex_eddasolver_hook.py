import numpy as np
import pytest

from edda.config.sim_config import ComputeParams, SimulationConfig
from edda.solver.edda_solver import EDDASolver
from edda.solver.native_unsfin_provider import (
    DFS_SOURCE_STAGING_FAST_CONSUME_ENV,
    DFS_SOURCE_STAGING_FIELD_ENV,
    DFS_SOURCE_STAGING_KERNEL_ENV,
    PROJECT_CUDA_BACKEND_STAGE1_ENV,
    RNOFF_DFS_SHADOW_FEED_ENV,
    RNOFF_DFS_SHADOW_FEED_FLAG_DISABLED_REASON,
    RNOFF_GPU_FIELD_FEED_ENV,
    RNOFF_NATIVE_FEED_FLAG_DISABLED_REASON,
    RNOFF_NATIVE_UNSFIN_FEED_ENV,
    RNOFF_Q_ORACLE_NOT_ACCEPTED_REASON,
    RNOFF_TOPOINDEX_ENV,
    RUNTIME_FEED_ENV,
)
from tools.diagnostics.native_unsfin_ledger_diagnostic import LedgerArrays


def _write_ascii_dem(path):
    path.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 10",
                "NODATA_value -9999",
                "10 9",
                "8 7",
            ]
        )
        + "\n",
        encoding="ascii",
    )


def _write_synthetic_sidecars(tmp_path):
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    (sidecars / "nxtfil.asc").write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 10",
                "NODATA_value -9999",
                "2 4",
                "4 4",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    (sidecars / "ndxfil.txt").write_text("1 1\n2 2\n3 3\n4 4\n", encoding="ascii")
    (sidecars / "dscfil.txt").write_text(
        "\n".join(
            [
                "-9999",
                "1",
                "2",
                "4",
                "-9999",
                "2",
                "4",
                "-9999",
                "3",
                "4",
                "-9999",
                "4",
                "4",
                "-9999",
                "5",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    (sidecars / "wffil.txt").write_text(
        "\n".join(
            [
                "-9999",
                "1",
                "0.7",
                "0.3",
                "-9999",
                "2",
                "1.0",
                "-9999",
                "3",
                "1.0",
                "-9999",
                "4",
                "1.0",
                "-9999",
                "5",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    return sidecars


def _solver_with_staged_rnoff_inputs(tmp_path):
    dem_path = tmp_path / "dem.asc"
    _write_ascii_dem(dem_path)
    config = SimulationConfig(
        dem_file=str(dem_path),
        output_dir=str(tmp_path / "output"),
        save_intermediate=False,
        compute=ComputeParams(backend="cpu"),
    )
    solver = EDDASolver(config)
    solver.initialize()

    # field arrays use Taichi shape (nx, ny); cell ids are [[1, 3], [2, 4]].
    rideb = np.array([[1.5, 0.0], [0.1, 0.0]], dtype=solver.numpy_float_dtype)
    kst = np.full((2, 2), 0.5, dtype=solver.numpy_float_dtype)
    depth = np.ones((2, 2), dtype=solver.numpy_float_dtype)
    rizero = np.full((2, 2), 1.0e-9, dtype=solver.numpy_float_dtype)
    solver.fields.tempri.from_numpy(rideb)
    solver.fields.infiltration.from_numpy(np.full((2, 2), -1.0, dtype=solver.numpy_float_dtype))
    solver.fields.K_sat_top_field.from_numpy(kst)
    solver.dfs_dynamic_wave.depthwt0_field.from_numpy(depth)
    solver.dfs_dynamic_wave.rizero0_field.from_numpy(rizero)
    return solver


def _configure_hook(solver, sidecars):
    return solver.configure_rnoff_topoindex_runtime_hook(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
    )


def _fake_provider_generator(_request):
    ledger = LedgerArrays(
        gindx=np.array([1, 0, 1, 1], dtype=np.int32),
        tfail_s=np.array([10.0, np.nan, 600.0, 900.0], dtype=np.float64),
        fdepth_m=np.array([0.2, 0.0, 0.3, 0.4], dtype=np.float64),
        fsdepth_m=None,
        meta={
            "source_provenance": "production_native_unsfin_ledger_only",
            "completed_active_count": 4,
            "processed_eligible_cells": 3,
            "performance_truncated": False,
            "config_hash": "rnoff-provider-runtime-validation",
        },
    )
    return ledger, {"processed_eligible_cells": 3, "wall_seconds": 0.01}


def _fake_rnoff_schedule_generator(request, q_rows_by_cell):
    rows = []
    for cell_id in request.rnoff_schedule_target_cells or []:
        q_rows = list(q_rows_by_cell[int(cell_id)])
        rows.append(
            {
                "case": "synthetic",
                "one_based_cell_id": int(cell_id),
                "period": int(q_rows[-1]["period"]),
                "q_period_count": len(q_rows),
                "q_after_cap": float(q_rows[-1]["q_after_cap"]),
                "tfail": 10.0 * int(cell_id),
                "gindx": 1,
                "fdepth": 3.0,
                "branch": "tfail_assigned",
                "event_type": "TFailAssignment",
            }
        )
    return rows, {
        "schedule_diagnostic_row_count": len(rows),
        "event_type_counts": {"TFailAssignment": len(rows)},
        "tfail_positive_count": len(rows),
        "tfail_negative_count": 0,
        "skip_or_no_failure_count": 0,
        "q_period_rows_used": sum(int(row["q_period_count"]) for row in rows),
    }


def test_dfs_connectivity_host_cache_reuses_immutable_snapshots(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    dfs = solver.dfs_dynamic_wave

    first = dfs._get_flow_connectivity_numpy_cached()
    refresh_count = dfs._flow_connectivity_host_cache_refresh_count
    second = dfs._get_flow_connectivity_numpy_cached()

    assert dfs._flow_connectivity_host_cache_refresh_count == refresh_count
    assert second["cell_id"] is first["cell_id"]
    assert second["flow_neighbor_id"] is first["flow_neighbor_id"]
    assert second["flow_neighbor_i"] is first["flow_neighbor_i"]
    assert second["flow_neighbor_j"] is first["flow_neighbor_j"]
    assert first["cell_id"].flags.writeable is False
    assert first["flow_neighbor_id"].flags.writeable is False
    np.testing.assert_array_equal(first["cell_id"], solver.fields.cell_id.to_numpy())
    np.testing.assert_array_equal(first["flow_neighbor_id"], solver.fields.flow_neighbor_id.to_numpy())
    np.testing.assert_array_equal(first["flow_neighbor_i"], solver.fields.flow_neighbor_i.to_numpy())
    np.testing.assert_array_equal(first["flow_neighbor_j"], solver.fields.flow_neighbor_j.to_numpy())


def test_dfs_connectivity_host_cache_refreshes_after_connectivity_reset(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    dfs = solver.dfs_dynamic_wave

    first = dfs._get_flow_connectivity_numpy_cached()
    refresh_count = dfs._flow_connectivity_host_cache_refresh_count
    cell_id = solver.fields.cell_id.to_numpy().copy()
    neighbor_id = solver.fields.flow_neighbor_id.to_numpy().copy()
    neighbor_i = solver.fields.flow_neighbor_i.to_numpy().copy()
    neighbor_j = solver.fields.flow_neighbor_j.to_numpy().copy()

    solver.fields.set_flow_connectivity(cell_id, neighbor_id, neighbor_i, neighbor_j)
    second = dfs._get_flow_connectivity_numpy_cached()

    assert dfs._flow_connectivity_host_cache_refresh_count == refresh_count + 1
    assert second["cell_id"] is not first["cell_id"]
    np.testing.assert_array_equal(second["cell_id"], cell_id)
    np.testing.assert_array_equal(second["flow_neighbor_id"], neighbor_id)
    np.testing.assert_array_equal(second["flow_neighbor_i"], neighbor_i)
    np.testing.assert_array_equal(second["flow_neighbor_j"], neighbor_j)


def test_dfs_connectivity_host_cache_refreshes_after_checkpoint_restore(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    dfs = solver.dfs_dynamic_wave

    first = dfs._get_flow_connectivity_numpy_cached()
    refresh_count = dfs._flow_connectivity_host_cache_refresh_count
    checkpoint_path = tmp_path / "restart_state.npz"
    modified_checkpoint_path = tmp_path / "restart_state_modified.npz"
    solver.save_state(str(checkpoint_path))

    with np.load(checkpoint_path, allow_pickle=False) as checkpoint:
        arrays = {name: checkpoint[name].copy() for name in checkpoint.files}
    restored_cell_id = arrays["fields__cell_id"].copy()
    restored_cell_id[0, 0] = restored_cell_id[0, 0] + 100
    arrays["fields__cell_id"] = restored_cell_id
    np.savez_compressed(modified_checkpoint_path, **arrays)

    solver.load_state(str(modified_checkpoint_path))
    second = dfs._get_flow_connectivity_numpy_cached()

    assert dfs._flow_connectivity_host_cache_refresh_count == refresh_count + 1
    assert second["cell_id"] is not first["cell_id"]
    np.testing.assert_array_equal(second["cell_id"], restored_cell_id)


def test_eddasolver_rnoff_topoindex_hook_flag_off_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", raising=False)
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    _configure_hook(solver, sidecars)

    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    manifest = solver.apply_rnoff_topoindex_runtime_hook(dt=1.0)

    assert manifest["rnoff_topoindex_runtime_enabled"] is False
    assert manifest["rnoff_topoindex_branch_active"] is False
    assert manifest["changed_field_names"] == []
    assert manifest["default_off_verified"] is True
    assert manifest["dfs_connectivity_changed"] is False
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)


def test_eddasolver_rnoff_topoindex_hook_flag_on_updates_only_rnoff_state(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "1")
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    _configure_hook(solver, sidecars)

    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    manifest = solver.apply_rnoff_topoindex_runtime_hook(dt=1.0)

    assert manifest["rnoff_topoindex_runtime_enabled"] is True
    assert manifest["rnoff_topoindex_branch_active"] is True
    assert manifest["sidecar_shape_validated"] is True
    assert manifest["fail_closed"] is False
    assert manifest["dfs_connectivity_changed"] is False
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    assert set(manifest["changed_field_names"]).issubset({"ir", "rik", "ro"})

    by_cell = {row["cell_id"]: row for row in manifest["cells"]}
    assert [by_cell[cell]["ro"] for cell in range(1, 5)] == pytest.approx([1.0, 0.3, 0.0, 0.1])
    assert [by_cell[cell]["rik"] for cell in range(1, 5)] == pytest.approx([1.0, 1.0, 0.0, 1.0])
    assert [by_cell[cell]["ir"] for cell in range(1, 5)] == pytest.approx([0.5, 0.5, 0.0, 0.5])

    infiltration = solver.fields.infiltration.to_numpy()
    assert infiltration[0, 0] == pytest.approx(0.5)
    assert infiltration[1, 0] == pytest.approx(0.5)
    assert infiltration[0, 1] == pytest.approx(0.0)
    assert infiltration[1, 1] == pytest.approx(0.5)


def test_eddasolver_rnoff_topoindex_hook_missing_sidecar_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "1")
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    (sidecars / "wffil.txt").unlink()
    _configure_hook(solver, sidecars)

    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    manifest = solver.apply_rnoff_topoindex_runtime_hook(dt=1.0)

    assert manifest["rnoff_topoindex_runtime_enabled"] is True
    assert manifest["rnoff_topoindex_branch_active"] is False
    assert manifest["fail_closed"] is True
    assert "wffil" in manifest["blocked_reason"]
    assert manifest["dfs_connectivity_changed"] is False
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)


def test_rnoff_period_precompute_flag_off_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv("EDDA_EXPERIMENT_RNOFF_PERIOD_PRECOMPUTE", raising=False)
    monkeypatch.delenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", raising=False)
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    _configure_hook(solver, sidecars)

    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    manifest = solver.dfs_dynamic_wave.apply_rnoff_period_precompute(dt=1.0)

    assert manifest["rnoff_period_precompute_enabled"] is False
    assert manifest["rnoff_period_precompute_active"] is False
    assert manifest["default_off_verified"] is True
    assert manifest["changed_field_names"] == []
    assert int(solver.dfs_dynamic_wave.rnoff_period_precompute_active[None]) == 0
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)


def test_rnoff_period_precompute_stages_source_order_ir_without_late_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_PERIOD_PRECOMPUTE", "1")
    monkeypatch.delenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", raising=False)
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    _configure_hook(solver, sidecars)
    rainfall = np.array([[1.5, 0.0], [0.1, 0.0]], dtype=solver.numpy_float_dtype)
    solver.fields.rainfall.from_numpy(rainfall)

    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    manifest = solver.dfs_dynamic_wave.apply_rnoff_period_precompute(dt=1.0)

    assert manifest["rnoff_period_precompute_enabled"] is True
    assert manifest["rnoff_period_precompute_active"] is True
    assert manifest["hook_stage"] == "period_precompute"
    assert manifest["mutate_infiltration"] is False
    assert manifest["diagnostic_output_fields"] == ["ir", "rik", "ro"]
    assert manifest["production_changed_field_names"] == []
    assert int(solver.dfs_dynamic_wave.rnoff_period_precompute_active[None]) == 1
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)
    np.testing.assert_allclose(
        solver.dfs_dynamic_wave.rnoff_period_precompute_ir_field.to_numpy(),
        np.array([[0.5, 0.0], [0.5, 0.5]], dtype=solver.numpy_float_dtype),
    )


def test_rnoff_period_precompute_gpu_kernel_matches_source_order_ir(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_PERIOD_PRECOMPUTE", "1")
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX_PERIOD_GPU_KERNEL", "1")
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    _configure_hook(solver, sidecars)
    rainfall = np.array([[1.5, 0.0], [0.1, 0.0]], dtype=solver.numpy_float_dtype)
    solver.fields.rainfall.from_numpy(rainfall)

    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    manifest = solver.dfs_dynamic_wave.apply_rnoff_period_precompute(dt=1.0)

    assert manifest["rnoff_period_precompute_enabled"] is True
    assert manifest["rnoff_period_precompute_active"] is True
    assert manifest["rnoff_topoindex_period_gpu_kernel_gate_enabled"] is True
    assert manifest["rnoff_topoindex_period_gpu_kernel_active"] is True
    assert manifest["host_runtime_consumer_used"] is False
    assert manifest["diagnostic_output_fields"] == ["ir", "rik", "ro"]
    assert int(solver.dfs_dynamic_wave.rnoff_period_precompute_active[None]) == 1
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)
    np.testing.assert_allclose(
        solver.dfs_dynamic_wave.rnoff_period_precompute_ir_field.to_numpy(),
        np.array([[0.5, 0.0], [0.5, 0.5]], dtype=solver.numpy_float_dtype),
    )


def test_rnoff_period_precompute_recomputes_surface_staging_and_skips_late_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_PERIOD_PRECOMPUTE", "1")
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "1")
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    _configure_hook(solver, sidecars)
    rainfall = np.array([[1.5, 0.0], [0.1, 0.0]], dtype=solver.numpy_float_dtype)
    solver.fields.rainfall.from_numpy(rainfall)
    solver.fields.h.from_numpy(np.full((2, 2), 2.0, dtype=solver.numpy_float_dtype))
    solver.fields.rho.from_numpy(np.full((2, 2), solver.config.rheology.rho_water, dtype=solver.numpy_float_dtype))
    solver.fields.is_boundary.from_numpy(np.zeros((2, 2), dtype=np.int32))
    solver.fields.boundary_type.from_numpy(np.zeros((2, 2), dtype=np.int32))

    solver.dfs_dynamic_wave.apply_rnoff_period_precompute(dt=1.0)
    solver.dfs_dynamic_wave._stage_surface_forcing_direct_rain_plus_storage(
        1.0,
        solver.config.rheology.rho_water,
        solver.config.rheology.Cv_max,
    )
    manifest = solver.dfs_dynamic_wave.apply_rnoff_period_precompute_to_surface_staging(dt=1.0)
    late = solver.dfs_dynamic_wave.apply_rnoff_topoindex_runtime_hook(dt=1.0)

    expected_ir = np.array([[0.5, 0.0], [0.5, 0.5]], dtype=solver.numpy_float_dtype)
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), expected_ir)
    np.testing.assert_allclose(
        solver.fields.fhpredi1.to_numpy(),
        solver.fields.h.to_numpy() + (rainfall - expected_ir),
    )
    assert manifest["period_precompute_applied_to_surface_staging"] is True
    assert manifest["fhpredi1_frhopredi1_recomputed_after_period_precompute"] is True
    assert set(manifest["production_changed_field_names"]) == {"infiltration", "fhpredi1", "frhopredi1"}
    assert late["rnoff_late_hook_skipped_due_period_precompute"] is True
    assert late["changed_field_names"] == []


def test_eddasolver_rnoff_provider_validation_flag_off_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv(RNOFF_TOPOINDEX_ENV, raising=False)
    monkeypatch.delenv(RNOFF_NATIVE_UNSFIN_FEED_ENV, raising=False)
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(tmp_path / "provider_validation"),
        env={},
        provider_generator=_fake_provider_generator,
    )

    assert manifest["rnoff_native_unsfin_provider_validation_enabled"] is False
    assert manifest["fallback_reason"] == RNOFF_NATIVE_FEED_FLAG_DISABLED_REASON
    assert manifest["provider_result_status"] is None
    assert manifest["final_state_mutated"] is False
    assert manifest["changed_field_names"] == []
    assert not (tmp_path / "provider_validation").exists()
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)


def test_eddasolver_rnoff_provider_validation_generates_contract_and_q_diagnostics(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(tmp_path / "provider_validation"),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={RNOFF_TOPOINDEX_ENV: "1", RNOFF_NATIVE_UNSFIN_FEED_ENV: "1"},
        provider_generator=_fake_provider_generator,
    )

    assert manifest["rnoff_native_unsfin_provider_validation_enabled"] is True
    assert manifest["precompute_contract_sidecar_shape_validated"] is True
    assert manifest["precompute_contract_period_count"] == 1
    assert manifest["provider_result_status"] == "generated"
    assert manifest["provider_blocked_reason"] is None
    assert manifest["rnoff_contract_loaded"] is True
    assert manifest["rik_period_loaded"] is True
    assert manifest["q_formula_validated"] is True
    assert manifest["q_runtime_oracle_status"] == "Q_RUNTIME_MATCHES_FORMULA_REPLAY"
    assert manifest["native_unsfin_rnoff_feed_active"] is True
    assert manifest["schedule_generated_with_rnoff"] is False
    assert manifest["rnoff_provider_feed"]["semantic_payload"] == "rik_period"
    assert manifest["rnoff_provider_feed"]["q_payload_role"] == "diagnostic_check_only"
    assert manifest["rnoff_provider_feed"]["q_diagnostic_row_count"] == 4
    assert manifest["final_state_mutated"] is False
    assert manifest["changed_field_names"] == []
    assert solver.get_rnoff_native_unsfin_provider_diagnostics()["provider_result_status"] == "generated"
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)


def test_eddasolver_rnoff_provider_schedule_generation_dry_run_is_non_mutating(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    output_dir = tmp_path / "provider_schedule_validation"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={RNOFF_TOPOINDEX_ENV: "1", RNOFF_NATIVE_UNSFIN_FEED_ENV: "1"},
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        schedule_target_cells=[1, 4],
    )

    assert manifest["rnoff_native_unsfin_provider_validation_enabled"] is True
    assert manifest["provider_result_status"] == "generated"
    assert manifest["provider_blocked_reason"] is None
    assert manifest["rnoff_contract_loaded"] is True
    assert manifest["rik_period_loaded"] is True
    assert manifest["q_formula_validated"] is True
    assert manifest["schedule_generated_with_rnoff"] is True
    assert manifest["provider_schedule_generation_active"] is True
    assert manifest["dfs_runtime_feed_blocked"] is True
    assert manifest["rnoff_provider_schedule"]["schedule_diagnostic_row_count"] == 2
    assert manifest["final_state_mutated"] is False
    assert manifest["changed_field_names"] == []
    assert (output_dir / "provider_rnoff_schedule_diagnostics.csv").exists()
    assert (output_dir / "provider_rnoff_schedule_diagnostics.json").exists()
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)


def test_eddasolver_rnoff_shadow_lifecycle_requires_explicit_shadow_gate(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(tmp_path / "provider_shadow_validation"),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={RNOFF_TOPOINDEX_ENV: "1", RNOFF_NATIVE_UNSFIN_FEED_ENV: "1"},
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        shadow_lifecycle_enabled=True,
        schedule_target_cells=[1, 4],
    )

    assert manifest["rnoff_native_unsfin_provider_validation_enabled"] is True
    assert manifest["rnoff_dfs_shadow_feed_gate_enabled"] is False
    assert manifest["fallback_reason"] == RNOFF_DFS_SHADOW_FEED_FLAG_DISABLED_REASON
    assert manifest["shadow_lifecycle_active"] is False
    assert manifest["shadow_final_state_mutated"] is False
    assert manifest["schedule_consumed_by_dfs"] is False
    assert manifest["changed_field_names"] == []
    assert not (tmp_path / "provider_shadow_validation").exists()


def test_eddasolver_rnoff_shadow_lifecycle_is_non_mutating_and_does_not_configure_dfs(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    before_infiltration = solver.fields.infiltration.to_numpy().copy()
    before_tempfsh = solver.fields.tempfsh_flow.to_numpy().copy()
    before_tempfsrho = solver.fields.tempfsrho_flow.to_numpy().copy()
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    output_dir = tmp_path / "provider_shadow_validation"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
            RNOFF_DFS_SHADOW_FEED_ENV: "1",
        },
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        shadow_lifecycle_enabled=True,
        schedule_target_cells=[1, 4],
    )

    assert manifest["provider_result_status"] == "generated"
    assert manifest["schedule_generated_with_rnoff"] is True
    assert manifest["provider_schedule_generation_active"] is True
    assert manifest["dfs_runtime_feed_blocked"] is True
    assert manifest["shadow_lifecycle_active"] is True
    assert manifest["shadow_schedule_loaded"] is True
    assert manifest["shadow_crossing_count"] == 2
    assert manifest["shadow_candidate_stage_count"] == 2
    assert manifest["shadow_rejected_discard_count"] == 2
    assert manifest["shadow_accepted_commit_count"] == 2
    assert manifest["shadow_duplicate_fire_count"] == 0
    assert manifest["shadow_final_state_mutated"] is False
    assert manifest["final_state_mutated"] is False
    assert manifest["schedule_consumed_by_dfs"] is False
    assert manifest["changed_field_names"] == []
    assert (output_dir / "rnoff_dfs_shadow_lifecycle" / "rnoff_dfs_shadow_events.csv").exists()
    assert (output_dir / "rnoff_dfs_shadow_lifecycle" / "rnoff_dfs_shadow_lifecycle.json").exists()
    assert solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()["configured"] is False
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)
    np.testing.assert_allclose(solver.fields.tempfsh_flow.to_numpy(), before_tempfsh)
    np.testing.assert_allclose(solver.fields.tempfsrho_flow.to_numpy(), before_tempfsrho)


def test_eddasolver_rnoff_final_state_feed_configures_precomputed_schedule_under_all_gates(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    output_dir = tmp_path / "provider_final_feed"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
        },
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        schedule_target_cells=[1, 4],
    )

    diagnostics = solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()
    assert manifest["provider_result_status"] == "configured"
    assert manifest["provider_dry_run_only"] is False
    assert manifest["schedule_generated_with_rnoff"] is True
    assert manifest["rnoff_dfs_runtime_feed_active"] is True
    assert manifest["schedule_consumed_by_dfs"] is True
    assert manifest["final_state_mutated"] is True
    assert manifest["changed_field_names"]
    assert manifest["rnoff_gpu_field_feed_gate_enabled"] is False
    assert manifest["rnoff_gpu_field_feed_active"] is False
    assert manifest["schedule_buffer_uploaded_to_taichi"] is False
    assert manifest["taichi_schedule_buffer_roundtrip_ok"] is None
    assert manifest["gindx_zero_no_feed_count"] == 0
    assert diagnostics["configured"] is True
    assert diagnostics["scheduled_cell_count"] == 2
    assert solver.dfs_dynamic_wave.dfs_failure_source_variant == "precomputed_unsfin_schedule"
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity


def test_eddasolver_rnoff_gpu_field_feed_uploads_schedule_buffer_under_explicit_gate(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    output_dir = tmp_path / "provider_gpu_field_feed"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
            RNOFF_GPU_FIELD_FEED_ENV: "1",
        },
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        schedule_target_cells=[1, 4],
    )

    diagnostics = solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()
    assert manifest["provider_result_status"] == "configured"
    assert manifest["rnoff_dfs_runtime_feed_active"] is True
    assert manifest["schedule_consumed_by_dfs"] is True
    assert manifest["final_state_mutated"] is True
    assert manifest["rnoff_gpu_field_feed_gate_enabled"] is True
    assert manifest["rnoff_gpu_field_feed_active"] is True
    assert manifest["dfs_source_staging_field_gate_enabled"] is False
    assert manifest["dfs_source_staging_field_active"] is False
    assert manifest["schedule_buffer_uploaded_to_taichi"] is True
    assert manifest["taichi_schedule_buffer_roundtrip_ok"] is True
    assert manifest["taichi_schedule_buffer_fallback_reason"] is None
    assert diagnostics["rnoff_gpu_field_feed_active"] is True
    assert diagnostics["taichi_schedule_buffer_roundtrip_ok"] is True
    assert diagnostics["dfs_source_staging_field_active"] is False
    np.testing.assert_array_equal(
        solver.dfs_dynamic_wave.precomputed_failure_tfail_field.to_numpy(),
        solver.dfs_dynamic_wave.precomputed_failure_tfail,
    )
    np.testing.assert_array_equal(
        solver.dfs_dynamic_wave.precomputed_failure_gindx_field.to_numpy(),
        solver.dfs_dynamic_wave.precomputed_failure_gindx,
    )
    np.testing.assert_array_equal(
        solver.dfs_dynamic_wave.precomputed_failure_fdepth_field.to_numpy(),
        solver.dfs_dynamic_wave.precomputed_failure_fdepth,
    )


def test_eddasolver_dfs_source_staging_field_requires_explicit_gate_pair(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    output_dir = tmp_path / "provider_source_staging_field"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
            RNOFF_GPU_FIELD_FEED_ENV: "1",
            DFS_SOURCE_STAGING_FIELD_ENV: "1",
        },
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        schedule_target_cells=[1, 4],
    )

    diagnostics = solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()
    assert manifest["provider_result_status"] == "configured"
    assert manifest["rnoff_gpu_field_feed_active"] is True
    assert manifest["dfs_source_staging_field_gate_enabled"] is True
    assert manifest["dfs_source_staging_field_active"] is True
    assert diagnostics["dfs_source_staging_field_active"] is True
    assert diagnostics["source_staging_cpu_vs_taichi_match"] is None


def test_eddasolver_project_cuda_backend_stage1_enables_validated_source_bundle(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    output_dir = tmp_path / "project_cuda_backend_stage1"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
            PROJECT_CUDA_BACKEND_STAGE1_ENV: "1",
        },
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        schedule_target_cells=[1, 4],
    )

    diagnostics = solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()
    assert manifest["provider_result_status"] == "configured"
    assert manifest["project_cuda_backend_stage1_gate_enabled"] is True
    assert manifest["project_cuda_backend_stage1_active"] is True
    assert manifest["cuda_backend_stage1_active"] is True
    assert manifest["cuda_backend_stage1_component_count"] == 3
    assert manifest["project_cuda_backend_stage1_components"] == [
        "rnoff_gpu_field_feed",
        "dfs_source_staging_field",
        "dfs_source_staging_fast_consume",
    ]
    assert manifest["rnoff_gpu_field_feed_active"] is True
    assert manifest["dfs_source_staging_field_active"] is True
    assert manifest["dfs_source_staging_fast_consume_gate_enabled"] is True
    assert manifest["dfs_source_staging_kernel_gate_enabled"] is False
    assert manifest["dfs_source_staging_kernel_active"] is False
    assert manifest["final_state_mutated"] is True
    assert diagnostics["rnoff_gpu_field_feed_active"] is True
    assert diagnostics["dfs_source_staging_field_active"] is True
    assert diagnostics["dfs_source_staging_fast_consume_gate_enabled"] is True
    assert diagnostics["dfs_source_staging_kernel_gate_enabled"] is False


def test_eddasolver_dfs_source_staging_kernel_manifest_is_default_closed_until_validated_stage(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    output_dir = tmp_path / "provider_source_staging_kernel"

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(output_dir),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
            RNOFF_GPU_FIELD_FEED_ENV: "1",
            DFS_SOURCE_STAGING_FIELD_ENV: "1",
            DFS_SOURCE_STAGING_FAST_CONSUME_ENV: "1",
            DFS_SOURCE_STAGING_KERNEL_ENV: "1",
        },
        provider_generator=_fake_provider_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
        provider_schedule_generation_enabled=True,
        schedule_target_cells=[1, 4],
    )

    diagnostics = solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()
    assert manifest["schedule_consumed_by_dfs"] is True
    assert manifest["final_state_mutated"] is True
    assert manifest["dfs_source_staging_kernel_gate_enabled"] is True
    assert manifest["dfs_source_staging_kernel_required_gates_active"] is True
    assert manifest["dfs_source_staging_kernel_active"] is False
    assert manifest["source_staging_kernel_vs_cpu_match"] is None
    assert manifest["kernel_fallback_active"] is True
    assert manifest["kernel_fallback_reason"] == "SOURCE_STAGING_FAST_CONSUME_NOT_VALIDATED"
    assert manifest["kernel_candidate_stage_count"] == 0
    assert manifest["kernel_h2d_bytes"] == 0
    assert manifest["kernel_d2h_bytes"] == 0
    assert diagnostics["dfs_source_staging_kernel_gate_enabled"] is True
    assert diagnostics["kernel_fallback_reason"] == "SOURCE_STAGING_FAST_CONSUME_NOT_VALIDATED"


def test_eddasolver_rnoff_provider_validation_requires_q_oracle_status(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(tmp_path / "provider_validation"),
        env={RNOFF_TOPOINDEX_ENV: "1", RNOFF_NATIVE_UNSFIN_FEED_ENV: "1"},
        provider_generator=_fake_provider_generator,
    )

    assert manifest["precompute_contract_sidecar_shape_validated"] is True
    assert manifest["provider_result_status"] == "blocked"
    assert manifest["provider_blocked_reason"] == RNOFF_Q_ORACLE_NOT_ACCEPTED_REASON
    assert manifest["rnoff_contract_loaded"] is False
    assert manifest["final_state_mutated"] is False
    assert manifest["changed_field_names"] == []


def test_eddasolver_rnoff_provider_validation_missing_sidecar_fails_closed(tmp_path):
    solver = _solver_with_staged_rnoff_inputs(tmp_path)
    sidecars = _write_synthetic_sidecars(tmp_path)
    (sidecars / "wffil.txt").unlink()
    before_infiltration = solver.fields.infiltration.to_numpy().copy()

    manifest = solver.validate_rnoff_native_unsfin_provider_runtime_path(
        nxtfil=str(sidecars / "nxtfil.asc"),
        ndxfil=str(sidecars / "ndxfil.txt"),
        dscfil=str(sidecars / "dscfil.txt"),
        wffil=str(sidecars / "wffil.txt"),
        imax=4,
        provider_output_dir=str(tmp_path / "provider_validation"),
        q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        env={RNOFF_TOPOINDEX_ENV: "1", RNOFF_NATIVE_UNSFIN_FEED_ENV: "1"},
        provider_generator=_fake_provider_generator,
    )

    assert manifest["precompute_contract_fail_closed"] is True
    assert "wffil" in manifest["precompute_contract_blocked_reason"]
    assert manifest["provider_result_status"] is None
    assert manifest["final_state_mutated"] is False
    assert manifest["changed_field_names"] == []
    assert not (tmp_path / "provider_validation").exists()
    np.testing.assert_allclose(solver.fields.infiltration.to_numpy(), before_infiltration)
