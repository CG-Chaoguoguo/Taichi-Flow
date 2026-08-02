from __future__ import annotations

from pathlib import Path

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.reference_config_parser import parse_reference_config_file


CASE_20A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a")


def _find_manifest_entry(runtime_input_manifest, family: str):
    for entry in runtime_input_manifest["inputs"]:
        if entry["family"] == family:
            return entry
    raise KeyError(family)


def test_native_path_resolution_preserves_file_vs_fallback_semantics():
    parsed = parse_reference_config_file(str(CASE_20A / "edda_in.txt"))
    _, _, runtime_input_manifest, _ = build_reference_runtime_metadata(parsed, Path.cwd() / ".runtime" / "paired_path_resolver_probe")

    dem_entry = _find_manifest_entry(runtime_input_manifest, "demfil")
    outflow_entry = _find_manifest_entry(runtime_input_manifest, "outflow.txt")
    depfil_entry = _find_manifest_entry(runtime_input_manifest, "depfil")
    rizerofil_entry = _find_manifest_entry(runtime_input_manifest, "rizerofil")
    manningfil_entry = _find_manifest_entry(runtime_input_manifest, "manningfil")
    rifil_entry = _find_manifest_entry(runtime_input_manifest, "rifil")

    assert Path(dem_entry["path"]).exists()
    assert Path(outflow_entry["path"]).exists()
    assert depfil_entry["input_state"] == "config_fallback"
    assert rizerofil_entry["input_state"] == "config_fallback"
    assert manningfil_entry["input_state"] == "config_fallback"
    assert rifil_entry["input_state"] == "config_fallback"
