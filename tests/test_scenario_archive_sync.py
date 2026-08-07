from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario


def test_draft_preview_and_delete_are_physical(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Scenario delete")
        scenario = _create_ready_scenario(client, project, "Draft")
        preview_url = f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}/delete-preview"

        preview = client.post(preview_url)
        assert preview.status_code == 200
        assert preview.json() == {
            "scenario_id": scenario["scenario_id"],
            "disposition": "delete",
            "can_remove": True,
            "can_archive": True,
            "can_permanently_delete": True,
            "blocking_queue_item_ids": [],
            "active_simulation_ids": [],
            "run_count": 0,
            "result_family_count": 0,
            "queue_item_count": 0,
            "output_count": 0,
            "export_count": 0,
            "derived_scenario_count": 0,
            "preserves_history": False,
        }

        deleted = client.delete(f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}").status_code == 404


def test_terminal_history_archives_and_restores_without_losing_run(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Scenario archive")
        scenario = _create_ready_scenario(client, project, "Historical")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()
        assert queued["status"] == "waiting"
        assert client.post(f"{queue_url}/start", json={}).status_code == 200
        store = client.app.state.workbench
        claimed = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
        store.finish_run(project["project_id"], claimed["simulation_id"], {"status": "completed"})
        deleted = client.post(
            f"{queue_url}/batch-delete",
            json={"queue_item_ids": [queued["queue_item_id"]]},
        )
        assert deleted.status_code == 200

        scenario_url = f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        preview = client.post(f"{scenario_url}/delete-preview")
        assert preview.status_code == 200
        assert preview.json()["disposition"] == "archive"
        assert preview.json()["can_remove"] is True
        assert preview.json()["run_count"] == 1

        archived = client.post(f"{scenario_url}/archive")
        assert archived.status_code == 200
        assert archived.json()["archived"] is True
        assert archived.json()["status"] == "archived"
        rejected_enqueue = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert rejected_enqueue.status_code == 409
        assert rejected_enqueue.json()["code"] == "scenario_archived"
        preserved = client.get(f"/api/projects/{project['project_id']}/simulations/{claimed['simulation_id']}")
        assert preserved.status_code == 200
        assert preserved.json()["status"] == "completed"

        restored = client.post(f"{scenario_url}/restore")
        assert restored.status_code == 200
        assert restored.json()["archived"] is False
        assert restored.json()["status"] == "completed"
        requeued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert requeued.status_code == 201
        assert requeued.json()["status"] == "waiting"


def test_all_terminal_states_can_edit_parameters_and_bindings_without_mutating_history(tmp_path: Path) -> None:
    terminal_states = ("completed", "failed", "stopped", "interrupted", "cancelled")
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Terminal editability")
        store = client.app.state.workbench
        queue_url = f"/api/projects/{project['project_id']}/queue"

        for index, terminal_state in enumerate(terminal_states, start=1):
            scenario = _create_ready_scenario(client, project, f"Terminal {terminal_state}")
            queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()
            assert client.post(f"{queue_url}/start", json={}).status_code == 200
            claimed = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
            store.finish_run(project["project_id"], claimed["simulation_id"], {"status": terminal_state})

            edited = client.patch(
                f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
                json={
                    "expected_version": scenario["version"],
                    "name": f"Edited {terminal_state}",
                    "parameter_patch": {**scenario["parameter_patch"], "time.t_end": 3600 + index * 3600},
                    "input_bindings": scenario.get("input_bindings", []),
                },
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["status"] == "draft"
            assert edited.json()["latest_simulation_id"] == claimed["simulation_id"]
            historical = client.get(
                f"/api/projects/{project['project_id']}/simulations/{claimed['simulation_id']}"
            )
            assert historical.status_code == 200
            assert historical.json()["status"] == terminal_state


def test_archive_and_delete_preview_block_visible_queue_and_active_run(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Scenario blockers")
        scenario = _create_ready_scenario(client, project, "Blocked")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        scenario_url = f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()

        preview = client.post(f"{scenario_url}/delete-preview")
        assert preview.status_code == 200
        assert preview.json()["can_remove"] is False
        assert preview.json()["blocking_queue_item_ids"] == [queued["queue_item_id"]]
        blocked = client.post(f"{scenario_url}/archive")
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "scenario_in_queue"

        client.post(f"{queue_url}/start", json={})
        claimed = client.app.state.workbench.claim_queue_item(project["project_id"], queued["queue_item_id"])
        preview_active = client.post(f"{scenario_url}/delete-preview")
        assert preview_active.status_code == 200
        assert preview_active.json()["active_simulation_ids"] == [claimed["simulation_id"]]
        assert preview_active.json()["can_permanently_delete"] is False
        blocked_active = client.post(f"{scenario_url}/archive")
        assert blocked_active.status_code == 409
        assert blocked_active.json()["code"] == "scenario_in_queue"
        blocked_permanent = client.delete(f"{scenario_url}/permanent")
        assert blocked_permanent.status_code == 409
        assert blocked_permanent.json()["code"] == "scenario_run_active"


def test_permanent_delete_preview_and_waiting_cleanup(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Permanent delete")
        scenario = _create_ready_scenario(client, project, "Disposable")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        scenario_url = f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()

        preview = client.post(f"{scenario_url}/delete-preview")
        assert preview.status_code == 200
        payload = preview.json()
        assert payload["can_archive"] is False
        assert payload["can_remove"] is False
        assert payload["can_permanently_delete"] is True
        assert payload["queue_item_count"] == 1
        assert payload["output_count"] == 0
        assert payload["export_count"] == 0
        assert payload["derived_scenario_count"] == 0

        deleted = client.delete(f"{scenario_url}/permanent")
        assert deleted.status_code == 200
        assert deleted.json()["scenario_id"] == scenario["scenario_id"]
        assert deleted.json()["queue_item_count"] == 1
        assert client.get(scenario_url).status_code == 404
        assert client.get(queue_url).json()["items"] == []


def test_permanent_delete_purges_private_history_and_preserves_derived_inputs(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Permanent history")
        scenario = _create_ready_scenario(client, project, "Historical disposable")
        scenario_url = f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()
        assert client.post(f"{queue_url}/start").status_code == 200
        store = client.app.state.workbench
        claimed = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
        output_dir = Path(claimed["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "depth_0001.tif").write_bytes(b"result")
        store.update_run(project["project_id"], claimed["simulation_id"], {"output_count": 2})
        store.finish_run(project["project_id"], claimed["simulation_id"], {"status": "completed", "progress": 100})
        indexed = client.get(
            f"/api/projects/{project['project_id']}/results/{claimed['simulation_id']}"
        )
        assert indexed.status_code == 200
        exported = client.post(
            f"/api/projects/{project['project_id']}/exports",
            json={"simulation_id": claimed["simulation_id"], "families": [], "filenames": []},
        )
        assert exported.status_code == 202
        export_id = exported.json()["export_id"]
        derived = client.post(f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}/duplicate")
        assert derived.status_code == 201
        derived_id = derived.json()["scenario_id"]

        preview = client.post(f"{scenario_url}/delete-preview").json()
        assert preview["can_permanently_delete"] is True
        assert preview["queue_item_count"] == 1
        assert preview["run_count"] == 1
        assert preview["result_family_count"] == 1
        assert preview["output_count"] == 2
        assert preview["export_count"] == 1
        assert preview["derived_scenario_count"] == 1

        deleted = client.delete(f"{scenario_url}/permanent")
        assert deleted.status_code == 200
        assert deleted.json()["run_count"] == 1
        assert client.get(scenario_url).status_code == 404
        assert client.get(f"/api/projects/{project['project_id']}/simulations/{claimed['simulation_id']}").status_code == 404
        assert client.get(f"/api/projects/{project['project_id']}/exports/{export_id}").status_code == 404
        assert not output_dir.exists()
        assert not store.project_database(project["project_id"]).scenario_dir(scenario["scenario_id"]).exists()
        derived_after = client.get(f"/api/projects/{project['project_id']}/scenarios/{derived_id}")
        assert derived_after.status_code == 200
        assert derived_after.json()["base_scenario_id"] is None


def test_permanent_delete_rejects_output_path_escape_without_mutation(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Path safety")
        scenario = _create_ready_scenario(client, project, "Path guarded")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        scenario_url = f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()
        client.post(f"{queue_url}/start")
        store = client.app.state.workbench
        claimed = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
        store.finish_run(project["project_id"], claimed["simulation_id"], {"status": "completed"})
        outside = tmp_path / "outside-output"
        with store.project_database(project["project_id"]).connect() as connection:
            connection.execute(
                "UPDATE simulation_runs SET output_dir=? WHERE simulation_id=?",
                (str(outside), claimed["simulation_id"]),
            )

        blocked = client.delete(f"{scenario_url}/permanent")
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "scenario_path_invalid"
        assert client.get(scenario_url).status_code == 200
        assert store.project_database(project["project_id"]).scenario_dir(scenario["scenario_id"]).exists()
