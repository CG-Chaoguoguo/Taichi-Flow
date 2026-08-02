from __future__ import annotations

import numpy as np

from api.services.edda_input_mapper import collect_runtime_source_chain_diagnostics
from tests.test_runtime_source_chain_diagnostics import _make_precomputed_schedule_case
from tests.test_native_runtime_consumption import _initialize_real_solver


def test_precomputed_unsfin_source_depth_and_mass_enter_downstream_predictor(tmp_path):
    edda_in = _make_precomputed_schedule_case(tmp_path)
    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_source_chain")
    solver.fields.erodible_thickness.from_numpy(np.full((solver.fields.nx, solver.fields.ny), 10.0, dtype=np.float64))

    solver.dfs_dynamic_wave.set_current_time(0.0)
    step_info = solver.dfs_dynamic_wave.step(1.0)
    assert step_info["accepted"] is True

    diagnostics = collect_runtime_source_chain_diagnostics(solver, runtime_input_manifest)
    expected_source_depth = 0.6
    expected_source_rho = (
        (solver.config.rheology.rho_sediment - solver.config.rheology.rho_water)
        * solver.config.rheology.Cv_max
        + solver.config.rheology.rho_water
    )

    np.testing.assert_allclose(
        diagnostics["failure_source_flow_depth_sum"],
        expected_source_depth,
        rtol=1.0e-12,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        diagnostics["failure_source_mass_sum"],
        expected_source_depth * expected_source_rho,
        rtol=1.0e-12,
        atol=1.0e-12,
    )
    assert "Cv_sum" in diagnostics
    assert "Cv_max" in diagnostics
    assert diagnostics["Erosion_depth_sum"] >= 0.0
    assert diagnostics["Deposit_depth_sum"] >= 0.0
