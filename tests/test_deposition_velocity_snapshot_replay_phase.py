import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = (
    REPO
    / "PROJECT_REPORTS"
    / "agent_runs"
    / "2026-04-29"
    / "phase_deposition_velocity_snapshot_replay_and_candidate_repair"
)


def test_targeted_replay_was_tracked_only_for_cell_35978():
    for case in ("20a", "50a"):
        payload = json.loads((PHASE / f"current_snapshot_replay_raw_{case}.json").read_text(encoding="utf-8"))

        assert payload["t_end_s"] == 228.1
        assert payload["tracked_only_current_internal"] is True
        assert payload["candidate_cell_count"] == 1
        assert payload["forced_tracked_cell_ids"] == [35978]


def test_snapshot_delta_rejects_all_source_supported_candidates():
    payload = json.loads((PHASE / "snapshot_replay_delta_matrix.json").read_text(encoding="utf-8"))
    rows = payload["rows"]

    assert payload["status"] == "NO_SNAPSHOT_MATCHES_ORIGINAL"
    assert payload["classifications"] == {
        "20a": "NO_SNAPSHOT_MATCHES_ORIGINAL",
        "50a": "NO_SNAPSHOT_MATCHES_ORIGINAL",
    }

    high_candidates = {
        "active_branch",
        "source_entry",
        "pre_source_branch",
        "branch_fv",
        "branch_fvpredi2",
        "branch_fvpredi2_recomputed",
        "before_face_flux",
    }
    for row in rows:
        if row["snapshot_candidate"] in high_candidates:
            assert row["candidate_gate_result"] == 0
            assert row["absubar_ratio_to_original"] > 1.5
            assert row["production_eligibility"] == "not_allowed_no_absubar_match"


def test_post_flux_and_original_absubar_are_not_production_eligible():
    payload = json.loads((PHASE / "snapshot_replay_delta_matrix.json").read_text(encoding="utf-8"))
    rows = payload["rows"]

    post_flux = [row for row in rows if row["snapshot_candidate"] == "after_face_flux"]
    original_audit = [row for row in rows if row["snapshot_candidate"] == "original_absubar_audit"]
    assert post_flux
    assert original_audit

    assert all(row["candidate_gate_result"] == 1 for row in post_flux)
    assert all(row["production_eligibility"] == "not_allowed_post_flux_fortran_order_rejected" for row in post_flux)
    assert all(row["production_eligibility"] == "not_allowed_artifact_substitution" for row in original_audit)


def test_repair_decision_keeps_production_gate_closed():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    handoff = (PHASE / "next_round_handoff.md").read_text(encoding="utf-8")

    assert "NO_PRODUCTION_CHANGE_EVIDENCE_GATE_NOT_MET" in decision
    assert "NO_SNAPSHOT_MATCHES_ORIGINAL" in decision
    assert "Trace why current source-entry / pre-branch / branch velocity" in handoff
