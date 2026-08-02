import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_positive_artifact_multiagent_repair_loop"
)


def test_original_positive_deposition_artifact_is_valid_for_matched_delta():
    validation = json.loads((PHASE / "original_deposition_positive_artifact_validation.json").read_text(encoding="utf-8"))

    assert validation
    assert {row["case"] for row in validation} == {"20a", "50a"}
    assert all(row["classification"] == "VALID_FOR_CURRENT_MATCHED_DELTA" for row in validation)
    assert all(row["nonzero_deporate_count"] > 0 for row in validation)
    assert all(row["deposit_writer_positive_count"] > 0 for row in validation)


def test_current_matched_delta_classifies_deposition_gate_mismatch():
    matrix = (PHASE / "original_current_deposition_positive_delta_matrix.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert "DEPOSITION_GATE_MISMATCH" in matrix
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision

    for case_key in ("20a", "50a"):
        with (PHASE / f"original_current_deposition_positive_delta_{case_key}.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows
        assert any(row["classification"] == "DEPOSITION_GATE_MISMATCH" for row in rows)
        assert any(row["cell_id"] == "35978" for row in rows)
