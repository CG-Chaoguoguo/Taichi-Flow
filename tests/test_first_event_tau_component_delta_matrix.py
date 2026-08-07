from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_tau_component_original_artifact_and_state_mapping_repair"
)


def test_tau_component_delta_matrix_localizes_absubar_state_mismatch():
    payload = json.loads((PHASE_DIR / "first_event_tau_component_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["rows"]
    assert {row["classification"] for row in payload["rows"]} == {"FIRST_EVENT_ABSUBAR_STATE_MISMATCH"}

    for row in payload["rows"]:
        assert abs(float(row["absubar_ratio"]) - 2.0) < 1.0e-12
        assert 1.9 < float(row["sfmiu_tau_ratio"]) < 2.1
        assert 3.9 < float(row["sfmanning_tau_ratio"]) < 4.1
        assert float(row["tau_minus_taoc_ratio"]) > 3.0
        assert abs(float(row["erorate_ratio"]) - float(row["tau_minus_taoc_ratio"])) < 1.0e-12


def test_tau_component_delta_csv_keeps_original_event_cells_only():
    for case_key in ("20a", "50a"):
        rows = list(csv.DictReader((PHASE_DIR / f"first_event_tau_component_delta_{case_key}.csv").open(encoding="utf-8")))
        assert {int(row["cell_id"]) for row in rows} == {36762, 37023}
