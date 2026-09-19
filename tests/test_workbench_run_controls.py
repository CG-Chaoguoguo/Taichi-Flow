from __future__ import annotations

from itertools import count
from pathlib import Path
from time import monotonic, sleep
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.services import workbench_store
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario
from tests.test_workbench_scheduler import BlockingRunExecutor


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


@pytest.mark.parametrize("uuid_step", [1, -1])
def test_stop_active_run_then_retry_creates_a_new_queue_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uuid_step: int,
) -> None:
    uuid_values = count(1 if uuid_step > 0 else (2**128 - 1), uuid_step)
    monkeypatch.setattr(workbench_store, "uuid4", lambda: UUID(int=next(uuid_values)))
    monkeypatch.setattr(workbench_store, "utc_now", lambda: "2026-09-19T00:00:00+00:00")

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
        _wait_for(
            lambda: next(
                item
                for item in client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
                if item["queue_item_id"] == queued["queue_item_id"]
            )["status"]
            == "running"
        )
        simulation = client.get(f"/api/projects/{project['project_id']}/simulations").json()["simulations"][0]

        stopped = client.post(f"/api/simulations/{simulation['simulation_id']}/stop")
        assert stopped.status_code == 200
        _wait_for(
            lambda: next(
                item
                for item in client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
                if item["queue_item_id"] == queued["queue_item_id"]
            )["status"]
            == "stopped"
        )

        retry = client.post(
            f"/api/projects/{project['project_id']}/queue/{queued['queue_item_id']}/retry"
        )
        assert retry.status_code == 201
        retried = retry.json()
        assert retried["queue_item_id"] != queued["queue_item_id"]
        executor.release.set()
        _wait_for(
            lambda: next(
                item
                for item in client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
                if item["queue_item_id"] == retried["queue_item_id"]
            )["status"]
            == "completed"
        )
        items = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        assert len(items) == 2
        items_by_id = {item["queue_item_id"]: item for item in items}
        assert items_by_id[queued["queue_item_id"]]["status"] == "stopped"
        assert items_by_id[retried["queue_item_id"]]["status"] == "completed"
        assert items_by_id[retried["queue_item_id"]]["retry_of"] == queued["queue_item_id"]
