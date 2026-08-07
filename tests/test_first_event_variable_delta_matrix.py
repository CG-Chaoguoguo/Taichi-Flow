from __future__ import annotations

import csv
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_rate_magnitude_state_mapping_fortran_repair"
)


def test_first_event_variable_delta_localizes_tau_minus_taoc_mismatch():
    report = PHASE_DIR / "first_event_variable_delta_matrix.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "TAU_MINUS_TAOC_MAGNITUDE_MISMATCH" in text

    for case_key in ("20a", "50a"):
        rows = list(csv.DictReader((PHASE_DIR / f"first_event_variable_delta_{case_key}.csv").open(encoding="utf-8")))
        assert {int(row["cell_id"]) for row in rows} == {36762, 37023}
        for row in rows:
            assert float(row["tau_minus_taoc_ratio"]) > 3.0
            assert abs(float(row["fhpredi1_delta"])) < 1.0e-5
            assert abs(float(row["cv_delta"])) < 1.0e-4
            assert abs(float(row["current_kero"]) - float(row["original_kero_inferred"])) < 1.0e-12


def test_current_original_cell_matched_tables_include_original_event_cells():
    for case_key in ("20a", "50a"):
        rows = list(
            csv.DictReader((PHASE_DIR / f"current_original_cell_matched_state_table_{case_key}.csv").open(encoding="utf-8"))
        )
        assert {int(row["cell_id"]) for row in rows} == {36762, 37023}
        assert all(row["all_erosion_gate_active"] == "True" for row in rows)
