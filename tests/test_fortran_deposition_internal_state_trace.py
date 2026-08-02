from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_fortran_deposition_internal_trace_identifies_source_formulae():
    trace = (PHASE / "fortran_deposition_internal_state_trace.md").read_text(encoding="utf-8")

    assert "FORTRAN_DEPOSITION_INTERNAL_TRACE_READY" in trace
    assert "cv>cvlimit" in trace
    assert "absubar<2./3.*fvdepo" in trace
    assert "coedepo*(1.-3./2.*absubar/fvdepo)*(cvlimit-cv)/cvstar*absubar" in trace
    assert "debdepothick + abs(deporate*dt)" in trace
    assert "requires matched internal artifact" in trace
