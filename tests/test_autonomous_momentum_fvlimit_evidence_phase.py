from __future__ import annotations

import json
from pathlib import Path


PHASE = (
    Path(__file__).resolve().parents[1]
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_autonomous_tracked_scalar_momentum_evidence_and_repair"
)


def test_autonomous_phase_records_precise_original_runtime_blocker():
    validation = (PHASE / "original_tracked_scalar_momentum_terms_validation.md").read_text(encoding="utf-8")
    assert "ORIGINAL_TRACKED_SCALAR_MOMENTUM_ARTIFACT_FAILED_WITH_TRACE" in validation
    assert "timed out before `after_unsfin`" in validation
    assert "SIGSEGV" in validation


def test_delta_remains_current_only_without_production_repair():
    payload = json.loads((PHASE / "tracked_scalar_momentum_term_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ORIGINAL_TRACKED_SCALAR_MOMENTUM_ARTIFACT_FAILED_WITH_TRACE"
    assert payload["repair_decision"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["classification"] == "ORIGINAL_ARTIFACT_INSUFFICIENT_FOR_DELTA"
    assert payload["original_artifact_status"] == "failed_with_trace"


def test_missing_evidence_index_names_fvlimit_and_predictor_terms():
    text = (PHASE / "missing_evidence_index.md").read_text(encoding="utf-8")
    assert "original `fvlimit`" in text
    assert "original `fvpredi` before clamp" in text
    assert "original mirrored opposite-direction `fvpredi`" in text


def test_repair_decision_keeps_gate_closed():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "No production repair was made" in decision
