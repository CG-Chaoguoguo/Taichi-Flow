import numpy as np

from tools.run_cuda_candidate_case import fortran_ssvgrd_g12p4_numeric


def test_fortran_ssvgrd_g12p4_uses_fixed_branch_after_rounding_to_point_one() -> None:
    values = np.asarray([[0.0, 0.09996865235553248, 0.0123456, 1.23456]], dtype=np.float64)

    formatted = fortran_ssvgrd_g12p4_numeric(values)

    np.testing.assert_allclose(
        formatted,
        np.asarray([[0.0, 0.1000, 0.01235, 1.2346]], dtype=np.float64),
        rtol=0.0,
        atol=0.0,
    )
