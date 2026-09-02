from pathlib import Path
from types import SimpleNamespace

from api.services.runtime_session import RuntimeSession, prepare_runtime_from_payload


class _DiagnosticFakeSolver:
    instances = []

    def __init__(self, config):
        self.config = config
        self.time_stepper = SimpleNamespace(output_count=0)
        self.rainfall_reader = None
        self.progress_callback = None
        self.output_callback = None
        self.results = []
        self.statuses = []
        _DiagnosticFakeSolver.instances.append(self)

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

    def get_numerical_diagnostics(self, *, status=None):
        self.statuses.append(status)
        return {
            "schema_version": 1,
            "status": status,
            "global_volume_ledger": {"relative_error": 0.0, "passed": True},
        }


def test_runtime_session_persists_diagnostics_before_manifest(tmp_path: Path):
    dem_file = tmp_path / "tiny.asc"
    dem_file.write_text("placeholder\n", encoding="utf-8")
    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        dem_file=str(dem_file),
        runtime_profile_name="cuda_production_default",
        overrides={"time": {"t_end": 1.0, "dt_output": 1.0}},
    )
    session = RuntimeSession(
        prepared,
        solver_factory=_DiagnosticFakeSolver,
        reset_runtime_on_dispose=False,
    )
    state = {"simulations": {prepared.simulation_id: session.initialize()}}

    session.run_to_completion(state)

    diagnostics_path = prepared.output_dir / "numerical_diagnostics.json"
    manifest_path = prepared.output_dir / "output_manifest.json"
    assert diagnostics_path.exists()
    assert manifest_path.exists()
    assert "numerical_diagnostics.json" in manifest_path.read_text(encoding="utf-8")
    assert state["simulations"][prepared.simulation_id]["numerical_diagnostics"]["status"] == "completed"
    assert _DiagnosticFakeSolver.instances[-1].statuses == ["pending", "completed"]

