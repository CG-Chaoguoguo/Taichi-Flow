from __future__ import annotations

import numpy as np

from api.services.edda_input_mapper import collect_runtime_source_chain_diagnostics
from tests.test_native_runtime_consumption import _initialize_real_solver
from tests.test_runtime_source_chain_diagnostics import _make_precomputed_schedule_case


def test_current_downstream_gate_diagnostics_are_observational(tmp_path):
    edda_in = _make_precomputed_schedule_case(tmp_path)
    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_downstream_gates")
    solver.fields.erodible_thickness.from_numpy(np.full((solver.fields.nx, solver.fields.ny), 10.0, dtype=np.float64))

    solver.dfs_dynamic_wave.set_current_time(0.0)
    step_info = solver.dfs_dynamic_wave.step(1.0)

    assert step_info["accepted"] is True
    diagnostics = collect_runtime_source_chain_diagnostics(solver, runtime_input_manifest)

    for key in (
        "erosion_gate_count",
        "deposition_gate_count",
        "rholimit_clamp_count",
        "erodible_clamp_count",
        "erorate_raw_max",
        "erorate_raw_sum",
        "erorate_clamped_max",
        "erorate_clamped_sum",
        "deporate_raw_abs_max",
        "deporate_clamped_abs_sum",
    ):
        assert key in diagnostics

    state = solver.fields.get_full_state()
    for field_name in (
        "tau_temp",
        "taoc_temp",
        "erorate_raw_temp",
        "erorate_clamped_temp",
        "deporate_raw_temp",
        "deporate_clamped_temp",
        "erosion_gate_temp",
        "deposition_gate_temp",
        "rholimit_clamp_temp",
        "erodible_clamp_temp",
    ):
        assert field_name in state
        assert state[field_name].shape == state["h"].shape
