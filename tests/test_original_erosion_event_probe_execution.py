from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_dfs_prologue_local_storage_unblock_and_original_event_artifact"
)


def test_original_erosion_event_probe_execution_records_valid_original_event_artifact():
    progress = PHASE_DIR / "original_erosion_event_probe_progress.txt"
    assert progress.exists()
    text = progress.read_text(encoding="utf-8")
    assert "20a" in text
    assert "220.25399999999999" in text

    status_20a = json.loads((PHASE_DIR / "original_erosion_event_probe_20a.json").read_text(encoding="utf-8"))
    assert status_20a["artifact_acquired"] is True
    assert status_20a["status"] == "ORIGINAL_INTERNAL_EVENT_ARTIFACT_ACQUIRED"
    assert status_20a["validation_status"] == "ORIGINAL_EVENT_ARTIFACT_VALID_FOR_TIMING"
    assert status_20a["event_row"]["tnow"].strip().startswith("220.253999")

    status_50a = json.loads((PHASE_DIR / "original_erosion_event_probe_50a.json").read_text(encoding="utf-8"))
    assert status_50a["artifact_acquired"] is True
    assert status_50a["status"] == "ORIGINAL_INTERNAL_EVENT_ARTIFACT_ACQUIRED"
    assert status_50a["validation_status"] == "ORIGINAL_EVENT_ARTIFACT_VALID_FOR_TIMING"
    assert status_50a["event_row"]["tnow"].strip().startswith("220.253999")

