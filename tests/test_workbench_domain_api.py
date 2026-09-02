from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.runtime_session import prepare_runtime_from_payload
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
        json={"name": name, "input_revision_id": revision.json()["revision_id"]},
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

    with TestClient(create_app(state_dir=state_dir, scheduler_enabled=False)) as client:
        persisted = client.get(f"/api/projects/{project['project_id']}/queue").json()["items"]
        assert {item["status"] for item in persisted} == {"queued", "cancelled"}
        assert any(item["retry_of"] == first.json()["queue_item_id"] for item in persisted)


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
