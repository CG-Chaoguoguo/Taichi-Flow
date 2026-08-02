import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_paired_after_sediment_output_repair_improves_volumetric_rmse():
    summary = json.loads((PHASE / "sediment_phase_summary.json").read_text(encoding="utf-8"))
    previous = summary["previous_delta_of_delta_rmse"]
    current = summary["current_delta_of_delta_rmse"]

    assert current["Volumetric_sediment"] < previous["Volumetric_sediment"]
    assert current["Volumetric_sediment"] < 0.106817
    assert current["Flow_depth"] <= previous["Flow_depth"]
    assert current["Deposit_depth"] <= previous["Deposit_depth"]
    assert current["Erosion_depth"] <= previous["Erosion_depth"]


def test_output_reexport_manifest_marks_validation_as_output_only():
    payload = json.loads((PHASE / "volumetric_sediment_output_reexport_summary.json").read_text(encoding="utf-8"))
    for case_payload in payload["cases"].values():
        marker = case_payload["run_summary"]["volumetric_sediment_output_reexport"]
        assert marker["fresh_solver_rerun"] is False
        assert marker["repair_kind"] == "output_only_fortran_writer_mask"
        assert marker["files_rewritten"] > 0
