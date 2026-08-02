import json
from pathlib import Path


PHASE = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_absubar_velocity_state_mapping_source_repair_and_full_paired_validation"
)


def test_first_event_after_absubar_repair_keeps_timing_and_flags():
    for case_key in ("20a", "50a"):
        payload = json.loads((PHASE / f"current_erosion_event_probe_{case_key}.json").read_text(encoding="utf-8"))
        assert payload["use_fortran_absubar_velocity_state"] is True
        event = payload["events"]["first_erorate_gt_0"]
        assert abs(float(event["tnow"]) - 220.254) < 1e-3
        sources = {cell.get("absubar_active_source") for cell in event["cells"]}
        assert sources == {"fortran_preflux_fvpredi2_half_accepted"}

