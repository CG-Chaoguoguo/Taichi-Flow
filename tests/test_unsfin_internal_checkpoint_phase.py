from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_unsfin_internal_checkpoint_state_dump_and_restore_probe"
)


def test_phase_localizes_unsfin_timeout_and_keeps_gate_closed():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "UNSFIN_INTERNAL_TIMEOUT_LOCALIZED" in summary
    assert "UNSFIN_Q_ALLOCATION_STATE_ACQUIRED" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision


def test_checkpoint_validation_has_q_state_but_blocks_restore():
    payload = json.loads((PHASE / "unsfin_state_artifact_validation.json").read_text(encoding="utf-8"))
    assert payload["classification"] == "UNSFIN_STATE_DUMP_PARTIAL_REQUIRES_MORE_FIELDS"
    assert payload["q_manifest_exists"] is True
    assert payload["q_manifest"]["q_allocated"] is True
    assert payload["q_manifest"]["q_shape_0"] == 141180
    assert payload["q_manifest"]["q_shape_1"] == 18
    assert payload["restore_allowed"] is False


def test_run_matrix_records_doublelayer_progress_and_no_restore():
    matrix = (PHASE / "unsfin_internal_checkpoint_run_matrix.md").read_text(encoding="utf-8")
    restore = (PHASE / "state_restore_run_matrix.md").read_text(encoding="utf-8")
    assert "unsfin_doublelayer_complete" in matrix
    assert "STATE_RESTORE_NOT_ATTEMPTED_PARTIAL_MANIFEST_ONLY" in restore


def test_progress_log_reaches_unsfin_internal_markers():
    progress = (PHASE / "unsfin_internal_progress_20a.log").read_text(encoding="utf-8")
    assert "unsfin_entry" in progress
    assert "unsfin_after_q_allocate" in progress
    assert "unsfin_q_fill_begin" in progress
