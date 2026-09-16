from pathlib import Path
from types import SimpleNamespace

from copy import deepcopy

from api.services.edda_switch_registry import EDDA_SWITCH_REGISTRY
from api.services.parameter_templates import builtin_bj_hxl_template
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


def test_runtime_session_applies_frozen_fp64_compute_override(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    dem_file.write_text("placeholder\n", encoding="utf-8")
    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        dem_file=str(dem_file),
        runtime_profile_name="cuda_production_default",
        overrides={
            "compute": {"use_double_precision": True},
            "time": {"t_end": 1.0, "dt_output": 1.0},
        },
        frozen_effective_config={"compute.use_double_precision": True},
    )

    assert prepared.config.compute.use_double_precision is True
    assert prepared.effective_config["frozen_effective_config"]["compute.use_double_precision"] is True
    assert prepared.runtime_input_manifest["frozen_effective_config"]["compute.use_double_precision"] is True


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


def test_structured_edda_run_controls_activate_uploaded_inflow(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    inflow_file = tmp_path / "inflow.txt"
    dem_file.write_text("placeholder\n", encoding="utf-8")
    inflow_file.write_text("placeholder\n", encoding="utf-8")

    values = builtin_bj_hxl_template()["values"]
    edda = {"registry_version": values["edda.registry_version"], "run_controls": {}, "output_controls": {}}
    for spec in EDDA_SWITCH_REGISTRY:
        group = "output_controls" if spec.group in {"legacy_output", "process_output"} else "run_controls"
        edda[group][spec.key] = deepcopy(values[spec.taichi_config_path])
    edda["run_controls"]["simulate_inflow_hydrograph"] = True

    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        dem_file=str(dem_file),
        case_input_files={"inflow.txt": str(inflow_file)},
        runtime_profile_name="cuda_production_default",
        overrides={
            "edda": edda,
            "time": {"t_end": 1.0, "dt_output": 60.0},
        },
    )

    registry = prepared.runtime_input_manifest["input_source_registry"]["inflow_source"]
    manifest = {entry["family"]: entry for entry in prepared.runtime_input_manifest["inputs"]}

    assert registry["runtime_active"] is True
    assert manifest["inflow.txt"]["original_branch_active"] is True
    assert manifest["inflow.txt"]["current_backend_branch_active"] is True
