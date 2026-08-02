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
    / "phase_deposition_absubar_velocity_lifecycle_repair"
)


def test_deposition_velocity_lifecycle_repair_phase_reports() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tests" / "comparison" / "generate_deposition_velocity_lifecycle_repair_reports.py"),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    delta = json.loads((PHASE_DIR / "deposition_velocity_lifecycle_delta_matrix.json").read_text(encoding="utf-8"))
    variants = json.loads((PHASE_DIR / "deposition_velocity_lifecycle_variant_matrix.json").read_text(encoding="utf-8"))
    repair_decision = (PHASE_DIR / "repair_decision.md").read_text(encoding="utf-8")

    assert delta["status"] == "NO_CURRENT_LIFECYCLE_MATCHES_ORIGINAL_NEXT_DEPORATE_FORMULA"
    assert variants["status"] == "NO_LIFECYCLE_VARIANT_MATCHES_ORIGINAL"
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in repair_decision
    assert all(row["active_branch_ratio"] > 1.0 for row in delta["rows"])
    assert all(row["accepted_snapshot_ratio"] < 0.2 for row in delta["rows"])
