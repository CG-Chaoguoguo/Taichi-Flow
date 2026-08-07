from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_tau_component_original_artifact_and_state_mapping_repair"
)


def test_original_tau_component_probe_artifact_validates_formula_relationships():
    payload = json.loads((PHASE_DIR / "original_tau_component_artifact_validation.json").read_text(encoding="utf-8"))
    assert payload["aggregate_status"] == "ORIGINAL_TAU_COMPONENT_ARTIFACT_VALID"

    for case_key, case_payload in payload["cases"].items():
        assert case_key in {"20a", "50a"}
        assert case_payload["status"] == "ORIGINAL_TAU_COMPONENT_ARTIFACT_VALID"
        assert case_payload["tracked_cells"] == [36761, 36762, 36763, 37023]
        assert case_payload["tau_formula_max_residual"] < 1.0e-9
        assert case_payload["erorate_formula_max_residual"] < 1.0e-12


def test_original_tau_component_tables_include_first_event_and_neighbor_cells():
    for case_key in ("20a", "50a"):
        rows = list(csv.DictReader((PHASE_DIR / f"original_tau_component_state_table_{case_key}.csv").open(encoding="utf-8")))
        assert {int(row["cell_id"]) for row in rows} == {36761, 36762, 36763, 37023}

        positive = {int(row["cell_id"]) for row in rows if float(row["erorate"]) > 0.0}
        assert positive == {36762, 37023}

        for row in rows:
            tau = float(row["tau"])
            reconstructed_tau = (
                float(row["sfy"]) + float(row["sfmiu"]) + float(row["sfmanning"])
            ) * float(row["gammadeb"]) * float(row["fhpredi1"])
            assert abs(tau - reconstructed_tau) < 1.0e-8
