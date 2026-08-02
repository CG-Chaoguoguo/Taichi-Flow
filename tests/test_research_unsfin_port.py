from __future__ import annotations

import numpy as np
import pytest

from edda.research.fortran_unsfin_port.research_unsfin_port import (
    attach_supplied_tfail,
    scaffold_from_ls_scar_and_faildph,
    validate_unsfin_scaffold,
)


def test_research_unsfin_scaffold_does_not_infer_tfail():
    ls_scar = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float64)
    faildph = np.array([[0.2, 0.0], [0.4, 0.0]], dtype=np.float64)

    scaffold = scaffold_from_ls_scar_and_faildph(ls_scar, faildph)
    summary = validate_unsfin_scaffold(scaffold)

    assert scaffold.tfail_s is None
    assert summary["validated_provider_status"] == "scaffold_only"
    assert summary["tfail_status"] == "absent_not_inferred"
    assert summary["active_scaffold_count"] == 2
    assert summary["fdepth_sum"] == pytest.approx(0.6)


def test_research_unsfin_scaffold_rejects_tfail_inference_request():
    with pytest.raises(ValueError, match="cannot be used to infer"):
        scaffold_from_ls_scar_and_faildph(
            np.array([[1.0]], dtype=np.float64),
            np.array([[0.2]], dtype=np.float64),
            infer_tfail=True,
        )


def test_research_unsfin_scaffold_accepts_separately_supplied_tfail():
    scaffold = scaffold_from_ls_scar_and_faildph(
        np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float64),
        np.array([[0.2, 0.0], [0.4, 0.0]], dtype=np.float64),
    )
    scheduled = attach_supplied_tfail(
        scaffold,
        np.array([[100.0, 9999.0], [700.0, 9999.0]], dtype=np.float64),
    )

    summary = validate_unsfin_scaffold(scheduled)

    assert summary["validated_provider_status"] == "schedule_supplied"
    assert summary["tfail_active_count"] == 2
    assert summary["tfail_lte_600_count"] == 1
