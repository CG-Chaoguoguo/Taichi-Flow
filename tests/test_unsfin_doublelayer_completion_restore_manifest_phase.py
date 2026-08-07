from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_unsfin_doublelayer_completion_and_restore_manifest"
)


def test_phase_advances_to_doublelayer_completed_and_keeps_gate_closed():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "UNSFIN_DOUBLELAYER_COMPLETED" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision


def test_progress_reaches_state_dump_complete_and_before_dfs():
    report = (PHASE / "unsfin_doublelayer_progress_report.md").read_text(encoding="utf-8")
    assert "unsfin_before_return" in report
    assert "state_dump_complete" in report
    assert "before_dfs" in report


def test_restore_manifest_is_acquired_but_not_level4_valid():
    validation = json.loads((PHASE / "restore_validation_report.json").read_text(encoding="utf-8"))
    assert validation["manifest_exists"] is True
    assert validation["manifest"]["gindx_allocated"] is True
    assert validation["manifest"]["tfail_allocated"] is True
    assert validation["manifest"]["fdepth_allocated"] is True
    assert validation["manifest"]["q_allocated"] is True
    assert validation["restore_allowed"] is False
    assert validation["classification"] == "RESTORE_MANIFEST_PARTIAL_NOT_LEVEL4_VALID"


def test_restore_not_attempted_and_assignment_artifact_unavailable():
    restore = (PHASE / "restore_run_matrix.md").read_text(encoding="utf-8")
    assignment = (PHASE / "original_assignment_artifact_report.md").read_text(encoding="utf-8")
    assert "STATE_RESTORE_NOT_ATTEMPTED_PARTIAL_MANIFEST_ONLY" in restore
    assert "ORIGINAL_ASSIGNMENT_ARTIFACT_NOT_ATTEMPTED" in assignment
