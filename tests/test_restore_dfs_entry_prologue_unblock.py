from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_restore_dfs_entry_prologue_unblock_and_assignment_artifact"
)


def test_restore_dfs_entry_prologue_unblock_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_restore_dfs_entry_prologue_unblock_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "loop_state_summary.md",
        "dfs_entry_prologue_unblock_plan.md",
        "restore_marker_trace.md",
        "dfs_prologue_storage_audit.md",
        "restore_vs_live_metadata_comparison.md",
        "dfs_entry_probe_matrix.md",
        "restore_missing_state_trace.md",
        "restore_schema_update_report.md",
        "restore_run_matrix.md",
        "original_assignment_artifact_report.md",
        "momentum_assignment_term_delta_matrix.md",
        "repair_decision.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "next_round_handoff.md",
        "next_round_codex_prompt.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (REPORT_DIR / name).exists(), name

    summary = (REPORT_DIR / "loop_state_summary.md").read_text(encoding="utf-8")
    assert "ORIGINAL_TRACKED_SCALAR_MOMENTUM_ARTIFACT_ACQUIRED_AFTER_RESTORE" in summary
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in summary

    missing = (REPORT_DIR / "restore_missing_state_trace.md").read_text(encoding="utf-8")
    assert "voltonode=0" in missing
    assert "RESTORE_STORMDRAIN_STATE_MISSING" in missing
