from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_rate_magnitude_state_mapping_fortran_repair"
)


def test_original_current_first_event_comparison_preserves_evidence_gate():
    report = PHASE_DIR / "original_current_first_erosion_event_comparison.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "production_repair_allowed: `false`" in text
    assert "220.254" in text
    assert "ORIGINAL_CURRENT_EVENT_TIMING_ALIGNED_NEXT_RATE_MAGNITUDE" in text
    assert "FIRST_EVENT_TAU_MINUS_TAOC_MISMATCH" in text

