from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_rate_magnitude_state_mapping_fortran_repair"
)


def test_current_erosion_event_probe_captures_first_gate_erorate_and_export_events():
    for case_key in ("20a", "50a"):
        payload = json.loads((PHASE_DIR / f"current_erosion_event_probe_{case_key}.json").read_text(encoding="utf-8"))
        assert payload["status"] == "event_found"
        assert payload["accepted_steps_scanned"] > 0

        first_gate = payload["events"]["first_all_erosion_gates_true"]
        first_erorate = payload["events"]["first_erorate_gt_0"]
        first_export = payload["events"]["first_exported_fortran_erosion"]
        assert first_gate["tnow"] == first_erorate["tnow"]
        assert first_erorate["erorate_raw_sum"] > 0.0
        assert first_export["tnow"] > first_erorate["tnow"]
        assert first_export["erosion_output_fortran_positive_cells"] > 0
        assert payload["tracked_cell_ids_requested"] == [36762, 37023]
        assert {cell["cell_id"] for cell in first_erorate["tracked_cells"]} == {36762, 37023}

        rows = list(csv.DictReader((PHASE_DIR / f"current_erosion_event_probe_{case_key}.csv").open(encoding="utf-8")))
        assert rows
        assert {row["event_kind"] for row in rows} >= {
            "first_all_erosion_gates_true",
            "first_erorate_gt_0",
            "first_exported_fortran_erosion",
        }

