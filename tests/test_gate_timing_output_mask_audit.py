from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-27\phase_gate_timing_original_internal_artifact_repair"
)


def test_gate_timing_output_mask_audit_shows_fortran_mask_reduces_raw_cells():
    path = PHASE_DIR / "current_gate_timing_output_mask_audit.json"
    assert path.exists()

    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload.values():
        assert row["accepted_step_count"] > 0
        assert row["gate_sum"] > 0
        assert row["raw"]["positive_erosion_cell_count"] > row["exported"]["positive_erosion_cell_count"]
        assert row["raw"]["sum"] > row["exported"]["sum"]
        assert row["exported"]["positive_erosion_cell_count"] == 4
        assert "few-cell magnitude" in row["interpretation"]

