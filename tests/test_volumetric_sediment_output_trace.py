from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_fortran_volumetric_output_trace_records_shallow_depth_mask():
    trace = (PHASE / "fortran_volumetric_sediment_output_trace.md").read_text(encoding="utf-8")

    assert "tfg(i)=cv(i)" in trace
    assert "if(fh(i)<0.005) tfg(i) = 0." in trace or "if(fh(i)<0.005) tfg(i)=0." in trace
    assert "VOLUMETRIC_OUTPUT_INTERPRETATION_REPAIR_CANDIDATE" in trace


def test_current_concentration_export_uses_fortran_writer_helper():
    solver_text = (REPO / "edda" / "solver" / "edda_solver.py").read_text(encoding="utf-8")

    assert "_build_fortran_volumetric_sediment_output" in solver_text
    assert "h < 0.005" in solver_text
    assert "Cv_export = self._build_fortran_volumetric_sediment_output(state).T.copy()" in solver_text
