from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE = (
    ROOT
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-05-01"
    / "phase_neighbor_depth_state_at_wet_dry_gate_repair_gate"
)


def test_neighbor_depth_lifecycle_reports_generate():
    script = ROOT / "tests" / "comparison" / "generate_neighbor_depth_lifecycle_reports.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

    required = [
        "neighbor_depth_lifecycle_report.md",
        "neighbor_depth_lifecycle_trace_original.md",
        "neighbor_depth_lifecycle_trace_current.md",
        "neighbor_depth_lifecycle_delta_matrix.md",
        "repair_decision.md",
        "next_round_handoff.md",
        "lifecycle_probe_commands.md",
        "targeted_test_evidence.md",
        "cleanup_manifest.md",
        "final_process_check.md",
    ]
    for name in required:
        assert (PHASE / name).exists(), name


def test_contributor_depth_divergence_is_localized():
    summary = (PHASE / "neighbor_depth_lifecycle_report.md").read_text(encoding="utf-8")
    delta = json.loads((PHASE / "neighbor_depth_lifecycle_delta_matrix.json").read_text(encoding="utf-8"))

    assert "NEIGHBOR_DEPTH_STATE_DIVERGENCE_LOCALIZED" in summary
    assert delta["status"] == "NEIGHBOR_DEPTH_STATE_DIVERGENCE_LOCALIZED"
    assert delta["secondary_status"] == "CONTRIBUTOR_FHPREDI_COMPONENT_TRACE_REQUIRED"
    assert delta["blocker"] == "UPSTREAM_NEIGHBOR_DEPTH_COMPONENT_LEDGER_REQUIRED"


def test_first_divergence_is_contributor_predicted_depth_not_source_depth():
    delta = json.loads((PHASE / "neighbor_depth_lifecycle_delta_matrix.json").read_text(encoding="utf-8"))
    rows = {row["candidate"]: row for row in delta["rows"]}

    assert rows["source_cell_predicted_depth"]["classification"] == "ALIGNED"
    assert abs(rows["source_cell_predicted_depth"]["delta"]) < 1.0e-12
    assert rows["contributor_predicted_depth_at_gate"]["classification"] == "FIRST_DIVERGENCE"
    assert rows["contributor_predicted_depth_at_gate"]["delta"] > 4.0e-4
    assert delta["metrics"]["current_neighbor_margin_above_tol"] > 0.0
    assert delta["metrics"]["original_neighbor_margin_below_tol"] > 0.0


def test_same_interval_flux_and_precision_are_not_first_divergence():
    delta = json.loads((PHASE / "neighbor_depth_lifecycle_delta_matrix.json").read_text(encoding="utf-8"))
    rows = {row["candidate"]: row for row in delta["rows"]}

    assert rows["source_prior_face_flux"]["classification"] == "NOT_FIRST_DIVERGENCE"
    assert rows["depth_clamp_floor_behavior"]["classification"] == "EXCLUDED"
    assert rows["precision_tol"]["classification"] == "EXCLUDED"
    assert rows["rainfall_source_inflow_into_36238"]["classification"] == "BLOCKED_BY_MISSING_ARTIFACT"
    assert rows["writeback_order"]["classification"] == "PLAUSIBLE_NEEDS_TRACE"


def test_repair_gate_remains_closed_until_component_ledger_exists():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "fhpredi1" in handoff
    assert "qnet" in handoff
    assert "accepted commit" in handoff
