from __future__ import annotations

from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_rate_magnitude_state_mapping_fortran_repair"
)


def test_first_event_rate_magnitude_variants_remain_diagnostics_only():
    matrix = PHASE_DIR / "first_event_rate_magnitude_variant_matrix.md"
    constraint = PHASE_DIR / "first_event_variant_original_constraint_report.md"
    decision = PHASE_DIR / "repair_decision.md"
    assert matrix.exists()
    assert constraint.exists()
    assert decision.exists()

    matrix_text = matrix.read_text(encoding="utf-8")
    assert "A_current_full_first_event" in matrix_text
    assert "B_current_original_cell_mask" in matrix_text
    assert "C_swap_original_tau_minus_taoc_for_original_cells" in matrix_text
    assert "`false`" in matrix_text

    decision_text = decision.read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision_text
    assert "FIRST_EVENT_TAU_MINUS_TAOC_MISMATCH" in decision_text
    assert "production repair allowed: `false`" in decision_text
