from __future__ import annotations

import csv
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-27\phase_gate_timing_original_internal_artifact_repair"
)


def test_cell_level_erosion_tracking_contains_original_and_current_positive_sets():
    path = PHASE_DIR / "cell_level_original_current_erosion_tracking_600s.csv"
    assert path.exists()

    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    assert rows
    assert {"20a", "50a"} <= {row["case"] for row in rows}

    for case_key in ("20a", "50a"):
        case_rows = [row for row in rows if row["case"] == case_key]
        assert any(row["original_positive"] == "True" for row in case_rows)
        assert any(row["current_positive"] == "True" for row in case_rows)
        assert any(row["overlap_positive"] == "True" for row in case_rows)

