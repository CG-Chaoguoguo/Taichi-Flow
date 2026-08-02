from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SEDIMENT_PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"
DEPOSIT_PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_volumetric_writer_parity_remains_active():
    solver_text = (REPO / "edda" / "solver" / "edda_solver.py").read_text(encoding="utf-8")
    assert "_build_fortran_volumetric_sediment_output" in solver_text
    assert "h < 0.005" in solver_text


def test_volumetric_writer_evidence_is_retained_across_deposit_phase():
    assert (SEDIMENT_PHASE / "fortran_volumetric_sediment_output_trace.md").exists()
    handoff = (DEPOSIT_PHASE / "next_round_handoff.md").read_text(encoding="utf-8")
    assert "Volumetric" in handoff
