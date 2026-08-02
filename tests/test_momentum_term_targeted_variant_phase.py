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
    / "phase_momentum_term_delta_targeted_variant_and_repair_gate"
)


def test_momentum_term_targeted_variant_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_momentum_term_delta_targeted_variant_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "current_split_step_alignment_report.md",
        "fortran_momentum_term_source_trace.md",
        "momentum_term_delta_refined_matrix.md",
        "momentum_term_targeted_variant_matrix.md",
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


def test_split_step_alignment_keeps_production_gate_closed():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    alignment = (PHASE / "current_split_step_alignment_report.md").read_text(encoding="utf-8")

    assert "CURRENT_SPLIT_STEP_LIMITS_PRODUCTION_REPAIR" in summary
    assert "PREVIOUS_FACE_PREDICTOR_MISMATCH" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "split accepted step" in alignment


def test_refined_delta_identifies_previous_predictor_as_first_aligned_mismatch():
    payload = json.loads((PHASE / "momentum_term_delta_refined_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "CURRENT_SPLIT_STEP_LIMITS_PRODUCTION_REPAIR"
    assert payload["secondary_classification"] == "PREVIOUS_FACE_PREDICTOR_MISMATCH"

    rows = {row["term"]: row for row in payload["rows"]}
    predictor = rows["source_entry_previous_face_predictor_component"]
    assert predictor["alignment_status"] == "aligned_source_entry_interval"
    assert predictor["production_relevance"] == "first_significant_mismatch"
    assert abs(predictor["ratio_current_over_original"] - 6.34211851179) < 1e-6


def test_variants_are_audit_only_until_lifecycle_replay_exists():
    payload = json.loads((PHASE / "momentum_term_targeted_variant_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "TARGETED_VARIANTS_AUDIT_ONLY"
    assert payload["production_eligible_variant_count"] == 0
    assert all(row["production_eligible"] == "no" for row in payload["rows"])
    names = {row["variant"] for row in payload["rows"]}
    assert "previous_face_predictor_lifecycle_match_original_component" in names
    assert "sfmanning_match_original_assignment_term" in names
    assert "artivis_match_original_assignment_term" in names
