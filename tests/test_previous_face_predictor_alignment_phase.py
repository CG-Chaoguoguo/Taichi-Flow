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
    / "phase_previous_face_predictor_alignment_and_momentum_repair_gate"
)


def test_previous_face_predictor_alignment_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_previous_face_predictor_alignment_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "current_split_step_alignment_report.md",
        "accepted_step_matching_report.md",
        "fortran_previous_face_predictor_lifecycle_trace.md",
        "momentum_term_delta_refined_matrix.md",
        "previous_face_predictor_variant_matrix.md",
        "momentum_term_repair_candidate_report.md",
        "repair_decision.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "next_round_handoff.md",
        "next_round_codex_prompt.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (PHASE / name).exists(), name


def test_previous_predictor_mismatch_is_confirmed_but_gate_stays_closed():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert "PREVIOUS_FACE_PREDICTOR_MISMATCH_CONFIRMED" in summary
    assert "current/original" in summary
    assert "6.34211851179x" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision


def test_accepted_step_matching_reports_missing_lifecycle_fields():
    matching = (PHASE / "accepted_step_matching_report.md").read_text(encoding="utf-8")

    assert "`accepted_step_id` | `present`" in matching
    assert "`candidate_step_id` | `present`" in matching
    assert "`retry_attempt_id` | `present`" in matching
    assert "`rejected_step_status` | `present`" in matching
    assert "previous_predictor_carryover_state_id=257" in matching
    assert "CURRENT_SPLIT_STEP_LIMITS_PRODUCTION_REPAIR" in matching


def test_refined_delta_and_variant_remain_audit_only():
    delta = json.loads((PHASE / "momentum_term_delta_refined_matrix.json").read_text(encoding="utf-8"))
    variant = json.loads((PHASE / "previous_face_predictor_variant_matrix.json").read_text(encoding="utf-8"))

    assert delta["status"] == "PREVIOUS_FACE_PREDICTOR_MISMATCH_CONFIRMED"
    predictor = next(
        row
        for row in delta["rows"]
        if row["term"] == "source_entry_previous_face_predictor_component_boundary_interval"
    )
    same_start = next(
        row
        for row in delta["rows"]
        if row["term"] == "source_entry_previous_face_predictor_component_same_start"
    )
    assert predictor["classification"] == "PREVIOUS_FACE_PREDICTOR_MISMATCH_CONFIRMED"
    assert abs(predictor["current_over_original"] - 6.34211851179) < 1e-6
    assert same_start["classification"] == "PREVIOUS_FACE_PREDICTOR_MISMATCH_CONFIRMED"
    assert same_start["current_over_original"] > 3.0

    assert variant["status"] == "PREVIOUS_FACE_PREDICTOR_VARIANTS_AUDIT_ONLY"
    assert variant["production_eligible_variant_count"] == 0
    assert all(row["production_eligible"] == "no" for row in variant["rows"])
