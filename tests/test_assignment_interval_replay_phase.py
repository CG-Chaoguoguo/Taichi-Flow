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
    / "phase_dv_fvlimit_qq_assignment_interval_replay_and_repair_gate"
)


def test_assignment_interval_replay_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_assignment_interval_replay_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "assignment_interval_replay_plan.md",
        "fortran_dv_fvlimit_qq_lifecycle_trace.md",
        "original_assignment_interval_ledger.md",
        "current_assignment_interval_replay_report.md",
        "assignment_interval_delta_matrix.md",
        "dv_fvlimit_qq_variant_matrix.md",
        "face_predictor_repair_candidate_report.md",
        "repair_decision.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "next_round_handoff.md",
        "next_round_codex_prompt.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (PHASE / name).exists(), name


def test_assignment_history_replay_advances_to_dv_history_mismatch():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    delta = json.loads((PHASE / "assignment_interval_delta_matrix.json").read_text(encoding="utf-8"))

    assert "DV_UPDATE_HISTORY_MISMATCH" in summary
    assert delta["status"] == "DV_UPDATE_HISTORY_MISMATCH"
    assert delta["secondary_status"] == "FVLIMIT_CLAMP_HISTORY_MISMATCH"
    assert delta["next_blocker"] == "ASSIGNMENT_UPDATE_ACTIVATION_GATE_SOURCE_TRACE_REQUIRED"


def test_first_divergence_is_current_assignment_without_original_update():
    delta = json.loads((PHASE / "assignment_interval_delta_matrix.json").read_text(encoding="utf-8"))
    first = delta["rows"][0]

    assert first["classification"] == "DV_UPDATE_HISTORY_MISMATCH"
    assert first["original_has_assignment_update"] is False
    assert first["current_has_assignment_update"] is True
    assert first["current_fvpredi_after_clamp"] < 0.0
    assert first["current_clamp_status"] == 1


def test_clamp_mismatch_is_downstream_and_gate_stays_closed():
    delta = json.loads((PHASE / "assignment_interval_delta_matrix.json").read_text(encoding="utf-8"))
    variants = json.loads((PHASE / "dv_fvlimit_qq_variant_matrix.json").read_text(encoding="utf-8"))
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert any(row["classification"] == "FVLIMIT_CLAMP_HISTORY_MISMATCH" for row in delta["rows"])
    assert variants["status"] == "TARGETED_VARIANTS_AUDIT_ONLY"
    assert variants["production_eligible_variant_count"] == 0
    assert all(row["production_eligible"] == "no" for row in variants["rows"])
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
