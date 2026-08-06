from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.workbench_store import WorkbenchStore
from tests.test_native_input_chain import _make_reference_case


def test_config_interface_and_case_base_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("TAICHI_FLOW_STATE_DIR", str(state_dir))

    edda_in = _make_reference_case(tmp_path)
    case_dir = edda_in.parent
    dem = case_dir / "Data" / "tutorial" / "bcdem.asc"

    store = WorkbenchStore(state_dir)
    project = store.create_or_open_project(name="cfg-iface", root_path=str(case_dir))
    project_id = project["project_id"]

    config_upload = store.ingest_upload_from_path(project_id, family="config", path=str(edda_in))
    dem_upload = store.ingest_upload_from_path(project_id, family="dem", path=str(dem))
    revision = store.create_input_revision(
        project_id,
        version_tag="v1",
        upload_ids=[config_upload["upload_id"], dem_upload["upload_id"]],
        parent_revision_id=None,
    )

    interface = store.get_config_interface(project_id, revision["revision_id"])
    assert Path(interface["case_base_dir"]) == case_dir.resolve()
    assert interface["parsed_values"]["rainfall"]["mode"] in {"uniform_cri", "raster_rifil", "mixed"}
    assert "manning" in interface["parsed_values"]

    scenario = store.create_scenario(
        project_id,
        name="baseline",
        input_revision_id=revision["revision_id"],
        base_scenario_id=None,
        parameter_patch={"rainfall.mode": "uniform_cri", "rheology.n_manning": 0.08},
    )
    queue_item = store.enqueue_scenario(project_id, scenario["scenario_id"])
    claim = store.claim_queue_item(project_id, queue_item["queue_item_id"])
    assert Path(claim["case_base_dir"]) == case_dir.resolve()
    assert claim["overrides"]["rainfall"]["mode"] == "uniform_cri"
    assert claim["overrides"]["rheology"]["n_manning"] == 0.08

    app = create_app(state_dir=state_dir, scheduler_enabled=False)
    client = TestClient(app)
    response = client.get(
        f"/api/projects/{project_id}/input-revisions/{revision['revision_id']}/config-interface"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["revision_id"] == revision["revision_id"]
