from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-27\phase_gate_timing_original_internal_artifact_repair"
)


def test_checkpoint_erosion_output_timeline_localizes_residual_to_per_cell_magnitude():
    path = PHASE_DIR / "checkpoint_erosion_output_timeline_after_output_repair.json"
    assert path.exists()

    payload = json.loads(path.read_text(encoding="utf-8"))
    for case_key, original_positive in {"20a": 5, "50a": 4}.items():
        row = payload[case_key]
        assert row["classification"] == "PER_CELL_MAGNITUDE_CANDIDATE"
        assert row["original"]["positive_cells"] == original_positive
        assert row["current_fortran_output"]["positive_erosion_cell_count"] <= original_positive
        assert row["current_fortran_output"]["sum"] > row["original"]["sum"]
        assert row["current_raw"]["sum"] > row["current_fortran_output"]["sum"]
