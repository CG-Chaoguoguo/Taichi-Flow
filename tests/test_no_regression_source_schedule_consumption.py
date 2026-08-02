from __future__ import annotations

import numpy as np

from api.services.edda_input_mapper import collect_runtime_source_chain_diagnostics
from tests.test_native_runtime_consumption import _initialize_real_solver
from tests.test_runtime_source_chain_diagnostics import _make_precomputed_schedule_case


def test_source_schedule_consumption_survives_taoc_diagnostics(tmp_path):
    edda_in = _make_precomputed_schedule_case(tmp_path)
    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_schedule_taoc")
    solver.fields.erodible_thickness.from_numpy(np.full((solver.fields.nx, solver.fields.ny), 10.0, dtype=np.float64))

    solver.dfs_dynamic_wave.set_current_time(0.0)
    step_info = solver.dfs_dynamic_wave.step(1.0)
    assert step_info["accepted"] is True

    diagnostics = collect_runtime_source_chain_diagnostics(solver, runtime_input_manifest)

    assert diagnostics["schedule_loaded"] is True
    assert diagnostics["runtime_active"] is True
    assert diagnostics["consumed_count"] == 2
    assert diagnostics["failure_source_flow_depth_sum"] > 0.0
    assert diagnostics["failure_source_mass_sum"] > 0.0
    assert "count_tau_gt_taoc_old" in diagnostics
    assert "count_tau_gt_taoc_fortran" in diagnostics
    assert "count_all_erosion_gates_true_old" in diagnostics
    assert "count_all_erosion_gates_true_fortran" in diagnostics
