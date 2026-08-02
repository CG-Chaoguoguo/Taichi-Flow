from __future__ import annotations

import numpy as np

from tests.test_erosion_taoc_fortran_formula import _make_ctao_case
from tests.test_native_runtime_consumption import _initialize_real_solver


def test_fortran_taoc_gate_can_open_when_old_gate_is_blocked(tmp_path):
    edda_in = _make_ctao_case(tmp_path, ctao=1.0)
    solver, _, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_taoc_gate")
    dfs = solver.dfs_dynamic_wave
    shape = (solver.fields.nx, solver.fields.ny)

    cv = 0.10
    h = np.full(shape, 0.5, dtype=np.float64)
    fhpredi1 = np.full(shape, 0.5, dtype=np.float64)
    frhopredi1 = np.full(
        shape,
        solver.config.rheology.rho_water
        + cv * (solver.config.rheology.rho_sediment - solver.config.rheology.rho_water),
        dtype=np.float64,
    )
    high_velocity_faces = np.full((shape[0], shape[1], 8), 100.0, dtype=np.float64)

    solver.fields.h.from_numpy(h)
    solver.fields.Cv.from_numpy(np.full(shape, cv, dtype=np.float64))
    solver.fields.fhpredi1.from_numpy(fhpredi1)
    solver.fields.frhopredi1.from_numpy(frhopredi1)
    solver.fields.fv_fortran.from_numpy(high_velocity_faces)
    solver.fields.phi_field.from_numpy(np.full(shape, 24.0, dtype=np.float64))
    solver.fields.slope_angle.from_numpy(np.full(shape, 0.2, dtype=np.float64))
    solver.fields.tanslo_fortran.from_numpy(np.full(shape, np.tan(0.2), dtype=np.float64))
    solver.fields.ctao_field.from_numpy(np.full(shape, 1.0, dtype=np.float64))
    solver.fields.c_field.from_numpy(np.full(shape, 1.0e7, dtype=np.float64))
    solver.fields.cvlimit_temp.from_numpy(np.full(shape, 0.65, dtype=np.float64))
    solver.fields.rholimit_temp.from_numpy(np.full(shape, 2000.0, dtype=np.float64))
    solver.fields.erodible_thickness.from_numpy(np.full(shape, 10.0, dtype=np.float64))
    solver.fields.n_manning_field.from_numpy(np.full(shape, 0.1, dtype=np.float64))

    dfs._compute_source_rates(
        1.0,
        solver.config.rheology.rho_water,
        solver.config.rheology.rho_sediment,
        solver.config.rheology.Cv_max,
    )

    old_gate_count = int(np.count_nonzero(solver.fields.all_erosion_gate_old_temp.to_numpy()))
    fortran_gate_count = int(np.count_nonzero(solver.fields.all_erosion_gate_fortran_temp.to_numpy()))
    active_gate_count = int(np.count_nonzero(solver.fields.erosion_gate_temp.to_numpy()))

    assert old_gate_count == 0
    assert fortran_gate_count > 0
    assert active_gate_count == fortran_gate_count
    assert float(np.sum(solver.fields.erorate_raw_temp.to_numpy())) > 0.0
