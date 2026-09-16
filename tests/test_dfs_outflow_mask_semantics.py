import numpy as np

import taichi as ti

from edda.core.fields import EDDAFields
from edda.solver.edda_solver import EDDASolver


def test_dfs_outflow_mask_is_separate_from_generic_boundary_metadata():
    ti.init(arch=ti.cpu, default_fp=ti.f64)
    fields = EDDAFields(2, 2, 1.0, 1.0, fp_dtype=ti.f64)
    fields.initialize_all()

    boundary_mask = np.ones((2, 2), dtype=np.int32)
    boundary_types = np.ones((2, 2), dtype=np.int32)
    fields.set_boundary_conditions(boundary_mask, boundary_types)

    assert np.count_nonzero(fields.boundary_type.to_numpy() == 1) == 4
    assert np.count_nonzero(fields.dfs_outflow_mask.to_numpy()) == 0

    sidecar_mask = np.zeros((2, 2), dtype=np.int32)
    sidecar_mask[1, 0] = 1
    fields.dfs_outflow_mask.from_numpy(sidecar_mask)

    np.testing.assert_array_equal(fields.dfs_outflow_mask.to_numpy(), sidecar_mask)


def test_configuring_dfs_outflow_observer_does_not_mutate_generic_boundaries():
    ti.init(arch=ti.cpu, default_fp=ti.f64)
    fields = EDDAFields(2, 2, 1.0, 1.0, fp_dtype=ti.f64)
    fields.initialize_all()
    fields.cell_id.from_numpy(np.array([[1, 2], [3, 4]], dtype=np.int32))

    boundary_mask = np.array([[1, 1], [0, 0]], dtype=np.int32)
    boundary_types = np.array([[2, 2], [0, 0]], dtype=np.int32)
    fields.set_boundary_conditions(boundary_mask, boundary_types)

    solver = EDDASolver.__new__(EDDASolver)
    solver.fields = fields
    solver.configure_outflow_process_observer([3])

    np.testing.assert_array_equal(fields.is_boundary.to_numpy(), boundary_mask)
    np.testing.assert_array_equal(fields.boundary_type.to_numpy(), boundary_types)
    np.testing.assert_array_equal(
        fields.dfs_outflow_mask.to_numpy(),
        np.array([[0, 0], [1, 0]], dtype=np.int32),
    )


def test_strict_outflow_false_cannot_activate_sidecar_mask_through_direct_configuration():
    ti.init(arch=ti.cpu, default_fp=ti.f64)
    fields = EDDAFields(2, 2, 1.0, 1.0, fp_dtype=ti.f64)
    fields.initialize_all()
    fields.cell_id.from_numpy(np.array([[1, 2], [3, 4]], dtype=np.int32))

    class _StrictOutflowDisabled:
        strict = True

        @staticmethod
        def run_enabled(key, *, compatibility_default=True):
            assert key == "simulate_outflow_cell"
            return False

    solver = EDDASolver.__new__(EDDASolver)
    solver.fields = fields
    solver.edda_runtime_control_plan = _StrictOutflowDisabled()

    result = solver.configure_outflow_process_observer([3])

    assert result["configured_cell_count"] == 0
    assert result["disabled_by_control"] is True
    assert np.count_nonzero(fields.dfs_outflow_mask.to_numpy()) == 0
