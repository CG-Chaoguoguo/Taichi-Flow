from pathlib import Path

import pytest

from api.services.parameter_catalog import build_case_config_interface
from api.services.reference_config_parser import parse_reference_config_file

CASE_DIR = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text")
EDDA_IN = CASE_DIR / "edda_in.txt"


@pytest.mark.skipif(not EDDA_IN.is_file(), reason="BJ_HXL_Text case not present on this machine")
def test_bj_hxl_text_edda_in_parse_rainfall_and_manning():
    parsed = parse_reference_config_file(str(EDDA_IN), str(CASE_DIR))
    assert parsed.nper == 72
    assert parsed.rainfall_duration_s == pytest.approx(259200.0)
    assert parsed.rainfall_mode == "raster_rifil"
    assert len(parsed.cri_mps) == 72
    assert len(parsed.capt_s) == 73
    assert parsed.capt_s[0] == pytest.approx(0.0)
    assert parsed.capt_s[-1] == pytest.approx(parsed.rainfall_duration_s)
    assert all(cri < 0 for cri in parsed.cri_mps)
    assert "global" in parsed.manning_source
    assert parsed.manning_global == pytest.approx(0.10)
    assert parsed.simul == pytest.approx(259200.0)
    assert parsed.tout == pytest.approx(3600.0)

    rifil = parsed.file_inputs["rifil"]
    assert len(rifil.resolved_paths) == 72
    assert sum(rifil.exists) == 72

    interface = build_case_config_interface(parsed)
    rainfall = interface["parsed_values"]["rainfall"]
    manning = interface["parsed_values"]["manning"]
    assert rainfall["mode"] == "raster_rifil"
    assert len(rainfall["periods"]) == 72
    assert "global" in manning["source"]
