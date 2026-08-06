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
        json={
            "name": name,
            "input_revision_id": revision.json()["revision_id"],
            "parameter_patch": {
                "time.t_end": 3600,
                "rainfall.mode": "uniform",
                "rainfall.periods": [
                    {
                        "period_id": "period-0001",
                        "index": 1,
                        "start_s": 0,
                        "end_s": 3600,
                        "source": "uniform",
                        "cri_mps": 0,
                    }
                ],
                "manning.source": "global",
            },
        },
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


def test_draft_scenario_allowed_without_input_revision(tmp_path: Path) -> None:
    project_root = tmp_path / "draft-project"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root, name="Draft first")
        created = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "Early draft"},
        )
        assert created.status_code == 201
        scenario = created.json()
        assert scenario["status"] == "draft"
        assert scenario["input_revision_id"] is None

        blocked = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert blocked.status_code == 422
        assert blocked.json()["code"] == "scenario_configuration_invalid"

        dem = client.post(
            f"/api/projects/{project['project_id']}/uploads/dem",
            files={"file": ("dem.asc", b"ncols 1\nnrows 1\ncellsize 1\n1\n", "text/plain")},
        )
        assert dem.status_code == 201
        revision = client.post(
            f"/api/projects/{project['project_id']}/input-revisions",
            json={"upload_ids": [dem.json()["upload_id"]]},
        )
        assert revision.status_code == 201
        assert revision.json()["status"] == "ready"

        refreshed = client.get(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["status"] == "draft"
        assert refreshed.json()["input_revision_id"] is None

        configured = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": refreshed.json()["version"],
                "parameter_patch": {
                    "time.t_end": 3600,
                    "rainfall.mode": "uniform",
                    "rainfall.periods": [
                        {
                            "period_id": "period-0001",
                            "index": 1,
                            "start_s": 0,
                            "end_s": 3600,
                            "source": "uniform",
                            "cri_mps": 0,
                        }
                    ],
                    "manning.source": "global",
                },
                "input_bindings": [
                    {
                        "binding_key": "dem.primary",
                        "asset_id": dem.json()["upload_id"],
                        "family": "dem",
                        "role": "primary",
                    }
                ],
            },
        )
        assert configured.status_code == 200

        queued = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201


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
        assert scenario["effective_parameters"]["time.t_end"] == 259200.0

        rejected = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={"parameter_patch": {"rheology.unproven_parameter": 99}},
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "parameter_not_editable"


def test_delete_upload_removes_from_list_and_allows_revision_bound(tmp_path: Path) -> None:
    project_root = tmp_path / "delete-upload-project"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root, name="Delete upload")
        project_id = project["project_id"]
        payload = b"ncols 1\nnrows 1\ncellsize 1\n1\n"

        orphan = client.post(
            f"/api/projects/{project_id}/uploads/slope",
            files={"file": ("orphan.asc", payload, "text/plain")},
        )
        assert orphan.status_code == 201
        orphan_id = orphan.json()["upload_id"]

        deleted = client.delete(f"/api/projects/{project_id}/uploads/{orphan_id}")
        assert deleted.status_code == 204
        listed = client.get(f"/api/projects/{project_id}/uploads")
        assert listed.status_code == 200
        assert all(item["upload_id"] != orphan_id for item in listed.json()["uploads"])

        dem = client.post(
            f"/api/projects/{project_id}/uploads/dem",
            files={"file": ("dem.asc", payload + b"2\n", "text/plain")},
        )
        assert dem.status_code == 201
        dem_id = dem.json()["upload_id"]
        revision = client.post(
            f"/api/projects/{project_id}/input-revisions",
            json={"upload_ids": [dem_id]},
        )
        assert revision.status_code == 201
        revision_id = revision.json()["revision_id"]

        bound_delete = client.delete(f"/api/projects/{project_id}/uploads/{dem_id}")
        assert bound_delete.status_code == 204
        assert all(
            item["upload_id"] != dem_id
            for item in client.get(f"/api/projects/{project_id}/uploads").json()["uploads"]
        )
        validated = client.post(f"/api/projects/{project_id}/input-revisions/{revision_id}/validate")
        assert validated.status_code == 200
        assert validated.json()["valid"] is True

        missing = client.delete(f"/api/projects/{project_id}/uploads/upl-missing")
        assert missing.status_code == 404
        assert missing.json()["code"] == "upload_not_found"


def test_upload_raster_preview_png(tmp_path: Path) -> None:
    project_root = tmp_path / "preview-project"
    asc = (
        b"ncols 2\n"
        b"nrows 2\n"
        b"xllcorner 100\n"
        b"yllcorner 200\n"
        b"cellsize 10\n"
        b"NODATA_value -9999\n"
        b"1 2\n"
        b"3 4\n"
    )
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root, name="Preview")
        project_id = project["project_id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/uploads/dem",
            files={"file": ("tiny.asc", asc, "text/plain")},
        )
        assert uploaded.status_code == 201
        upload_id = uploaded.json()["upload_id"]

        preview = client.get(
            f"/api/projects/{project_id}/uploads/{upload_id}/preview",
            params={"mode": "downsample"},
        )
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("image/png")
        assert preview.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert preview.headers["X-Raster-Width"] == "2"
        assert preview.headers["X-Raster-Height"] == "2"
        assert "100" in preview.headers["X-Raster-Bounds"]
        assert preview.headers["X-Value-Min"] == "1.0"
        assert preview.headers["X-Value-Max"] == "4.0"

        missing = client.get(f"/api/projects/{project_id}/uploads/upl-missing/preview")
        assert missing.status_code == 404
        assert missing.json()["code"] == "upload_not_found"


def test_chinese_scenario_name_round_trip(tmp_path: Path) -> None:
    project_root = tmp_path / "chinese-name-project"
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, project_root, name="中文项目")
        created = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "基准工况"},
        )
        assert created.status_code == 201
        assert created.json()["name"] == "基准工况"

        listed = client.get(f"/api/projects/{project['project_id']}/scenarios")
        assert listed.status_code == 200
        assert listed.json()["scenarios"][0]["name"] == "基准工况"

        detail = client.get(
            f"/api/projects/{project['project_id']}/scenarios/{created.json()['scenario_id']}"
        )
        assert detail.status_code == 200
        assert detail.json()["name"] == "基准工况"


def test_corrupted_scenario_name_repaired_from_scenario_json(tmp_path: Path) -> None:
    from api.services.workbench_store import WorkbenchStore

    project_root = tmp_path / "repair-name-project"
    state_dir = tmp_path / "state"
    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        project = _create_project(client, project_root, name="Repair study")
        created = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "基准工况"},
        )
        assert created.status_code == 201
        scenario_id = created.json()["scenario_id"]

    store = WorkbenchStore(state_dir=state_dir)
    database = store.project_database(project["project_id"])
    with database.connect() as connection:
        connection.execute(
            "UPDATE scenarios SET name=? WHERE scenario_id=?",
            ("????", scenario_id),
        )
        connection.commit()

    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        listed = client.get(f"/api/projects/{project['project_id']}/scenarios")
        assert listed.status_code == 200
        assert listed.json()["scenarios"][0]["name"] == "基准工况"

        detail = client.get(f"/api/projects/{project['project_id']}/scenarios/{scenario_id}")
        assert detail.status_code == 200
        assert detail.json()["name"] == "基准工况"


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
