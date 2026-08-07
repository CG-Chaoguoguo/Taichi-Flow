import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_deposition_internal_variants_are_not_production_eligible_without_artifact():
    for name in (
        "deposition_gate_variant_matrix",
        "deporate_rhodepo_variant_matrix",
        "flow_cv_deposition_coupling_variant_matrix",
        "extra_neighbor_deposition_variant_matrix",
    ):
        rows = json.loads((PHASE / f"{name}.json").read_text(encoding="utf-8"))
        assert rows
        assert all(row["production_eligible"] is False for row in rows)

    report = (PHASE / "deposition_variant_original_constraint_report.md").read_text(encoding="utf-8")
    assert "VARIANTS_REJECTED_NEXT_FLOW_RESPONSE_OR_INTERNAL_ARTIFACT" in report
