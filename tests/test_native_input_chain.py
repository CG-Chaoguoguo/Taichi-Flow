"""S1 regression tests for the production native input chain."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from api.services.edda_input_mapper import (
    apply_native_runtime_inputs,
    build_reference_runtime_metadata,
    write_runtime_metadata_files,
)
from api.services.reference_config_parser import parse_reference_config_file
from edda.io.rainfall_reader import RainfallReader


def _write_ascii_grid(path: Path, values: np.ndarray, nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"ncols {values.shape[1]}\n")
        handle.write(f"nrows {values.shape[0]}\n")
        handle.write("xllcorner 0\n")
        handle.write("yllcorner 0\n")
        handle.write("cellsize 1\n")
        handle.write(f"NODATA_value {nodata}\n")
        for row in values:
            handle.write(" ".join(str(v) for v in row) + "\n")


def _make_reference_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    tutorial_dir = case_dir / "Data" / "tutorial"
    topo_dir = case_dir / "Data" / "topo"

    grid = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64)
    _write_ascii_grid(tutorial_dir / "bcdem.asc", grid)
    _write_ascii_grid(tutorial_dir / "bczone.asc", np.array([[1, 1], [1, 1]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "bcslope.asc", np.array([[20.0, 25.0], [30.0, 35.0]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "bcltstar.asc", np.array([[2.0, 2.5], [3.0, 3.5]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "manning.asc", np.array([[0.1, 0.11], [0.12, 0.13]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "directions.asc", np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "depthwt.asc", np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "rizero.asc", np.array([[1.0e-9, 1.0e-9], [1.0e-9, 1.0e-9]], dtype=np.float64))

    for topo_name in (
        "TIdscelGrid_tutorial.txt",
        "TIcelindxList_tutorial.txt",
        "TIdscelList_tutorial.txt",
        "TIwfactorList_tutorial.txt",
    ):
        (topo_dir / topo_name).parent.mkdir(parents=True, exist_ok=True)
        (topo_dir / topo_name).write_text("1 2 3\n", encoding="utf-8")

    edda_in = case_dir / "edda_in.txt"
    edda_in.write_text(
        """
imax, row, col, nwf, tx, nmax,flow-direction numbering scheme (ESRI=1, TopoIndex=2)
60578, 281, 411, 200000, 1, 10, 1
nzsb, nzst, mmax, nper,  zmin,  uww,     t(rainfall), zones
10, 10, 100, 2, 0.001, 9.8e3, 7200, 1
ltstar, lbstar, zmax,   depth,   rizero,  Min_Slope_Angle (degrees)
-1, 4, 7, 7, 1.0e-9, 0.1
cri(1), cri(2)
3.33333e-07 5.55556e-08
capt(1), capt(2)
0 3600 7200
Skip other timesteps? Enter T (.true.) or F (.false.)
F
Use analytic solution for fillable porosity?  Enter T (.true.) or F (.false.)
T
Estimate positive pressure head in rising water table zone (i.e. in lower part of unsat zone)?  Enter T (.true.) or F (.false.)
T
Use psi0=-1/alpha? Enter T (.true.) or F (.false.) (False selects the default value, psi0=0)
F
Log mass balance results?   Enter T (.true.) or F (.false.)
T
Flow direction (enter "gener", "slope", or "hydro")
slope
Add steady background flux to transient infiltration rate
T
Save grid files of runoff? Enter T (.true.) or F (.false.)
F
Save grid of minimum factor of safety? Enter Enter T (.true.) or F (.false.)
T
Save grid of depth of minimum factor of safety? Enter Enter T (.true.) or F (.false.)
F
Save grid of pore pressure at depth of minimum factor of safety? Enter Enter T (.true.) or F (.false.)
F
Save grid files of actual infiltration rate? Enter T (.true.) or F (.false.)
F
Save grid files of unsaturated zone basal flux? Enter T (.true.) or F (.false.)
F
Save grid files of the deposit distribution? Enter T (.true.) or F (.false.)
F
Save grid of probability of failure (pf) at depth of minimum factor of safety? Enter Enter T (.true.) or F (.false.)
F
Save grid of risk imposed by the slope failure to the road? Enter Enter T (.true.) or F (.false.)
F
Save grid of warning level along the road? Enter Enter T (.true.) or F (.false.)
F
Save grid of trace of the detached material and debris? Enter Enter T (.true.) or F (.false.)
F
Save listing of pressure head and factor of safety ("flag")? (Enter -2 detailed, -1 normal, 0 none)
-1
Number of times to save output grids of slope failures
1
Times of output grids
3600
File name of slope angle grid (slofil)
Data\\tutorial\\bcslope.asc
File name of dem file grid (demfil)
Data\\tutorial\\bcdem.asc
File name of manning coefficients (manningfil)
Data\\tutorial\\manning.asc
File name of direction grid (dirfil)
Data\\tutorial\\directions.asc
File name of property zone grid (zonfil)
Data\\tutorial\\bczone.asc
File name of depth grid (zfil)
Data\\tutorial\\bcltstar.asc
File name of initial depth of water table grid   (depfil)
Data\\tutorial\\depthwt.asc
File name of initial infiltration rate grid   (rizerofil)
Data\\tutorial\\rizero.asc
List of file name(s) of rainfall intensity for each period, (rifil)
Data\\tutorial\\ri1.txt
Data\\tutorial\\ri2.txt
Data\\topo\\TIdscelGrid_tutorial.txt
File name of list of defining runoff computation order (ndxfil)
Data\\topo\\TIcelindxList_tutorial.txt
File name of list of all runoff receptor cells  (dscfil)
Data\\topo\\TIdscelList_tutorial.txt
File name of list of runoff weighting factors  (wffil)
Data\\topo\\TIwfactorList_tutorial.txt
alpha1 beta1 alpha2   beta2   K     manning  limitfr  shallown
3.8 3.51 0.02 2.97 2500 0.1 1.0 0.2
d50    cvstar  coedepo  cs
0.002 0.65 0.01 0.5
dtmin(s)   dtmax(s)   dti(s)   dtd(s)   simul(s)  tout(s)   toldh(m)   toldhp  wavemax
0.00001 2.0 0.0001 0.001 7200.0 3600.0 0.1 0.05 0.25
Using the full dynamic wave equation to compute the velocity?
T
Simulte rainfall? Enter T (.true.) or F (.false.)
T
Simulte infiltration? Enter T (.true.) or F (.false.)
T
Simulate inflow hydrograph? Enter T (.true.) or F (.false.)
F
Simulate outflow cell? Enter T (.true.) or F (.false.)
T
Simulate shallow landslide? Enter T (.true.) or F (.false.)
T
Simulate debris flow? Enter T (.true.) or F (.false.)
T
Simulte erosion? Enter T (.true.) or F (.false.)
T
Simulte simulate the water and solid material seperately? Enter T (.true.) or F (.false.)
T
Save grid of minimum factor of safety? Enter T (.true.) or F (.false.)
T
Save grid of flow depth? Enter T (.true.) or F (.false.)
T
Save grid of maximum flow depth? Enter T (.true.) or F (.false.)
T
Save grid of flow velocity? Enter T (.true.) or F (.false.)
T
Save grid of maximum flow velocity? Enter T (.true.) or F (.false.)
T
Save grid of Erosion depth? Enter T (.true.) or F (.false.)
T
Save grid of deposition depth when simulating water and soil deposition seperately? Enter T (.true.) or F (.false.)
T
Save grid of total depth of flow depth and deposit depth? Enter T (.true.) or F (.false.)
F
Save grid of volumetric sediment concentration? Enter T (.true.) or F (.false.)
T
Save outflow process? Enter T (.true.) or F (.false.)
T
Save hydrograph of specified cells? Enter T (.true.) or F (.false.)
F
zone, 1
5000 0 30 0 15 0 21000 1e-6 1e-5 0.45 0.05 0.20 0.40 0.10 2.0 1e-6
4000 0 28 0 14 0 20500 2e-6 2e-5 0.43 0.04 0.18 0.38 0.09 1.8 2e-6
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    (case_dir / "outflow.txt").write_text("outflow cells\n1\n1\n", encoding="utf-8")
    (case_dir / "hydrograph.txt").write_text("hydrograph cells\n1\n2\n", encoding="utf-8")
    (case_dir / "inflow.txt").write_text(
        "\n".join(
            [
                "inflow hydrograph file",
                "1",
                "inflow period and dt",
                "3600 3600",
                "2",
                "0 1.0 0.2",
                "3600 1.5 0.25",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return edda_in


def test_reference_config_parser_reports_supported_and_recognized_only_fields(tmp_path):
    edda_in = _make_reference_case(tmp_path)

    parsed = parse_reference_config_file(str(edda_in))

    assert parsed.nzon == 1
    assert "zonfil" in parsed.supported_fields
    assert "slofil" in parsed.supported_fields
    assert "zfil" in parsed.supported_fields
    assert "manningfil" in parsed.supported_fields
    assert "dirfil" in parsed.recognized_unsupported_fields
    assert "nxtfil" in parsed.recognized_unsupported_fields
    assert parsed.file_inputs["outflow.txt"].production_status == "partial"
    assert parsed.file_inputs["hydrograph.txt"].production_status == "partial"
    assert parsed.file_inputs["inflow.txt"].production_status == "partial"
    assert parsed.file_inputs["depfil"].original_branch_active is False
    assert parsed.file_inputs["depfil"].current_backend_branch_active is False
    assert parsed.file_inputs["rizerofil"].original_branch_active is None or parsed.file_inputs["rizerofil"].original_branch_active is False
    assert parsed.file_inputs["zfil"].original_branch_active is True
    assert parsed.file_inputs["zfil"].current_backend_branch_active is True
    assert parsed.file_inputs["outflow.txt"].original_branch_active is True
    assert parsed.file_inputs["outflow.txt"].current_backend_branch_active is True
    assert parsed.file_inputs["outflow.txt"].expected_output_families == ["OUTNQ_*"]
    assert parsed.file_inputs["hydrograph.txt"].original_branch_active is False
    assert parsed.file_inputs["inflow.txt"].original_branch_active is False
    assert parsed.file_inputs["zonfil"].exists == [True]
    assert parsed.file_inputs["zonfil"].original_branch_active is False
    assert parsed.file_inputs["zonfil"].current_backend_branch_active is False
    assert parsed.file_inputs["outflow.txt"].structure_summary["declared_cell_count"] == 1
    assert parsed.file_inputs["outflow.txt"].structure_summary["grid_coords_preview"][0] == {
        "cell_id": 1,
        "col": 0,
        "row": 0,
    }
    assert parsed.file_inputs["hydrograph.txt"].structure_summary["cell_ids_preview"] == [2]
    assert parsed.file_inputs["inflow.txt"].structure_summary["declared_cell_count"] == 1
    assert parsed.file_inputs["inflow.txt"].structure_summary["expected_pulses_per_cell"] == 2
    assert parsed.file_inputs["rifil"].raw_paths == [
        "Data\\tutorial\\ri1.txt",
        "Data\\tutorial\\ri2.txt",
    ]
    assert parsed.rainfall_mode == "uniform_cri"
    assert parsed.rainfall_period_sources[0]["source"] == "uniform_cri"
    assert parsed.period_source_map["1"]["source"] == "uniform_cri"
    assert parsed.flags["simulate_outflow_cell"] is True
    assert parsed.flags["use_analytic_fillable_porosity"] is True
    assert parsed.flags["estimate_positive_pressure_head"] is True
    assert parsed.flags["use_psi0_negative_inverse_alpha"] is False
    assert parsed.flags["log_mass_balance_results"] is True
    assert parsed.flags["flow_direction_mode"] == "slope"
    assert parsed.flags["simulate_rainfall"] is True
    assert parsed.flags["simulate_infiltration"] is True
    assert parsed.dfs_infiltration_variant == "tol_clipped_fhw"
    assert parsed.dfs_face_flux_variant == "asymmetric_head_guard"


def test_reference_runtime_preserves_parsed_output_interval(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))

    config, effective_config, _, _ = build_reference_runtime_metadata(parsed, tmp_path / "out_parsed_tout")

    assert parsed.tout == 3600.0
    assert config.time.dt_output == 3600.0
    assert effective_config["config"]["time"]["dt_output"] == 3600.0


def test_reference_config_parser_detects_direct_rain_plus_storage_dfs_variant(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "      if (infilsimul) then",
                "      do i=1,imx1",
                "          fhw(i)=fh(i)*(1-cv(i)/cvstar)",
                "          inflx(i)=tempri(i) +(tempinflowh(i)+fhw(i))/dt",
                "      end do",
                "      end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_reference_config_file(str(edda_in))
    _, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(parsed, tmp_path / "out_variant")

    assert parsed.dfs_infiltration_variant == "direct_rain_plus_storage"
    assert parsed.dfs_infiltration_variant_source.endswith("dfs.F90")
    assert "keeps rainfall forcing active" in (parsed.dfs_infiltration_variant_basis or "")
    assert effective_config["config"]["hydrology"]["dfs_infiltration_variant"] == "direct_rain_plus_storage"
    assert runtime_input_manifest["input_source_registry"]["dfs_infiltration_variant"]["selected_source"] == "direct_rain_plus_storage"
    assert provenance["reference_config_audit"]["dfs_infiltration_variant"] == "direct_rain_plus_storage"
    assert parsed.flags["simulate_debris_flow"] is True
    assert parsed.flags["simulate_erosion"] is True
    assert parsed.flags["simulate_water_and_solid_separately"] is True
    assert parsed.flags["pressure_head_fs_listing_flag"] == -1
    assert parsed.flags["slope_failure_output_count"] == 1
    assert parsed.flags["slope_failure_output_times_s"] == [3600.0]
    assert parsed.ltstar_raw < 0
    assert parsed.zmax == 7.0
    unsupported_flags = {entry["flag"]: entry for entry in parsed.unsupported_flags}
    assert unsupported_flags["use_analytic_fillable_porosity"]["current_status"] == "parsed_only"
    assert unsupported_flags["flow_direction_mode"]["current_status"] == "parsed_only"
    assert "simulate_rainfall" not in unsupported_flags
    assert unsupported_flags["save_runoff_grids"]["current_status"] == "unsupported"
    assert "OUTNQ_*" in parsed.reference_output_expectations["expected_output_families"]
    assert "Flow_depth_*" in parsed.reference_output_expectations["expected_output_families"]
    assert parsed.reference_output_expectations["output_timing"]["Flow_depth_*"] == "periodic_output"
    assert parsed.reference_output_expectations["output_timing"]["OUTNQ_*"] == "end_of_run_only"


def test_reference_config_parser_detects_both_thin_weighted_face_flux_variant(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        if (fhpredi(i)<=tol .and. fhpredi(nq)<=tol) then",
                "        fvpredi(i,ii)=0.",
                "        end if",
                "        hbar=(fhpredi(i) * cellareacal(i) +fhpredi(nq) * cellareacal(nq)) / (cellareacal(i)+cellareacal(nq))",
                "        cvbar=(parai* cellareacal(i)+paran* cellareacal(nq)) / (fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))",
                "        frhobar=(frhopredi(i)*fhpredi(i)* cellareacal(i)+frhopredi(nq)*fhpredi(nq)* cellareacal(nq))/ (fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_reference_config_file(str(edda_in))
    _, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(parsed, tmp_path / "out_face_variant")

    assert parsed.dfs_face_flux_variant == "both_thin_weighted"
    assert parsed.dfs_face_flux_variant_source.endswith("dfs.F90")
    assert "cellareacal`-weighted" in (parsed.dfs_face_flux_variant_basis or "")
    assert effective_config["config"]["hydrology"]["dfs_face_flux_variant"] == "both_thin_weighted"
    assert runtime_input_manifest["input_source_registry"]["dfs_face_flux_variant"]["selected_source"] == "both_thin_weighted"
    assert provenance["reference_config_audit"]["dfs_face_flux_variant"] == "both_thin_weighted"


def test_reference_config_parser_detects_precomputed_unsfin_failure_source_variant(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        !if (fssimul) then",
                "        !    if (tnow<60.) tnow=60.",
                "        !    call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)",
                "        !end if",
                "        if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
                "            tempfsh(i)=fsdepth(i)",
                "            tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
                "        end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (edda_in.parent / "edda main program.F90").write_text(
        "if (fssimul) call unsfin(imx1,u(19),u(2),profil)\n",
        encoding="utf-8",
    )

    parsed = parse_reference_config_file(str(edda_in))
    _, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(parsed, tmp_path / "out_failure_variant")

    assert parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule"
    assert parsed.dfs_failure_source_variant_source.endswith("dfs.F90")
    assert "precomputed `tfail`" in (parsed.dfs_failure_source_variant_basis or "")
    assert effective_config["config"]["hydrology"]["dfs_failure_source_variant"] == "precomputed_unsfin_schedule"
    assert runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]["selected_source"] == "precomputed_unsfin_schedule"
    assert runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]["runtime_equivalent_implemented"] is False
    assert runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]["runtime_active"] is False
    assert provenance["reference_config_audit"]["dfs_failure_source_variant"] == "precomputed_unsfin_schedule"


def test_reference_config_parser_accepts_run_mode_label_variants(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    text = text.replace(
        "Simulte rainfall? Enter T (.true.) or F (.false.)",
        "Simulate rainfall? Enter T (.true.) or F (.false.)",
    )
    text = text.replace(
        "Simulte infiltration? Enter T (.true.) or F (.false.)",
        "Simulate infiltration? Enter T (.true.) or F (.false.)",
    )
    text = text.replace(
        "Simulte erosion? Enter T (.true.) or F (.false.)",
        "Simulate erosion? Enter T (.true.) or F (.false.)",
    )
    text = text.replace(
        "Simulte simulate the water and solid material seperately? Enter T (.true.) or F (.false.)",
        "Simulate simulate the water and solid material seperately? Enter T (.true.) or F (.false.)",
    )
    edda_in.write_text(text, encoding="utf-8")

    parsed = parse_reference_config_file(str(edda_in))

    assert parsed.flags["simulate_rainfall"] is True
    assert parsed.flags["simulate_infiltration"] is True
    assert parsed.flags["simulate_erosion"] is True
    assert parsed.flags["simulate_water_and_solid_separately"] is True


class _FakeBuffer:
    def __init__(self):
        self.value = None

    def from_numpy(self, value):
        self.value = np.array(value)


class _FakeFields:
    def __init__(self):
        self.nx = 2
        self.ny = 2
        self.slope_mag = _FakeBuffer()
        self.slope_angle = _FakeBuffer()
        self.n_manning_field = _FakeBuffer()
        self.ltstar_field = _FakeBuffer()


class _FakeRheology:
    def __init__(self):
        self.manning = _FakeBuffer()
        self.manning_ori = _FakeBuffer()


class _FakeDoubleLayer:
    def __init__(self):
        self.initialized_with = None

    def build_initial_rikzero_field(self, rizero_rate: float):
        if np.isscalar(rizero_rate):
            return np.full((2, 2), rizero_rate, dtype=np.float64)
        return np.array(rizero_rate, dtype=np.float64)

    def initialize_double_layer(self, rikzero: np.ndarray):
        self.initialized_with = np.array(rikzero)


class _FakeDFS:
    def __init__(self):
        self.rikzero = None
        self.depthwt = None
        self.rizero = None

    def set_initial_rikzero_field(self, rikzero: np.ndarray):
        self.rikzero = np.array(rikzero)

    def set_initial_depthwt_field(self, depthwt: np.ndarray | None):
        self.depthwt = None if depthwt is None else np.array(depthwt)

    def set_initial_rizero_field(self, rizero: np.ndarray | None):
        self.rizero = None if rizero is None else np.array(rizero)


class _FakeSolver:
    def __init__(self):
        self.fields = _FakeFields()
        self.numpy_float_dtype = np.float64
        self.rheology = _FakeRheology()
        self.double_layer = _FakeDoubleLayer()
        self.dfs_dynamic_wave = _FakeDFS()
        self.rainfall_reader = object()
        self.outflow_observer = None
        self.inflow_forcing = None
        self.stormdrain_hook = None
        self.config = SimpleNamespace(
            rheology=SimpleNamespace(n_manning=0.1),
            hydrology=SimpleNamespace(rizero_initial=1.0e-9, depthwt_initial=7.0),
            soil=SimpleNamespace(double_layer=SimpleNamespace(ltstar=3.0)),
            spatial_zones=SimpleNamespace(zone_file="dummy-zone.asc"),
        )

    def configure_outflow_process_observer(self, cell_ids, sidecar_path=None, output_filename="OUTNQ_EDDA_TAICHI.txt"):
        self.outflow_observer = {
            "cell_ids": list(cell_ids),
            "sidecar_path": sidecar_path,
            "output_filename": output_filename,
        }
        return {
            "configured_cell_count": len(cell_ids),
            "missing_cell_ids": [],
            "output_filename": output_filename,
        }

    def configure_inflow_hydrograph_forcing(
        self,
        hydrographs,
        sidecar_path=None,
        denominator_variant=None,
        denominator_source=None,
        denominator_basis=None,
        denominator_direction=None,
        denominator_fv_value=None,
    ):
        self.inflow_forcing = {
            "hydrographs": list(hydrographs),
            "sidecar_path": sidecar_path,
            "denominator_variant": denominator_variant,
            "denominator_source": denominator_source,
            "denominator_basis": denominator_basis,
            "denominator_direction": denominator_direction,
            "denominator_fv_value": denominator_fv_value,
        }
        return {
            "configured_cell_count": len(hydrographs),
            "missing_cell_ids": [],
            "configured_preview": [{"cell_id": block["cell_id"]} for block in hydrographs[:10]],
            "inflow_denominator_variant": denominator_variant,
            "inflow_denominator_source": denominator_source,
            "inflow_denominator_direction": denominator_direction,
            "inflow_denominator_fv_value": denominator_fv_value,
        }

    def configure_stormdrain_runtime_hook(
        self,
        drainage_path,
        expected_node_count=None,
        expected_conduit_count=None,
    ):
        self.stormdrain_hook = {
            "drainage_path": drainage_path,
            "expected_node_count": expected_node_count,
            "expected_conduit_count": expected_conduit_count,
        }
        return {
            "stormdrain_runtime_enabled": True,
            "stormdrain_branch_active": False,
            "stormdrain_available": Path(drainage_path).exists() if drainage_path else False,
            "changed_field_names": [],
            "active_cell_count": 4,
            "imax": 4,
        }


def test_reference_mapping_builds_manifest_and_applies_priority_native_loaders(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))

    config, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )

    solver = _FakeSolver()
    solver.config.spatial_zones = config.spatial_zones
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)

    assert config.dem_file.endswith("bcdem.asc")
    assert config.spatial_zones is not None
    assert config.spatial_zones.enabled is False
    assert config.spatial_zones.zone_file is None
    assert config.native_inputs is not None
    assert (tmp_path / "output" / "_generated_inputs" / "rainfall_from_edda_in.csv").exists()
    assert solver.fields.slope_angle.value.shape == (2, 2)
    assert solver.fields.n_manning_field.value.shape == (2, 2)
    assert solver.fields.ltstar_field.value.shape == (2, 2)
    assert solver.double_layer.initialized_with is not None
    assert provenance["helper_fallback_used"] is False
    consumed = {entry["family"]: entry["consumed"] for entry in runtime_input_manifest["inputs"]}
    statuses = {entry["family"]: entry["production_status"] for entry in runtime_input_manifest["inputs"]}
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    source_registry = runtime_input_manifest["input_source_registry"]
    assert consumed["zonfil"] is False
    assert consumed["slofil"] is True
    assert consumed["manningfil"] is True
    assert consumed["zfil"] is True
    assert consumed["rifil"] is False
    assert consumed["dirfil"] is False
    assert consumed["depfil"] is False
    assert consumed["rizerofil"] is False
    assert manifest["depfil"]["input_state"] == "config_fallback"
    assert manifest["rizerofil"]["input_state"] == "config_fallback"
    assert manifest["manningfil"]["input_state"] == "file_backed"
    assert manifest["rifil"]["input_state"] == "config_fallback"
    assert manifest["outflow.txt"]["input_state"] == "file_backed"
    assert manifest["depfil"]["resolved_via_fallback"] is True
    assert manifest["depfil"]["effective_runtime_source"] == "config_depth"
    assert manifest["depfil"]["effective_runtime_source_active"] is True
    assert manifest["rizerofil"]["resolved_via_fallback"] is True
    assert manifest["rizerofil"]["effective_runtime_source"] == "config_rizero"
    assert manifest["rizerofil"]["effective_runtime_source_active"] is True
    assert manifest["manningfil"]["resolved_via_fallback"] is False
    assert manifest["manningfil"]["effective_runtime_source"] == "raster_manningfil"
    assert manifest["manningfil"]["effective_runtime_source_active"] is True
    assert manifest["rifil"]["resolved_via_fallback"] is True
    assert manifest["rifil"]["effective_runtime_source"] == "uniform_cri"
    assert manifest["rifil"]["effective_runtime_source_active"] is True
    assert manifest["outflow.txt"]["resolved_via_fallback"] is False
    assert manifest["outflow.txt"]["effective_runtime_source"] == "outflow_txt"
    assert manifest["outflow.txt"]["effective_runtime_source_active"] is True
    assert statuses["rifil"] == "recognized-only"
    assert statuses["zfil"] == "partial"
    assert statuses["dirfil"] == "recognized-only"
    assert statuses["nxtfil"] == "recognized-only"
    assert statuses["outflow.txt"] == "partial"
    assert statuses["hydrograph.txt"] == "partial"
    assert statuses["inflow.txt"] == "partial"
    assert manifest["depfil"]["original_branch_active"] is False
    assert manifest["depfil"]["current_backend_branch_active"] is False
    assert manifest["rizerofil"]["original_branch_active"] is False
    assert manifest["rizerofil"]["current_backend_branch_active"] is False
    assert manifest["zfil"]["original_branch_active"] is True
    assert manifest["zfil"]["current_backend_branch_active"] is True
    assert manifest["outflow.txt"]["original_branch_active"] is True
    assert manifest["outflow.txt"]["current_backend_branch_active"] is True
    assert manifest["outflow.txt"]["expected_output_families"] == ["OUTNQ_*"]
    assert manifest["hydrograph.txt"]["original_branch_active"] is False
    assert manifest["inflow.txt"]["original_branch_active"] is False
    assert manifest["inflow.txt"]["current_backend_branch_active"] is False
    assert "ltstar" in manifest["zfil"]["status_basis"]
    assert "groundwater-depth" in manifest["depfil"]["blocked_reason"] or "water-table" in manifest["depfil"]["blocked_reason"]
    assert "rizero < 0" in manifest["rizerofil"]["blocked_reason"] or "infiltration-rate" in manifest["rizerofil"]["blocked_reason"]
    assert manifest["outflow.txt"]["structure_summary"]["declared_cell_count"] == 1
    assert manifest["hydrograph.txt"]["structure_summary"]["cell_ids_preview"] == [2]
    assert manifest["inflow.txt"]["structure_summary"]["parsed_block_count"] == 1
    assert effective_config["source_mode"] == "reference_config"
    assert effective_config["reference_config_effective_sources"]["rainfall"] == "uniform_cri"
    assert effective_config["reference_config_effective_sources"]["manning"] == "raster_manningfil"
    assert effective_config["input_source_registry"]["water_table_source"]["selected_source"] == "config_depth"
    assert effective_config["input_source_registry"]["initial_infiltration_source"]["selected_source"] == "config_rizero"
    assert effective_config["input_source_registry"]["manning_source"]["selected_source"] == "raster_manningfil"
    assert effective_config["input_source_registry"]["rainfall_source"]["selected_source"] == "uniform_cri"
    assert effective_config["input_source_registry"]["outflow_point_source"]["selected_source"] == "outflow_txt"
    assert effective_config["input_source_registry"]["inflow_source"]["selected_source"] == "inflow_txt"
    assert effective_config["input_source_registry"]["inflow_source"]["runtime_active"] is False
    assert effective_config["reference_case_activation"]["outflow.txt"]["original_branch_active"] is True
    assert effective_config["reference_case_activation"]["depfil"]["input_state"] == "config_fallback"
    assert effective_config["reference_case_activation"]["zfil"]["current_backend_branch_active"] is True
    assert "OUTNQ_*" in effective_config["reference_output_expectations"]["expected_output_families"]
    assert effective_config["reference_output_expectations"]["output_timing"]["OUTNQ_*"] == "end_of_run_only"
    assert effective_config["sidecar_output_parity"]["outflow.txt"]["parity_status"] == "partial"
    assert effective_config["sidecar_output_parity"]["outflow.txt"]["declared_cell_count"] == 1
    assert effective_config["sidecar_output_parity"]["EDDALog.txt"]["parity_status"] == "metadata_only"
    assert runtime_input_manifest["period_source_map"]["1"]["source"] == "uniform_cri"
    assert source_registry["water_table_source"]["state"] == "config_fallback"
    assert source_registry["initial_infiltration_source"]["state"] == "config_fallback"
    assert source_registry["manning_source"]["state"] == "file_backed"
    assert source_registry["rainfall_source"]["state"] == "config_fallback"
    assert source_registry["outflow_point_source"]["selected_source"] == "outflow_txt"
    assert source_registry["inflow_source"]["selected_source"] == "inflow_txt"
    assert source_registry["inflow_source"]["runtime_active"] is False
    assert runtime_input_manifest["reference_case_activation"]["depfil"]["original_branch_active"] is False
    assert "OUTNQ_*" in runtime_input_manifest["reference_output_expectations"]["expected_output_families"]
    assert runtime_input_manifest["sidecar_output_parity"]["outflow.txt"]["parity_status"] == "partial"
    assert runtime_input_manifest["sidecar_output_parity"]["outflow.txt"]["declared_cell_count"] == 1
    assert effective_config["reference_config_sidecars"]["inflow.txt"]["declared_cell_count"] == 1
    assert "zfil" in effective_config["reference_config_semantic_alerts"]
    assert "OUTNQ_*" in provenance["reference_output_expectations"]["expected_output_families"]
    assert provenance["sidecar_output_parity"]["outflow.txt"]["parity_status"] == "partial"
    assert provenance["sidecar_output_parity"]["EDDALog.txt"]["parity_status"] == "metadata_only"
    assert provenance["input_source_registry"]["manning_source"]["selected_source"] == "raster_manningfil"
    assert provenance["input_source_registry"]["inflow_source"]["selected_source"] == "inflow_txt"


def test_reference_mapping_uses_global_manning_when_declared_grid_is_missing(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "Data" / "tutorial" / "manning.asc").unlink()
    parsed = parse_reference_config_file(str(edda_in))

    assert parsed.manning_source == "global_initiation_manning"

    _, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )
    runtime_input_manifest = apply_native_runtime_inputs(_FakeSolver(), runtime_input_manifest)

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["manningfil"]["consumed"] is False
    assert manifest["manningfil"]["default_substitution_used"] is True
    assert manifest["manningfil"]["input_state"] == "config_fallback"
    assert manifest["manningfil"]["resolved_via_fallback"] is True
    assert manifest["manningfil"]["effective_runtime_source"] == "global_manning"
    assert manifest["manningfil"]["effective_runtime_source_active"] is True
    assert manifest["manning_global"]["consumed"] is True
    assert runtime_input_manifest["input_source_registry"]["manning_source"]["selected_source"] == "global_manning"


def test_reference_mapping_consumes_depfil_and_rizerofil_when_original_branches_are_active(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace("-1, 4, 7, 7, 1.0e-9, 0.1", "-1, 4, 7, -1, -1, 0.1"),
        encoding="utf-8",
    )

    parsed = parse_reference_config_file(str(edda_in))
    _, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output_dep_rizero",
    )

    solver = _FakeSolver()
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}

    expected_depth = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float64).T
    expected_rizero = np.array([[1.0e-9, 1.0e-9], [1.0e-9, 1.0e-9]], dtype=np.float64).T

    assert parsed.file_inputs["depfil"].original_branch_active is True
    assert parsed.file_inputs["rizerofil"].original_branch_active is True
    assert runtime_input_manifest["input_source_registry"]["water_table_source"]["state"] == "file_backed"
    assert runtime_input_manifest["input_source_registry"]["initial_infiltration_source"]["state"] == "file_backed"
    assert manifest["depfil"]["consumed"] is True
    assert manifest["rizerofil"]["consumed"] is True
    assert manifest["depfil"]["input_state"] == "file_backed"
    assert manifest["rizerofil"]["input_state"] == "file_backed"
    assert manifest["depfil"]["resolved_via_fallback"] is False
    assert manifest["depfil"]["effective_runtime_source"] == "depfil"
    assert manifest["depfil"]["effective_runtime_source_active"] is True
    assert manifest["rizerofil"]["resolved_via_fallback"] is False
    assert manifest["rizerofil"]["effective_runtime_source"] == "rizerofil"
    assert manifest["rizerofil"]["effective_runtime_source_active"] is True


def test_write_runtime_metadata_files_persists_input_source_registry(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))
    _, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "out_metadata",
    )

    write_runtime_metadata_files(
        tmp_path / "out_metadata",
        effective_config,
        runtime_input_manifest,
        provenance,
    )

    registry_file = tmp_path / "out_metadata" / "input_source_registry.json"
    assert registry_file.exists()
    stored = json.loads(registry_file.read_text(encoding="utf-8"))
    assert stored["water_table_source"]["selected_source"] == "config_depth"
    assert stored["initial_infiltration_source"]["selected_source"] == "config_rizero"
    assert stored["manning_source"]["selected_source"] == "raster_manningfil"
    assert stored["rainfall_source"]["selected_source"] == "uniform_cri"
    assert stored["outflow_point_source"]["selected_source"] == "outflow_txt"
    assert stored["inflow_source"]["selected_source"] == "inflow_txt"


def test_reference_mapping_enables_outflow_sidecar_runtime_observer(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))
    _, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output_outflow",
    )

    solver = _FakeSolver()
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}

    assert manifest["outflow.txt"]["consumed"] is True
    assert manifest["outflow.txt"]["runtime_stage"] == "post_initialize.outflow_sidecar_loader"
    assert runtime_input_manifest["sidecar_output_parity"]["outflow.txt"]["parity_status"] == "partial"
    assert solver.outflow_observer is not None
    assert solver.outflow_observer["cell_ids"] == [1]
    assert solver.outflow_observer["output_filename"].startswith("OUTNQ_")


def test_reference_mapping_configures_stormdrain_hook_only_when_flagged(tmp_path, monkeypatch):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    text = text.replace(
        "Simulte simulate the water and solid material seperately? Enter T (.true.) or F (.false.)\nT\nSave grid of minimum factor of safety?",
        "Simulte simulate the water and solid material seperately? Enter T (.true.) or F (.false.)\n"
        "T\nSimulte drainage flow? Enter T (.true.) or F (.false.)\nT\nSave grid of minimum factor of safety?",
    )
    text = text.replace(
        "Save outflow process? Enter T (.true.) or F (.false.)\nT\nSave hydrograph of specified cells?",
        "Save outflow process? Enter T (.true.) or F (.false.)\n"
        "T\nSave drainage nodal flow? Enter T (.true.) or F (.false.)\n"
        "T\nSave drainage conduit flow? Enter T (.true.) or F (.false.)\n"
        "T\nSave hydrograph of specified cells?",
    )
    edda_in.write_text(text, encoding="utf-8")
    (edda_in.parent / "drainage.txt").write_text(
        "\n".join(
            [
                " drainage information for EDDA 2.0",
                " number of nodes:",
                " 2",
                " node name ,  index,   type,   invertEl,       maxdepth",
                " j1 1 0 0.0 1.0",
                " o1 2 1 0.0 0.0",
                " number of conduits:",
                " 1",
                "conduit name, inletno,   outletno,   length,    manningN,  xsecshp,   geom1,   geom2",
                " c1 1 2 10.0 0.01 1 1.0 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (edda_in.parent / "swmm.txt").write_text("[TITLE]\nfixture\n", encoding="utf-8")

    monkeypatch.setenv("EDDA_EXPERIMENT_STORMDRAIN", "1")
    parsed = parse_reference_config_file(str(edda_in))
    _, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output_stormdrain",
    )

    solver = _FakeSolver()
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}

    assert parsed.flags["simulate_drainage_flow"] is True
    assert parsed.flags["save_drainage_nodal_flow"] is True
    assert manifest["drainage.txt"]["consumed"] is True
    assert manifest["drainage.txt"]["runtime_stage"] == "post_initialize.stormdrain_runtime_hook"
    assert manifest["drainage.txt"]["current_backend_branch_active"] is True
    assert runtime_input_manifest["stormdrain_runtime_hook"]["stormdrain_runtime_enabled"] is True
    assert solver.stormdrain_hook["drainage_path"].endswith("drainage.txt")


def test_reference_mapping_converts_cri_negative_rifil_to_spatial_rainfall(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    tutorial_dir = edda_in.parent / "Data" / "tutorial"
    _write_ascii_grid(tutorial_dir / "ri1.txt", np.array([[1.0e-6, 2.0e-6], [3.0e-6, 4.0e-6]], dtype=np.float64))
    _write_ascii_grid(tutorial_dir / "ri2.txt", np.array([[5.0e-7, 5.0e-7], [5.0e-7, 5.0e-7]], dtype=np.float64))
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(text.replace("3.33333e-07 5.55556e-08", "-1 5.55556e-08"), encoding="utf-8")

    parsed = parse_reference_config_file(str(edda_in))
    config, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output_spatial",
    )

    assert parsed.rainfall_mode == "mixed"
    assert parsed.rainfall_period_sources[0]["source"] == "rifil_grid"
    assert parsed.period_source_map["1"]["source"] == "rifil_grid"
    assert parsed.period_source_map["2"]["source"] == "uniform_cri"
    assert config.rainfall.mode == "spatial_tif_series"
    assert config.rainfall.interval_bounds_s == [0.0, 3600.0, 7200.0]
    assert Path(config.rainfall.directory).exists()
    assert len(list(Path(config.rainfall.directory).glob("period_*.tif"))) == 2

    reader = RainfallReader(config.rainfall.directory)
    reader.read_spatial_rainfall(
        config.rainfall.directory,
        file_pattern=config.rainfall.file_pattern,
        interval_bounds_s=config.rainfall.interval_bounds_s,
    )
    rain_first = reader.get_spatial_interval_average_rainfall(0.0, 3600.0)
    np.testing.assert_allclose(rain_first, np.array([[1.0e-6, 2.0e-6], [3.0e-6, 4.0e-6]]), rtol=1e-12, atol=1e-12)

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["rifil"]["production_status"] == "production-reachable"
    assert manifest["rainfall_spatial_series"]["production_status"] == "production-reachable"
    assert effective_config["reference_config_effective_sources"]["rainfall"] == "mixed"
    assert effective_config["reference_config_effective_sources"]["period_source_map"]["1"]["source"] == "rifil_grid"
    assert provenance["rainfall_audit"]["active_source"] == "mixed"
    assert "rainfall_schedule" not in manifest


def test_reference_mapping_requires_rifil_when_cri_is_negative(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(text.replace("3.33333e-07 5.55556e-08", "-1 5.55556e-08"), encoding="utf-8")

    parsed = parse_reference_config_file(str(edda_in))

    with pytest.raises(FileNotFoundError, match="requires rainfall raster"):
        build_reference_runtime_metadata(
            parsed,
            tmp_path / "output_missing_rifil",
        )
