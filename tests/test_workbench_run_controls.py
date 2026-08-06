from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient

from api.app import create_app
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario
from tests.test_workbench_scheduler import BlockingRunExecutor


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


def test_stop_active_run_then_retry_creates_a_new_queue_item(tmp_path: Path) -> None:
    executor = BlockingRunExecutor()
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=True,
        run_executor=executor,
        scheduler_poll_interval=0.01,
        max_concurrent_projects=2,
    )
    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "project", "Controls")
        scenario = _create_ready_scenario(client, project, "Control scenario")
        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        ).json()
        assert client.post(f"/api/projects/{project['project_id']}/queue/start", json={}).status_code == 200
        _wait_for(lambda: client.get(f"/api/projects/{project['project_id']}/queue").json()["items"][0]["status"] == "running")
        simulation = client.get(f"/api/projects/{project['project_id']}/simulations").json()["simulations"][0]

        stopped = client.post(f"/api/simulations/{simulation['simulation_id']}/stop")
        assert stopped.status_code == 200
        _wait_for(lambda: client.get(f"/api/projects/{project['project_id']}/queue").json()["items"][0]["status"] == "stopped")

        retry = client.post(
            f"/api/projects/{project['project_id']}/queue/{queued['queue_item_id']}/retry"
        )
        assert retry.status_code == 201
        assert client.post(f"/api/projects/{project['project_id']}/queue/start", json={}).status_code == 200
        executor.release.set()
        _wait_for(
            lambda: all(
                item["status"] == "completed"
                for item in client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
                if item["queue_item_id"] != queued["queue_item_id"]
            )
        )
        items = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        assert len(items) == 2
        assert items[0]["queue_item_id"] == queued["queue_item_id"]
        assert items[1]["retry_of"] == queued["queue_item_id"]
