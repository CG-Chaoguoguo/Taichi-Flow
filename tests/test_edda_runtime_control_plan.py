import os
from pathlib import Path
from threading import Event

import pytest

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.edda_semantic_gate import (
    SemanticGateViolation,
    validate_flat_edda_controls,
    validate_runtime_control_plan,
)
from api.services.reference_config_parser import parse_reference_config_file
from api.services.runtime_session import prepare_runtime_from_payload
from api.services import scheduler as scheduler_module
from api.services.scheduler import RuntimeRunExecutor
from api.services.parameter_templates import normalized_parameter_values
from api.services.structured_input_resolver import validate_scenario_configuration
from edda.config.edda_runtime_plan import build_runtime_control_plan
from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver


def _case_dir() -> Path:
    raw_case_dir = os.environ.get("EDDA_BJ_HXL_CASE_DIR")
    if not raw_case_dir:
        pytest.skip("set EDDA_BJ_HXL_CASE_DIR to run external BJ_HXL integration tests")
    case_dir = Path(raw_case_dir)
    if not (case_dir / "edda_in.txt").is_file():
        pytest.skip(f"BJ_HXL configuration is unavailable: {case_dir / 'edda_in.txt'}")
    return case_dir


def _case_config_file() -> Path:
    return _case_dir() / "edda_in.txt"


def test_reference_controls_are_frozen_while_control_free_direct_api_is_compatible(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    reference_config, *_ = build_reference_runtime_metadata(parsed, tmp_path / "reference")

    strict_plan = build_runtime_control_plan(reference_config)
    assert strict_plan.strict is True
    assert strict_plan.source_mode == "reference_config"
    assert strict_plan.run_enabled("simulate_rainfall") is True
    assert strict_plan.output_enabled("save_outflow_process") is False
    with pytest.raises(TypeError):
        strict_plan.run_controls["simulate_rainfall"] = False

    direct_config = SimulationConfig(dem_file="dem.asc")
    compatibility_plan = build_runtime_control_plan(direct_config)
    assert compatibility_plan.strict is False
    assert compatibility_plan.source_mode == "direct_api_compatibility"


def test_strict_gate_rejects_wfs_request_but_allows_control_free_direct_compatibility(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    config, *_ = build_reference_runtime_metadata(parsed, tmp_path / "reference")
    config.edda.run_controls = {**config.edda.run_controls, "simulate_debris_flow": False}

    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_runtime_control_plan(build_runtime_control_plan(config))

    assert exc_info.value.code == "edda_wfs_unsupported"
    assert exc_info.value.details["control"] == "simulate_debris_flow"
    validate_runtime_control_plan(build_runtime_control_plan(SimulationConfig(dem_file="dem.asc")))


def test_runtime_preparation_cannot_bypass_strict_gate_with_reference_override(tmp_path):
    with pytest.raises(SemanticGateViolation) as exc_info:
        prepare_runtime_from_payload(
            app_output_dir=tmp_path,
            case_config_file=str(_case_config_file()),
            case_base_dir=str(_case_dir()),
            overrides={
                "edda": {"run_controls": {"simulate_debris_flow": False}},
            },
        )

    assert exc_info.value.code == "edda_wfs_unsupported"


def test_path_free_workbench_parameters_use_the_same_strict_gate():
    parsed = parse_reference_config_file(_case_config_file())
    values = normalized_parameter_values(parsed)
    values["edda.run_controls.simulate_debris_flow"] = False

    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_flat_edda_controls(values)

    assert exc_info.value.code == "edda_wfs_unsupported"


def test_workbench_preflight_surfaces_semantic_gate_code_before_queueing():
    parsed = parse_reference_config_file(_case_config_file())
    values = normalized_parameter_values(parsed)
    values["edda.run_controls.simulate_debris_flow"] = False

    validation = validate_scenario_configuration(values, [])

    assert validation["valid"] is False
    assert "edda_wfs_unsupported" in {issue["code"] for issue in validation["issues"]}


def test_strict_debris_flow_control_selects_dfs_without_double_layer_heuristic(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    config, *_ = build_reference_runtime_metadata(parsed, tmp_path / "reference")
    solver = EDDASolver(config)
    solver.dfs_dynamic_wave = object()
    solver.double_layer = None

    assert solver._use_fortran_dfs() is True


def test_runtime_executor_preserves_semantic_gate_code_and_details(monkeypatch, tmp_path):
    violation = SemanticGateViolation(
        code="edda_unsfin_schedule_required",
        message="validated UNSFIN schedule required",
        details={"control": "simulate_shallow_landslide", "configured_value": True},
    )

    def reject_preparation(**_kwargs):
        raise violation

    monkeypatch.setattr(scheduler_module, "prepare_runtime_from_payload", reject_preparation)
    executor = RuntimeRunExecutor(reset_runtime_on_dispose=False)

    result = executor.execute(
        {"simulation_id": "sim-semantic-gate", "project_root": str(tmp_path)},
        lambda _update: None,
        Event(),
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "edda_unsfin_schedule_required"
    assert result["error_details"] == {
        "control": "simulate_shallow_landslide",
        "configured_value": True,
    }


def test_exact_bj_runtime_gate_rejects_missing_unsfin_schedule_before_stepping(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    config, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "exact-bj",
    )
    plan = build_runtime_control_plan(config)

    outflow_entry = next(
        item
        for item in runtime_input_manifest["inputs"]
        if item.get("family") == "outflow.txt"
    )
    outflow_entry["consumed"] = True
    outflow_entry["structure_summary"] = {
        **(outflow_entry.get("structure_summary") or {}),
        "configured_cell_count": 13,
    }

    validate_runtime_control_plan(plan)
    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_runtime_control_plan(
            plan,
            runtime_input_manifest=runtime_input_manifest,
        )

    assert exc_info.value.code == "edda_unsfin_schedule_required"
    assert exc_info.value.details["control"] == "simulate_shallow_landslide"


def test_runtime_gate_requires_configured_outflow_sidecar_when_enabled(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    config, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "outflow-not-configured",
    )
    config.edda.run_controls = {
        **config.edda.run_controls,
        "simulate_shallow_landslide": False,
    }

    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_runtime_control_plan(
            build_runtime_control_plan(config),
            runtime_input_manifest=runtime_input_manifest,
        )

    assert exc_info.value.code == "edda_outflow_sidecar_required"
    assert exc_info.value.details["control"] == "simulate_outflow_cell"


def test_strict_gate_rejects_unsupported_detailed_unsfin_listing(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    config, *_ = build_reference_runtime_metadata(parsed, tmp_path / "detailed-listing")
    config.edda.output_controls = {
        **config.edda.output_controls,
        "pressure_head_fs_listing_flag": -2,
    }

    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_runtime_control_plan(build_runtime_control_plan(config))

    assert exc_info.value.code == "edda_detailed_unsfin_listing_unsupported"
    assert exc_info.value.details["control"] == "pressure_head_fs_listing_flag"


@pytest.mark.parametrize(
    ("group", "key", "malformed_value"),
    [
        ("run_controls", "simulate_debris_flow", "false"),
        ("output_controls", "pressure_head_fs_listing_flag", "-2"),
    ],
)
def test_strict_gate_rejects_stringly_typed_control_values(
    tmp_path, group, key, malformed_value
):
    parsed = parse_reference_config_file(_case_config_file())
    config, *_ = build_reference_runtime_metadata(parsed, tmp_path / key)
    controls = dict(getattr(config.edda, group))
    controls[key] = malformed_value
    setattr(config.edda, group, controls)

    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_runtime_control_plan(build_runtime_control_plan(config))

    assert exc_info.value.code == "edda_control_value_invalid"
    assert exc_info.value.details["control"] == key


def test_strict_gate_reports_unknown_control_as_structured_snapshot_error(tmp_path):
    parsed = parse_reference_config_file(_case_config_file())
    config, *_ = build_reference_runtime_metadata(parsed, tmp_path / "unknown-control")
    config.edda.run_controls = {
        **config.edda.run_controls,
        "unexpected_control": True,
    }

    with pytest.raises(SemanticGateViolation) as exc_info:
        validate_runtime_control_plan(build_runtime_control_plan(config))

    assert exc_info.value.code == "edda_control_snapshot_incomplete"
    assert exc_info.value.details["unknown_run_controls"] == ["unexpected_control"]
