from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MATRIX = ROOT / "PROJECT_REPORTS" / "BACKEND_ALIGNMENT_AUDITS" / "parameter_role_matrix.csv"
OUTPUT_DIR = ROOT / "PROJECT_REPORTS" / "PARAMETER_PROVENANCE"
FORTRAN_TRACE_DIR = OUTPUT_DIR / "fortran_trace"
TAICHI_TRACE_DIR = OUTPUT_DIR / "taichi_trace"
TODAY = date.today().isoformat()

CSV_COLUMNS = [
    "parameter_family",
    "edda_input_source",
    "fortran_reader",
    "fortran_runtime_consumer",
    "branch_condition",
    "physical_module",
    "taichi_config_field",
    "service_mapper",
    "solver_consumer",
    "runtime_evidence",
    "case_coverage",
    "output_families_affected",
    "status",
    "allowed_for_calibration",
]


@dataclass(frozen=True)
class SourceCase:
    entire: str
    no8: str
    test31: str
    note: str = ""

    def coverage_text(self) -> str:
        return (
            f"EntireBanzigou1005::{self.entire} || "
            f"NO.8_AYG_V2::{self.no8} || "
            f"Test31::{self.test31}"
        )


def load_source_matrix() -> dict[str, dict[str, str]]:
    with SOURCE_MATRIX.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {row["original_parameter"]: row for row in rows}


SOURCE_ROWS = load_source_matrix()


def require_source(key: str) -> dict[str, str]:
    if key not in SOURCE_ROWS:
        raise KeyError(f"Missing source matrix row: {key}")
    return SOURCE_ROWS[key]


def matrix_entry(
    matrix_key: str,
    *,
    parameter_family: str | None = None,
    edda_input_source: str,
    fortran_reader: str,
    fortran_runtime_consumer: str,
    branch_condition: str,
    physical_module: str,
    service_mapper: str,
    solver_consumer: str | None = None,
    runtime_evidence: str,
    cases: SourceCase,
    output_families_affected: str,
    status: str,
    allowed_for_calibration: str,
    status_note: str,
) -> dict[str, Any]:
    row = require_source(matrix_key)
    return {
        "parameter_family": parameter_family or row["original_parameter"],
        "edda_input_source": edda_input_source,
        "fortran_reader": fortran_reader,
        "fortran_runtime_consumer": fortran_runtime_consumer,
        "branch_condition": branch_condition,
        "physical_module": physical_module,
        "taichi_config_field": row["current_system_mapping_field"],
        "service_mapper": service_mapper,
        "solver_consumer": solver_consumer or row["current_runtime_consumption"],
        "runtime_evidence": runtime_evidence,
        "case_coverage": cases.coverage_text(),
        "output_families_affected": output_families_affected,
        "status": status,
        "allowed_for_calibration": allowed_for_calibration,
        "_status_note": status_note,
        "_case_note": cases.note,
    }


def manual_entry(
    *,
    parameter_family: str,
    edda_input_source: str,
    fortran_reader: str,
    fortran_runtime_consumer: str,
    branch_condition: str,
    physical_module: str,
    taichi_config_field: str,
    service_mapper: str,
    solver_consumer: str,
    runtime_evidence: str,
    cases: SourceCase,
    output_families_affected: str,
    status: str,
    allowed_for_calibration: str,
    status_note: str,
) -> dict[str, Any]:
    return {
        "parameter_family": parameter_family,
        "edda_input_source": edda_input_source,
        "fortran_reader": fortran_reader,
        "fortran_runtime_consumer": fortran_runtime_consumer,
        "branch_condition": branch_condition,
        "physical_module": physical_module,
        "taichi_config_field": taichi_config_field,
        "service_mapper": service_mapper,
        "solver_consumer": solver_consumer,
        "runtime_evidence": runtime_evidence,
        "case_coverage": cases.coverage_text(),
        "output_families_affected": output_families_affected,
        "status": status,
        "allowed_for_calibration": allowed_for_calibration,
        "_status_note": status_note,
        "_case_note": cases.note,
    }


ENTIRE_ONLY_PROVENANCE = SourceCase(
    entire="read-only provenance in real-case trace",
    no8="not covered in the 2026-04-24 multicase audit",
    test31="not covered in the 2026-04-24 multicase audit",
    note="These families are recorded mainly from the EntireBanzigou source-trace baseline.",
)

REGISTRY_ENTRIES: list[dict[str, Any]] = []

REGISTRY_ENTRIES.extend(
    [
        matrix_entry(
            "simul",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 / wfs.F90 stop-time horizon",
            branch_condition="always active when parsed",
            physical_module="time control",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="All grid outputs; OUTNQ_* timing; HYDROGRAPH_* timing",
            status="closed",
            allowed_for_calibration="no",
            status_note="Runtime stop condition is closed, but this is a schedule control, not a science calibration variable.",
        ),
        matrix_entry(
            "tout",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 / wfs.F90 output cadence",
            branch_condition="always active when parsed",
            physical_module="time control",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="All exported result families; OUTNQ_* timing; HYDROGRAPH_* timing",
            status="closed",
            allowed_for_calibration="no",
            status_note="Closed as an export cadence control only.",
        ),
        matrix_entry(
            "dtmin",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 accepted/rejected-step bounds",
            branch_condition="always active when parsed",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Indirectly all time-resolved outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Numerical stability control, not a science tuning variable.",
        ),
        matrix_entry(
            "dtmax",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 accepted-step growth bounds",
            branch_condition="always active when parsed",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Indirectly all time-resolved outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Numerical stability control, not a science tuning variable.",
        ),
        matrix_entry(
            "dti",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 accepted-step increment rule",
            branch_condition="always active when parsed",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Indirectly all time-resolved outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Numerical step-growth control only.",
        ),
        matrix_entry(
            "dtd",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 rejected-step decrement rule",
            branch_condition="always active when parsed",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Indirectly all time-resolved outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Numerical retry control only.",
        ),
        matrix_entry(
            "toldh",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 depth-change rejection test",
            branch_condition="always active when parsed",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Indirectly all time-resolved outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Numerical rejection gate only.",
        ),
        matrix_entry(
            "toldhp",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="dfs.F90 relative depth-change rejection test",
            branch_condition="always active when parsed",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Indirectly all time-resolved outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Numerical rejection gate only.",
        ),
        matrix_entry(
            "wavemax",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 time-control block",
            fortran_runtime_consumer="wfs.F90 full dynamic-wave stability limiter",
            branch_condition="would matter only if the original full dynamic-wave branch is honored",
            physical_module="solver stability",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; edda/config/sim_config.py",
            cases=SourceCase("parsed, mapped, not consumed", "parsed, mapped, not consumed", "parsed, mapped, not consumed"),
            output_families_affected="Would affect all time-resolved flow outputs if runtime closure existed",
            status="blocked",
            allowed_for_calibration="no",
            status_note="Mapped into config only; no closed Taichi runtime consumer is audited.",
        ),
        matrix_entry(
            "depth",
            parameter_family="depth/depfil",
            edda_input_source="edda_in.txt scalar with optional depfil raster fallback",
            fortran_reader="trini.f90 dep / depfil branch",
            fortran_runtime_consumer="infr.F90 exfiltration edge case; original groundwater initialization path",
            branch_condition="depth >= 0 uses scalar depth; depth < 0 activates depfil raster",
            physical_module="hydrology / initialization",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; tests/test_native_runtime_consumption.py::test_real_solver_consumes_depfil_and_rizerofil_when_original_branches_are_active; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md",
            cases=SourceCase(
                "config_fallback depth=7",
                "config_fallback depth=7",
                "config_fallback depth=7",
                note="No shipped case activates depfil; the raster branch is covered only by dedicated runtime tests.",
            ),
            output_families_affected="Flow_depth; Flow_velocity_*; Max_flow_depth; Total_depth; FS_min_*; OUTNQ_*",
            status="partial",
            allowed_for_calibration="no",
            status_note="Current backend compresses water-table default and soil-depth semantics; depfil branch exists, but the family is not yet semantically clean enough for calibration.",
        ),
        matrix_entry(
            "rizero",
            parameter_family="rizero/rizerofil",
            edda_input_source="edda_in.txt scalar with optional rizerofil raster fallback",
            fortran_reader="trini.f90 crizero / rizerofil branch",
            fortran_runtime_consumer="steady.f90; infr.F90; inidoublelayer.F90; doublelayer.F90",
            branch_condition="rizero >= 0 uses scalar fallback; rizero < 0 activates rizerofil raster",
            physical_module="hydrology / infiltration",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; tests/test_native_runtime_consumption.py::test_real_solver_consumes_depfil_and_rizerofil_when_original_branches_are_active; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md",
            cases=SourceCase(
                "config_fallback rizero=1.0e-9",
                "config_fallback rizero=1.0e-9",
                "config_fallback rizero=1.0e-9",
                note="No shipped case activates rizerofil; the raster branch is exercised in dedicated runtime tests.",
            ),
            output_families_affected="Flow_depth; Flow_velocity_*; Max_flow_depth; Total_depth; FS_min_*",
            status="partial",
            allowed_for_calibration="no",
            status_note="Scalar fallback is closed, but the combined family still lacks multicase file-backed evidence.",
        ),
        matrix_entry(
            "uww",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 double-layer / hydro-mechanical parameter block",
            fortran_runtime_consumer="doublelayer.F90 and stability formulas",
            branch_condition="always active when double-layer / hydro-mechanical path is enabled",
            physical_module="double-layer hydro-mechanics",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; tests/test_native_runtime_consumption.py::test_real_solver_double_layer_consumes_reference_uww",
            cases=SourceCase(
                "parsed; dedicated runtime test proves consumption",
                "parsed; no multicase runtime probe recorded",
                "parsed; no multicase runtime probe recorded",
            ),
            output_families_affected="FS_min_*; pressure-head / stability derived outputs",
            status="partial",
            allowed_for_calibration="no",
            status_note="The main consumer is closed in current code, but the family remains under semantic audit because earlier hard-coded branches existed and broad parity is not yet fully revalidated.",
        ),
    ]
)

REGISTRY_ENTRIES.extend(
    [
        matrix_entry(
            "nzsb",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 double-layer discretization block",
            fortran_runtime_consumer="doublelayer.F90 sublayer allocation",
            branch_condition="active only when double-layer runtime is enabled",
            physical_module="double-layer discretization",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase(
                "parsed and consumed in double-layer-capable path",
                "parsed and consumed in double-layer-capable path",
                "parsed and consumed in double-layer-capable path",
            ),
            output_families_affected="FS_min_*; pressure-head / stability derived outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Discretization control, not a science calibration variable.",
        ),
        matrix_entry(
            "nzst",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 double-layer discretization block",
            fortran_runtime_consumer="doublelayer.F90 sublayer allocation",
            branch_condition="active only when double-layer runtime is enabled",
            physical_module="double-layer discretization",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase(
                "parsed and consumed in double-layer-capable path",
                "parsed and consumed in double-layer-capable path",
                "parsed and consumed in double-layer-capable path",
            ),
            output_families_affected="FS_min_*; pressure-head / stability derived outputs",
            status="closed",
            allowed_for_calibration="no",
            status_note="Discretization control, not a science calibration variable.",
        ),
        matrix_entry(
            "zone_1_2_3_params",
            parameter_family="zones/zonfil",
            edda_input_source="edda_in.txt zone rows plus optional zonfil raster",
            fortran_reader="trini.f90 zone rows and zonfil branch",
            fortran_runtime_consumer="edda main program.F90 zone-indexed property lookup",
            branch_condition="nzon > 1 and zonfil usable -> raster-driven heterogeneous fields; otherwise scalar/global subset",
            physical_module="heterogeneous properties",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata; edda/io/zone_reader.py",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/case_inventory.md",
            cases=SourceCase("file_backed zonfil with nzon=3", "zonfil declared but inactive because nzon=1", "file_backed zonfil"),
            output_families_affected="Flow_depth; Flow_velocity_*; Total_depth; FS_min_*; Erosion_depth; Deposit_depth",
            status="partial",
            allowed_for_calibration="no",
            status_note="Zone heterogeneity is runtime-active, but several original semantic distinctions remain compressed.",
        ),
        matrix_entry(
            "slofil",
            edda_input_source="raster file",
            fortran_reader="trini.f90 slope-file branch",
            fortran_runtime_consumer="steady.f90; inidoublelayer.F90; doublelayer.F90; dfs.F90; wfs.F90",
            branch_condition="always file-backed in audited real cases",
            physical_module="topography / stability / flow routing",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; outputs/s1_reference_case_audit/runtime_input_manifest.json; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/case_inventory.md",
            cases=SourceCase("file_backed", "file_backed", "file_backed"),
            output_families_affected="Flow_depth; Flow_velocity_*; Max_flow_*; FS_min_*; OUTNQ_*",
            status="closed",
            allowed_for_calibration="no",
            status_note="Native slope raster is closed as an input family, but it is an input dataset rather than a calibration variable.",
        ),
        matrix_entry(
            "zfil/ltstar",
            parameter_family="ltstar/zfil",
            edda_input_source="edda_in.txt scalar with optional zfil raster",
            fortran_reader="trini.f90 ltstar / zfil branch",
            fortran_runtime_consumer="doublelayer.F90; erosion bookkeeping",
            branch_condition="ltstar < 0 activates zfil raster for upper-layer thickness; the original zmax branch is still unresolved",
            physical_module="double-layer geometry",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; outputs/s1_reference_case_audit/runtime_input_manifest.json; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/case_inventory.md",
            cases=SourceCase("file_backed zfil", "file_backed zfil", "file_backed zfil"),
            output_families_affected="FS_min_*; pressure-head / stability derived outputs; erosion bookkeeping",
            status="partial",
            allowed_for_calibration="no",
            status_note="The raster-driven ltstar subset is closed, but the historical zmax-side semantics are not.",
        ),
        matrix_entry(
            "dirfil",
            edda_input_source="raster file",
            fortran_reader="trini.f90 direction-file branch",
            fortran_runtime_consumer="no active consumer found in focused source trace",
            branch_condition="would matter only if predefined flow-direction mode were honored",
            physical_module="routing support",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/native_input_source_trace.md",
            cases=ENTIRE_ONLY_PROVENANCE,
            output_families_affected="Would affect routing-sensitive depth / velocity outputs if supported",
            status="unsupported",
            allowed_for_calibration="no",
            status_note="Recorded for provenance only; current runtime still uses DEM-derived connectivity.",
        ),
        matrix_entry(
            "TopoIndex/LogTI",
            edda_input_source="topographic support tables",
            fortran_reader="trini.f90 nxtfil / ndxfil / dscfil / wffil block",
            fortran_runtime_consumer="outside current forced target; no production Taichi consumer",
            branch_condition="not part of the current backend target surface",
            physical_module="topographic support tables",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/native_input_source_trace.md",
            cases=ENTIRE_ONLY_PROVENANCE,
            output_families_affected="Would affect legacy runoff-order / weighting families, not current production outputs",
            status="unsupported",
            allowed_for_calibration="no",
            status_note="Pure provenance family outside the current closure target.",
        ),
        matrix_entry(
            "cri/capt",
            parameter_family="cri/rifil/capt",
            edda_input_source="edda_in.txt scalar schedule with optional rifil raster series",
            fortran_reader="trini.f90 rainfall schedule block",
            fortran_runtime_consumer="edda main program.F90 builds rideb(:,j); dfs.F90 / wfs.F90 rainfall forcing",
            branch_condition="cri(j) >= 0 keeps uniform scalar rainfall; cri(j) < 0 activates the matching rifil(j) raster",
            physical_module="rainfall forcing",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::_build_rainfall_forcing; edda/io/rainfall_reader.py",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; tests/test_native_runtime_consumption.py::test_real_solver_uses_uniform_cri_interval_average; tests/test_native_runtime_consumption.py::test_real_solver_uses_mixed_rifil_and_uniform_periods; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md",
            cases=SourceCase(
                "uniform cri scalar path",
                "uniform cri scalar path",
                "uniform cri scalar path even though rainfall flag is F",
                note="No shipped case exercises negative-cri rifil; the mixed branch is covered by dedicated tests only.",
            ),
            output_families_affected="Flow_depth; Flow_velocity_*; Max_flow_*; Total_depth; Volumetric_sediment_concentration_*; OUTNQ_*",
            status="partial",
            allowed_for_calibration="no",
            status_note="Scalar schedule is closed; rifil branch exists and is tested, but there is no shipped-case runtime evidence yet.",
        ),
        matrix_entry(
            "output_flags",
            edda_input_source="edda_in.txt save / export flags",
            fortran_reader="trini.f90 whole-process save-flag block",
            fortran_runtime_consumer="original grid exporters; soutf.F90; shydro.F90; EDDALog.txt",
            branch_condition="flag-specific",
            physical_module="output control",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; api/services/reference_config_parser.py::UNSUPPORTED_FLAG_SPECS; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_mode_activation_matrix.md",
            cases=SourceCase(
                "parsed, current exporter does not honor original contract",
                "parsed, current exporter does not honor original contract",
                "parsed, current exporter does not honor original contract",
            ),
            output_families_affected="Flow_depth; Flow_velocity_*; Max_flow_*; Total_depth; Volumetric_sediment_concentration_*; FS_min_*; OUTNQ_*; HYDROGRAPH_*; EDDALog.txt",
            status="blocked",
            allowed_for_calibration="no",
            status_note="Important provenance family, but not a closed runtime-control surface in the current backend.",
        ),
        manual_entry(
            parameter_family="inflow.txt",
            edda_input_source="sidecar file",
            fortran_reader="inflow_read.F90 fixed-path inflow.txt reader",
            fortran_runtime_consumer="dfs.F90 inflow staging; wfs.F90 inflow staging",
            branch_condition="simulate_inflow_hydrograph = T activates inflow.txt",
            physical_module="inflow forcing",
            taichi_config_field="native_inputs.files.inflow.txt sidecar summary",
            service_mapper="api/services/reference_config_parser.py::_discover_case_sidecar_inputs; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            solver_consumer="edda/solver/edda_solver.py::configure_inflow_hydrograph_forcing; edda/solver/dfs_dynamic_wave.py::step",
            runtime_evidence="tests/test_native_runtime_consumption.py::test_real_solver_consumes_inflow_sidecar_when_original_branch_is_active; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md",
            cases=SourceCase("not shipped; inactive", "file_backed and consumed (5 cells)", "file_backed and consumed (47 cells)"),
            output_families_affected="Flow_depth; Flow_velocity_*; Max_flow_*; Total_depth; OUTNQ_*",
            status="partial",
            allowed_for_calibration="no",
            status_note="The forcing chain is closed for supported runs, but original reporting parity is still incomplete.",
        ),
        matrix_entry(
            "outflow.txt",
            edda_input_source="sidecar file",
            fortran_reader="outflow_read.F90 fixed-path outflow.txt reader",
            fortran_runtime_consumer="dfs.F90; wfs.F90; soutf.F90",
            branch_condition="simulate_outflow_cell = T activates outflow.txt",
            physical_module="outflow process / selected-cell observation",
            service_mapper="api/services/reference_config_parser.py::_discover_case_sidecar_inputs; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            solver_consumer="edda/solver/edda_solver.py::configure_outflow_process_observer; edda/io/result_exporter.py partial OUTNQ export chain",
            runtime_evidence="tests/test_native_runtime_consumption.py::test_real_solver_exports_partial_outnq_process_file; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_mode_activation_matrix.md",
            cases=SourceCase("file_backed and consumed (11 cells)", "file_backed and consumed (177 cells)", "file_backed and consumed (29 cells)"),
            output_families_affected="OUTNQ_*; boundary/outflow metadata; indirectly Flow_depth and Flow_velocity_* near configured outlets",
            status="partial",
            allowed_for_calibration="no",
            status_note="Runtime observer/export closure exists, but full original hydraulic parity remains partial.",
        ),
        matrix_entry(
            "hydrograph.txt",
            edda_input_source="sidecar file",
            fortran_reader="hydro_read.F90 fixed-path hydrograph.txt reader",
            fortran_runtime_consumer="dfs.F90 hydrograph accumulation; shydro.F90 export",
            branch_condition="save_hydrograph_cells = T activates hydrograph.txt",
            physical_module="hydrograph monitoring / export",
            service_mapper="api/services/reference_config_parser.py::_discover_case_sidecar_inputs",
            solver_consumer="none in current production backend",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; api/services/reference_config_parser.py::UNSUPPORTED_FLAG_SPECS; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_mode_activation_matrix.md",
            cases=SourceCase("not shipped; inactive", "not shipped; inactive", "not shipped; inactive"),
            output_families_affected="HYDROGRAPH_*",
            status="unsupported",
            allowed_for_calibration="no",
            status_note="Neither loader nor export chain is closed in current production runtime.",
        ),
    ]
)

REGISTRY_ENTRIES.extend(
    [
        matrix_entry(
            "alpha1",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="dfs.F90 debris rheology path",
            branch_condition="always active in debris/hyperconcentrated rheology path",
            physical_module="rheology",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Flow_depth; Total_depth; Volumetric_sediment_concentration_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "beta1",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="dfs.F90 debris rheology path",
            branch_condition="always active in debris/hyperconcentrated rheology path",
            physical_module="rheology",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Flow_depth; Total_depth; Volumetric_sediment_concentration_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "alpha2",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="dfs.F90 viscosity / friction path",
            branch_condition="always active in debris/hyperconcentrated rheology path",
            physical_module="rheology",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Flow_depth; Total_depth; Volumetric_sediment_concentration_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "beta2",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="dfs.F90 viscosity / friction path",
            branch_condition="always active in debris/hyperconcentrated rheology path",
            physical_module="rheology",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Flow_depth; Total_depth; Volumetric_sediment_concentration_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "manning",
            parameter_family="manning/manningfil",
            edda_input_source="edda_in.txt scalar with optional manningfil raster override",
            fortran_reader="trini.f90 manning / manningfil branch",
            fortran_runtime_consumer="dfs.F90 / wfs.F90 flow resistance",
            branch_condition="usable manningfil raster overrides scalar; otherwise scalar Manning stays active",
            physical_module="rheology / flow resistance",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata; api/services/edda_input_mapper.py::apply_native_runtime_inputs",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; tests/test_native_runtime_consumption.py::test_real_solver_initialize_applies_raster_manning_field; tests/test_native_runtime_consumption.py::test_real_solver_initialize_falls_back_to_global_manning_constant; PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md",
            cases=SourceCase(
                "config_fallback global Manning=0.1",
                "config_fallback global Manning=0.10",
                "config_fallback global Manning=0.050",
                note="No shipped case reaches file-backed manningfil; raster branch is proved only in dedicated runtime tests.",
            ),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Flow_depth; Max_flow_depth; Total_depth; OUTNQ_*",
            status="partial",
            allowed_for_calibration="yes",
            status_note="Scalar Manning is calibration-safe; the combined family remains partial because the raster branch lacks shipped-case evidence.",
        ),
        matrix_entry(
            "limitfr",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="dfs.F90 Froude limiter; wfs.F90 adaptive Manning control",
            branch_condition="always active in current DFS flux and post-flow control path",
            physical_module="rheology / flow control",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; edda/solver/dfs_dynamic_wave.py; edda/physics/rheology.py",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Flow_depth; Max_flow_depth; OUTNQ_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science/runtime control parameter.",
        ),
        matrix_entry(
            "shallown",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="wfs.F90 shallow-flow branch in original source family",
            branch_condition="would matter only if the original shallown branch were carried into the current runtime",
            physical_module="rheology / shallow-water",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv; edda/config/sim_config.py",
            cases=SourceCase("parsed, mapped, not consumed", "parsed, mapped, not consumed", "parsed, mapped, not consumed"),
            output_families_affected="Would affect shallow-flow velocity and depth outputs if runtime closure existed",
            status="blocked",
            allowed_for_calibration="no",
            status_note="Known config field with no audited runtime consumer.",
        ),
        matrix_entry(
            "cvstar",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology / concentration block",
            fortran_runtime_consumer="dfs.F90 concentration cap family; related erosion/deposition source terms",
            branch_condition="always active where concentration evolution is modeled",
            physical_module="rheology / concentration",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase(
                "parsed and consumed through substituted role",
                "parsed and consumed through substituted role",
                "parsed and consumed through substituted role",
            ),
            output_families_affected="Volumetric_sediment_concentration_*; Flow_depth; Total_depth; Deposit_depth; Erosion_depth",
            status="partial",
            allowed_for_calibration="no",
            status_note="Current backend compresses several original Cv* semantics into a smaller set of caps and limiters.",
        ),
        matrix_entry(
            "cs",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology coefficient block",
            fortran_runtime_consumer="dfs.F90 shear / suspension-related source terms",
            branch_condition="always active in debris / erosion coupling path",
            physical_module="erosion / rheology coupling",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Volumetric_sediment_concentration_*; Erosion_depth; Deposit_depth; Flow_velocity_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "d50",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 deposition parameter block",
            fortran_runtime_consumer="deposition law in original deposition source family",
            branch_condition="always active in deposition path",
            physical_module="deposition",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Deposit_depth; Total_depth; Volumetric_sediment_concentration_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "coedepo",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 deposition parameter block",
            fortran_runtime_consumer="deposition coefficient in original deposition law",
            branch_condition="always active in deposition path",
            physical_module="deposition",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase("parsed and consumed", "parsed and consumed", "parsed and consumed"),
            output_families_affected="Deposit_depth; Total_depth; Volumetric_sediment_concentration_*",
            status="closed",
            allowed_for_calibration="yes",
            status_note="Closed science coefficient.",
        ),
        matrix_entry(
            "K/kresis",
            edda_input_source="edda_in.txt scalar",
            fortran_reader="trini.f90 rheology / resistance block",
            fortran_runtime_consumer="dfs.F90 laminar resistance path",
            branch_condition="always active where viscous resistance is modeled",
            physical_module="rheology / resistance",
            service_mapper="api/services/reference_config_parser.py::parse_reference_config_file; api/services/edda_input_mapper.py::build_reference_runtime_metadata",
            runtime_evidence="PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv",
            cases=SourceCase(
                "parsed and consumed through kresis main path",
                "parsed and consumed through kresis main path",
                "parsed and consumed through kresis main path",
            ),
            output_families_affected="Flow_velocity_*; Max_flow_velocity; Erosion_depth; Total_depth",
            status="partial",
            allowed_for_calibration="no",
            status_note="Main resistance role survives, but one mapper split still confuses it with a different erosion threshold carrier.",
        ),
    ]
)


def rows_for_csv(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{column: str(entry[column]) for column in CSV_COLUMNS} for entry in entries]


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join([header_line, divider, body])


def write_csv_registry(entries: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "parameter_registry.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_for_csv(entries))


def write_registry_md(entries: list[dict[str, Any]]) -> None:
    counts = Counter(entry["status"] for entry in entries)
    summary_rows = [
        [
            entry["parameter_family"],
            entry["physical_module"],
            entry["status"],
            entry["allowed_for_calibration"],
            entry["taichi_config_field"],
        ]
        for entry in entries
    ]
    content = f"""# Parameter Registry

Last updated: {TODAY}

This directory turns the question

`is this parameter really used?`

into a versioned answer with:

- original Fortran reader / consumer anchors,
- current FastAPI-to-Taichi mapping anchors,
- runtime evidence already present inside this repository,
- explicit multicase coverage notes,
- calibration gating.

## Source basis

- `PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv`
- `PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/case_inventory.md`
- `PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_parameter_activation_matrix.md`
- `PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/cross_case_mode_activation_matrix.md`
- `PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/native_input_source_trace.md`
- `tests/test_native_runtime_consumption.py`
- `outputs/s1_reference_case_audit/runtime_input_manifest.json`

## Status counts

- `closed`: {counts.get("closed", 0)}
- `fallback_closed`: {counts.get("fallback_closed", 0)}
- `partial`: {counts.get("partial", 0)}
- `blocked`: {counts.get("blocked", 0)}
- `unsupported`: {counts.get("unsupported", 0)}

## Review Table

The CSV is the authoritative wide table. The shorter table below is for scan speed.

{markdown_table(
    ["parameter_family", "physical_module", "status", "allowed_for_calibration", "taichi_config_field"],
    summary_rows,
)}
"""
    (OUTPUT_DIR / "parameter_registry.md").write_text(content, encoding="utf-8", newline="\n")


def write_case_activation_matrix(entries: list[dict[str, Any]]) -> None:
    rows = []
    for entry in entries:
        parts = dict(part.split("::", 1) for part in entry["case_coverage"].split(" || "))
        rows.append(
            [
                entry["parameter_family"],
                parts["EntireBanzigou1005"],
                parts["NO.8_AYG_V2"],
                parts["Test31"],
                entry["_case_note"] or "-",
            ]
        )
    content = f"""# Case Activation Matrix

Last updated: {TODAY}

This file normalizes the cross-case coverage surface for the families in `parameter_registry.csv`.

{markdown_table(
    ["parameter_family", "EntireBanzigou1005", "NO.8_AYG_V2", "Test31", "notes"],
    rows,
)}
"""
    (OUTPUT_DIR / "case_activation_matrix.md").write_text(content, encoding="utf-8", newline="\n")


def write_blocked_list(entries: list[dict[str, Any]]) -> None:
    blocked = [entry for entry in entries if entry["status"] in {"blocked", "unsupported"}]
    partial = [entry for entry in entries if entry["status"] == "partial"]

    def render_section(title: str, items: list[dict[str, Any]]) -> str:
        lines = [f"## {title}", ""]
        if not items:
            lines.append("None.")
            lines.append("")
            return "\n".join(lines)
        for entry in items:
            lines.append(f"### {entry['parameter_family']}")
            lines.append("")
            lines.append(f"- status: `{entry['status']}`")
            lines.append(f"- module: `{entry['physical_module']}`")
            lines.append(f"- reason: {entry['_status_note']}")
            lines.append(f"- runtime evidence: `{entry['runtime_evidence']}`")
            lines.append(f"- case coverage: `{entry['case_coverage']}`")
            lines.append("")
        return "\n".join(lines)

    content = f"""# Blocked Parameter List

Last updated: {TODAY}

This file keeps the no-go surface explicit. Use it before exposing parameters in UI
or treating them as safe calibration variables.

{render_section("Blocked Or Unsupported", blocked)}
{render_section("Partial Families That Still Need Caution", partial)}
"""
    (OUTPUT_DIR / "blocked_parameter_list.md").write_text(content, encoding="utf-8", newline="\n")


def write_fortran_trace(entries: list[dict[str, Any]]) -> None:
    FORTRAN_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_rows = [
        [
            entry["parameter_family"],
            entry["fortran_reader"],
            entry["fortran_runtime_consumer"],
            entry["branch_condition"],
            entry["status"],
        ]
        for entry in entries
    ]
    readme = f"""# Fortran Trace

Last updated: {TODAY}

Primary evidence used here:

- `PROJECT_REPORTS/agent_runs/2026-04-24/phase_multicase_inflow/native_input_source_trace.md`
- `PROJECT_REPORTS/BACKEND_ALIGNMENT_AUDITS/parameter_role_matrix.csv`
- `tests/comparison/run_entire_banzigou_alignment.py`

Important limitation:

- the original Fortran source tree is not vendored in this repository;
- some scalar-family rows are anchored through prior audit notes and parser mirrors rather than direct local source files.
"""
    family_trace = f"""# Fortran Family Trace

{markdown_table(
    ["parameter_family", "fortran_reader", "fortran_runtime_consumer", "branch_condition", "status"],
    trace_rows,
)}
"""
    (FORTRAN_TRACE_DIR / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    (FORTRAN_TRACE_DIR / "family_trace.md").write_text(family_trace, encoding="utf-8", newline="\n")


def write_taichi_trace(entries: list[dict[str, Any]]) -> None:
    TAICHI_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_rows = [
        [
            entry["parameter_family"],
            entry["taichi_config_field"],
            entry["service_mapper"],
            entry["solver_consumer"],
            entry["runtime_evidence"],
            entry["status"],
        ]
        for entry in entries
    ]
    readme = f"""# Taichi Trace

Last updated: {TODAY}

Primary evidence used here:

- `api/services/reference_config_parser.py`
- `api/services/edda_input_mapper.py`
- `api/services/runtime_audit.py`
- `edda/config/sim_config.py`
- `tests/test_native_runtime_consumption.py`
"""
    runtime_chain = f"""# Config To Runtime Chain

{markdown_table(
    ["parameter_family", "taichi_config_field", "service_mapper", "solver_consumer", "runtime_evidence", "status"],
    trace_rows,
)}
"""
    (TAICHI_TRACE_DIR / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    (TAICHI_TRACE_DIR / "runtime_chain.md").write_text(runtime_chain, encoding="utf-8", newline="\n")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv_registry(REGISTRY_ENTRIES)
    write_registry_md(REGISTRY_ENTRIES)
    write_case_activation_matrix(REGISTRY_ENTRIES)
    write_blocked_list(REGISTRY_ENTRIES)
    write_fortran_trace(REGISTRY_ENTRIES)
    write_taichi_trace(REGISTRY_ENTRIES)
    print(f"Wrote parameter provenance artifacts to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
