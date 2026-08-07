from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE = (
    Path(__file__).resolve().parents[1]
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_original_tracked_scalar_momentum_artifact_acquisition_and_delta"
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_original_partial_artifact_is_retained_for_cell_35978_d6():
    validation = (PHASE / "original_tracked_scalar_momentum_terms_validation.md").read_text(
        encoding="utf-8"
    )
    assert "VALID_PARTIAL_ORIGINAL_TRACKED_SCALAR_MOMENTUM_TERMS" in validation
    for case in ("20a", "50a"):
        rows = _rows(PHASE / f"original_tracked_scalar_momentum_terms_{case}.csv")
        assert len(rows) == 1
        row = rows[0]
        assert int(row["cell_id"]) == 35978
        assert int(row["direction_0based"]) == 5
        assert row["selected_direction"] == "vcomp"
        assert float(row["absubar"]) > 0.0
        assert row["fvlimit"] == "missing_runtime_term"


def test_delta_records_partial_original_status_and_keeps_repair_gate_closed():
    payload = json.loads(
        (PHASE / "tracked_scalar_momentum_term_delta_matrix.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "VALID_PARTIAL_ORIGINAL_TRACKED_SCALAR_MOMENTUM_TERMS"
    assert payload["repair_decision"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["original_artifact_status"] == "partial"
    assert payload["classification"] == "ORIGINAL_RUNTIME_TERMS_PARTIAL_DELTA_ONLY"
    assert "SOURCE_ENTRY_PREDICTOR_DIFFERENCE_OBSERVED" in payload["candidate_mismatch"]


def test_probe_execution_matrix_preserves_precise_full_runtime_failure_trace():
    matrix = (PHASE / "original_probe_execution_matrix.md").read_text(encoding="utf-8")
    trace = (PHASE / "original_probe_failure_trace.md").read_text(encoding="utf-8")
    assert "before_unsfin" in matrix
    assert "SIGSEGV" in matrix
    assert "before_unsfin" in trace
    assert "SIGSEGV" in trace


def test_next_handoff_names_remaining_full_runtime_terms_blocker():
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "ORIGINAL_FULL_MOMENTUM_RUNTIME_TERMS_STILL_MISSING" in handoff
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
