from api.services.parameter_catalog import (
    build_case_config_interface,
    build_parameter_catalog,
    build_static_parameter_catalog,
)
from api.services.edda_switch_registry import EDDA_SWITCH_REGISTRY


def test_static_parameter_catalog_exposes_canonical_edda_controls_with_frontend_gate():
    catalog = build_static_parameter_catalog()
    controls = [
        entry for entry in catalog["parameters"]
        if entry.get("control_family") == "edda"
    ]

    assert catalog["control_registry"] == {
        "registry_version": "1.0.0",
        "entry_count": 45,
        "editable_count": 16,
        "restricted_count": 29,
    }
    assert [entry["source_index"] for entry in controls] == list(range(1, 46))
    assert [entry["control_key"] for entry in controls] == [
        spec.key for spec in EDDA_SWITCH_REGISTRY
    ]
    assert sum(entry["editable"] for entry in controls) == 16
    assert all(
        entry["editable"]
        == (entry["runtime_status"] in catalog["editable_statuses"])
        for entry in controls
    )
    assert all(entry["config_path"] == entry["key"] for entry in controls)
    assert all(
        entry["label_zh"] and entry["description_zh"]
        for entry in controls
    )
    assert all(entry["status_label_zh"] for entry in controls)
    by_control_key = {entry["control_key"]: entry for entry in controls}
    assert by_control_key["save_runoff_grids"]["label_zh"] == "保存径流栅格"
    assert by_control_key["simulate_drainage_flow"]["label_zh"] == "模拟排水管网流"
    assert by_control_key["simulate_rainfall"]["group"] == "compute_process"
    assert by_control_key["save_flow_depth"]["group"] == "compute_outputs"
    assert by_control_key["save_erosion_depth"]["dependency_paths"] == [
        "edda.run_controls.simulate_erosion"
    ]
    assert "hydrology.use_background_flux_offset" not in {
        entry["key"] for entry in catalog["parameters"]
        if entry.get("control_family") != "edda"
    }


def test_parameter_catalog_classifies_consumed_fallback_and_unsupported():
    audit = {
        "parameters": [
            {
                "parameter": "hydrology.K_sat",
                "parsed": True,
                "mapped": True,
                "consumed": True,
                "status": "configured",
                "output_evidence": ["depth.tif"],
                "evidence": {"runtime_stage": "uniform_field_init"},
            },
            {
                "parameter": "water_table_source",
                "parsed": True,
                "mapped": True,
                "consumed": True,
                "status": "config_fallback",
                "output_evidence": [],
                "evidence": {"input_state": "config_fallback"},
            },
            {
                "parameter": "dirfil",
                "parsed": True,
                "mapped": True,
                "consumed": False,
                "status": "recognized-only",
                "output_evidence": [],
                "evidence": {},
            },
        ]
    }
    provenance = {
        "reference_config_audit": {
            "unsupported_flags": [
                {
                    "flag": "flow_direction_mode",
                    "blocked_reason": "No safe runtime switch.",
                }
            ]
        }
    }

    catalog = build_parameter_catalog(audit, {}, provenance)
    by_key = {entry["key"]: entry for entry in catalog["parameters"]}

    assert by_key["hydrology.K_sat"]["runtime_status"] == "production_consumed"
    assert by_key["hydrology.K_sat"]["editable"] is True
    assert by_key["water_table_source"]["runtime_status"] == "config_fallback_consumed"
    assert by_key["water_table_source"]["editable"] is False
    assert by_key["dirfil"]["runtime_status"] == "mapped_only"
    assert by_key["flow_direction_mode"]["runtime_status"] == "unsupported"
    assert by_key["flow_direction_mode"]["editable"] is False


class ParsedCaseStub:
    reference_config_file = "E:/case/edda_in.txt"
    reference_base_dir = "E:/case"

    def to_audit_dict(self):
        return {
            "file_inputs": {},
            "supported_fields": [
                "depth",
                "manning_global",
                "rizero",
                "simul",
                "tout",
                "uww",
                "wavemax",
            ],
            "recognized_unsupported_fields": ["zmax"],
            "unrecognized_fields": [],
        }


def test_case_config_interface_exposes_edda_in_override_paths_without_promoting_mapped_only_fields():
    interface = build_case_config_interface(ParsedCaseStub())
    parameters = {
        entry["key"]: entry
        for entry in interface["parameter_catalog"]["parameters"]
    }

    assert parameters["simul"]["editable"] is False
    assert parameters["simul"]["config_path"] == "time.t_end"
    assert parameters["simul"]["override_paths"] == ["time.t_end"]
    assert parameters["tout"]["override_paths"] == ["time.dt_output"]
    assert parameters["wavemax"]["override_paths"] == ["time.wavemax"]
    assert parameters["manning_global"]["override_paths"] == ["rheology.n_manning"]
    assert parameters["rizero"]["override_paths"] == ["hydrology.rizero_initial"]
    assert parameters["depth"]["override_paths"] == [
        "soil.depth",
        "hydrology.depthwt_initial",
    ]
    assert parameters["uww"]["override_paths"] == [
        "soil.gamma_w",
        "soil.double_layer.uww",
    ]
    assert parameters["zmax"]["editable"] is False
    assert parameters["zmax"]["config_path"] is None
