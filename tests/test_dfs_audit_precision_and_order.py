"""Explicit dtype and kernel/host face-order contracts, independent of defaults."""
import numpy as np
import pytest
import taichi as ti

from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver, DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV
from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
from tests.test_dfs_dynamic_wave import _build_config, _build_fields


@pytest.mark.parametrize("owner,order,source", [(False, 10, 0), (True, 22, 1)])
def test_host_face_order_matches_kernel_and_rejected_prefix(monkeypatch, owner, order, source):
    monkeypatch.setenv(DFS_FORTRAN_FACE_OWNER_MAX_CELL_ENV, str(int(owner)))
    ti.init(arch=ti.cpu, default_fp=ti.f64, fast_math=False)
    f = _build_fields()
    solver = DFSDynamicWaveSolver(f, _build_config(face_flux_variant="arithmetic_mean_chamoli"), FortranDynamicWaveWorkspace(f))
    si, sj, ni, nj = solver._ensure_legacy_fortran_order_face_pairs()
    np.testing.assert_array_equal(si, [source])
    np.testing.assert_array_equal(ni, [1-source])
    np.testing.assert_array_equal(solver._legacy_fortran_order_face_pair_order, [order])
    f.fhpredi.fill(1.0)
    f.frhopredi.from_numpy(np.array([[1165.], [1495.]], dtype=np.float64))
    solver.legacy_previous_face_cvbar_scalar = 0.275
    solver._update_legacy_previous_face_cvbar_scalar(cfl_stop_order=order-1)
    assert solver.legacy_previous_face_cvbar_scalar == 0.275
    solver._update_legacy_previous_face_cvbar_scalar(assignment_order=order)
    assert solver.legacy_previous_face_cvbar_scalar == pytest.approx(0.2, abs=1e-15)
    with pytest.raises(RuntimeError, match="no unique"):
        solver._update_legacy_previous_face_cvbar_scalar(assignment_order=order+1)


def test_f64_flux_sum_does_not_inherit_f32_runtime_local_type():
    ti.init(arch=ti.cpu, default_fp=ti.f32, fast_math=False)
    f = _build_fields()  # Explicitly f64 fields, despite the f32 runtime default.
    solver = DFSDynamicWaveSolver(f, _build_config(), FortranDynamicWaveWorkspace(f))
    flux = np.array([1.e8, 1., -1.e8, 0.1, 0.2, 0., 0., 0.], dtype=np.float64)
    qq = np.tile(flux, (2, 1, 1))
    f.qq_fortran.from_numpy(qq)
    f.qqmass_fortran.from_numpy(qq * 1650.)
    before = f.h.to_numpy().copy()
    solver._diagnostic_qnet_qmassnet_accumulation_kernel()
    def serial_sum(values):
        acc = 0.0
        for value in values:
            acc -= float(value)
        return acc
    np.testing.assert_array_equal(solver.qnet_diag_kernel.to_numpy(), np.full((2, 1), serial_sum(flux)))
    np.testing.assert_array_equal(solver.qmassnet_diag_kernel.to_numpy(), np.full((2, 1), serial_sum(flux * 1650.)))
    np.testing.assert_array_equal(f.h.to_numpy(), before)
