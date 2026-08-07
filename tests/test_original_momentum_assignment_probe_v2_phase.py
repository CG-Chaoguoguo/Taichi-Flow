from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_original_momentum_assignment_term_probe_cell35978"
)
PATCH_V2 = (
    ROOT
    / "tests"
    / "_fortran_toolchain_sandbox"
    / "patches"
    / "instrument_original_momentum_assignment_terms_probe_v2.patch"
)
BUILD_SCRIPT = ROOT / "tests" / "_fortran_toolchain_sandbox" / "scripts" / "build_instrumented_edda.ps1"
RUN_SCRIPT = ROOT / "tests" / "_fortran_toolchain_sandbox" / "scripts" / "run_instrumented_original_cases.ps1"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_assignment_probe_v2_scaffold_and_sandbox_recognition_exist():
    patch = PATCH_V2.read_text(encoding="utf-8")
    build = BUILD_SCRIPT.read_text(encoding="utf-8")
    run = RUN_SCRIPT.read_text(encoding="utf-8")
    assert "assignment sites" in patch
    assert "fvlimit" in patch
    assert "qqmass" in patch
    assert "momentum_assignment_terms_probe_v2" in build
    assert "original_momentum_assignment_terms_raw.txt" in run


def test_phase_records_assignment_probe_failure_with_trace():
    summary = (PHASE / "loop_state_summary.md").read_text(encoding="utf-8")
    failure = (PHASE / "original_probe_failure_trace.md").read_text(encoding="utf-8")
    assert "ORIGINAL_TRACKED_SCALAR_MOMENTUM_ARTIFACT_FAILED_WITH_TRACE" in summary
    assert "ORIGINAL_MOMENTUM_ASSIGNMENT_PROBE_FAILED_WITH_TRACE" in failure
    assert "before_unsfin" in failure
    assert "SIGSEGV" in failure


def test_assignment_site_trace_names_required_terms():
    trace = (PHASE / "fortran_momentum_assignment_site_trace.md").read_text(encoding="utf-8")
    for term in ("grad", "sfy", "sfmiu", "sfmanning", "localvdiff", "artivis", "dv", "fvlimit", "qq/qqmass"):
        assert term in trace


def test_current_assignment_artifact_confirmed_but_original_delta_insufficient():
    current = _rows(PHASE / "current_momentum_assignment_terms_20a.csv")
    consumed = next(row for row in current if row["record_scope"] == "source_entry_consumed_previous_face_predictor")
    assert int(consumed["target_cell_id"]) == 35978
    assert int(consumed["target_direction"]) == 5
    assert int(consumed["clamp_status"]) == 1

    payload = json.loads((PHASE / "momentum_assignment_term_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ORIGINAL_TRACKED_SCALAR_MOMENTUM_ARTIFACT_FAILED_WITH_TRACE"
    assert payload["repair_decision"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["classification"] == "ORIGINAL_ARTIFACT_INSUFFICIENT_FOR_DELTA"
