from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_original_erosion_event_probe_and_gate_timing_repair"
)


def test_no_production_change_keeps_g4_metrics_carried_forward():
    fix_log = (PHASE_DIR / "production_fix_log.md").read_text(encoding="utf-8")
    delta = (PHASE_DIR / "delta_of_delta_matrix.md").read_text(encoding="utf-8")
    assert "No active production solver formula changed" in fix_log
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in fix_log
    assert "0.0515026" in delta
    assert "0.123435" in delta
    assert "0.0681378" in delta
