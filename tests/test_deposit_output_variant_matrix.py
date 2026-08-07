import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_deposit_output_variants_reject_new_writer_patch():
    variants = json.loads((PHASE / "deposit_output_variant_matrix.json").read_text(encoding="utf-8"))
    by_name = {row["variant"]: row for row in variants}

    assert by_name["bed_elevation_delta_max_ele_minus_eleori_0"]["support_status"] == "source_supported"
    assert by_name["bed_elevation_delta_max_ele_minus_eleori_0"]["production_eligible"] is False
    assert by_name["positive_threshold_lt_0p001"]["support_status"] == "audit_only"
    assert by_name["gindx_mask"]["support_status"] == "audit_only"


def test_deposit_output_matrix_report_exists():
    report = (PHASE / "deposit_output_variant_matrix.md").read_text(encoding="utf-8")
    assert "Deposit Output Variant Matrix" in report
    assert "already implemented" in report
