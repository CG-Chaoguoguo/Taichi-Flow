from pathlib import Path

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.edda_switch_registry import (
    ALLOWED_STATUSES,
    EDDA_SWITCH_REGISTRY,
)
from api.services.reference_config_parser import parse_reference_config_file


CASE_DIR = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text"
)


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
    parsed = parse_reference_config_file(CASE_DIR / "edda_in.txt")

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
    parsed = parse_reference_config_file(CASE_DIR / "edda_in.txt")

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
