from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from api.app import create_app
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario


def _completed_run(client: TestClient, project: dict, scenario: dict, project_root: Path) -> str:
    queued = client.post(
        f"/api/projects/{project['project_id']}/queue",
        json={"scenario_id": scenario["scenario_id"]},
    ).json()
    store = client.app.state.workbench
    context = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "Flow_depthTaichi_0001.tif").write_bytes(b"one-cell-result")
    (output_dir / "HYDROGRAPHTaichi_0001.txt").write_text("0,0\n", encoding="utf-8")
    store.finish_run(
        project["project_id"],
        context["simulation_id"],
        {"status": "completed", "progress": 100.0, "resource_summary": {"children": 0}},
    )
    return context["simulation_id"]


def test_result_index_safe_download_zip_and_async_export(tmp_path: Path) -> None:
    app = create_app(state_dir=tmp_path / "state", scheduler_enabled=False)
    with TestClient(app) as client:
        project_root = tmp_path / "project"
        project = _create_project(client, project_root, "Results")
        scenario = _create_ready_scenario(client, project, "Result scenario")
        simulation_id = _completed_run(client, project, scenario, project_root)

        index = client.get(f"/api/projects/{project['project_id']}/results/{simulation_id}")
        assert index.status_code == 200
        assert index.json()["count"] == 2
        families = {item["name"] for item in index.json()["families"]}
        assert {"Flow_depth", "HYDROGRAPH"}.issubset(families)

        download = client.get(
            f"/api/projects/{project['project_id']}/results/{simulation_id}/files/Flow_depthTaichi_0001.tif"
        )
        assert download.status_code == 200
        assert download.content == b"one-cell-result"
        traversal = client.get(
            f"/api/projects/{project['project_id']}/results/{simulation_id}/files/..%2Fstate.sqlite3"
        )
        assert traversal.status_code == 422

        archive = client.get(f"/api/projects/{project['project_id']}/results/{simulation_id}/download.zip")
        assert archive.status_code == 200
        archive_path = tmp_path / "results.zip"
        archive_path.write_bytes(archive.content)
        with ZipFile(archive_path) as zip_file:
            names = set(zip_file.namelist())
            assert "manifest.json" in names
            assert "Flow_depthTaichi_0001.tif" in names

        export = client.post(
            f"/api/projects/{project['project_id']}/exports",
            json={"simulation_id": simulation_id, "families": ["Flow_depth"]},
        )
        assert export.status_code == 202
        export_id = export.json()["export_id"]
        job = client.get(f"/api/projects/{project['project_id']}/exports/{export_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "completed"
        exported = client.get(f"/api/projects/{project['project_id']}/exports/{export_id}/download")
        assert exported.status_code == 200
        export_path = tmp_path / "export.zip"
        export_path.write_bytes(exported.content)
        with ZipFile(export_path) as zip_file:
            assert "effective_parameters.json" in zip_file.namelist()
            assert "manifest.json" in zip_file.namelist()


def test_export_and_metadata_use_frozen_simulation_config(tmp_path: Path) -> None:
    app = create_app(state_dir=tmp_path / "state", scheduler_enabled=False)
    with TestClient(app) as client:
        project_root = tmp_path / "frozen-export-project"
        project = _create_project(client, project_root, "Frozen export")
        scenario = _create_ready_scenario(client, project, "Frozen export scenario")
        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201
        frozen = queued.json()["effective_config"]
        assert frozen

        live_parameters = dict(frozen)
        live_parameters["rheology.n_manning"] = 0.99
        store = client.app.state.workbench
        database = store.project_database(project["project_id"])
        with database.connect() as connection:
            connection.execute(
                "UPDATE scenarios SET effective_parameters_json=? WHERE scenario_id=?",
                (json.dumps(live_parameters, ensure_ascii=False), scenario["scenario_id"]),
            )
        changed = client.put(
            "/api/settings/compute-gates",
            json={"values": {"hydrology.dfs_failure_source_policy": "disabled"}},
        )
        assert changed.status_code == 200
        assert live_parameters != frozen

        context = store.claim_queue_item(project["project_id"], queued.json()["queue_item_id"])
        output_dir = Path(context["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "Flow_depthTaichi_0001.tif").write_bytes(b"one-cell-result")
        store.finish_run(
            project["project_id"],
            context["simulation_id"],
            {"status": "completed", "progress": 100.0, "resource_summary": {"children": 0}},
        )
        simulation_id = context["simulation_id"]
        assert store.public_simulation(
            project["project_id"],
            store.simulation_row(project["project_id"], simulation_id),
        )["effective_config"] == frozen

        metadata = client.get(f"/api/projects/{project['project_id']}/results/{simulation_id}/metadata")
        assert metadata.status_code == 200
        assert metadata.json()["effective_parameters"] == frozen
        assert metadata.json()["effective_parameters"] != live_parameters

        export = client.post(
            f"/api/projects/{project['project_id']}/exports",
            json={"simulation_id": simulation_id},
        )
        assert export.status_code == 202
        export_id = export.json()["export_id"]
        job = client.get(f"/api/projects/{project['project_id']}/exports/{export_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "completed"
        exported = client.get(f"/api/projects/{project['project_id']}/exports/{export_id}/download")
        assert exported.status_code == 200
        export_path = tmp_path / "frozen-export.zip"
        export_path.write_bytes(exported.content)
        with ZipFile(export_path) as zip_file:
            assert "effective_parameters.json" in zip_file.namelist()
            assert "effective_parameters.csv" in zip_file.namelist()
            exported_params = json.loads(zip_file.read("effective_parameters.json"))
            assert exported_params == frozen
            assert exported_params != live_parameters

        with database.connect() as connection:
            connection.execute(
                "UPDATE simulation_runs SET effective_config_json='{}' WHERE simulation_id=?",
                (simulation_id,),
            )
        empty_export = client.post(
            f"/api/projects/{project['project_id']}/exports",
            json={"simulation_id": simulation_id},
        )
        assert empty_export.status_code == 202
        empty_id = empty_export.json()["export_id"]
        empty_job = client.get(f"/api/projects/{project['project_id']}/exports/{empty_id}")
        assert empty_job.status_code == 200
        assert empty_job.json()["status"] == "completed"
        empty_bytes = client.get(f"/api/projects/{project['project_id']}/exports/{empty_id}/download")
        assert empty_bytes.status_code == 200
        empty_path = tmp_path / "empty-frozen-export.zip"
        empty_path.write_bytes(empty_bytes.content)
        with ZipFile(empty_path) as zip_file:
            assert json.loads(zip_file.read("effective_parameters.json")) == {}
        empty_metadata = client.get(f"/api/projects/{project['project_id']}/results/{simulation_id}/metadata")
        assert empty_metadata.status_code == 200
        assert empty_metadata.json()["effective_parameters"] == {}
