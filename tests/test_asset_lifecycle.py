from __future__ import annotations

from pathlib import Path
import threading

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from api.services.workbench_store import ProjectDatabase, WorkbenchError


ASC = b"ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1\n"


def _create_project(client: TestClient, root: Path) -> dict:
    response = client.post(
        "/api/projects",
        json={"name": "Asset lifecycle", "root_path": str(root), "description": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client: TestClient, project_id: str, family: str, name: str, value: int) -> dict:
    payload = ASC.replace(b"\n1\n", f"\n{value}\n".encode("ascii"))
    response = client.post(
        f"/api/projects/{project_id}/assets/{family}",
        files={"files": (name, payload, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["assets"][0]


def test_draft_assets_are_deletable_and_delete_cancels_waiting_queue(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain = _upload(client, project_id, "rainfall", "rain.asc", 2)
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Draft lifecycle"},
        ).json()
        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": scenario["version"],
                "parameter_patch": {
                    "time.t_end": 3600,
                    "rainfall.mode": "uniform",
                    "rainfall.periods": [
                        {"period_id": "period-0001", "index": 1, "start_s": 0, "end_s": 3600, "source": "uniform", "cri_mps": 1e-6}
                    ],
                    "manning.source": "global",
                },
                "input_bindings": [
                    {"binding_key": "dem.primary", "asset_id": dem["asset_id"], "family": "dem", "role": "primary"},
                    {"binding_key": "rainfall.period.0001", "asset_id": rain["asset_id"], "family": "rainfall", "role": "rainfall-period", "period_id": "period-0001", "ordinal": 1},
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["input_revision_id"] is None
        assert saved.json()["binding_state"] == "draft"

        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201, queued.text

        preview = client.post(
            f"/api/projects/{project_id}/assets/delete-preview",
            json={"asset_ids": [rain["asset_id"]]},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["cancelled_queue_item_ids"] == [queued.json()["queue_item_id"]]

        deleted = client.post(
            f"/api/projects/{project_id}/assets/batch-delete",
            json={"asset_ids": [rain["asset_id"]]},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_ids"] == [rain["asset_id"]]
        assert deleted.json()["detached_binding_count"] == 1
        assert deleted.json()["cancelled_queue_item_ids"] == [queued.json()["queue_item_id"]]

        queue = client.get(f"/api/projects/{project_id}/queue").json()["items"]
        assert queue[0]["status"] == "cancelled"
        assert queue[0]["cancel_reason"] == "asset_deleted"
        refreshed = client.get(f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}").json()
        assert refreshed["version"] == saved.json()["version"] + 1
        assert refreshed["input_bindings"] == [
            {"binding_key": "dem.primary", "asset_id": dem["asset_id"], "family": "dem", "role": "primary", "period_id": None, "ordinal": None, "active": True, "metadata": {}}
        ]


def _configured_draft(client: TestClient, project_id: str, dem: dict, rain: dict) -> dict:
    scenario = client.post(
        f"/api/projects/{project_id}/scenarios",
        json={"name": "Snapshot lifecycle"},
    ).json()
    saved = client.patch(
        f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
        json={
            "expected_version": scenario["version"],
            "parameter_patch": {
                "time.t_end": 3600,
                "rainfall.mode": "raster",
                "rainfall.periods": [
                    {"period_id": "period-0001", "index": 1, "start_s": 0, "end_s": 3600, "source": "raster", "asset_id": rain["asset_id"]}
                ],
                "manning.source": "global",
            },
            "input_bindings": [
                {"binding_key": "dem.primary", "asset_id": dem["asset_id"], "family": "dem", "role": "primary"},
                {"binding_key": "rainfall.period.0001", "asset_id": rain["asset_id"], "family": "rainfall", "role": "rainfall-period", "period_id": "period-0001", "ordinal": 1},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_running_snapshot_locks_assets_then_terminal_delete_retains_retryable_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain = _upload(client, project_id, "rainfall", "rain.asc", 2)
        scenario = _configured_draft(client, project_id, dem, rain)
        queue = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queue.status_code == 201, queue.text
        item = queue.json()
        assert item["input_revision_id"] is None

        claim = client.app.state.workbench.claim_queue_item(project_id, item["queue_item_id"])
        simulation_id = claim["simulation_id"]
        queued = client.get(f"/api/projects/{project_id}/queue").json()["items"][0]
        assert queued["status"] == "starting"
        assert queued["input_revision_id"]
        snapshot_id = queued["input_revision_id"]
        assert client.get(f"/api/projects/{project_id}/input-revisions/{snapshot_id}").json()["file_count"] == 2
        assert client.get(f"/api/projects/{project_id}/simulations/{simulation_id}").json()["input_revision_id"] == snapshot_id

        assets = {asset["asset_id"]: asset for asset in client.get(f"/api/projects/{project_id}/assets").json()["assets"]}
        assert assets[rain["asset_id"]]["runtime_lock"] == {
            "locked": True,
            "simulation_ids": [simulation_id],
            "statuses": ["starting"],
        }
        locked = client.post(
            f"/api/projects/{project_id}/assets/batch-delete",
            json={"asset_ids": [rain["asset_id"]]},
        )
        assert locked.status_code == 409
        assert locked.json()["code"] == "asset_runtime_locked"

        spare = _upload(client, project_id, "rainfall", "spare.asc", 3)
        mixed_batch = client.post(
            f"/api/projects/{project_id}/assets/batch-delete",
            json={"asset_ids": [rain["asset_id"], spare["asset_id"]]},
        )
        assert mixed_batch.status_code == 409
        assert mixed_batch.json()["code"] == "asset_runtime_locked"
        asset_ids_after_rollback = {
            asset["asset_id"] for asset in client.get(f"/api/projects/{project_id}/assets").json()["assets"]
        }
        assert {rain["asset_id"], spare["asset_id"]}.issubset(asset_ids_after_rollback)

        client.app.state.workbench.finish_run(project_id, simulation_id, {"status": "failed", "error": "test terminal"})
        released = client.post(
            f"/api/projects/{project_id}/assets/batch-delete",
            json={"asset_ids": [rain["asset_id"]]},
        )
        assert released.status_code == 200, released.text
        assert released.json()["retained_snapshot_blob_count"] == 1
        snapshot_files = client.get(f"/api/projects/{project_id}/input-revisions/{snapshot_id}").json()["files"]
        assert {file["sha256"] for file in snapshot_files} == {dem["sha256"], rain["sha256"]}

        retried = client.post(f"/api/projects/{project_id}/queue/{item['queue_item_id']}/retry")
        assert retried.status_code == 201, retried.text
        assert retried.json()["input_revision_id"] == snapshot_id
        retry_claim = client.app.state.workbench.claim_queue_item(project_id, retried.json()["queue_item_id"])
        assert retry_claim["simulation_id"] != simulation_id


def test_identical_uploads_keep_independent_logical_asset_ids(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        first = _upload(client, project_id, "rainfall", "ri-01.asc", 2)
        second = _upload(client, project_id, "rainfall", "ri-02.asc", 2)
        assert first["asset_id"] != second["asset_id"]
        assert first["sha256"] == second["sha256"]
        assert second["deduplicated"] is True
        assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
        assert {asset["asset_id"] for asset in assets} == {first["asset_id"], second["asset_id"]}
        assert client.post(
            f"/api/projects/{project_id}/assets/batch-delete",
            json={"asset_ids": [first["asset_id"]]},
        ).status_code == 200
        remaining = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
        assert [asset["asset_id"] for asset in remaining] == [second["asset_id"]]


def test_v3_to_v6_migration_keeps_started_run_snapshot_and_is_idempotent(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root)
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain = _upload(client, project_id, "rainfall", "rain.asc", 2)
        scenario = _configured_draft(client, project_id, dem, rain)
        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201, queued.text
        claim = client.app.state.workbench.claim_queue_item(project_id, queued.json()["queue_item_id"])
        simulation_id = claim["simulation_id"]
        snapshot_id = client.get(f"/api/projects/{project_id}/simulations/{simulation_id}").json()["input_revision_id"]
        assert snapshot_id

        database = ProjectDatabase(project_root)
        with database.connect() as connection:
            connection.execute("UPDATE schema_metadata SET value='3' WHERE key='schema_version'")
        database.ensure_schema()
        database.ensure_schema()

        with database.connect() as connection:
            assert connection.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()["value"] == "6"
            assert connection.execute(
                "SELECT input_revision_id FROM simulation_runs WHERE simulation_id=?", (simulation_id,)
            ).fetchone()["input_revision_id"] == snapshot_id
            assert connection.execute(
                "SELECT input_revision_id FROM queue_items WHERE queue_item_id=?", (queued.json()["queue_item_id"],)
            ).fetchone()["input_revision_id"] == snapshot_id
            assert connection.execute(
                "SELECT COUNT(*) FROM input_revisions WHERE revision_id=?", (snapshot_id,)
            ).fetchone()[0] == 1


def test_scheduler_claim_and_batch_delete_race_is_all_or_nothing(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain = _upload(client, project_id, "rainfall", "rain.asc", 2)
        scenario = _configured_draft(client, project_id, dem, rain)
        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201, queued.text
        queue_item_id = queued.json()["queue_item_id"]
        store = client.app.state.workbench
        barrier = threading.Barrier(3)
        outcomes: dict[str, object] = {}

        def claim() -> None:
            barrier.wait()
            try:
                outcomes["claim"] = store.claim_queue_item(project_id, queue_item_id)
            except WorkbenchError as error:
                outcomes["claim"] = error.code

        def delete() -> None:
            barrier.wait()
            try:
                outcomes["delete"] = store.batch_delete_assets(project_id, [rain["asset_id"]])
            except WorkbenchError as error:
                outcomes["delete"] = error.code

        claim_thread = threading.Thread(target=claim)
        delete_thread = threading.Thread(target=delete)
        claim_thread.start()
        delete_thread.start()
        barrier.wait()
        claim_thread.join(timeout=10)
        delete_thread.join(timeout=10)
        assert not claim_thread.is_alive()
        assert not delete_thread.is_alive()

        final_queue = client.get(f"/api/projects/{project_id}/queue").json()["items"][0]
        final_asset_ids = {
            asset["asset_id"] for asset in client.get(f"/api/projects/{project_id}/assets").json()["assets"]
        }
        if outcomes["delete"] == "asset_runtime_locked":
            assert isinstance(outcomes["claim"], dict)
            assert final_queue["status"] == "starting"
            assert final_queue["input_revision_id"]
            assert rain["asset_id"] in final_asset_ids
        else:
            assert isinstance(outcomes["delete"], dict)
            assert rain["asset_id"] not in final_asset_ids
            assert final_queue["status"] == "cancelled"
            assert final_queue["cancel_reason"] == "asset_deleted"
            assert outcomes["claim"] == "queue_item_not_claimable"


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "stopped", "interrupted"])
def test_every_terminal_run_state_releases_logical_asset_deletion(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain = _upload(client, project_id, "rainfall", "rain.asc", 2)
        scenario = _configured_draft(client, project_id, dem, rain)
        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201, queued.text
        claim = client.app.state.workbench.claim_queue_item(project_id, queued.json()["queue_item_id"])
        simulation_id = claim["simulation_id"]
        snapshot_id = client.get(f"/api/projects/{project_id}/simulations/{simulation_id}").json()["input_revision_id"]

        client.app.state.workbench.finish_run(project_id, simulation_id, {"status": terminal_status})
        removed = client.delete(f"/api/projects/{project_id}/assets/{rain['asset_id']}")
        assert removed.status_code == 204, removed.text
        assert client.get(f"/api/projects/{project_id}/simulations/{simulation_id}").json()["status"] == terminal_status
        snapshot_files = client.get(f"/api/projects/{project_id}/input-revisions/{snapshot_id}").json()["files"]
        assert rain["sha256"] in {file["sha256"] for file in snapshot_files}
