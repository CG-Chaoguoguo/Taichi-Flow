from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_flow_deposition_coupling_trace_keeps_internal_state_as_open_surface():
    trace = (PHASE / "fortran_flow_deposition_coupling_trace.md").read_text(encoding="utf-8")

    assert "FLOW_DEPOSITION_COUPLING_TRACE_READY" in trace
    assert "fhpredi=fhpredi1+(erorate+deporate)*dt+tempfsh" in trace
    assert "qmassnet" in trace
    assert "frhoflux" in trace
    assert "frhopredi2=(frhopredi*fhpredi*cellarea+qmassnet)/fhpredi2/cellarea" in trace
