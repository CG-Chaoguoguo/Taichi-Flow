import csv
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_absubar_reconstruction_and_deporate_formula_split_repair"
)


def _ensure_reports() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO / "tests" / "comparison" / "generate_deposition_absubar_reconstruction_and_deporate_split_reports.py"),
        ],
        cwd=REPO,
        check=True,
    )


def test_absubar_reconstruction_reports_no_current_lifecycle_match():
    _ensure_reports()

    summary = json.loads((PHASE / "absubar_reconstruction_ledger_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "ABSUBAR_RECONSTRUCTION_NO_CURRENT_STATE_MATCH"
    assert {row["case"] for row in summary["rows"]} == {"20a", "50a"}
    assert all(row["classification"] == "NO_CURRENT_LIFECYCLE_MATCHES_ORIGINAL_ABSUBAR" for row in summary["rows"])

    for case in ("20a", "50a"):
        with (PHASE / f"absubar_reconstruction_ledger_{case}.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert any(row["candidate"] == "active_branch_source_time" and float(row["absubar_ratio_to_original"]) > 1 for row in rows)
        assert any(row["candidate"] == "original_selected_magnitude_audit" and row["production_eligibility"] == "not_allowed_artifact_substitution" for row in rows)


def test_deporate_split_reports_reject_coefficient_inference():
    _ensure_reports()

    summary = json.loads((PHASE / "deporate_formula_ledger_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "DEPORATE_RAW_FORMULA_MISMATCH_AFTER_GATE_AUDIT"
    assert all(row["classification"] == "DEPORATE_RAW_FORMULA_MISMATCH" for row in summary["rows"])
    assert all(row["inferred_coedepo_production_eligibility"] == "not_allowed_coefficient_inference" for row in summary["rows"])

    matrix = (PHASE / "double_ledger_variant_matrix.md").read_text(encoding="utf-8")
    assert "not_allowed_coefficient_inference" in matrix
    assert "not_allowed_artifact_substitution" in matrix


def test_repair_gate_remains_closed_for_double_ledger_phase():
    _ensure_reports()

    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "No production solver formula was modified." in decision
