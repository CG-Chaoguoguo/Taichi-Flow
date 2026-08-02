from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_unsfin_state_dump_restore_assignment_artifact"
)


def test_phase_records_state_dump_runtime_blocker():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "UNSFIN_STATE_DUMP_TIMEOUT_OR_RUNTIME_BLOCKED" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision


def test_dump_patch_report_confirms_buildable_patch_and_copy_support():
    report = (PHASE / "unsfin_state_dump_patch_report.md").read_text(encoding="utf-8")
    assert "UNSFIN_STATE_DUMP_PATCH_READY" in report
    assert "built_with_gfortran" in report
    assert "run script copies state artifacts" in report


def test_state_dump_validation_blocks_restore_without_manifest():
    validation = json.loads((PHASE / "unsfin_state_artifact_validation.json").read_text(encoding="utf-8"))
    assert validation["classification"] == "UNSFIN_STATE_DUMP_INVALID"
    assert validation["restore_allowed"] is False
    assert validation["dump_files"]["manifest"] is False
    restore = (PHASE / "state_restore_run_matrix.md").read_text(encoding="utf-8")
    assert "STATE_RESTORE_NOT_ATTEMPTED_NO_VALID_DUMP" in restore


def test_progress_log_never_reaches_after_unsfin():
    progress = (PHASE / "unsfin_state_dump_progress.log").read_text(encoding="utf-8")
    assert "before_unsfin" in progress
    assert "after_unsfin" not in progress
    assert "state_dump_complete" not in progress
