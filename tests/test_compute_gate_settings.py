from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.compute_gate_defaults import (
    compute_gate_baseline,
    merge_compute_gate_defaults,
    strip_gate_parameters,
)
from tests.test_workbench_domain_api import _create_project


def test_merge_compute_gate_defaults_prefers_global_gates_then_non_gate_patch() -> None:
    baseline = {
        "time.t_end": 100.0,
        "edda.run_controls.simulate_rainfall": True,
        "hydrology.dfs_face_flux_variant": "both_thin_weighted",
    }
    patch = {
        "time.t_end": 200.0,
        "edda.run_controls.simulate_rainfall": False,
        "hydrology.dfs_face_flux_variant": "asymmetric_head_guard",
    }
    gates = {
        "edda.run_controls.simulate_rainfall": False,
        "hydrology.dfs_face_flux_variant": "arithmetic_mean_chamoli",
    }
    merged = merge_compute_gate_defaults(baseline, patch, gates)
    assert merged["time.t_end"] == 200.0
    assert merged["edda.run_controls.simulate_rainfall"] is False
    assert merged["hydrology.dfs_face_flux_variant"] == "arithmetic_mean_chamoli"
    assert "edda.run_controls.simulate_rainfall" not in strip_gate_parameters(patch)


def test_compute_gates_settings_round_trip_and_scenario_merge(tmp_path: Path) -> None:
    project_root = tmp_path / "project-gates"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        empty = client.get("/api/settings/compute-gates")
        assert empty.status_code == 200
        body = empty.json()
        assert body["values"] == {}
        assert "hydrology.dfs_face_flux_variant" not in body["effective"]
        assert "hydrology.dfs_failure_source_policy" not in body["values"]
        assert body["baseline"]["hydrology.dfs_face_flux_variant"] == compute_gate_baseline()["hydrology.dfs_face_flux_variant"]

        written = client.put(
            "/api/settings/compute-gates",
            json={
                "values": {
                    "hydrology.dfs_face_flux_variant": "arithmetic_mean_chamoli",
                    "boundary_conditions.default_type": "wall",
                    "edda.run_controls.simulate_rainfall": False,
                }
            },
        )
        assert written.status_code == 200
        assert written.json()["values"]["hydrology.dfs_face_flux_variant"] == "arithmetic_mean_chamoli"
        assert written.json()["effective"]["boundary_conditions.default_type"] == "wall"

        invalid = client.put(
            "/api/settings/compute-gates",
            json={"values": {"hydrology.dfs_face_flux_variant": "not_a_real_variant"}},
        )
        assert invalid.status_code == 422

        project = _create_project(client, project_root)
        scenario = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "Gate merge", "parameter_patch": {"time.t_end": 12.0, "edda.run_controls.simulate_rainfall": True}},
        )
        assert scenario.status_code == 201
        created = scenario.json()
        assert "edda.run_controls.simulate_rainfall" not in created["parameter_patch"]
        assert created["parameter_patch"]["time.t_end"] == 12.0
        assert created["effective_parameters"]["edda.run_controls.simulate_rainfall"] is False
        assert created["effective_parameters"]["hydrology.dfs_face_flux_variant"] == "arithmetic_mean_chamoli"
        configuration = client.get(
            f"/api/projects/{project['project_id']}/scenarios/{created['scenario_id']}/configuration"
        )
        assert configuration.status_code == 200
        body = configuration.json()
        assert body["effective"]["boundary_conditions.default_type"] == "wall"
        assert body["compute_policy_resolution"]["requested"] == "auto"
        assert "effective" in body["compute_policy_resolution"]

        restricted = client.put(
            "/api/settings/compute-gates",
            json={"values": {"edda.run_controls.simulate_debris_flow": False}},
        )
        assert restricted.status_code == 422
        assert restricted.json()["code"] == "parameter_not_editable"

        live = client.put(
            "/api/settings/compute-gates",
            json={
                "values": {
                    "hydrology.dfs_failure_source_policy": "live",
                    "experimental.enable_live_doublelayer_in_dfs": True,
                }
            },
        )
        assert live.status_code == 200
        locked = client.put(
            "/api/settings/compute-gates",
            json={"values": {"experimental.enable_live_doublelayer_in_dfs": False}},
        )
        assert locked.status_code == 422
        assert locked.json()["code"] == "live_unlock_required"


def test_enqueue_accepts_cpu_runtime_profile(tmp_path: Path) -> None:
    from tests.test_workbench_domain_api import _create_ready_scenario

    project_root = tmp_path / "project-runtime"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root)
        scenario = _create_ready_scenario(client, project, "cpu-run")
        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"], "runtime_profile": "compat_default_off"},
        )
        assert queued.status_code == 201
        assert queued.json()["runtime_profile"] == "compat_default_off"

        rejected = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"], "runtime_profile": "blocked"},
        )
        assert rejected.status_code in {409, 422}
