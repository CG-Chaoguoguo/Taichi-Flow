from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_deposit_output_trace_marks_writer_aligned():
    trace = (PHASE / "fortran_deposit_output_trace.md").read_text(encoding="utf-8")

    assert "FORTRAN_DEPOSIT_OUTPUT_TRACE_READY" in trace
    assert "tfg(i)=ele(i)-eleori(i)" in trace
    assert "if (tfg(i)<0.) tfg(i)=0." in trace
    assert "no output parity repair" in trace


def test_current_deposition_export_uses_bed_delta_semantics():
    solver_text = (REPO / "edda" / "solver" / "edda_solver.py").read_text(encoding="utf-8")

    assert "final_deposition.tif" in solver_text
    assert "np.maximum(final_state['z_bed'] - final_state['z_original'], 0.0)" in solver_text
