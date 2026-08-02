from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_original_erosion_event_probe_and_gate_timing_repair"
)


def test_bed_elevation_audit_does_not_claim_unproven_repair_candidate():
    report = PHASE_DIR / "bed_elevation_erosion_coupling_audit.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "WRITER_PARITY_ALIGNED_NEXT_GATE_TIMING" in text
    assert "unresolved" in text
    assert "no repair candidate" in text

