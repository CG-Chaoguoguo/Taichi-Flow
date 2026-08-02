import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"
DEPOSITION_PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def _assert_dashboard(phase: Path):
    dashboard = (phase / "original_current_result_comparison_dashboard.md").read_text(encoding="utf-8")
    assert "Original / Current Result Comparison Dashboard" in dashboard
    assert "current_before" in dashboard
    assert "current_after" in dashboard

    for family in ("Flow_depth", "Volumetric_sediment", "Deposit_depth", "Erosion_depth"):
        report = phase / f"comparison_{family}.md"
        assert report.exists()
        text = report.read_text(encoding="utf-8")
        assert "current_before_sum" in text
        assert "current_after_sum" in text


def test_original_current_dashboard_and_family_reports_exist():
    _assert_dashboard(PHASE)
    _assert_dashboard(DEPOSITION_PHASE)


def test_dashboard_machine_readable_metrics_are_present():
    family_payload = json.loads((PHASE / "comparison_metrics_by_family.json").read_text(encoding="utf-8"))
    spatial_payload = json.loads((PHASE / "spatial_difference_summary.json").read_text(encoding="utf-8"))

    assert set(family_payload) >= {"Flow_depth", "Volumetric_sediment", "Deposit_depth", "Erosion_depth"}
    assert set(spatial_payload) >= {"Flow_depth", "Volumetric_sediment", "Deposit_depth", "Erosion_depth"}

    with (PHASE / "comparison_metrics_by_checkpoint.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert {
            "checkpoint",
            "case",
            "original_sum",
            "current_before_sum",
            "current_after_sum",
            "before_abs_error",
            "after_abs_error",
            "improvement",
            "original_positive_cells",
            "current_after_positive_cells",
        } <= set(reader.fieldnames or [])
        rows = list(reader)
    assert rows


def test_dashboard_figure_manifest_exists_even_if_png_generation_is_optional():
    manifest = json.loads((PHASE / "comparison_figure_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) >= {"Flow_depth", "Volumetric_sediment", "Deposit_depth", "Erosion_depth"}
    # When matplotlib is available this contains PNG paths; otherwise the report
    # still has JSON/CSV summaries. The current CI environment has matplotlib.
    assert any(str(item).endswith(".png") for values in manifest.values() for item in values)
