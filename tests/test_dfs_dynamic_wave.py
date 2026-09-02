import numpy as np
import taichi as ti

from edda.config.sim_config import DoubleLayerSoilParams, SimulationConfig
from edda.core.fields import EDDAFields
from edda.solver.dfs_dynamic_wave import (
    DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV,
    DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV,
    DFS_EROSION_DEPOSITION_MUTATE_ENV,
    DFS_FACE_GATE_TOL_EPS_ENV,
    DFS_FACE_FLUX_KERNEL_ENV,
    DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV,
    DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV,
    DFS_H_CV_RHO_MUTATE_ENV,
    DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT_ENV,
    DFS_ORIGINAL_LIVE_MOVING_THIN_FACE_GATE_COMPAT_ENV,
    DFS_ORIGINAL_PREDICTOR_RETRY_GATES_ENV,
    DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV,
    DFS_PREDICTOR_MUTATE_ENV,
    DFS_QNET_QMASSNET_KERNEL_ENV,
    DFS_QNET_QMASSNET_MUTATE_ENV,
    DFS_SOURCE_STAGING_FIELD_ENV,
    DFS_SOURCE_STAGING_FAST_CONSUME_ENV,
    DFS_SOURCE_STAGING_KERNEL_ENV,
    FIRST_REJECT_CFL,
    FIRST_REJECT_DEPTH_CHANGE,
    DFSDynamicWaveSolver,
    GPU_ONLY_PRODUCTION_SMOKE_ENV,
    PROJECT_CUDA_BACKEND_STAGE2_ENV,
    RNOFF_GPU_FIELD_FEED_ENV,
    _green_ampt_average_infiltration_rate,
)
from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
from edda.solver.edda_solver import EDDASolver


def _build_config(
    *,
    face_flux_variant: str = "asymmetric_head_guard",
    failure_source_variant: str = "live_doublelayer_in_dfs",
    dry_face_velocity_variant: str = "keep_velocity_bj",
    artivis_variant: str = "depth_ratio_bj",
    absubar_variant: str = "max_component_bj",
) -> SimulationConfig:
    return SimulationConfig.from_dict(
        {
            "dem_file": "dummy.asc",
            "output_dir": "./output",
            "save_intermediate": False,
            "compute": {
                "backend": "cpu",
                "use_double_precision": True,
            },
            "time": {
                "dt_min": 1.0e-5,
                "dt_max": 1.0,
                "dt_increase": 1.0e-3,
                "dt_decrease": 5.0e-2,
                "toldh": 10.0,
                "toldhp": 10.0,
            },
            "hydrology": {
                "K_sat": 1.0e-6,
                "depthwt_initial": 7.0,
                "rizero_initial": 1.0e-9,
                "dfs_face_flux_variant": face_flux_variant,
                "dfs_failure_source_variant": failure_source_variant,
                "dfs_dry_face_velocity_variant": dry_face_velocity_variant,
                "dfs_artivis_variant": artivis_variant,
                "dfs_absubar_variant": absubar_variant,
            },
            "rheology": {
                "rho_water": 1000.0,
                "rho_sediment": 2650.0,
                "Cv_max": 0.65,
                "limitfr": 1.0,
                "kresis": 2500.0,
                "cs": 0.5,
            },
            "erosion": {
                "d50": 0.002,
                "coedepo": 0.01,
            },
        }
    )


def _with_strict_run_controls(config: SimulationConfig, **overrides: bool) -> SimulationConfig:
    controls = {
        "simulate_debris_flow": True,
        "simulate_rainfall": True,
        "simulate_infiltration": True,
        "simulate_inflow_hydrograph": False,
        "simulate_outflow_cell": False,
        "simulate_shallow_landslide": True,
        "simulate_drainage_flow": False,
        "simulate_erosion": True,
        "simulate_water_and_solid_separately": True,
        "simulate_barrier": False,
    }
    controls.update(overrides)
    config.edda.run_controls = controls
    return config


def _build_fields() -> EDDAFields:
    fields = EDDAFields(2, 1, 10.0, 10.0, fp_dtype=ti.f64)
    z = np.array([[1.0], [0.0]], dtype=np.float64)
    nodata = np.zeros((2, 1), dtype=np.int32)
    cell_id = np.array([[1], [2]], dtype=np.int32)
    neighbor_id = np.zeros((2, 1, 8), dtype=np.int32)
    neighbor_i = np.full((2, 1, 8), -1, dtype=np.int32)
    neighbor_j = np.full((2, 1, 8), -1, dtype=np.int32)

    # Fortran order [N, NE, E, SE, S, SW, W, NW]
    neighbor_id[0, 0, 2] = 2
    neighbor_i[0, 0, 2] = 1
    neighbor_j[0, 0, 2] = 0
    neighbor_id[1, 0, 6] = 1
    neighbor_i[1, 0, 6] = 0
    neighbor_j[1, 0, 6] = 0

    fields.initialize_from_numpy(z)
    fields.set_nodata_mask(nodata)
    fields.initialize_all()
    fields.set_flow_connectivity(cell_id, neighbor_id, neighbor_i, neighbor_j)

    h = np.array([[0.5], [0.5]], dtype=np.float64)
    rho = np.array([[1000.0], [1000.0]], dtype=np.float64)
    rain = np.zeros((2, 1), dtype=np.float64)
    fields.h.from_numpy(h)
    fields.rho.from_numpy(rho)
    fields.rainfall.from_numpy(rain)
    fields.z_bed.from_numpy(z)

    return fields


def test_strict_background_flux_uses_immutable_runtime_plan_value():
    cfg = _with_strict_run_controls(
        _build_config(),
        background_flux_offset=True,
        simulate_shallow_landslide=False,
    )
    cfg.hydrology.use_background_flux_offset = False
    fields = _build_fields()

    solver = DFSDynamicWaveSolver(
        fields,
        cfg,
        FortranDynamicWaveWorkspace(fields),
    )

    assert solver.runtime_control_plan.strict is True
    assert solver.use_background_flux is True


def test_dfs_step_accepts_small_dt_and_updates_pairwise_velocity():
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    result = solver.step(1.0e-3)

    assert result["accepted"] is True

    fv = fields.fv_fortran.to_numpy()
    assert fv[0, 0, 2] != 0.0
    assert np.isclose(fv[0, 0, 2], -fv[1, 0, 6])


def test_dfs_outflow_sample_uses_accepted_pre_clear_predictor_state():
    cfg = _build_config()
    fields = _build_fields()
    fields.dfs_outflow_mask.from_numpy(np.array([[0], [1]], dtype=np.int32))
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))

    result = solver.step(1.0e-3)

    assert result["accepted"] is True
    assert float(fields.h[1, 0]) == 0.0
    samples = solver.get_last_accepted_outflow_samples(
        [{"cell_id": 2, "i": 1, "j": 0}],
        dt_used=float(result["used_dt"]),
    )
    assert samples[0]["predictor_depth"] > 0.0
    assert samples[0]["discharge_cms"] > 0.0


def test_generic_boundary_metadata_does_not_remove_dfs_face_pair():
    cfg = _with_strict_run_controls(
        _build_config(), simulate_shallow_landslide=False
    )
    fields = _build_fields()
    fields.set_boundary_conditions(
        np.array([[1], [0]], dtype=np.int32),
        np.array([[1], [0]], dtype=np.int32),
    )
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))

    source_i, source_j, target_i, target_j = solver._ensure_legacy_fortran_order_face_pairs()

    assert list(zip(source_i, source_j, target_i, target_j)) == [(0, 0, 1, 0)]


def test_outer_boundary_clear_is_direct_compatibility_only():
    class _AcceptedDFS:
        @staticmethod
        def set_current_time(_time):
            return None

        @staticmethod
        def step(dt):
            return {"accepted": True, "used_dt": dt}

    remaining_depth = []
    for strict in (False, True):
        cfg = _build_config()
        if strict:
            cfg = _with_strict_run_controls(
                cfg, simulate_shallow_landslide=False
            )
        cfg.soil.double_layer = DoubleLayerSoilParams(enabled=True)
        fields = _build_fields()
        fields.set_boundary_conditions(
            np.array([[1], [0]], dtype=np.int32),
            np.array([[1], [0]], dtype=np.int32),
        )
        solver = EDDASolver(cfg)
        solver.fields = fields
        solver.double_layer = object()
        solver.dfs_dynamic_wave = _AcceptedDFS()
        solver.time_stepper = type("_Time", (), {"t_current": 0.0})()

        solver._physics_step(1.0e-3)
        remaining_depth.append(float(fields.h[0, 0]))

    assert remaining_depth == [0.0, 0.5]


def test_strict_shallow_landslide_false_skips_outer_stability_calls():
    class _AcceptedDFS:
        @staticmethod
        def set_current_time(_time):
            return None

        @staticmethod
        def step(dt):
            return {"accepted": True, "used_dt": dt}

    class _Hydrology:
        def step(self, _dt):
            return None

    class _Stability:
        def __init__(self):
            self.calls = []

        def step(self, **kwargs):
            self.calls.append(("step", kwargs))

        def populate_failure_source_terms(self, **kwargs):
            self.calls.append(("populate_failure_source_terms", kwargs))

    cfg = _with_strict_run_controls(
        _build_config(), simulate_shallow_landslide=False
    )
    solver = EDDASolver(cfg)
    solver.fields = _build_fields()
    solver.hydrology = _Hydrology()
    solver.stability = _Stability()
    solver.dfs_dynamic_wave = _AcceptedDFS()
    solver.time_stepper = type("_Time", (), {"t_current": 0.0})()

    solver._physics_step(1.0e-3)

    assert solver.stability.calls == []


def test_strict_infiltration_false_keeps_rainfall_but_stages_zero_infiltration():
    cfg = _with_strict_run_controls(
        _build_config(),
        simulate_infiltration=False,
        simulate_shallow_landslide=False,
        simulate_erosion=False,
        simulate_water_and_solid_separately=False,
    )
    fields = _build_fields()
    fields.rainfall.from_numpy(np.full((2, 1), 1.0e-3, dtype=np.float64))
    fields.K_sat_top_field.fill(1.0e-4)
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))

    solver.step(1.0e-3)

    np.testing.assert_allclose(fields.tempri.to_numpy(), 1.0e-3)
    np.testing.assert_allclose(fields.infiltration.to_numpy(), 0.0)


def test_strict_false_process_controls_zero_rain_and_skip_failure_advancement():
    cfg = _with_strict_run_controls(
        _build_config(),
        simulate_rainfall=False,
        simulate_infiltration=False,
        simulate_shallow_landslide=False,
        simulate_erosion=False,
        simulate_water_and_solid_separately=False,
    )
    fields = _build_fields()
    fields.rainfall.from_numpy(np.full((2, 1), 1.0e-3, dtype=np.float64))
    fields.dfs_outflow_mask.from_numpy(np.array([[0], [1]], dtype=np.int32))
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))
    fake = _FakeDoubleLayerModel()
    solver.set_double_layer_model(fake)

    solver.step(1.0e-3)

    np.testing.assert_allclose(fields.tempri.to_numpy(), 0.0)
    np.testing.assert_allclose(fields.infiltration.to_numpy(), 0.0)
    np.testing.assert_allclose(fields.erosion_rate.to_numpy(), 0.0)
    np.testing.assert_allclose(fields.deposition_rate.to_numpy(), 0.0)
    assert np.count_nonzero(fields.dfs_outflow_mask.to_numpy()) == 0
    assert fake.calls == []


def test_accepted_commit_tracks_max_solid_depth_without_decreasing_history():
    cfg = _build_config()
    fields = _build_fields()
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))
    rho_water = cfg.rheology.rho_water
    rho_sediment = cfg.rheology.rho_sediment
    density_span = rho_sediment - rho_water

    fields.fhpredi2.from_numpy(np.array([[2.0], [1.0]], dtype=np.float64))
    fields.frhopredi2.from_numpy(
        np.array([[rho_water + 0.25 * density_span], [rho_water + 0.50 * density_span]], dtype=np.float64)
    )
    fields.tempele.from_numpy(fields.z_bed.to_numpy())
    solver._commit_step(0.1, 0.1, rho_water, rho_sediment, cfg.rheology.Cv_max)
    np.testing.assert_allclose(fields.max_solid_depth.to_numpy(), np.array([[0.5], [0.5]]))

    fields.fhpredi2.from_numpy(np.array([[0.5], [0.25]], dtype=np.float64))
    fields.frhopredi2.from_numpy(
        np.array([[rho_water + 0.10 * density_span], [rho_water + 0.20 * density_span]], dtype=np.float64)
    )
    solver._commit_step(0.1, 0.1, rho_water, rho_sediment, cfg.rheology.Cv_max)
    np.testing.assert_allclose(fields.max_solid_depth.to_numpy(), np.array([[0.5], [0.5]]))


def test_paired_face_flux_variant_opens_face_when_only_one_cell_is_thin():
    cfg = _build_config(face_flux_variant="both_thin_weighted")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.h.from_numpy(np.array([[0.005], [0.02]], dtype=np.float64))
    fields.rho.from_numpy(np.array([[1000.0], [1000.0]], dtype=np.float64))

    result = solver.step(1.0e-3)

    assert result["accepted"] is True
    fv = fields.fv_fortran.to_numpy()
    assert fv[0, 0, 2] != 0.0
    assert np.isclose(fv[0, 0, 2], -fv[1, 0, 6])


def test_fortran_face_owner_lower_cell_is_default_and_max_cell_is_opt_in(monkeypatch):
    monkeypatch.delenv(DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV, raising=False)
    cfg = _build_config(face_flux_variant="both_thin_weighted")
    fields_lower_cell_default = _build_fields()
    fields_lower_cell_default.h.from_numpy(np.array([[0.08], [0.03]], dtype=np.float64))
    fields_lower_cell_default.rho.from_numpy(np.array([[1000.0], [1010.0]], dtype=np.float64))
    fv_seed = np.zeros((2, 1, 8), dtype=np.float64)
    fv_seed[0, 0, 2] = 0.40
    fv_seed[0, 0, 6] = -0.05
    fv_seed[1, 0, 2] = 0.12
    fv_seed[1, 0, 6] = -0.20
    fields_lower_cell_default.fv_fortran.from_numpy(fv_seed)
    solver_lower_cell_default = DFSDynamicWaveSolver(
        fields_lower_cell_default,
        cfg,
        FortranDynamicWaveWorkspace(fields_lower_cell_default),
    )

    result_lower_cell_default = solver_lower_cell_default.step(1.0e-3)
    fv_lower_cell_default = fields_lower_cell_default.fv_fortran.to_numpy().copy()

    monkeypatch.setenv(DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV, "1")
    fields_max_cell_opt_in = _build_fields()
    fields_max_cell_opt_in.h.from_numpy(np.array([[0.08], [0.03]], dtype=np.float64))
    fields_max_cell_opt_in.rho.from_numpy(np.array([[1000.0], [1010.0]], dtype=np.float64))
    fields_max_cell_opt_in.fv_fortran.from_numpy(fv_seed)
    solver_max_cell_opt_in = DFSDynamicWaveSolver(
        fields_max_cell_opt_in,
        cfg,
        FortranDynamicWaveWorkspace(fields_max_cell_opt_in),
    )

    result_max_cell_opt_in = solver_max_cell_opt_in.step(1.0e-3)
    fv_max_cell_opt_in = fields_max_cell_opt_in.fv_fortran.to_numpy()

    assert result_lower_cell_default["accepted"] is True
    assert result_max_cell_opt_in["accepted"] is True
    assert solver_lower_cell_default.fortran_face_owner_max_cell_enabled is False
    assert solver_max_cell_opt_in.fortran_face_owner_max_cell_enabled is True
    assert np.isclose(fv_lower_cell_default[0, 0, 2], -fv_lower_cell_default[1, 0, 6])
    assert np.isclose(fv_max_cell_opt_in[0, 0, 2], -fv_max_cell_opt_in[1, 0, 6])
    assert not np.isclose(fv_lower_cell_default[0, 0, 2], fv_max_cell_opt_in[0, 0, 2])


def test_both_thin_weighted_face_flux_consumes_cellareacal_weights():
    cfg = _build_config(face_flux_variant="both_thin_weighted")

    fields_equal_area = _build_fields()
    fields_equal_area.h.from_numpy(np.array([[0.08], [0.03]], dtype=np.float64))
    fields_equal_area.rho.from_numpy(np.array([[1000.0], [1100.0]], dtype=np.float64))
    solver_equal_area = DFSDynamicWaveSolver(
        fields_equal_area,
        cfg,
        FortranDynamicWaveWorkspace(fields_equal_area),
    )

    fields_weighted_area = _build_fields()
    fields_weighted_area.h.from_numpy(np.array([[0.08], [0.03]], dtype=np.float64))
    fields_weighted_area.rho.from_numpy(np.array([[1000.0], [1100.0]], dtype=np.float64))
    fields_weighted_area.cell_area_cal.from_numpy(np.array([[100.0], [400.0]], dtype=np.float64))
    solver_weighted_area = DFSDynamicWaveSolver(
        fields_weighted_area,
        cfg,
        FortranDynamicWaveWorkspace(fields_weighted_area),
    )

    result_equal_area = solver_equal_area.step(1.0e-3)
    result_weighted_area = solver_weighted_area.step(1.0e-3)

    fv_weighted_area = fields_weighted_area.fv_fortran.to_numpy()
    qq_equal_area = fields_equal_area.qq_fortran.to_numpy()
    qq_weighted_area = fields_weighted_area.qq_fortran.to_numpy()

    assert result_equal_area["accepted"] is True
    assert result_weighted_area["accepted"] is True
    assert np.isclose(fv_weighted_area[0, 0, 2], -fv_weighted_area[1, 0, 6])
    assert np.isclose(qq_weighted_area[0, 0, 2], -qq_weighted_area[1, 0, 6])
    assert not np.isclose(qq_equal_area[0, 0, 2], qq_weighted_area[0, 0, 2])


def test_arithmetic_mean_chamoli_face_flux_diverges_from_both_thin_weighted_on_unequal_depth():
    """Wet/dry-front Cv/rho averages differ between Chamoli arithmetic and BJ depth-weighted."""
    h_values = np.array([[0.20], [0.02]], dtype=np.float64)
    rho_values = np.array([[1800.0], [1000.0]], dtype=np.float64)

    fields_weighted = _build_fields()
    fields_weighted.h.from_numpy(h_values.copy())
    fields_weighted.rho.from_numpy(rho_values.copy())
    solver_weighted = DFSDynamicWaveSolver(
        fields_weighted,
        _build_config(face_flux_variant="both_thin_weighted"),
        FortranDynamicWaveWorkspace(fields_weighted),
    )

    fields_chamoli = _build_fields()
    fields_chamoli.h.from_numpy(h_values.copy())
    fields_chamoli.rho.from_numpy(rho_values.copy())
    solver_chamoli = DFSDynamicWaveSolver(
        fields_chamoli,
        _build_config(face_flux_variant="arithmetic_mean_chamoli"),
        FortranDynamicWaveWorkspace(fields_chamoli),
    )

    assert solver_chamoli.dfs_face_flux_variant == "arithmetic_mean_chamoli"
    result_weighted = solver_weighted.step(1.0e-3)
    result_chamoli = solver_chamoli.step(1.0e-3)

    qq_weighted = fields_weighted.qq_fortran.to_numpy()
    qq_chamoli = fields_chamoli.qq_fortran.to_numpy()
    fv_weighted = fields_weighted.fv_fortran.to_numpy()
    fv_chamoli = fields_chamoli.fv_fortran.to_numpy()

    assert result_weighted["accepted"] is True
    assert result_chamoli["accepted"] is True
    assert np.isclose(fv_chamoli[0, 0, 2], -fv_chamoli[1, 0, 6])
    assert np.isclose(qq_chamoli[0, 0, 2], -qq_chamoli[1, 0, 6])
    assert not np.isclose(qq_weighted[0, 0, 2], qq_chamoli[0, 0, 2])
    assert not np.isclose(fv_weighted[0, 0, 2], fv_chamoli[0, 0, 2])


def test_zero_dry_face_chamoli_clears_predicted_velocity_from_dry_upstream():
    """Chamoli zeros fvpredi when the owning (upstream) cell is thinner than tol."""
    h_values = np.array([[0.005], [0.20]], dtype=np.float64)
    rho_values = np.array([[1000.0], [1000.0]], dtype=np.float64)

    fields_keep = _build_fields()
    fields_keep.h.from_numpy(h_values.copy())
    fields_keep.rho.from_numpy(rho_values.copy())
    solver_keep = DFSDynamicWaveSolver(
        fields_keep,
        _build_config(
            face_flux_variant="arithmetic_mean_chamoli",
            dry_face_velocity_variant="keep_velocity_bj",
        ),
        FortranDynamicWaveWorkspace(fields_keep),
    )

    fields_zero = _build_fields()
    fields_zero.h.from_numpy(h_values.copy())
    fields_zero.rho.from_numpy(rho_values.copy())
    solver_zero = DFSDynamicWaveSolver(
        fields_zero,
        _build_config(
            face_flux_variant="arithmetic_mean_chamoli",
            dry_face_velocity_variant="zero_dry_face_chamoli",
        ),
        FortranDynamicWaveWorkspace(fields_zero),
    )

    assert solver_zero.dfs_dry_face_velocity_variant == "zero_dry_face_chamoli"
    result_keep = solver_keep.step(1.0e-3)
    result_zero = solver_zero.step(1.0e-3)
    assert result_keep["accepted"] is True
    assert result_zero["accepted"] is True

    fv_keep = fields_keep.fv_fortran.to_numpy()
    fv_zero = fields_zero.fv_fortran.to_numpy()
    # Owner cell (0,0) is dry (h=0.005 < tol); Chamoli must not emit into (1,0).
    assert np.isclose(fv_zero[0, 0, 2], 0.0)
    assert np.isclose(fv_zero[1, 0, 6], 0.0)
    assert not np.isclose(fv_keep[0, 0, 2], 0.0)


def test_velocity_ratio_chamoli_artivis_diverges_from_depth_ratio_bj():
    """Unequal depths + seeded face velocity make the two artivis weights differ."""
    h_values = np.array([[0.20], [0.02]], dtype=np.float64)
    rho_values = np.array([[1000.0], [1000.0]], dtype=np.float64)
    fv_seed = np.zeros((2, 1, 8), dtype=np.float64)
    fv_seed[0, 0, 2] = 1.0
    fv_seed[1, 0, 6] = -1.0

    fields_bj = _build_fields()
    fields_bj.h.from_numpy(h_values.copy())
    fields_bj.rho.from_numpy(rho_values.copy())
    fields_bj.fv_fortran.from_numpy(fv_seed.copy())
    solver_bj = DFSDynamicWaveSolver(
        fields_bj,
        _build_config(
            face_flux_variant="arithmetic_mean_chamoli",
            artivis_variant="depth_ratio_bj",
        ),
        FortranDynamicWaveWorkspace(fields_bj),
    )

    fields_ch = _build_fields()
    fields_ch.h.from_numpy(h_values.copy())
    fields_ch.rho.from_numpy(rho_values.copy())
    fields_ch.fv_fortran.from_numpy(fv_seed.copy())
    solver_ch = DFSDynamicWaveSolver(
        fields_ch,
        _build_config(
            face_flux_variant="arithmetic_mean_chamoli",
            artivis_variant="velocity_ratio_chamoli",
        ),
        FortranDynamicWaveWorkspace(fields_ch),
    )

    assert solver_ch.dfs_artivis_variant == "velocity_ratio_chamoli"
    result_bj = solver_bj.step(1.0e-3)
    result_ch = solver_ch.step(1.0e-3)
    assert result_bj["accepted"] is True
    assert result_ch["accepted"] is True

    fv_bj = fields_bj.fv_fortran.to_numpy()
    fv_ch = fields_ch.fv_fortran.to_numpy()
    assert not np.isclose(fv_bj[0, 0, 2], fv_ch[0, 0, 2])


def test_signed_mean_chamoli_absubar_uses_raw_fv_not_half_max_component():
    """Chamoli dfs.F90:209-212 signed mean on raw fv vs BJ max(vorth,vcomp) on 0.5*fv."""
    h_values = np.array([[0.20], [0.20]], dtype=np.float64)
    rho_values = np.array([[1000.0], [1000.0]], dtype=np.float64)
    fv_seed = np.zeros((2, 1, 8), dtype=np.float64)
    fv_seed[0, 0, 2] = 2.0

    fields_bj = _build_fields()
    fields_bj.h.from_numpy(h_values.copy())
    fields_bj.rho.from_numpy(rho_values.copy())
    fields_bj.fv_fortran.from_numpy(fv_seed.copy())
    solver_bj = DFSDynamicWaveSolver(
        fields_bj,
        _build_config(absubar_variant="max_component_bj"),
        FortranDynamicWaveWorkspace(fields_bj),
    )

    fields_ch = _build_fields()
    fields_ch.h.from_numpy(h_values.copy())
    fields_ch.rho.from_numpy(rho_values.copy())
    fields_ch.fv_fortran.from_numpy(fv_seed.copy())
    solver_ch = DFSDynamicWaveSolver(
        fields_ch,
        _build_config(absubar_variant="signed_mean_chamoli"),
        FortranDynamicWaveWorkspace(fields_ch),
    )

    assert solver_bj.dfs_absubar_variant == "max_component_bj"
    assert solver_ch.dfs_absubar_variant == "signed_mean_chamoli"
    assert solver_bj.step(1.0e-3)["accepted"] is True
    assert solver_ch.step(1.0e-3)["accepted"] is True

    ab_bj = fields_bj.absubar_temp.to_numpy()[0, 0]
    ab_ch = fields_ch.absubar_temp.to_numpy()[0, 0]
    # BJ: 0.5 scale then 0.5*(|fv2|+|fv6|) => 0.5
    # Chamoli: vy=(fv2-fv6)*0.5 => 1.0
    assert np.isclose(ab_bj, 0.5)
    assert np.isclose(ab_ch, 1.0)


def test_paired_face_flux_tol_epsilon_is_default_off_and_opt_in(monkeypatch):
    monkeypatch.delenv(DFS_FACE_GATE_TOL_EPS_ENV, raising=False)
    cfg = _build_config(face_flux_variant="both_thin_weighted")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    fields.h.from_numpy(np.array([[0.01000006], [0.00992169]], dtype=np.float64))
    fields.rho.from_numpy(np.array([[1000.0], [1000.0]], dtype=np.float64))

    result = solver.step(1.0e-3)

    assert result["accepted"] is True
    fv = fields.fv_fortran.to_numpy()
    assert fv[0, 0, 2] != 0.0

    monkeypatch.setenv(DFS_FACE_GATE_TOL_EPS_ENV, "1e-7")
    cfg = _build_config(face_flux_variant="both_thin_weighted")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    fields.h.from_numpy(np.array([[0.01000006], [0.00992169]], dtype=np.float64))
    fields.rho.from_numpy(np.array([[1000.0], [1000.0]], dtype=np.float64))

    result = solver.step(1.0e-3)

    assert result["accepted"] is True
    fv = fields.fv_fortran.to_numpy()
    assert np.isclose(fv[0, 0, 2], 0.0)
    assert np.isclose(fv[1, 0, 6], 0.0)


def test_original_live_moving_thin_face_gate_blocks_one_thin_downhill_face(monkeypatch):
    monkeypatch.delenv(DFS_ORIGINAL_LIVE_MOVING_THIN_FACE_GATE_COMPAT_ENV, raising=False)
    cfg = _build_config(face_flux_variant="both_thin_weighted")

    fields_default = _build_fields()
    fields_default.h.from_numpy(np.array([[0.01000006], [0.00993673]], dtype=np.float64))
    fields_default.z_bed.from_numpy(np.array([[10.0], [10.01]], dtype=np.float64))
    fields_default.rho.from_numpy(np.array([[1000.0], [1000.0]], dtype=np.float64))
    solver_default = DFSDynamicWaveSolver(
        fields_default,
        cfg,
        FortranDynamicWaveWorkspace(fields_default),
    )

    result_default = solver_default.step(1.0e-3)
    fv_default = fields_default.fv_fortran.to_numpy()

    monkeypatch.setenv(DFS_ORIGINAL_LIVE_MOVING_THIN_FACE_GATE_COMPAT_ENV, "1")
    fields_live = _build_fields()
    fields_live.h.from_numpy(np.array([[0.01000006], [0.00993673]], dtype=np.float64))
    fields_live.z_bed.from_numpy(np.array([[10.0], [10.01]], dtype=np.float64))
    fields_live.rho.from_numpy(np.array([[1000.0], [1000.0]], dtype=np.float64))
    solver_live = DFSDynamicWaveSolver(
        fields_live,
        cfg,
        FortranDynamicWaveWorkspace(fields_live),
    )

    result_live = solver_live.step(1.0e-3)
    fv_live = fields_live.fv_fortran.to_numpy()

    assert result_default["accepted"] is True
    assert result_live["accepted"] is True
    assert solver_live.original_live_moving_thin_face_gate_compat_enabled is True
    assert abs(float(fv_default[0, 0, 2])) > 0.0
    assert np.isclose(fv_live[0, 0, 2], 0.0)
    assert np.isclose(fv_live[1, 0, 6], 0.0)


def test_default_face_flux_variant_blocks_upslope_thin_face():
    cfg = _build_config(face_flux_variant="asymmetric_head_guard")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.h.from_numpy(np.array([[0.005], [0.02]], dtype=np.float64))
    fields.rho.from_numpy(np.array([[1000.0], [1000.0]], dtype=np.float64))

    result = solver.step(1.0e-3)

    assert result["accepted"] is True
    fv = fields.fv_fortran.to_numpy()
    assert np.isclose(fv[0, 0, 2], 0.0)
    assert np.isclose(fv[1, 0, 6], 0.0)


def test_face_flux_kernel_diagnostic_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver.step(1.0e-3)
    diagnostics = solver.get_face_flux_kernel_diagnostics()

    assert diagnostics["dfs_face_flux_kernel_gate_enabled"] is False
    assert diagnostics["dfs_face_flux_kernel_active"] is False
    assert diagnostics["face_flux_cpu_vs_kernel_match"] is None
    assert diagnostics["face_flux_kernel_fallback_reason"] == "DFS_FACE_FLUX_KERNEL_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def test_face_flux_kernel_diagnostic_matches_cpu_without_mutating_final_state(monkeypatch):
    cfg = _build_config()

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    fields_cpu = _build_fields()
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0e-3)

    monkeypatch.setenv(DFS_FACE_FLUX_KERNEL_ENV, "1")
    fields_kernel = _build_fields()
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0e-3)

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    diagnostics = solver_kernel.get_face_flux_kernel_diagnostics()
    assert diagnostics["dfs_face_flux_kernel_gate_enabled"] is True
    assert diagnostics["dfs_face_flux_kernel_active"] is True
    assert diagnostics["face_flux_cpu_vs_kernel_match"] is True
    assert diagnostics["face_flux_compared_count"] == 2
    assert diagnostics["face_flux_max_abs_error"] == 0.0
    assert diagnostics["face_flux_mismatch_count"] == 0
    assert diagnostics["face_flux_mask_mismatch_count"] == 0
    assert diagnostics["face_flux_kernel_h2d_bytes"] == 0
    assert diagnostics["face_flux_kernel_d2h_bytes"] > 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []

    for name in ("h", "rho", "Cv", "fv_fortran", "qq_fortran", "qqmass_fortran", "qnet_fortran", "qmassnet_fortran"):
        np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def _run_face_flux_candidate_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0e-3)

    monkeypatch.setenv(DFS_FACE_FLUX_KERNEL_ENV, "1")
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0e-3)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel.get_face_flux_kernel_diagnostics()


def test_face_flux_candidate_kernel_reports_mask_and_mirror_contract(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, diagnostics = _run_face_flux_candidate_case(monkeypatch)

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_face_flux_kernel_gate_enabled"] is True
    assert diagnostics["dfs_face_flux_kernel_active"] is True
    assert diagnostics["dfs_face_flux_kernel_mode"] == "candidate_mask_and_mirror"
    assert diagnostics["face_flux_candidate_subset"] == "valid_mask_and_opposite_face_mirror"
    assert diagnostics["face_flux_full_formula_recomputed"] is False
    assert diagnostics["face_flux_valid_mask_recomputed"] is True
    assert diagnostics["face_flux_opposite_mirror_recomputed"] is True
    assert diagnostics["face_flux_fv_pred_mismatch_count"] == 0
    assert diagnostics["face_flux_qq_mismatch_count"] == 0
    assert diagnostics["face_flux_qqmass_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []

    for name in ("h", "rho", "Cv", "fv_fortran", "qq_fortran", "qqmass_fortran", "qnet_fortran", "qmassnet_fortran"):
        np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_face_flux_candidate_kernel_matches_weighted_and_blocked_faces(monkeypatch):
    cases = [
        ("both_thin_weighted", np.array([[0.005], [0.02]], dtype=np.float64)),
        ("asymmetric_head_guard", np.array([[0.005], [0.02]], dtype=np.float64)),
    ]
    for face_flux_variant, h_values in cases:
        result_cpu, result_kernel, fields_cpu, fields_kernel, diagnostics = _run_face_flux_candidate_case(
            monkeypatch,
            face_flux_variant=face_flux_variant,
            h_values=h_values,
        )

        assert result_cpu["accepted"] is True
        assert result_kernel["accepted"] is True
        assert diagnostics["dfs_face_flux_kernel_active"] is True
        assert diagnostics["face_flux_cpu_vs_kernel_match"] is True
        assert diagnostics["face_flux_compared_count"] == 2
        assert diagnostics["face_flux_max_abs_error"] == 0.0
        assert diagnostics["face_flux_mismatch_count"] == 0
        assert diagnostics["face_flux_mask_mismatch_count"] == 0
        assert diagnostics["final_state_mutated"] is False

        for name in ("h", "rho", "Cv", "fv_fortran", "qq_fortran", "qqmass_fortran", "qnet_fortran", "qmassnet_fortran"):
            np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_qnet_qmassnet_diagnostic_kernel_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver.step(1.0e-3)
    diagnostics = solver.get_qnet_qmassnet_kernel_diagnostics()

    assert diagnostics["dfs_qnet_qmassnet_kernel_gate_enabled"] is False
    assert diagnostics["dfs_qnet_qmassnet_kernel_active"] is False
    assert diagnostics["qnet_qmassnet_cpu_vs_kernel_match"] is None
    assert diagnostics["qnet_qmassnet_kernel_fallback_reason"] == "DFS_QNET_QMASSNET_KERNEL_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def _run_qnet_qmassnet_diagnostic_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0e-3)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_QNET_QMASSNET_KERNEL_ENV, "1")
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0e-3)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel


def test_qnet_qmassnet_diagnostic_kernel_matches_reference_without_mutating_final_state(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_qnet_qmassnet_diagnostic_case(monkeypatch)
    diagnostics = solver_kernel.get_qnet_qmassnet_kernel_diagnostics()

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_qnet_qmassnet_kernel_gate_enabled"] is True
    assert diagnostics["dfs_qnet_qmassnet_kernel_active"] is True
    assert diagnostics["dfs_qnet_qmassnet_kernel_mode"] == "diagnostic_accumulation"
    assert diagnostics["qnet_qmassnet_cpu_vs_kernel_match"] is True
    assert diagnostics["qnet_qmassnet_compared_cell_count"] == 2
    assert diagnostics["qnet_qmassnet_compared_face_count"] == 2
    assert diagnostics["qnet_qmassnet_max_abs_error_qnet"] == 0.0
    assert diagnostics["qnet_qmassnet_max_abs_error_qmassnet"] == 0.0
    assert diagnostics["qnet_qmassnet_mismatch_count"] == 0
    assert diagnostics["qnet_qmassnet_cell_mask_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []

    np.testing.assert_allclose(solver_kernel.qnet_diag_kernel.to_numpy(), fields_kernel.qnet_fortran.to_numpy())
    np.testing.assert_allclose(solver_kernel.qmassnet_diag_kernel.to_numpy(), fields_kernel.qmassnet_fortran.to_numpy())
    for name in ("h", "rho", "Cv", "fv_fortran", "qq_fortran", "qqmass_fortran", "qnet_fortran", "qmassnet_fortran"):
        np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_qnet_qmassnet_diagnostic_kernel_matches_weighted_and_blocked_faces(monkeypatch):
    cases = [
        ("both_thin_weighted", np.array([[0.005], [0.02]], dtype=np.float64)),
        ("asymmetric_head_guard", np.array([[0.005], [0.02]], dtype=np.float64)),
    ]
    for face_flux_variant, h_values in cases:
        result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_qnet_qmassnet_diagnostic_case(
            monkeypatch,
            face_flux_variant=face_flux_variant,
            h_values=h_values,
        )
        diagnostics = solver_kernel.get_qnet_qmassnet_kernel_diagnostics()

        assert result_cpu["accepted"] is True
        assert result_kernel["accepted"] is True
        assert diagnostics["dfs_qnet_qmassnet_kernel_active"] is True
        assert diagnostics["qnet_qmassnet_cpu_vs_kernel_match"] is True
        assert diagnostics["qnet_qmassnet_compared_cell_count"] == 2
        assert diagnostics["qnet_qmassnet_compared_face_count"] == 2
        assert diagnostics["qnet_qmassnet_max_abs_error_qnet"] == 0.0
        assert diagnostics["qnet_qmassnet_max_abs_error_qmassnet"] == 0.0
        assert diagnostics["qnet_qmassnet_mismatch_count"] == 0
        assert diagnostics["final_state_mutated"] is False

        np.testing.assert_allclose(solver_kernel.qnet_diag_kernel.to_numpy(), fields_kernel.qnet_fortran.to_numpy())
        np.testing.assert_allclose(solver_kernel.qmassnet_diag_kernel.to_numpy(), fields_kernel.qmassnet_fortran.to_numpy())
        for name in ("h", "rho", "Cv", "fv_fortran", "qq_fortran", "qqmass_fortran", "qnet_fortran", "qmassnet_fortran"):
            np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_qnet_qmassnet_mutation_kernel_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver.step(1.0e-3)
    diagnostics = solver.get_qnet_qmassnet_mutation_diagnostics()

    assert diagnostics["dfs_qnet_qmassnet_mutation_gate_enabled"] is False
    assert diagnostics["dfs_qnet_qmassnet_mutation_active"] is False
    assert diagnostics["qnet_qmassnet_mutation_cpu_vs_kernel_match"] is None
    assert diagnostics["qnet_qmassnet_mutation_fallback_reason"] == "DFS_QNET_QMASSNET_MUTATE_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def _run_qnet_qmassnet_mutation_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0e-3)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_QNET_QMASSNET_MUTATE_ENV, "1")
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0e-3)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel


def test_qnet_qmassnet_mutation_kernel_matches_reference_without_mutating_final_state(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_qnet_qmassnet_mutation_case(monkeypatch)
    diagnostics = solver_kernel.get_qnet_qmassnet_mutation_diagnostics()

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_qnet_qmassnet_mutation_gate_enabled"] is True
    assert diagnostics["dfs_qnet_qmassnet_mutation_active"] is True
    assert diagnostics["dfs_qnet_qmassnet_mutation_mode"] == "validated_writeback"
    assert diagnostics["qnet_qmassnet_mutation_cpu_vs_kernel_match"] is True
    assert diagnostics["qnet_qmassnet_mutation_fallback_active"] is False
    assert diagnostics["qnet_qmassnet_mutation_fallback_reason"] is None
    assert diagnostics["qnet_qmassnet_mutation_compared_cell_count"] == 2
    assert diagnostics["qnet_qmassnet_mutation_compared_face_count"] == 2
    assert diagnostics["qnet_qmassnet_mutation_max_abs_error_qnet"] == 0.0
    assert diagnostics["qnet_qmassnet_mutation_max_abs_error_qmassnet"] == 0.0
    assert diagnostics["qnet_qmassnet_mutation_mismatch_count"] == 0
    assert diagnostics["qnet_qmassnet_mutation_cell_mask_mismatch_count"] == 0
    assert diagnostics["qnet_qmassnet_mutation_writeback_count"] == 2
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == ["qnet_fortran", "qmassnet_fortran"]

    np.testing.assert_allclose(solver_kernel.qnet_diag_kernel.to_numpy(), fields_kernel.qnet_fortran.to_numpy())
    np.testing.assert_allclose(solver_kernel.qmassnet_diag_kernel.to_numpy(), fields_kernel.qmassnet_fortran.to_numpy())
    for name in (
        "h",
        "rho",
        "Cv",
        "fv_fortran",
        "qq_fortran",
        "qqmass_fortran",
        "qnet_fortran",
        "qmassnet_fortran",
        "fhpredi2",
        "frhopredi2",
    ):
        np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_qnet_qmassnet_mutation_kernel_matches_weighted_and_blocked_faces(monkeypatch):
    cases = [
        ("both_thin_weighted", np.array([[0.005], [0.02]], dtype=np.float64)),
        ("asymmetric_head_guard", np.array([[0.005], [0.02]], dtype=np.float64)),
    ]
    for face_flux_variant, h_values in cases:
        result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_qnet_qmassnet_mutation_case(
            monkeypatch,
            face_flux_variant=face_flux_variant,
            h_values=h_values,
        )
        diagnostics = solver_kernel.get_qnet_qmassnet_mutation_diagnostics()

        assert result_cpu["accepted"] is True
        assert result_kernel["accepted"] is True
        assert diagnostics["dfs_qnet_qmassnet_mutation_active"] is True
        assert diagnostics["qnet_qmassnet_mutation_cpu_vs_kernel_match"] is True
        assert diagnostics["qnet_qmassnet_mutation_compared_cell_count"] == 2
        assert diagnostics["qnet_qmassnet_mutation_compared_face_count"] == 2
        assert diagnostics["qnet_qmassnet_mutation_max_abs_error_qnet"] == 0.0
        assert diagnostics["qnet_qmassnet_mutation_max_abs_error_qmassnet"] == 0.0
        assert diagnostics["qnet_qmassnet_mutation_mismatch_count"] == 0
        assert diagnostics["final_state_mutated"] is False
        assert diagnostics["changed_field_names"] == ["qnet_fortran", "qmassnet_fortran"]

        np.testing.assert_allclose(solver_kernel.qnet_diag_kernel.to_numpy(), fields_kernel.qnet_fortran.to_numpy())
        np.testing.assert_allclose(solver_kernel.qmassnet_diag_kernel.to_numpy(), fields_kernel.qmassnet_fortran.to_numpy())
        for name in (
            "h",
            "rho",
            "Cv",
            "fv_fortran",
            "qq_fortran",
            "qqmass_fortran",
            "qnet_fortran",
            "qmassnet_fortran",
            "fhpredi2",
            "frhopredi2",
        ):
            np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_predictor_diagnostic_kernel_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver.step(1.0e-3)
    diagnostics = solver.get_predictor_kernel_diagnostics()

    assert diagnostics["dfs_predictor_diagnostic_kernel_gate_enabled"] is False
    assert diagnostics["dfs_predictor_diagnostic_kernel_active"] is False
    assert diagnostics["predictor_cpu_vs_kernel_match"] is None
    assert diagnostics["predictor_kernel_fallback_reason"] == "DFS_PREDICTOR_DIAGNOSTIC_KERNEL_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def _run_predictor_diagnostic_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0e-3)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.setenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, "1")
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0e-3)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel


def test_predictor_diagnostic_kernel_matches_reference_without_mutating_final_state(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_predictor_diagnostic_case(monkeypatch)
    diagnostics = solver_kernel.get_predictor_kernel_diagnostics()

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_predictor_diagnostic_kernel_gate_enabled"] is True
    assert diagnostics["dfs_predictor_diagnostic_kernel_active"] is True
    assert diagnostics["dfs_predictor_diagnostic_kernel_mode"] == "diagnostic_predictor_update"
    assert diagnostics["predictor_cpu_vs_kernel_match"] is True
    assert diagnostics["predictor_compared_cell_count"] == 2
    assert diagnostics["predictor_max_abs_error_fhpredi2"] <= 1.0e-12
    assert diagnostics["predictor_max_abs_error_frhopredi2"] <= 1.0e-9
    assert diagnostics["predictor_mismatch_count"] == 0
    assert diagnostics["predictor_cell_mask_mismatch_count"] == 0
    assert diagnostics["predictor_tolerance_rtol"] == 1.0e-12
    assert diagnostics["predictor_tolerance_atol"] == 1.0e-12
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []

    np.testing.assert_allclose(solver_kernel.fhpredi2_diag_kernel.to_numpy(), fields_kernel.fhpredi2.to_numpy())
    np.testing.assert_allclose(solver_kernel.frhopredi2_diag_kernel.to_numpy(), fields_kernel.frhopredi2.to_numpy())
    for name in ("h", "rho", "Cv", "qnet_fortran", "qmassnet_fortran", "fhpredi2", "frhopredi2"):
        np.testing.assert_allclose(getattr(fields_kernel, name).to_numpy(), getattr(fields_cpu, name).to_numpy())


def test_predictor_diagnostic_kernel_handles_dry_and_density_guard(monkeypatch):
    monkeypatch.setenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi.from_numpy(np.array([[0.2], [0.2]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    fields.qqmass_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qq = fields.qq_fortran.to_numpy()
    qq[0, 0, 2] = 30.0
    fields.qq_fortran.from_numpy(qq)
    solver.reject_flag[None] = 0
    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)
    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    solver._run_predictor_diagnostic_if_enabled()
    diagnostics = solver.get_predictor_kernel_diagnostics()

    assert diagnostics["predictor_cpu_vs_kernel_match"] is True
    assert diagnostics["predictor_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []
    np.testing.assert_allclose(solver.fhpredi2_diag_kernel.to_numpy(), fields.fhpredi2.to_numpy())
    np.testing.assert_allclose(solver.frhopredi2_diag_kernel.to_numpy(), fields.frhopredi2.to_numpy())
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)
    assert np.isclose(solver.fhpredi2_diag_kernel.to_numpy()[0, 0], 0.0)
    assert np.isclose(solver.frhopredi2_diag_kernel.to_numpy()[0, 0], cfg.rheology.rho_water)

    fields.fhpredi.from_numpy(np.array([[1.0], [1.0]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qqmass = np.zeros((2, 1, 8), dtype=np.float64)
    qqmass[0, 0, 2] = 10000.0
    fields.qqmass_fortran.from_numpy(qqmass)
    solver.reject_flag[None] = 0
    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)
    solver._run_predictor_diagnostic_if_enabled()

    diagnostics = solver.get_predictor_kernel_diagnostics()
    assert diagnostics["predictor_cpu_vs_kernel_match"] is True
    assert diagnostics["predictor_mismatch_count"] == 0
    assert np.isclose(solver.fhpredi2_diag_kernel.to_numpy()[0, 0], 0.0)
    assert np.isclose(solver.frhopredi2_diag_kernel.to_numpy()[0, 0], cfg.rheology.rho_water)


def test_predictor_mutation_kernel_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_PREDICTOR_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    diagnostics = solver.get_predictor_mutation_diagnostics()

    assert diagnostics["dfs_predictor_mutation_gate_enabled"] is False
    assert diagnostics["dfs_predictor_mutation_active"] is False
    assert diagnostics["predictor_mutation_cpu_vs_kernel_match"] is None
    assert diagnostics["predictor_mutation_fallback_reason"] == "DFS_PREDICTOR_MUTATE_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def _run_predictor_mutation_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_MUTATE_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_PREDICTOR_MUTATE_ENV, "1")
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel


def test_predictor_mutation_kernel_matches_reference_without_mutating_final_state(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_predictor_mutation_case(monkeypatch)
    diagnostics = solver_kernel.get_predictor_mutation_diagnostics()

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_predictor_mutation_gate_enabled"] is True
    assert diagnostics["dfs_predictor_mutation_active"] is True
    assert diagnostics["dfs_predictor_mutation_mode"] == "validated_writeback"
    assert diagnostics["predictor_mutation_cpu_vs_kernel_match"] is True
    assert diagnostics["predictor_mutation_compared_cells"] == 2
    assert diagnostics["predictor_mutation_writeback_count"] == 2
    assert diagnostics["predictor_mutation_mismatch_count"] == 0
    assert diagnostics["predictor_mutation_max_abs_error_fhpredi2"] <= 1.0e-12
    assert diagnostics["predictor_mutation_max_abs_error_frhopredi2"] <= 1.0e-12
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == ["fhpredi2", "frhopredi2"]

    np.testing.assert_allclose(fields_kernel.fhpredi2.to_numpy(), fields_cpu.fhpredi2.to_numpy())
    np.testing.assert_allclose(fields_kernel.frhopredi2.to_numpy(), fields_cpu.frhopredi2.to_numpy())
    np.testing.assert_allclose(fields_kernel.h.to_numpy(), fields_cpu.h.to_numpy())
    np.testing.assert_allclose(fields_kernel.Cv.to_numpy(), fields_cpu.Cv.to_numpy())
    np.testing.assert_allclose(fields_kernel.rho.to_numpy(), fields_cpu.rho.to_numpy())


def test_predictor_mutation_kernel_handles_dry_and_density_guard(monkeypatch):
    monkeypatch.setenv(DFS_PREDICTOR_MUTATE_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi.from_numpy(np.array([[0.2], [1.0]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    fields.qqmass_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qq = np.zeros((2, 1, 8), dtype=np.float64)
    qqmass = np.zeros_like(qq)
    qq[0, 0, 2] = 30.0
    qqmass[1, 0, 2] = 10_000.0
    fields.qq_fortran.from_numpy(qq)
    fields.qqmass_fortran.from_numpy(qqmass)

    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    solver.reject_flag[None] = 0
    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)
    solver._run_predictor_mutation_if_enabled()

    diagnostics = solver.get_predictor_mutation_diagnostics()
    assert diagnostics["predictor_mutation_cpu_vs_kernel_match"] is True
    assert diagnostics["predictor_mutation_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == ["fhpredi2", "frhopredi2"]
    np.testing.assert_allclose(fields.fhpredi2.to_numpy(), np.array([[0.0], [0.0]], dtype=np.float64))
    np.testing.assert_allclose(
        fields.frhopredi2.to_numpy(),
        np.array([[cfg.rheology.rho_water], [cfg.rheology.rho_water]], dtype=np.float64),
    )
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)


def test_h_cv_rho_diagnostic_kernel_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    diagnostics = solver.get_h_cv_rho_kernel_diagnostics()

    assert diagnostics["dfs_h_cv_rho_diagnostic_kernel_gate_enabled"] is False
    assert diagnostics["dfs_h_cv_rho_diagnostic_kernel_active"] is False
    assert diagnostics["h_cv_rho_cpu_vs_kernel_match"] is None
    assert diagnostics["h_cv_rho_kernel_fallback_reason"] == "DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def _run_h_cv_rho_diagnostic_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_MUTATE_ENV, raising=False)
    monkeypatch.setenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, "1")
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel


def test_h_cv_rho_diagnostic_kernel_matches_reference_without_mutating_final_state(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_h_cv_rho_diagnostic_case(monkeypatch)
    diagnostics = solver_kernel.get_h_cv_rho_kernel_diagnostics()

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_h_cv_rho_diagnostic_kernel_gate_enabled"] is True
    assert diagnostics["dfs_h_cv_rho_diagnostic_kernel_active"] is True
    assert diagnostics["dfs_h_cv_rho_diagnostic_kernel_mode"] == "diagnostic_precommit_candidate_update"
    assert diagnostics["h_cv_rho_cpu_vs_kernel_match"] is True
    assert diagnostics["h_cv_rho_compared_cell_count"] == 2
    assert diagnostics["h_cv_rho_mismatch_count"] == 0
    assert diagnostics["h_cv_rho_cell_mask_mismatch_count"] == 0
    assert diagnostics["h_max_abs_error"] <= 1.0e-12
    assert diagnostics["Cv_max_abs_error"] <= 1.0e-12
    assert diagnostics["rho_max_abs_error"] <= 1.0e-12
    assert diagnostics["h_cv_rho_tolerance_rtol"] == 1.0e-12
    assert diagnostics["h_cv_rho_tolerance_atol"] == 1.0e-12
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []

    np.testing.assert_allclose(fields_kernel.h.to_numpy(), fields_cpu.h.to_numpy())
    np.testing.assert_allclose(fields_kernel.Cv.to_numpy(), fields_cpu.Cv.to_numpy())
    np.testing.assert_allclose(fields_kernel.rho.to_numpy(), fields_cpu.rho.to_numpy())
    np.testing.assert_allclose(solver_kernel.h_diag_kernel.to_numpy(), fields_kernel.h.to_numpy())
    np.testing.assert_allclose(solver_kernel.Cv_diag_kernel.to_numpy(), fields_kernel.Cv.to_numpy())
    np.testing.assert_allclose(solver_kernel.rho_diag_kernel.to_numpy(), fields_kernel.rho.to_numpy())


def test_h_cv_rho_diagnostic_kernel_handles_dry_and_cv_rho_cases(monkeypatch):
    monkeypatch.setenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi2.from_numpy(np.array([[0.0], [1.25]], dtype=np.float64))
    fields.frhopredi2.from_numpy(np.array([[cfg.rheology.rho_water], [1165.0]], dtype=np.float64))
    h_before = fields.h.to_numpy().copy()
    Cv_before = fields.Cv.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()

    solver._prepare_h_cv_rho_diagnostic_if_enabled()

    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.Cv.to_numpy(), Cv_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)

    solver._commit_step(1.0, 1.0, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    solver._finalize_h_cv_rho_diagnostic_if_enabled()
    diagnostics = solver.get_h_cv_rho_kernel_diagnostics()

    assert diagnostics["h_cv_rho_cpu_vs_kernel_match"] is True
    assert diagnostics["h_cv_rho_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []
    np.testing.assert_allclose(solver.h_diag_kernel.to_numpy(), np.array([[0.0], [1.25]], dtype=np.float64))
    np.testing.assert_allclose(solver.rho_diag_kernel.to_numpy(), np.array([[1000.0], [1165.0]], dtype=np.float64))
    np.testing.assert_allclose(solver.Cv_diag_kernel.to_numpy(), np.array([[0.0], [0.1]], dtype=np.float64))
    np.testing.assert_allclose(solver.h_diag_kernel.to_numpy(), fields.h.to_numpy())
    np.testing.assert_allclose(solver.Cv_diag_kernel.to_numpy(), fields.Cv.to_numpy())
    np.testing.assert_allclose(solver.rho_diag_kernel.to_numpy(), fields.rho.to_numpy())


def test_h_cv_rho_mutation_kernel_is_default_off(monkeypatch):
    monkeypatch.delenv(DFS_H_CV_RHO_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    diagnostics = solver.get_h_cv_rho_mutation_diagnostics()

    assert diagnostics["dfs_h_cv_rho_mutation_gate_enabled"] is False
    assert diagnostics["dfs_h_cv_rho_mutation_active"] is False
    assert diagnostics["h_cv_rho_mutation_cpu_vs_kernel_match"] is None
    assert diagnostics["h_cv_rho_mutation_fallback_reason"] == "DFS_H_CV_RHO_MUTATE_GATE_NOT_SET"
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []


def _run_h_cv_rho_mutation_case(monkeypatch, *, face_flux_variant="asymmetric_head_guard", h_values=None):
    cfg = _build_config(face_flux_variant=face_flux_variant)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_H_CV_RHO_MUTATE_ENV, raising=False)
    fields_cpu = _build_fields()
    if h_values is not None:
        fields_cpu.h.from_numpy(h_values)
    workspace_cpu = FortranDynamicWaveWorkspace(fields_cpu)
    solver_cpu = DFSDynamicWaveSolver(fields_cpu, cfg, workspace_cpu)
    result_cpu = solver_cpu.step(1.0)

    monkeypatch.delenv(DFS_FACE_FLUX_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_QNET_QMASSNET_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_PREDICTOR_MUTATE_ENV, raising=False)
    monkeypatch.delenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_H_CV_RHO_MUTATE_ENV, "1")
    fields_kernel = _build_fields()
    if h_values is not None:
        fields_kernel.h.from_numpy(h_values)
    workspace_kernel = FortranDynamicWaveWorkspace(fields_kernel)
    solver_kernel = DFSDynamicWaveSolver(fields_kernel, cfg, workspace_kernel)
    result_kernel = solver_kernel.step(1.0)

    return result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel


def test_h_cv_rho_mutation_kernel_matches_reference_and_reports_final_state_writeback(monkeypatch):
    result_cpu, result_kernel, fields_cpu, fields_kernel, solver_kernel = _run_h_cv_rho_mutation_case(monkeypatch)
    diagnostics = solver_kernel.get_h_cv_rho_mutation_diagnostics()

    assert result_cpu["accepted"] is True
    assert result_kernel["accepted"] is True
    assert diagnostics["dfs_h_cv_rho_mutation_gate_enabled"] is True
    assert diagnostics["dfs_h_cv_rho_mutation_active"] is True
    assert diagnostics["dfs_h_cv_rho_mutation_mode"] == "validated_writeback"
    assert diagnostics["h_cv_rho_mutation_cpu_vs_kernel_match"] is True
    assert diagnostics["h_cv_rho_mutation_fallback_active"] is False
    assert diagnostics["h_cv_rho_mutation_fallback_reason"] is None
    assert diagnostics["h_cv_rho_mutation_compared_cell_count"] == 2
    assert diagnostics["h_cv_rho_mutation_writeback_count"] == 2
    assert diagnostics["h_cv_rho_mutation_mismatch_count"] == 0
    assert diagnostics["h_mutation_max_abs_error"] <= 1.0e-12
    assert diagnostics["Cv_mutation_max_abs_error"] <= 1.0e-12
    assert diagnostics["rho_mutation_max_abs_error"] <= 1.0e-12
    assert diagnostics["final_state_mutated"] is True
    assert diagnostics["changed_field_names"] == ["h", "Cv", "rho"]

    np.testing.assert_allclose(fields_kernel.h.to_numpy(), fields_cpu.h.to_numpy())
    np.testing.assert_allclose(fields_kernel.Cv.to_numpy(), fields_cpu.Cv.to_numpy())
    np.testing.assert_allclose(fields_kernel.rho.to_numpy(), fields_cpu.rho.to_numpy())
    np.testing.assert_allclose(solver_kernel.h_diag_kernel.to_numpy(), fields_kernel.h.to_numpy())
    np.testing.assert_allclose(solver_kernel.Cv_diag_kernel.to_numpy(), fields_kernel.Cv.to_numpy())
    np.testing.assert_allclose(solver_kernel.rho_diag_kernel.to_numpy(), fields_kernel.rho.to_numpy())


def test_h_cv_rho_diagnostic_mode_remains_separate_from_mutation(monkeypatch):
    monkeypatch.setenv(DFS_H_CV_RHO_DIAGNOSTIC_KERNEL_ENV, "1")
    monkeypatch.delenv(DFS_H_CV_RHO_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    result = solver.step(1.0)
    diagnostic = solver.get_h_cv_rho_kernel_diagnostics()
    mutation = solver.get_h_cv_rho_mutation_diagnostics()

    assert result["accepted"] is True
    assert diagnostic["h_cv_rho_cpu_vs_kernel_match"] is True
    assert diagnostic["final_state_mutated"] is False
    assert diagnostic["changed_field_names"] == []
    assert mutation["dfs_h_cv_rho_mutation_gate_enabled"] is False
    assert mutation["h_cv_rho_mutation_cpu_vs_kernel_match"] is None
    assert mutation["final_state_mutated"] is False
    assert mutation["changed_field_names"] == []


def test_h_cv_rho_mutation_kernel_handles_dry_and_cv_rho_cases(monkeypatch):
    monkeypatch.setenv(DFS_H_CV_RHO_MUTATE_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi2.from_numpy(np.array([[0.0], [1.25]], dtype=np.float64))
    fields.frhopredi2.from_numpy(np.array([[cfg.rheology.rho_water], [1165.0]], dtype=np.float64))
    solver._prepare_h_cv_rho_mutation_if_enabled()
    solver._commit_step(1.0, 1.0, cfg.rheology.rho_water, cfg.rheology.rho_sediment, cfg.rheology.Cv_max)
    erosion_after_commit = fields.erosion_depth.to_numpy().copy()
    deposition_after_commit = fields.deposition_depth.to_numpy().copy()
    z_bed_after_commit = fields.z_bed.to_numpy().copy()
    solver._run_h_cv_rho_mutation_if_enabled()
    diagnostics = solver.get_h_cv_rho_mutation_diagnostics()

    assert diagnostics["h_cv_rho_mutation_cpu_vs_kernel_match"] is True
    assert diagnostics["h_cv_rho_mutation_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is True
    assert diagnostics["changed_field_names"] == ["h", "Cv", "rho"]
    np.testing.assert_allclose(fields.h.to_numpy(), np.array([[0.0], [1.25]], dtype=np.float64))
    np.testing.assert_allclose(fields.rho.to_numpy(), np.array([[1000.0], [1165.0]], dtype=np.float64))
    np.testing.assert_allclose(fields.Cv.to_numpy(), np.array([[0.0], [0.1]], dtype=np.float64))
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_after_commit)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_after_commit)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_bed_after_commit)


class _FakeDoubleLayerModel:
    def __init__(self):
        self.calls = []

    def solve_richards_equation(self, dt, tempir):
        self.calls.append(("solve_richards_equation", float(dt), float(np.asarray(tempir).sum())))

    def compute_pore_pressure(self):
        self.calls.append(("compute_pore_pressure",))

    def find_minimum_fs(self):
        self.calls.append(("find_minimum_fs",))

    def populate_failure_source_terms(self, cvstar, rho_sediment, rho_water):
        self.calls.append(("populate_failure_source_terms", float(cvstar), float(rho_sediment), float(rho_water)))

    def restore_richards_committed_state(self):
        self.calls.append(("restore_richards_committed_state",))


def test_precomputed_unsfin_failure_source_variant_skips_live_doublelayer_advancement():
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    fake = _FakeDoubleLayerModel()
    solver.set_double_layer_model(fake)

    fields.infiltration.from_numpy(np.full((2, 1), 1.0e-6, dtype=np.float64))
    solver._advance_double_layer_failure_sources(1.0)

    assert fake.calls == []


def test_precomputed_unsfin_schedule_stages_crossing_failure_source_once_after_commit():
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[2.0], [10.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )
    assert info["scheduled_cell_count"] == 2

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)

    staged_depth = fields.tempfsh_flow.to_numpy()
    staged_rho = fields.tempfsrho_flow.to_numpy()
    expected_rho = (cfg.rheology.rho_sediment - cfg.rheology.rho_water) * cfg.rheology.Cv_max + cfg.rheology.rho_water
    assert np.isclose(staged_depth[0, 0], 2.0)
    assert np.isclose(staged_depth[1, 0], 0.0)
    assert np.isclose(staged_rho[0, 0], expected_rho)

    solver._commit_precomputed_failure_schedule()
    diagnostics = solver.get_precomputed_failure_schedule_diagnostics()
    assert diagnostics["fired_cell_count"] == 1
    assert diagnostics["committed_fired_count"] == 1
    assert diagnostics["candidate_fired_count"] == 0

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    assert np.isclose(fields.tempfsh_flow.to_numpy().sum(), 0.0)
    assert solver.get_precomputed_failure_schedule_diagnostics()["duplicate_fire_count"] == 1


def test_precomputed_unsfin_schedule_retries_staging_until_commit():
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[5.0], [5.0]], dtype=np.float64))
    solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    first_sum = float(fields.tempfsh_flow.to_numpy().sum())
    solver._advance_double_layer_failure_sources(1.0)
    retry_sum = float(fields.tempfsh_flow.to_numpy().sum())

    assert np.isclose(first_sum, 3.0)
    assert np.isclose(retry_sum, 3.0)


def test_precomputed_unsfin_schedule_discards_candidate_on_rejected_retry():
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[5.0], [5.0]], dtype=np.float64))
    solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    assert solver.get_precomputed_failure_schedule_diagnostics()["candidate_fired_count"] == 1

    solver._discard_precomputed_failure_candidate()
    diagnostics = solver.get_precomputed_failure_schedule_diagnostics()
    assert diagnostics["candidate_fired_count"] == 0
    assert diagnostics["rejected_step_discard_count"] == 1
    assert diagnostics["fired_cell_count"] == 0

    solver._advance_double_layer_failure_sources(1.0)
    assert np.isclose(fields.tempfsh_flow.to_numpy().sum(), 3.0)


def test_precomputed_unsfin_schedule_never_feeds_gindx_zero_fdepth():
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[5.0], [5.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [0.5]], dtype=np.float64),
        gindx=np.array([[0], [1]], dtype=np.int32),
        fdepth_m=np.array([[999.0], [4.0]], dtype=np.float64),
    )
    assert info["scheduled_cell_count"] == 1
    assert info["gindx_zero_no_feed_count"] == 1
    assert solver.precomputed_failure_gindx[0, 0] == 0
    assert solver.precomputed_failure_fdepth[0, 0] == 0.0

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    staged_depth = fields.tempfsh_flow.to_numpy()
    assert np.isclose(staged_depth[0, 0], 0.0)
    assert np.isclose(staged_depth[1, 0], 4.0)


def test_precomputed_unsfin_schedule_gpu_field_feed_default_off(monkeypatch):
    monkeypatch.delenv(DFS_SOURCE_STAGING_FIELD_ENV, raising=False)
    monkeypatch.delenv(RNOFF_GPU_FIELD_FEED_ENV, raising=False)
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [0.5]], dtype=np.float64),
        gindx=np.array([[1], [0]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [999.0]], dtype=np.float64),
    )

    assert info["rnoff_gpu_field_feed_gate_enabled"] is False
    assert info["rnoff_gpu_field_feed_active"] is False
    assert info["dfs_source_staging_field_gate_enabled"] is False
    assert info["dfs_source_staging_field_active"] is False
    assert info["schedule_buffer_uploaded_to_taichi"] is False
    assert info["taichi_schedule_buffer_roundtrip_ok"] is None
    assert solver.precomputed_failure_tfail_field is None
    assert solver.precomputed_failure_gindx_field is None
    assert solver.precomputed_failure_fdepth_field is None


def test_precomputed_unsfin_schedule_gpu_field_feed_roundtrips_sanitized_buffers(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.delenv(DFS_SOURCE_STAGING_FIELD_ENV, raising=False)
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[5.0], [5.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [0.5]], dtype=np.float64),
        gindx=np.array([[0], [1]], dtype=np.int32),
        fdepth_m=np.array([[999.0], [4.0]], dtype=np.float64),
    )

    assert info["rnoff_gpu_field_feed_gate_enabled"] is True
    assert info["rnoff_gpu_field_feed_active"] is True
    assert info["dfs_source_staging_field_gate_enabled"] is False
    assert info["dfs_source_staging_field_active"] is False
    assert info["dfs_source_staging_field_fallback_reason"] == "DFS_SOURCE_STAGING_FIELD_GATE_NOT_SET"
    assert info["schedule_buffer_uploaded_to_taichi"] is True
    assert info["taichi_schedule_buffer_roundtrip_ok"] is True
    assert info["taichi_schedule_buffer_fallback_reason"] is None
    assert info["gindx_zero_no_feed_count"] == 1
    assert info["taichi_schedule_buffer_max_abs_error_tfail"] == 0.0
    assert info["taichi_schedule_buffer_max_abs_error_fdepth"] == 0.0
    assert info["taichi_schedule_buffer_gindx_mismatch_count"] == 0

    np.testing.assert_array_equal(
        solver.precomputed_failure_tfail_field.to_numpy(),
        solver.precomputed_failure_tfail,
    )
    np.testing.assert_array_equal(
        solver.precomputed_failure_gindx_field.to_numpy(),
        solver.precomputed_failure_gindx,
    )
    np.testing.assert_array_equal(
        solver.precomputed_failure_fdepth_field.to_numpy(),
        solver.precomputed_failure_fdepth,
    )
    assert solver.precomputed_failure_gindx[0, 0] == 0
    assert solver.precomputed_failure_fdepth[0, 0] == 0.0



def test_precomputed_unsfin_source_staging_field_requires_rnoff_field_feed(monkeypatch):
    monkeypatch.delenv(RNOFF_GPU_FIELD_FEED_ENV, raising=False)
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [0.5]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )

    assert info["rnoff_gpu_field_feed_gate_enabled"] is False
    assert info["rnoff_gpu_field_feed_active"] is False
    assert info["dfs_source_staging_field_gate_enabled"] is True
    assert info["dfs_source_staging_field_active"] is False
    assert info["dfs_source_staging_field_fallback_reason"] == "RNOFF_GPU_FIELD_FEED_NOT_ACTIVE"
    assert info["schedule_buffer_uploaded_to_taichi"] is False
    assert solver.precomputed_failure_tfail_field is None


def test_precomputed_unsfin_source_staging_field_matches_cpu_staging(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[5.0], [5.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [0.5]], dtype=np.float64),
        gindx=np.array([[0], [1]], dtype=np.int32),
        fdepth_m=np.array([[999.0], [4.0]], dtype=np.float64),
    )

    assert info["rnoff_gpu_field_feed_active"] is True
    assert info["dfs_source_staging_field_gate_enabled"] is True
    assert info["dfs_source_staging_field_active"] is True

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    diagnostics = solver.get_precomputed_failure_schedule_diagnostics()
    staged_depth = fields.tempfsh_flow.to_numpy()
    assert np.isclose(staged_depth[0, 0], 0.0)
    assert np.isclose(staged_depth[1, 0], 4.0)
    np.testing.assert_allclose(
        solver.precomputed_failure_source_depth_staging_field.to_numpy(),
        staged_depth,
    )
    np.testing.assert_allclose(
        solver.precomputed_failure_source_density_staging_field.to_numpy(),
        fields.tempfsrho_flow.to_numpy(),
    )
    assert diagnostics["source_staging_field_roundtrip_ok"] is True
    assert diagnostics["source_staging_cpu_vs_taichi_match"] is True
    assert diagnostics["source_staging_depth_max_abs_error"] == 0.0
    assert diagnostics["source_staging_density_max_abs_error"] == 0.0
    assert diagnostics["source_staging_candidate_mask_mismatch_count"] == 0


def test_precomputed_unsfin_schedule_field_staging_commits_and_retries_like_cpu(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    monkeypatch.delenv(DFS_SOURCE_STAGING_FAST_CONSUME_ENV, raising=False)
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[2.0], [10.0]], dtype=np.float64))
    solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    assert np.isclose(fields.tempfsh_flow.to_numpy()[0, 0], 2.0)
    assert solver.get_precomputed_failure_schedule_diagnostics()["candidate_fired_count"] == 1

    solver._commit_precomputed_failure_schedule()
    assert solver.precomputed_failure_committed_fire_mask_field.to_numpy()[0, 0] == 1

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    diagnostics = solver.get_precomputed_failure_schedule_diagnostics()
    assert np.isclose(fields.tempfsh_flow.to_numpy().sum(), 0.0)
    assert diagnostics["duplicate_fire_count"] == 1
    assert diagnostics["dfs_source_staging_field_active"] is True


def test_precomputed_unsfin_source_staging_fast_consume_reduces_stage_parity_downloads(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FAST_CONSUME_ENV, "1")
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[2.0], [10.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )
    assert info["dfs_source_staging_fast_consume_gate_enabled"] is True
    assert info["dfs_source_staging_fast_consume_active"] is False
    assert info["parity_validation_mode"] == "first_stage_then_fast_consume"

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    first = solver.get_precomputed_failure_schedule_diagnostics()
    assert first["source_staging_cpu_vs_taichi_match"] is True
    assert first["parity_download_count"] == 1
    assert first["dfs_source_staging_fast_consume_active"] is False
    assert first["candidate_fired_count"] == 1
    solver._commit_precomputed_failure_schedule()

    solver.set_current_time(1.0)
    solver._advance_double_layer_failure_sources(2.0)
    second = solver.get_precomputed_failure_schedule_diagnostics()
    assert second["dfs_source_staging_fast_consume_active"] is True
    assert second["per_stage_parity_download_disabled"] is True
    assert second["source_staging_device_consumed"] is True
    assert second["parity_download_count"] == 1
    assert second["candidate_fired_count"] == 1
    assert np.isclose(fields.tempfsh_flow.to_numpy()[1, 0], 4.0)
    solver._commit_precomputed_failure_schedule()
    assert solver.get_precomputed_failure_schedule_diagnostics()["committed_fired_count"] == 2


def test_precomputed_unsfin_source_staging_kernel_default_off(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FAST_CONSUME_ENV, "1")
    monkeypatch.delenv(DFS_SOURCE_STAGING_KERNEL_ENV, raising=False)
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )

    assert info["dfs_source_staging_kernel_gate_enabled"] is False
    assert info["dfs_source_staging_kernel_active"] is False
    assert info["kernel_fallback_active"] is False
    assert info["kernel_fallback_reason"] == "DFS_SOURCE_STAGING_KERNEL_GATE_NOT_SET"


def test_precomputed_unsfin_source_staging_kernel_fails_closed_without_required_gates(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FAST_CONSUME_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_KERNEL_ENV, "1")
    monkeypatch.delenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", raising=False)
    monkeypatch.delenv("EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED", raising=False)
    monkeypatch.delenv("EDDA_NATIVE_UNSFIN_RUNTIME_FEED", raising=False)
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )

    assert info["dfs_source_staging_kernel_gate_enabled"] is True
    assert info["dfs_source_staging_kernel_required_gates_active"] is False
    assert info["dfs_source_staging_kernel_active"] is False
    assert info["kernel_fallback_active"] is True
    assert info["kernel_fallback_reason"] == "DFS_SOURCE_STAGING_KERNEL_REQUIRED_GATES_NOT_ACTIVE"


def test_precomputed_unsfin_source_staging_kernel_avoids_candidate_mask_download_and_committed_mask_upload(monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "1")
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED", "1")
    monkeypatch.setenv("EDDA_NATIVE_UNSFIN_RUNTIME_FEED", "1")
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FAST_CONSUME_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_KERNEL_ENV, "1")
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[2.0], [10.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )
    assert info["dfs_source_staging_kernel_gate_enabled"] is True
    assert info["dfs_source_staging_kernel_required_gates_active"] is True
    assert info["dfs_source_staging_kernel_active"] is False

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    first = solver.get_precomputed_failure_schedule_diagnostics()
    assert first["source_staging_cpu_vs_taichi_match"] is True
    assert first["dfs_source_staging_kernel_active"] is False
    solver._commit_precomputed_failure_schedule()

    solver.set_current_time(1.0)
    solver._advance_double_layer_failure_sources(2.0)
    second = solver.get_precomputed_failure_schedule_diagnostics()
    assert second["dfs_source_staging_kernel_active"] is True
    assert second["source_staging_kernel_vs_cpu_match"] is True
    assert second["kernel_fallback_active"] is False
    assert second["kernel_candidate_stage_count"] == 1
    assert second["kernel_h2d_bytes"] == 0
    assert second["kernel_d2h_bytes"] > 0
    assert second["parity_download_count"] == 1
    assert np.isclose(fields.tempfsh_flow.to_numpy()[1, 0], 4.0)
    solver._commit_precomputed_failure_schedule()
    assert solver.get_precomputed_failure_schedule_diagnostics()["committed_fired_count"] == 2
    np.testing.assert_array_equal(
        solver.precomputed_failure_committed_fire_mask_field.to_numpy(),
        solver.precomputed_failure_fired.astype(np.int32),
    )


def test_precomputed_unsfin_source_staging_kernel_preserves_gindx_zero_and_duplicate_prevention(monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_TOPOINDEX", "1")
    monkeypatch.setenv("EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED", "1")
    monkeypatch.setenv("EDDA_NATIVE_UNSFIN_RUNTIME_FEED", "1")
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FIELD_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_FAST_CONSUME_ENV, "1")
    monkeypatch.setenv(DFS_SOURCE_STAGING_KERNEL_ENV, "1")
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.erodible_thickness.from_numpy(np.array([[5.0], [5.0]], dtype=np.float64))
    info = solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [2.0]], dtype=np.float64),
        gindx=np.array([[0], [1]], dtype=np.int32),
        fdepth_m=np.array([[999.0], [4.0]], dtype=np.float64),
    )
    assert info["gindx_zero_no_feed_count"] == 1
    assert solver.precomputed_failure_fdepth[0, 0] == 0.0

    solver.set_current_time(0.0)
    solver._advance_double_layer_failure_sources(1.0)
    solver._commit_precomputed_failure_schedule()

    solver.set_current_time(1.0)
    solver._advance_double_layer_failure_sources(2.0)
    assert solver.get_precomputed_failure_schedule_diagnostics()["dfs_source_staging_kernel_active"] is True
    assert np.isclose(fields.tempfsh_flow.to_numpy()[0, 0], 0.0)
    assert np.isclose(fields.tempfsh_flow.to_numpy()[1, 0], 4.0)
    solver._commit_precomputed_failure_schedule()

    solver.set_current_time(1.0)
    solver._advance_double_layer_failure_sources(2.0)
    diagnostics = solver.get_precomputed_failure_schedule_diagnostics()
    assert np.isclose(fields.tempfsh_flow.to_numpy().sum(), 0.0)
    assert diagnostics["duplicate_fire_count"] == 1


def test_precomputed_unsfin_schedule_gpu_field_feed_reconfigure_replaces_stale_buffers(monkeypatch):
    monkeypatch.setenv(RNOFF_GPU_FIELD_FEED_ENV, "1")
    monkeypatch.delenv(DFS_SOURCE_STAGING_FIELD_ENV, raising=False)
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[0.5], [0.5]], dtype=np.float64),
        gindx=np.array([[1], [1]], dtype=np.int32),
        fdepth_m=np.array([[3.0], [4.0]], dtype=np.float64),
    )
    first_tfail = solver.precomputed_failure_tfail_field.to_numpy().copy()

    solver.configure_precomputed_failure_schedule(
        tfail_s=np.array([[2.5], [3.5]], dtype=np.float64),
        gindx=np.array([[1], [0]], dtype=np.int32),
        fdepth_m=np.array([[6.0], [9.0]], dtype=np.float64),
    )

    assert not np.array_equal(solver.precomputed_failure_tfail_field.to_numpy(), first_tfail)
    np.testing.assert_array_equal(
        solver.precomputed_failure_tfail_field.to_numpy(),
        solver.precomputed_failure_tfail,
    )
    np.testing.assert_array_equal(
        solver.precomputed_failure_gindx_field.to_numpy(),
        solver.precomputed_failure_gindx,
    )
    np.testing.assert_array_equal(
        solver.precomputed_failure_fdepth_field.to_numpy(),
        solver.precomputed_failure_fdepth,
    )
    assert solver.precomputed_failure_gindx[1, 0] == 0
    assert solver.precomputed_failure_fdepth[1, 0] == 0.0


def test_rnoff_provider_schedule_shadow_preview_does_not_stage_or_commit_sources():
    cfg = _build_config(failure_source_variant="precomputed_unsfin_schedule")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    before_tempfsh = fields.tempfsh_flow.to_numpy().copy()
    before_tempfsrho = fields.tempfsrho_flow.to_numpy().copy()
    before_infiltration = fields.infiltration.to_numpy().copy()
    precomputed_before = solver.get_precomputed_failure_schedule_diagnostics()

    rows = [
        {
            "one_based_cell_id": 1,
            "tfail": 0.5,
            "gindx": 1,
            "fdepth": 3.0,
            "event_type": "TFailAssignment",
            "branch": "tfail_assigned",
        },
        {
            "one_based_cell_id": 2,
            "tfail": 2.0,
            "gindx": 1,
            "fdepth": 4.0,
            "event_type": "TFailAssignment",
            "branch": "tfail_assigned",
        },
    ]

    shadow = solver.run_rnoff_provider_schedule_shadow_lifecycle(rows, t_start_s=0.0, t_end_s=1.0)

    assert shadow["shadow_schedule_loaded"] is True
    assert shadow["shadow_active_row_count"] == 2
    assert shadow["shadow_crossing_count"] == 1
    assert shadow["shadow_candidate_stage_count"] == 1
    assert shadow["shadow_rejected_discard_count"] == 1
    assert shadow["shadow_accepted_commit_count"] == 1
    assert shadow["shadow_duplicate_fire_count"] == 0
    assert shadow["shadow_final_state_mutated"] is False
    assert shadow["schedule_consumed_by_dfs"] is False
    assert shadow["changed_field_names"] == []

    np.testing.assert_allclose(fields.tempfsh_flow.to_numpy(), before_tempfsh)
    np.testing.assert_allclose(fields.tempfsrho_flow.to_numpy(), before_tempfsrho)
    np.testing.assert_allclose(fields.infiltration.to_numpy(), before_infiltration)
    assert solver.precomputed_failure_fired is None
    assert solver.get_precomputed_failure_schedule_diagnostics() == precomputed_before


def test_live_failure_source_variant_advances_doublelayer_model():
    cfg = _build_config(failure_source_variant="live_doublelayer_in_dfs")
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    fake = _FakeDoubleLayerModel()
    solver.set_double_layer_model(fake)

    fields.infiltration.from_numpy(np.full((2, 1), 1.0e-6, dtype=np.float64))
    solver._advance_double_layer_failure_sources(1.0)

    assert [entry[0] for entry in fake.calls] == [
        "solve_richards_equation",
        "compute_pore_pressure",
        "find_minimum_fs",
        "populate_failure_source_terms",
    ]


def test_dfs_step_rejects_large_dt():
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    result = solver.step(2.0)

    assert result["accepted"] is False
    assert result["suggested_dt"] < 2.0


def test_first_reject_short_circuit_experiment_is_default_off(monkeypatch):
    monkeypatch.delenv("EDDA_EXPERIMENT_FIRST_REJECT_SHORT_CIRCUIT", raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    result = solver.step(2.0)

    assert result["accepted"] is False
    assert result["experimental_first_reject_short_circuit"] is False
    assert solver.get_first_reject_diagnostics()["experiment_enabled"] is False


def test_first_reject_short_circuit_experiment_records_cfl_and_returns_early(monkeypatch):
    monkeypatch.setenv("EDDA_EXPERIMENT_FIRST_REJECT_SHORT_CIRCUIT", "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    result = solver.step(2.0)
    diag = solver.get_first_reject_diagnostics()

    assert result["accepted"] is False
    assert result["experimental_first_reject_short_circuit"] is True
    assert diag["experiment_enabled"] is True
    assert diag["first_reject_reason"] == FIRST_REJECT_CFL
    assert diag["early_return_count"] == 1
    assert diag["cell_id"] > 0
    assert diag["direction_one_based"] in {1, 2, 3, 4, 5, 6, 7, 8}


def test_accumulate_resets_dry_or_low_density_cell_before_depth_gate():
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi.from_numpy(np.array([[0.2], [0.2]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    fields.qqmass_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qq = fields.qq_fortran.to_numpy()
    qq[0, 0, 2] = 30.0
    fields.qq_fortran.from_numpy(qq)
    solver.reject_flag[None] = 0

    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)

    assert int(solver.reject_flag[None]) == 0
    assert np.isclose(fields.qnet_fortran.to_numpy()[0, 0], -30.0)
    assert np.isclose(fields.fhpredi2.to_numpy()[0, 0], 0.0)
    assert np.isclose(fields.frhopredi2.to_numpy()[0, 0], cfg.rheology.rho_water)

    fields.fhpredi.from_numpy(np.array([[1.0], [1.0]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qqmass = np.zeros((2, 1, 8), dtype=np.float64)
    qqmass[0, 0, 2] = 10000.0
    fields.qqmass_fortran.from_numpy(qqmass)
    solver.reject_flag[None] = 0

    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)

    assert int(solver.reject_flag[None]) == 0
    assert np.isclose(fields.fhpredi2.to_numpy()[0, 0], 0.0)
    assert np.isclose(fields.frhopredi2.to_numpy()[0, 0], cfg.rheology.rho_water)


def test_accumulate_and_check_consumes_cellareacal_for_depth_and_density_update():
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.cell_area_cal.from_numpy(np.array([[200.0], [100.0]], dtype=np.float64))
    fields.fhpredi.from_numpy(np.array([[1.0], [1.0]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    fields.qqmass_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qq = fields.qq_fortran.to_numpy()
    qqmass = fields.qqmass_fortran.to_numpy()
    qq[0, 0, 2] = -50.0
    qqmass[0, 0, 2] = -50000.0
    fields.qq_fortran.from_numpy(qq)
    fields.qqmass_fortran.from_numpy(qqmass)
    solver.reject_flag[None] = 0

    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)

    assert int(solver.reject_flag[None]) == 0
    assert np.isclose(fields.qnet_fortran.to_numpy()[0, 0], 50.0)
    assert np.isclose(fields.qmassnet_fortran.to_numpy()[0, 0], 50000.0)
    assert np.isclose(fields.fhpredi2.to_numpy()[0, 0], 1.25)
    assert np.isclose(fields.frhopredi2.to_numpy()[0, 0], 1000.0)


def test_original_predictor_retry_gates_clamp_low_density_before_retry(monkeypatch):
    monkeypatch.delenv(DFS_ORIGINAL_PREDICTOR_RETRY_GATES_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi.from_numpy(np.array([[1.0], [1.0]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qqmass = np.zeros((2, 1, 8), dtype=np.float64)
    qqmass[0, 0, 2] = 10000.0
    fields.qqmass_fortran.from_numpy(qqmass)
    solver.reject_flag[None] = 0

    solver._accumulate_and_check(1.0, cfg.rheology.rho_water, 10.0, 10.0)
    diag = solver.get_first_reject_diagnostics()

    assert int(solver.reject_flag[None]) == 0
    assert diag["predictor_retry_gates_enabled"] is True
    assert diag["first_reject_reason"] == 0
    assert np.isclose(fields.fhpredi2.to_numpy()[0, 0], 0.0)
    assert np.isclose(fields.frhopredi2.to_numpy()[0, 0], cfg.rheology.rho_water)


def test_depth_change_retry_default_matches_original_dfs(monkeypatch):
    monkeypatch.delenv(DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi.from_numpy(np.array([[0.0008563631349900014], [0.0008563631349900014]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    fields.qqmass_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qq = fields.qq_fortran.to_numpy()
    qqmass = fields.qqmass_fortran.to_numpy()
    cellarea = fields.dx * fields.dy
    qq[0, 0, 2] = -0.132366569448597 * cellarea
    qqmass[0, 0, 2] = -27428.9202745159
    fields.qq_fortran.from_numpy(qq)
    fields.qqmass_fortran.from_numpy(qqmass)
    solver.reject_flag[None] = 0

    solver._accumulate_and_check(0.781, cfg.rheology.rho_water, 0.05, cfg.time.toldhp)
    diag = solver.get_first_reject_diagnostics()

    assert int(solver.reject_flag[None]) == 1
    assert diag["ifort_inactive_barrier_depth_gate_compat_enabled"] is False
    assert diag["first_reject_reason"] == FIRST_REJECT_DEPTH_CHANGE
    assert np.isclose(fields.fhpredi2.to_numpy()[0, 0], 0.133222932583587)


def test_ifort_inactive_barrier_depth_gate_compat_explicit_ablation_skips_depth_change_reject(monkeypatch):
    monkeypatch.setenv(DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    fields.fhpredi.from_numpy(np.array([[0.0008563631349900014], [0.0008563631349900014]], dtype=np.float64))
    fields.frhopredi.from_numpy(np.full((2, 1), 1000.0, dtype=np.float64))
    fields.qq_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    fields.qqmass_fortran.from_numpy(np.zeros((2, 1, 8), dtype=np.float64))
    qq = fields.qq_fortran.to_numpy()
    qqmass = fields.qqmass_fortran.to_numpy()
    cellarea = fields.dx * fields.dy
    qq[0, 0, 2] = -0.132366569448597 * cellarea
    qqmass[0, 0, 2] = -27428.9202745159
    fields.qq_fortran.from_numpy(qq)
    fields.qqmass_fortran.from_numpy(qqmass)
    solver.reject_flag[None] = 0

    solver._accumulate_and_check(0.781, cfg.rheology.rho_water, 0.05, cfg.time.toldhp)
    diag = solver.get_first_reject_diagnostics()

    assert int(solver.reject_flag[None]) == 0
    assert diag["ifort_inactive_barrier_depth_gate_compat_enabled"] is True
    assert np.isclose(fields.fhpredi2.to_numpy()[0, 0], 0.133222932583587)


def test_stage_trace_defaults_off_and_records_enabled_stage_rows():
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver.step(1.0e-3)
    assert solver.get_stage_trace_records() == []

    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    solver.configure_stage_trace(
        enabled=True,
        target_cell_ids=[1],
        window_start_s=0.0,
        window_end_s=1.0,
    )
    solver.step(1.0e-3)

    records = solver.get_stage_trace_records()
    stages = {record["stage"] for record in records}
    assert {"STEP_START", "SOURCE_STAGING", "POST_SOURCE_MERGE", "FACE_FLUX", "POST_FLUX", "RETRY_CHECK", "COMMIT"} <= stages
    assert any(record["stage"] == "FACE_FLUX" and record["dir"] in range(1, 9) for record in records)
    assert all(record["cell"] == 1 for record in records)


def test_green_ampt_average_infiltration_matches_no_runoff_limit():
    fave, tempci = _green_ampt_average_infiltration_rate(
        cinow=0.1,
        inflx=1.0e-7,
        dt=10.0,
        ksti=1.0e-6,
        psiti=0.2,
        delth=0.2,
    )

    assert np.isclose(fave, 1.0e-7)
    assert np.isclose(tempci, 0.1 + 1.0e-7 * 10.0)


def test_green_ampt_average_infiltration_is_ks_limited_after_runoff():
    fave, tempci = _green_ampt_average_infiltration_rate(
        cinow=0.02,
        inflx=2.0e-5,
        dt=100.0,
        ksti=1.0e-6,
        psiti=0.3,
        delth=0.25,
    )

    assert fave <= 2.0e-5
    assert fave > 0.0
    assert tempci > 0.02


def test_rholimit_persists_when_all_fortran_tanslodir_entries_are_negative():
    fields = EDDAFields(3, 3, 10.0, 10.0, fp_dtype=ti.f64)
    z = np.ones((3, 3), dtype=np.float64)
    z[1, 1] = 0.0
    nodata = np.zeros((3, 3), dtype=np.int32)
    cell_id = np.arange(1, 10, dtype=np.int32).reshape(3, 3)
    neighbor_id = np.zeros((3, 3, 8), dtype=np.int32)
    neighbor_i = np.full((3, 3, 8), -1, dtype=np.int32)
    neighbor_j = np.full((3, 3, 8), -1, dtype=np.int32)
    directions = [
        (1, 0),
        (2, 0),
        (2, 1),
        (2, 2),
        (1, 2),
        (0, 2),
        (0, 1),
        (0, 0),
    ]
    for d, (ni, nj) in enumerate(directions):
        neighbor_i[1, 1, d] = ni
        neighbor_j[1, 1, d] = nj
        neighbor_id[1, 1, d] = cell_id[ni, nj]

    fields.initialize_from_numpy(z)
    fields.set_nodata_mask(nodata)
    fields.initialize_all()
    fields.set_flow_connectivity(cell_id, neighbor_id, neighbor_i, neighbor_j)
    fields.h.from_numpy(np.zeros((3, 3), dtype=np.float64))
    fields.rho.from_numpy(np.full((3, 3), 1000.0, dtype=np.float64))
    fields.phi_field.from_numpy(np.full((3, 3), 30.0, dtype=np.float64))
    fields.rholimit_temp.from_numpy(np.full((3, 3), 1234.0, dtype=np.float64))

    workspace = FortranDynamicWaveWorkspace(fields)
    workspace.compute_bed_slope_limiter(1000.0, 2650.0, 0.65)

    tanslo = fields.tanslo_fortran.to_numpy()
    cvlimit = fields.cvlimit_temp.to_numpy()
    rholimit = fields.rholimit_temp.to_numpy()
    # All eight neighbors exist and sit uphill, so maxval(tanslodir) is the
    # least-negative diagonal gradient.  dfs.F90 still stores that negative
    # `tanslo` before `cvlimit=0; cycle`, and must not rewrite rholimit.
    assert tanslo[1, 1] < 0.0
    assert np.isclose(tanslo[1, 1], -1.0 / (10.0 * np.sqrt(2.0)))
    assert np.isclose(cvlimit[1, 1], 0.0)
    assert np.isclose(rholimit[1, 1], 1234.0)


def test_fortran_cvlimit_limiter_keeps_zero_slots_for_missing_neighbors():
    fields = _build_fields()
    fields.z_bed.from_numpy(np.array([[0.0], [1.0]], dtype=np.float64))
    fields.h.from_numpy(np.array([[0.0], [0.0]], dtype=np.float64))
    fields.phi_field.from_numpy(np.array([[30.0], [30.0]], dtype=np.float64))
    fields.rholimit_temp.from_numpy(np.full((2, 1), 1234.0, dtype=np.float64))
    workspace = FortranDynamicWaveWorkspace(fields)

    workspace.compute_bed_slope_limiter(1000.0, 2650.0, 0.65)

    tanslo = fields.tanslo_fortran.to_numpy()
    cvlimit = fields.cvlimit_temp.to_numpy()
    rholimit = fields.rholimit_temp.to_numpy()
    assert np.isclose(tanslo[0, 0], 0.0)
    assert np.isclose(cvlimit[0, 0], 0.0)
    assert np.isclose(rholimit[0, 0], 1000.0)


def test_fortran_cvlimit_limiter_uses_water_surface_head():
    fields = _build_fields()
    fields.z_bed.from_numpy(np.array([[1.0], [1.0]], dtype=np.float64))
    fields.h.from_numpy(np.array([[0.2], [0.0]], dtype=np.float64))
    fields.phi_field.from_numpy(np.array([[30.0], [30.0]], dtype=np.float64))
    workspace = FortranDynamicWaveWorkspace(fields)

    workspace.compute_bed_slope_limiter(1000.0, 2650.0, 0.65)

    tanslo = fields.tanslo_fortran.to_numpy()
    cvlimit = fields.cvlimit_temp.to_numpy()
    assert np.isclose(tanslo[0, 0], 0.02)
    assert cvlimit[0, 0] > 0.0


def test_erosion_deposition_diagnostic_kernel_default_off(monkeypatch):
    monkeypatch.delenv(PROJECT_CUDA_BACKEND_STAGE2_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    diagnostics = solver.get_erosion_deposition_kernel_diagnostics()
    deep_state = solver.get_erosion_deposition_deep_state_kernel_diagnostics()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert diagnostics["dfs_erosion_deposition_diagnostic_kernel_gate_enabled"] is False
    assert diagnostics["dfs_erosion_deposition_diagnostic_kernel_active"] is False
    assert diagnostics["erosion_deposition_cpu_vs_kernel_match"] is None
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []
    assert diagnostics["scratch_buffer_names"] == []
    assert deep_state["dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled"] is False
    assert deep_state["dfs_erosion_deposition_deep_state_diagnostic_kernel_active"] is False
    assert deep_state["deep_state_cpu_vs_kernel_match"] is None
    assert deep_state["final_state_mutated"] is False
    assert deep_state["changed_field_names"] == []
    assert deep_state["scratch_buffer_names"] == []
    assert mutation["dfs_erosion_deposition_mutation_gate_enabled"] is False
    assert mutation["erosion_deposition_mutation_cpu_vs_kernel_match"] is None
    assert mutation["final_state_mutated"] is False
    assert mutation["changed_field_names"] == []
    assert solver.erorate_diag_kernel is None
    assert solver.deporate_diag_kernel is None
    assert solver.erosion_depth_delta_diag_kernel is None
    assert solver.deep_state_diag_cell_mask is None


def test_project_cuda_backend_stage2_enables_erosion_deposition_correctness_bundle(monkeypatch):
    monkeypatch.setenv(PROJECT_CUDA_BACKEND_STAGE2_ENV, "1")
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    erorate = np.array([[0.004], [0.0]], dtype=np.float64)
    deporate = np.array([[0.0], [-0.006]], dtype=np.float64)
    tempfsh_flow = np.array([[0.02], [0.0]], dtype=np.float64)
    tempele = np.array([[0.999], [0.006]], dtype=np.float64)
    erosion_depth = np.array([[0.1], [0.2]], dtype=np.float64)
    deposition_depth = np.array([[0.3], [0.4]], dtype=np.float64)
    fields.erosion_rate.from_numpy(erorate)
    fields.deposition_rate.from_numpy(deporate)
    fields.tempfsh_flow.from_numpy(tempfsh_flow)
    fields.tempele.from_numpy(tempele)
    fields.erosion_depth.from_numpy(erosion_depth)
    fields.deposition_depth.from_numpy(deposition_depth)
    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    cv_before = fields.Cv.to_numpy().copy()
    z_before = fields.z_bed.to_numpy().copy()

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    solver._run_erosion_deposition_mutation_if_enabled()
    rate_diag = solver.get_erosion_deposition_kernel_diagnostics()
    deep_state = solver.get_erosion_deposition_deep_state_kernel_diagnostics()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert rate_diag["project_cuda_backend_stage2_gate_enabled"] is True
    assert rate_diag["project_cuda_backend_stage2_active"] is True
    assert rate_diag["erosion_deposition_cpu_vs_kernel_match"] is True
    assert rate_diag["erosion_deposition_mismatch_count"] == 0
    assert deep_state["project_cuda_backend_stage2_gate_enabled"] is True
    assert deep_state["project_cuda_backend_stage2_active"] is True
    assert deep_state["deep_state_cpu_vs_kernel_match"] is True
    assert deep_state["deep_state_mismatch_count"] == 0
    assert deep_state["final_state_mutated"] is False
    assert deep_state["changed_field_names"] == []
    assert mutation["project_cuda_backend_stage2_gate_enabled"] is True
    assert mutation["project_cuda_backend_stage2_active"] is True
    assert mutation["erosion_deposition_mutation_cpu_vs_kernel_match"] is True
    assert mutation["erosion_deposition_mutation_fallback_active"] is False
    assert mutation["final_state_mutated"] is True
    assert mutation["changed_field_names"] == ["erosion_rate", "deposition_rate"]
    np.testing.assert_allclose(solver.erosion_depth_delta_diag_kernel.to_numpy(), erorate * dt)
    np.testing.assert_allclose(solver.deposition_depth_delta_diag_kernel.to_numpy(), np.abs(deporate) * dt)
    np.testing.assert_allclose(
        solver.source_depth_rate_diag_kernel.to_numpy(),
        tempfsh_flow / dt + erorate + deporate,
    )
    np.testing.assert_allclose(solver.z_bed_candidate_diag_kernel.to_numpy(), tempele)
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)
    np.testing.assert_allclose(fields.Cv.to_numpy(), cv_before)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_before)
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_depth)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_depth)


def test_project_cuda_backend_stage2_mutation_fails_closed_without_prepared_candidate(monkeypatch):
    monkeypatch.setenv(PROJECT_CUDA_BACKEND_STAGE2_ENV, "1")
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)

    solver._run_erosion_deposition_mutation_if_enabled()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert mutation["project_cuda_backend_stage2_gate_enabled"] is True
    assert mutation["project_cuda_backend_stage2_active"] is False
    assert mutation["erosion_deposition_mutation_fallback_active"] is True
    assert mutation["erosion_deposition_mutation_fallback_reason"] == "EROSION_DEPOSITION_MUTATION_CANDIDATE_NOT_PREPARED"
    assert mutation["final_state_mutated"] is False
    assert mutation["changed_field_names"] == []


def test_gpu_only_production_smoke_flag_enables_stage2_bundle_without_direct_stage2_flag(monkeypatch):
    monkeypatch.setenv(GPU_ONLY_PRODUCTION_SMOKE_ENV, "1")
    monkeypatch.delenv(PROJECT_CUDA_BACKEND_STAGE2_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, raising=False)
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    fields.erosion_rate.from_numpy(np.array([[0.004], [0.0]], dtype=np.float64))
    fields.deposition_rate.from_numpy(np.array([[0.0], [-0.006]], dtype=np.float64))
    fields.tempfsh_flow.from_numpy(np.array([[0.02], [0.0]], dtype=np.float64))
    fields.tempele.from_numpy(np.array([[0.999], [0.006]], dtype=np.float64))

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    solver._run_erosion_deposition_mutation_if_enabled()
    rate_diag = solver.get_erosion_deposition_kernel_diagnostics()
    deep_state = solver.get_erosion_deposition_deep_state_kernel_diagnostics()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert solver.gpu_only_production_smoke_gate_enabled is True
    assert rate_diag["project_cuda_backend_stage2_gate_enabled"] is True
    assert rate_diag["project_cuda_backend_stage2_active"] is True
    assert rate_diag["erosion_deposition_mismatch_count"] == 0
    assert deep_state["project_cuda_backend_stage2_active"] is True
    assert deep_state["deep_state_mismatch_count"] == 0
    assert deep_state["final_state_mutated"] is False
    assert deep_state["changed_field_names"] == []
    assert mutation["project_cuda_backend_stage2_active"] is True
    assert mutation["erosion_deposition_mutation_fallback_active"] is False
    assert mutation["final_state_mutated"] is True
    assert mutation["changed_field_names"] == ["erosion_rate", "deposition_rate"]


def test_erosion_deposition_diagnostic_kernel_mirrors_source_bookkeeping(monkeypatch):
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    fields.erosion_rate.from_numpy(np.array([[0.004], [0.0]], dtype=np.float64))
    fields.deposition_rate.from_numpy(np.array([[0.0], [-0.006]], dtype=np.float64))
    fields.tempfsh_flow.from_numpy(np.array([[0.02], [0.0]], dtype=np.float64))
    fields.tempele.from_numpy(np.array([[0.999], [0.006]], dtype=np.float64))
    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    cv_before = fields.Cv.to_numpy().copy()
    z_before = fields.z_bed.to_numpy().copy()
    erosion_depth_before = fields.erosion_depth.to_numpy().copy()
    deposition_depth_before = fields.deposition_depth.to_numpy().copy()

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    diagnostics = solver.get_erosion_deposition_kernel_diagnostics()

    assert diagnostics["dfs_erosion_deposition_diagnostic_kernel_gate_enabled"] is True
    assert diagnostics["dfs_erosion_deposition_diagnostic_kernel_active"] is True
    assert diagnostics["erosion_deposition_cpu_vs_kernel_match"] is True
    assert diagnostics["erosion_deposition_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []
    assert diagnostics["max_abs_error_erorate"] == 0.0
    assert diagnostics["max_abs_error_deporate"] == 0.0
    assert diagnostics["max_abs_error_erosion_depth_delta"] == 0.0
    assert diagnostics["max_abs_error_deposition_depth_delta"] == 0.0
    assert diagnostics["max_abs_error_source_depth_rate"] == 0.0
    assert diagnostics["max_abs_error_z_bed_candidate"] == 0.0
    np.testing.assert_allclose(solver.erorate_diag_kernel.to_numpy(), fields.erosion_rate.to_numpy())
    np.testing.assert_allclose(solver.deporate_diag_kernel.to_numpy(), fields.deposition_rate.to_numpy())
    np.testing.assert_allclose(solver.erosion_depth_diag_kernel.to_numpy(), fields.erosion_rate.to_numpy() * dt)
    np.testing.assert_allclose(
        solver.deposition_depth_diag_kernel.to_numpy(),
        np.abs(fields.deposition_rate.to_numpy()) * dt,
    )
    np.testing.assert_allclose(
        solver.source_depth_rate_diag_kernel.to_numpy(),
        fields.tempfsh_flow.to_numpy() / dt + fields.erosion_rate.to_numpy() + fields.deposition_rate.to_numpy(),
    )
    np.testing.assert_allclose(solver.z_bed_candidate_diag_kernel.to_numpy(), fields.tempele.to_numpy())
    np.testing.assert_array_equal(solver.erosion_deposition_diag_cell_mask.to_numpy(), np.ones((2, 1), dtype=np.int32))
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)
    np.testing.assert_allclose(fields.Cv.to_numpy(), cv_before)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_before)
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_depth_before)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_depth_before)


def test_erosion_deposition_deep_state_diagnostic_kernel_mirrors_candidates(monkeypatch):
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, raising=False)
    monkeypatch.setenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    erorate = np.array([[0.004], [0.0]], dtype=np.float64)
    deporate = np.array([[0.0], [-0.006]], dtype=np.float64)
    tempfsh_flow = np.array([[0.02], [0.0]], dtype=np.float64)
    tempele = np.array([[0.999], [0.006]], dtype=np.float64)
    erosion_depth = np.array([[0.1], [0.2]], dtype=np.float64)
    deposition_depth = np.array([[0.3], [0.4]], dtype=np.float64)
    fields.erosion_rate.from_numpy(erorate)
    fields.deposition_rate.from_numpy(deporate)
    fields.tempfsh_flow.from_numpy(tempfsh_flow)
    fields.tempele.from_numpy(tempele)
    fields.erosion_depth.from_numpy(erosion_depth)
    fields.deposition_depth.from_numpy(deposition_depth)

    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    cv_before = fields.Cv.to_numpy().copy()
    z_before = fields.z_bed.to_numpy().copy()

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    diagnostics = solver.get_erosion_deposition_deep_state_kernel_diagnostics()

    assert diagnostics["dfs_erosion_deposition_deep_state_diagnostic_kernel_gate_enabled"] is True
    assert diagnostics["dfs_erosion_deposition_deep_state_diagnostic_kernel_active"] is True
    assert diagnostics["deep_state_cpu_vs_kernel_match"] is True
    assert diagnostics["deep_state_mismatch_count"] == 0
    assert diagnostics["final_state_mutated"] is False
    assert diagnostics["changed_field_names"] == []
    assert diagnostics["max_abs_error_erosion_depth_delta"] == 0.0
    assert diagnostics["max_abs_error_deposition_depth_delta"] == 0.0
    assert diagnostics["max_abs_error_source_depth_rate"] == 0.0
    assert diagnostics["max_abs_error_z_bed_candidate"] == 0.0
    assert diagnostics["max_abs_error_erosion_depth_candidate"] == 0.0
    assert diagnostics["max_abs_error_deposition_depth_candidate"] == 0.0

    erosion_delta = erorate * dt
    deposition_delta = np.abs(deporate) * dt
    np.testing.assert_allclose(solver.erosion_depth_delta_diag_kernel.to_numpy(), erosion_delta)
    np.testing.assert_allclose(solver.deposition_depth_delta_diag_kernel.to_numpy(), deposition_delta)
    np.testing.assert_allclose(
        solver.source_depth_rate_diag_kernel.to_numpy(),
        tempfsh_flow / dt + erorate + deporate,
    )
    np.testing.assert_allclose(solver.z_bed_candidate_diag_kernel.to_numpy(), tempele)
    np.testing.assert_allclose(solver.erosion_depth_candidate_diag_kernel.to_numpy(), erosion_depth + erosion_delta)
    np.testing.assert_allclose(
        solver.deposition_depth_candidate_diag_kernel.to_numpy(),
        deposition_depth + deposition_delta,
    )
    np.testing.assert_array_equal(solver.deep_state_diag_cell_mask.to_numpy(), np.ones((2, 1), dtype=np.int32))
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)
    np.testing.assert_allclose(fields.Cv.to_numpy(), cv_before)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_before)
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_depth)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_depth)


def test_erosion_deposition_deep_state_diagnostic_rate_mutation_interaction(monkeypatch):
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, "1")
    monkeypatch.setenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    erorate = np.array([[0.004], [0.0]], dtype=np.float64)
    deporate = np.array([[0.0], [-0.006]], dtype=np.float64)
    fields.erosion_rate.from_numpy(erorate)
    fields.deposition_rate.from_numpy(deporate)
    erosion_depth_before = fields.erosion_depth.to_numpy().copy()
    deposition_depth_before = fields.deposition_depth.to_numpy().copy()
    z_before = fields.z_bed.to_numpy().copy()

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    solver._run_erosion_deposition_mutation_if_enabled()
    deep_state = solver.get_erosion_deposition_deep_state_kernel_diagnostics()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert deep_state["deep_state_cpu_vs_kernel_match"] is True
    assert deep_state["final_state_mutated"] is False
    assert deep_state["changed_field_names"] == []
    assert mutation["erosion_deposition_mutation_cpu_vs_kernel_match"] is True
    assert mutation["changed_field_names"] == ["erosion_rate", "deposition_rate"]
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_depth_before)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_depth_before)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_before)


def test_erosion_deposition_mutation_candidate_validated_writeback(monkeypatch):
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    erorate = np.array([[0.004], [0.0]], dtype=np.float64)
    deporate = np.array([[0.0], [-0.006]], dtype=np.float64)
    fields.erosion_rate.from_numpy(erorate)
    fields.deposition_rate.from_numpy(deporate)
    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    cv_before = fields.Cv.to_numpy().copy()
    z_before = fields.z_bed.to_numpy().copy()
    erosion_depth_before = fields.erosion_depth.to_numpy().copy()
    deposition_depth_before = fields.deposition_depth.to_numpy().copy()

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    solver._run_erosion_deposition_mutation_if_enabled()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert mutation["dfs_erosion_deposition_mutation_gate_enabled"] is True
    assert mutation["dfs_erosion_deposition_mutation_active"] is True
    assert mutation["dfs_erosion_deposition_mutation_mode"] == "validated_writeback"
    assert mutation["erosion_deposition_mutation_cpu_vs_kernel_match"] is True
    assert mutation["erosion_deposition_mutation_fallback_active"] is False
    assert mutation["erosion_deposition_mutation_fallback_reason"] is None
    assert mutation["erosion_deposition_mutation_compared_cell_count"] == 2
    assert mutation["erosion_deposition_mutation_writeback_count"] == 2
    assert mutation["erosion_deposition_mutation_mismatch_count"] == 0
    assert mutation["erorate_mutation_max_abs_error"] == 0.0
    assert mutation["deporate_mutation_max_abs_error"] == 0.0
    assert mutation["final_state_mutated"] is True
    assert mutation["changed_field_names"] == ["erosion_rate", "deposition_rate"]
    np.testing.assert_allclose(fields.erosion_rate.to_numpy(), erorate)
    np.testing.assert_allclose(fields.deposition_rate.to_numpy(), deporate)
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)
    np.testing.assert_allclose(fields.Cv.to_numpy(), cv_before)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_before)
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_depth_before)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_depth_before)


def test_erosion_deposition_mutation_candidate_mismatch_fails_closed(monkeypatch):
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.delenv(DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL_ENV, raising=False)
    monkeypatch.setenv(DFS_EROSION_DEPOSITION_MUTATE_ENV, "1")
    cfg = _build_config()
    fields = _build_fields()
    workspace = FortranDynamicWaveWorkspace(fields)
    solver = DFSDynamicWaveSolver(fields, cfg, workspace)
    dt = 0.25

    erorate = np.array([[0.004], [0.0]], dtype=np.float64)
    deporate = np.array([[0.0], [-0.006]], dtype=np.float64)
    fields.erosion_rate.from_numpy(erorate)
    fields.deposition_rate.from_numpy(deporate)
    h_before = fields.h.to_numpy().copy()
    rho_before = fields.rho.to_numpy().copy()
    cv_before = fields.Cv.to_numpy().copy()
    z_before = fields.z_bed.to_numpy().copy()
    erosion_depth_before = fields.erosion_depth.to_numpy().copy()
    deposition_depth_before = fields.deposition_depth.to_numpy().copy()

    solver._run_erosion_deposition_kernel_diagnostic_if_enabled(dt)
    solver.erorate_diag_kernel.from_numpy(erorate + np.array([[1.0e-3], [0.0]], dtype=np.float64))
    solver._run_erosion_deposition_mutation_if_enabled()
    mutation = solver.get_erosion_deposition_mutation_diagnostics()

    assert mutation["dfs_erosion_deposition_mutation_gate_enabled"] is True
    assert mutation["dfs_erosion_deposition_mutation_active"] is False
    assert mutation["erosion_deposition_mutation_cpu_vs_kernel_match"] is False
    assert mutation["erosion_deposition_mutation_fallback_active"] is True
    assert mutation["erosion_deposition_mutation_fallback_reason"] == "EROSION_DEPOSITION_MUTATION_VALIDATION_MISMATCH"
    assert mutation["erosion_deposition_mutation_writeback_count"] == 0
    assert mutation["erorate_mutation_mismatch_count"] == 1
    assert mutation["final_state_mutated"] is False
    assert mutation["changed_field_names"] == []
    np.testing.assert_allclose(fields.erosion_rate.to_numpy(), erorate)
    np.testing.assert_allclose(fields.deposition_rate.to_numpy(), deporate)
    np.testing.assert_allclose(fields.h.to_numpy(), h_before)
    np.testing.assert_allclose(fields.rho.to_numpy(), rho_before)
    np.testing.assert_allclose(fields.Cv.to_numpy(), cv_before)
    np.testing.assert_allclose(fields.z_bed.to_numpy(), z_before)
    np.testing.assert_allclose(fields.erosion_depth.to_numpy(), erosion_depth_before)
    np.testing.assert_allclose(fields.deposition_depth.to_numpy(), deposition_depth_before)
def test_volume_relative_tolerance_matches_original_dfs_literal():
    from edda.solver.fortran_literals import DFS_VOLUME_REL_TOL

    assert abs(float(DFS_VOLUME_REL_TOL) - 0.001) < 1.0e-9
