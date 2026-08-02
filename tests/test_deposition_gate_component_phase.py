import csv
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_gate_fvdepo_component_matched_delta_and_targeted_variant"
)


def _read_one(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    return rows[0]


def test_deposition_gate_component_delta_classifies_threshold_mismatch():
    matrix = (PHASE / "deposition_gate_component_delta_matrix.md").read_text(encoding="utf-8")

    assert "GATE_ABSUBAR_FVDEPO_THRESHOLD_MISMATCH" in matrix
    for case_key in ("20a", "50a"):
        row = _read_one(PHASE / f"deposition_gate_component_delta_{case_key}.csv")
        assert row["cell_id"] == "35978"
        assert row["current_gate_cv_gt_cvlimit"] == "1"
        assert row["current_gate_absubar_lt_threshold"] == "0"
        assert float(row["current_absubar_over_threshold"]) > 1.0


def test_deposition_gate_component_reports_keep_repair_gate_closed():
    current_report = (PHASE / "current_deposition_gate_component_report.md").read_text(encoding="utf-8")
    variant_report = (PHASE / "deposition_gate_targeted_variant_matrix.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert "CURRENT_DEPOSITION_GATE_COMPONENT_DIAGNOSTICS_READY" in current_report
    assert "ABSUBAR_THRESHOLD_VARIANT_IDENTIFIES_REPAIR_CANDIDATE" in variant_report
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
