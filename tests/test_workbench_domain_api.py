from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.services.runtime_session import prepare_runtime_from_payload
from api.services.workbench_store import WorkbenchError, WorkbenchStore
from tests.test_native_input_chain import _make_reference_case


def _create_project(client: TestClient, root: Path, name: str = "Slope study") -> dict:
    response = client.post(
        "/api/projects",
        json={"name": name, "root_path": str(root), "description": "test project"},
    )
    assert response.status_code == 201
    return response.json()


def _create_ready_scenario(client: TestClient, project: dict, name: str) -> dict:
    gates = client.put(
        "/api/settings/compute-gates",
        json={"values": {"edda.run_controls.simulate_rainfall": False}},
    )
    assert gates.status_code == 200
    dem = client.post(
        f"/api/projects/{project['project_id']}/uploads/dem",
        files={
            "file": (
                f"{name}.asc",
                b"ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1 1\n1 1\n",
                "text/plain",
            )
        },
    )
    assert dem.status_code == 201
    grid_header = b"ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n"
    supporting_assets: list[tuple[str, dict]] = []
    for binding_key, family, filename, content in (
        ("outflow.primary", "outflow", "outflow.txt", b"outflow cells\n1\n1\n"),
        ("precomputed_unsfin.gindx", "precomputed_unsfin", "precomputed_unsfin_gindx.txt", grid_header + b"1 0\n0 0\n"),
        ("precomputed_unsfin.tfail_s", "precomputed_unsfin", "precomputed_unsfin_tfail.txt", grid_header + b"0 9999\n9999 9999\n"),
        ("precomputed_unsfin.fdepth_m", "precomputed_unsfin", "precomputed_unsfin_fdepth.txt", grid_header + b"0.1 0\n0 0\n"),
        (
            "precomputed_unsfin.meta",
            "precomputed_unsfin",
            "precomputed_unsfin_meta.json",
            b'{"provider":"production_native_unsfin","source_provenance":"production_native_unsfin","shape_kind":"ascii_grid"}\n',
        ),
    ):
        uploaded = client.post(
            f"/api/projects/{project['project_id']}/uploads/{family}",
            files={"file": (filename, content, "text/plain")},
        )
        assert uploaded.status_code == 201
        supporting_assets.append((binding_key, uploaded.json()))
    revision = client.post(
        f"/api/projects/{project['project_id']}/input-revisions",
        json={
            "bindings": [
                {
                    "binding_key": "dem.primary",
                    "asset_id": dem.json()["upload_id"],
                    "family": "dem",
                    "role": "primary",
                    "ordinal": 1,
                },
                *[
                    {
                        "binding_key": binding_key,
                        "asset_id": asset["upload_id"],
                        "family": asset["family"],
                        "role": "outflow" if binding_key == "outflow.primary" else "precomputed-unsfin",
                        "ordinal": index,
                    }
                    for index, (binding_key, asset) in enumerate(supporting_assets, start=1)
                ],
            ],
        },
    )
    assert revision.status_code == 201
    scenario = client.post(
        f"/api/projects/{project['project_id']}/scenarios",
        json={
            "name": name,
            "input_revision_id": revision.json()["revision_id"],
        },
    )
    assert scenario.status_code == 201
    return scenario.json()


def _make_importable_reference_case(root: Path) -> Path:
    edda_in = _make_reference_case(root)
    text = edda_in.read_text(encoding="utf-8")
    marker = "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nT\nSimulate debris flow?"
    assert marker in text
    edda_in.write_text(text.replace(marker, marker.replace("\nT\n", "\nF\n")), encoding="utf-8")
    return edda_in


def test_case_preview_reports_unsfin_loader_failures_as_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _make_reference_case(tmp_path / "source")
    (source.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        !if (fssimul) then",
                "        !    if (tnow<60.) tnow=60.",
                "        !    call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)",
                "        !end if",
                "        if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
                "            tempfsh(i)=fsdepth(i)",
                "            tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
                "        end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source.parent / "edda main program.F90").write_text(
        "if (fssimul) call unsfin(imx1,u(19),u(2),profil)\n",
        encoding="utf-8",
    )

    def fail_loader(*args: object, **kwargs: object) -> dict:
        raise ValueError("malformed numeric UNSFIN fixture")

    monkeypatch.setattr("api.services.native_sidecar_loader.load_precomputed_unsfin_schedule", fail_loader)
    preview = WorkbenchStore(tmp_path / "state").preview_case_import(str(source.parent))

    validation = preview["plan"]["precomputed_unsfin_validation"]
    assert validation["valid"] is False
    assert validation["parse_status"] == "invalid"
    assert validation["error"] == "malformed numeric UNSFIN fixture"
    assert preview["plan"]["unresolved_active_count"] >= 1


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
        assert scenario["effective_parameters"]["edda.registry_version"] == "1.0.0"
        assert scenario["effective_parameters"]["edda.run_controls.simulate_rainfall"] is True

        rejected = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={"parameter_patch": {"rheology.unproven_parameter": 99}},
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "parameter_not_editable"


def test_edda_compute_controls_round_trip_through_global_settings_api(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "compute-controls")
        created = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "EDDA control variant"},
        )
        assert created.status_code == 201
        scenario = created.json()
        assert scenario["parameter_template_id"] == "pt-bj-hxl-v4"
        assert scenario["parameter_baseline"]["edda.registry_version"] == "1.0.0"
        assert sum(
            key.startswith(("edda.run_controls.", "edda.output_controls."))
            for key in scenario["parameter_baseline"]
        ) == 45

        patch = {
            "edda.run_controls.simulate_rainfall": False,
            "edda.output_controls.save_flow_depth": False,
        }
        stripped = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={"parameter_patch": patch, "expected_version": scenario["version"]},
        )
        assert stripped.status_code == 200
        assert stripped.json()["parameter_patch"] == {}
        assert stripped.json()["effective_parameters"]["edda.run_controls.simulate_rainfall"] is True

        written = client.put("/api/settings/compute-gates", json={"values": patch})
        assert written.status_code == 200
        refreshed = client.get(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}"
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["parameter_patch"] == {}
        assert refreshed.json()["effective_parameters"]["edda.run_controls.simulate_rainfall"] is False
        assert refreshed.json()["effective_parameters"]["edda.output_controls.save_flow_depth"] is False
        assert refreshed.json()["effective_parameters"]["edda.output_controls.save_max_flow_depth"] is True

        configuration = client.get(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}/configuration"
        )
        assert configuration.status_code == 200
        assert configuration.json()["overrides"] == {}
        assert configuration.json()["effective"]["edda.run_controls.simulate_rainfall"] is False

        restricted = client.put(
            "/api/settings/compute-gates",
            json={"values": {"edda.run_controls.simulate_debris_flow": False}},
        )
        assert restricted.status_code == 422
        assert restricted.json()["code"] == "parameter_not_editable"


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
        assert retried.json()["position"] == 2

        current_queue = client.get(queue_url).json()["items"]
        assert [item["position"] for item in current_queue if item["status"] == "queued"] == [1, 2]

    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        persisted = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        assert {item["status"] for item in persisted} == {"queued", "cancelled"}
        assert any(item["retry_of"] == first.json()["queue_item_id"] for item in persisted)
        assert [item["position"] for item in persisted if item["status"] == "queued"] == [1, 2]


def test_queue_rejects_enabled_outflow_before_creating_a_run(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "outflow-preflight-project")
        dem = client.post(
            f"/api/projects/{project['project_id']}/uploads/dem",
            files={"file": ("dem.asc", b"ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1 1\n1 1\n", "text/plain")},
        )
        assert dem.status_code == 201
        revision = client.post(
            f"/api/projects/{project['project_id']}/input-revisions",
            json={"upload_ids": [dem.json()["upload_id"]]},
        )
        assert revision.status_code == 201
        created = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "Missing outflow", "input_revision_id": revision.json()["revision_id"]},
        )
        assert created.status_code == 201
        scenario = created.json()
        assert scenario["effective_parameters"]["edda.run_controls.simulate_outflow_cell"] is True

        rejected = client.post(
            f"/api/projects/{project['project_id']}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )

        assert rejected.status_code == 422
        assert rejected.json()["code"] == "scenario_configuration_invalid"
        details = rejected.json()["details"]
        assert "outflow_binding_missing" in {issue["code"] for issue in details["issues"]}
        queue = client.get(f"/api/projects/{project['project_id']}/queue").json()
        assert queue["items"] == []


def test_queue_freezes_policy_and_retry_reuses_original_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "freeze-project")
        scenario = _create_ready_scenario(client, project, "Frozen policy")
        queue_url = f"/api/projects/{project['project_id']}/queue"

        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert queued.status_code == 201
        original = queued.json()
        assert original["compute_policy_resolution"]["status"] == "resolved"
        original_mode = original["compute_policy_resolution"]["effective"]["mode"]

        changed = client.put(
            "/api/settings/compute-gates",
            json={"values": {"hydrology.dfs_failure_source_policy": "disabled"}},
        )
        assert changed.status_code == 200

        persisted = client.get(queue_url).json()["items"]
        current = next(item for item in persisted if item["queue_item_id"] == original["queue_item_id"])
        assert current["compute_policy_resolution"]["effective"]["mode"] == original_mode

        cancelled = client.delete(f"{queue_url}/{original['queue_item_id']}")
        assert cancelled.status_code == 200
        retried = client.post(f"{queue_url}/{original['queue_item_id']}/retry")
        assert retried.status_code == 201
        assert retried.json()["compute_policy_resolution"]["effective"]["mode"] == original_mode


def test_retry_after_draft_change_claims_frozen_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "retry-claim-project")
        scenario = _create_ready_scenario(client, project, "Retry claim frozen")
        queue_url = f"/api/projects/{project['project_id']}/queue"

        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert queued.status_code == 201
        original = queued.json()
        frozen_config = original["effective_config"]
        assert original["retry_of"] in {None, ""}
        assert original["input_revision_id"]
        assert frozen_config

        edited = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}",
            json={"parameter_patch": {"rheology.n_manning": 0.08}, "expected_version": scenario["version"]},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["effective_parameters"]["rheology.n_manning"] == 0.08
        assert edited.json()["version"] != original["scenario_version"]

        cancelled = next(
            item
            for item in client.get(queue_url).json()["items"]
            if item["queue_item_id"] == original["queue_item_id"]
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancel_reason"] == "draft_changed"

        retried = client.post(f"{queue_url}/{original['queue_item_id']}/retry")
        assert retried.status_code == 201, retried.text
        retry_item = retried.json()
        assert retry_item["retry_of"] == original["queue_item_id"]
        assert retry_item["input_revision_id"] == original["input_revision_id"]
        assert retry_item["effective_config"] == frozen_config
        assert retry_item["scenario_version"] == original["scenario_version"]

        store = client.app.state.workbench
        context = store.claim_queue_item(project["project_id"], retry_item["queue_item_id"])
        assert context["effective_config"] == frozen_config
        assert context["effective_config"]["rheology.n_manning"] != 0.08
        simulation = store.public_simulation(
            project["project_id"],
            store.simulation_row(project["project_id"], context["simulation_id"]),
        )
        assert simulation["status"] == "starting"
        assert simulation["effective_config"] == frozen_config
        assert simulation["input_revision_id"] == original["input_revision_id"]


def test_first_enqueue_claim_cancels_when_live_version_changes(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "first-enqueue-claim-project")
        scenario = _create_ready_scenario(client, project, "First enqueue live version")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert queued.status_code == 201
        item = queued.json()
        assert item["retry_of"] in {None, ""}
        assert item["input_revision_id"]
        assert item["effective_config"]

        store = client.app.state.workbench
        database = store.project_database(project["project_id"])
        with database.connect() as connection:
            connection.execute(
                "UPDATE scenarios SET version=? WHERE scenario_id=?",
                (int(item["scenario_version"]) + 1, scenario["scenario_id"]),
            )

        with pytest.raises(WorkbenchError) as error:
            store.claim_queue_item(project["project_id"], item["queue_item_id"])
        assert error.value.code == "queue_item_draft_changed"
        cancelled = next(
            row for row in store.list_queue(project["project_id"]) if row["queue_item_id"] == item["queue_item_id"]
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancel_reason"] == "draft_changed"


def test_queue_rejects_invalid_erosion_probe_payload_and_freezes_valid_options(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "probe-project")
        scenario = _create_ready_scenario(client, project, "Probe validation")
        queue_url = f"/api/projects/{project['project_id']}/queue"

        empty_enabled = client.post(
            queue_url,
            json={
                "scenario_id": scenario["scenario_id"],
                "diagnostics": {"erosion_probe": {"enabled": True, "probe_cells": []}},
            },
        )
        assert empty_enabled.status_code == 422
        assert empty_enabled.json()["code"] == "erosion_probe_invalid"

        malformed = client.post(
            queue_url,
            json={
                "scenario_id": scenario["scenario_id"],
                "diagnostics": {"erosion_probe": {"enabled": True, "probe_cells": [[0, 0, 1]]}},
            },
        )
        assert malformed.status_code == 422
        assert malformed.json()["code"] == "erosion_probe_invalid"

        duplicate = client.post(
            queue_url,
            json={
                "scenario_id": scenario["scenario_id"],
                "diagnostics": {"erosion_probe": {"enabled": True, "probe_cells": [[0, 0], [0, 0]]}},
            },
        )
        assert duplicate.status_code == 422
        assert duplicate.json()["code"] == "erosion_probe_invalid"

        outside = client.post(
            queue_url,
            json={
                "scenario_id": scenario["scenario_id"],
                "diagnostics": {"erosion_probe": {"enabled": True, "probe_cells": [[2, 0]]}},
            },
        )
        assert outside.status_code == 422
        assert outside.json()["code"] == "erosion_probe_invalid"

        queued = client.post(
            queue_url,
            json={
                "scenario_id": scenario["scenario_id"],
                "diagnostics": {"erosion_probe": {"enabled": True, "probe_cells": [[0, 0]]}},
            },
        )
        assert queued.status_code == 201
        assert queued.json()["run_options"] == {
            "diagnostics": {"erosion_probe": {"enabled": True, "probe_cells": [[0, 0]]}}
        }

        cancelled = client.delete(f"{queue_url}/{queued.json()['queue_item_id']}")
        assert cancelled.status_code == 200
        retried = client.post(f"{queue_url}/{queued.json()['queue_item_id']}/retry")
        assert retried.status_code == 201
        assert retried.json()["run_options"] == queued.json()["run_options"]


def test_probe_suggestions_use_latest_manifested_same_writer_result(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "probe-suggestions-project")
        scenario = _create_ready_scenario(client, project, "Probe suggestion source")
        writer_settings = client.put("/api/settings/compute-gates", json={"values": {
            "hydrology.dfs_erosion_depth_writer_variant": "net_bed_change_bj",
            "edda.run_controls.simulate_rainfall": False,
        }})
        assert writer_settings.status_code == 200
        endpoint = (
            f"/api/projects/{project['project_id']}/scenarios/"
            f"{scenario['scenario_id']}/diagnostics/probe-suggestions"
        )
        unavailable = client.get(endpoint)
        assert unavailable.status_code == 404
        assert unavailable.json()["code"] == "probe_suggestions_unavailable"

        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert queued.status_code == 201
        store = client.app.state.workbench
        context = store.claim_queue_item(project["project_id"], queued.json()["queue_item_id"])
        output_dir = Path(context["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        grid = "ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n0.8\n"
        (output_dir / "Erosion_depth_EDDA_45.0.txt").write_text(grid, encoding="utf-8")
        (output_dir / "Erosion_depth_EDDA_90.0.txt").write_text(grid, encoding="utf-8")
        # A newer lookalike must not make Top-N cross writer contracts.
        (output_dir / "Erosion_depth_EDDA_900.0.txt").write_text(grid, encoding="utf-8")
        (output_dir / "output_manifest.json").write_text(
            json.dumps(
                {
                    "result_files": [
                        {
                            "family": "Erosion_depth",
                            "relative_path": "Erosion_depth_EDDA_45.0.txt",
                            "writer": "taichi_edda_text",
                        },
                        {
                            "family": "Erosion_depth",
                            "relative_path": "Erosion_depth_EDDA_90.0.txt",
                            "writer": "taichi_edda_text",
                        },
                        {
                            "family": "Erosion_depth",
                            "relative_path": "Erosion_depth_EDDA_900.0.txt",
                            "writer": "foreign_writer",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        store.finish_run(project["project_id"], context["simulation_id"], {"status": "completed"})

        # Historical filename-only evidence cannot supply an exact output event.
        assert client.get(endpoint).status_code == 404
        from hashlib import sha256
        manifest_path = output_dir / "output_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        events = []
        for index, entry in enumerate(manifest["result_files"]):
            # Deliberately use a non-rounded physical time different from the filename.
            physical_time = ["45", "89.99999999999999", "900"][index]
            entry.update(frame_time_s=physical_time, frame_event_writer=entry["writer"],
                         sha256=sha256((output_dir / entry["relative_path"]).read_bytes()).hexdigest())
            events.append({"time_s": physical_time, "writer": entry["writer"],
                           "relative_paths": [entry["relative_path"]]})
        manifest_path.write_text(json.dumps(manifest))
        (output_dir / "output_frame_events.json").write_text(json.dumps(
            {"schema_version": "fix3-output-frame-events-v1", "events": events}))

        response = client.get(endpoint, params={"top": 5})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["simulation_id"] == context["simulation_id"]
        assert payload["input_revision_id"] == scenario["input_revision_id"]
        assert payload["source_file"] == "Erosion_depth_EDDA_90.0.txt"
        assert payload["source_frame_s"] == 89.99999999999999
        assert payload["writer"] == "taichi_edda_text"
        assert payload["probe_cells"] == [[0, 0]]

        copied = client.post(
            f"/api/projects/{project['project_id']}/scenarios/{scenario['scenario_id']}/duplicate"
        )
        assert copied.status_code == 201
        copied_endpoint = endpoint.replace(scenario["scenario_id"], copied.json()["scenario_id"])
        compatible = client.get(copied_endpoint)
        assert compatible.status_code == 200
        assert compatible.json()["simulation_id"] == context["simulation_id"]
        # Compatibility uses frozen output semantics, not only file extensions.
        database = store.project_database(project["project_id"])
        with database.connect() as connection:
            saved = connection.execute("SELECT effective_config_json FROM simulation_runs WHERE simulation_id=?",
                                       (context["simulation_id"],)).fetchone()[0]
            changed = json.loads(saved)
            changed["hydrology.dfs_erosion_depth_writer_variant"] = "incompatible_test_semantics"
            connection.execute("UPDATE simulation_runs SET effective_config_json=? WHERE simulation_id=?",
                               (json.dumps(changed), context["simulation_id"]))
        assert client.get(copied_endpoint).status_code == 404
        with database.connect() as connection:
            connection.execute("UPDATE simulation_runs SET effective_config_json=? WHERE simulation_id=?",
                               (saved, context["simulation_id"]))

        selected = output_dir / "Erosion_depth_EDDA_90.0.txt"
        selected.write_text(grid.replace("0.8", "9.8"), encoding="utf-8")
        # An unchanged manifest cannot authorize bytes modified after indexing.
        corrupted = client.get(endpoint)
        assert corrupted.status_code == 404
        assert corrupted.json()["code"] == "probe_suggestions_unavailable"


def test_claim_copies_queue_policy_into_simulation_and_runtime_payload(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "claim-freeze-project")
        scenario = _create_ready_scenario(client, project, "Claim frozen policy")
        queue_url = f"/api/projects/{project['project_id']}/queue"
        queued = client.post(queue_url, json={"scenario_id": scenario["scenario_id"]})
        assert queued.status_code == 201
        item = queued.json()

        changed = client.put(
            "/api/settings/compute-gates",
            json={"values": {"hydrology.dfs_failure_source_policy": "disabled"}},
        )
        assert changed.status_code == 200

        store = client.app.state.workbench
        context = store.claim_queue_item(project["project_id"], item["queue_item_id"])
        expected = item["compute_policy_resolution"]
        assert context["compute_policy_resolution"] == expected
        simulation = store.public_simulation(
            project["project_id"],
            store.simulation_row(project["project_id"], context["simulation_id"]),
        )
        assert simulation["compute_policy_resolution"] == expected


def test_case_import_replaces_an_existing_empty_destination(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_importable_reference_case(tmp_path / "source")
        destination = tmp_path / "existing-empty-destination"
        destination.mkdir()
        preview = store.preview_case_import(str(edda_in.parent))

        imported = store.commit_case_import(
            str(edda_in.parent),
            str(destination),
            expected_fingerprint=str(preview["case_fingerprint"]),
        )

        assert Path(imported["project"]["root_path"]) == destination
        assert (destination / ".taichi-flow" / "state.sqlite3").is_file()


def test_case_import_aborts_when_a_fingerprinted_source_changes_during_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_importable_reference_case(tmp_path / "source")
        destination = tmp_path / "fingerprint-destination"
        preview = store.preview_case_import(str(edda_in.parent))
        original_ingest = store.ingest_upload_from_path
        changed = False

        def mutate_before_ingest(project_id: str, *, family: str, path: str) -> dict:
            nonlocal changed
            if family == "dem" and not changed:
                changed = True
                source = Path(path)
                source.write_bytes(source.read_bytes() + b"\n")
            return original_ingest(project_id, family=family, path=path)

        monkeypatch.setattr(store, "ingest_upload_from_path", mutate_before_ingest)

        with pytest.raises(WorkbenchError) as error:
            store.commit_case_import(
                str(edda_in.parent),
                str(destination),
                expected_fingerprint=str(preview["case_fingerprint"]),
            )

        assert error.value.code == "case_fingerprint_mismatch"
        assert changed
        assert not destination.exists()
        assert all(Path(project["root_path"]) != destination for project in store.list_projects())


def test_case_import_refuses_a_destination_that_changes_before_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_importable_reference_case(tmp_path / "source")
        destination = tmp_path / "changing-destination"
        preview = store.preview_case_import(str(edda_in.parent))
        original_create_scenario = store.create_scenario

        def create_scenario_then_change_destination(*args: object, **kwargs: object) -> dict:
            result = original_create_scenario(*args, **kwargs)
            destination.mkdir()
            (destination / "arrived-during-import.txt").write_text("preserve me", encoding="utf-8")
            return result

        monkeypatch.setattr(store, "create_scenario", create_scenario_then_change_destination)

        with pytest.raises(WorkbenchError) as error:
            store.commit_case_import(
                str(edda_in.parent),
                str(destination),
                expected_fingerprint=str(preview["case_fingerprint"]),
            )

        assert error.value.code == "case_destination_not_empty"
        assert (destination / "arrived-during-import.txt").read_text(encoding="utf-8") == "preserve me"


def test_case_import_restores_removed_empty_destination_when_publish_move_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_importable_reference_case(tmp_path / "source")
        destination = tmp_path / "restore-empty-destination"
        destination.mkdir()
        preview = store.preview_case_import(str(edda_in.parent))
        original_replace = Path.replace

        def fail_only_final_publish(self: Path, target: str | Path) -> Path:
            if self.name.startswith(f".{destination.name}.import-") and Path(target) == destination:
                raise OSError("simulated publish move failure")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", fail_only_final_publish)

        with pytest.raises(OSError, match="simulated publish move failure"):
            store.commit_case_import(
                str(edda_in.parent),
                str(destination),
                expected_fingerprint=str(preview["case_fingerprint"]),
            )

        assert destination.is_dir()
        assert not any(destination.iterdir())


def test_case_import_recovers_catalog_when_publish_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_importable_reference_case(tmp_path / "source")
        destination = tmp_path / "recover-published-destination"
        preview = store.preview_case_import(str(edda_in.parent))
        original_public_scenario = store._public_scenario
        original_replace = Path.replace
        failed_after_publish = False

        def fail_after_publish(*args: object, **kwargs: object) -> dict:
            nonlocal failed_after_publish
            if destination.exists() and not failed_after_publish:
                failed_after_publish = True
                raise OSError("simulated post-publish catalog failure")
            return original_public_scenario(*args, **kwargs)

        def fail_publish_rollback(self: Path, target: str | Path) -> Path:
            target_path = Path(target)
            if self == destination and target_path.name.startswith(f".{destination.name}.import-"):
                raise OSError("simulated rollback rename failure")
            return original_replace(self, target)

        monkeypatch.setattr(store, "_public_scenario", fail_after_publish)
        monkeypatch.setattr(Path, "replace", fail_publish_rollback)

        recovered = store.commit_case_import(
            str(edda_in.parent),
            str(destination),
            expected_fingerprint=str(preview["case_fingerprint"]),
        )

        assert recovered["idempotent"] is True
        assert Path(recovered["project"]["root_path"]) == destination
        assert not (destination / ".taichi-flow" / "case-import-recovery.json").exists()
        assert store.commit_case_import(
            str(edda_in.parent),
            str(destination),
            expected_fingerprint=str(preview["case_fingerprint"]),
        )["idempotent"] is True


def test_batch_delete_reclaims_only_unreferenced_project_blobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        project = store.create_or_open_project(name="Asset lifecycle", root_path=str(tmp_path / "project"), description="")
        project_id = project["project_id"]

        def upload(name: str, contents: bytes) -> dict:
            return store.ingest_upload(
                project_id,
                family="dem",
                filename=name,
                stream=BytesIO(contents),
            )

        shared_live = upload("shared-live.asc", b"shared contents")
        shared_archived = upload("shared-archived.asc", b"shared contents")
        revision_owned = upload("revision-owned.asc", b"revision contents")
        orphaned = upload("orphaned.asc", b"orphaned contents")
        cleanup_failure = upload("cleanup-failure.asc", b"cleanup failure contents")
        shared_path = store.get_upload_blob_path(project_id, shared_live["asset_id"])
        revision_path = store.get_upload_blob_path(project_id, revision_owned["asset_id"])
        orphaned_path = store.get_upload_blob_path(project_id, orphaned["asset_id"])
        failure_path = store.get_upload_blob_path(project_id, cleanup_failure["asset_id"])
        store.archive_asset(project_id, shared_archived["asset_id"])
        store.create_input_revision(
            project_id,
            version_tag=None,
            upload_ids=[revision_owned["asset_id"]],
            parent_revision_id=None,
        )

        first = store.batch_delete_assets(
            project_id,
            [shared_live["asset_id"], revision_owned["asset_id"], orphaned["asset_id"]],
        )

        assert first["deleted_blob_count"] == 1
        assert first["retained_upload_blob_count"] == 1
        assert first["retained_snapshot_blob_count"] == 1
        assert first["orphaned_blob_cleanup_failures"] == []
        assert shared_path.is_file()
        assert revision_path.is_file()
        assert not orphaned_path.exists()

        original_unlink = Path.unlink

        def fail_only_orphan_cleanup(self: Path, *args: object, **kwargs: object) -> None:
            if self == failure_path:
                raise OSError("simulated blob cleanup failure")
            original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_only_orphan_cleanup)
        failed_cleanup = store.batch_delete_assets(project_id, [cleanup_failure["asset_id"]])

        assert failed_cleanup["deleted_ids"] == [cleanup_failure["asset_id"]]
        assert failed_cleanup["orphaned_blob_cleanup_failures"] == [
            {
                "sha256": cleanup_failure["sha256"],
                "path": str(failure_path.resolve()),
                "error": "simulated blob cleanup failure",
            }
        ]
        assert failure_path.is_file()


def test_reference_case_claim_preserves_edda_config_mapping(tmp_path: Path) -> None:
    """A reference-owned import must not collapse into direct/default runtime config."""
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_reference_case(tmp_path)
        # This test exercises runtime source selection rather than the separate
        # UNSFIN topology gate, so keep its compact fixture on the inactive
        # shallow-landslide branch.
        source_text = edda_in.read_text(encoding="utf-8")
        original = "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nT\nSimulate debris flow?"
        assert source_text.count(original) == 1
        edda_in.write_text(source_text.replace(original, original.replace("\nT\n", "\nF\n")), encoding="utf-8")
        source_root = edda_in.parent
        preview = store.preview_case_import(str(source_root))
        imported = store.commit_case_import(
            str(source_root),
            str(tmp_path / "reference-project"),
            expected_fingerprint=str(preview["case_fingerprint"]),
        )
        project = imported["project"]
        scenario = imported["scenario"]
        assert scenario["configuration_ownership"] == "reference_case"

        queued = store.enqueue_scenario(project["project_id"], scenario["scenario_id"])
        context = store.claim_queue_item(project["project_id"], queued["queue_item_id"])

        # This is the critical seam: the runtime must receive the immutable
        # imported edda_in blob, not fall through to the direct API payload.
        assert context["case_config_file"] is not None
        assert Path(context["case_config_file"]).is_file()
        assert context["case_base_dir"] == project["root_path"]
        frozen_input_paths = {
            "case_config_file": context["case_config_file"],
            "dem_file": context["dem_file"],
            "soil_zones_file": context["soil_zones_file"],
            "boundary_file": context["boundary_file"],
            **context["case_input_files"],
        }
        assert {"case_config_file", "dem_file"} <= {
            key for key, path in frozen_input_paths.items() if path is not None
        }
        assert context["case_input_files"]
        missing_frozen_inputs = [
            f"{key}={path}"
            for key, path in frozen_input_paths.items()
            if path is not None and not Path(path).is_file()
        ]
        assert not missing_frozen_inputs, missing_frozen_inputs

        prepared = prepare_runtime_from_payload(
            app_output_dir=tmp_path / "app-output",
            dem_file=context.get("dem_file"),
            rainfall_file=context.get("rainfall_file"),
            soil_zones_file=context.get("soil_zones_file"),
            boundary_file=context.get("boundary_file"),
            output_dir=context["output_dir"],
            overrides=context["overrides"],
            case_config_file=context["case_config_file"],
            case_base_dir=context["case_base_dir"],
            case_input_files=context["case_input_files"],
            runtime_profile_name=context["runtime_profile"],
            session_id=context["simulation_id"],
            frozen_effective_config=context["effective_config"],
            frozen_compute_policy_resolution=context["compute_policy_resolution"],
        )

        assert prepared.provenance["source_mode"] == "reference_config"
        assert prepared.effective_config["source_mode"] == "reference_config"


def test_reference_case_inactive_failure_policy_keeps_frozen_forensics_when_source_files_are_not_imported(tmp_path: Path) -> None:
    """An inactive DFS policy must not require source-only Fortran evidence at runtime."""
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_reference_case(tmp_path)
        source_text = edda_in.read_text(encoding="utf-8")
        original = "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nT\nSimulate debris flow?"
        assert source_text.count(original) == 1
        edda_in.write_text(source_text.replace(original, original.replace("\nT\n", "\nF\n")), encoding="utf-8")
        (edda_in.parent / "edda main program.F90").write_text(
            "if (fssimul) call unsfin(imx1,u(19),u(2),profil)\n",
            encoding="utf-8",
        )
        (edda_in.parent / "dfs.F90").write_text(
            "\n".join(
                [
                    "if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
                    "  tempfsh(i)=fsdepth(i)",
                    "  tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
                    "end if",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        preview = store.preview_case_import(str(edda_in.parent))
        imported = store.commit_case_import(
            str(edda_in.parent),
            str(tmp_path / "reference-project"),
            expected_fingerprint=str(preview["case_fingerprint"]),
        )
        project = imported["project"]
        scenario = imported["scenario"]
        queued = store.enqueue_scenario(project["project_id"], scenario["scenario_id"])
        assert queued["compute_policy_resolution"]["detected"]["topology_status"] == "recognized"
        assert queued["compute_policy_resolution"]["effective"]["mode"] == "disabled"

        context = store.claim_queue_item(project["project_id"], queued["queue_item_id"])
        assert not (Path(context["case_base_dir"]) / "dfs.F90").exists()
        prepared = prepare_runtime_from_payload(
            app_output_dir=tmp_path / "app-output",
            dem_file=context.get("dem_file"),
            rainfall_file=context.get("rainfall_file"),
            soil_zones_file=context.get("soil_zones_file"),
            boundary_file=context.get("boundary_file"),
            output_dir=context["output_dir"],
            overrides=context["overrides"],
            case_config_file=context["case_config_file"],
            case_base_dir=context["case_base_dir"],
            case_input_files=context["case_input_files"],
            runtime_profile_name=context["runtime_profile"],
            session_id=context["simulation_id"],
            frozen_effective_config=context["effective_config"],
            frozen_compute_policy_resolution=context["compute_policy_resolution"],
        )

        assert prepared.runtime_input_manifest["compute_policy_resolution"] == queued["compute_policy_resolution"]


def test_reference_case_parameter_save_and_duplicate_keep_immutable_input_revision(tmp_path: Path) -> None:
    """A runtime-only parameter edit must not detach a ready reference input snapshot."""
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        edda_in = _make_reference_case(tmp_path)
        source_text = edda_in.read_text(encoding="utf-8")
        original = "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nT\nSimulate debris flow?"
        assert source_text.count(original) == 1
        edda_in.write_text(source_text.replace(original, original.replace("\nT\n", "\nF\n")), encoding="utf-8")

        preview = store.preview_case_import(str(edda_in.parent))
        imported = store.commit_case_import(
            str(edda_in.parent),
            str(tmp_path / "reference-project"),
            expected_fingerprint=str(preview["case_fingerprint"]),
        )
        project = imported["project"]
        source = imported["scenario"]
        revision_id = imported["input_revision_id"]
        assert source["input_revision_id"] == revision_id
        assert source["status"] == "ready"

        # This matches the editor save contract: it submits the current binding
        # projection together with a parameter-only change.
        saved = client.patch(
            f"/api/projects/{project['project_id']}/scenarios/{source['scenario_id']}",
            json={
                "parameter_patch": {"time.t_end": 900},
                "input_bindings": source["input_bindings"],
                "expected_version": source["version"],
            },
        )
        assert saved.status_code == 200
        saved_scenario = saved.json()
        assert saved_scenario["input_revision_id"] == revision_id
        assert saved_scenario["status"] == "ready"
        assert saved_scenario["effective_parameters"]["time.t_end"] == 900

        duplicated = client.post(
            f"/api/projects/{project['project_id']}/scenarios/{saved_scenario['scenario_id']}/duplicate"
        )
        assert duplicated.status_code == 201
        copied = duplicated.json()
        assert copied["input_revision_id"] == revision_id
        assert copied["status"] == "ready"
        assert copied["configuration_ownership"] == "reference_case"
