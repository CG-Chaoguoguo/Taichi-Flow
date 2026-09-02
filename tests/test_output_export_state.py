import numpy as np
from pathlib import Path

from edda.config.sim_config import SimulationConfig
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
        self.include_fields = None

    def get_full_state(self, *, include_fields=None, exclude_fields=None):
        self.include_fields = tuple(include_fields) if include_fields is not None else None
        self.exclude_fields = tuple(exclude_fields or ())
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


def _strict_output_solver(
    tmp_path,
    *,
    extension_controls=None,
    hydrology=None,
    run_controls=None,
    **enabled_outputs,
):
    output_controls = {
        "save_fs_min_grid": False,
        "save_flow_depth": False,
        "save_max_flow_depth": False,
        "save_flow_velocity": False,
        "save_max_flow_velocity": False,
        "save_erosion_depth": False,
        "save_deposition_depth": False,
        "save_total_depth": False,
        "save_max_solid_depth": False,
        "save_volumetric_sediment_concentration": False,
        "save_outflow_process": False,
        "save_drainage_nodal_flow": False,
        "save_drainage_conduit_flow": False,
    }
    output_controls.update(enabled_outputs)
    run = {
        "simulate_debris_flow": True,
        "simulate_rainfall": True,
        "simulate_infiltration": True,
        "simulate_inflow_hydrograph": False,
        "simulate_outflow_cell": True,
        "simulate_shallow_landslide": True,
        "simulate_erosion": True,
        "simulate_water_and_solid_separately": True,
        "simulate_drainage_flow": False,
        "simulate_barrier": False,
    }
    run.update(run_controls or {})
    payload = {
        "dem_file": "dummy.asc",
        "output_dir": str(tmp_path),
        "edda": {
            "run_controls": run,
            "output_controls": output_controls,
            "extension_controls": dict(extension_controls or {}),
        },
    }
    if hydrology:
        payload["hydrology"] = hydrology
    config = SimulationConfig.from_dict(payload)
    solver = EDDASolver(config)
    solver.output_dir = tmp_path
    solver.export_metadata = {"nodata_value": -9999.0}
    solver.dfs_dynamic_wave = None
    return solver


def _strict_output_state():
    fv = np.zeros((2, 1, 8), dtype=np.float64)
    return {
        "h": np.array([[1.0], [1.0]], dtype=np.float64),
        "Cv": np.array([[0.2], [0.3]], dtype=np.float64),
        "fv_fortran": fv,
        "z_bed": np.array([[12.0], [9.0]], dtype=np.float64),
        "z_original": np.array([[10.0], [10.0]], dtype=np.float64),
        "deposition_depth": np.array([[99.0], [99.0]], dtype=np.float64),
        "erosion_depth_fortran_output": np.array([[0.0], [1.0]], dtype=np.float64),
        "max_flow_depth": np.array([[2.0], [3.0]], dtype=np.float64),
        "max_flow_velocity": np.array([[4.0], [5.0]], dtype=np.float64),
        "max_solid_depth": np.array([[0.005], [0.006]], dtype=np.float64),
        "fdepth": np.array([[0.0], [2.0]], dtype=np.float64),
    }


def _record_strict_text_families(solver, state):
    written = {}

    def record(stem, _t, data, _nodata_mask, _nodata_value):
        written[stem] = np.asarray(data).copy()

    solver._write_edda_text_grid = record
    solver._export_taichi_named_edda_text_outputs(
        state=state,
        t=10.0,
        h_export=state["h"].T.copy(),
        velocity_export=np.zeros((1, 2), dtype=np.float64),
        cv_export=state["Cv"].T.copy(),
        nodata_mask=np.zeros((1, 2), dtype=np.int32),
        nodata_value=-9999.0,
    )
    return written


def test_strict_edda_text_writer_emits_only_enabled_family(tmp_path):
    solver = _strict_output_solver(tmp_path, save_flow_depth=True)

    written = _record_strict_text_families(solver, _strict_output_state())

    assert list(written) == ["Flow_depth_EDDA"]


def test_fs_min_writer_follows_fsminsave_even_when_fssimul_is_off(tmp_path):
    solver = _strict_output_solver(
        tmp_path,
        save_fs_min_grid=True,
        run_controls={"simulate_shallow_landslide": False},
    )
    state = _strict_output_state()
    state["fdepth"] = np.array([[0.0], [0.0]], dtype=np.float64)

    written = _record_strict_text_families(solver, state)

    assert "LS_ScarEDDA" in written
    assert "faildphEDDA" in written
    np.testing.assert_allclose(written["LS_ScarEDDA"], [[0.0, 0.0]])
    np.testing.assert_allclose(written["faildphEDDA"], [[0.0, 0.0]])


def test_chamoli_regime_depths_write_under_flowdepthsave(tmp_path):
    solver = _strict_output_solver(
        tmp_path,
        save_flow_depth=True,
        save_max_flow_depth=True,
        hydrology={"dfs_manningbar_variant": "debrisflowmanning_cvtol"},
    )
    state = _strict_output_state()
    state["sfh"] = np.array([[1.5], [0.0]], dtype=np.float64)
    state["dfh"] = np.array([[0.0], [0.8]], dtype=np.float64)
    state["ffh"] = np.array([[0.2], [0.0]], dtype=np.float64)
    state["maxsfh"] = np.array([[2.0], [0.0]], dtype=np.float64)
    state["maxdfh"] = np.array([[0.0], [1.1]], dtype=np.float64)
    state["maxffh"] = np.array([[0.4], [0.0]], dtype=np.float64)

    written = _record_strict_text_families(solver, state)

    assert "SFdepthEDDA" in written
    assert "DFdepthEDDA" in written
    assert "FFdepthEDDA" in written
    assert "MaxSFdepthEDDA" in written
    np.testing.assert_allclose(written["SFdepthEDDA"], [[1.5, 0.0]])
    np.testing.assert_allclose(written["DFdepthEDDA"], [[0.0, 0.8]])
    np.testing.assert_allclose(written["MaxDFdepthEDDA"], [[0.0, 1.1]])


def test_chamoli_sf_df_ff_classify_uses_previous_cv_semantics():
    """Document Chamoli dfs.F90:1115-1133: class depths use PREVIOUS cv vs NEW h.

    Cell with incoming shallow clear water (prev_cv < 0.2) must land in FF even
    when the accepted step later raises Cv via mixing/erosion.
    """
    import inspect

    from edda.solver import dfs_dynamic_wave as dfs_mod

    cls = next(
        obj
        for name, obj in vars(dfs_mod).items()
        if isinstance(obj, type) and hasattr(obj, "_commit_step")
    )
    source = inspect.getsource(cls._commit_step)
    assert "prev_cv = self.fields.Cv[i, j]" in source
    assert "prev_cv >= 0.5" in source
    assert "prev_cv >= 0.2" in source
    assert "self.fields.ffh[i, j] = local_h" in source
    # Classification must capture previous cv before the accepted rho overwrite.
    prev_idx = source.index("prev_cv = self.fields.Cv[i, j]")
    cv_update_idx = source.index("self.fields.Cv[i, j] = (self.fields.rho[i, j] - rho_water)")
    assert prev_idx < cv_update_idx
    # Sticky maxima use the same previous-cv branch.
    assert "self.fields.maxffh[i, j] = ti.max(self.fields.maxffh[i, j], local_h)" in source


def test_strict_edda_text_writer_uses_bed_delta_and_accepted_maxima(tmp_path):
    solver = _strict_output_solver(
        tmp_path,
        save_deposition_depth=True,
        save_total_depth=True,
        save_max_flow_depth=True,
        save_max_flow_velocity=True,
        save_max_solid_depth=True,
    )

    written = _record_strict_text_families(solver, _strict_output_state())

    np.testing.assert_allclose(written["Deposit_depth_EDDA"], np.array([[2.0, 0.0]]))
    np.testing.assert_allclose(written["Total_depth_EDDA"], np.array([[3.0, 0.0]]))
    np.testing.assert_allclose(written["Max_flow_depth_EDDA"], np.array([[2.0, 3.0]]))
    np.testing.assert_allclose(written["Max_flow_velocity_EDDA"], np.array([[4.0, 5.0]]))
    np.testing.assert_allclose(written["MaxsoliddepthEDDA"], np.array([[0.0, 0.006]]))


def test_control_free_direct_output_retains_checkpoint_max_cache_compatibility(tmp_path):
    config = SimulationConfig.from_dict(
        {"dem_file": "dummy.asc", "output_dir": str(tmp_path)}
    )
    solver = EDDASolver(config)
    solver.output_dir = tmp_path
    solver.export_metadata = {"nodata_value": -9999.0}
    solver.dfs_dynamic_wave = None
    state = _strict_output_state()
    state["h"] = np.array([[1.0], [2.0]], dtype=np.float64)
    state["Cv"] = np.array([[0.01], [0.5]], dtype=np.float64)
    state["max_flow_depth"] = np.zeros((2, 1), dtype=np.float64)
    state["max_flow_velocity"] = np.zeros((2, 1), dtype=np.float64)
    state["max_solid_depth"] = np.zeros((2, 1), dtype=np.float64)
    written = {}
    solver._write_edda_text_grid = (
        lambda stem, _t, data, _mask, _nodata: written.__setitem__(
            stem, np.asarray(data).copy()
        )
    )

    solver._export_taichi_named_edda_text_outputs(
        state=state,
        t=10.0,
        h_export=state["h"].T.copy(),
        velocity_export=np.array([[3.0, 4.0]], dtype=np.float64),
        cv_export=state["Cv"].T.copy(),
        nodata_mask=np.zeros((1, 2), dtype=np.int32),
        nodata_value=-9999.0,
    )

    np.testing.assert_allclose(written["Max_flow_depth_EDDA"], [[1.0, 2.0]])
    np.testing.assert_allclose(written["Max_flow_velocity_EDDA"], [[3.0, 4.0]])
    np.testing.assert_allclose(written["MaxsoliddepthEDDA"], [[0.01, 1.0]])


def test_strict_edda_output_schedule_is_independent_of_generic_intermediate_geotiff(tmp_path):
    solver = _strict_output_solver(tmp_path, save_flow_depth=True)
    solver.config.save_intermediate = False
    solver.fields = _RecordingFieldsWithDirectionalVelocity()
    solver.time_stepper = _TimeStepper()
    solver.results = []
    solver.output_callback = None
    written = []
    solver._write_edda_text_grid = (
        lambda stem, _t, _data, _mask, _nodata: written.append(stem)
    )

    solver._output_results()

    assert written == ["Flow_depth_EDDA"]


def _seed_outflow_observer(solver):
    solver.outflow_process_observer = {
        "output_filename": "OUTNQ_Taichi.txt",
        "cells": [{"cell_id": 7, "i": 0, "j": 0}],
        "samples": [
            {
                "time_hours": 1.0,
                "cells": [{"cell_id": 7, "discharge_cms": 2.5, "cv": 0.3}],
            }
        ],
        "max_discharge": {7: 2.5},
        "max_time_hours": {7: 1.0},
    }


def test_outnq_false_gate_creates_no_file(tmp_path):
    solver = _strict_output_solver(tmp_path, save_outflow_process=False)
    _seed_outflow_observer(solver)

    result = solver._export_outflow_process_text()

    assert result is None
    assert not (tmp_path / "OUTNQ_Taichi.txt").exists()


def test_outnq_true_gate_uses_original_three_column_format(tmp_path):
    solver = _strict_output_solver(tmp_path, save_outflow_process=True)
    _seed_outflow_observer(solver)

    result = solver._export_outflow_process_text()

    assert result == tmp_path / "OUTNQ_Taichi.txt"
    content = result.read_text(encoding="utf-8")
    assert "DISCHARGE (CMS)" in content
    assert "CV" not in content


def test_hydrograph_false_gate_creates_no_file(tmp_path):
    solver = _strict_output_solver(
        tmp_path,
        extension_controls={"save_hydrograph_cells": False},
    )
    solver.hydrograph_monitor_observer = {
        "output_filename": "HYDROGRAPHTaichi.txt",
        "cells": [{"cell_id": 7, "i": 0, "j": 0}],
        "samples": [
            {
                "time_hours": 1.0,
                "cells": [{"cell_id": 7, "discharge_cms": 2.5, "cv": 0.3}],
            }
        ],
        "max_discharge": {7: 2.5},
        "max_time_hours": {7: 1.0},
    }

    result = solver._export_hydrograph_monitor_text()

    assert result is None
    assert not (tmp_path / "HYDROGRAPHTaichi.txt").exists()


def test_pressure_head_listing_zero_gate_creates_no_file(tmp_path):
    solver = _strict_output_solver(
        tmp_path,
        pressure_head_fs_listing_flag=0,
    )

    result = solver._export_list_z_p_fs_text()

    assert result is None
    assert not (tmp_path / "list_z_p_fs_Taichi.txt").exists()


def test_pressure_head_listing_minus_one_writes_supported_normal_header(tmp_path):
    solver = _strict_output_solver(
        tmp_path,
        pressure_head_fs_listing_flag=-1,
    )

    result = solver._export_list_z_p_fs_text()

    assert result == tmp_path / "list_z_p_fs_Taichi.txt"
    assert result.read_text(encoding="utf-8").splitlines()[-1] == "Z         P         FS"


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
    assert solver.fields.include_fields is not None
    assert "h" in solver.fields.include_fields
    assert "pt" not in solver.fields.include_fields
    assert "pt" not in solver.results[0]["state"]
    assert "erosion_depth_fortran_output" in solver.results[0]["state"]


def test_output_results_exports_fortran_flow_velocity_from_directional_state(monkeypatch, tmp_path):
    exported = {}

    class _Exporter:
        def __init__(self, data, transform=None, crs=None, nodata_value=-9999.0):
            self.data = np.asarray(data)

        def to_geotiff(self, path):
            exported[Path(path).name] = self.data.copy()

        def to_ascii_grid(self, _path):
            return None

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
