from __future__ import annotations

import json

from api.services.runtime_audit import build_output_manifest


def test_output_manifest_binds_grid_to_solver_recorded_physical_time_and_content_hash(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "Flow_depth_Taichi_90.0.txt").write_text("grid payload\n", encoding="utf-8")
    (output / "output_frame_events.json").write_text(
        json.dumps(
            {
                "schema_version": "fix3-output-frame-events-v1",
                "events": [
                    {
                        "event_index": 0,
                        "time_s": "89.99999999999999",
                        "writer": "taichi_edda_text",
                        "relative_paths": ["Flow_depth_Taichi_90.0.txt"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = build_output_manifest(output)

    entry = manifest["result_files"][0]
    assert entry["relative_path"] == "Flow_depth_Taichi_90.0.txt"
    assert entry["frame_time_s"] == "89.99999999999999"
    assert len(entry["sha256"]) == 64
    assert manifest["frame_event_evidence"]["status"] == "present"
    assert manifest["frame_event_evidence"]["declared_paths_missing_from_output"] == []


def test_output_manifest_marks_ambiguous_frame_events_invalid(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "output_frame_events.json").write_text(
        json.dumps(
            {
                "schema_version": "fix3-output-frame-events-v1",
                "events": [
                    {"time_s": "1", "relative_paths": ["Flow_depth_Taichi_1.0.txt"]},
                    {"time_s": "2", "relative_paths": ["Flow_depth_Taichi_1.0.txt"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = build_output_manifest(output)

    evidence = manifest["frame_event_evidence"]
    assert evidence["status"] == "invalid"
    assert "duplicate output path" in evidence["errors"][0]
