from pathlib import Path

import pytest

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.reference_config_parser import parse_reference_config_file
from api.services.runtime_audit import build_output_manifest, build_parameter_audit


CASE_DIR = Path(r"C:\Users\Administrator\Desktop\EntireBanzigou1005")
CASE_CONFIG = CASE_DIR / "edda_in.txt"
CASE_RESULTS = CASE_DIR / "results"

pytestmark = pytest.mark.skipif(
    not CASE_CONFIG.exists(),
    reason="EntireBanzigou1005 case is not available on this machine.",
)


def test_entire_banzigou_case_activation_metadata_matches_original_branches(tmp_path):
    parsed = parse_reference_config_file(CASE_CONFIG)
    config, effective_config, runtime_input_manifest, provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "case-output",
    )
    output_manifest = build_output_manifest(
        CASE_RESULTS,
        reference_output_expectations=provenance["reference_output_expectations"],
    )
    parameter_audit = build_parameter_audit(
        config,
        runtime_input_manifest,
        provenance,
        output_manifest=output_manifest,
    )

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    parameter_map = {entry["parameter"]: entry for entry in parameter_audit["parameters"]}

    assert parsed.rainfall_mode == "uniform_cri"
    assert parsed.manning_source == "global_initiation_manning"

    assert parsed.file_inputs["depfil"].original_branch_active is False
    assert parsed.file_inputs["rizerofil"].original_branch_active is False
    assert parsed.file_inputs["zfil"].original_branch_active is True
    assert parsed.file_inputs["zfil"].current_backend_branch_active is True
    assert parsed.file_inputs["outflow.txt"].original_branch_active is True
    assert parsed.file_inputs["outflow.txt"].current_backend_branch_active is True
    assert parsed.file_inputs["outflow.txt"].structure_summary["declared_cell_count"] == 11

    assert manifest["depfil"]["original_branch_active"] is False
    assert manifest["rizerofil"]["original_branch_active"] is False
    assert manifest["zfil"]["original_branch_active"] is True
    assert manifest["zfil"]["current_backend_branch_active"] is True
    assert manifest["outflow.txt"]["original_branch_active"] is True
    assert manifest["outflow.txt"]["current_backend_branch_active"] is True
    assert manifest["outflow.txt"]["expected_output_families"] == ["OUTNQ_*"]

    assert effective_config["reference_case_activation"]["depfil"]["original_branch_active"] is False
    assert effective_config["reference_case_activation"]["outflow.txt"]["original_branch_active"] is True
    assert "OUTNQ_*" in effective_config["reference_output_expectations"]["expected_output_families"]
    assert "Flow_depth_*" in effective_config["reference_output_expectations"]["expected_output_families"]
    assert effective_config["reference_output_expectations"]["output_timing"]["OUTNQ_*"] == "end_of_run_only"
    assert effective_config["sidecar_output_parity"]["outflow.txt"]["parity_status"] == "partial"
    assert effective_config["sidecar_output_parity"]["EDDALog.txt"]["parity_status"] == "metadata_only"

    assert parameter_audit["reference_case_activation"]["zfil"]["current_backend_branch_active"] is True
    assert parameter_map["sidecar.outflow.txt"]["evidence"]["original_branch_active"] is True
    assert parameter_map["sidecar.outflow.txt"]["evidence"]["structure_summary"]["declared_cell_count"] == 11
    assert parameter_map["native_input.zfil"]["evidence"]["original_branch_active"] is True
    assert parameter_map["native_input.zfil"]["evidence"]["current_backend_branch_active"] is True
    assert "ltstar grid" in parameter_map["native_input.zfil"]["evidence"]["original_fortran_semantic"]
    assert parameter_map["output.OUTNQ_*"]["status"] == "missing"
    assert parameter_map["sidecar.EDDALog.txt"]["status"] == "metadata-only"
    assert parameter_audit["reference_summary"]["sidecar_output_parity"]["outflow.txt"]["parity_status"] == "partial"

    result_paths = [entry["relative_path"] for entry in output_manifest["result_files"]]
    assert any(path.startswith("Flow_depth_") for path in result_paths)
    assert any(path.startswith("Flow_velocity_") for path in result_paths)
    assert not any(path.startswith("OUTNQ_") for path in result_paths)
    parity = {entry["artifact"]: entry for entry in output_manifest["reference_output_parity"]["artifact_status"]}
    assert parity["Flow_depth_*"]["parity_status"] == "present"
    assert parity["OUTNQ_*"]["parity_status"] == "missing"
    assert parity["EDDALog mass-balance sections"]["parity_status"] == "not_observable_from_file_inventory"
