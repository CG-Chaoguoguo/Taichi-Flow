import inspect

from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver


def test_rholimit_seed_cvstar_clamp_is_explicit_experiment_not_default():
    source = inspect.getsource(DFSDynamicWaveSolver._seed_initial_rholimit_from_input_slope)

    assert "invalid_cvlimit = cvlimit < 0.0 or cvlimit > 1.0" in source
    assert "self.cvlimit_seed_cvstar_clamp_enabled" in source
    assert "invalid_cvlimit = cvlimit < 0.0 or cvlimit > cvstar" in source
