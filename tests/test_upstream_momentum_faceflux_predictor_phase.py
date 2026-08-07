import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_upstream_momentum_faceflux_predictor_ledger_repair"
)
PATCH = (
    REPO
    / "tests"
    / "_fortran_toolchain_sandbox"
    / "patches"
    / "instrument_original_upstream_momentum_faceflux_probe.patch"
)


def test_fortran_momentum_faceflux_trace_is_ready_and_scoped_to_terms():
    trace = (PHASE / "fortran_upstream_momentum_faceflux_trace.md").read_text(encoding="utf-8")

    assert "FORTRAN_MOMENTUM_FACEFLUX_TRACE_READY" in trace
    assert "fvpredi2=0.5*(fv+fvpredi)" in trace
    assert "post-flux snapshot" in trace

    for term in ("grad", "sfy", "sfmiu", "sfmanning", "localvdiff", "artivis", "dv", "fvlimit"):
        assert term in trace


def test_delta_matrix_keeps_production_closed_until_term_artifacts_exist():
    payload = json.loads((PHASE / "momentum_faceflux_delta_matrix.json").read_text(encoding="utf-8"))

    assert payload["status"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["blocker"] == "MOMENTUM_FACEFLUX_RUNTIME_TERM_ARTIFACT_REQUIRED"
    assert payload["prior_status"] == "VELOCITY_STATE_UPSTREAM_MOMENTUM_MISMATCH"

    rows = payload["rows"]
    assert rows
    assert {row["classification"] for row in rows} == {"TERM_RUNTIME_ARTIFACT_REQUIRED"}
    assert {row["production_eligibility"] for row in rows} == {"not_allowed_missing_term_delta"}


def test_original_probe_patch_and_next_prompt_are_actionable():
    assert PATCH.exists()
    patch_text = PATCH.read_text(encoding="utf-8")
    prompt = (PHASE / "next_round_codex_prompt.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    for term in ("grad", "sfy", "sfmiu", "sfmanning", "localvdiff", "artivis", "dv", "fvlimit", "qqmass"):
        assert term in patch_text
        assert term in prompt

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "No production repair is allowed" in decision
    assert "Do not modify deporate formula" in prompt
    assert "post-flux velocity" in prompt
