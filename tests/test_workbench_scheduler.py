from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from threading import Event, Lock
from time import monotonic, sleep

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.scheduler import _RunProgressPersister
from api.services.workbench_store import ProjectDatabase, SCHEMA_VERSION
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
        on_update({"status": "running", "progress": 25.0, "current_time": 1.0})
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


class SignalRunExecutor:
    """Minimal executor used to prove a queued item is eventually admitted."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def signature(self, context: dict) -> str:
        return "test-compatible-runtime"

    def request_stop(self, simulation_id: str) -> None:
        self.release.set()

    def execute(self, context: dict, on_update, stop_event: Event) -> dict:
        self.started.set()
        on_update({"status": "running", "progress": 1.0, "current_time": 0.0})
        while not self.release.wait(0.01):
            if stop_event.is_set():
                return {"status": "stopped", "resource_summary": {"children": 0}}
        return {"status": "completed", "progress": 100.0, "resource_summary": {"children": 0}}


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

        assert executor.two_projects_started.wait(5.0)
        queue_a = client.get(f"/api/projects/{project_a['project_id']}/queue").json()["items"]
        queue_b = client.get(f"/api/projects/{project_b['project_id']}/queue").json()["items"]
        assert [item["status"] for item in queue_a].count("running") == 1
        assert [item["status"] for item in queue_a].count("queued") == 1
        assert [item["status"] for item in queue_b].count("running") == 1
        assert executor.max_global == 2
        assert max(executor.max_by_project.values()) == 1

        executor.release.set()
        _wait_for(
            lambda: all(
                item["status"] == "completed"
                for item in client.get(f"/api/projects/{project_a['project_id']}/queue").json()["items"]
                + client.get(f"/api/projects/{project_b['project_id']}/queue").json()["items"]
            )
        )

        immutable = client.patch(
            f"/api/projects/{project_a['project_id']}/scenarios/{scenario_a1['scenario_id']}",
            json={"name": "must not mutate"},
        )
        assert immutable.status_code == 409


def test_scheduler_recovers_after_transient_queue_scan_error(tmp_path: Path, monkeypatch) -> None:
    """A single store exception must not silently kill the dispatch loop."""
    executor = SignalRunExecutor()
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=True,
        run_executor=executor,
        scheduler_poll_interval=0.01,
    )
    with TestClient(app) as client:
        store = client.app.state.workbench
        original_queue_candidates = store.queue_candidates
        raised_once = False

        def raise_once(active_projects):
            nonlocal raised_once
            if not raised_once:
                raised_once = True
                raise RuntimeError("temporary queue scan failure")
            return original_queue_candidates(active_projects)

        monkeypatch.setattr(store, "queue_candidates", raise_once)
        project = _create_project(client, tmp_path / "transient-queue-project", "Transient queue")
        scenario = _create_ready_scenario(client, project, "Recover queue")
        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201

        assert executor.started.wait(5.0)
        assert raised_once is True
        executor.release.set()
        _wait_for(
            lambda: client.get(f"/api/projects/{project['project_id']}/queue").json()["items"][0]["status"]
            == "completed"
        )


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


def test_schema_v6_migrates_structured_error_columns(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "legacy-v6-project")
    database.initialize(
        project_id="prj-legacy-v6",
        name="Legacy v6",
        description="migration fixture",
        created_at="2026-08-09T00:00:00+00:00",
    )
    with database.connect() as connection:
        connection.execute("ALTER TABLE simulation_runs DROP COLUMN error_details_json")
        connection.execute("ALTER TABLE simulation_runs DROP COLUMN error_code")
        connection.execute(
            "UPDATE schema_metadata SET value='6' WHERE key='schema_version'"
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
    assert version == str(SCHEMA_VERSION)


def test_schema_v8_migrates_compute_policy_snapshot_columns(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "legacy-v8-project")
    database.initialize(
        project_id="prj-legacy-v8",
        name="Legacy v8",
        description="compute policy migration fixture",
        created_at="2026-08-25T00:00:00+00:00",
    )
    with database.connect() as connection:
        connection.execute("ALTER TABLE simulation_runs DROP COLUMN compute_policy_resolution_json")
        connection.execute("ALTER TABLE queue_items DROP COLUMN effective_config_json")
        connection.execute("ALTER TABLE queue_items DROP COLUMN compute_policy_resolution_json")
        connection.execute("UPDATE schema_metadata SET value='8' WHERE key='schema_version'")

    database.ensure_schema()

    with database.connect() as connection:
        simulation_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(simulation_runs)").fetchall()
        }
        queue_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(queue_items)").fetchall()
        }
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()["value"]

    assert "compute_policy_resolution_json" in simulation_columns
    assert {"effective_config_json", "compute_policy_resolution_json"} <= queue_columns
    assert version == str(SCHEMA_VERSION)


class _RecordingStore:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def persist(self, payload: dict) -> None:
        self.payloads.append(dict(payload))


def _emit_step_updates(persister: _RunProgressPersister, *, steps: int, output_every: int) -> None:
    persister.observe({"status": "running", "start_time": "2026-09-03T00:00:00+00:00"})
    for step in range(1, steps + 1):
        persister.observe({"progress": step * (100.0 / steps)})
        persister.observe({"current_time": float(step)})
        persister.observe({"step_count": step})
        persister.observe({"output_count": step // output_every})
    persister.observe(
        {
            "status": "completed",
            "end_time_actual": "2026-09-03T00:01:00+00:00",
            "progress": 100.0,
            "current_time": float(steps),
            "step_count": steps,
            "output_count": steps // output_every,
        }
    )
    persister.flush()


def test_progress_persister_coalesces_to_lifecycle_and_output_boundaries() -> None:
    store = _RecordingStore()
    persister = _RunProgressPersister(store.persist)
    steps = 20
    output_every = 10
    _emit_step_updates(persister, steps=steps, output_every=output_every)

    output_boundaries = steps // output_every
    # running + each output_count advance + completed; terminal flush is a no-op.
    assert len(store.payloads) == 1 + output_boundaries + 1
    assert store.payloads[0]["status"] == "running"
    assert [payload.get("output_count") for payload in store.payloads[1 : 1 + output_boundaries]] == [
        1,
        2,
    ]
    assert store.payloads[-1]["status"] == "completed"
    assert store.payloads[-1]["current_time"] == float(steps)
    assert store.payloads[-1]["step_count"] == steps
    assert store.payloads[-1]["output_count"] == output_boundaries
    uncoalesced = 1 + (steps * 4) + 1
    assert len(store.payloads) < uncoalesced


def test_progress_persister_flushes_structured_error_immediately() -> None:
    store = _RecordingStore()
    persister = _RunProgressPersister(store.persist)
    persister.observe({"progress": 12.5, "current_time": 3.0, "step_count": 8})
    assert store.payloads == []

    persister.observe(
        {
            "status": "failed",
            "error": "validated UNSFIN schedule required",
            "error_code": "edda_unsfin_schedule_required",
            "error_details": {"control": "simulate_shallow_landslide"},
        }
    )
    assert len(store.payloads) == 1
    payload = store.payloads[0]
    assert payload["status"] == "failed"
    assert payload["error_code"] == "edda_unsfin_schedule_required"
    assert payload["error_details"] == {"control": "simulate_shallow_landslide"}
    assert payload["progress"] == 12.5
    assert payload["step_count"] == 8


def test_progress_persister_flush_writes_trailing_progress() -> None:
    store = _RecordingStore()
    persister = _RunProgressPersister(store.persist)
    persister.observe({"status": "running"})
    persister.observe({"progress": 41.0, "current_time": 9.0, "step_count": 17, "output_count": 0})
    assert len(store.payloads) == 1
    persister.flush()
    assert len(store.payloads) == 2
    assert store.payloads[-1]["current_time"] == 9.0
    assert store.payloads[-1]["step_count"] == 17


class BurstProgressExecutor:
    """Emit one assignment per progress field per step, matching RuntimeSession."""

    STEPS = 20
    OUTPUT_EVERY = 10

    def signature(self, context: dict) -> str:
        return "test-compatible-runtime"

    def request_stop(self, simulation_id: str) -> None:
        return None

    def execute(self, context: dict, on_update, stop_event: Event) -> dict:
        on_update({"status": "running", "start_time": "2026-09-03T00:00:00+00:00"})
        for step in range(1, self.STEPS + 1):
            on_update({"progress": step * (100.0 / self.STEPS)})
            on_update({"current_time": float(step)})
            on_update({"step_count": step})
            on_update({"output_count": step // self.OUTPUT_EVERY})
        on_update(
            {
                "status": "completed",
                "end_time_actual": "2026-09-03T00:01:00+00:00",
                "progress": 100.0,
                "current_time": float(self.STEPS),
                "step_count": self.STEPS,
                "output_count": self.STEPS // self.OUTPUT_EVERY,
            }
        )
        return {
            "status": "completed",
            "progress": 100.0,
            "current_time": float(self.STEPS),
            "step_count": self.STEPS,
            "output_count": self.STEPS // self.OUTPUT_EVERY,
            "resource_summary": {"children": 0},
        }


def test_scheduler_throttles_progress_writes_to_output_boundaries(tmp_path: Path) -> None:
    executor = BurstProgressExecutor()
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=True,
        run_executor=executor,
        scheduler_poll_interval=0.01,
    )
    with TestClient(app) as client:
        store = client.app.state.workbench
        update_calls: list[dict] = []
        original_update_run = store.update_run

        def counting_update_run(project_id: str, simulation_id: str, values: dict) -> None:
            update_calls.append(dict(values))
            original_update_run(project_id, simulation_id, values)

        store.update_run = counting_update_run  # type: ignore[method-assign]
        project = _create_project(client, tmp_path / "coalesce-project", "Coalesce progress")
        scenario = _create_ready_scenario(client, project, "Burst steps")
        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201
        _wait_for(
            lambda: client.get(f"/api/projects/{project['project_id']}/queue").json()["items"][0]["status"]
            == "completed"
        )
        completed_item = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"][0]
        simulation = store.public_simulation(
            project["project_id"],
            store.simulation_row(project["project_id"], completed_item["simulation_id"]),
        )
        uncoalesced = 1 + 1 + (BurstProgressExecutor.STEPS * 4) + 1
        assert len(update_calls) < uncoalesced
        assert len(update_calls) <= 6
        assert any(payload.get("status") == "starting" for payload in update_calls)
        assert any(payload.get("status") == "running" for payload in update_calls)
        assert simulation["status"] == "completed"
        assert simulation["progress"] == 100.0
        assert simulation["step_count"] == BurstProgressExecutor.STEPS
        assert simulation["current_time"] == float(BurstProgressExecutor.STEPS)
        assert simulation["output_count"] == BurstProgressExecutor.STEPS // BurstProgressExecutor.OUTPUT_EVERY
