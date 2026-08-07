from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_dfs_prologue_local_storage_unblock_and_original_event_artifact"
)


def test_dfs_prologue_storage_probe_unblocks_original_event_artifact():
    matrix = json.loads((PHASE_DIR / "original_dfs_prologue_storage_probe_matrix.json").read_text(encoding="utf-8"))
    assert matrix["status"] == "ORIGINAL_INTERNAL_EVENT_ARTIFACT_ACQUIRED"
    assert matrix["production_repair_allowed"] is False

    classifications = {item["classification"] for item in matrix["variants"]}
    assert "DFS_NON_ARRAY_GUARD_ALLOWS_ENTRY" in classifications
    assert "ORIGINAL_INTERNAL_EVENT_ARTIFACT_ACQUIRED" in classifications


def test_dfs_prologue_storage_audit_records_voltonode_risk():
    audit = (PHASE_DIR / "dfs_prologue_local_storage_audit.md").read_text(encoding="utf-8")
    assert "voltonode=0." in audit
    assert "DFS_DRAINAGE_NON_ARRAY_RISK_MAPPED" in audit

