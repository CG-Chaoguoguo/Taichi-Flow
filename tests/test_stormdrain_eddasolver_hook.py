import numpy as np
import pytest

from edda.config.sim_config import ComputeParams, SimulationConfig
from edda.io.stormdrain_reader import STORMDRAIN_LOW_DEPTH_WEIR_COEFF
from edda.solver.edda_solver import EDDASolver


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


def _write_minimal_drainage(path):
    path.write_text(
        "\n".join(
            [
                " drainage information for EDDA 2.0",
                " number of nodes:",
                " 2",
                " node name ,  index,   type,   invertEl,       maxdepth",
                " j1 1 0 0.0 1.0",
                " o1 2 1 0.0 0.0",
                " number of conduits:",
                " 1",
                "conduit name, inletno,   outletno,   length,    manningN,  xsecshp,   geom1,   geom2",
                " c1 1 2 10.0 0.01 1 1.0 0.0",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    return path


def _solver_with_staged_stormdrain_inputs(tmp_path):
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
    fh = np.zeros((2, 2), dtype=solver.numpy_float_dtype)
    fh[0, 0] = 3.8787900000000005e-11
    solver.fields.fhpredi2.from_numpy(fh)
    return solver


def test_eddasolver_stormdrain_hook_flag_off_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv("EDDA_EXPERIMENT_STORMDRAIN", raising=False)
    solver = _solver_with_staged_stormdrain_inputs(tmp_path)
    drainage = _write_minimal_drainage(tmp_path / "drainage.txt")
    solver.configure_stormdrain_runtime_hook(
        drainage_path=str(drainage),
        expected_node_count=2,
        expected_conduit_count=1,
    )

    before_fhpredi2 = solver.fields.fhpredi2.to_numpy().copy()
    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    manifest = solver.apply_stormdrain_runtime_hook(dt=1.0e-5)

    assert manifest["stormdrain_runtime_enabled"] is False
    assert manifest["stormdrain_branch_active"] is False
    assert manifest["changed_field_names"] == []
    assert manifest["default_off_verified"] is True
    assert manifest["dfs_connectivity_changed"] is False
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    np.testing.assert_allclose(solver.fields.fhpredi2.to_numpy(), before_fhpredi2)


def test_eddasolver_stormdrain_hook_flag_on_updates_only_stormdrain_depth(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_STORMDRAIN", "1")
    solver = _solver_with_staged_stormdrain_inputs(tmp_path)
    drainage = _write_minimal_drainage(tmp_path / "drainage.txt")
    solver.configure_stormdrain_runtime_hook(
        drainage_path=str(drainage),
        expected_node_count=2,
        expected_conduit_count=1,
    )

    before_connectivity = solver.dfs_dynamic_wave._flow_connectivity_hash()
    before = solver.fields.fhpredi2.to_numpy().copy()
    dt = 1.0e-5
    manifest = solver.apply_stormdrain_runtime_hook(dt=dt)

    expected_flow = float(before[0, 0]) ** 1.5 * STORMDRAIN_LOW_DEPTH_WEIR_COEFF
    expected_after = float(before[0, 0]) - expected_flow * dt / 100.0
    assert manifest["stormdrain_runtime_enabled"] is True
    assert manifest["stormdrain_branch_active"] is True
    assert manifest["topology_loaded"] is True
    assert manifest["drainage_topology_validated"] is True
    assert manifest["fail_closed"] is False
    assert manifest["dfs_connectivity_changed"] is False
    assert solver.dfs_dynamic_wave._flow_connectivity_hash() == before_connectivity
    assert set(manifest["changed_field_names"]).issubset({"stormdrain_fhpredi2"})
    assert solver.fields.fhpredi2.to_numpy()[0, 0] == pytest.approx(expected_after)
    assert solver.fields.fhpredi2.to_numpy()[1, 0] == pytest.approx(0.0)
    assert manifest["mutation_contract"]["dfs_equations_changed"] is False
    assert manifest["mutation_contract"]["dfs_face_connectivity_changed"] is False


def test_eddasolver_stormdrain_hook_missing_topology_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_STORMDRAIN", "1")
    solver = _solver_with_staged_stormdrain_inputs(tmp_path)
    solver.configure_stormdrain_runtime_hook(drainage_path=str(tmp_path / "missing.txt"))

    before_fhpredi2 = solver.fields.fhpredi2.to_numpy().copy()
    manifest = solver.apply_stormdrain_runtime_hook(dt=1.0e-5)

    assert manifest["stormdrain_runtime_enabled"] is True
    assert manifest["stormdrain_branch_active"] is False
    assert manifest["fail_closed"] is True
    assert "missing drainage topology" in manifest["blocked_reason"]
    assert manifest["dfs_connectivity_changed"] is False
    np.testing.assert_allclose(solver.fields.fhpredi2.to_numpy(), before_fhpredi2)
