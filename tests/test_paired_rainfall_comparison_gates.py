from __future__ import annotations

from pathlib import Path

from tests.comparison.run_paired_rainfall_alignment import run_alignment


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-05-03\phase_full_case_scientific_closure_after_erosion_repairs"
)
CASE_A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a")
CASE_B = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_50a\NO.5_XHG_V2_50a")


def test_paired_alignment_runner_writes_reports():
    results = run_alignment(CASE_A, CASE_B, PHASE_DIR, write_report=True)
    failed = {row["gate"]: row["status"] for row in results["failed_gates"]}

    assert "Flow_depth" in results["paired_diff"]["paired_supported_families"]
    assert "Volumetric_sediment" in results["paired_diff"]["paired_supported_families"]
    assert "Deposit_depth" in results["paired_diff"]["paired_supported_families"]
    assert "Erosion_depth" in results["paired_diff"]["paired_supported_families"]

    gate_status = {row["gate"]: row["status"] for row in results["gates"]}
    assert gate_status["G0_native_input_gate"] == "PASS"
    assert gate_status["G1_same_parameter_gate"] == "PASS"
    assert gate_status["G2_runtime_consumption_gate"] == "PASS"
    assert gate_status["G3_per_case_output_gate"] == "PASS"
    assert gate_status["G4_paired_rainfall_response_gate"] == "PASS"
    assert "G4_paired_rainfall_response_gate" not in failed

    root_causes = {row["category"]: row for row in results["root_causes"]}
    assert root_causes["precomputed_failure_schedule_gap"]["status"] == "partial"
    assert root_causes["runtime_consumption_gap"]["status"] == "fail"
    assert root_causes["runtime_logic_gap"]["status"] == "fail"
    for case_key in ("20a", "50a"):
        unsupported = {item["family"] for item in results["case_reports"][case_key]["numeric"]["unsupported_families"]}
        assert "LS_Scar" in unsupported
        assert "faildph" in unsupported

    for name in (
        "current_case_run_summary.md",
        "output_manifest_by_case.json",
        "parameter_audit_by_case.json",
        "runtime_input_manifest_by_case.json",
        "per_case_difference_report.md",
        "paired_rainfall_response_report.md",
        "delta_of_delta_matrix.md",
        "root_cause_matrix.md",
        "failed_gate_matrix.md",
        "acceptance_gate_report.md",
        "regression_delta.md",
        "production_fix_log.md",
        "remaining_blockers.md",
    ):
        assert (PHASE_DIR / name).exists(), name
