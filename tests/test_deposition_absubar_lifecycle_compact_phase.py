from pathlib import Path


PHASE = Path(
    "PROJECT_REPORTS/agent_runs/2026-04-29/phase_deposition_absubar_fvdepo_lifecycle_compact_agent_loop"
)


def test_compact_phase_directional_velocity_delta_classifies_lifecycle_mismatch():
    report = PHASE / "full_deposition_directional_velocity_delta_matrix.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "DEPOSITION_ABSUBAR_VELOCITY_LIFECYCLE_MISMATCH" in text
    assert "branch_velocity_state_scale=0.5" in text
    assert "vcomp" in text


def test_compact_phase_keeps_repair_gate_closed_without_original_directional_components():
    original_validation = PHASE / "original_deposition_directional_velocity_validation.md"
    repair_decision = PHASE / "repair_decision.md"
    variant_matrix = PHASE / "deposition_directional_velocity_variant_matrix.md"
    for path in (original_validation, repair_decision, variant_matrix):
        assert path.exists()

    assert "VALID_ABSUBAR_ONLY" in original_validation.read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in repair_decision.read_text(encoding="utf-8")
    assert "VARIANTS_AUDIT_ONLY_NO_PRODUCTION_CHANGE" in variant_matrix.read_text(encoding="utf-8")
