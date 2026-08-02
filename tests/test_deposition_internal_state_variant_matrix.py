import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_deposition_internal_variants_require_original_artifact():
    variants = json.loads((PHASE / "deposition_internal_state_variant_matrix.json").read_text(encoding="utf-8"))

    assert variants
    assert all(row["production_eligible"] is False for row in variants)
    assert any(row["support_status"] == "requires_original_artifact" for row in variants)
    assert any(row["variant"] == "tempdebdepothick_writer_candidate" and row["support_status"] == "rejected_by_source" for row in variants)
