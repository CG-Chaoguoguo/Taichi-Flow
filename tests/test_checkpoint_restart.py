import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver


def _write_ascii_dem(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 10",
                "NODATA_value -9999",
                "2 1",
                "1 0",
            ]
        ),
        encoding="ascii",
    )


def _build_config(dem_file: Path, output_dir: Path) -> SimulationConfig:
    return SimulationConfig.from_dict(
        {
            "dem_file": str(dem_file),
            "output_dir": str(output_dir),
            "save_intermediate": False,
            "time": {
                "t_start": 0.0,
                "t_end": 10.0,
                "dt_initial": 1.0,
                "dt_min": 1.0e-4,
                "dt_max": 1.0,
                "dt_output": 5.0,
                "CFL": 0.5,
                "dt_increase": 0.1,
                "dt_decrease": 0.05,
                "toldh": 1.0,
                "toldhp": 1.0,
            },
            "hydrology": {
                "K_sat": 1.0e-6,
                "theta_s": 0.45,
                "theta_i": 0.2,
                "psi_f": 0.1,
                "depthwt_initial": 7.0,
                "rizero_initial": 1.0e-9,
                "use_background_flux_offset": True,
            },
            "soil": {
                "c": 5000.0,
                "phi": 30.0,
                "gamma_s": 20000.0,
                "gamma_w": 9800.0,
                "depth": 2.0,
                "double_layer": {
                    "enabled": True,
                    "nzst": 4,
                    "nzsb": 4,
                    "ltstar": 1.5,
                    "lbstar": 2.0,
                    "zmin": 0.01,
                    "uww": 7.0,
                    "min_slope_angle_deg": 0.0,
                    "top_layer": {
                        "c": 5000.0,
                        "phi": 30.0,
                        "phib": 15.0,
                        "gamma_s": 20000.0,
                        "K_sat": 1.0e-6,
                        "theta_sat": 0.45,
                        "theta_res": 0.05,
                        "theta_ini": 0.2,
                        "alpha": 2.0,
                        "diffusivity": 1.0e-6,
                    },
                    "bottom_layer": {
                        "c": 8000.0,
                        "phi": 35.0,
                        "phib": 20.0,
                        "gamma_s": 21000.0,
                        "K_sat": 5.0e-7,
                        "theta_sat": 0.4,
                        "theta_res": 0.05,
                        "theta_ini": 0.18,
                        "alpha": 1.5,
                        "diffusivity": 5.0e-7,
                    },
                },
            },
            "rheology": {
                "n_manning": 0.1,
                "alpha1": 0.0765,
                "beta1": 10.11,
                "alpha2": 0.0538,
                "beta2": 17.48,
                "rho_water": 1000.0,
                "rho_sediment": 2650.0,
                "Cv_max": 0.65,
                "limitfr": 1.0,
                "manningb": 0.0538,
                "manningm": 6.0896,
                "kresis": 2500.0,
                "cs": 0.5,
            },
            "erosion": {
                "tau_c": 10.0,
                "k_erosion": 1.0e-6,
                "d50": 0.002,
                "coedepo": 0.01,
            },
            "compute": {
                "backend": "cpu",
                "use_double_precision": True,
            },
            "boundary_conditions": {
                "mode": "auto",
                "default_type": "outflow",
                "include_nodata": True,
            },
        }
    )


def test_checkpoint_restores_auxiliary_solver_state(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    output_a = tmp_path / "out_a"
    output_b = tmp_path / "out_b"
    checkpoint = tmp_path / "restart_state.npz"
    _write_ascii_dem(dem_file)

    config_a = _build_config(dem_file, output_a)
    solver_a = EDDASolver(config_a)
    solver_a.initialize()

    nx, ny = solver_a.fields.nx, solver_a.fields.ny
    solver_a.rheology.manning.from_numpy(np.full((nx, ny), 0.123, dtype=np.float64))
    solver_a.rheology.manning_ori.from_numpy(np.full((nx, ny), 0.456, dtype=np.float64))
    solver_a.rheology.fhmax = 2.5
    solver_a.shallow_water.h_new.from_numpy(np.full((nx, ny), 1.1, dtype=np.float64))
    solver_a.shallow_water.hu_new.from_numpy(np.full((nx, ny), 2.2, dtype=np.float64))
    solver_a.shallow_water.hv_new.from_numpy(np.full((nx, ny), 3.3, dtype=np.float64))
    solver_a.shallow_water.hCv_new.from_numpy(np.full((nx, ny), 4.4, dtype=np.float64))
    solver_a.shallow_water.v_pred.from_numpy(np.full((nx, ny, 8), 5.5, dtype=np.float64))
    solver_a.shallow_water.v_prev.from_numpy(np.full((nx, ny, 8), 6.6, dtype=np.float64))
    solver_a.dfs_dynamic_wave.set_initial_rikzero_field(np.full((nx, ny), 0.789, dtype=np.float64))
    solver_a.time_stepper.t_current = 4.0
    solver_a.time_stepper.dt_current = 0.25
    solver_a.fortran_tempdt = 0.75

    expected_manning = solver_a.rheology.manning.to_numpy().copy()
    expected_manning_ori = solver_a.rheology.manning_ori.to_numpy().copy()
    expected_h_new = solver_a.shallow_water.h_new.to_numpy().copy()
    expected_hu_new = solver_a.shallow_water.hu_new.to_numpy().copy()
    expected_hv_new = solver_a.shallow_water.hv_new.to_numpy().copy()
    expected_hcv_new = solver_a.shallow_water.hCv_new.to_numpy().copy()
    expected_v_pred = solver_a.shallow_water.v_pred.to_numpy().copy()
    expected_v_prev = solver_a.shallow_water.v_prev.to_numpy().copy()
    expected_rikzero = solver_a.dfs_dynamic_wave.initial_rikzero_field.copy()

    solver_a.save_state(str(checkpoint))

    config_b = _build_config(dem_file, output_b)
    solver_b = EDDASolver(config_b)
    solver_b.initialize()
    solver_b.load_state(str(checkpoint))

    np.testing.assert_allclose(solver_b.rheology.manning.to_numpy(), expected_manning)
    np.testing.assert_allclose(solver_b.rheology.manning_ori.to_numpy(), expected_manning_ori)
    assert solver_b.rheology.fhmax == 2.5
    np.testing.assert_allclose(solver_b.shallow_water.h_new.to_numpy(), expected_h_new)
    np.testing.assert_allclose(solver_b.shallow_water.hu_new.to_numpy(), expected_hu_new)
    np.testing.assert_allclose(solver_b.shallow_water.hv_new.to_numpy(), expected_hv_new)
    np.testing.assert_allclose(solver_b.shallow_water.hCv_new.to_numpy(), expected_hcv_new)
    np.testing.assert_allclose(solver_b.shallow_water.v_pred.to_numpy(), expected_v_pred)
    np.testing.assert_allclose(solver_b.shallow_water.v_prev.to_numpy(), expected_v_prev)
    np.testing.assert_allclose(solver_b.shallow_water.manning.to_numpy(), expected_manning)
    np.testing.assert_allclose(solver_b.dfs_dynamic_wave.initial_rikzero_field, expected_rikzero)
    assert solver_b.time_stepper.t_current == 4.0
    assert solver_b.time_stepper.dt_current == 0.25
    assert solver_b.fortran_tempdt == 0.75
