"""Catalog / enum gate coverage for DFS face-flux and Manning-bar variants."""

from api.services.parameter_catalog import (
    EDITABLE_PARAMETERS,
    PARAMETER_ENUM_SPECS,
    build_static_parameter_catalog,
)
from api.services.structured_input_resolver import validate_scenario_configuration


def test_static_catalog_exposes_editable_dfs_variant_enums():
    catalog = build_static_parameter_catalog()
    by_key = {entry["key"]: entry for entry in catalog["parameters"]}

    face = by_key["hydrology.dfs_face_flux_variant"]
    manning = by_key["hydrology.dfs_manningbar_variant"]
    dry_face = by_key["hydrology.dfs_dry_face_velocity_variant"]
    artivis = by_key["hydrology.dfs_artivis_variant"]
    absubar = by_key["hydrology.dfs_absubar_variant"]
    boundary = by_key["boundary_conditions.mode"]

    assert face["editable"] is True
    assert face["value_type"] == "enum"
    assert face["allowed_values"] == PARAMETER_ENUM_SPECS["hydrology.dfs_face_flux_variant"]["allowed_values"]
    assert face["allowed_value_labels_zh"]["both_thin_weighted"] == "双薄层加权平均（BJ 默认）"
    assert manning["editable"] is True
    assert manning["value_type"] == "enum"
    assert manning["allowed_values"] == PARAMETER_ENUM_SPECS["hydrology.dfs_manningbar_variant"]["allowed_values"]
    assert dry_face["editable"] is True
    assert dry_face["value_type"] == "enum"
    assert dry_face["allowed_values"] == ["keep_velocity_bj", "zero_dry_face_chamoli"]
    assert dry_face["allowed_value_labels_zh"]["zero_dry_face_chamoli"] == "干面上游清零（Chamoli）"
    assert artivis["editable"] is True
    assert artivis["value_type"] == "enum"
    assert artivis["allowed_values"] == ["depth_ratio_bj", "velocity_ratio_chamoli"]
    assert artivis["allowed_value_labels_zh"]["velocity_ratio_chamoli"] == "速度比权重（Chamoli）"
    assert absubar["editable"] is True
    assert absubar["value_type"] == "enum"
    assert absubar["allowed_values"] == ["max_component_bj", "signed_mean_chamoli"]
    assert absubar["allowed_value_labels_zh"]["signed_mean_chamoli"] == "有符号合成速度（Chamoli）"
    assert boundary["editable"] is True
    assert boundary["value_type"] == "enum"
    assert boundary["allowed_values"] == ["auto", "file", "manual"]
    assert boundary["allowed_value_labels_zh"]["auto"] == "自动检测"
    assert "hydrology.dfs_face_flux_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_manningbar_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_dry_face_velocity_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_artivis_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_absubar_variant" in EDITABLE_PARAMETERS
    policy = by_key["hydrology.dfs_failure_source_policy"]
    assert policy["editable"] is True
    assert policy["allowed_values"] == ["disabled", "precomputed", "live"]
    assert "hydrology.dfs_failure_source_policy" in EDITABLE_PARAMETERS


def test_scenario_configuration_rejects_invalid_boundary_enum():
    bindings = [{"binding_key": "dem.primary", "role": "primary", "active": True}]
    parameters = {
        "boundary_conditions.default_type": "not_a_boundary",
        "edda.run_controls.simulate_rainfall": False,
    }
    result = validate_scenario_configuration(parameters, bindings)
    codes = {issue["code"] for issue in result["issues"]}
    assert "parameter_enum_invalid" in codes
    assert result["valid"] is False


def test_scenario_configuration_rejects_invalid_face_flux_enum():
    bindings = [{"binding_key": "dem.primary", "role": "primary", "active": True}]
    parameters = {
        "hydrology.dfs_face_flux_variant": "not_a_real_variant",
    }
    result = validate_scenario_configuration(parameters, bindings)
    codes = {issue["code"] for issue in result["issues"]}
    assert "parameter_enum_invalid" in codes
    assert result["valid"] is False


def test_scenario_configuration_accepts_chamoli_and_bj_variant_defaults():
    bindings = [{"binding_key": "dem.primary", "role": "primary", "active": True}]
    for face, manning, dry_face, artivis, absubar in (
        ("arithmetic_mean_chamoli", "debrisflowmanning_cvtol", "zero_dry_face_chamoli", "velocity_ratio_chamoli", "signed_mean_chamoli"),
        ("both_thin_weighted", "exponential_cv", "keep_velocity_bj", "depth_ratio_bj", "max_component_bj"),
    ):
        parameters = {
            "hydrology.dfs_face_flux_variant": face,
            "hydrology.dfs_manningbar_variant": manning,
            "hydrology.dfs_dry_face_velocity_variant": dry_face,
            "hydrology.dfs_artivis_variant": artivis,
            "hydrology.dfs_absubar_variant": absubar,
            # Satisfy rainfall preflight without engaging the EDDA control gate.
            "rainfall.periods": [
                {
                    "period_id": "period-0001",
                    "index": 1,
                    "start_s": 0.0,
                    "end_s": 3600.0,
                    "source": "uniform",
                    "cri_mps": 0.0,
                }
            ],
            "rainfall.timeline": {
                "mode": "regular",
                "start_s": 0.0,
                "end_s": 3600.0,
                "interval_s": 3600.0,
                "period_count": 1,
            },
        }
        result = validate_scenario_configuration(parameters, bindings)
        codes = {issue["code"] for issue in result["issues"]}
        assert "parameter_enum_invalid" not in codes
        assert result["valid"] is True
