from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario


def _completed_run(client: TestClient, project: dict, scenario: dict) -> str:
    queued = client.post(
        f"/api/projects/{project['project_id']}/queue",
        json={"scenario_id": scenario["scenario_id"]},
    ).json()
    client.post(f"/api/projects/{project['project_id']}/queue/start", json={})
    store = client.app.state.workbench
    context = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
    store.finish_run(project["project_id"], context["simulation_id"], {"status": "completed", "progress": 100})
    return str(context["simulation_id"])


def test_realtime_routes_publish_final_snapshots_and_remove_old_route(tmp_path: Path) -> None:
    app = create_app(state_dir=tmp_path / "state", scheduler_enabled=False)
    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "project", "Realtime")
        scenario = _create_ready_scenario(client, project, "Realtime scenario")
        simulation_id = _completed_run(client, project, scenario)

        with client.websocket_connect(f"/ws/simulations/{simulation_id}") as socket:
            message = socket.receive_json()
            assert message["type"] == "simulation_snapshot"
            assert message["simulation"]["status"] == "completed"

        with client.websocket_connect(f"/ws/projects/{project['project_id']}/queue") as socket:
            message = socket.receive_json()
            assert message["type"] == "queue_snapshot"
            assert message["items"][0]["status"] == "completed"

        assert client.get(f"/ws/simulation/{simulation_id}").status_code == 404
