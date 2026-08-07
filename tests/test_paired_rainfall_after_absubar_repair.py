import json
from pathlib import Path


PHASE = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_absubar_velocity_state_mapping_source_repair_and_full_paired_validation"
)


def test_full_paired_after_absubar_repair_improves_erosion_rmse():
    summary = json.loads((PHASE / "absubar_velocity_state_phase_summary.json").read_text(encoding="utf-8"))
    rmse = summary["delta_of_delta_rmse"]
    assert rmse["Erosion_depth"] < 0.0681378
    assert rmse["Flow_depth"] < 0.0515026
    assert rmse["Deposit_depth"] < 0.105191
    assert (PHASE / "_current_runs" / "20a_cuda" / "run_summary.json").exists()
    assert (PHASE / "_current_runs" / "50a_cuda" / "run_summary.json").exists()

