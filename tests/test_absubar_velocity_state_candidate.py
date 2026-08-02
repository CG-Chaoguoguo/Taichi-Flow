import json
from pathlib import Path


PHASE = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_absubar_velocity_state_mapping_source_repair_and_full_paired_validation"
)


def test_absubar_candidate_matches_original_first_event_overlap_cells():
    summary = json.loads((PHASE / "absubar_velocity_state_phase_summary.json").read_text(encoding="utf-8"))
    for case_key, rows in summary["first_event_rows"].items():
        overlap_rows = [row for row in rows if row["is_original_event_cell"]]
        assert overlap_rows, case_key
        for row in overlap_rows:
            assert row["absubar_active_source"] == "fortran_preflux_fvpredi2_half_accepted"
            assert abs(float(row["absubar_ratio"]) - 1.0) < 1e-9
            assert abs(float(row["erorate_ratio"]) - 1.0) < 5e-4

