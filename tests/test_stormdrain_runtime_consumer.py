from pathlib import Path

import pytest

from edda.io.stormdrain_reader import (
    STORMDRAIN_LOW_DEPTH_WEIR_COEFF,
    load_stormdrain_topology,
    run_stormdrain_runtime_consumer,
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


def test_stormdrain_topology_loader_validates_original_drainage_schema(tmp_path):
    drainage = _write_minimal_drainage(tmp_path / "drainage.txt")

    topology = load_stormdrain_topology(drainage, imax=4)

    assert topology.node_count == 2
    assert topology.conduit_count == 1
    assert topology.nodes[0].nodeindex == 1
    assert topology.nodes[1].nodetype == 1
    assert topology.conduits[0].inlet_node == 1
    assert topology.conduits[0].outlet_node == 2


def test_stormdrain_runtime_consumer_flag_off_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv("EDDA_EXPERIMENT_STORMDRAIN", raising=False)
    drainage = _write_minimal_drainage(tmp_path / "drainage.txt")

    manifest = run_stormdrain_runtime_consumer(
        drainage_path=drainage,
        imax=4,
        fhpredi2=[0.0, 0.1, 0.0, 0.0, 0.0],
        cell_area=100.0,
        dt=1.0e-5,
    )

    assert manifest["stormdrain_runtime_enabled"] is False
    assert manifest["stormdrain_branch_active"] is False
    assert manifest["changed_field_names"] == []
    assert manifest["node_exchange"] == []
    assert manifest["default_off_verified"] is True


def test_stormdrain_runtime_consumer_flag_on_matches_source_node_exchange(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_STORMDRAIN", "1")
    drainage = _write_minimal_drainage(tmp_path / "drainage.txt")
    fh = 3.8787900000000005e-11
    dt = 1.0e-5
    cell_area = 100.0

    manifest = run_stormdrain_runtime_consumer(
        drainage_path=drainage,
        imax=4,
        fhpredi2=[0.0, fh, 0.0, 0.0, 0.0],
        cell_area=cell_area,
        dt=dt,
        expected_node_count=2,
        expected_conduit_count=1,
    )

    expected_flow = fh ** 1.5 * STORMDRAIN_LOW_DEPTH_WEIR_COEFF
    expected_after = fh - expected_flow * dt / cell_area
    assert manifest["stormdrain_runtime_enabled"] is True
    assert manifest["stormdrain_branch_active"] is True
    assert manifest["topology_loaded"] is True
    assert manifest["node_count"] == 2
    assert manifest["conduit_count"] == 1
    assert manifest["changed_field_names"] == ["stormdrain_fhpredi2"]
    first = manifest["node_exchange"][0]
    assert first["event"] == "surface_to_node_pre_dwflow"
    assert first["newlatflow"] == pytest.approx(expected_flow)
    assert first["voltonode_step_volume"] == pytest.approx(expected_flow * dt)
    assert first["fh_after_removal"] == pytest.approx(expected_after)
    assert manifest["dwflow_nodes"][0]["ninflow_m3s"] == pytest.approx(expected_flow)
    assert manifest["balance"]["tempnodeinflowvol_m3"] == pytest.approx(expected_flow * dt)
    assert float(manifest["fh_after_by_cell"]["1"]) == pytest.approx(expected_after)


def test_stormdrain_runtime_consumer_flag_on_missing_topology_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_STORMDRAIN", "1")

    manifest = run_stormdrain_runtime_consumer(
        drainage_path=tmp_path / "missing_drainage.txt",
        imax=4,
        fhpredi2=[0.0, 0.1, 0.0, 0.0, 0.0],
        cell_area=100.0,
        dt=1.0e-5,
    )

    assert manifest["stormdrain_runtime_enabled"] is True
    assert manifest["stormdrain_branch_active"] is False
    assert manifest["fail_closed"] is True
    assert "missing drainage topology" in manifest["blocked_reason"]
    assert manifest["changed_field_names"] == []


def test_stormdrain_runtime_consumer_flag_on_loads_copied_20a_oracle_topology(monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_STORMDRAIN", "1")
    oracle_root = (
        Path(__file__).resolve().parents[1]
        / "PROJECT_REPORTS"
        / "agent_runs"
        / "2026-05-05"
        / "phase_stormdrain_phase_local_20a_coordinate_compatible_swmm_oracle"
    )
    drainage = oracle_root / "04_instrumented_original_run" / "run_workspace_instrumented" / "drainage.txt"

    manifest = run_stormdrain_runtime_consumer(
        drainage_path=drainage,
        imax=141180,
        expected_node_count=64,
        expected_conduit_count=54,
    )

    assert manifest["stormdrain_runtime_enabled"] is True
    assert manifest["stormdrain_branch_active"] is True
    assert manifest["drainage_topology_validated"] is True
    assert manifest["fail_closed"] is False
    assert manifest["changed_field_names"] == []
    assert manifest["node_count"] == 64
    assert manifest["conduit_count"] == 54
    assert manifest["oracle_comparable_metrics"]["readdrainage_nodes_rows"] == 64
    assert manifest["oracle_comparable_metrics"]["readdrainage_conduits_rows"] == 54
    assert manifest["topology_summary"]["junction_count"] == 54
    assert manifest["topology_summary"]["outfall_count"] == 10
