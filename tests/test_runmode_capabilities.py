"""Run-mode capability registry regressions."""

from pathlib import Path

from api.services.runmode_capabilities import (
    build_runmode_capabilities,
    write_runmode_capabilities_file,
)
from edda.config.sim_config import SimulationConfig


def test_runmode_capability_registry_reports_switchable_and_blocked_items():
    payload = build_runmode_capabilities(source_mode="unit_test")

    capabilities = {entry["key"]: entry for entry in payload["capabilities"]}
    assert capabilities["hydrology.use_background_flux_offset"]["current_backend_status"] == "implemented_and_switchable"
    assert capabilities["hydrology.use_background_flux_offset"]["frontend_exposure_policy"] == "switchable"
    assert capabilities["flags.use_full_dynamic_wave"]["current_backend_status"] == "blocked_by_missing_source_trace"
    assert capabilities["flags.log_mass_balance_results"]["current_backend_status"] == "partial"
    assert capabilities["flags.simulate_rainfall"]["frontend_exposure_policy"] == "fixed_path"
    assert capabilities["native_inputs.zonfil"]["frontend_exposure_policy"] == "importable_auditable"
    assert capabilities["sidecar.hydrograph.txt"]["current_backend_status"] == "partial"
    assert capabilities["sidecar.inflow.txt"]["current_backend_status"] == "partial"
    assert capabilities["sidecar.EDDALog.txt"]["current_backend_status"] == "partial"
    assert capabilities["soil.double_layer.uww"]["current_backend_status"] == "implemented_but_fixed_scientific_path"
    assert capabilities["sidecar.inflow.txt"]["source_trace_status"] == "anchored"
    assert payload["summary"]["switchable_keys"] == ["hydrology.use_background_flux_offset"]


def test_runmode_capability_registry_records_configured_background_flux_value(tmp_path):
    dem_file = tmp_path / "tiny.asc"
    dem_file.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 1",
                "NODATA_value -9999",
                "1 1",
                "1 1",
            ]
        ),
        encoding="ascii",
    )

    config = SimulationConfig.from_dict(
        {
            "dem_file": str(dem_file),
            "output_dir": str(tmp_path / "out"),
            "hydrology": {"use_background_flux_offset": True},
        }
    )
    payload = write_runmode_capabilities_file(
        tmp_path / "out",
        config=config,
        reference_audit={"flags": {"use_full_dynamic_wave": True}},
        source_mode="reference_config",
    )

    stored = (tmp_path / "out" / "runmode_capabilities.json").read_text(encoding="utf-8")
    assert "hydrology.use_background_flux_offset" in stored

    capabilities = {entry["key"]: entry for entry in payload["capabilities"]}
    assert capabilities["hydrology.use_background_flux_offset"]["configured_value"] is True
    assert capabilities["flags.use_full_dynamic_wave"]["configured_value"] is True
