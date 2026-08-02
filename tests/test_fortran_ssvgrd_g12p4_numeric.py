import numpy as np
import pytest

try:
    from tools.fortran_ssvgrd_format import fortran_ssvgrd_g12p4_numeric
except ModuleNotFoundError:
    from fortran_ssvgrd_format import fortran_ssvgrd_g12p4_numeric  # type: ignore[no-redef]


def test_g12p4_fixed_branch_uses_four_significant_digits() -> None:
    values = np.asarray(
        [
            1.008172492213332,
            -1.008172492213332,
            0.099968,
            0.0,
        ],
        dtype=np.float64,
    )

    formatted = fortran_ssvgrd_g12p4_numeric(values)

    assert formatted[0] == pytest.approx(1.008)
    assert formatted[1] == pytest.approx(-1.008)
    assert formatted[2] == pytest.approx(0.1)
    assert formatted[3] == pytest.approx(0.0)
