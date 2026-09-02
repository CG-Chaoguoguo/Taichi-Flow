"""Real-solver source-selection regressions for native input chains."""

from pathlib import Path

import numpy as np

from api.services.edda_input_mapper import (
    apply_native_runtime_inputs,
    build_direct_runtime_metadata,
    build_reference_runtime_metadata,
)
from api.services.reference_config_parser import parse_reference_config_file
from api.services.runtime_audit import build_output_manifest
from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver
from tests.test_native_input_chain import _make_reference_case, _write_ascii_grid


def _initialize_real_solver(edda_in: Path, output_dir: Path, *, config_overrides=None):
    parsed = parse_reference_config_file(str(edda_in))
    config, _, runtime_input_manifest, provenance = build_reference_runtime_metadata(
        parsed,
        output_dir,
        config_overrides={
            "compute": {
                "backend": "cpu",
                "use_double_precision": True,
            },
            "save_intermediate": False,
            **(config_overrides or {}),
        },
    )
    solver = EDDASolver(config)
    solver.initialize()
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)
    return solver, runtime_input_manifest, parsed, provenance


def test_real_solver_initialize_applies_raster_manning_field(tmp_path):
    edda_in = _make_reference_case(tmp_path)

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_raster")

    expected = np.array([[0.1, 0.11], [0.12, 0.13]], dtype=np.float64).T
    np.testing.assert_allclose(solver.fields.n_manning_field.to_numpy(), expected)
    np.testing.assert_allclose(solver.rheology.manning.to_numpy(), expected)

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["manningfil"]["consumed"] is True
    assert manifest["manning_global"]["consumed"] is False


def test_real_solver_initialize_falls_back_to_global_manning_constant(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "Data" / "tutorial" / "manning.asc").unlink()

    solver, runtime_input_manifest, parsed, _ = _initialize_real_solver(edda_in, tmp_path / "out_global")

    expected = np.full((solver.fields.nx, solver.fields.ny), parsed.manning_global, dtype=np.float64)
    np.testing.assert_allclose(solver.fields.n_manning_field.to_numpy(), expected)

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["manningfil"]["consumed"] is False
    assert manifest["manning_global"]["consumed"] is True
    assert manifest["manningfil"]["missing_on_disk"] is True
    assert "global initiation Manning" in manifest["manningfil"]["notes"]


def test_real_solver_uses_uniform_cri_interval_average(tmp_path):
    edda_in = _make_reference_case(tmp_path)

    solver, _, parsed, _ = _initialize_real_solver(edda_in, tmp_path / "out_uniform_rain")

    rainfall = solver._get_rainfall_field_for_interval(0.0, 3600.0)
    expected = np.full((solver.fields.nx, solver.fields.ny), parsed.cri_mps[0], dtype=np.float64)
    np.testing.assert_allclose(rainfall, expected, rtol=1e-12, atol=1e-12)


def test_real_solver_uses_mixed_rifil_and_uniform_periods(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    tutorial_dir = edda_in.parent / "Data" / "tutorial"
    rifil_grid = np.array([[1.0e-6, 2.0e-6], [3.0e-6, 4.0e-6]], dtype=np.float64)
    _write_ascii_grid(tutorial_dir / "ri1.txt", rifil_grid)
    _write_ascii_grid(tutorial_dir / "ri2.txt", np.full((2, 2), 5.55556e-08, dtype=np.float64))
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(text.replace("3.33333e-07 5.55556e-08", "-1 5.55556e-08"), encoding="utf-8")

    solver, runtime_input_manifest, _, provenance = _initialize_real_solver(edda_in, tmp_path / "out_mixed_rain")

    rain_first = solver._get_rainfall_field_for_interval(0.0, 3600.0)
    rain_second = solver._get_rainfall_field_for_interval(3600.0, 7200.0)

    np.testing.assert_allclose(rain_first, rifil_grid.T, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(
        rain_second,
        np.full((solver.fields.nx, solver.fields.ny), 5.55556e-08, dtype=np.float64),
        rtol=1e-12,
        atol=1e-12,
    )

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert provenance["period_source_map"]["1"]["source"] == "rifil_grid"
    assert provenance["period_source_map"]["2"]["source"] == "uniform_cri"
    assert manifest["rainfall_spatial_series"]["consumed"] is True
    assert manifest["rifil"]["consumed"] is True


def test_real_solver_double_layer_consumes_reference_uww(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(text.replace("9.8e3", "1.2345e4", 1), encoding="utf-8")

    solver, _, parsed, _ = _initialize_real_solver(edda_in, tmp_path / "out_uww")

    assert parsed.uww == 12345.0
    assert solver.config.soil.double_layer is not None
    assert solver.config.soil.double_layer.uww == 12345.0
    assert solver.double_layer is not None
    assert solver.double_layer.uww == 12345.0


def test_direct_payload_real_solver_consumes_core_fields_and_background_flux_flag(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))

    config = SimulationConfig.from_dict(
        {
            "dem_file": str(dem_file),
            "output_dir": str(tmp_path / "out_direct"),
            "save_intermediate": False,
            "compute": {
                "backend": "cpu",
                "use_double_precision": True,
            },
            "hydrology": {
                "K_sat": 2.5e-5,
                "theta_s": 0.41,
                "theta_i": 0.19,
                "psi_f": 0.08,
                "use_background_flux_offset": True,
            },
            "soil": {
                "c": 1200.0,
                "phi": 27.0,
                "gamma_s": 19000.0,
                "gamma_w": 9800.0,
                "depth": 2.0,
            },
            "rheology": {
                "n_manning": 0.07,
            },
        }
    )
    _, runtime_input_manifest, _ = build_direct_runtime_metadata(config)

    solver = EDDASolver(config)
    solver.initialize()
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)

    np.testing.assert_allclose(solver.fields.K_sat_field.to_numpy(), np.full((2, 2), 2.5e-5, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.theta_s_field.to_numpy(), np.full((2, 2), 0.41, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.theta_i_field.to_numpy(), np.full((2, 2), 0.19, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.psi_f_field.to_numpy(), np.full((2, 2), 0.08, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.c_field.to_numpy(), np.full((2, 2), 1200.0, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.phi_field.to_numpy(), np.full((2, 2), 27.0, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.gamma_s_field.to_numpy(), np.full((2, 2), 19000.0, dtype=np.float64))
    np.testing.assert_allclose(solver.fields.n_manning_field.to_numpy(), np.full((2, 2), 0.07, dtype=np.float64))
    assert solver.dfs_dynamic_wave.use_background_flux is True

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["demfil"]["consumed"] is True


def test_real_solver_consumes_depfil_and_rizerofil_when_original_branches_are_active(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace("-1, 4, 7, 7, 1.0e-9, 0.1", "-1, 4, 7, -1, -1, 0.1"),
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_dep_rizero")
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}

    expected_depth = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float64).T
    expected_rizero = np.array([[1.0e-9, 1.0e-9], [1.0e-9, 1.0e-9]], dtype=np.float64).T

    np.testing.assert_allclose(solver.dfs_dynamic_wave.depthwt0_field.to_numpy(), expected_depth)
    np.testing.assert_allclose(solver.dfs_dynamic_wave.rizero0_field.to_numpy(), expected_rizero)
    assert manifest["depfil"]["consumed"] is True
    assert manifest["rizerofil"]["consumed"] is True


def test_real_solver_consumes_inflow_sidecar_when_original_branch_is_active(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace(
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)\nF",
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)\nT",
        ),
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(
        edda_in,
        tmp_path / "out_inflow",
        config_overrides={
            "time": {
                "t_end": 2.0,
                "dt_output": 1.0,
            },
        },
    )

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["inflow.txt"]["consumed"] is True
    assert manifest["inflow.txt"]["current_backend_branch_active"] is True
    assert solver.inflow_hydrograph_config is not None
    assert solver.inflow_hydrograph_config["configured_cell_count"] == 1

    configured = solver.inflow_hydrograph_config["configured_preview"][0]
    solver.dfs_dynamic_wave.set_current_time(0.0)
    # The fixture's first inflow pulse has a CFL limit below one second.
    # This test verifies sidecar consumption, so use a stable candidate
    # step instead of accidentally asserting against the reject mechanism.
    step_info = solver.dfs_dynamic_wave.step(0.05)

    assert step_info["accepted"] is True
    assert solver.fields.tempinflowh.to_numpy().sum() > 0.0
    assert solver.fields.tempinflowrho.to_numpy()[configured["i"], configured["j"]] > solver.config.rheology.rho_water


def test_real_solver_uses_source_detected_celsiz_fv_inflow_denominator(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace(
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)\nF",
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)\nT",
        ),
        encoding="utf-8",
    )
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "      do k=1,noinflow",
                "          if (inflowht(k,j)<=tnow .and. tnext<=inflowht(k,j+1)) then",
                "              fv(i,4) = 5",
                "              tempinflowh(i)=inflowhq(k,j+1)*dt/celsiz/fv(i,4)",
                "          end if",
                "      end do",
                "      if (infilsimul) then",
                "      do i=1,imx1",
                "          fhw(i)=fh(i)*(1-cv(i)/cvstar)",
                "          inflx(i)=tempri(i) +(tempinflowh(i)+fhw(i))/dt",
                "      end do",
                "      end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(
        edda_in,
        tmp_path / "out_inflow_celsiz_fv",
        config_overrides={
            "time": {
                "t_end": 2.0,
                "dt_output": 1.0,
            },
        },
    )

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert runtime_input_manifest["input_source_registry"]["inflow_denominator_variant"]["selected_source"] == "CELSIZ_DIRECTIONAL_VELOCITY"
    assert manifest["inflow.txt"]["structure_summary"]["inflow_denominator_variant"] == "CELSIZ_DIRECTIONAL_VELOCITY"

    solver.dfs_dynamic_wave.set_current_time(0.0)
    tempinflowh, _ = solver.dfs_dynamic_wave._build_inflow_stage_arrays(0.0, 1.0)
    diagnostics = solver.dfs_dynamic_wave.get_inflow_forcing_diagnostics()

    assert diagnostics["samples"][0]["denominator_value"] == 5.0
    assert np.isclose(float(tempinflowh.sum()), 0.3)

    configured = solver.inflow_hydrograph_config["configured_preview"][0]
    fv_before = solver.fields.fv_fortran.to_numpy()
    direction = int(solver.inflow_hydrograph_config["inflow_denominator_direction"]) - 1
    assert np.isclose(float(fv_before[configured["i"], configured["j"], direction]), 0.0)

    solver.dfs_dynamic_wave._stage_inflow_forcing(1.0)
    fv_after = solver.fields.fv_fortran.to_numpy()
    diagnostics = solver.dfs_dynamic_wave.get_inflow_forcing_diagnostics()

    assert diagnostics["directional_velocity_injected_count"] == 1
    assert diagnostics["directional_velocity_direction"] == 4
    assert diagnostics["directional_velocity_value"] == 5.0
    assert np.isclose(float(fv_after[configured["i"], configured["j"], direction]), 5.0)


def test_real_solver_preserves_cellareacal_inflow_denominator_variant(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace(
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)\nF",
            "Simulate inflow hydrograph? Enter T (.true.) or F (.false.)\nT",
        ),
        encoding="utf-8",
    )
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "      do k=1,noinflow",
                "          if (inflowht(k,j)<=tnow .and. tnext<=inflowht(k,j+1)) then",
                "              tempinflowh(i)=inflowhq(k,j+1)*dt/cellareacal(i)",
                "          end if",
                "      end do",
                "      if (infilsimul) then",
                "      do i=1,imx1",
                "          fhw(i)=fh(i)*(1-cv(i)/cvstar)",
                "          inflx(i)=tempri(i) +(tempinflowh(i)+fhw(i))/dt",
                "      end do",
                "      end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(
        edda_in,
        tmp_path / "out_inflow_cellareacal",
        config_overrides={
            "time": {
                "t_end": 2.0,
                "dt_output": 1.0,
            },
        },
    )

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert runtime_input_manifest["input_source_registry"]["inflow_denominator_variant"]["selected_source"] == "CELLAREACAL"
    assert manifest["inflow.txt"]["structure_summary"]["inflow_denominator_variant"] == "CELLAREACAL"

    tempinflowh, _ = solver.dfs_dynamic_wave._build_inflow_stage_arrays(0.0, 1.0)
    diagnostics = solver.dfs_dynamic_wave.get_inflow_forcing_diagnostics()

    assert diagnostics["samples"][0]["denominator_value"] == 1.0
    assert np.isclose(float(tempinflowh.sum()), 1.5)


def test_real_solver_exports_partial_outnq_process_file(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    solver, _, _, provenance = _initialize_real_solver(
        edda_in,
        tmp_path / "out_outflow_process",
        config_overrides={
            "time": {
                "t_end": 2.0,
                "dt_output": 1.0,
            },
        },
    )

    solver.run()
    solver.export_final_results()

    outflow_files = list((tmp_path / "out_outflow_process").glob("OUTNQ_*.txt"))
    assert outflow_files, "Expected partial original-style OUTNQ export."
    content = outflow_files[0].read_text(encoding="utf-8")
    assert "THE MAX Q AT OUTFLOW ELEMENT" in content
    assert "TIME (HRS)" in content

    output_manifest = build_output_manifest(
        tmp_path / "out_outflow_process",
        reference_output_expectations=provenance["reference_output_expectations"],
    )
    parity = {entry["artifact"]: entry for entry in output_manifest["reference_output_parity"]["artifact_status"]}
    assert parity["OUTNQ_*"]["parity_status"] == "present"


def test_real_solver_consumes_direct_rain_plus_storage_dfs_variant_when_bundled_source_matches(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace("3.33333e-07 5.55556e-08", "3.0e-06 5.55556e-08"),
        encoding="utf-8",
    )
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "      if (infilsimul) then",
                "      do i=1,imx1",
                "          fhw(i)=fh(i)*(1-cv(i)/cvstar)",
                "          inflx(i)=tempri(i) +(tempinflowh(i)+fhw(i))/dt",
                "      end do",
                "      end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_direct_variant")
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}

    assert solver.dfs_dynamic_wave.dfs_infiltration_variant == "direct_rain_plus_storage"
    assert runtime_input_manifest["input_source_registry"]["dfs_infiltration_variant"]["selected_source"] == "direct_rain_plus_storage"

    rainfall = solver._get_rainfall_field_for_interval(0.0, 1.0)
    solver.fields.rainfall.from_numpy(rainfall.astype(np.float64, copy=False))
    solver.dfs_dynamic_wave.set_current_time(0.0)
    step_info = solver.dfs_dynamic_wave.step(1.0)

    assert step_info["accepted"] is True
    assert manifest["rainfall_schedule"]["consumed"] is True
    assert solver.fields.infiltration.to_numpy().max() > 0.0
    assert solver.fields.infiltration.to_numpy().max() <= solver.fields.K_sat_top_field.to_numpy().max()


def test_real_solver_consumes_both_thin_weighted_face_flux_variant_when_bundled_source_matches(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        if (fhpredi(i)<=tol .and. fhpredi(nq)<=tol) then",
                "        fvpredi(i,ii)=0.",
                "        end if",
                "        hbar=(fhpredi(i) * cellareacal(i) +fhpredi(nq) * cellareacal(nq)) / (cellareacal(i)+cellareacal(nq))",
                "        cvbar=(parai* cellareacal(i)+paran* cellareacal(nq)) / (fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))",
                "        frhobar=(frhopredi(i)*fhpredi(i)* cellareacal(i)+frhopredi(nq)*fhpredi(nq)* cellareacal(nq))/ (fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_face_variant")

    assert solver.dfs_dynamic_wave.dfs_face_flux_variant == "both_thin_weighted"
    assert runtime_input_manifest["input_source_registry"]["dfs_face_flux_variant"]["selected_source"] == "both_thin_weighted"


def test_real_solver_consumes_precomputed_unsfin_failure_source_variant_when_bundled_source_matches(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        !if (fssimul) then",
                "        !    if (tnow<60.) tnow=60.",
                "        !    call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)",
                "        !end if",
                "        if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
                "            tempfsh(i)=fsdepth(i)",
                "            tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
                "        end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (edda_in.parent / "edda main program.F90").write_text(
        "if (fssimul) call unsfin(imx1,u(19),u(2),profil)\n",
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_failure_variant")

    assert solver.dfs_dynamic_wave.dfs_failure_source_variant == "precomputed_unsfin_schedule"
    assert runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]["selected_source"] == "precomputed_unsfin_schedule"
    assert runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]["runtime_equivalent_implemented"] is False
    assert runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]["runtime_active"] is False


def test_real_solver_loads_original_precomputed_unsfin_schedule_artifacts(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        !if (fssimul) then",
                "        !    if (tnow<60.) tnow=60.",
                "        !    call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)",
                "        !end if",
                "        if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
                "            tempfsh(i)=fsdepth(i)",
                "            tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
                "        end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (edda_in.parent / "edda main program.F90").write_text(
        "if (fssimul) call unsfin(imx1,u(19),u(2),profil)\n",
        encoding="utf-8",
    )
    _write_ascii_grid(edda_in.parent / "precomputed_unsfin_gindx.txt", np.array([[1, 0], [0, 1]], dtype=np.float64))
    _write_ascii_grid(edda_in.parent / "precomputed_unsfin_tfail.txt", np.array([[100.0, 9999.0], [9999.0, 700.0]], dtype=np.float64))
    _write_ascii_grid(edda_in.parent / "precomputed_unsfin_fdepth.txt", np.array([[0.2, 0.0], [0.0, 0.4]], dtype=np.float64))
    (edda_in.parent / "precomputed_unsfin_meta.json").write_text(
        '{"shape_kind":"dem_yx_grid","provider":"original_instrumented_unsfin","dump_point":"after unsfin returns and before dfs enters"}\n',
        encoding="utf-8",
    )

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_failure_artifacts")
    registry = runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}

    assert registry["selected_source"] == "precomputed_unsfin_schedule"
    assert registry["schedule_provider"] == "uploaded_schedule"
    assert registry["schedule_provider_detail"] == "original_tfail_artifacts"
    assert registry["schedule_loaded"] is True
    assert registry["runtime_equivalent_implemented"] is True
    assert registry["runtime_active"] is True
    assert registry["consumed_count"] == 2
    assert manifest["precomputed_unsfin_schedule"]["consumed"] is True
    assert manifest["precomputed_unsfin_schedule"]["structure_summary"]["tfail_lte_600_count"] == 1
    assert solver.dfs_dynamic_wave.get_precomputed_failure_schedule_diagnostics()["scheduled_cell_count"] == 2
