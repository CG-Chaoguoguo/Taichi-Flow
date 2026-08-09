from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


def _create_project(client: TestClient, root: Path, name: str = "Slope study") -> dict:
    response = client.post(
        "/api/projects",
        json={"name": name, "root_path": str(root), "description": "test project"},
    )
    assert response.status_code == 201
    return response.json()


def _create_ready_scenario(client: TestClient, project: dict, name: str) -> dict:
    dem = client.post(
        f"/api/projects/{project['project_id']}/uploads/dem",
        files={"file": (f"{name}.asc", b"ncols 1\nnrows 1\ncellsize 1\n1\n", "text/plain")},
    )
    assert dem.status_code == 201
    revision = client.post(
        f"/api/projects/{project['project_id']}/input-revisions",
        json={"upload_ids": [dem.json()["upload_id"]]},
    )
    assert revision.status_code == 201
    scenario = client.post(
        f"/api/projects/{project['project_id']}/scenarios",
        json={"name": name, "input_revision_id": revision.json()["revision_id"]},
    )
    assert scenario.status_code == 201
    return scenario.json()


def test_project_catalog_survives_application_restart(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    project_root = tmp_path / "project-a"

    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        response = client.post(
            "/api/projects",
            json={
                "name": "Slope study",
                "root_path": str(project_root),
                "description": "persistent catalog contract",
            },
        )
        assert response.status_code == 201
        created = response.json()
        assert created["name"] == "Slope study"
        assert created["root_path"] == str(project_root.resolve())
        assert (project_root / ".taichi-flow" / "state.sqlite3").exists()

    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        response = client.get("/api/projects")
        assert response.status_code == 200
        assert response.json() == {"projects": [created], "count": 1}

        detail = client.get(f"/api/projects/{created['project_id']}")
        assert detail.status_code == 200
        assert detail.json() == created

        assert client.get("/api/projects/list").status_code == 404
        assert client.get("/api/simulation/list").status_code == 404


def test_content_addressed_revision_and_evidence_gated_scenario(tmp_path: Path) -> None:
    project_root = tmp_path / "project-inputs"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root)
        upload_url = f"/api/projects/{project['project_id']}/uploads/dem"
        payload = b"ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1 2\n3 4\n"

        first = client.post(upload_url, files={"file": ("dem.asc", payload, "text/plain")})
        second = client.post(upload_url, files={"file": ("dem-copy.asc", payload, "text/plain")})
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["sha256"] == second.json()["sha256"]
        assert first.json()["deduplicated"] is False
        assert second.json()["deduplicated"] is True

        revision_response = client.post(
            f"/api/projects/{project['project_id']}/input-revisions",
            json={"version_tag": "v1", "upload_ids": [first.json()["upload_id"]]},
        )
        assert revision_response.status_code == 201
        revision = revision_response.json()
        assert revision["status"] == "ready"
        assert revision["file_count"] == 1
        assert client.post(
            f"/api/projects/{project['project_id']}/input-revisions/{revision['revision_id']}/validate"
        ).json()["valid"] is True

        scenario_response = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={
                "name": "Manning variant",
                "input_revision_id": revision["revision_id"],
                "parameter_patch": {"rheology.n_manning": 0.04},
            },
        )
        assert scenario_response.status_code == 201
        scenario = scenario_response.json()
        assert scenario["parameter_patch"] == {"rheology.n_manning": 0.04}
        assert scenario["effective_parameters"]["rheology.n_manning"] == 0.04
        assert scenario["effective_parameters"]["edda.registry_version"] == "1.0.0"
        assert scenario["effective_parameters"]["edda.run_controls.simulate_rainfall"] is True

        rejected = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={"parameter_patch": {"rheology.unproven_parameter": 99}},
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "parameter_not_editable"


def test_edda_compute_controls_round_trip_through_scenario_public_api(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "compute-controls")
        created = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "EDDA control variant"},
        )
        assert created.status_code == 201
        scenario = created.json()
        assert scenario["parameter_template_id"] == "pt-bj-hxl-v3"
        assert scenario["parameter_baseline"]["edda.registry_version"] == "1.0.0"
        assert sum(
            key.startswith(("edda.run_controls.", "edda.output_controls."))
            for key in scenario["parameter_baseline"]
        ) == 45

        patch = {
            "edda.run_controls.simulate_rainfall": False,
            "edda.output_controls.save_flow_depth": False,
        }
        saved = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={"parameter_patch": patch, "expected_version": scenario["version"]},
        )
        assert saved.status_code == 200
        assert saved.json()["parameter_patch"] == patch
        assert saved.json()["effective_parameters"]["edda.run_controls.simulate_rainfall"] is False
        assert saved.json()["effective_parameters"]["edda.output_controls.save_flow_depth"] is False
        assert saved.json()["effective_parameters"]["edda.output_controls.save_max_flow_depth"] is True

        configuration = client.get(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}/configuration"
        )
        assert configuration.status_code == 200
        assert configuration.json()["overrides"] == patch
        assert configuration.json()["effective"]["edda.run_controls.simulate_rainfall"] is False

        restricted = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={
                "parameter_patch": {
                    "edda.run_controls.simulate_debris_flow": False,
                },
                "expected_version": saved.json()["version"],
            },
        )
        assert restricted.status_code == 422
        assert restricted.json()["code"] == "parameter_not_editable"


def test_queue_order_cancel_retry_and_restart_persistence(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    project_root = tmp_path / "queue-project"
    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        project = _create_project(client, project_root)
        scenario_a = _create_ready_scenario(client, project, "Scenario A")
        scenario_b = _create_ready_scenario(client, project, "Scenario B")
        queue_url = f"/api/projects/{project['project_id']}/queue"

        first = client.post(queue_url, json={"scenario_id": scenario_a["scenario_id"]})
        second = client.post(queue_url, json={"scenario_id": scenario_b["scenario_id"]})
        assert first.status_code == 201
        assert second.status_code == 201
        assert [item["position"] for item in client.get(queue_url).json()["items"]] == [1, 2]

        reordered = client.patch(
            f"{queue_url}/order",
            json={"item_id": second.json()["queue_item_id"], "new_position": 1},
        )
        assert reordered.status_code == 200
        assert reordered.json()["items"][0]["queue_item_id"] == second.json()["queue_item_id"]

        cancelled = client.delete(f"{queue_url}/{first.json()['queue_item_id']}")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        retried = client.post(f"{queue_url}/{first.json()['queue_item_id']}/retry")
        assert retried.status_code == 201
        assert retried.json()["retry_of"] == first.json()["queue_item_id"]
        assert retried.json()["status"] == "queued"

    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        persisted = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        assert {item["status"] for item in persisted} == {"queued", "cancelled"}
        assert any(item["retry_of"] == first.json()["queue_item_id"] for item in persisted)
