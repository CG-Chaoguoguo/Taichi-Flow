from copy import deepcopy
from pathlib import Path

from api.services.reference_config_parser import parse_reference_config_file
from api.services.scenario_config_overrides import apply_scenario_overrides
from tests.test_native_input_chain import _make_reference_case


def test_apply_scenario_overrides_switches_uniform_to_raster(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))
    assert parsed.rainfall_mode == "uniform_cri"

    overridden = apply_scenario_overrides(
        parsed,
        {"rainfall": {"mode": "raster_rifil"}},
    )
    assert overridden.rainfall_mode == "raster_rifil"
    assert all(cri < 0 for cri in overridden.cri_mps)
    # original unchanged
    assert parsed.rainfall_mode == "uniform_cri"


def test_apply_scenario_overrides_switches_raster_to_uniform_and_sets_manning(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = Path(edda_in).read_text(encoding="utf-8")
    Path(edda_in).write_text(text.replace("3.33333e-07 5.55556e-08", "-1 -1"), encoding="utf-8")
    parsed = parse_reference_config_file(str(edda_in))
    assert parsed.rainfall_mode == "raster_rifil"

    overridden = apply_scenario_overrides(
        parsed,
        {
            "rainfall": {
                "mode": "uniform_cri",
                "periods": [
                    {"index": 1, "source": "uniform_cri", "cri_mps": 1e-6},
                    {"index": 2, "source": "uniform_cri", "cri_mps": 2e-6},
                ],
            },
            "manning": {"source": "global_manning"},
            "rheology": {"n_manning": 0.045},
        },
    )
    assert overridden.rainfall_mode == "uniform_cri"
    assert overridden.cri_mps[0] == 1e-6
    assert overridden.cri_mps[1] == 2e-6
    assert overridden.manning_source == "global_initiation_manning"
    assert overridden.manning_global == 0.045


def test_apply_scenario_overrides_requests_raster_manning(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))
    # fixture manning may or may not exist; force global then request raster
    base = apply_scenario_overrides(parsed, {"manning": {"source": "global_manning"}})
    assert base.manning_source == "global_initiation_manning"

    manning_path = tmp_path / "Data" / "tutorial" / "manning.asc"
    manning_path.parent.mkdir(parents=True, exist_ok=True)
    if not manning_path.exists():
        manning_path.write_text(
            "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n0.1 0.1\n0.1 0.1\n",
            encoding="utf-8",
        )

    overridden = apply_scenario_overrides(
        base,
        {
            "manning": {"source": "raster_manningfil"},
            "native_inputs": {
                "files": {
                    "manningfil": {"path": str(manning_path)},
                }
            },
        },
    )
    assert overridden.manning_source == "raster_manningfil"
    assert overridden.file_inputs["manningfil"].resolved_paths == [str(manning_path)]


def test_deepcopy_isolation(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    parsed = parse_reference_config_file(str(edda_in))
    before = deepcopy(parsed.cri_mps)
    apply_scenario_overrides(parsed, {"rainfall": {"mode": "raster_rifil"}})
    assert parsed.cri_mps == before
