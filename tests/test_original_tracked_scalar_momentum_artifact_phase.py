from __future__ import annotations

import csv
import json
from pathlib import Path


PHASE = (
    Path(__file__).resolve().parents[1]
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-30"
    / "phase_original_tracked_scalar_momentum_artifact_and_fvlimit_delta"
)
PATCH = (
    Path(__file__).resolve().parents[0]
    / "_fortran_toolchain_sandbox"
    / "patches"
    / "instrument_original_tracked_scalar_momentum_terms_probe.patch"
)


def _read_rows(case: str) -> list[dict[str, str]]:
    with (PHASE / f"current_tracked_scalar_momentum_terms_{case}.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


def test_phase_reports_confirm_current_tracked_scalar_artifact_and_keep_gate_closed():
    payload = json.loads((PHASE / "tracked_scalar_momentum_term_delta_matrix.json").read_text(encoding="utf-8"))
    assert payload["status"] == "CURRENT_TRACKED_SCALAR_MOMENTUM_ARTIFACT_CONFIRMED"
    assert payload["repair_decision"] == "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET"
    assert payload["original_artifact_status"] == "missing"
    assert payload["candidate_mismatch"] == "FV_LIMIT_CLAMP_REQUIRES_ORIGINAL_RUNTIME_TERM_DELTA"


def test_current_artifacts_are_tracked_scalar_only_and_capture_fvlimit_clamp():
    for case in ("20a", "50a"):
        rows = _read_rows(case)
        consumed = next(
            row for row in rows if row["record_scope"] == "source_entry_consumed_previous_face_predictor"
        )
        assert int(consumed["target_cell_id"]) == 35978
        assert int(consumed["target_direction"]) == 5
        assert int(consumed["clamp_status"]) == 1
        assert float(consumed["fvlimit"]) > 0.0


def test_original_probe_patch_scaffold_exists_and_forbids_full_grid_dump():
    text = PATCH.read_text(encoding="utf-8")
    assert "cell_id=35978" in text
    assert "D6" in text
    assert "fvlimit" in text
    assert "do not dump full grids" in text.lower()


def test_handoff_names_original_artifact_as_precise_blocker():
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "ORIGINAL_TRACKED_SCALAR_MOMENTUM_FACEFLUX_RUNTIME_ARTIFACT_REQUIRED" in handoff
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
