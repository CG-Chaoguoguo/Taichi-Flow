"""Per-zone double-layer soil independence, patch channel, and zfil nodata semantics."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from api.services.edda_input_mapper import (
    apply_native_runtime_inputs,
    build_reference_runtime_metadata,
)
from api.services.parameter_catalog import (
    EDITABLE_PARAMETERS,
    READONLY_DISPLAY_PARAMETERS,
    ZONE_TAKEN_OVER_PARAMETERS,
    build_static_parameter_catalog,
)
from api.services.parameter_templates import normalized_parameter_values
from api.services.reference_config_parser import parse_reference_config_file
from api.services.scenario_config_overrides import apply_scenario_overrides
from api.services.structured_input_resolver import validate_scenario_configuration


CHAMOLI = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file")


def _bindings():
    return [{"binding_key": "dem.primary", "role": "primary", "active": True}]


def _rainfall_ok(parameters: dict) -> dict:
    parameters = dict(parameters)
    parameters.setdefault(
        "rainfall.periods",
        [
            {
                "period_id": "period-0001",
                "index": 1,
                "start_s": 0.0,
                "end_s": 3600.0,
                "source": "uniform",
                "cri_mps": 0.0,
            }
        ],
    )
    parameters.setdefault(
        "rainfall.timeline",
        {
            "mode": "regular",
            "start_s": 0.0,
            "end_s": 3600.0,
            "interval_s": 3600.0,
        },
    )
    return parameters


class _FakeBuffer:
    def __init__(self):
        self.value = None

    def from_numpy(self, array):
        self.value = np.array(array, copy=True)


class _FakeFields:
    def __init__(self, nx=2, ny=2):
        self.nx = nx
        self.ny = ny
        self.ltstar_field = _FakeBuffer()
        self.erodible_thickness = _FakeBuffer()
        self.n_manning_field = _FakeBuffer()
        self.slope_angle = _FakeBuffer()


class _FakeDoubleLayer:
    def __init__(self):
        self.initialized_with = None

    def build_initial_rikzero_field(self, rizero_rate):
        return np.zeros((2, 2), dtype=np.float64)

    def initialize_double_layer(self, rikzero):
        self.initialized_with = rikzero


def test_static_catalog_exposes_editable_zone_matrix():
    catalog = build_static_parameter_catalog()
    by_key = {entry["key"]: entry for entry in catalog["parameters"]}
    zones = by_key["spatial_zones.zones"]
    assert "spatial_zones.zones" in EDITABLE_PARAMETERS
    assert "spatial_zones.zones" not in READONLY_DISPLAY_PARAMETERS
    assert zones["editable"] is True
    assert zones["value_type"] == "structured"
    assert "soil.c" in ZONE_TAKEN_OVER_PARAMETERS
    assert by_key["erosion.ctao"]["editable"] is False


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_chamoli_four_zones_keep_independent_double_layer_params(tmp_path):
    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    assert sorted(parsed.zones) == [1, 2, 3, 4]
    assert parsed.zones[1].bottom.k_sat == pytest.approx(2.0e-7)
    assert parsed.zones[2].bottom.k_sat == pytest.approx(9.0e-7)
    assert parsed.zones[1].top.cvero == pytest.approx(0.6)
    assert parsed.zones[2].top.cvero == pytest.approx(0.3)
    assert parsed.zones[4].top.cvero == pytest.approx(0.55)
    assert parsed.zones[1].top.phi == pytest.approx(42.0)
    assert parsed.zones[2].top.phi == pytest.approx(20.0)

    config, _effective, _manifest, _provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )
    assert config.spatial_zones.enabled is True
    assert config.spatial_zones.zones[1].K_sat_bottom == pytest.approx(2.0e-7)
    assert config.spatial_zones.zones[2].K_sat_bottom == pytest.approx(9.0e-7)
    assert config.spatial_zones.zones[1].c_bottom == pytest.approx(2.0e7)
    assert config.spatial_zones.zones[1].ltstar == pytest.approx(0.0)
    values = normalized_parameter_values(parsed)
    assert values["spatial_zones.zones"]["1"]["K_sat_bottom"] == pytest.approx(2.0e-7)
    assert values["spatial_zones.zones"]["2"]["K_sat_bottom"] == pytest.approx(9.0e-7)


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_spatial_zones_patch_updates_zone_two_without_touching_zone_one(tmp_path):
    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    original_zone1_ksb = parsed.zones[1].bottom.k_sat
    overridden = apply_scenario_overrides(
        parsed,
        {
            "spatial_zones": {
                "zones": {
                    "2": {
                        "zone_id": 2,
                        "K_sat_bottom": 1.5e-6,
                        "alpha_top": 1.1,
                    }
                }
            }
        },
    )
    assert overridden.zones[1].bottom.k_sat == pytest.approx(original_zone1_ksb)
    assert overridden.zones[2].bottom.k_sat == pytest.approx(1.5e-6)
    assert overridden.zones[2].top.alpha == pytest.approx(1.1)
    assert overridden.zones[3].top.alpha == pytest.approx(parsed.zones[3].top.alpha)

    config, _effective, _manifest, _provenance = build_reference_runtime_metadata(
        overridden,
        tmp_path / "patched",
        config_overrides={
            "spatial_zones": {
                "zones": {
                    "2": {"zone_id": 2, "K_sat_bottom": 1.5e-6, "alpha_top": 1.1}
                }
            }
        },
    )
    assert config.spatial_zones.zones[1].K_sat_bottom == pytest.approx(original_zone1_ksb)
    assert config.spatial_zones.zones[2].K_sat_bottom == pytest.approx(1.5e-6)
    assert config.spatial_zones.zones[2].alpha_top == pytest.approx(1.1)


@pytest.mark.skipif(not (CHAMOLI / "edda_in.txt").exists(), reason="Chamoli reference case is not on disk")
def test_multi_zone_global_double_layer_block_stays_zone_one_fallback(tmp_path):
    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    config, _effective, _manifest, _provenance = build_reference_runtime_metadata(
        parsed,
        tmp_path / "output",
    )
    assert config.soil.double_layer.bottom_layer.K_sat == pytest.approx(parsed.zones[1].bottom.k_sat)
    assert config.spatial_zones.zones[2].K_sat_bottom != pytest.approx(config.soil.double_layer.bottom_layer.K_sat)


def test_scenario_configuration_rejects_invalid_zone_matrix():
    parameters = _rainfall_ok(
        {
            "spatial_zones.zones": {
                "1": {
                    "zone_id": 1,
                    "K_sat_top": 0.0,
                    "theta_sat_top": 0.2,
                    "theta_res_top": 0.3,
                }
            }
        }
    )
    result = validate_scenario_configuration(parameters, _bindings())
    codes = {issue["code"] for issue in result["issues"]}
    assert "spatial_zone_ksat_nonpositive" in codes
    assert "spatial_zone_theta_order_invalid" in codes
    assert result["valid"] is False


def test_scenario_configuration_accepts_chamoli_shaped_zone_matrix():
    parameters = _rainfall_ok(
        {
            "spatial_zones.zones": {
                "1": {
                    "zone_id": 1,
                    "K_sat_top": 8e-6,
                    "K_sat_bottom": 2e-7,
                    "theta_sat_top": 0.5,
                    "theta_res_top": 0.27,
                    "theta_sat_bottom": 0.2,
                    "theta_res_bottom": 0.07,
                    "cvero": 0.6,
                }
            }
        }
    )
    result = validate_scenario_configuration(parameters, _bindings())
    codes = {issue["code"] for issue in result["issues"]}
    assert "spatial_zone_ksat_nonpositive" not in codes
    assert "spatial_zone_theta_order_invalid" not in codes
    assert result["valid"] is True


def test_two_zone_params_rasterize_independent_bottom_ksat(tmp_path):
    from edda.config.sim_config import ZoneParams
    from edda.io.zone_reader import ZoneReader

    zone_path = tmp_path / "zones.asc"
    zone_path.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 1",
                "NODATA_value -9999",
                "1 2",
                "1 2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    reader = ZoneReader(str(zone_path))
    reader.read_zone_grid()
    zones = {
        1: ZoneParams(zone_id=1, K_sat_bottom=2.0e-7, alpha_top=0.7, K_sat_top=8e-6),
        2: ZoneParams(zone_id=2, K_sat_bottom=9.0e-7, alpha_top=1.1, K_sat_top=4e-6),
    }
    _mask, params = reader.apply_zone_parameters(zones, grid_shape=(2, 2))
    assert params.shape == (2, 28)
    unique = [int(value) for value in np.unique(reader.zone_grid[reader.zone_grid >= 0])]
    ksb = {zone_id: params[idx, 17] for idx, zone_id in enumerate(unique)}
    alphat = {zone_id: params[idx, 14] for idx, zone_id in enumerate(unique)}
    assert ksb[1] == pytest.approx(2.0e-7)
    assert ksb[2] == pytest.approx(9.0e-7)
    assert alphat[1] == pytest.approx(0.7)
    assert alphat[2] == pytest.approx(1.1)


def test_zfil_nodata_cells_stay_zero_not_median_fill(tmp_path):
    grid_path = tmp_path / "glacier.asc"
    grid_path.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 1",
                "NODATA_value -9999",
                "50.0 40.0",
                "-9999 10.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    solver = SimpleNamespace(
        fields=_FakeFields(),
        config=SimpleNamespace(
            spatial_zones=None,
            boundary_conditions=None,
            hydrology=SimpleNamespace(depthwt_initial=0.0, rizero_initial=0.0),
            soil=SimpleNamespace(double_layer=SimpleNamespace(ltstar=3.0)),
        ),
        numpy_float_dtype=np.float64,
        double_layer=_FakeDoubleLayer(),
        dfs_dynamic_wave=SimpleNamespace(set_initial_rikzero_field=lambda *_args, **_kwargs: None),
        rainfall_reader=None,
    )
    manifest = {
        "inputs": [
            {
                "family": "zfil",
                "path": str(grid_path),
                "original_branch_active": True,
                "production_status": "production-reachable",
            }
        ]
    }
    apply_native_runtime_inputs(solver, manifest)
    loaded = solver.fields.ltstar_field.value
    # ASCII (ny, nx) is transposed into field (nx, ny). NODATA stays 0, not the median.
    assert loaded.shape == (2, 2)
    np.testing.assert_allclose(loaded, np.array([[50.0, 0.0], [40.0, 10.0]]))
    np.testing.assert_allclose(solver.fields.erodible_thickness.value, loaded)
    assert np.all(loaded >= 0.0)
    assert not np.allclose(loaded, np.median([50.0, 40.0, 10.0]))
