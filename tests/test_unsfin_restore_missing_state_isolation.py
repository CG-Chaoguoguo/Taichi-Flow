from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_unsfin_restore_missing_state_isolation_and_dfs_entry"
)


def test_restore_reaches_before_dfs_but_not_dfs_entry():
    validation = json.loads((PHASE / "restore_validation_report.json").read_text(encoding="utf-8"))
    assert validation["restore_reached_before_dfs"] is True
    assert validation["restore_reached_dfs_entry"] is False
    assert validation["last_marker"] == "before_dfs"


def test_allocatable_status_contains_restored_core_state():
    matrix = (PHASE / "restore_allocatable_status_matrix.md").read_text(encoding="utf-8")
    assert "| q | T | 141180 | 18 |" in matrix
    assert "| gindx | T | 141180 | 0 |" in matrix
    assert "| tfail | T | 141180 | 0 |" in matrix
    assert "| fdepth | T | 141180 | 0 |" in matrix


def test_precise_trace_keeps_production_gate_closed():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "RESTORE_REACHES_BEFORE_DFS" in summary
    assert "RESTORE_FAILED_WITH_PRECISE_STATEMENT_TRACE" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
