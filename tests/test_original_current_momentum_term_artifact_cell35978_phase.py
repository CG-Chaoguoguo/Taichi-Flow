from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE = (
    Path(__file__).resolve().parents[1]
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_original_current_momentum_term_artifact_cell35978"
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_phase_status_advances_to_valid_partial_original_artifact():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    validation = (PHASE / "original_tracked_scalar_momentum_terms_validation.md").read_text(
        encoding="utf-8"
    )
    assert "phase_original_current_momentum_term_artifact_cell35978" in summary
    assert "VALID_PARTIAL_ORIGINAL_TRACKED_SCALAR_MOMENTUM_TERMS" in summary
    assert "VALID_PARTIAL_ORIGINAL_TRACKED_SCALAR_MOMENTUM_TERMS" in validation


def test_original_and_current_artifacts_align_target_cell_direction_and_contributor():
    original = _rows(PHASE / "original_tracked_scalar_momentum_terms_20a.csv")[0]
    current = _rows(PHASE / "current_tracked_scalar_momentum_terms_20a.csv")[0]
    assert int(original["cell_id"]) == 35978
    assert int(original["direction_0based"]) == 5
    assert int(original["contributor_cell_id_from_current_source_trace"]) == 36238
    assert int(current["target_cell_id"]) == 35978
    assert int(current["target_direction"]) == 5
    assert int(current["neighbor_cell_id"]) == 36238


def test_delta_matrix_keeps_production_gate_closed_until_runtime_terms_exist():
    payload = json.loads(
        (PHASE / "tracked_scalar_momentum_term_delta_matrix.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "VALID_PARTIAL_ORIGINAL_TRACKED_SCALAR_MOMENTUM_TERMS"
    assert payload["repair_decision"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["original_artifact_status"] == "partial"
    assert payload["classification"] == "ORIGINAL_RUNTIME_TERMS_PARTIAL_DELTA_ONLY"
    assert payload["rows"][0]["production_eligibility"] == (
        "not_allowed_missing_original_fvlimit_dv_momentum_terms"
    )


def test_sandbox_scripts_are_ready_but_runtime_blocker_remains():
    plan = (PHASE / "original_tracked_scalar_probe_plan.md").read_text(encoding="utf-8")
    failure = (PHASE / "original_probe_failure_trace.md").read_text(encoding="utf-8")
    assert "build_instrumented_edda.ps1" in plan
    assert "run_instrumented_original_cases.ps1" in plan
    assert "`ready`" in plan
    assert "before_unsfin" in failure
    assert "SIGSEGV" in failure
