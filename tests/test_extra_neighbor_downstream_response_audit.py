import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SEDIMENT_PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"
DEPOSIT_PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"
DEPOSITION_PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_extra_neighbor_audit_remains_non_production_surface():
    audit = (SEDIMENT_PHASE / "extra_neighbor_downstream_response_audit.md").read_text(encoding="utf-8")
    variants = json.loads((SEDIMENT_PHASE / "extra_neighbor_downstream_variant_matrix.json").read_text(encoding="utf-8"))

    assert "EXTRA_NEIGHBOR_RESPONSE_MINOR_FOR_VOLUMETRIC_OUTPUT_PHASE" in audit
    assert variants
    assert all(row["production_eligible"] is False for row in variants)
    assert any(row["support_status"] == "audit_only" for row in variants)


def test_deposit_phase_extra_neighbor_audit_blocks_repair():
    audit = (DEPOSIT_PHASE / "extra_neighbor_downstream_response_audit.md").read_text(encoding="utf-8")
    variants = json.loads((DEPOSIT_PHASE / "extra_neighbor_downstream_variant_matrix.json").read_text(encoding="utf-8"))

    assert "EXTRA_NEIGHBOR_AUDIT_ONLY_NO_REPAIR" in audit
    assert variants
    assert all(row["production_eligible"] is False for row in variants)


def test_deposition_phase_extra_neighbor_audit_blocks_repair():
    audit = (DEPOSITION_PHASE / "extra_neighbor_downstream_response_audit.md").read_text(encoding="utf-8")
    variants = json.loads((DEPOSITION_PHASE / "extra_neighbor_deposition_variant_matrix.json").read_text(encoding="utf-8"))

    assert "EXTRA_NEIGHBOR_AUDIT_ONLY_NO_REPAIR" in audit
    assert variants
    assert all(row["production_eligible"] is False for row in variants)
