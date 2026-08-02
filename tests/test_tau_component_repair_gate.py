from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_tau_component_original_artifact_and_state_mapping_repair"
)


def test_tau_component_repair_gate_blocks_active_formula_change():
    decision = (PHASE_DIR / "repair_decision.md").read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "localized status: `FIRST_EVENT_ABSUBAR_STATE_MISMATCH`" in decision
    assert "production repair allowed: `false`" in decision

    production_log = (PHASE_DIR / "production_fix_log.md").read_text(encoding="utf-8")
    assert "active production solver formula changed: `false`" in production_log
