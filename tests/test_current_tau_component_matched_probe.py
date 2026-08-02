from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_tau_component_original_artifact_and_state_mapping_repair"
)


def test_current_tau_component_probe_exports_native_and_original_cell_sets():
    expected_native = {
        "20a": {36761, 36762, 37023},
        "50a": {36761, 36762, 36763, 37023},
    }

    for case_key, expected_cells in expected_native.items():
        payload = json.loads((PHASE_DIR / f"current_tau_component_state_table_{case_key}.json").read_text(encoding="utf-8"))
        cells = {int(row["cell_id"]) for row in payload["rows"]}
        assert cells == expected_cells

        matched = json.loads(
            (PHASE_DIR / f"current_original_cell_matched_tau_components_{case_key}.json").read_text(encoding="utf-8")
        )
        assert {int(row["cell_id"]) for row in matched["rows"]} == {36762, 37023}


def test_current_tau_component_rows_include_required_diagnostic_terms():
    required = {
        "cv",
        "cvbar",
        "fhpredi1",
        "frhopredi1",
        "gammadeb",
        "manningbar",
        "miudebris",
        "coemiu",
        "coemanning",
        "sfy",
        "sfmiu",
        "sfmanning",
        "absubar",
        "tau",
        "taoc",
        "tau_minus_taoc",
        "erorate",
    }

    for case_key in ("20a", "50a"):
        with (PHASE_DIR / f"current_tau_component_state_table_{case_key}.csv").open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert required <= set(reader.fieldnames or [])
            rows = list(reader)
        assert rows
        assert all(float(row["absubar"]) > 0.0 for row in rows)
