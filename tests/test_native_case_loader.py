from __future__ import annotations

from pathlib import Path

from api.services.reference_config_parser import parse_reference_config_file


CASE_20A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a")
CASE_50A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_50a\NO.5_XHG_V2_50a")


def test_paired_rainfall_cases_parse_as_native_reference_configs():
    parsed_20 = parse_reference_config_file(str(CASE_20A / "edda_in.txt"))
    parsed_50 = parse_reference_config_file(str(CASE_50A / "edda_in.txt"))

    assert parsed_20.rainfall_mode == "uniform_cri"
    assert parsed_50.rainfall_mode == "uniform_cri"
    assert parsed_20.flags["simulate_inflow_hydrograph"] is False
    assert parsed_50.flags["simulate_inflow_hydrograph"] is False
    assert parsed_20.file_inputs["outflow.txt"].resolved_paths == [str(CASE_20A / "outflow.txt")]
    assert parsed_50.file_inputs["outflow.txt"].resolved_paths == [str(CASE_50A / "outflow.txt")]
    assert parsed_20.cri_mps != parsed_50.cri_mps
