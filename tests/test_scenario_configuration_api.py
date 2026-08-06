from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.runtime_session import prepare_runtime_from_payload
from api.services.structured_input_resolver import validate_scenario_configuration
from api.services.workbench_store import ProjectDatabase
from tests.test_native_input_chain import _make_reference_case


def _create_project(client: TestClient, root: Path) -> dict:
    response = client.post(
        "/api/projects",
        json={"name": "Structured inputs", "root_path": str(root)},
    )
    assert response.status_code == 201
    return response.json()


def _upload(client: TestClient, project_id: str, family: str, name: str, value: int) -> dict:
    body = (
        "ncols 1\n"
        "nrows 1\n"
        "xllcorner 0\n"
        "yllcorner 0\n"
        "cellsize 1\n"
        "NODATA_value -9999\n"
        f"{value}\n"
    ).encode()
    response = client.post(
        f"/api/projects/{project_id}/uploads/{family}",
        files={"file": (name, body, "text/plain")},
    )
    assert response.status_code == 201
    return response.json()


def test_atomic_scenario_save_preserves_72_ordered_rainfall_bindings(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rainfall = [
            _upload(client, project_id, "rainfall", f"ri{index}.asc", index)
            for index in range(1, 73)
        ]
        scenario_response = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Three periods"},
        )
        assert scenario_response.status_code == 201
        scenario = scenario_response.json()

        bindings = [
            {
                "binding_key": "dem.primary",
                "asset_id": dem["upload_id"],
                "family": "dem",
                "role": "primary",
                "active": True,
            },
            *[
                {
                    "binding_key": f"rainfall.period.{index:04d}",
                    "asset_id": asset["upload_id"],
                    "family": "rainfall",
                    "role": "rainfall-period",
                    "period_id": f"period-{index:04d}",
                    "ordinal": index,
                    "active": True,
                }
                for index, asset in enumerate(rainfall, start=1)
            ],
        ]
        periods = [
            {
                "period_id": f"period-{index:04d}",
                "index": index,
                "start_s": (index - 1) * 3600,
                "end_s": index * 3600,
                "source": "raster",
                "asset_id": asset["upload_id"],
            }
            for index, asset in enumerate(rainfall, start=1)
        ]

        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": scenario["version"],
                "parameter_patch": {
                    "rainfall.mode": "raster",
                    "rainfall.periods": periods,
                    "manning.source": "global",
                },
                "input_bindings": bindings,
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["version"] == scenario["version"] + 1
        assert body["input_revision_id"] is None
        assert body["binding_state"] == "draft"
        assert [item["binding_key"] for item in body["input_bindings"]] == [
            "dem.primary",
            *[f"rainfall.period.{index:04d}" for index in range(1, 73)],
        ]
        assert body["effective_parameters"]["rainfall.periods"] == periods

        conflict = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={"expected_version": scenario["version"], "name": "stale write"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "scenario_version_conflict"


def test_asset_batch_upload_exposes_metadata_and_protects_references(tmp_path: Path) -> None:
    asc = (
        b"ncols 2\n"
        b"nrows 1\n"
        b"xllcorner 100\n"
        b"yllcorner 200\n"
        b"cellsize 10\n"
        b"NODATA_value -9999\n"
        b"1 2\n"
    )
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/assets/rainfall",
            files=[
                ("files", ("ri1.asc", asc, "text/plain")),
                ("files", ("ri2.asc", asc.replace(b"1 2", b"3 4"), "text/plain")),
            ],
        )
        assert uploaded.status_code == 201, uploaded.text
        assets = uploaded.json()["assets"]
        assert len(assets) == 2
        assert assets[0]["asset_id"] == assets[0]["upload_id"]
        assert assets[0]["roles"] == ["rainfall-period"]
        assert assets[0]["media_type"] == "text/plain"
        assert assets[0]["raster_metadata"]["rows"] == 1
        assert assets[0]["raster_metadata"]["cols"] == 2
        assert assets[0]["raster_metadata"]["cell_size"] == 10.0

        duplicate = client.post(
            f"/api/projects/{project_id}/assets/rainfall",
            files=[("files", ("same-content.asc", asc, "text/plain"))],
        )
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["assets"][0]["asset_id"] != assets[0]["asset_id"]
        assert duplicate.json()["assets"][0]["sha256"] == assets[0]["sha256"]
        assert duplicate.json()["assets"][0]["deduplicated"] is True

        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Bound asset"},
        ).json()
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": scenario["version"],
                "parameter_patch": {"rainfall.mode": "raster", "rainfall.periods": []},
                "input_bindings": [
                    {
                        "binding_key": "dem.primary",
                        "asset_id": dem["upload_id"],
                        "family": "dem",
                        "role": "primary",
                    },
                    {
                        "binding_key": "rainfall.period.0001",
                        "asset_id": assets[0]["asset_id"],
                        "family": "rainfall",
                        "role": "rainfall-period",
                        "period_id": "period-0001",
                        "ordinal": 1,
                    },
                ],
            },
        )
        assert saved.status_code == 200, saved.text

        protected = client.delete(f"/api/projects/{project_id}/assets/{assets[0]['asset_id']}")
        assert protected.status_code == 204

        removed = client.delete(f"/api/projects/{project_id}/assets/{assets[1]['asset_id']}")
        assert removed.status_code == 204
        listed = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
        assert {item["asset_id"] for item in listed} == {
            duplicate.json()["assets"][0]["asset_id"],
            dem["upload_id"],
        }


def test_v2_to_v6_binding_backfill_converts_unrun_legacy_revision_to_idempotent_draft(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain1 = _upload(client, project_id, "rainfall", "ri1.asc", 2)
        rain2 = _upload(client, project_id, "rainfall", "ri2.asc", 3)
        revision = client.post(
            f"/api/projects/{project_id}/input-revisions",
            json={"upload_ids": [dem["asset_id"], rain1["asset_id"], rain2["asset_id"]]},
        ).json()
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Historical", "input_revision_id": revision["revision_id"]},
        ).json()

    database = ProjectDatabase(Path(project["root_path"]))
    with sqlite3.connect(database.database_path) as connection:
        connection.execute("DROP TABLE input_revision_bindings")
        connection.execute("DROP TABLE parameter_templates")
        connection.execute("UPDATE schema_metadata SET value='2' WHERE key='schema_version'")
        connection.commit()

    database.ensure_schema()
    database.ensure_schema()
    with sqlite3.connect(database.database_path) as connection:
        version = connection.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()[0]
        binding_rows = connection.execute(
            "SELECT binding_key, asset_id FROM scenario_draft_bindings WHERE scenario_id=? ORDER BY binding_key",
            (scenario["scenario_id"],),
        ).fetchall()
        scenario_row = connection.execute(
            "SELECT scenario_id, input_revision_id FROM scenarios WHERE scenario_id=?",
            (scenario["scenario_id"],),
        ).fetchone()
        template_count = connection.execute("SELECT COUNT(*) FROM parameter_templates").fetchone()[0]
        orphan_revision_count = connection.execute(
            "SELECT COUNT(*) FROM input_revisions WHERE revision_id=?", (revision["revision_id"],)
        ).fetchone()[0]
        assert version == "7"
    assert binding_rows == [
        ("dem.primary", dem["asset_id"]),
        ("rainfall.period.0001", rain1["asset_id"]),
        ("rainfall.period.0002", rain2["asset_id"]),
    ]
    assert scenario_row == (scenario["scenario_id"], None)
    assert orphan_revision_count == 0
    assert template_count >= 1


def test_builtin_parameter_template_supplies_real_effective_defaults(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        templates = client.get(f"/api/projects/{project_id}/parameter-templates")
        assert templates.status_code == 200, templates.text
        template_items = templates.json()["templates"]
        assert {item["template_id"] for item in template_items} >= {"pt-bj-hxl-v1", "pt-bj-hxl-v2"}
        template = next(item for item in template_items if item["template_id"] == "pt-bj-hxl-v2")
        assert template["source_hash"] == "6ed94a70bd075d392c4cd1ea2659416efc62e2beb0e9c8ca247648ff50cd9689"
        assert template["values"]["time.t_end"] == 259200.0
        assert template["values"]["rheology.n_manning"] == 0.1
        assert len(template["values"]["rainfall.periods"]) == 72
        assert template["values"]["rainfall.timeline"] == {
            "mode": "regular",
            "start_s": 0.0,
            "end_s": 259200.0,
            "interval_s": 3600.0,
            "period_count": 72,
            "boundaries_s": [float(index * 3600) for index in range(73)],
            "source": "bundled_case",
            "declared_period_count": 72,
            "declared_end_s": 259200.0,
        }
        assert not any("path" in key.lower() for key in template["values"])

        created = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Defaults"},
        )
        assert created.status_code == 201, created.text
        scenario = created.json()
        assert scenario["parameter_template_id"] == template["template_id"]
        assert scenario["parameter_baseline"]["time.t_end"] == 259200.0
        assert scenario["parameter_patch"] == {}
        assert scenario["effective_parameters"]["time.t_end"] == 259200.0
        assert scenario["effective_parameters"]["hydrology.use_background_flux_offset"] is True

        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": scenario["version"],
                "parameter_patch": {"rheology.n_manning": 0.045},
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["effective_parameters"]["time.t_end"] == 259200.0
        assert saved.json()["effective_parameters"]["rheology.n_manning"] == 0.045


def test_edda_parameter_import_preview_ignores_all_file_paths(tmp_path: Path) -> None:
    edda_in = _make_reference_case(tmp_path / "legacy-case")
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, edda_in.parent)
        project_id = project["project_id"]
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Import target"},
        ).json()

        preview = client.post(
            f"/api/projects/{project_id}/parameter-imports/preview",
            params={"scenario_id": scenario["scenario_id"]},
            files={"file": ("edda_in.txt", edda_in.read_bytes(), "text/plain")},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["source_kind"] == "edda_in_parameter_import"
        assert body["values"]["time.t_end"] > 0
        assert body["values"]["rainfall.mode"] in {"uniform", "raster", "mixed"}
        assert body["values"]["rainfall.timeline"] == {
            "mode": "regular",
            "start_s": 0.0,
            "end_s": 7200.0,
            "interval_s": 3600.0,
            "period_count": 2,
            "boundaries_s": [0.0, 3600.0, 7200.0],
            "source": "edda_in",
            "declared_period_count": 2,
            "declared_end_s": 7200.0,
        }
        assert body["ignored_file_references"]["count"] > 0
        assert body["ignored_file_references"]["families"]
        serialized_values = str(body["values"]).lower()
        assert "resolved_paths" not in serialized_values
        assert "raw_paths" not in serialized_values
        assert str(edda_in.parent).lower() not in serialized_values
        assert any(item["key"] == "time.t_end" for item in body["diff"])


def test_edda_parameter_import_preview_preserves_path_free_runtime_semantics(tmp_path: Path) -> None:
    edda_in = _make_reference_case(tmp_path / "legacy-case")
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, edda_in.parent)
        scenario = client.post(
            f"/api/projects/{project['project_id']}/scenarios",
            json={"name": "Semantic import target"},
        ).json()

        preview = client.post(
            f"/api/projects/{project['project_id']}/parameter-imports/preview",
            params={"scenario_id": scenario["scenario_id"]},
            files={"file": ("edda_in.txt", edda_in.read_bytes(), "text/plain")},
        )

        assert preview.status_code == 200, preview.text
        values = preview.json()["values"]
        assert values["compute.use_double_precision"] is True
        assert values["time.dt_initial"] == 1.0
        assert values["hydrology.theta_s"] == 0.43
        assert values["hydrology.theta_i"] == 0.18
        assert values["hydrology.psi_f"] == 0.09
        assert values["hydrology.dfs_infiltration_variant"] == "tol_clipped_fhw"
        assert values["hydrology.dfs_face_flux_variant"] == "asymmetric_head_guard"
        assert values["hydrology.dfs_failure_source_variant"] == "live_doublelayer_in_dfs"
        assert values["hydrology.inflow_denominator_variant"] == "CELLAREA"
        assert values["soil.double_layer.enabled"] is True
        assert values["soil.double_layer.zmin"] == 0.001
        assert values["soil.double_layer.top_layer.c"] == 4000.0
        assert values["soil.double_layer.bottom_layer.c"] == 5000.0
        assert values["erosion.tau_c"] == 10.0
        assert values["erosion.k_erosion"] == 2.0e-6
        assert values["rheology.Cv_max"] == 0.65
        assert values["spatial_zones.enabled"] is True
        assert values["spatial_zones.num_zones"] == 1
        assert values["boundary_conditions.mode"] == "auto"
        assert values["boundary_conditions.default_type"] == "outflow"
        assert values["boundary_conditions.include_nodata"] is True
        assert not any("path" in key.lower() for key in values)


def test_edda_parameter_import_apply_changes_parameters_but_never_bindings(tmp_path: Path) -> None:
    edda_in = _make_reference_case(tmp_path / "legacy-case")
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, edda_in.parent)
        project_id = project["project_id"]
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Import target"},
        ).json()

        applied = client.post(
            f"/api/projects/{project_id}/parameter-imports/apply",
            params={
                "scenario_id": scenario["scenario_id"],
                "expected_version": scenario["version"],
            },
            files={"file": ("edda_in.txt", edda_in.read_bytes(), "text/plain")},
        )
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["scenario"]["parameter_template_id"].startswith("pt-import-")
        assert body["scenario"]["parameter_template_id"].endswith("-params-v2")
        assert str(body["template"]["version"]) == "2"
        assert body["scenario"]["input_revision_id"] is None
        assert body["scenario"]["input_bindings"] == []
        assert body["scenario"]["effective_parameters"]["time.t_end"] == 7200.0
        assert body["scenario"]["effective_parameters"]["rainfall.timeline"]["period_count"] == 2
        assert body["ignored_file_references"]["count"] > 0
        assert all("path" not in key.lower() for key in body["template"]["values"])


def test_imported_scenario_claim_activates_bound_zones_and_path_free_runtime_semantics(tmp_path: Path) -> None:
    edda_in = _make_reference_case(tmp_path / "legacy-case")
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, edda_in.parent)
        project_id = project["project_id"]
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Runtime semantic import"},
        ).json()
        imported = client.post(
            f"/api/projects/{project_id}/parameter-imports/apply",
            params={"scenario_id": scenario["scenario_id"], "expected_version": scenario["version"]},
            files={"file": ("edda_in.txt", edda_in.read_bytes(), "text/plain")},
        ).json()["scenario"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        zones = _upload(client, project_id, "zones", "zones.asc", 1)
        slope = _upload(client, project_id, "slope", "slope.asc", 20)
        thickness = _upload(client, project_id, "thickness", "thickness.asc", 3)
        manning = _upload(client, project_id, "manning", "manning.asc", 1)

        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": imported["version"],
                "input_bindings": [
                    {"binding_key": "dem.primary", "asset_id": dem["asset_id"], "family": "dem", "role": "primary"},
                    {"binding_key": "zones.primary", "asset_id": zones["asset_id"], "family": "zones", "role": "zones"},
                    {"binding_key": "slope.primary", "asset_id": slope["asset_id"], "family": "slope", "role": "slope"},
                    {"binding_key": "thickness.primary", "asset_id": thickness["asset_id"], "family": "thickness", "role": "thickness"},
                    {"binding_key": "manning.raster", "asset_id": manning["asset_id"], "family": "manning", "role": "manning-raster"},
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201, queued.text
        assert client.post(f"/api/projects/{project_id}/queue/start", json={}).status_code == 200
        claim = client.app.state.workbench.claim_queue_item(project_id, queued.json()["queue_item_id"])

        prepared = prepare_runtime_from_payload(
            app_output_dir=tmp_path / "runtime",
            dem_file=claim["dem_file"],
            soil_zones_file=claim["soil_zones_file"],
            output_dir=str(tmp_path / "runtime" / "run"),
            overrides=claim["overrides"],
            case_input_files=claim["case_input_files"],
            runtime_profile_name="cuda_production_default",
        )

        assert prepared.config.compute.use_double_precision is True
        assert prepared.config.time.dt_initial == 1.0
        assert prepared.config.hydrology.theta_i == 0.18
        assert prepared.config.soil.double_layer is not None
        assert prepared.config.soil.double_layer.enabled is True
        assert prepared.config.soil.double_layer.top_layer.c == 4000.0
        assert prepared.config.erosion.k_erosion == 2.0e-6
        assert prepared.config.spatial_zones.enabled is True
        assert prepared.config.spatial_zones.zone_file == claim["soil_zones_file"]
        assert prepared.config.native_inputs.files["zfil"].path == claim["case_input_files"]["zfil"]


def test_regular_rainfall_timeline_is_authoritative_for_period_count_and_boundaries() -> None:
    timeline = {
        "mode": "regular",
        "start_s": 0.0,
        "end_s": 10800.0,
        "interval_s": 3600.0,
        "period_count": 3,
        "boundaries_s": [0.0, 3600.0, 7200.0, 10800.0],
        "source": "user",
    }
    two_periods = [
        {"period_id": "period-0001", "index": 1, "start_s": 0, "end_s": 3600, "source": "uniform", "cri_mps": 0},
        {"period_id": "period-0002", "index": 2, "start_s": 3600, "end_s": 7200, "source": "uniform", "cri_mps": 0},
    ]
    manifest = [{"binding_key": "dem.primary", "asset_id": "dem-1", "family": "dem", "role": "primary", "active": True}]

    invalid = validate_scenario_configuration(
        {"time.t_end": 10800, "rainfall.mode": "uniform", "rainfall.timeline": timeline, "rainfall.periods": two_periods},
        manifest,
    )
    assert invalid["valid"] is False
    assert any("时间轴要求 3 个时段" in error for error in invalid["errors"])

    valid = validate_scenario_configuration(
        {
            "time.t_end": 10800,
            "rainfall.mode": "uniform",
            "rainfall.timeline": timeline,
            "rainfall.periods": [
                *two_periods,
                {"period_id": "period-0003", "index": 3, "start_s": 7200, "end_s": 10800, "source": "uniform", "cri_mps": 0},
            ],
        },
        manifest,
    )
    assert valid == {"valid": True, "errors": [], "warnings": [], "issues": []}


def test_structured_mixed_rainfall_preflight_and_runtime_need_no_edda_in(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = _upload(client, project_id, "dem", "dem.asc", 1)
        rain = _upload(client, project_id, "rainfall", "ri1.asc", 2)
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Mixed rainfall"},
        ).json()
        periods = [
            {
                "period_id": "period-0001",
                "index": 1,
                "start_s": 0,
                "end_s": 3600,
                "source": "raster",
                "asset_id": rain["upload_id"],
            },
            {
                "period_id": "period-0002",
                "index": 2,
                "start_s": 3600,
                "end_s": 7200,
                "source": "uniform",
                "cri_mps": 1.0e-6,
            },
        ]
        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": scenario["version"],
                "parameter_patch": {
                    "time.t_end": 7200,
                    "rainfall.mode": "mixed",
                    "rainfall.periods": periods,
                    "manning.source": "global",
                },
                "input_bindings": [
                    {
                        "binding_key": "dem.primary",
                        "asset_id": dem["upload_id"],
                        "family": "dem",
                        "role": "primary",
                    },
                    {
                        "binding_key": "rainfall.period.0001",
                        "asset_id": rain["upload_id"],
                        "family": "rainfall",
                        "role": "rainfall-period",
                        "period_id": "period-0001",
                        "ordinal": 1,
                    },
                ],
            },
        )
        assert saved.status_code == 200, saved.text

        configuration = client.get(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}/configuration"
        )
        assert configuration.status_code == 200, configuration.text
        assert configuration.json()["validation"] == {"valid": True, "errors": [], "warnings": [], "issues": []}

        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 201, queued.text
        assert client.post(f"/api/projects/{project_id}/queue/start", json={}).status_code == 200
        claim = client.app.state.workbench.claim_queue_item(project_id, queued.json()["queue_item_id"])
        assert claim["case_config_file"] is None
        assert claim["case_base_dir"] is None
        assert claim["overrides"]["structured_rainfall"]["periods"][0]["path"]
        assert "path" not in claim["overrides"]["structured_rainfall"]["periods"][1]

        prepared = prepare_runtime_from_payload(
            app_output_dir=tmp_path / "runtime",
            dem_file=claim["dem_file"],
            output_dir=str(tmp_path / "runtime" / "run"),
            overrides=claim["overrides"],
            case_config_file=claim["case_config_file"],
            case_base_dir=claim["case_base_dir"],
            case_input_files=claim["case_input_files"],
            runtime_profile_name="cuda_production_default",
        )
        assert prepared.config.rainfall is not None
        assert prepared.config.rainfall.mode == "spatial_tif_series"
        assert prepared.config.rainfall.interval_bounds_s == [0.0, 3600.0, 7200.0]
        assert len(list(Path(prepared.config.rainfall.directory).glob("period_*.tif"))) == 2
        assert "case_config_file" not in prepared.request_payload


def test_structured_preflight_rejects_time_manning_and_grid_inconsistencies(tmp_path: Path) -> None:
    dem_body = (
        b"ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
        b"NODATA_value -9999\n1\n"
    )
    rain_body = (
        b"ncols 1\nnrows 1\nxllcorner 10\nyllcorner 0\ncellsize 2\n"
        b"NODATA_value -9999\n2\n"
    )
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, tmp_path / "project")
        project_id = project["project_id"]
        dem = client.post(
            f"/api/projects/{project_id}/assets/dem",
            files=[("files", ("dem.asc", dem_body, "text/plain"))],
        ).json()["assets"][0]
        rain = client.post(
            f"/api/projects/{project_id}/assets/rainfall",
            files=[("files", ("rain.asc", rain_body, "text/plain"))],
        ).json()["assets"][0]
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Invalid structure"},
        ).json()

        saved = client.patch(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}",
            json={
                "expected_version": scenario["version"],
                "parameter_patch": {
                    "time.t_end": 7200,
                    "rainfall.mode": "mixed",
                    "rainfall.periods": [
                        {"period_id": "duplicate", "index": 1, "start_s": 0, "end_s": 3600, "source": "raster", "asset_id": rain["asset_id"]},
                        {"period_id": "duplicate", "index": 3, "start_s": 4000, "end_s": 7000, "source": "uniform", "cri_mps": -1},
                    ],
                    "manning.source": "raster",
                },
                "input_bindings": [
                    {"binding_key": "dem.primary", "asset_id": dem["asset_id"], "family": "dem", "role": "primary"},
                    {"binding_key": "rainfall.period.0001", "asset_id": rain["asset_id"], "family": "rainfall", "role": "rainfall-period", "period_id": "duplicate", "ordinal": 1},
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        validation = client.get(
            f"/api/projects/{project_id}/scenarios/{scenario['scenario_id']}/configuration"
        ).json()["validation"]
        assert validation["valid"] is False
        combined = "\n".join(validation["errors"])
        assert "标识重复" in combined
        assert "序号必须唯一" in combined
        assert "不连续" in combined
        assert "均匀雨强不能为负数" in combined
        assert "终点与模拟结束时间不一致" in combined
        assert "manning.raster" in combined
        assert "分辨率与 DEM 不一致" in combined
        assert "空间范围与 DEM 不一致" in combined
        issues = validation["issues"]
        assert any(issue["code"] == "rainfall_period_duplicate" and issue["period_id"] == "duplicate" for issue in issues)
        assert any(issue["code"] == "rainfall_uniform_value_negative" and issue["period_id"] == "duplicate" for issue in issues)
        assert any(issue["code"] == "rainfall_end_time_mismatch" and issue["parameter_key"] == "time.t_end" for issue in issues)
        assert any(issue["code"] == "manning_binding_missing" and issue["binding_key"] == "manning.raster" for issue in issues)

        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert queued.status_code == 422
        assert queued.json()["code"] == "scenario_configuration_invalid"


def test_legacy_migration_requires_preview_and_commits_assets_explicitly(tmp_path: Path) -> None:
    edda_in = _make_reference_case(tmp_path / "legacy")
    case_dir = edda_in.parent
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        project = _create_project(client, case_dir)
        project_id = project["project_id"]
        config = client.post(
            f"/api/projects/{project_id}/uploads/config",
            files={"file": ("edda_in.txt", edda_in.read_bytes(), "text/plain")},
        ).json()
        dem_path = case_dir / "Data" / "tutorial" / "bcdem.asc"
        dem = client.post(
            f"/api/projects/{project_id}/uploads/dem",
            files={"file": ("bcdem.asc", dem_path.read_bytes(), "text/plain")},
        ).json()
        revision = client.post(
            f"/api/projects/{project_id}/input-revisions",
            json={"upload_ids": [config["upload_id"], dem["upload_id"]]},
        ).json()
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Legacy", "input_revision_id": revision["revision_id"]},
        ).json()
        assert scenario["parameter_template_id"] is None

        preview = client.post(
            f"/api/projects/{project_id}/migrations/legacy/preview",
            json={"scenario_id": scenario["scenario_id"]},
        )
        assert preview.status_code == 200, preview.text
        plan = preview.json()
        assert plan["source_hash"] == config["sha256"]
        assert plan["existing_file_count"] > 0
        assert plan["missing_file_count"] > 0
        assert plan["unresolved_active_count"] == 0
        assert any(item["binding_key"] == "dem.primary" for item in plan["proposed_bindings"])
        assert not any(item["native_family"] == "swmm.txt" for item in plan["proposed_bindings"])
        assert all(item.get("path") for item in plan["file_references"])

        committed = client.post(
            f"/api/projects/{project_id}/migrations/legacy/commit",
            json={
                "scenario_id": scenario["scenario_id"],
                "expected_version": scenario["version"],
            },
        )
        assert committed.status_code == 200, committed.text
        migrated = committed.json()["scenario"]
        assert migrated["parameter_template_id"].startswith("pt-import-")
        assert migrated["input_revision_id"] != revision["revision_id"]
        assert all(item["binding_key"] != "legacy.config" for item in migrated["input_bindings"])
        assert migrated["effective_parameters"]["time.t_end"] == 7200.0
        assert committed.json()["report"]["rollback"]["input_revision_id"] == revision["revision_id"]
        assert Path(committed.json()["report_path"]).is_file()


def test_legacy_migration_keeps_unresolved_active_bindings_invalid(tmp_path: Path) -> None:
    edda_in = _make_reference_case(tmp_path / "legacy-missing-active")
    case_dir = edda_in.parent
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace("3.33333e-07 5.55556e-08", "-1 5.55556e-08"),
        encoding="utf-8",
    )
    with TestClient(create_app(state_dir=tmp_path / "state-missing-active", scheduler_enabled=False)) as client:
        project = _create_project(client, case_dir)
        project_id = project["project_id"]
        config = client.post(
            f"/api/projects/{project_id}/uploads/config",
            files={"file": ("edda_in.txt", edda_in.read_bytes(), "text/plain")},
        ).json()
        dem_path = case_dir / "Data" / "tutorial" / "bcdem.asc"
        dem = client.post(
            f"/api/projects/{project_id}/uploads/dem",
            files={"file": ("bcdem.asc", dem_path.read_bytes(), "text/plain")},
        ).json()
        revision = client.post(
            f"/api/projects/{project_id}/input-revisions",
            json={"upload_ids": [config["upload_id"], dem["upload_id"]]},
        ).json()
        scenario = client.post(
            f"/api/projects/{project_id}/scenarios",
            json={"name": "Legacy missing rainfall", "input_revision_id": revision["revision_id"]},
        ).json()

        preview = client.post(
            f"/api/projects/{project_id}/migrations/legacy/preview",
            json={"scenario_id": scenario["scenario_id"]},
        ).json()
        assert preview["unresolved_active_count"] == 1
        assert preview["unresolved_active_bindings"][0]["binding_key"] == "rainfall.period.0001"

        committed = client.post(
            f"/api/projects/{project_id}/migrations/legacy/commit",
            json={"scenario_id": scenario["scenario_id"], "expected_version": scenario["version"]},
        )
        assert committed.status_code == 200, committed.text
        body = committed.json()
        assert body["report"]["production_blocked"] is True
        migrated = body["scenario"]
        configuration = client.get(
            f"/api/projects/{project_id}/scenarios/{migrated['scenario_id']}/configuration"
        ).json()
        assert configuration["validation"]["valid"] is False
        assert configuration["validation"]["unresolved_bindings"][0]["binding_key"] == "rainfall.period.0001"

        assert migrated["input_revision_id"] is None
        assert migrated["binding_state"] == "draft"
        queued = client.post(
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": migrated["scenario_id"]},
        )
        assert queued.status_code == 422
        assert queued.json()["code"] == "scenario_configuration_invalid"
