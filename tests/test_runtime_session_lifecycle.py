from pathlib import Path
from types import SimpleNamespace

from api.services.runtime_session import RuntimeSession, prepare_runtime_from_payload


class _FakeSolver:
    instances = []

    def __init__(self, config):
        self.config = config
        self.time_stepper = SimpleNamespace(output_count=0)
        self.rainfall_reader = None
        self.progress_callback = None
        self.output_callback = None
        self.results = ["large-placeholder"]
        _FakeSolver.instances.append(self)

    def initialize(self):
        return None

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def run(self):
        if self.progress_callback:
            self.progress_callback({"progress": 100.0, "t_current": self.config.time.t_end, "step_count": 1})

    def export_final_results(self, format: str = "geotiff"):
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final_depth.tif").write_text("ok\n", encoding="utf-8")
        self.time_stepper.output_count = 1


class _OutputBoundaryFakeSolver(_FakeSolver):
    def run(self):
        for step_count, output_count in (
            (1, 0),
            (2, 0),
            (3, 1),
            (4, 1),
            (5, 2),
        ):
            self.time_stepper.output_count = output_count
            if self.progress_callback:
                self.progress_callback(
                    {
                        "progress": step_count * 10.0,
                        "t_current": float(step_count),
                        "step_count": step_count,
                    }
                )

    def export_final_results(self, format: str = "geotiff"):
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final_depth.tif").write_text("ok\n", encoding="utf-8")


class _RecordingSimulationState(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.progress_snapshots = []

    def update(self, *args, **kwargs):
        payload = dict(*args, **kwargs)
        super().update(payload)
        if "progress" in payload and "status" not in payload:
            self.progress_snapshots.append(dict(payload))


def test_runtime_session_releases_solver_after_completed_run(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    dem_file.write_text("placeholder\n", encoding="utf-8")
    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        dem_file=str(dem_file),
        runtime_profile_name="cuda_production_default",
        overrides={"time": {"t_end": 1.0, "dt_output": 1.0}},
    )
    session = RuntimeSession(prepared, solver_factory=_FakeSolver, reset_runtime_on_dispose=False)
    app_state = {"simulations": {prepared.simulation_id: session.initialize()}}

    session.run_to_completion(app_state)

    sim_data = app_state["simulations"][prepared.simulation_id]
    fake_solver = _FakeSolver.instances[-1]
    assert sim_data["status"] == "completed"
    assert sim_data["solver"] is None
    assert sim_data["runtime_session"] is None
    assert session.solver is None
    assert fake_solver.progress_callback is None
    assert fake_solver.output_callback is None
    assert fake_solver.results == []
    assert sim_data["resource_summary"]["children"] == 0
    assert sim_data["resource_summary"]["active_sessions"] == 0
    assert (prepared.output_dir / "parameter_catalog.json").exists()
    assert (prepared.output_dir / "final_depth.tif").exists()


def test_runtime_session_publishes_progress_only_when_output_count_increases(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    dem_file.write_text("placeholder\n", encoding="utf-8")
    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        dem_file=str(dem_file),
        runtime_profile_name="cuda_production_default",
        overrides={"time": {"t_end": 5.0, "dt_output": 2.0}},
    )
    session = RuntimeSession(
        prepared,
        solver_factory=_OutputBoundaryFakeSolver,
        reset_runtime_on_dispose=False,
    )
    sim_data = _RecordingSimulationState(session.initialize())

    session.run_to_completion({"simulations": {prepared.simulation_id: sim_data}})

    assert [snapshot["output_count"] for snapshot in sim_data.progress_snapshots] == [1, 2]
    assert [snapshot["step_count"] for snapshot in sim_data.progress_snapshots] == [3, 5]


def test_direct_payload_keeps_uploaded_inflow_inactive_when_original_flag_is_false(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    inflow_file = tmp_path / "inflow.txt"
    dem_file.write_text("placeholder\n", encoding="utf-8")
    inflow_file.write_text("placeholder\n", encoding="utf-8")

    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        dem_file=str(dem_file),
        case_input_files={"inflow.txt": str(inflow_file)},
        runtime_profile_name="cuda_production_default",
        overrides={
            "run_flags": {
                "simulate_inflow_hydrograph": False,
            },
            "time": {"t_end": 1.0, "dt_output": 60.0},
        },
    )

    registry = prepared.runtime_input_manifest["input_source_registry"]["inflow_source"]
    manifest = {entry["family"]: entry for entry in prepared.runtime_input_manifest["inputs"]}

    assert registry["state"] == "file_backed"
    assert registry["runtime_active"] is False
    assert manifest["inflow.txt"]["original_branch_active"] is False
    assert manifest["inflow.txt"]["current_backend_branch_active"] is False
