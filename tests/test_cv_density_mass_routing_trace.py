from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_cv_density_mass_routing_trace_preserves_formula_scope():
    trace = (PHASE / "fortran_cv_density_mass_routing_trace.md").read_text(encoding="utf-8")

    assert "CV_DENSITY_MASS_ROUTING_TRACE_READY" in trace
    assert "frhopredi2=(frhopredi*fhpredi*cellareacal+qmassnet)" in trace
    assert "qqmass=frhoflux*qq" in trace
    assert "no Cv/rho/mass-routing production formula change is justified" in trace


def test_current_solver_still_carries_fortran_mass_routing_fields():
    fields_text = (REPO / "edda" / "core" / "fields.py").read_text(encoding="utf-8")
    solver_text = (REPO / "edda" / "solver" / "dfs_dynamic_wave.py").read_text(encoding="utf-8")

    for token in ("frhopredi1", "frhopredi", "frhopredi2", "qqmass_fortran", "qmassnet_fortran"):
        assert token in fields_text
        assert token in solver_text
