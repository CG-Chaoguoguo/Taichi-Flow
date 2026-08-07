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
    / "phase_mirrored_d2_dv_update_history_repair_gate"
)


def test_mirrored_direction_predictor_history_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_mirrored_d2_dv_update_history_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "d6_d2_predictor_history_plan.md",
        "fortran_mirrored_direction_lifecycle_trace.md",
        "current_d6_d2_predictor_history_report.md",
        "d6_d2_predictor_history_delta_matrix.md",
        "dv_fvlimit_history_delta_matrix.md",
        "qq_qqmass_history_delta_matrix.md",
        "mirrored_direction_variant_matrix.md",
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


def test_current_history_contains_d6_and_mirrored_d2_rows():
    report = (PHASE / "current_d6_d2_predictor_history_report.md").read_text(encoding="utf-8")

    assert "source_entry_actual_face_state" in report
    assert "source_entry_mirrored_opposite_face_state" in report
    assert "assignment_mirrored_opposite_face_state" in report
    assert "state 257 D6" in report
    assert "state 258 D6" in report


def test_mirror_mismatch_is_not_supported_by_captured_rows():
    payload = json.loads((PHASE / "d6_d2_predictor_history_delta_matrix.json").read_text(encoding="utf-8"))

    assert payload["status"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["secondary_status"] == "D6_D2_MIRROR_ASSIGNMENT_ORDER_ALIGNED"
    assert payload["next_blocker"] == "DV_FVLIMIT_QQ_HISTORY_REQUIRES_ASSIGNMENT_INTERVAL_REPLAY"
    assert all(abs(row["d6_plus_d2"]) < 1e-12 for row in payload["rows"] if row["d6_plus_d2"] is not None)
    assert all("MISMATCH" not in row["classification"] for row in payload["rows"])


def test_variants_and_repair_gate_remain_closed():
    variants = json.loads((PHASE / "mirrored_direction_variant_matrix.json").read_text(encoding="utf-8"))
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    dv = json.loads((PHASE / "dv_fvlimit_history_delta_matrix.json").read_text(encoding="utf-8"))
    qq = json.loads((PHASE / "qq_qqmass_history_delta_matrix.json").read_text(encoding="utf-8"))

    assert variants["status"] == "MIRRORED_DIRECTION_VARIANTS_AUDIT_ONLY"
    assert variants["production_eligible_variant_count"] == 0
    assert all(row["production_eligible"] == "no" for row in variants["rows"])
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert any("SPLIT_TAIL_CONSTRAINS" in row["classification"] for row in dv["rows"])
    assert any("SPLIT_TAIL_CONSTRAINS" in row["classification"] for row in qq["rows"])
