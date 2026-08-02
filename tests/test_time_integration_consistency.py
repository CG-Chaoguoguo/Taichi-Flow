import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from edda.solver.edda_solver import EDDASolver
from edda.solver.time_stepper import TimeStepper


class _HarnessSolver(EDDASolver):
    """
    Lightweight harness around EDDASolver.run() to regression-test the
    accepted/rejected dt control flow without initializing the full Taichi stack.
    """

    def __init__(self, scripted_steps, *, t_end: float, dt_initial: float, dt_output: float):
        self.fields = object()
        self.time_stepper = TimeStepper(
            t_start=0.0,
            t_end=t_end,
            dt_initial=dt_initial,
            dt_min=1.0e-4,
            dt_max=20.0,
            dt_output=dt_output,
            CFL=0.5,
            dx=10.0,
            dy=10.0,
        )
        self.results = []
        self.rainfall_reader = None
        self.progress_callback = None
        self.output_callback = None
        self.dfs_dynamic_wave = None
        self.fortran_tempdt = 0.0
        self.dfs_candidate_step_id = 0
        self.dfs_accepted_step_id = 0
        self._scripted_steps = list(scripted_steps)
        self.physics_dts = []
        self.output_times = []

    def _use_fortran_dfs(self) -> bool:  # pragma: no cover - behavior tested through run()
        return True

    def _physics_step(self, dt: float):  # pragma: no cover - behavior tested through run()
        self.physics_dts.append(float(dt))
        if not self._scripted_steps:
            raise AssertionError("No scripted step info left for _physics_step().")
        return dict(self._scripted_steps.pop(0))

    def _output_results(self):  # pragma: no cover - behavior tested through run()
        self.output_times.append(float(self.time_stepper.t_current))


class _StopAfterAudit(RuntimeError):
    pass


def test_run_advances_time_with_used_dt_not_next_dt(monkeypatch):
    monkeypatch.setenv("TQDM_DISABLE", "1")

    solver = _HarnessSolver(
        scripted_steps=[
            {
                "accepted": True,
                "used_dt": 1.0,
                "next_dt": 2.0,
            }
        ],
        t_end=1.0,
        dt_initial=1.0,
        dt_output=10.0,
    )

    solver.run()

    assert solver.physics_dts == [1.0]
    assert solver.time_stepper.t_current == pytest.approx(1.0)
    # The next candidate dt is allowed to change after acceptance, but time
    # advancement itself must follow the accepted step size.
    assert solver.time_stepper.dt_current == pytest.approx(2.0)


def test_fortran_tempdt_is_restored_after_truncation_and_retry(monkeypatch):
    monkeypatch.setenv("TQDM_DISABLE", "1")

    solver = _HarnessSolver(
        scripted_steps=[
            {
                "accepted": False,
                "used_dt": 5.0,
                "suggested_dt": 2.0,
                "next_dt": 2.0,
            },
            {
                "accepted": True,
                "used_dt": 2.0,
                "next_dt": 3.0,
            },
            {
                "accepted": True,
                "used_dt": 3.0,
                "next_dt": 4.0,
            },
        ],
        t_end=6.0,
        dt_initial=8.0,
        dt_output=5.0,
    )

    def _stop_after_output(info):
        if info["t_current"] >= 5.0:
            raise _StopAfterAudit()

    solver.progress_callback = _stop_after_output

    with pytest.raises(_StopAfterAudit):
        solver.run()

    # Outer-loop candidate 8.0 s is first truncated to the 5.0 s output boundary,
    # then rejected to 2.0 s, then a second accepted step reaches the output.
    assert solver.physics_dts == [5.0, 2.0, 3.0]
    assert solver.time_stepper.t_current == pytest.approx(5.0)
    # Match original dfs.F90 semantics: restore the previously larger pre-output
    # dt after the output-aligned block finishes.
    assert solver.fortran_tempdt == pytest.approx(8.0)
    assert solver.time_stepper.dt_current == pytest.approx(8.0)
    assert solver.time_stepper.rejected_steps == 1
    assert any(t == pytest.approx(5.0) for t in solver.output_times)


def test_output_truncation_precedes_end_time_truncation_when_boundaries_coincide(monkeypatch):
    monkeypatch.setenv("TQDM_DISABLE", "1")

    solver = _HarnessSolver(
        scripted_steps=[
            {
                "accepted": True,
                "used_dt": 5.0,
                "next_dt": 5.0001,
            }
        ],
        t_end=5.0,
        dt_initial=8.0,
        dt_output=5.0,
    )

    solver.run()

    assert solver.physics_dts == [5.0]
    assert solver.time_stepper.t_current == pytest.approx(5.0)
    # dfs.F90 tests `ttout` before `simul`, so the pre-output larger candidate
    # dt must still survive even when the run also ends at that same time.
    assert solver.fortran_tempdt == pytest.approx(8.0)
    assert solver.time_stepper.dt_current == pytest.approx(8.0)
