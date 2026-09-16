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
    flow_velocity_writer = by_key["hydrology.dfs_flow_velocity_writer_variant"]
    erosion_depth_writer = by_key["hydrology.dfs_erosion_depth_writer_variant"]
    sfdf_classify_cv = by_key["hydrology.dfs_sfdf_classify_cv_variant"]
    cvlimit = by_key["hydrology.dfs_cvlimit_variant"]
    erodph_dt = by_key["hydrology.dfs_erodph_dt_variant"]
    barrier_flux = by_key["hydrology.dfs_barrier_flux_variant"]
    commit_cv_eps = by_key["hydrology.dfs_commit_cv_eps_variant"]
    boundary = by_key["boundary_conditions.mode"]

    assert face["editable"] is True
    assert face["value_type"] == "enum"
    assert face["allowed_values"] == PARAMETER_ENUM_SPECS["hydrology.dfs_face_flux_variant"]["allowed_values"]
    assert face["allowed_value_labels_zh"]["both_thin_weighted"] == "双薄层加权平均"
    assert manning["editable"] is True
    assert manning["value_type"] == "enum"
    assert manning["allowed_values"] == PARAMETER_ENUM_SPECS["hydrology.dfs_manningbar_variant"]["allowed_values"]
    assert dry_face["editable"] is True
    assert dry_face["value_type"] == "enum"
    assert dry_face["allowed_values"] == ["keep_velocity_bj", "zero_dry_face_chamoli"]
    assert dry_face["allowed_value_labels_zh"]["zero_dry_face_chamoli"] == "干面上游清零"
    assert artivis["editable"] is True
    assert artivis["value_type"] == "enum"
    assert artivis["allowed_values"] == ["depth_ratio_bj", "velocity_ratio_chamoli"]
    assert artivis["allowed_value_labels_zh"]["velocity_ratio_chamoli"] == "速度比权重"
    assert absubar["editable"] is True
    assert absubar["value_type"] == "enum"
    assert absubar["allowed_values"] == ["max_component_bj", "signed_mean_chamoli", "weighted_signed_test31"]
    assert absubar["allowed_value_labels_zh"]["signed_mean_chamoli"] == "有符号合成速度"
    assert absubar["allowed_value_labels_zh"]["weighted_signed_test31"] == "Test31加权有符号速度"
    assert flow_velocity_writer["editable"] is True
    assert flow_velocity_writer["value_type"] == "enum"
    assert flow_velocity_writer["allowed_values"] == ["half_sum_abs_fv_bj", "absubar_chamoli"]
    assert flow_velocity_writer["allowed_value_labels_zh"]["absubar_chamoli"] == "Chamoli有向合成absubar"
    assert erosion_depth_writer["editable"] is True
    assert erosion_depth_writer["value_type"] == "enum"
    assert erosion_depth_writer["allowed_values"] == ["net_bed_change_bj", "cumulative_erodph_chamoli"]
    assert erosion_depth_writer["allowed_value_labels_zh"]["cumulative_erodph_chamoli"] == "累计侵蚀erodph"
    assert sfdf_classify_cv["editable"] is True
    assert sfdf_classify_cv["value_type"] == "enum"
    assert sfdf_classify_cv["allowed_values"] == ["previous_committed_cv", "predicted_step_cv_chamoli"]
    assert sfdf_classify_cv["allowed_value_labels_zh"]["predicted_step_cv_chamoli"] == "本步预测cv"
    assert cvlimit["editable"] is True
    assert cvlimit["value_type"] == "enum"
    assert cvlimit["allowed_values"] == ["tanslo_cycle_cvstar_clamp_bj", "tan_slo_unit_clamp_chamoli"]
    assert cvlimit["allowed_value_labels_zh"]["tan_slo_unit_clamp_chamoli"] == "Chamoli每步重算·1.0上限"
    assert erodph_dt["editable"] is True
    assert erodph_dt["value_type"] == "enum"
    assert erodph_dt["allowed_values"] == ["accepted_dt_bj", "post_dti_dt_chamoli"]
    assert erodph_dt["allowed_value_labels_zh"]["post_dti_dt_chamoli"] == "dti后dt_next"
    assert barrier_flux["editable"] is True
    assert barrier_flux["value_type"] == "enum"
    assert barrier_flux["allowed_values"] == ["bj_barrier_branch", "chamoli_scour_kill_or"]
    assert barrier_flux["allowed_value_labels_zh"]["chamoli_scour_kill_or"] == "Chamoli负向面·低于原地面清零"
    assert commit_cv_eps["editable"] is True
    assert commit_cv_eps["value_type"] == "enum"
    assert commit_cv_eps["allowed_values"] == ["no_clamp_bj", "eps_clamp_chamoli"]
    assert commit_cv_eps["allowed_value_labels_zh"]["eps_clamp_chamoli"] == "cv<eps归零"
    assert boundary["editable"] is True
    assert boundary["value_type"] == "enum"
    assert boundary["allowed_values"] == ["auto", "file", "manual"]
    assert boundary["allowed_value_labels_zh"]["auto"] == "自动检测"
    assert "hydrology.dfs_face_flux_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_manningbar_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_dry_face_velocity_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_artivis_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_absubar_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_flow_velocity_writer_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_erosion_depth_writer_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_sfdf_classify_cv_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_cvlimit_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_erodph_dt_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_barrier_flux_variant" in EDITABLE_PARAMETERS
    assert "hydrology.dfs_commit_cv_eps_variant" in EDITABLE_PARAMETERS
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


def test_scenario_configuration_rejects_invalid_flow_velocity_writer_enum():
    bindings = [{"binding_key": "dem.primary", "role": "primary", "active": True}]
    parameters = {
        "hydrology.dfs_flow_velocity_writer_variant": "not_a_real_writer",
    }
    result = validate_scenario_configuration(parameters, bindings)
    codes = {issue["code"] for issue in result["issues"]}
    assert "parameter_enum_invalid" in codes
    assert result["valid"] is False


def test_scenario_configuration_accepts_chamoli_and_bj_variant_defaults():
    bindings = [{"binding_key": "dem.primary", "role": "primary", "active": True}]
    for (
        face,
        manning,
        dry_face,
        artivis,
        absubar,
        flow_velocity_writer,
        erosion_depth_writer,
        sfdf_classify_cv,
        cvlimit,
        erodph_dt,
        barrier_flux,
        commit_cv_eps,
    ) in (
        (
            "arithmetic_mean_chamoli",
            "debrisflowmanning_cvtol",
            "zero_dry_face_chamoli",
            "velocity_ratio_chamoli",
            "signed_mean_chamoli",
            "absubar_chamoli",
            "cumulative_erodph_chamoli",
            "predicted_step_cv_chamoli",
            "tan_slo_unit_clamp_chamoli",
            "post_dti_dt_chamoli",
            "chamoli_scour_kill_or",
            "eps_clamp_chamoli",
        ),
        (
            "arithmetic_mean_chamoli",
            "debrisflowmanning_cvtol",
            "zero_dry_face_chamoli",
            "velocity_ratio_chamoli",
            "weighted_signed_test31",
            "absubar_chamoli",
            "cumulative_erodph_chamoli",
            "predicted_step_cv_chamoli",
            "tan_slo_unit_clamp_chamoli",
            "post_dti_dt_chamoli",
            "chamoli_scour_kill_or",
            "eps_clamp_chamoli",
        ),
        (
            "both_thin_weighted",
            "exponential_cv",
            "keep_velocity_bj",
            "depth_ratio_bj",
            "max_component_bj",
            "half_sum_abs_fv_bj",
            "net_bed_change_bj",
            "previous_committed_cv",
            "tanslo_cycle_cvstar_clamp_bj",
            "accepted_dt_bj",
            "bj_barrier_branch",
            "no_clamp_bj",
        ),
    ):
        parameters = {
            "hydrology.dfs_face_flux_variant": face,
            "hydrology.dfs_manningbar_variant": manning,
            "hydrology.dfs_dry_face_velocity_variant": dry_face,
            "hydrology.dfs_artivis_variant": artivis,
            "hydrology.dfs_absubar_variant": absubar,
            "hydrology.dfs_flow_velocity_writer_variant": flow_velocity_writer,
            "hydrology.dfs_erosion_depth_writer_variant": erosion_depth_writer,
            "hydrology.dfs_sfdf_classify_cv_variant": sfdf_classify_cv,
            "hydrology.dfs_cvlimit_variant": cvlimit,
            "hydrology.dfs_erodph_dt_variant": erodph_dt,
            "hydrology.dfs_barrier_flux_variant": barrier_flux,
            "hydrology.dfs_commit_cv_eps_variant": commit_cv_eps,
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
