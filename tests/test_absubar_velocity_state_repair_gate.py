from pathlib import Path


PHASE = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_absubar_velocity_state_mapping_source_repair_and_full_paired_validation"
)


def test_absubar_repair_decision_gate_is_evidence_backed():
    text = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "PRODUCTION_REPAIR_ALLOWED_ABSUBAR_VELOCITY_STATE_MAPPING" in text
    assert "ABSUBAR_REPAIR_FULL_G4_IMPROVED" in text
    assert "does not modify coefficients" in text

