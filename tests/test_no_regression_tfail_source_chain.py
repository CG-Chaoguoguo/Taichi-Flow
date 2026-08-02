from __future__ import annotations

from tests.test_no_regression_source_schedule_consumption import (
    test_source_schedule_consumption_survives_taoc_diagnostics,
)


def test_tfail_source_chain_regression_alias(tmp_path):
    test_source_schedule_consumption_survives_taoc_diagnostics(tmp_path)
