"""Chamoli EDDA 1.5 variant: six-value sediment line, triggerslide, debrisflowmanning."""

from pathlib import Path

import pytest

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.reference_config_parser import parse_reference_config_file


CHAMOLI = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file")
BJ_HXL = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text")
TEST31 = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Test31-1_cvlandslide0.50+cs0.7")


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_chamoli_edda_in_uses_six_value_sediment_line_and_triggerslide(tmp_path):
    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))

    assert parsed.d50 == pytest.approx(0.035)
    assert parsed.cvstar == pytest.approx(0.6)
    assert parsed.cvglacier == pytest.approx(0.3)
    assert parsed.cvlandslide == pytest.approx(0.55)
    assert parsed.coedepo == pytest.approx(0.001)
    assert parsed.cs == pytest.approx(0.7)
    assert parsed.debrisflowmanning == pytest.approx(0.070)
    assert parsed.shallown == pytest.approx(0.2)
    assert parsed.dfs_manningbar_variant == "debrisflowmanning_cvtol"
    assert parsed.dfs_face_flux_variant == "arithmetic_mean_chamoli"
    assert parsed.dfs_dry_face_velocity_variant == "zero_dry_face_chamoli"
    assert parsed.dfs_artivis_variant == "velocity_ratio_chamoli"
    assert parsed.dfs_absubar_variant == "signed_mean_chamoli"
    assert parsed.dfs_flow_velocity_writer_variant == "absubar_chamoli"
    assert parsed.dfs_erosion_depth_writer_variant == "cumulative_erodph_chamoli"
    assert parsed.dfs_sfdf_classify_cv_variant == "predicted_step_cv_chamoli"
    assert parsed.dfs_cvlimit_variant == "tan_slo_unit_clamp_chamoli"
    assert parsed.dfs_erodph_dt_variant == "post_dti_dt_chamoli"
    assert parsed.dfs_barrier_flux_variant == "chamoli_scour_kill_or"
    assert parsed.dfs_commit_cv_eps_variant == "eps_clamp_chamoli"
    assert parsed.manningb == pytest.approx(1.0)
    assert parsed.manningm == pytest.approx(0.0)
    assert "area-mean `cvbar`" in (parsed.dfs_face_flux_variant_basis or "")
    assert "triggerslide" in parsed.file_inputs
    assert parsed.file_inputs["triggerslide"].original_branch_active is True
    assert parsed.file_inputs["triggerslide"].current_backend_branch_active is True
    assert parsed.file_inputs["triggerslide"].exists == [True]
    assert parsed.extension_flags.get("simulate_buildings") is False
    assert parsed.flags["simulate_rainfall"] is False
    assert parsed.flags["simulate_infiltration"] is False
    assert parsed.flags["simulate_inflow_hydrograph"] is True
    assert parsed.flags["simulate_outflow_cell"] is True
    assert parsed.flags["simulate_shallow_landslide"] is False
    assert parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule"
    assert parsed.dfs_failure_source_topology_status == "recognized"
    assert parsed.flags["simulate_debris_flow"] is True
    assert parsed.flags["simulate_erosion"] is True
    assert parsed.flags["simulate_water_and_solid_separately"] is True
    assert parsed.flags["simulate_drainage_flow"] is False
    assert parsed.flags["simulate_barrier"] is False
    assert parsed.flags["save_max_solid_depth"] is None
    assert parsed.flags["save_volumetric_sediment_concentration"] is True
    assert parsed.flags["save_outflow_process"] is False

    config, _effective, manifest, _provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )
    assert config.rheology.cvlandslide == pytest.approx(0.55)
    assert config.rheology.debrisflowmanning == pytest.approx(0.070)
    assert config.hydrology.dfs_manningbar_variant == "debrisflowmanning_cvtol"
    assert config.hydrology.dfs_face_flux_variant == "arithmetic_mean_chamoli"
    assert config.hydrology.dfs_dry_face_velocity_variant == "zero_dry_face_chamoli"
    assert config.hydrology.dfs_artivis_variant == "velocity_ratio_chamoli"
    assert config.hydrology.dfs_absubar_variant == "signed_mean_chamoli"
    assert config.hydrology.dfs_flow_velocity_writer_variant == "absubar_chamoli"
    assert config.hydrology.dfs_erosion_depth_writer_variant == "cumulative_erodph_chamoli"
    assert config.hydrology.dfs_sfdf_classify_cv_variant == "predicted_step_cv_chamoli"
    assert config.hydrology.dfs_cvlimit_variant == "tan_slo_unit_clamp_chamoli"
    assert config.hydrology.dfs_erodph_dt_variant == "post_dti_dt_chamoli"
    assert config.hydrology.dfs_barrier_flux_variant == "chamoli_scour_kill_or"
    assert config.hydrology.dfs_commit_cv_eps_variant == "eps_clamp_chamoli"
    assert config.rheology.manningb == pytest.approx(1.0)
    assert config.rheology.manningm == pytest.approx(0.0)
    families = {entry["family"]: entry for entry in manifest["inputs"]}
    assert families["triggerslide"]["path"]
    assert Path(families["triggerslide"]["path"]).exists()
    assert "precomputed_unsfin_schedule" not in families
    registry = manifest["input_source_registry"]["dfs_failure_source_variant"]
    assert registry["effective_mode"] == "disabled"
    assert registry["skip_reason"] == "control_off"
    assert registry["runtime_active"] is False
    assert registry["blocked_reason"] is None
    assert config.edda.run_controls["simulate_shallow_landslide"] is False


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_chamoli_normalized_parameters_include_debrisflow_fields():
    from api.services.parameter_templates import normalized_parameter_values

    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    values = normalized_parameter_values(parsed)
    assert values["compute.use_double_precision"] is True
    assert values["rheology.debrisflowmanning"] == pytest.approx(0.070)
    assert values["rheology.cvlandslide"] == pytest.approx(0.55)
    assert values["rheology.cvglacier"] == pytest.approx(0.3)
    assert values["erosion.d50"] == pytest.approx(0.035)
    assert values["erosion.coedepo"] == pytest.approx(0.001)
    assert values["rheology.cs"] == pytest.approx(0.7)
    assert values["hydrology.dfs_face_flux_variant"] == "arithmetic_mean_chamoli"
    assert values["hydrology.dfs_manningbar_variant"] == "debrisflowmanning_cvtol"
    assert values["hydrology.dfs_dry_face_velocity_variant"] == "zero_dry_face_chamoli"
    assert values["hydrology.dfs_artivis_variant"] == "velocity_ratio_chamoli"
    assert values["hydrology.dfs_absubar_variant"] == "signed_mean_chamoli"
    assert values["hydrology.dfs_flow_velocity_writer_variant"] == "absubar_chamoli"
    assert values["hydrology.dfs_erosion_depth_writer_variant"] == "cumulative_erodph_chamoli"
    assert values["hydrology.dfs_sfdf_classify_cv_variant"] == "predicted_step_cv_chamoli"
    assert values["hydrology.dfs_cvlimit_variant"] == "tan_slo_unit_clamp_chamoli"
    assert values["hydrology.dfs_erodph_dt_variant"] == "post_dti_dt_chamoli"
    assert values["hydrology.dfs_barrier_flux_variant"] == "chamoli_scour_kill_or"
    assert values["hydrology.dfs_commit_cv_eps_variant"] == "eps_clamp_chamoli"
    assert values["hydrology.dfs_failure_source_variant"] == "precomputed_unsfin_schedule"
    assert values["edda.output_controls.save_max_solid_depth"] is False
    assert parsed.flags["save_max_solid_depth"] is None


@pytest.mark.skipif(not (TEST31 / "edda_in.txt").exists(), reason="Test31 reference case is not on disk")
def test_test31_uses_its_weighted_signed_absubar_lineage(tmp_path):
    """Test31 is a separate DFS source lineage, not a Chamoli alias."""
    from api.services.parameter_templates import normalized_parameter_values

    parsed = parse_reference_config_file(str(TEST31 / "edda_in.txt"), str(TEST31))

    assert parsed.dfs_absubar_variant == "weighted_signed_test31"
    assert parsed.dfs_barrier_flux_variant == "chamoli_scour_kill_or"
    assert parsed.dfs_commit_cv_eps_variant == "eps_clamp_chamoli"
    assert parsed.manningb == pytest.approx(1.0)
    assert parsed.manningm == pytest.approx(0.0)
    assert "0.4142" in (parsed.dfs_absubar_variant_basis or "")
    assert "0.2929" in (parsed.dfs_absubar_variant_basis or "")

    values = normalized_parameter_values(parsed)
    assert values["hydrology.dfs_absubar_variant"] == "weighted_signed_test31"

    config, _effective, _manifest, _provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )
    assert config.hydrology.dfs_absubar_variant == "weighted_signed_test31"


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_chamoli_workbench_preflight_ignores_inactive_rainfall_and_absent_maxsoliddepth():
    from api.services.edda_semantic_gate import validate_flat_edda_controls
    from api.services.parameter_templates import normalized_parameter_values
    from api.services.structured_input_resolver import validate_scenario_configuration

    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    values = normalized_parameter_values(parsed)
    bindings = [{"binding_key": "dem.primary", "role": "primary", "active": True}]

    gate = validate_flat_edda_controls({**values, "edda.output_controls.save_max_solid_depth": None})
    assert gate["decision"] == "allow_supported_edda_semantics"

    validation = validate_scenario_configuration(values, bindings)
    codes = {issue["code"] for issue in validation["issues"]}
    assert "rainfall_end_time_mismatch" not in codes
    assert "rainfall_periods_empty" not in codes
    assert "edda_control_value_invalid" not in codes
    assert "rainfall_inactive_schedule_ignored" in codes
    assert validation["valid"] is True

    rainfall_on = dict(values)
    rainfall_on["edda.run_controls.simulate_rainfall"] = True
    blocked = validate_scenario_configuration(rainfall_on, bindings)
    assert "rainfall_end_time_mismatch" in {issue["code"] for issue in blocked["issues"]}
    assert blocked["valid"] is False


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_chamoli_zone_cvero_and_zfil_erodible_wiring(tmp_path):
    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))

    expected_cvero = {1: 0.6, 2: 0.3, 3: 0.4, 4: 0.55}
    assert parsed.ltstar_raw < 0
    for zone_id, cvero in expected_cvero.items():
        assert parsed.zones[zone_id].top.cvero == pytest.approx(cvero)

    from api.services.parameter_templates import normalized_parameter_values

    values = normalized_parameter_values(parsed)
    zones = values["spatial_zones.zones"]
    for zone_id, cvero in expected_cvero.items():
        assert zones[str(zone_id)]["cvero"] == pytest.approx(cvero)

    config, _effective, manifest, _provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )
    for zone_id, cvero in expected_cvero.items():
        assert config.spatial_zones.zones[zone_id].cvero == pytest.approx(cvero)

    families = {entry["family"]: entry for entry in manifest["inputs"]}
    assert families["zfil"]["production_status"] == "production-reachable"
    assert families["zfil"]["current_backend_branch_active"] is True
    assert Path(families["zfil"]["path"]).exists()


@pytest.mark.skipif(not (BJ_HXL / "edda_in.txt").exists(), reason="BJ_HXL reference case is not on disk")
def test_bj_hxl_four_value_sediment_line_is_unchanged():
    parsed = parse_reference_config_file(str(BJ_HXL / "edda_in.txt"), str(BJ_HXL))

    assert parsed.d50 == pytest.approx(0.001)
    assert parsed.cvstar == pytest.approx(0.65)
    assert parsed.coedepo == pytest.approx(0.005)
    assert parsed.cs == pytest.approx(0.7)
    assert parsed.cvglacier is None
    assert parsed.cvlandslide is None
    assert parsed.debrisflowmanning is None
    assert parsed.shallown == pytest.approx(0.2)
    assert parsed.dfs_manningbar_variant == "exponential_cv"
    assert parsed.dfs_face_flux_variant == "both_thin_weighted"
    assert parsed.dfs_dry_face_velocity_variant == "keep_velocity_bj"
    assert parsed.dfs_artivis_variant == "depth_ratio_bj"
    assert parsed.dfs_absubar_variant == "max_component_bj"
    assert parsed.dfs_flow_velocity_writer_variant == "half_sum_abs_fv_bj"
    assert parsed.dfs_erosion_depth_writer_variant == "net_bed_change_bj"
    assert parsed.dfs_sfdf_classify_cv_variant == "previous_committed_cv"
    assert parsed.dfs_cvlimit_variant == "tanslo_cycle_cvstar_clamp_bj"
    assert parsed.dfs_erodph_dt_variant == "accepted_dt_bj"
    assert parsed.dfs_barrier_flux_variant == "bj_barrier_branch"
    assert parsed.dfs_commit_cv_eps_variant == "no_clamp_bj"
    assert parsed.manningb == pytest.approx(0.0538)
    assert parsed.manningm == pytest.approx(6.0896)
    assert "triggerslide" not in parsed.file_inputs
    for zone in parsed.zones.values():
        assert zone.top.cvero is None


@pytest.mark.skipif(not (BJ_HXL / "edda_in.txt").exists(), reason="BJ_HXL reference case is not on disk")
def test_bj_zone_cvero_falls_back_to_sentinel_in_zone_params(tmp_path):
    import numpy as np

    from edda.config.sim_config import ZoneParams
    from edda.io.zone_reader import ZoneReader

    parsed = parse_reference_config_file(str(BJ_HXL / "edda_in.txt"), str(BJ_HXL))
    config, *_ = build_reference_runtime_metadata(parsed, tmp_path / "output")
    for zone in config.spatial_zones.zones.values():
        assert zone.cvero is None

    # BJ zone tops omit cvero; zone_reader must emit the -1 sentinel so rhoero
    # falls back to global cvstar at runtime.
    zr = ZoneReader.__new__(ZoneReader)
    zr.zone_grid = np.array([[1, 1], [1, 1]], dtype=np.int32)
    zone_id = next(iter(config.spatial_zones.zones))
    zone = config.spatial_zones.zones[zone_id]
    assert isinstance(zone, ZoneParams)
    _mask, zone_params = ZoneReader.apply_zone_parameters(
        zr,
        {1: zone},
        grid_shape=(2, 2),
    )
    assert zone_params.shape[1] >= 28
    assert float(zone_params[0, 27]) == pytest.approx(-1.0)


NO5_20A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a")
NO5_50A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_50a\NO.5_XHG_V2_50a")
NO8 = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.8_AYG_V2")


@pytest.mark.parametrize(
    "case_dir, barrier, cv_eps, manningb, manningm, absubar",
    [
        (CHAMOLI, "chamoli_scour_kill_or", "eps_clamp_chamoli", 1.0, 0.0, "signed_mean_chamoli"),
        (TEST31, "chamoli_scour_kill_or", "eps_clamp_chamoli", 1.0, 0.0, "weighted_signed_test31"),
        (BJ_HXL, "bj_barrier_branch", "no_clamp_bj", 0.0538, 6.0896, "max_component_bj"),
        (NO5_20A, "bj_barrier_branch", "no_clamp_bj", 0.0538, 6.0896, "max_component_bj"),
        (NO5_50A, "bj_barrier_branch", "no_clamp_bj", 0.0538, 6.0896, "max_component_bj"),
        (NO8, "bj_barrier_branch", "no_clamp_bj", 0.0538, 6.0896, "max_component_bj"),
    ],
)
def test_six_reference_cases_resolve_barrier_cv_eps_and_manning_coefficients(
    case_dir, barrier, cv_eps, manningb, manningm, absubar
):
    edda_in = case_dir / "edda_in.txt"
    if not edda_in.exists():
        pytest.skip(f"{case_dir} reference case is not on disk")
    parsed = parse_reference_config_file(str(edda_in), str(case_dir))
    assert parsed.dfs_barrier_flux_variant == barrier
    assert parsed.dfs_commit_cv_eps_variant == cv_eps
    assert parsed.manningb == pytest.approx(manningb)
    assert parsed.manningm == pytest.approx(manningm)
    assert parsed.dfs_absubar_variant == absubar


def test_test31_absubar_literals_match_default_real_source_weights():
    from edda.solver.fortran_literals import (
        DFS_TEST31_ABSUBAR_CARDINAL_WEIGHT,
        DFS_TEST31_ABSUBAR_DIAGONAL_GROUP_WEIGHT,
        default_real,
    )

    assert float(DFS_TEST31_ABSUBAR_CARDINAL_WEIGHT) == default_real(0.4142)
    assert float(DFS_TEST31_ABSUBAR_DIAGONAL_GROUP_WEIGHT) == default_real(0.2929)
