from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_original_dfs_call_boundary_stabilization_and_event_artifact_repair"
)


def test_dfs_noop_stub_classifies_real_dfs_prologue_crash_without_production_repair():
    matrix = json.loads((PHASE_DIR / "original_dfs_call_boundary_probe_matrix.json").read_text(encoding="utf-8-sig"))
    assert matrix["status"] == "DFS_NOOP_STUB_SUCCEEDS_REAL_DFS_PROLOGUE_CRASH"
    assert matrix["production_repair_allowed"] is False

    progress = (PHASE_DIR / "dfs_noop_stub_progress_20a.log").read_text(encoding="utf-8")
    assert "before_dfs" in progress
    assert "dfs_noop_stub_entered" in progress
    assert "after_dfs" in progress

    args = (PHASE_DIR / "dfs_noop_stub_args_20a.txt").read_text(encoding="utf-8")
    assert "imx1=141180" in args
    assert "u_count=28" in args
