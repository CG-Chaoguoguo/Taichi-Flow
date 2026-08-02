import pytest

from edda.io.topoindex_sidecar import run_rnoff_topoindex_runtime_consumer


def _write_synthetic_sidecars(tmp_path):
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    (sidecars / "nxtfil.asc").write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 10",
                "NODATA_value -9999",
                "2 4",
                "4 4",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    (sidecars / "ndxfil.txt").write_text("1 1\n2 2\n3 3\n4 4\n", encoding="ascii")
    (sidecars / "dscfil.txt").write_text(
        "\n".join(
            [
                "-9999",
                "1",
                "2",
                "4",
                "-9999",
                "2",
                "4",
                "-9999",
                "3",
                "4",
                "-9999",
                "4",
                "4",
                "-9999",
                "5",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    (sidecars / "wffil.txt").write_text(
        "\n".join(
            [
                "-9999",
                "1",
                "0.7",
                "0.3",
                "-9999",
                "2",
                "1.0",
                "-9999",
                "3",
                "1.0",
                "-9999",
                "4",
                "1.0",
                "-9999",
                "5",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    return sidecars


def _runtime_inputs(sidecar_dir):
    return {
        "nxtfil": sidecar_dir / "nxtfil.asc",
        "ndxfil": sidecar_dir / "ndxfil.txt",
        "dscfil": sidecar_dir / "dscfil.txt",
        "wffil": sidecar_dir / "wffil.txt",
        "imax": 4,
        "rideb": {1: 1.5, 2: 0.1, 3: 0.0, 4: 0.0},
        "kst": {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        "depth": {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0},
        "rizero": {1: 1e-9, 2: 1e-9, 3: 1e-9, 4: 1e-9},
    }


def _assert_direct_fallback(manifest):
    by_cell = {row["cell_id"]: row for row in manifest["cells"]}
    assert manifest["rnoff_topoindex_branch_active"] is False
    assert manifest["sidecar_shape_validated"] is False
    assert manifest["changed_field_names"] == []
    assert [by_cell[cell]["ro"] for cell in range(1, 5)] == pytest.approx([1.0, 0.0, 0.0, 0.0])
    assert [by_cell[cell]["rik"] for cell in range(1, 5)] == pytest.approx([1.0, 0.2, 0.0, 0.0])


def test_rnoff_topoindex_runtime_flag_off_keeps_direct_fallback(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)

    manifest = run_rnoff_topoindex_runtime_consumer(**_runtime_inputs(sidecar_dir), environ={})

    assert manifest["rnoff_topoindex_runtime_enabled"] is False
    assert manifest["rnoff_topoindex_selected"] is False
    assert manifest["default_off_verified"] is True
    assert manifest["fail_closed"] is False
    _assert_direct_fallback(manifest)


def test_rnoff_topoindex_runtime_flag_on_matches_original_oracle(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    by_cell = {row["cell_id"]: row for row in manifest["cells"]}
    assert manifest["rnoff_topoindex_runtime_enabled"] is True
    assert manifest["rnoff_topoindex_selected"] is True
    assert manifest["rnoff_topoindex_branch_active"] is True
    assert manifest["sidecar_shape_validated"] is True
    assert manifest["fail_closed"] is False
    assert manifest["nxt_count"] == 4
    assert manifest["indx_count"] == 4
    assert manifest["dsc_count"] == 5
    assert manifest["wf_count"] == 5
    assert manifest["changed_field_names"] == ["ir", "rik", "ro"]
    assert [by_cell[cell]["ro"] for cell in range(1, 5)] == pytest.approx([1.0, 0.3, 0.0, 0.1])
    assert [by_cell[cell]["rik"] for cell in range(1, 5)] == pytest.approx([1.0, 1.0, 0.0, 1.0])


@pytest.mark.parametrize(
    ("file_name", "family"),
    [
        ("nxtfil.asc", "nxtfil"),
        ("ndxfil.txt", "ndxfil"),
        ("dscfil.txt", "dscfil"),
        ("wffil.txt", "wffil"),
    ],
)
def test_rnoff_topoindex_runtime_missing_sidecar_fails_closed(tmp_path, file_name, family):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / file_name).unlink()

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    assert manifest["rnoff_topoindex_runtime_enabled"] is True
    assert manifest["fail_closed"] is True
    assert family in manifest["blocked_reason"]
    _assert_direct_fallback(manifest)


def test_rnoff_topoindex_runtime_flag_off_missing_sidecars_does_not_fail(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    for file_name in ("nxtfil.asc", "ndxfil.txt", "dscfil.txt", "wffil.txt"):
        (sidecar_dir / file_name).unlink()

    manifest = run_rnoff_topoindex_runtime_consumer(**_runtime_inputs(sidecar_dir), environ={})

    assert manifest["rnoff_topoindex_runtime_enabled"] is False
    assert manifest["fail_closed"] is False
    assert manifest["blocked_reason"] is None
    assert manifest["rnoff_topoindex_available"] is False
    _assert_direct_fallback(manifest)


def test_rnoff_topoindex_runtime_malformed_sidecar_fails_closed(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "dscfil.txt").write_text("-9999\n1\n5\n-9999\n2\n-9999\n3\n-9999\n4\n-9999\n5\n", encoding="ascii")

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    assert manifest["rnoff_topoindex_runtime_enabled"] is True
    assert manifest["rnoff_topoindex_branch_active"] is False
    assert manifest["sidecar_shape_validated"] is False
    assert manifest["fail_closed"] is True
    assert "receptor cell out of range" in manifest["blocked_reason"]
    assert manifest["changed_field_names"] == []


def test_rnoff_topoindex_runtime_malformed_shape_fails_closed(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "nxtfil.asc").write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 10",
                "NODATA_value -9999",
                "2 4",
                "4 -9999",
            ]
        )
        + "\n",
        encoding="ascii",
    )

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    assert manifest["fail_closed"] is True
    assert "active-cell count" in manifest["blocked_reason"]
    _assert_direct_fallback(manifest)


def test_rnoff_topoindex_runtime_invalid_one_based_cell_id_fails_closed(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "nxtfil.asc").write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 10",
                "NODATA_value -9999",
                "2 5",
                "4 4",
            ]
        )
        + "\n",
        encoding="ascii",
    )

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    assert manifest["fail_closed"] is True
    assert "out of range" in manifest["blocked_reason"]
    _assert_direct_fallback(manifest)


def test_rnoff_topoindex_runtime_invalid_indx_span_fails_closed(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "ndxfil.txt").write_text("1 1\n1 2\n3 3\n4 4\n", encoding="ascii")

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    assert manifest["fail_closed"] is True
    assert "duplicate position" in manifest["blocked_reason"]
    _assert_direct_fallback(manifest)


def test_rnoff_topoindex_runtime_nonfinite_weight_fails_closed(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "wffil.txt").write_text(
        "\n".join(
            [
                "-9999",
                "1",
                "1e999",
                "0.3",
                "-9999",
                "2",
                "1.0",
                "-9999",
                "3",
                "1.0",
                "-9999",
                "4",
                "1.0",
                "-9999",
                "5",
            ]
        )
        + "\n",
        encoding="ascii",
    )

    manifest = run_rnoff_topoindex_runtime_consumer(
        **_runtime_inputs(sidecar_dir),
        environ={"EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1"},
    )

    assert manifest["fail_closed"] is True
    assert "non-finite weight" in manifest["blocked_reason"]
    _assert_direct_fallback(manifest)
