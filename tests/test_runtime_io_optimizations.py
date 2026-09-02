import numpy as np

from edda.io.async_result_writer import AsyncResultWriter, GridWriteJob
from edda.io.result_exporter import ResultExporter
from edda.solver.edda_solver import EDDASolver


def test_async_result_writer_writes_ascii_and_flushes(tmp_path):
    writer = AsyncResultWriter(max_queued_frames=2)
    writer.start()
    path = tmp_path / "grid.txt"
    data = np.array([[1.25, 2.5], [3.75, 4.0]], dtype=np.float64)
    writer.submit(
        GridWriteJob(
            kind="ascii",
            path=str(path),
            data=data,
            nodata_value=-9999.0,
        )
    )
    writer.close()

    text = path.read_text(encoding="ascii")
    assert "ncols         2" in text
    assert "1.250000" in text
    assert "4.000000" in text


def test_ascii_grid_uses_buffered_binary_write(tmp_path):
    path = tmp_path / "fast.asc"
    exporter = ResultExporter(
        data=np.array([[0.1, 0.2]], dtype=np.float64),
        nodata_value=-9999.0,
    )
    exporter.to_ascii_grid(str(path))
    body = path.read_bytes()
    assert body.startswith(b"ncols")
    assert b"0.100000" in body


def test_observe_numerical_step_respects_stride():
    solver = object.__new__(EDDASolver)
    solver.config = type(
        "_Config",
        (),
        {"compute": type("_Compute", (), {"numerical_observe_stride": 20})(), "time": type("_Time", (), {"dt_min": 1e-5})()},
    )()
    solver.dfs_dynamic_wave = None
    solver.dfs_candidate_step_id = 7
    solver.numerical_max_abs_relative_error = 0.0
    solver.numerical_volume_violation_count = 0
    solver.numerical_dt_min_hits = 0
    solver.numerical_nonfinite_counts = {}
    solver.numerical_dt_history = []
    solver.numerical_reject_reasons = {}
    solver.numerical_reject_examples = {}
    solver.numerical_observe_count = 0
    solver.time_stepper = None

    solver._observe_numerical_step({"used_dt": 0.2, "accepted": True}, accepted=True, attempted_dt=0.2)

    assert solver.numerical_observe_count == 0
    assert solver.numerical_dt_history == [0.2]


def test_observe_numerical_step_forces_volume_on_output_frame():
    class _Wave:
        def get_volume_balance_snapshot(self):
            return {"relative_error": 0.002}

    solver = object.__new__(EDDASolver)
    solver.config = type(
        "_Config",
        (),
        {"compute": type("_Compute", (), {"numerical_observe_stride": 20})(), "time": type("_Time", (), {"dt_min": 1e-5})()},
    )()
    solver.dfs_dynamic_wave = _Wave()
    solver.dfs_candidate_step_id = 7
    solver.numerical_max_abs_relative_error = 0.0
    solver.numerical_volume_violation_count = 0
    solver.numerical_dt_min_hits = 0
    solver.numerical_nonfinite_counts = {}
    solver.numerical_dt_history = []
    solver.numerical_reject_reasons = {}
    solver.numerical_reject_examples = {}
    solver.numerical_observe_count = 0
    solver.time_stepper = None

    solver._observe_numerical_step(
        {"used_dt": 0.2, "accepted": True},
        accepted=True,
        attempted_dt=0.2,
        force_volume=True,
    )

    assert solver.numerical_observe_count == 1
    assert solver.numerical_max_abs_relative_error == 0.002
    assert solver.numerical_volume_violation_count == 1
