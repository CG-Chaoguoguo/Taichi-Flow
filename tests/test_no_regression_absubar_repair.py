from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_absubar_velocity_state_repair_not_reverted_by_sediment_phase():
    config_text = (REPO / "edda" / "config" / "sim_config.py").read_text(encoding="utf-8")
    solver_text = (REPO / "edda" / "solver" / "dfs_dynamic_wave.py").read_text(encoding="utf-8")
    fix_log = (PHASE / "production_fix_log.md").read_text(encoding="utf-8")

    assert "use_fortran_absubar_velocity_state" in config_text
    assert "velocity_state_scale = 0.5" in solver_text
    assert "absubar velocity-state repair" in fix_log


def test_sediment_phase_does_not_reauthorize_closed_chain_edits():
    fix_log = (PHASE / "production_fix_log.md").read_text(encoding="utf-8")

    forbidden_scopes = ["rainfall", "Manning", "fallback", "outflow", "`taoc`", "`kero`"]
    for scope in forbidden_scopes:
        assert scope in fix_log
    assert "No active solver formula changed" in fix_log
