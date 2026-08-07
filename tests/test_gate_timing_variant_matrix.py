from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_original_event_probe_stabilization_and_checkpoint_constrained_gate_repair"
)


def test_gate_timing_variant_matrix_is_audit_only_without_original_event():
    report = PHASE_DIR / "gate_timing_variant_matrix.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "original_event_required" in text
    assert "audit_only" in text
    assert "false" in text

