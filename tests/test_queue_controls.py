from __future__ import annotations

from pathlib import Path
from threading import Event, Lock
from time import monotonic, sleep

from fastapi.testclient import TestClient

from api.app import create_app
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario


class QueueControlExecutor:
    def __init__(self) -> None:
        self.release = Event()
        self.started = Event()
        self.lock = Lock()
        self.started_contexts: list[str] = []

    def signature(self, context: dict) -> str:
        return "queue-control-test"

    def request_stop(self, simulation_id: str) -> None:
        return None

    def execute(self, context: dict, on_update, stop_event: Event) -> dict:
        with self.lock:
            self.started_contexts.append(str(context["queue_item_id"]))
            self.started.set()
        on_update({"status": "running", "progress": 10.0})
        while not self.release.wait(0.01):
            if stop_event.is_set():
                return {"status": "stopped", "progress": 10.0, "resource_summary": {"children": 0}}
        return {"status": "completed", "progress": 100.0, "resource_summary": {"children": 0}}


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


def test_enqueue_stages_waiting_until_explicit_batch_start(tmp_path: Path) -> None:
    executor = QueueControlExecutor()
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=True,
        run_executor=executor,
        scheduler_poll_interval=0.01,
    )
    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "project", "Queue controls")
        scenario_a = _create_ready_scenario(client, project, "A")
        scenario_b = _create_ready_scenario(client, project, "B")
        queue_url = f"/api/projects/{project['project_id']}/queue"

        first = client.post(queue_url, json={"scenario_id": scenario_a["scenario_id"]})
        assert first.status_code == 201
        assert first.json()["status"] == "waiting"
        sleep(0.15)
        assert executor.started_contexts == []

        started = client.post(f"{queue_url}/start", json={})
        assert started.status_code == 200
        assert started.json()["started_item_ids"] == [first.json()["queue_item_id"]]
        assert executor.started.wait(5.0)

        second = client.post(queue_url, json={"scenario_id": scenario_b["scenario_id"]})
        assert second.status_code == 201
        assert second.json()["status"] == "waiting"
        assert next(item for item in client.get(queue_url).json()["items"] if item["queue_item_id"] == second.json()["queue_item_id"])["status"] == "waiting"

        executor.release.set()
        _wait_for(
            lambda: next(item for item in client.get(queue_url).json()["items"] if item["queue_item_id"] == first.json()["queue_item_id"])["status"] == "completed"
        )
        assert next(item for item in client.get(queue_url).json()["items"] if item["queue_item_id"] == second.json()["queue_item_id"])["status"] == "waiting"


def test_queue_delete_and_reorder_are_transactional(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Queue delete")
        scenarios = [_create_ready_scenario(client, project, name) for name in ("A", "B", "C")]
        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = [client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json() for scenario in scenarios]

        reordered = client.patch(
            f"{queue_url}/order",
            json={"item_id": queued[2]["queue_item_id"], "new_position": 1},
        )
        assert reordered.status_code == 200
        waiting = [item for item in reordered.json()["items"] if item["status"] == "waiting"]
        assert [item["scenario_name"] for item in waiting] == ["C", "A", "B"]

        started = client.post(f"{queue_url}/start", json={})
        assert started.status_code == 200
        next_scenario = _create_ready_scenario(client, project, "D")
        next_item = client.post(queue_url, json={"scenario_id": next_scenario["scenario_id"]}).json()
        locked = client.patch(
            f"{queue_url}/order",
            json={"item_id": next_item["queue_item_id"], "new_position": 1},
        )
        assert locked.status_code == 409
        assert locked.json()["code"] == "queue_order_locked"

        preview = client.post(
            f"{queue_url}/delete-preview",
            json={"queue_item_ids": [queued[0]["queue_item_id"]]},
        )
        assert preview.status_code == 200
        deleted = client.post(
            f"{queue_url}/batch-delete",
            json={"queue_item_ids": [queued[0]["queue_item_id"]]},
        )
        assert deleted.status_code == 200
        assert queued[0]["queue_item_id"] not in {item["queue_item_id"] for item in deleted.json()["items"]}


def test_deleting_terminal_queue_record_keeps_latest_scenario_state(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project", "Queue terminal retention")
        scenario = _create_ready_scenario(client, project, "Completed")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]}).json()
        client.post(f"{queue_url}/start", json={})
        store = client.app.state.workbench
        claimed = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
        store.finish_run(project["project_id"], claimed["simulation_id"], {"status": "completed"})
        deleted = client.post(
            f"{queue_url}/batch-delete",
            json={"queue_item_ids": [queued["queue_item_id"]]},
        )
        assert deleted.status_code == 200
        latest = client.get(f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}")
        assert latest.status_code == 200
        assert latest.json()["status"] == "completed"
