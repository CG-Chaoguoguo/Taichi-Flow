import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_original_deposition_internal_probe_stabilization_and_matched_delta"


def test_original_deposition_stabilization_phase_records_partial_artifact():
    validation = (PHASE / "original_deposition_internal_artifact_validation.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert "ORIGINAL_DEPOSITION_ARTIFACT_PARTIAL_CONSTRAINT_ONLY" in validation
    assert "ORIGINAL_DEPOSITION_PARTIAL_ARTIFACT_ACQUIRED" in decision
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision


def test_original_deposition_first_event_artifacts_are_normalized():
    payload = json.loads((PHASE / "original_deposition_internal_artifact_validation.json").read_text(encoding="utf-8"))

    assert {row["case"] for row in payload} == {"20a", "50a"}
    assert all(row["row_count"] > 0 for row in payload)
    assert all(row["deposition_gate_count"] > 0 for row in payload)
    assert all(row["deporate_nonzero_count"] == 0 for row in payload)
    for case_key in ("20a", "50a"):
        assert (PHASE / f"original_deposition_first_event_{case_key}.csv").exists()
        assert (PHASE / f"original_deposition_first_event_{case_key}.json").exists()
