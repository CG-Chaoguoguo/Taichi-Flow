from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_dfs_prologue_local_storage_unblock_and_original_event_artifact"
)


def test_original_event_probe_parser_records_valid_timing_artifacts():
    validation_path = PHASE_DIR / "original_erosion_event_probe_validation.json"
    assert validation_path.exists()
    payload = json.loads(validation_path.read_text(encoding="utf-8"))
    assert payload["aggregate_status"] == "ORIGINAL_INTERNAL_EVENT_ARTIFACT_ACQUIRED"

    for case_key, case_payload in payload["cases"].items():
        assert case_key in {"20a", "50a"}
        assert case_payload["validation_status"] == "ORIGINAL_EVENT_ARTIFACT_VALID_FOR_TIMING"
        assert case_payload["usable_for_production_repair_decision"] is True
        assert case_payload["event_row"]["tnow"].strip().startswith("220.253999")
        assert case_payload["progress_tail"]

