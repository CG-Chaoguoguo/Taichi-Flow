import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_cv_density_mass_variants_do_not_authorize_formula_repair():
    variants = json.loads((PHASE / "cv_density_mass_variant_matrix.json").read_text(encoding="utf-8"))
    by_name = {row["variant"]: row for row in variants}

    assert by_name["writer_time_Cv_equals_committed_Cv_with_fh_mask"]["production_eligible"] is True
    assert by_name["frhopredi2_or_qmassnet_formula_change"]["production_eligible"] is False
    assert by_name["frhopredi2_or_qmassnet_formula_change"]["support_status"] == "requires_original_internal_artifact"


def test_repair_decision_limits_scope_to_output_parity():
    decision = (PHASE / "repair_decision.md").read_text(encoding="utf-8")
    assert "PRODUCTION_REPAIR_ALLOWED_VOLUMETRIC_OUTPUT_PARITY" in decision
    assert "does not alter solver Cv/rho/mass transport" in decision
