import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_velocity_state_upstream_mismatch_repair"
)


def test_upstream_delta_classifies_pre_branch_velocity_as_momentum_mismatch():
    payload = json.loads((PHASE / "velocity_upstream_delta_matrix.json").read_text(encoding="utf-8"))
    rows = payload["rows"]

    assert payload["status"] == "VELOCITY_STATE_UPSTREAM_MOMENTUM_MISMATCH"

    source_order_snapshots = {
        "source_entry",
        "pre_source_branch",
        "branch_fv",
        "branch_fvpredi2",
        "before_face_flux",
    }
    checked = [row for row in rows if row["snapshot"] in source_order_snapshots]
    assert checked

    for row in checked:
        assert row["classification"] == "VELOCITY_STATE_UPSTREAM_MOMENTUM_MISMATCH"
        assert row["direction_index_status"] == "ALIGNED_D6_DOMINANT"
        assert row["current_selected_component"] == "vcomp"
        assert row["current_gate_result"] == 0
        assert row["absubar_ratio"] > 4.0
        assert row["depth_ratio_current_to_original"] < 1.1


def test_post_flux_snapshot_is_rejected_by_fortran_source_order():
    payload = json.loads((PHASE / "velocity_upstream_delta_matrix.json").read_text(encoding="utf-8"))
    post_flux_rows = [row for row in payload["rows"] if row["snapshot"] == "after_face_flux"]

    assert post_flux_rows
    assert all(row["classification"] == "AFTER_FACE_FLUX_REJECTED" for row in post_flux_rows)
    assert all(row["direction_index_status"] == "POST_FLUX_STATE" for row in post_flux_rows)
    assert all(row["current_gate_result"] == 1 for row in post_flux_rows)


def test_velocity_upstream_repair_gate_remains_closed_and_next_prompt_is_actionable():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")
    prompt = (PHASE / "next_round_codex_prompt.md").read_text(encoding="utf-8")

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "VELOCITY_STATE_UPSTREAM_MOMENTUM_MISMATCH" in decision

    for term in ("grad", "sfy", "sfmiu", "sfmanning", "localvdiff", "artivis", "dv"):
        assert term in handoff
        assert term in prompt

    assert "Do not modify deporate formula" in prompt
    assert "Do not use post-flux state" in prompt
