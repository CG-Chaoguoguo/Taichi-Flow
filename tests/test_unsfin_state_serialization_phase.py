from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_unsfin_state_serialization_for_assignment_loop_artifact"
)


def test_phase_records_dependency_map_ready_and_gate_closed():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "UNSFIN_DFS_STATE_DEPENDENCY_MAP_READY" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision


def test_dependency_map_includes_hidden_unsfin_state_beyond_shortcut():
    payload = json.loads((PHASE / "unsfin_dfs_state_dependency_map.json").read_text(encoding="utf-8"))
    names = {row["state_name"] for row in payload["rows"]}
    assert {"gindx", "tfail", "fdepth", "q"}.issubset(names)
    q_row = next(row for row in payload["rows"] if row["state_name"] == "q")
    assert "UNKNOWN_NEEDS_TRACE" in q_row["classification"]
    assert "imx1 x kper" in q_row["shape"]


def test_dump_schema_requires_manifest_and_checksums():
    payload = json.loads((PHASE / "unsfin_state_dump_schema.json").read_text(encoding="utf-8"))
    items = {row["schema item"] for row in payload["rows"]}
    assert "unsfin_state_manifest.json" in items
    assert "unsfin_state_checksums.json" in items
    assert "q" in items


def test_dump_run_matrix_preserves_timeout_before_unsfin_return():
    matrix = (PHASE / "unsfin_state_dump_run_matrix.md").read_text(encoding="utf-8")
    progress = (PHASE / "unsfin_state_dump_progress.log").read_text(encoding="utf-8")
    assert "UNSFIN_STATE_DUMP_TIMEOUT_BEFORE_UNSFIN_RETURNS" in matrix
    assert "before_unsfin" in progress
    assert "after_unsfin" not in progress


def test_state_dump_and_restore_patch_scaffolds_are_retained():
    dump_patch = ROOT / "tests" / "_fortran_toolchain_sandbox" / "patches" / "instrument_unsfin_state_dump.patch"
    restore_patch = (
        ROOT
        / "tests"
        / "_fortran_toolchain_sandbox"
        / "patches"
        / "instrument_unsfin_state_restore_and_assignment_probe.patch"
    )
    assert dump_patch.exists()
    assert restore_patch.exists()
    assert "unsfin_state_manifest.json" in dump_patch.read_text(encoding="utf-8")
    assert "state_restore_complete" in restore_patch.read_text(encoding="utf-8")
