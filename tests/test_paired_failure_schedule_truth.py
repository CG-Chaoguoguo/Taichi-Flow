from __future__ import annotations

from pathlib import Path

import numpy as np


CASE_20_RESULTS = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a\results"
)
CASE_50_RESULTS = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_50a\NO.5_XHG_V2_50a\results"
)


def _load_ascii_grid(path: Path) -> tuple[np.ndarray, float | None]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        header: dict[str, float] = {}
        for _ in range(6):
            key, value = handle.readline().split()[:2]
            header[key.lower()] = float(value) if "." in value or "e" in value.lower() else int(value)
        data = np.loadtxt(handle).astype(np.float64)
    return data, float(header.get("nodata_value", -9999.0))


def _valid_values(path: Path) -> np.ndarray:
    data, nodata = _load_ascii_grid(path)
    if nodata is None:
        return data.reshape(-1)
    mask = ~np.isclose(data, nodata)
    return data[mask]


def test_original_paired_cases_share_identical_failure_scaffold_at_600s():
    for filename in ("LS_ScarEDDA_600.0.txt", "faildphEDDA_600.0.txt"):
        values_20 = _valid_values(CASE_20_RESULTS / filename)
        values_50 = _valid_values(CASE_50_RESULTS / filename)
        assert values_20.shape == values_50.shape
        assert np.array_equal(values_20, values_50), filename


def test_original_paired_cases_already_diverge_downstream_of_scaffold_at_600s():
    for filename in (
        "Flow_depth_EDDA_600.0.txt",
        "Volumetric_sediment_conceEDDA_600.0.txt",
        "Deposit_depth_EDDA_600.0.txt",
        "Erosion_depth_EDDA_600.0.txt",
    ):
        values_20 = _valid_values(CASE_20_RESULTS / filename)
        values_50 = _valid_values(CASE_50_RESULTS / filename)
        assert values_20.shape == values_50.shape
        delta = values_50 - values_20
        assert np.count_nonzero(np.abs(delta) > 1.0e-12) > 0, filename
        assert abs(float(np.sum(delta))) > 0.0, filename
