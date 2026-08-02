import csv
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_component_multiagent_matched_evidence_loop"
)


def test_full_component_delta_advances_to_absubar_too_high():
    matrix = (PHASE / "full_deposition_component_delta_matrix.md").read_text(encoding="utf-8")

    assert "Status: `ABSUBAR_TOO_HIGH`" in matrix
    for case_key in ("20a", "50a"):
        with (PHASE / f"full_deposition_component_delta_{case_key}.csv").open(encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        assert row["cell_id"] == "35978"
        assert float(row["absubar_ratio"]) > 1.0
        assert float(row["fvdepo_ratio"]) >= 1.0
        assert row["current_gate_cv_gt_cvlimit"] == "1"
        assert row["current_gate_absubar_lt_threshold"] == "0"
        assert row["classification"] == "ABSUBAR_TOO_HIGH"


def test_targeted_variants_remain_audit_only_and_gate_closed_for_production():
    variants = (PHASE / "deposition_component_targeted_variant_matrix.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert "ABSUBAR_VARIANT_OPENS_GATE_BUT_NOT_PRODUCTION_ELIGIBLE" in variants
    assert "use_original_absubar" in variants
    assert "artifact_constraint_only" in variants
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
