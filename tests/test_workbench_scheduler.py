from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from threading import Event, Lock
from time import monotonic, sleep

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.workbench_store import ProjectDatabase
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario


class BlockingRunExecutor:
    def __init__(self) -> None:
        self.release = Event()
        self.two_projects_started = Event()
        self.lock = Lock()
        self.active_global = 0
        self.active_by_project: dict[str, int] = defaultdict(int)
        self.max_global = 0
        self.max_by_project: dict[str, int] = defaultdict(int)

    def signature(self, context: dict) -> str:
        return "test-compatible-runtime"

    def request_stop(self, simulation_id: str) -> None:
        return None

    def execute(self, context: dict, on_update, stop_event: Event) -> dict:
        project_id = context["project_id"]
        with self.lock:
            self.active_global += 1
            self.active_by_project[project_id] += 1
            self.max_global = max(self.max_global, self.active_global)
            self.max_by_project[project_id] = max(
                self.max_by_project[project_id], self.active_by_project[project_id]
            )
            if self.active_global == 2:
                self.two_projects_started.set()
        on_update({"status": "running"})
        on_update({"progress": 25.0, "current_time": 1.0, "output_count": 1})
        while not self.release.wait(0.01):
            if stop_event.is_set():
                result = {"status": "stopped", "progress": 25.0, "resource_summary": {"children": 0}}
                break
        else:
            result = {"status": "completed", "progress": 100.0, "resource_summary": {"children": 0}}
        with self.lock:
            self.active_global -= 1
            self.active_by_project[project_id] -= 1
        return result


class BurstingRunExecutor:
    def signature(self, context: dict) -> str:
        return "test-compatible-runtime"

    def request_stop(self, simulation_id: str) -> None:
        return None

    def execute(self, context: dict, on_update, stop_event: Event) -> dict:
        on_update({"status": "running", "progress": 0.0, "current_time": 0.0})
        for step in range(1, 251):
            on_update(
                {
                    "progress": step / 2.5,
                    "current_time": float(step),
                    "step_count": step,
                    "output_count": step // 100,
                }
            )
        return {
            "status": "completed",
            "progress": 100.0,
            "current_time": 250.0,
            "step_count": 250,
            "output_count": 2,
            "resource_summary": {"children": 0},
        }


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


def test_scheduler_serializes_each_project_and_runs_two_projects_concurrently(tmp_path: Path) -> None:
    executor = BlockingRunExecutor()
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=True,
        run_executor=executor,
        scheduler_poll_interval=0.01,
        max_concurrent_projects=2,
    )
    with TestClient(app) as client:
        project_a = _create_project(client, tmp_path / "project-a", "Project A")
        project_b = _create_project(client, tmp_path / "project-b", "Project B")
        scenario_a1 = _create_ready_scenario(client, project_a, "A1")
        scenario_a2 = _create_ready_scenario(client, project_a, "A2")
        scenario_b1 = _create_ready_scenario(client, project_b, "B1")

        for project, scenario in (
            (project_a, scenario_a1),
            (project_a, scenario_a2),
            (project_b, scenario_b1),
        ):
            response = client.post(
                f"/api/projects/{project['project_id']}/queue",
                json={"scenario_id": scenario["scenario_id"]},
            )
            assert response.status_code == 201

        assert client.post(f"/api/projects/{project_a['project_id']}/queue/start", json={}).status_code == 200
        assert client.post(f"/api/projects/{project_b['project_id']}/queue/start", json={}).status_code == 200

        assert executor.two_projects_started.wait(5.0)
        _wait_for(
            lambda: all(
                next(item for item in client.get(f"/api/projects/{project_id}/queue").json()["items"] if item["status"] == "running")["progress"] == 25.0
                for project_id in (project_a["project_id"], project_b["project_id"])
            )
        )
        queue_a = client.get(f"/api/projects/{project_a['project_id']}/queue").json()["items"]
        queue_b = client.get(f"/api/projects/{project_b['project_id']}/queue").json()["items"]
        assert [item["status"] for item in queue_a].count("running") == 1
        assert [item["status"] for item in queue_a].count("queued") == 1
        assert [item["status"] for item in queue_b].count("running") == 1
        assert next(item for item in queue_a if item["status"] == "running")["progress"] == 25.0
        assert next(item for item in queue_b if item["status"] == "running")["progress"] == 25.0
        assert executor.max_global == 2
        assert max(executor.max_by_project.values()) == 1

        blocked = client.patch(
            f"/api/projects/{project_a['project_id']}/scenarios/{scenario_a1['scenario_id']}",
            json={"name": "must remain locked while running"},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["code"] == "scenario_run_active"

        executor.release.set()
        _wait_for(
            lambda: all(
                item["status"] == "completed"
                for item in client.get(f"/api/projects/{project_a['project_id']}/queue").json()["items"]
                + client.get(f"/api/projects/{project_b['project_id']}/queue").json()["items"]
            )
        )

        editable = client.patch(
            f"/api/projects/{project_a['project_id']}/scenarios/{scenario_a1['scenario_id']}",
            json={"name": "edited after completion"},
        )
        assert editable.status_code == 200, editable.text
        edited = editable.json()
        assert edited["name"] == "edited after completion"
        assert edited["status"] == "draft"
        assert edited["input_revision_id"] is None
        assert edited["latest_simulation_id"]


def test_editing_unclaimed_queue_item_updates_its_version_and_keeps_order(tmp_path: Path) -> None:
    app = create_app(state_dir=tmp_path / "state", scheduler_enabled=False)
    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "project")
        first = _create_ready_scenario(client, project, "First")
        second = _create_ready_scenario(client, project, "Second")
        first_item = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": first["scenario_id"]},
        ).json()
        second_item = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": second["scenario_id"]},
        ).json()

        saved = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{first['scenario_id']}",
            json={
                "expected_version": first["version"],
                "name": "First edited while waiting",
                "parameter_patch": {"time.t_end": 7200},
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "waiting"

        items = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        first_after = next(item for item in items if item["queue_item_id"] == first_item["queue_item_id"])
        second_after = next(item for item in items if item["queue_item_id"] == second_item["queue_item_id"])
        assert first_after["status"] == "waiting"
        assert first_after["scenario_version"] == saved.json()["version"]
        assert first_after["input_revision_id"] is None
        assert first_after["queue_order"] < second_after["queue_order"]

        assert client.post(f"/api/projects/{project['project_id']}/queue/start", json={}).status_code == 200
        queued_edit = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{first['scenario_id']}",
            json={
                "expected_version": saved.json()["version"],
                "parameter_patch": {"time.t_end": 10800},
            },
        )
        assert queued_edit.status_code == 200, queued_edit.text
        queued_items = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        first_queued = next(item for item in queued_items if item["queue_item_id"] == first_item["queue_item_id"])
        assert first_queued["status"] == "queued"
        assert first_queued["scenario_version"] == queued_edit.json()["version"]
        assert first_queued["queue_order"] < next(item for item in queued_items if item["queue_item_id"] == second_item["queue_item_id"])["queue_order"]


def test_scheduler_persists_progress_only_at_output_boundaries(tmp_path: Path) -> None:
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=True,
        run_executor=BurstingRunExecutor(),
        scheduler_poll_interval=0.01,
    )
    persisted_updates: list[dict] = []
    original_update_run = app.state.workbench.update_run

    def counted_update_run(project_id: str, simulation_id: str, values: dict) -> None:
        persisted_updates.append(dict(values))
        original_update_run(project_id, simulation_id, values)

    app.state.workbench.update_run = counted_update_run

    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "project", "Burst project")
        scenario = _create_ready_scenario(client, project, "Burst scenario")
        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201
        assert client.post(f"/api/projects/{project['project_id']}/queue/start", json={}).status_code == 200

        _wait_for(
            lambda: client.get(
                f"/api/projects/{project['project_id']}/queue"
            ).json()["items"][0]["status"]
            == "completed",
            timeout=15.0,
        )

    progress_updates = [
        update for update in persisted_updates if "step_count" in update
    ]

    assert len(persisted_updates) == 4
    assert any(update.get("status") == "running" for update in persisted_updates)
    assert [update["output_count"] for update in progress_updates] == [1, 2]
    assert [update["step_count"] for update in progress_updates] == [100, 200]


def test_failed_run_persists_structured_semantic_error(tmp_path: Path) -> None:
    app = create_app(state_dir=tmp_path / "state", scheduler_enabled=False)
    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "project", "Structured failure")
        scenario = _create_ready_scenario(client, project, "Semantic gate")
        store = client.app.state.workbench
        simulation_id = "sim-structured-semantic-error"
        database = store.project_database(project["project_id"])
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO simulation_runs(simulation_id, scenario_id, status, created_at)
                VALUES(?, ?, 'running', '2026-08-09T00:00:00+00:00')
                """,
                (simulation_id, scenario["scenario_id"]),
            )
        store.finish_run(
            project["project_id"],
            simulation_id,
            {
                "status": "failed",
                "error": "validated UNSFIN schedule required",
                "error_code": "edda_unsfin_schedule_required",
                "error_details": {
                    "control": "simulate_shallow_landslide",
                    "configured_value": True,
                },
            },
        )

        simulation = store.public_simulation(
            project["project_id"],
            store.simulation_row(project["project_id"], simulation_id),
        )

        assert simulation["error_code"] == "edda_unsfin_schedule_required"
        assert simulation["error_details"] == {
            "control": "simulate_shallow_landslide",
            "configured_value": True,
        }


def test_schema_v7_queue_lineage_migrates_structured_error_columns(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "legacy-v7-queue-project")
    database.initialize(
        project_id="prj-legacy-v7-queue",
        name="Legacy v7 queue lineage",
        description="migration fixture",
        created_at="2026-08-09T00:00:00+00:00",
    )
    with database.connect() as connection:
        connection.execute("ALTER TABLE simulation_runs DROP COLUMN error_details_json")
        connection.execute("ALTER TABLE simulation_runs DROP COLUMN error_code")
        connection.execute(
            "UPDATE schema_metadata SET value='7' WHERE key='schema_version'"
        )

    database.ensure_schema()

    with database.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(simulation_runs)").fetchall()
        }
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()["value"]

    assert {"error_code", "error_details_json"} <= columns
    assert version == "8"


def test_schema_v7_error_lineage_migrates_queue_columns(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "legacy-v7-error-project")
    database.initialize(
        project_id="prj-legacy-v7-error",
        name="Legacy v7 error lineage",
        description="migration fixture",
        created_at="2026-08-09T00:00:00+00:00",
    )
    with database.connect() as connection:
        connection.execute("DROP INDEX IF EXISTS idx_queue_items_order")
        connection.execute("ALTER TABLE queue_items DROP COLUMN deleted_at")
        connection.execute("ALTER TABLE queue_items DROP COLUMN queue_order")
        connection.execute(
            "UPDATE schema_metadata SET value='7' WHERE key='schema_version'"
        )

    database.ensure_schema()

    with database.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(queue_items)").fetchall()
        }
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()["value"]

    assert {"queue_order", "deleted_at"} <= columns
    assert version == "8"
