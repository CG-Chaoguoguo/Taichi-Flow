import pytest

from edda.io.topoindex_sidecar import (
    TopoIndexSidecarError,
    build_rnoff_pre_dfs_period_precompute_contract,
    load_topoindex_sidecars,
    precompute_contract_to_manifest,
    run_rnoff_topoindex_dry_run,
)


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


def test_rnoff_topoindex_dry_run_matches_synthetic_original_oracle(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    sidecars = load_topoindex_sidecars(
        nxtfil=sidecar_dir / "nxtfil.asc",
        ndxfil=sidecar_dir / "ndxfil.txt",
        dscfil=sidecar_dir / "dscfil.txt",
        wffil=sidecar_dir / "wffil.txt",
        imax=4,
    )

    result = run_rnoff_topoindex_dry_run(
        sidecars,
        rideb={1: 1.5, 2: 0.1, 3: 0.0, 4: 0.0},
        kst={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        depth={1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0},
        rizero={1: 1e-9, 2: 1e-9, 3: 1e-9, 4: 1e-9},
    )

    by_cell = {row["cell_id"]: row for row in result.cells}
    assert result.sidecar_branch_active is True
    assert [row["dsc"] for row in result.sidecar_mappings] == [2, 4, 4, 4, 4]
    assert [row["wf"] for row in result.sidecar_mappings] == pytest.approx([0.7, 0.3, 1.0, 1.0, 1.0])
    assert [by_cell[cell]["ro"] for cell in range(1, 5)] == pytest.approx([1.0, 0.3, 0.0, 0.1])
    assert [by_cell[cell]["rik"] for cell in range(1, 5)] == pytest.approx([1.0, 1.0, 0.0, 1.0])
    assert by_cell[2]["rik_direct_fallback"] == pytest.approx(0.2)
    assert by_cell[4]["rik_direct_fallback"] == pytest.approx(0.0)


def test_rnoff_topoindex_loader_rejects_incomplete_sidecar_family(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "wffil.txt").unlink()

    with pytest.raises(FileNotFoundError):
        load_topoindex_sidecars(
            nxtfil=sidecar_dir / "nxtfil.asc",
            ndxfil=sidecar_dir / "ndxfil.txt",
            dscfil=sidecar_dir / "dscfil.txt",
            wffil=sidecar_dir / "wffil.txt",
            imax=4,
        )


def test_rnoff_topoindex_loader_rejects_invalid_receptor_cell(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "dscfil.txt").write_text("-9999\n1\n5\n-9999\n2\n-9999\n3\n-9999\n4\n-9999\n5\n", encoding="ascii")

    with pytest.raises(TopoIndexSidecarError, match="receptor cell out of range"):
        load_topoindex_sidecars(
            nxtfil=sidecar_dir / "nxtfil.asc",
            ndxfil=sidecar_dir / "ndxfil.txt",
            dscfil=sidecar_dir / "dscfil.txt",
            wffil=sidecar_dir / "wffil.txt",
            imax=4,
        )


def test_rnoff_pre_dfs_precompute_contract_is_default_off_and_non_mutating(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)

    contract = build_rnoff_pre_dfs_period_precompute_contract(
        nxtfil=sidecar_dir / "nxtfil.asc",
        ndxfil=sidecar_dir / "ndxfil.txt",
        dscfil=sidecar_dir / "dscfil.txt",
        wffil=sidecar_dir / "wffil.txt",
        imax=4,
        rideb_periods=[{1: 1.5, 2: 0.1, 3: 0.0, 4: 0.0}],
        kst={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        environ={},
    )
    manifest = precompute_contract_to_manifest(contract)

    assert manifest["contract_name"] == "SOURCE_ALIGNED_PRE_DFS_PRECOMPUTE_CONTRACT"
    assert manifest["current_bridge_name"] == "CURRENT_DFS_INTERNAL_BRIDGE_HOOK"
    assert manifest["contract_generation_enabled"] is False
    assert manifest["runtime_mutation"] is False
    assert manifest["dfs_runtime_mutation"] is False
    assert manifest["native_unsfin_runtime_feed"] is False
    assert manifest["periods"] == []
    assert manifest["sidecar_shape_validated"] is False
    assert manifest["default_off_verified"] is True


def test_rnoff_pre_dfs_precompute_contract_generates_period_arrays(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)

    contract = build_rnoff_pre_dfs_period_precompute_contract(
        nxtfil=sidecar_dir / "nxtfil.asc",
        ndxfil=sidecar_dir / "ndxfil.txt",
        dscfil=sidecar_dir / "dscfil.txt",
        wffil=sidecar_dir / "wffil.txt",
        imax=4,
        rideb_periods=[
            {1: 1.5, 2: 0.1, 3: 0.0, 4: 0.0},
            {1: 0.0, 2: 1.2, 3: 0.0, 4: 0.0},
        ],
        kst={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        depth={1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0},
        rizero={1: 1e-9, 2: 1e-9, 3: 1e-9, 4: 1e-9},
        diagnostic_request=True,
        case_path=tmp_path,
    )
    manifest = contract.manifest

    assert manifest["contract_generation_enabled"] is True
    assert manifest["diagnostic_request"] is True
    assert manifest["sidecar_shape_validated"] is True
    assert manifest["period_count"] == 2
    assert manifest["rik_unsfin_input_candidate"] is True
    assert manifest["rik_unsfin_runtime_integrated"] is False
    assert manifest["claims"]["changes_dfs_predictors"] is False

    period_1 = manifest["periods"][0]
    period_2 = manifest["periods"][1]
    assert period_1["ro_period"] == {"1": pytest.approx(1.0), "2": pytest.approx(0.3), "3": pytest.approx(0.0), "4": pytest.approx(0.1)}
    assert period_1["rik_period"] == {"1": pytest.approx(1.0), "2": pytest.approx(1.0), "3": pytest.approx(0.0), "4": pytest.approx(1.0)}
    assert period_1["ir_period"] == {"1": pytest.approx(0.5), "2": pytest.approx(0.5), "3": pytest.approx(0.0), "4": pytest.approx(0.5)}
    assert period_2["ro_period"]["2"] == pytest.approx(0.7)
    assert period_2["rik_period"]["2"] == pytest.approx(1.0)
    assert manifest["sidecar_provenance"]["sha256"]["nxtfil"]


def test_rnoff_pre_dfs_precompute_contract_fail_closes_on_missing_sidecar(tmp_path):
    sidecar_dir = _write_synthetic_sidecars(tmp_path)
    (sidecar_dir / "wffil.txt").unlink()

    contract = build_rnoff_pre_dfs_period_precompute_contract(
        nxtfil=sidecar_dir / "nxtfil.asc",
        ndxfil=sidecar_dir / "ndxfil.txt",
        dscfil=sidecar_dir / "dscfil.txt",
        wffil=sidecar_dir / "wffil.txt",
        imax=4,
        rideb_periods=[{1: 1.5, 2: 0.1, 3: 0.0, 4: 0.0}],
        kst={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        diagnostic_request=True,
    )
    manifest = contract.manifest

    assert manifest["contract_generation_enabled"] is True
    assert manifest["fail_closed"] is True
    assert manifest["sidecar_shape_validated"] is False
    assert manifest["periods"] == []
    assert "wffil" in manifest["blocked_reason"]
