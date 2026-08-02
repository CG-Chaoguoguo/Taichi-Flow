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
    / "phase_deposition_velocity_update_and_deporate_formula_source_repair"
)


def _ensure_reports() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO / "tests" / "comparison" / "generate_deposition_velocity_update_and_deporate_source_reports.py"),
        ],
        cwd=REPO,
        check=True,
    )


def test_velocity_update_order_delta_requires_intermediate_state_capture():
    _ensure_reports()

    payload = json.loads((PHASE / "velocity_update_order_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "CURRENT_LACKS_REQUIRED_INTERMEDIATE_VELOCITY_STATE"
    assert {row["case"] for row in payload["rows"]} == {"20a", "50a"}
    for row in payload["rows"]:
        assert row["classification"] == "CURRENT_LACKS_REQUIRED_INTERMEDIATE_VELOCITY_STATE"
        assert row["pre_branch_snapshot_available"] == "no"
        assert float(row["current_branch_ratio_to_original"]) > 1.0
        assert float(row["current_accepted_snapshot_ratio"]) < 1.0


def test_deporate_formula_delta_rejects_inferred_coefficient_repair():
    _ensure_reports()

    payload = json.loads((PHASE / "deporate_formula_term_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "DEPORATE_NORMAL_PATH_FORMULA_MISMATCH_AUDIT_ONLY"
    for row in payload["rows"]:
        assert row["classification"] == "DEPORATE_NORMAL_PATH_FORMULA_MISMATCH"
        assert row["coedepo_mapping_status"] == "SOURCE_ALIGNED"
        assert float(row["original_source_coedepo"]) == 0.005
        assert float(row["current_coedepo"]) == 0.005
        assert row["production_eligibility"] == "no_inferred_coefficient_forbidden_and_formula_point_needs_enrichment"


def test_repair_gate_stays_closed_for_velocity_deporate_phase():
    _ensure_reports()

    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "No production solver formula was modified." in decision

    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")
    assert "Add current diagnostics-only fields for deposition velocity lifecycle phase markers" in handoff
    assert "without inferred coefficient" in handoff
