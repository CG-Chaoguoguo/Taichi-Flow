from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from api.services.native_sidecar_loader import (
    load_precomputed_unsfin_schedule,
    load_inflow_runtime_payload,
    parse_cell_list_sidecar,
    parse_inflow_sidecar,
)


CASE_20A = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\NO.5_XHG_V2_20a(1)\NO.5_XHG_V2_20a")


def _write_ascii_grid(path: Path, values: np.ndarray, nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"ncols {values.shape[1]}\n")
        handle.write(f"nrows {values.shape[0]}\n")
        handle.write("xllcorner 0\n")
        handle.write("yllcorner 0\n")
        handle.write("cellsize 1\n")
        handle.write(f"NODATA_value {nodata}\n")
        for row in values:
            handle.write(" ".join(str(v) for v in row) + "\n")


def _valid_unsfin_meta(shape_kind: str) -> str:
    return json.dumps(
        {
            "shape_kind": shape_kind,
            "provider": "original_instrumented_unsfin",
            "dump_point": "after unsfin returns and before dfs enters",
        }
    )


def test_paired_case_outflow_sidecar_parses_as_point_ids():
    summary = parse_cell_list_sidecar(
        CASE_20A / "outflow.txt",
        "outflow.txt",
        CASE_20A / "data" / "tutorial" / "bcdem.asc",
    )
    assert summary["declared_cell_count"] == 53
    assert summary["parsed_cell_count"] == 53
    assert summary["grid_mapping_status"] == "mapped"


def test_paired_case_inflow_sidecar_audit_and_runtime_payload_parse():
    summary = parse_inflow_sidecar(
        CASE_20A / "inflow.txt",
        CASE_20A / "data" / "tutorial" / "bcdem.asc",
    )
    payload = load_inflow_runtime_payload(
        CASE_20A / "inflow.txt",
        CASE_20A / "data" / "tutorial" / "bcdem.asc",
    )

    assert summary["declared_cell_count"] == 5
    assert summary["expected_pulses_per_cell"] == 181
    assert payload["declared_cell_count"] == 5
    assert len(payload["configured_hydrographs"]) == 5
    assert len(payload["configured_hydrographs"][0]["series"]) == 181


def test_precomputed_unsfin_schedule_loader_requires_original_artifacts(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "LS_ScarEDDA_600.0.txt").write_text("1 1\n", encoding="utf-8")
    (case_dir / "faildphEDDA_600.0.txt").write_text("0.2 0.0\n", encoding="utf-8")

    payload = load_precomputed_unsfin_schedule(case_dir)

    assert payload["parse_status"] == "missing_artifacts"
    assert payload["runtime_arrays"] is None
    assert "precomputed_unsfin_tfail.txt" in payload["missing_artifacts"]


def test_precomputed_unsfin_schedule_loader_validates_shape_and_stats(tmp_path):
    case_dir = tmp_path / "case"
    dem_file = case_dir / "data" / "tutorial" / "bcdem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_gindx.txt", np.array([[1, 0], [0, 1]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_tfail.txt", np.array([[100.0, 9999.0], [9999.0, 700.0]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_fdepth.txt", np.array([[0.2, 0.0], [0.0, 0.4]], dtype=np.float64))
    (case_dir / "precomputed_unsfin_meta.json").write_text(
        _valid_unsfin_meta("dem_yx_grid"),
        encoding="utf-8",
    )

    payload = load_precomputed_unsfin_schedule(case_dir, dem_file=dem_file)

    assert payload["parse_status"] == "ok"
    assert payload["scheduled_cell_count"] == 2
    assert payload["gindx_nonzero_count"] == 2
    assert payload["fdepth_nonzero_count"] == 2
    assert payload["tfail_active_count"] == 2
    assert payload["tfail_lte_600_count"] == 1
    np.testing.assert_allclose(payload["runtime_arrays"]["tfail_s"], np.array([[100.0, 9999.0], [9999.0, 700.0]]).T)


def test_precomputed_unsfin_schedule_loader_maps_active_cell_vectors(tmp_path):
    case_dir = tmp_path / "case"
    dem_file = case_dir / "data" / "tutorial" / "bcdem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, -9999.0], [12.0, 13.0]], dtype=np.float64))
    np.savetxt(case_dir / "precomputed_unsfin_gindx.txt", np.array([1, 0, 1], dtype=np.float64))
    np.savetxt(case_dir / "precomputed_unsfin_tfail.txt", np.array([100.0, 9999.0, 700.0], dtype=np.float64))
    np.savetxt(case_dir / "precomputed_unsfin_fdepth.txt", np.array([0.2, 0.0, 0.4], dtype=np.float64))
    (case_dir / "precomputed_unsfin_meta.json").write_text(_valid_unsfin_meta("active_cell_vector"), encoding="utf-8")

    payload = load_precomputed_unsfin_schedule(case_dir, dem_file=dem_file)

    assert payload["parse_status"] == "ok"
    assert payload["runtime_orientation"] == "active_cell_vector_mapped_to_dem_valid_cells"
    assert payload["scheduled_cell_count"] == 2
    np.testing.assert_allclose(
        payload["runtime_arrays"]["tfail_s"],
        np.array([[100.0, 0.0], [9999.0, 700.0]], dtype=np.float64).T,
    )


def test_precomputed_unsfin_schedule_loader_fails_closed_on_output_inferred_meta(tmp_path):
    case_dir = tmp_path / "case"
    dem_file = case_dir / "data" / "tutorial" / "bcdem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_gindx.txt", np.array([[1, 0], [0, 1]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_tfail.txt", np.array([[100.0, 9999.0], [9999.0, 700.0]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_fdepth.txt", np.array([[0.2, 0.0], [0.0, 0.4]], dtype=np.float64))
    (case_dir / "precomputed_unsfin_meta.json").write_text(
        json.dumps({"shape_kind": "dem_yx_grid", "provider": "output_inferred", "source": "faildph"}),
        encoding="utf-8",
    )

    payload = load_precomputed_unsfin_schedule(case_dir, dem_file=dem_file)

    assert payload["parse_status"] == "invalid_meta"
    assert payload["runtime_arrays"] is None
    assert payload["meta_validation"]["valid"] is False


def test_precomputed_unsfin_schedule_loader_fails_closed_on_reference_failure_grid_mismatch(
    tmp_path, monkeypatch
):
    case_dir = tmp_path / "case"
    dem_file = case_dir / "data" / "tutorial" / "bcdem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_gindx.txt", np.array([[1, 1], [0, 1]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_tfail.txt", np.array([[100.0, 200.0], [9999.0, 700.0]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_fdepth.txt", np.array([[0.2, 0.3], [0.0, 0.4]], dtype=np.float64))
    (case_dir / "precomputed_unsfin_meta.json").write_text(
        _valid_unsfin_meta("dem_yx_grid"),
        encoding="utf-8",
    )
    _write_ascii_grid(case_dir / "results" / "LS_ScarEDDA_600.0.txt", np.array([[1, 0], [0, 1]], dtype=np.float64))
    _write_ascii_grid(case_dir / "results" / "faildphEDDA_600.0.txt", np.array([[0.2, 0.0], [0.0, 0.4]], dtype=np.float64))
    monkeypatch.setenv("EDDA_EXPERIMENT_VALIDATE_PRECOMPUTED_UNSFIN_FAILURE_GRID_MATCH", "1")

    payload = load_precomputed_unsfin_schedule(case_dir, dem_file=dem_file)

    assert payload["parse_status"] == "reference_failure_grid_mismatch"
    assert payload["runtime_arrays"] is None
    validation = payload["reference_failure_grid_validation"]
    assert validation["gindx_vs_lsscar_mismatch_count"] == 1
    assert validation["fdepth_vs_faildph_mismatch_count"] == 1
