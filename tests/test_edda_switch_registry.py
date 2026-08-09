import os
from pathlib import Path

import pytest

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.edda_switch_registry import (
    ALLOWED_STATUSES,
    EDDA_SWITCH_BY_KEY,
    EDDA_SWITCH_REGISTRY,
)
from api.services.reference_config_parser import parse_reference_config_file
from api.services.parameter_templates import (
    BJ_HXL_TEMPLATE_ID,
    builtin_bj_hxl_template,
    builtin_parameter_templates,
    normalized_parameter_values,
)


def _case_config_file() -> Path:
    raw_case_dir = os.environ.get("EDDA_BJ_HXL_CASE_DIR")
    if not raw_case_dir:
        pytest.skip("set EDDA_BJ_HXL_CASE_DIR to run external BJ_HXL integration tests")
    config_file = Path(raw_case_dir) / "edda_in.txt"
    if not config_file.is_file():
        pytest.skip(f"BJ_HXL configuration is unavailable: {config_file}")
    return config_file


EXPECTED_SWITCH_KEYS = [
    "save_runoff_grids",
    "save_fs_min_legacy",
    "save_fs_depth_at_min",
    "save_fs_pore_pressure_at_min",
    "save_infiltration_rate",
    "save_basal_flux",
    "save_deposit_distribution",
    "save_pf",
    "save_road_risk",
    "save_road_warning",
    "save_detached_trace",
    "pressure_head_fs_listing_flag",
    "slope_failure_output_count",
    "slope_failure_output_times_s",
    "skip_other_timesteps",
    "use_analytic_fillable_porosity",
    "estimate_positive_pressure_head",
    "use_psi0_negative_inverse_alpha",
    "log_mass_balance_results",
    "flow_direction_mode",
    "background_flux_offset",
    "use_full_dynamic_wave",
    "simulate_rainfall",
    "simulate_infiltration",
    "simulate_inflow_hydrograph",
    "simulate_outflow_cell",
    "simulate_shallow_landslide",
    "simulate_debris_flow",
    "simulate_erosion",
    "simulate_water_and_solid_separately",
    "simulate_drainage_flow",
    "simulate_barrier",
    "save_fs_min_grid",
    "save_flow_depth",
    "save_max_flow_depth",
    "save_flow_velocity",
    "save_max_flow_velocity",
    "save_erosion_depth",
    "save_deposition_depth",
    "save_total_depth",
    "save_max_solid_depth",
    "save_volumetric_sediment_concentration",
    "save_outflow_process",
    "save_drainage_nodal_flow",
    "save_drainage_conduit_flow",
]


def test_bj_hxl_parser_exposes_exact_versioned_45_switch_snapshot_in_source_order():
    parsed = parse_reference_config_file(_case_config_file())

    assert list(parsed.flags) == EXPECTED_SWITCH_KEYS
    assert len(parsed.flags) == 45
    assert parsed.flags["background_flux_offset"] is True
    assert parsed.flags["simulate_barrier"] is False
    assert parsed.flags["save_max_solid_depth"] is True
    assert "save_hydrograph_cells" not in parsed.flags

    snapshot = parsed.switch_snapshot.to_dict()
    assert snapshot["registry_version"] == "1.0.0"
    assert [entry["key"] for entry in snapshot["entries"]] == EXPECTED_SWITCH_KEYS
    assert snapshot["values"]["simulate_inflow_hydrograph"] is False
    assert snapshot["values"]["simulate_barrier"] is False


def test_reference_runtime_config_carries_the_same_snapshot_in_deep_edda_controls(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())

    config, effective, manifest, provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )

    flattened = {
        **config.edda.output_controls,
        **config.edda.run_controls,
    }
    assert [key for key in EXPECTED_SWITCH_KEYS if key in flattened] == EXPECTED_SWITCH_KEYS
    assert flattened == parsed.switch_snapshot.to_dict()["values"]
    assert effective["switch_snapshot"] == parsed.switch_snapshot.to_dict()
    assert manifest["switch_snapshot"] == parsed.switch_snapshot.to_dict()
    assert provenance["switch_snapshot"] == parsed.switch_snapshot.to_dict()


def test_registry_has_complete_nine_part_trace_and_acyclic_dependency_contract():
    assert len(EDDA_SWITCH_REGISTRY) == 45
    assert [spec.source_index for spec in EDDA_SWITCH_REGISTRY] == list(range(1, 46))
    assert [spec.key for spec in EDDA_SWITCH_REGISTRY] == EXPECTED_SWITCH_KEYS

    required_trace_fields = (
        "original_variable",
        "fortran_read_location",
        "fortran_runtime_consumer",
        "activation_condition",
        "taichi_parser_field",
        "taichi_config_path",
        "taichi_runtime_consumer",
        "real_case_activation_evidence",
        "test_or_audit_artifact",
    )
    known_keys = set(EXPECTED_SWITCH_KEYS)
    for spec in EDDA_SWITCH_REGISTRY:
        assert spec.status in ALLOWED_STATUSES
        assert all(getattr(spec, field) for field in required_trace_fields)
        assert set(spec.dependencies) <= known_keys
        assert spec.frontend_policy == (
            "editable"
            if spec.status in {"production_consumed", "config_fallback_consumed"}
            else "read_only"
        )


def test_output_truth_uses_one_scalar_flow_velocity_family_and_tracks_max_solid():
    parsed = parse_reference_config_file(_case_config_file())

    expected = parsed.reference_output_expectations["expected_grid_families"]
    assert "Flow_velocity_*" in expected
    assert "Flow_velocity_*_1..8" not in expected
    assert "Maxsoliddepth_*" in expected
    assert EDDA_SWITCH_BY_KEY["save_max_solid_depth"].status == "production_consumed"


def test_repaired_dfs_controls_and_output_families_report_current_consumption_truth():
    production_consumed = {
        "simulate_rainfall",
        "simulate_infiltration",
        "simulate_outflow_cell",
        "simulate_erosion",
        "simulate_water_and_solid_separately",
        "save_flow_depth",
        "save_max_flow_depth",
        "save_flow_velocity",
        "save_max_flow_velocity",
        "save_erosion_depth",
        "save_deposition_depth",
        "save_total_depth",
        "save_max_solid_depth",
        "save_volumetric_sediment_concentration",
        "save_outflow_process",
    }

    assert {
        key: EDDA_SWITCH_BY_KEY[key].status for key in production_consumed
    } == {key: "production_consumed" for key in production_consumed}
    assert EDDA_SWITCH_BY_KEY["simulate_shallow_landslide"].status == "partial"
    assert EDDA_SWITCH_BY_KEY["simulate_debris_flow"].status == "partial"


def test_path_free_import_preserves_all_edda_controls_for_strict_runtime_gate():
    parsed = parse_reference_config_file(_case_config_file())

    values = normalized_parameter_values(parsed)

    assert values["edda.registry_version"] == parsed.switch_snapshot.registry_version
    imported = {
        key.removeprefix("edda.run_controls.").removeprefix("edda.output_controls."): value
        for key, value in values.items()
        if key.startswith(("edda.run_controls.", "edda.output_controls."))
    }
    assert imported == parsed.switch_snapshot.to_dict()["values"]


def test_current_bj_hxl_template_freezes_exact_controls_without_rewriting_v2():
    parsed = parse_reference_config_file(_case_config_file())
    template = builtin_bj_hxl_template()
    template_ids = [item["template_id"] for item in builtin_parameter_templates()]

    assert BJ_HXL_TEMPLATE_ID == "pt-bj-hxl-v3"
    assert template["version"] == "3"
    assert "pt-bj-hxl-v2" in template_ids
    assert template_ids[-1] == BJ_HXL_TEMPLATE_ID
    assert template["values"]["edda.registry_version"] == parsed.switch_snapshot.registry_version
    controls = {
        key.removeprefix("edda.run_controls.").removeprefix("edda.output_controls."): value
        for key, value in template["values"].items()
        if key.startswith(("edda.run_controls.", "edda.output_controls."))
    }
    assert controls == parsed.switch_snapshot.to_dict()["values"]
