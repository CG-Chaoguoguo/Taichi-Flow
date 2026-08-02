import numpy as np
from pathlib import Path

from edda.core.fields import EDDAFields
from edda.solver import edda_solver as edda_solver_module
from edda.solver.edda_solver import EDDASolver


class _FakeField:
    def __init__(self, value):
        self.value = np.asarray(value)
        self.calls = 0

    def to_numpy(self):
        self.calls += 1
        return self.value.copy()


class _ExplodingField:
    calls = 0

    def to_numpy(self):
        self.calls += 1
        raise AssertionError("pt export should not be called")


def test_get_full_state_can_include_subset_without_exporting_pt():
    fields = object.__new__(EDDAFields)
    fields.h = _FakeField([[1.0, 2.0]])
    fields.pt = _ExplodingField()

    state = EDDAFields.get_full_state(fields, include_fields=("h", "pt"), exclude_fields=("pt",))

    assert list(state) == ["h"]
    np.testing.assert_allclose(state["h"], np.array([[1.0, 2.0]]))
    assert fields.h.calls == 1
    assert fields.pt.calls == 0


def test_get_full_state_exports_cell_area_cal_when_requested():
    fields = object.__new__(EDDAFields)
    fields.cell_area_cal = _FakeField([[100.0, 75.0]])

    state = EDDAFields.get_full_state(fields, include_fields=("cell_area_cal",))

    assert list(state) == ["cell_area_cal"]
    np.testing.assert_allclose(state["cell_area_cal"], np.array([[100.0, 75.0]]))
    assert fields.cell_area_cal.calls == 1


class _RecordingFields:
    def __init__(self):
        self.exclude_fields = None

    def get_full_state(self, *, include_fields=None, exclude_fields=None):
        self.exclude_fields = tuple(exclude_fields or ())
        assert include_fields is None
        assert "pt" in self.exclude_fields
        return {
            "h": np.array([[1.0, 0.0]], dtype=np.float64),
            "u": np.array([[0.25, 0.0]], dtype=np.float64),
            "v": np.array([[0.0, 0.0]], dtype=np.float64),
            "Cv": np.array([[0.1, 0.0]], dtype=np.float64),
            "z_bed": np.array([[9.9, 10.0]], dtype=np.float64),
            "z_original": np.array([[10.0, 10.0]], dtype=np.float64),
            "deposition_depth": np.array([[0.03, 0.0]], dtype=np.float64),
            "is_nodata": np.array([[0, 1]], dtype=np.int32),
        }


class _RecordingFieldsWithDirectionalVelocity:
    def __init__(self):
        self.exclude_fields = None

    def get_full_state(self, *, include_fields=None, exclude_fields=None):
        self.exclude_fields = tuple(exclude_fields or ())
        fv = np.zeros((2, 1, 8), dtype=np.float64)
        fv[0, 0, 4] = 7.0
        fv[1, 0, 0] = 2.0
        fv[1, 0, 1] = -4.0
        fv[1, 0, 2] = 6.0
        fv[1, 0, 3] = -8.0
        fv[1, 0, 7] = 100.0
        return {
            "h": np.array([[1.0], [1.0]], dtype=np.float64),
            "u": np.array([[99.0], [99.0]], dtype=np.float64),
            "v": np.array([[0.0], [0.0]], dtype=np.float64),
            "Cv": np.array([[0.1], [0.2]], dtype=np.float64),
            "fv_fortran": fv,
            "z_bed": np.array([[9.9], [10.0]], dtype=np.float64),
            "z_original": np.array([[10.0], [10.0]], dtype=np.float64),
            "is_nodata": np.array([[0], [0]], dtype=np.int32),
        }


class _TimeStepper:
    t_current = 10.0
    output_count = 1


class _Config:
    save_intermediate = False


def test_output_results_excludes_pt_from_standard_output_state():
    solver = object.__new__(EDDASolver)
    solver.fields = _RecordingFields()
    solver.time_stepper = _TimeStepper()
    solver.config = _Config()
    solver.results = []
    solver.export_metadata = {}
    solver.output_callback = None
    solver.dfs_dynamic_wave = None

    EDDASolver._output_results(solver)

    assert solver.fields.exclude_fields == ("pt",)
    assert "pt" not in solver.results[0]["state"]
    assert "erosion_depth_fortran_output" in solver.results[0]["state"]


def test_output_results_exports_fortran_flow_velocity_from_directional_state(monkeypatch, tmp_path):
    exported = {}

    class _Exporter:
        def __init__(self, data, transform=None, crs=None, nodata_value=-9999.0):
            self.data = np.asarray(data)

        def to_geotiff(self, path):
            exported[Path(path).name] = self.data.copy()

    monkeypatch.setattr(edda_solver_module, "ResultExporter", _Exporter)

    solver = object.__new__(EDDASolver)
    solver.fields = _RecordingFieldsWithDirectionalVelocity()
    solver.time_stepper = _TimeStepper()
    solver.config = type("_Config", (), {"save_intermediate": True})()
    solver.results = []
    solver.output_dir = tmp_path
    solver.export_metadata = {"nodata_value": -9999.0}
    solver.output_callback = None
    solver.dfs_dynamic_wave = None

    EDDASolver._output_results(solver)

    np.testing.assert_allclose(exported["result_0001_velocity.tif"], np.array([[0.0, 10.0]]))
    assert exported["result_0001_velocity.tif"][0, 1] != 99.0


def test_export_final_results_excludes_pt_from_geotiff_state(monkeypatch, tmp_path):
    exported = []

    class _Exporter:
        def __init__(self, data, transform=None, crs=None, nodata_value=-9999.0):
            self.data = np.asarray(data)

        def to_geotiff(self, path):
            exported.append(path)

    monkeypatch.setattr(edda_solver_module, "ResultExporter", _Exporter)

    solver = object.__new__(EDDASolver)
    solver.fields = _RecordingFields()
    solver.output_dir = tmp_path
    solver.export_metadata = {"nodata_value": -9999.0}
    solver.dfs_dynamic_wave = None
    solver.results = []

    EDDASolver.export_final_results(solver, format="geotiff")

    assert solver.fields.exclude_fields == ("pt",)
    assert [path.split("\\")[-1].split("/")[-1] for path in exported] == [
        "final_depth.tif",
        "final_erosion.tif",
        "final_deposition.tif",
    ]


def test_export_final_results_uses_deposition_depth_field(monkeypatch, tmp_path):
    exported = {}

    class _Exporter:
        def __init__(self, data, transform=None, crs=None, nodata_value=-9999.0):
            self.data = np.asarray(data)

        def to_geotiff(self, path):
            exported[Path(path).name] = self.data.copy()

    class _Fields:
        def get_full_state(self, *, include_fields=None, exclude_fields=None):
            return {
                "h": np.array([[1.0], [1.0]], dtype=np.float64),
                "Cv": np.array([[0.1], [0.2]], dtype=np.float64),
                "z_bed": np.array([[12.0], [10.0]], dtype=np.float64),
                "z_original": np.array([[10.0], [10.0]], dtype=np.float64),
                "deposition_depth": np.array([[0.25], [0.5]], dtype=np.float64),
                "is_nodata": np.array([[0], [0]], dtype=np.int32),
            }

    monkeypatch.setattr(edda_solver_module, "ResultExporter", _Exporter)

    solver = object.__new__(EDDASolver)
    solver.fields = _Fields()
    solver.output_dir = tmp_path
    solver.export_metadata = {"nodata_value": -9999.0}
    solver.dfs_dynamic_wave = None

    EDDASolver.export_final_results(solver, format="geotiff")

    np.testing.assert_allclose(exported["final_deposition.tif"], np.array([[0.25, 0.5]]))
    assert exported["final_deposition.tif"][0, 0] != 2.0
