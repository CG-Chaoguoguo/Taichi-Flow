from pathlib import Path
from fastapi.testclient import TestClient
from api.app import create_app
from tests.test_workbench_domain_api import _create_project, _create_ready_scenario


def test_scenario_controls_reset_snapshot_and_other_scenarios(tmp_path: Path):
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        scenario = _create_ready_scenario(client, project, "First")
        base = f"/api/projects/{project['project_id']}"
        path = f"{base}/scenarios/{scenario['scenario_id']}"
        other = client.post(f"{base}/scenarios", json={"name": "Other"}).json()
        other_path = f"{base}/scenarios/{other['scenario_id']}/configuration"
        before_other = client.get(other_path).json()
        gates = client.get("/api/settings/compute-gates").json()
        initial = client.get(path + "/configuration").json()
        key = "hydrology.dfs_face_flux_variant"
        response = client.patch(path, json={"control_overrides": {key: "arithmetic_mean_chamoli"}, "expected_version": initial["version"]})
        assert response.status_code == 200, response.text
        saved = client.get(path + "/configuration").json()
        assert saved["effective"][key] == "arithmetic_mean_chamoli"
        assert saved["control_defaults"] == initial["control_defaults"]
        assert client.get(other_path).json() == before_other
        assert client.get("/api/settings/compute-gates").json() == gates
        conflict = client.patch(path, json={"control_overrides": {}, "expected_version": initial["version"]})
        assert conflict.status_code == 409
        queued = client.post(base + "/queue", json={"scenario_id": scenario["scenario_id"], "runtime_profile": "compat_default_off"})
        assert queued.status_code in (200, 201), queued.text
        preview = client.post(base + "/delete-preview", json={"mode": "unregister"}).json()
        assert not preview["allowed"]
        preview = client.post(base + "/delete-preview", json={"mode": "permanent"}).json()
        assert not preview["allowed"]
        assert queued.json()["effective_config"][key] == "arithmetic_mean_chamoli"
        assert queued.json()["compute_policy_resolution"]["numeric_variants"][key]["source"] == "scenario_override"


def test_imported_controls_are_isolated_and_consumed_by_runtime(tmp_path):
    import hashlib
    from tests.test_native_input_chain import _make_reference_case
    from api.services.runtime_session import prepare_runtime_from_payload
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        store = client.app.state.workbench
        source = _make_reference_case(tmp_path)
        text = source.read_text(encoding="utf-8")
        marker = "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nT\nSimulate debris flow?"
        assert marker in text
        source.write_text(text.replace(marker, marker.replace("\nT\n", "\nF\n")), encoding="utf-8")
        hashes = {str(p.relative_to(source.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.parent.rglob("*") if p.is_file()}
        preview = store.preview_case_import(str(source.parent))
        imported = store.commit_case_import(str(source.parent), str(tmp_path / "copy"), expected_fingerprint=preview["case_fingerprint"])
        pid, sid = imported["project"]["project_id"], imported["scenario"]["scenario_id"]
        initial = store.get_scenario_configuration(pid, sid)
        other = store.duplicate_scenario(pid, sid)
        other_before = store.get_scenario_configuration(pid, other["scenario_id"])
        path = f"/api/projects/{pid}/scenarios/{sid}"
        key = "hydrology.dfs_face_flux_variant"
        saved = client.patch(path, json={"control_overrides": {key: "arithmetic_mean_chamoli"}, "expected_version": initial["version"]})
        assert saved.status_code == 200, saved.text
        config = store.get_scenario_configuration(pid, sid)
        assert config["baseline"] == initial["baseline"]
        assert config["effective"][key] == "arithmetic_mean_chamoli"
        queue = store.enqueue_scenario(pid, sid, runtime_profile="compat_default_off")
        assert queue["effective_config"][key] == config["effective"][key]
        context = store.claim_queue_item(pid, queue["queue_item_id"])
        prepared = prepare_runtime_from_payload(
            app_output_dir=tmp_path / "runtime", dem_file=context.get("dem_file"),
            rainfall_file=context.get("rainfall_file"), soil_zones_file=context.get("soil_zones_file"),
            boundary_file=context.get("boundary_file"), output_dir=context["output_dir"],
            overrides=context["overrides"], case_config_file=context["case_config_file"],
            case_base_dir=context["case_base_dir"], case_input_files=context["case_input_files"],
            runtime_profile_name=context["runtime_profile"], session_id=context["simulation_id"],
            frozen_effective_config=context["effective_config"], frozen_compute_policy_resolution=context["compute_policy_resolution"],
        )
        assert prepared.config.hydrology.dfs_face_flux_variant == "arithmetic_mean_chamoli"
        assert not store.get_scenario_configuration(pid, sid)["editable"]
        assert store.get_scenario_configuration(pid, other["scenario_id"]) == other_before
        assert {str(p.relative_to(source.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.parent.rglob("*") if p.is_file()} == hashes
        assert store.list_queue(pid)[0]["effective_config"] == queue["effective_config"]
