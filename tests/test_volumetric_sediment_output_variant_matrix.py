import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_volumetric_sediment_variant_identifies_source_supported_mask():
    variants = json.loads((PHASE / "volumetric_sediment_output_variant_matrix.json").read_text(encoding="utf-8"))
    by_name = {row["variant"]: row for row in variants}

    source_variant = by_name["fortran_fh_lt_0p005_writer_mask"]
    baseline = by_name["active_previous_current_output"]
    post = by_name["post_repair_output"]

    assert source_variant["support_status"] == "source_supported"
    assert source_variant["production_eligible"] is True
    assert source_variant["mean_rmse"] < baseline["mean_rmse"] * 0.25
    assert post["mean_rmse"] == source_variant["mean_rmse"]


def test_checkpoint_timeline_records_positive_cell_collapse():
    summary = json.loads((PHASE / "sediment_phase_summary.json").read_text(encoding="utf-8"))
    for case_payload in summary["variant_summary"]["cases"].values():
        final = case_payload["final"]
        assert final["post_repair_positive_cells"] < final["previous_positive_cells"] * 0.1
        assert final["post_repair_rmse"] < final["previous_rmse"] * 0.2
