from __future__ import annotations

from pathlib import Path

from api.services import parse_reference_config_file


CASE_20A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a")
CASE_50A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_50a\NO.5_XHG_V2_50a")


def test_paired_cases_resolve_manning_to_global_config_fallback():
    for case_dir in (CASE_20A, CASE_50A):
        parsed = parse_reference_config_file(case_dir / "edda_in.txt")
        assert parsed.manning_global == 0.1
        assert parsed.manning_source == "global_initiation_manning"
        manning_ref = parsed.file_inputs["manningfil"]
        assert not any(manning_ref.exists)

