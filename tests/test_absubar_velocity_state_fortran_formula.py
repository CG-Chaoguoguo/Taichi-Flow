from pathlib import Path

from edda.config.sim_config import HydrologyParams


REPO = Path(__file__).resolve().parents[1]


def test_absubar_velocity_state_flag_and_source_trace_present():
    config_text = (REPO / "edda" / "config" / "sim_config.py").read_text(encoding="utf-8")
    solver_text = (REPO / "edda" / "solver" / "dfs_dynamic_wave.py").read_text(encoding="utf-8")

    assert "use_fortran_absubar_velocity_state" in config_text
    assert "fvpredi2=0.5*(fv+fvpredi)" in solver_text
    assert "velocity_state_scale = 0.5" in solver_text
    assert "fortran_preflux_fvpredi2_half_accepted" in solver_text


def test_absubar_velocity_state_defaults_to_fortran_lifecycle():
    params = HydrologyParams()

    assert params.use_fortran_absubar_velocity_state is True
