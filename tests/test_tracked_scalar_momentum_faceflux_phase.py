from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE = (
    Path(__file__).resolve().parents[1]
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_tracked_scalar_momentum_faceflux_runtime_artifact_and_delta"
)


def _read_rows(case: str) -> list[dict[str, str]]:
    path = PHASE / f"current_momentum_faceflux_runtime_terms_{case}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_current_tracked_scalar_artifacts_capture_consumed_predictor_rows():
    for case in ("20a", "50a"):
        rows = _read_rows(case)
        scopes = {row["record_scope"] for row in rows}
        assert "source_entry_consumed_previous_face_predictor" in scopes
        assert "current_step_face_predictor_after_source_branch" in scopes
        consumed = next(row for row in rows if row["record_scope"] == "source_entry_consumed_previous_face_predictor")
        assert int(consumed["target_cell_id"]) == 35978
        assert int(consumed["target_direction"]) == 5
        assert int(consumed["clamp_status"]) == 1


def test_delta_matrix_keeps_production_gate_closed_without_original_terms():
    payload = json.loads((PHASE / "momentum_faceflux_runtime_term_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "CURRENT_TRACKED_SCALAR_MOMENTUM_ARTIFACT_ACQUIRED"
    assert payload["repair_decision"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["original_artifact_status"] == "missing"
    rows = payload["rows"]
    assert any(row["record_scope"] == "source_entry_consumed_previous_face_predictor" for row in rows)


def test_reports_forbid_full_grid_momentum_strategy():
    plan = (PHASE / "runtime_term_artifact_plan.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "No full-grid `momentum_*` fields are exported" in plan
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
