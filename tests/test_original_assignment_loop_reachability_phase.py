from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_original_assignment_loop_reachability_and_term_artifact"
)


def test_phase_records_unsfin_state_serialization_status():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")
    assert "ORIGINAL_ASSIGNMENT_LOOP_REQUIRES_UNSFIN_STATE_SERIALIZATION" in summary
    assert "LIVE_UNSFIN_TIMEOUT_BEFORE_DFS_ASSIGNMENT_LOOP" in handoff


def test_reachability_audit_confirms_assignment_probe_ready_but_dfs_not_reached():
    audit = (PHASE / "assignment_loop_reachability_audit.md").read_text(encoding="utf-8")
    chain = (PHASE / "assignment_probe_build_run_chain_report.md").read_text(encoding="utf-8")
    assert "assignment probe is at assignment sites" in audit
    assert "build script recognizes patch" in audit
    assert "run script copies artifacts" in audit
    assert "`TIMEOUT`" in chain
    assert "`before_unsfin`" in chain


def test_original_assignment_artifact_validation_marks_invalid_no_terms():
    payload = json.loads(
        (PHASE / "original_assignment_term_artifact_validation.json").read_text(encoding="utf-8")
    )
    assert payload["classification"] == "INVALID_ORIGINAL_ASSIGNMENT_MOMENTUM_TERMS"
    assert payload["failure_classification"] == "LIVE_UNSFIN_TIMEOUT_BEFORE_DFS"
    assert payload["artifact_raw_exists"] is False
    assert payload["artifact_meta_exists"] is False


def test_progress_log_stops_before_unsfin_and_repair_gate_closed():
    progress = (PHASE / "original_assignment_probe_progress.log").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "before_unsfin" in progress
    assert "after_unsfin" not in progress
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
