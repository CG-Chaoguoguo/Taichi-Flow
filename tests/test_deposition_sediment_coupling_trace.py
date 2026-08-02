from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_deposition_coupling_trace_contains_core_fortran_semantics():
    trace = (PHASE / "fortran_deposition_sediment_coupling_trace.md").read_text(encoding="utf-8")

    assert "DEPOSITION_COUPLING_TRACE_READY" in trace
    assert "cv>cvlimit .and. absubar<2./3.*fvdepo" in trace
    assert "deporate=coedepo" in trace
    assert "tempele=ele-erorate*dt+abs(deporate)*dt-tempfsh" in trace
    assert "frhopredi=(frhopredi1*fhpredi1+erorate*dt*rhoero+deporate*dt*rhodepo+tempfsh*tempfsrho)/fhpredi" in trace


def test_coupling_trace_blocks_formula_change_without_internal_artifact():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "original/current internal" in decision
