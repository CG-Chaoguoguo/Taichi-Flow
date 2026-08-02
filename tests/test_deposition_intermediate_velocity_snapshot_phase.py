import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_intermediate_velocity_snapshot_and_gate_repair"
)


def test_snapshot_plumbing_fields_and_capture_points_are_present():
    fields_source = (REPO / "edda" / "core" / "fields.py").read_text(encoding="utf-8")
    dfs_source = (REPO / "edda" / "solver" / "dfs_dynamic_wave.py").read_text(encoding="utf-8")
    diagnostic_source = (
        REPO / "tests" / "comparison" / "run_paired_erosion_gate_diagnostic.py"
    ).read_text(encoding="utf-8")

    for field_name in (
        "depo_velocity_source_entry",
        "depo_velocity_pre_source_branch",
        "depo_velocity_branch_fv",
        "depo_velocity_branch_fvpredi",
        "depo_velocity_branch_fvpredi2",
        "depo_velocity_before_face_flux",
        "depo_velocity_after_face_flux",
    ):
        assert field_name in fields_source
        assert field_name in diagnostic_source

    for capture_call in (
        "_capture_depo_velocity_source_entry",
        "_capture_depo_velocity_pre_source_branch",
        "_capture_depo_velocity_before_face_flux",
        "_capture_depo_velocity_after_face_flux",
    ):
        assert capture_call in dfs_source


def test_phase_reports_advance_to_snapshot_plumbing_not_production_repair():
    delta = json.loads((PHASE / "velocity_snapshot_delta_matrix.json").read_text(encoding="utf-8"))
    variants = json.loads((PHASE / "velocity_snapshot_variant_matrix.json").read_text(encoding="utf-8"))
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")

    assert delta["status"] == "CURRENT_INTERMEDIATE_VELOCITY_SNAPSHOTS_ADDED"
    assert delta["plumbing_present"] is True
    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision

    pending_candidates = [
        row
        for row in delta["rows"]
        if row["runtime_value_available"] == "pending_fresh_run"
    ]
    assert pending_candidates
    eligibility = {row["production_eligibility"] for row in variants["rows"]}
    assert "pending_runtime_evidence" in eligibility
    assert not any(str(value).startswith("production_allowed") for value in eligibility)


def test_next_round_prompt_keeps_scope_to_snapshot_runtime_validation():
    prompt = (PHASE / "next_round_codex_prompt.md").read_text(encoding="utf-8")

    assert "phase_deposition_snapshot_runtime_validation_cell35978" in prompt
    assert "Do not modify deporate formula" in prompt
    assert "Do not infer coefficients" in prompt
