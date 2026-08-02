from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_deposition_phase_records_no_production_repair_and_next_blocker():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    fix_log = (PHASE / "production_fix_log.md").read_text(encoding="utf-8")

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "NEXT_LOOP_FLOW_RESPONSE_OR_INTERNAL_ARTIFACT" in decision
    assert "No active production solver or writer formula changed" in fix_log
