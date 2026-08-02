from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = (
    REPO_ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_single_step_deposition_ledger_cell35978_fortran_repair"
)


def test_single_step_deposition_ledger_phase_reports() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tests" / "comparison" / "generate_single_step_deposition_ledger_reports.py"),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    summary = json.loads((PHASE_DIR / "single_step_deposition_ledger_summary.json").read_text(encoding="utf-8"))
    variants = json.loads((PHASE_DIR / "single_step_deposition_ledger_variant_matrix.json").read_text(encoding="utf-8"))
    repair_decision = (PHASE_DIR / "repair_decision.md").read_text(encoding="utf-8")

    assert summary["status"] == "LEDGER_FIRST_DIVERGENCE_ABSUBAR_STATE"
    assert variants["status"] == "LEDGER_VARIANTS_AUDIT_ONLY_NO_REPAIR"
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in repair_decision
    assert all(row["first_divergence_component"] == "absubar" for row in summary["rows"])
    assert any(row["production_eligibility"] == "not_allowed_coefficient_inference" for row in variants["rows"])
