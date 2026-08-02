import numpy as np

import taichi as ti

from edda.core.fields import EDDAFields


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
