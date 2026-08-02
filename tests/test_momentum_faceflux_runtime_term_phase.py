import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_momentum_faceflux_runtime_term_artifact_and_delta"
)
PATCH = (
    REPO
    / "tests"
    / "_fortran_toolchain_sandbox"
    / "patches"
    / "instrument_original_momentum_faceflux_runtime_terms_probe.patch"
)


def test_target_cell_direction_time_locked_for_runtime_term_probe():
    target = (PHASE / "target_cell_direction_time_index.md").read_text(encoding="utf-8")
    term_list = (PHASE / "momentum_faceflux_runtime_term_list.md").read_text(encoding="utf-8")

    assert "TARGET_CELL_DIRECTION_TIME_LOCKED" in target
    assert "`35978`" in target
    assert "`D6`" in target
    assert "228.1s" in target

    for term in ("grad", "sfy", "sfmiu", "sfmanning", "localvdiff", "artivis", "dv", "fvlimit", "qqmass"):
        assert term in term_list


def test_runtime_delta_remains_closed_after_current_export_failure():
    payload = json.loads((PHASE / "momentum_faceflux_runtime_term_delta_matrix.json").read_text(encoding="utf-8"))
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    current_report = (PHASE / "current_momentum_faceflux_runtime_terms_report.md").read_text(encoding="utf-8")

    assert payload["status"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["blocker"] == "MOMENTUM_FACEFLUX_RUNTIME_TERM_ARTIFACT_REQUIRED"
    assert payload["current_failure"] == "CURRENT_MOMENTUM_FACEFLUX_RUNTIME_ARTIFACT_EXPORT_FAILED_TAICHI_LLVM"
    assert {row["classification"] for row in payload["rows"]} == {"RUNTIME_TERM_ARTIFACT_REQUIRED"}

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "No production solver formula was changed" in decision
    assert "LLVM Fatal Error" in current_report
    assert "full-grid `momentum_*` 3D fields" in current_report


def test_next_prompt_requires_tracked_scalar_probe_not_full_grid_dump():
    prompt = (PHASE / "next_round_codex_prompt.md").read_text(encoding="utf-8")
    patch_text = PATCH.read_text(encoding="utf-8")

    assert "phase_tracked_scalar_momentum_faceflux_probe_cell35978" in prompt
    assert "tracked-scalar momentum probes" in prompt
    assert "Do not dump full grids" in patch_text
    assert "Do not modify deporate formula" in prompt
    assert "post-flux production source-rate mapping" in prompt
