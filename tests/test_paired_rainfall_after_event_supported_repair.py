from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_original_event_probe_stabilization_and_checkpoint_constrained_gate_repair"
)


def test_no_event_supported_production_repair_was_applied_without_original_artifact():
    fix_log = PHASE_DIR / "production_fix_log.md"
    gate = PHASE_DIR / "acceptance_gate_update.md"
    assert fix_log.exists()
    assert gate.exists()
    fix_text = fix_log.read_text(encoding="utf-8")
    gate_text = gate.read_text(encoding="utf-8")
    assert "No active production solver formula changed in this phase" in fix_text
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in gate_text

