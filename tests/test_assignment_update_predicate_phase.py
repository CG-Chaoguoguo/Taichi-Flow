from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_assignment_update_presence_predicate_repair_gate"
)


def test_assignment_update_predicate_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_assignment_update_predicate_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "assignment_update_presence_plan.md",
        "fortran_assignment_update_predicate_trace.md",
        "original_assignment_update_presence_ledger.md",
        "current_assignment_update_presence_report.md",
        "assignment_update_predicate_delta_matrix.md",
        "assignment_update_predicate_variant_matrix.md",
        "assignment_update_repair_candidate_report.md",
        "repair_decision.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "next_round_handoff.md",
        "next_round_codex_prompt.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (PHASE / name).exists(), name


def test_assignment_update_presence_mismatch_is_classified():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    delta = json.loads((PHASE / "assignment_update_predicate_delta_matrix.json").read_text(encoding="utf-8"))

    assert "ASSIGNMENT_UPDATE_PRESENCE_MISMATCH" in summary
    assert delta["status"] == "ASSIGNMENT_UPDATE_PRESENCE_MISMATCH"
    assert delta["secondary_status"] == "ORIGINAL_ASSIGNMENT_SKIP_PREDICATE_FIELDS_REQUIRED"
    assert delta["next_blocker"] == "ORIGINAL_ASSIGNMENT_SKIP_PREDICATE_ROW_REQUIRED"


def test_first_interval_original_absent_current_present():
    delta = json.loads((PHASE / "assignment_update_predicate_delta_matrix.json").read_text(encoding="utf-8"))
    first = delta["rows"][0]

    assert first["classification"] == "ASSIGNMENT_UPDATE_PRESENCE_MISMATCH"
    assert first["original_assignment_update_row_present"] is False
    assert first["current_assignment_update_executed"] is True
    assert first["neighbor_mapping_aligned"] is True
    assert first["current_gate_blocks_face"] == 0
    assert first["current_face_depth_positive"] is True
    assert first["first_actionable_gap"] == "instrument_original_skip_predicate_at_same_loop_site"


def test_predicate_variants_are_audit_only_until_original_skip_row_exists():
    variants = json.loads((PHASE / "assignment_update_predicate_variant_matrix.json").read_text(encoding="utf-8"))
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert variants["status"] == "TARGETED_VARIANTS_AUDIT_ONLY"
    assert variants["production_eligible_variant_count"] == 0
    assert all(row["production_eligible"] == "no" for row in variants["rows"])
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
