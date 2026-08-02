from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_unsfin_full_q_restore_manifest_and_assignment_probe"
)


def test_full_q_serialization_is_acquired_and_sized():
    validation = json.loads((PHASE / "level4_manifest_validation.json").read_text(encoding="utf-8"))
    assert validation["q_serialization_acquired"] is True
    assert validation["q_actual_bytes"] == 141180 * 18 * 8
    assert validation["q_expected_bytes"] == validation["q_actual_bytes"]
    assert validation["manifest"]["q_values_serialized"] is True


def test_restore_loads_arrays_but_fails_before_dfs_with_trace():
    validation = json.loads((PHASE / "level4_manifest_validation.json").read_text(encoding="utf-8"))
    trace = (PHASE / "restore_missing_state_trace.md").read_text(encoding="utf-8")
    assert validation["restore_loaded_arrays"] is True
    assert validation["restore_reached_dfs_entry"] is False
    assert validation["restore_failed_before_dfs"] is True
    assert "state_restore_arrays_loaded" in trace
    assert "SIGSEGV" in trace


def test_gate_stays_closed_without_assignment_artifact():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assignment = (PHASE / "original_assignment_artifact_report.md").read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "ORIGINAL_ASSIGNMENT_ARTIFACT_NOT_ACQUIRED" in assignment
