"""Boundary / outflow volume-ledger audits for Fortran-aligned DFS."""

from __future__ import annotations

import inspect

import numpy as np
import taichi as ti

from edda.config.sim_config import SimulationConfig
from edda.core.fields import EDDAFields
from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver, _is_outflow
from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
from edda.solver.edda_solver import EDDASolver, apply_outflow_boundaries_kernel


def test_dfs_is_outflow_ignores_generic_edge_boundary_metadata():
    ti.init(arch=ti.cpu, default_fp=ti.f64)
    fields = EDDAFields(3, 3, 1.0, 1.0, fp_dtype=ti.f64)
    fields.initialize_all()

    # Mark DEM edges as generic outflow boundaries (Taichi auto-detect path).
    boundary_mask = np.zeros((3, 3), dtype=np.int32)
    boundary_types = np.zeros((3, 3), dtype=np.int32)
    boundary_mask[0, :] = 1
    boundary_mask[-1, :] = 1
    boundary_mask[:, 0] = 1
    boundary_mask[:, -1] = 1
    boundary_types[boundary_mask == 1] = 1
    fields.set_boundary_conditions(boundary_mask, boundary_types)

    # Valid edge cell with depth must NOT be treated as Fortran outflow(i).
    fields.h.from_numpy(np.full((3, 3), 0.5, dtype=np.float64))
    assert np.count_nonzero(fields.boundary_type.to_numpy() == 1) == 8
    assert np.count_nonzero(fields.dfs_outflow_mask.to_numpy()) == 0

    total = ti.field(dtype=ti.i32, shape=())
    total[None] = 0

    @ti.kernel
    def count_outflow():
        for i, j in fields.h:
            ti.atomic_add(total[None], _is_outflow(fields, i, j))

    count_outflow()
    assert int(total[None]) == 0


def test_strict_fortran_dfs_path_does_not_apply_generic_outflow_kernel_after_step():
    source = inspect.getsource(EDDASolver._physics_step)
    # Strict plan must keep the Fortran DFS sidecar mask and must not leak
    # generic DEM-edge clearing after an accepted DFS step.
    assert "if step_info.get(\"accepted\", False) and not self.edda_runtime_control_plan.strict:" in source
    assert "apply_outflow_boundaries_kernel(self.fields)" in source
    # Non-strict legacy branch remains; the strict gate is the audited contract.
    assert "Strict EDDA plans use only the sidecar-backed DFS mask" in source


def test_generic_outflow_kernel_clears_only_boundary_type_cells():
    ti.init(arch=ti.cpu, default_fp=ti.f64)
    fields = EDDAFields(2, 2, 1.0, 1.0, fp_dtype=ti.f64)
    fields.initialize_all()
    fields.h.from_numpy(np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64))
    fields.u.from_numpy(np.ones((2, 2), dtype=np.float64))
    fields.v.from_numpy(np.ones((2, 2), dtype=np.float64))
    fields.Cv.from_numpy(np.full((2, 2), 0.4, dtype=np.float64))

    boundary_mask = np.array([[1, 0], [0, 0]], dtype=np.int32)
    boundary_types = np.array([[1, 0], [0, 0]], dtype=np.int32)
    fields.set_boundary_conditions(boundary_mask, boundary_types)

    apply_outflow_boundaries_kernel(fields)

    h = fields.h.to_numpy()
    assert h[0, 0] == 0.0
    assert h[0, 1] == 2.0
    assert h[1, 0] == 3.0
    assert h[1, 1] == 4.0


def test_volume_balance_excludes_outflow_cells_from_source_terms():
    """Match Chamoli dfs.F90:1162-1226 — ri/infil/depo/inflow/erosion/fs omit outflow cells."""
    ti.init(arch=ti.cpu, default_fp=ti.f64)
    fields = EDDAFields(2, 1, 1.0, 1.0, fp_dtype=ti.f64)
    fields.initialize_all()
    fields.cell_area_cal.from_numpy(np.array([[4.0], [4.0]], dtype=np.float64))
    fields.dfs_outflow_mask.from_numpy(np.array([[0], [1]], dtype=np.int32))
    fields.fhpredi2.from_numpy(np.array([[0.5], [0.8]], dtype=np.float64))
    fields.infiltration.from_numpy(np.array([[0.01], [0.02]], dtype=np.float64))
    fields.tempinflowh.from_numpy(np.array([[0.03], [0.04]], dtype=np.float64))
    fields.tempri.from_numpy(np.array([[0.05], [0.06]], dtype=np.float64))
    fields.erosion_rate.from_numpy(np.array([[0.07], [0.08]], dtype=np.float64))
    fields.tempfsh_flow.from_numpy(np.array([[0.09], [0.10]], dtype=np.float64))
    fields.deposition_rate.from_numpy(np.array([[-0.11], [-0.12]], dtype=np.float64))
    fields.temp_depo_thickness.from_numpy(np.array([[0.13], [0.14]], dtype=np.float64))

    cfg = SimulationConfig.from_dict(
        {
            "dem_file": "dummy.asc",
            "output_dir": "./output",
            "save_intermediate": False,
            "compute": {"backend": "cpu", "use_double_precision": True},
            "hydrology": {"dfs_face_flux_variant": "both_thin_weighted"},
            "rheology": {"rho_water": 1000.0, "rho_sediment": 2650.0, "Cv_max": 0.65},
            "erosion": {"d50": 0.002, "coedepo": 0.01},
        }
    )
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))
    solver._reset_volume_balance_accumulators()
    dt = 2.0
    solver._accumulate_volume_balance(dt)

    # Outflow cell contributes only to outflow volume (fhpredi2 * area).
    assert float(solver.acc_outflowvolume[None]) == pytest_approx(0.8 * 4.0)
    # Source terms exclude the outflow cell (index 1).
    assert float(solver.acc_infilvolume[None]) == pytest_approx(0.01 * dt * 4.0)
    assert float(solver.acc_inflowvolume[None]) == pytest_approx(0.03 * 4.0)
    assert float(solver.acc_rivolume[None]) == pytest_approx(0.05 * dt * 4.0)
    assert float(solver.acc_erosionvolume[None]) == pytest_approx(0.07 * dt * 4.0)
    assert float(solver.acc_fsvolume[None]) == pytest_approx(0.09 * 4.0)
    assert float(solver.acc_depovolume[None]) == pytest_approx(0.11 * dt * 4.0)
    # Flow storage excludes outflow; deposit thickness still sums all cells.
    assert float(solver.acc_flowvolume[None]) == pytest_approx(0.5 * 4.0)
    assert float(solver.acc_depositvolume[None]) == pytest_approx((0.13 + 0.14) * 4.0)


def pytest_approx(value: float, rel: float = 1e-12):
    import pytest

    return pytest.approx(value, rel=rel)
