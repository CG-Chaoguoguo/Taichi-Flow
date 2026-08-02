from pathlib import Path

import pytest

from api.services.edda_input_mapper import apply_native_runtime_inputs, build_reference_runtime_metadata
from api.services.reference_config_parser import parse_reference_config_file
from edda.io.hydrograph_exporter import (
    HydrographAccumulator,
    compare_hydrograph_outputs,
    parse_hydrograph_output,
    write_hydrograph_file,
    write_zero_flow_hydrograph_for_case,
)
from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver
from tests.test_native_input_chain import _make_reference_case


def test_hydrograph_writer_matches_original_zero_flow_schema(tmp_path):
    oracle = tmp_path / "oracle" / "HYDROGRAPH_EDDA.txt"
    oracle.parent.mkdir()
    oracle.write_text(
        "\n".join(
            [
                "THE MAX Q AT HYDROGRAPH ELEMENT:   8716IS:   0.00 CM/s AT TIME:   0.00",
                "ELEMENT       TIME (HRS)     DISCHARGE (CMS)CV",
                "  8716          0.00             0.00       0.0000",
                "                0.02             0.00       0.0000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    accumulator = HydrographAccumulator([8716])
    accumulator.record_checkpoint(
        time_hours=0.0,
        values={8716: {"discharge_cms": 0.0, "cv": 0.0}},
    )
    accumulator.record_checkpoint(
        time_hours=60.0 / 3600.0,
        values={8716: {"discharge_cms": 0.0, "cv": 0.0}},
    )
    current = write_hydrograph_file(
        tmp_path / "current" / "HYDROGRAPH_EDDA.txt",
        cell_ids=[8716],
        samples_by_cell=accumulator.samples_by_cell,
        max_discharge=accumulator.max_discharge,
        max_time_hours=accumulator.max_time_hours,
    )

    comparison = compare_hydrograph_outputs(oracle, current)
    assert comparison["matches"] is True
    assert comparison["current"]["monitored_cells"] == [8716]
    assert comparison["current"]["time_stamps_hours"] == [0.0, 0.02]


def test_hydrograph_comparison_checks_nonzero_max_q_line(tmp_path):
    oracle = tmp_path / "oracle" / "HYDROGRAPH_EDDA.txt"
    oracle.parent.mkdir()
    oracle.write_text(
        "\n".join(
            [
                "THE MAX Q AT HYDROGRAPH ELEMENT:  34726IS:  88.33 CM/s AT TIME:   0.02",
                "ELEMENT       TIME (HRS)     DISCHARGE (CMS)CV",
                " 34726          0.00             0.00       0.0000",
                "                0.02            75.09       -.0000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    accumulator = HydrographAccumulator([34726])
    accumulator.record_checkpoint(
        time_hours=0.0,
        values={34726: {"discharge_cms": 0.0, "cv": 0.0}},
    )
    accumulator.record_checkpoint(
        time_hours=60.0 / 3600.0,
        values={34726: {"discharge_cms": 75.09, "cv": 0.0}},
    )

    sample_only_max = write_hydrograph_file(
        tmp_path / "current_sample_only" / "HYDROGRAPH_EDDA.txt",
        cell_ids=[34726],
        samples_by_cell=accumulator.samples_by_cell,
        max_discharge={34726: 75.09},
        max_time_hours={34726: 60.0 / 3600.0},
    )
    sample_only_comparison = compare_hydrograph_outputs(oracle, sample_only_max)
    assert sample_only_comparison["matches"] is False
    assert sample_only_comparison["max_line_abs_discharge_delta"] == pytest.approx(13.24)

    current = write_hydrograph_file(
        tmp_path / "current" / "HYDROGRAPH_EDDA.txt",
        cell_ids=[34726],
        samples_by_cell=accumulator.samples_by_cell,
        max_discharge={34726: 88.33},
        max_time_hours={34726: 60.0 / 3600.0},
    )
    comparison = compare_hydrograph_outputs(oracle, current)
    assert comparison["matches"] is True
    assert comparison["max_line_abs_discharge_delta"] == 0.0


def test_zero_flow_hydrograph_dry_run_requires_hydrosave_sidecar(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace(
            "Save hydrograph of specified cells? Enter T (.true.) or F (.false.)\nF",
            "Save hydrograph of specified cells? Enter T (.true.) or F (.false.)\nT",
        ).replace(
            "0.00001 2.0 0.0001 0.001 7200.0 3600.0 0.1 0.05 0.25",
            "0.00001 2.0 0.0001 0.001 60.0 60.0 0.1 0.05 0.25",
        ),
        encoding="utf-8",
    )

    manifest = write_zero_flow_hydrograph_for_case(edda_in.parent, tmp_path / "dry_run")
    parsed = parse_hydrograph_output(manifest["output_file"])

    assert manifest["written"] is True
    assert manifest["hydrograph_sidecar"]["cell_ids"] == [2]
    assert parsed["sample_count"] == 2
    assert [row["time_hrs"] for row in parsed["rows"] if row["record_type"] == "sample"] == [0.0, 0.02]

    (edda_in.parent / "hydrograph.txt").unlink()
    with pytest.raises(FileNotFoundError):
        write_zero_flow_hydrograph_for_case(edda_in.parent, tmp_path / "missing_sidecar")


def test_real_solver_configures_hydrograph_monitor_when_original_branch_is_active(tmp_path):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    edda_in.write_text(
        text.replace(
            "Save hydrograph of specified cells? Enter T (.true.) or F (.false.)\nF",
            "Save hydrograph of specified cells? Enter T (.true.) or F (.false.)\nT",
        ),
        encoding="utf-8",
    )
    parsed = parse_reference_config_file(str(edda_in))
    config, _, runtime_input_manifest, _ = build_reference_runtime_metadata(
        parsed,
        tmp_path / "out",
        config_overrides={
            "compute": {"backend": "cpu", "use_double_precision": True},
            "save_intermediate": False,
            "time": {"t_end": 1.0, "dt_output": 1.0},
        },
    )
    solver = EDDASolver(config)
    solver.initialize()
    runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["hydrograph.txt"]["consumed"] is True
    assert manifest["hydrograph.txt"]["current_backend_branch_active"] is True
    assert solver.hydrograph_monitor_observer is not None
    assert solver.hydrograph_monitor_observer["configured_cell_count"] == 1

    output = solver._export_hydrograph_monitor_text()
    assert output is not None
    parsed_output = parse_hydrograph_output(output)
    assert parsed_output["monitored_cells"] == [2]
    assert parsed_output["sample_count"] == 1
