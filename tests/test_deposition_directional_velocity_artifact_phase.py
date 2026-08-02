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
    / "phase_deposition_absubar_directional_velocity_artifact_repair"
)


def test_deposition_directional_velocity_artifact_phase_reports() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tests" / "comparison" / "generate_deposition_directional_velocity_artifact_reports.py"),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    validation = json.loads(
        (PHASE_DIR / "original_deposition_directional_velocity_validation.json").read_text(encoding="utf-8")
    )
    delta = json.loads((PHASE_DIR / "deposition_directional_velocity_delta_matrix.json").read_text(encoding="utf-8"))
    repair_decision = (PHASE_DIR / "repair_decision.md").read_text(encoding="utf-8")

    assert validation["status"] == "VALID_DIRECTIONAL_VELOCITY"
    assert delta["status"] == "DEPOSITION_ABSUBAR_VELOCITY_LIFECYCLE_MISMATCH"
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in repair_decision
    assert all(row["direction_selection_matches"] == 1 for row in delta["rows"])
    assert all(row["current_absubar_over_threshold"] > 1.0 for row in delta["rows"])
