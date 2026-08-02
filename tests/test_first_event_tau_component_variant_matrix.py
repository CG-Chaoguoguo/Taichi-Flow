from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-28\phase_first_event_tau_component_original_artifact_and_state_mapping_repair"
)


def test_tau_component_variants_show_original_absubar_closes_first_event_ratio():
    payload = json.loads((PHASE_DIR / "first_event_tau_component_variant_matrix.json").read_text(encoding="utf-8"))
    rows = {(row["case"], row["variant"]): row for row in payload["rows"]}

    for case_key in ("20a", "50a"):
        current = rows[(case_key, "A_current_native_first_event")]
        original_cell_mask = rows[(case_key, "B_current_original_cell_mask")]
        original_absubar = rows[(case_key, "C_current_coefficients_original_absubar")]

        assert float(current["ratio_to_original"]) > 4.0
        assert float(original_cell_mask["ratio_to_original"]) > 3.0
        assert abs(float(original_absubar["ratio_to_original"]) - 1.0) < 2.0e-4
        assert original_absubar["support"] == "original_artifact_supported"
        assert original_absubar["production_eligible"] is False


def test_tau_component_repair_candidate_report_is_diagnostics_only():
    text = (PHASE_DIR / "first_event_tau_component_repair_candidate_report.md").read_text(encoding="utf-8")
    assert "FIRST_EVENT_ABSUBAR_STATE_MISMATCH" in text
    assert "production_repair_allowed_this_phase: `false`" in text
    assert "feature-gated implementation and full paired validation" in text
