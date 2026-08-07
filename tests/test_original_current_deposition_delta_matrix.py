import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_delta_matrix_is_skipped_without_original_internal_artifact():
    matrix = (PHASE / "original_current_deposition_internal_delta_matrix.md").read_text(encoding="utf-8")
    payload = json.loads((PHASE / "original_current_deposition_internal_delta_matrix.json").read_text(encoding="utf-8"))

    assert "ORIGINAL_ARTIFACT_ABSENT_DELTA_MATRIX_SKIPPED" in matrix
    assert payload
    assert all(row["status"] == "ORIGINAL_ARTIFACT_ABSENT_DELTA_MATRIX_SKIPPED" for row in payload)
