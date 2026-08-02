from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_original_event_probe_stabilization_and_checkpoint_constrained_gate_repair"
)


def test_bed_elevation_coupling_variants_remain_evidence_gated():
    report = PHASE_DIR / "bed_elevation_coupling_variant_matrix.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "original_event_required" in text
    assert "production eligible" in text
    assert "false" in text
    assert "Output writer parity is already active" in text

