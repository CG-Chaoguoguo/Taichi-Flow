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
    / "phase_original_accepted_step_metadata_and_preceding_predictor_replay"
)


def test_original_accepted_step_replay_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_original_accepted_step_metadata_and_preceding_predictor_replay_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "accepted_step_lifecycle_plan.md",
        "original_accepted_step_metadata_report.md",
        "current_preceding_history_replay_report.md",
        "accepted_step_lifecycle_delta_matrix.md",
        "previous_face_predictor_lifecycle_variant_matrix.md",
        "previous_face_predictor_repair_candidate_report.md",
        "repair_decision.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "next_round_handoff.md",
        "next_round_codex_prompt.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (PHASE / name).exists(), name


def test_lifecycle_alignment_and_rejected_leakage_are_classified():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert "ACCEPTED_STEP_LIFECYCLE_ALIGNED" in summary
    assert "SOURCE_ENTRY_FACE_PREDICTOR_MISMATCH" in summary
    assert "rejected_step_status=0" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "rejected-step leakage | rejected" in decision


def test_preceding_history_delta_contains_states_257_and_258():
    delta = json.loads((PHASE / "accepted_step_lifecycle_delta_matrix.json").read_text(encoding="utf-8"))

    assert delta["status"] == "ACCEPTED_STEP_LIFECYCLE_ALIGNED"
    rows = delta["rows"]
    state257 = next(row for row in rows if row["term"] == "previous_face_predictor_d6" and row["current_accepted_step_id"] == 257)
    state258 = next(row for row in rows if row["term"] == "previous_face_predictor_d6" and row["current_accepted_step_id"] == 258)

    assert state257["current_rejected_step_status"] == 0
    assert state258["current_rejected_step_status"] == 0
    assert state257["current_over_original"] > 6.0
    assert state258["current_over_original"] > 3.0


def test_variants_remain_audit_only_and_next_loop_targets_mirror_or_dv():
    variant = json.loads((PHASE / "previous_face_predictor_lifecycle_variant_matrix.json").read_text(encoding="utf-8"))
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")

    assert variant["status"] == "PREVIOUS_FACE_PREDICTOR_VARIANTS_AUDIT_ONLY"
    assert all(row["production_eligible"] == "no" for row in variant["rows"])
    assert "MIRRORED_D2_OR_DV_UPDATE_HISTORY_REQUIRED" in handoff
