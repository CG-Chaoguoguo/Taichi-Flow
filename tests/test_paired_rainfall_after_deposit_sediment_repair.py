from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_deposit_phase_records_no_production_repair_and_next_blocker():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    blockers = (PHASE / "remaining_blockers.md").read_text(encoding="utf-8")

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "NEXT_LOOP_DEPOSITION_INTERNAL_ARTIFACT_OR_FLOW_RESPONSE" in decision
    assert "Deposit_depth" in blockers
    assert "original internal deposition state" in blockers
