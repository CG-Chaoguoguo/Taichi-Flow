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
    / "phase_assignment_skip_predicate_evidence_and_repair_gate"
)


def test_assignment_skip_predicate_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_assignment_skip_predicate_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "fortran_assignment_skip_predicate_trace.md",
        "original_assignment_skip_predicate_ledger.md",
        "current_assignment_skip_predicate_report.md",
        "assignment_skip_predicate_delta_matrix.md",
        "assignment_skip_predicate_variant_matrix.md",
        "assignment_skip_predicate_repair_candidate_report.md",
        "repair_decision.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "next_round_handoff.md",
        "next_round_codex_prompt.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (PHASE / name).exists(), name


def test_wet_dry_predicate_mismatch_is_classified():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    delta = json.loads((PHASE / "assignment_skip_predicate_delta_matrix.json").read_text(encoding="utf-8"))

    assert "WET_DRY_PREDICATE_MISMATCH" in summary
    assert delta["status"] == "WET_DRY_PREDICATE_MISMATCH"
    assert delta["secondary_status"] == "NEIGHBOR_DEPTH_THRESHOLD_CROSSING_AT_WET_DRY_GATE"
    assert delta["next_blocker"] == "UPSTREAM_NEIGHBOR_DEPTH_STATE_AT_WET_DRY_GATE_REQUIRED"


def test_original_skips_because_both_depths_are_below_tol_while_current_executes():
    delta = json.loads((PHASE / "assignment_skip_predicate_delta_matrix.json").read_text(encoding="utf-8"))
    first = delta["rows"][0]

    assert first["predicate"] == "wet_dry_pair_threshold"
    assert first["classification"] == "WET_DRY_PREDICATE_MISMATCH"
    assert first["original_skip_reason"] == "both_depths_le_tol"
    assert first["original_both_dry"] is True
    assert first["current_update_executed"] is True
    assert first["current_both_dry_if_original_tol"] is False
    assert first["current_neighbor_above_original_tol"] is True
    assert first["delta_neighbor_minus_tol"] > 0.0
    assert first["production_eligible"] == "no"


def test_qq_and_mapping_are_not_first_divergence():
    delta = json.loads((PHASE / "assignment_skip_predicate_delta_matrix.json").read_text(encoding="utf-8"))
    rows = {row["predicate"]: row for row in delta["rows"]}

    assert rows["qq_zero_or_prior_flux"]["classification"] == "NOT_FIRST_DIVERGENCE"
    assert rows["qq_zero_or_prior_flux"]["original_qq_before"] == 0.0
    assert rows["loop_index_neighbor_mapping"]["classification"] == "ALIGNED"
    assert rows["loop_index_neighbor_mapping"]["original_nq"] == rows["loop_index_neighbor_mapping"]["current_neighbor_cell"]
    assert rows["ybar_zero"]["classification"] == "DOWNSTREAM_NOT_REACHED_IN_ORIGINAL_SKIP_INTERVAL"


def test_variants_remain_audit_only_and_gate_closed():
    variants = json.loads((PHASE / "assignment_skip_predicate_variant_matrix.json").read_text(encoding="utf-8"))
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert variants["status"] == "TARGETED_VARIANTS_AUDIT_ONLY"
    assert variants["production_eligible_variant_count"] == 0
    assert all(row["audit_only"] == "yes" for row in variants["rows"])
    assert all(row["production_eligible"] == "no" for row in variants["rows"])
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
