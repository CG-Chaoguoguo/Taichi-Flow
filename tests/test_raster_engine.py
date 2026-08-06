from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import Affine, from_origin  # noqa: E402

from api.services.raster_engine import build_lossless_cog, identify_raster, read_raster_profile  # noqa: E402


def _write_fixture(path: Path) -> None:
    values = np.array([[1.25, 2.5, -9999.0], [4.0, 5.75, 6.0]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="float32",
        nodata=-9999.0,
        transform=from_origin(100, 206, 2, 3),
    ) as dataset:
        dataset.write(values, 1)


def test_profile_uses_affine_and_exact_statistics(tmp_path: Path) -> None:
    source = tmp_path / "fixture.tif"
    _write_fixture(source)

    profile = read_raster_profile(source, sha256="fixture-sha", family="dem")

    assert profile["status"] == "ready"
    assert profile["bounds"] == {"xmin": 100.0, "ymin": 200.0, "xmax": 106.0, "ymax": 206.0}
    assert profile["transform"] == {"a": 2.0, "b": 0.0, "c": 100.0, "d": 0.0, "e": -3.0, "f": 206.0}
    assert profile["statistics"]["min"] == 1.25
    assert profile["statistics"]["max"] == 6.0
    assert profile["statistics"]["valid_count"] == 5
    assert profile["statistics"]["nodata_count"] == 1


def test_identify_returns_source_value_and_neighborhood(tmp_path: Path) -> None:
    source = tmp_path / "fixture.tif"
    _write_fixture(source)

    result = identify_raster(
        source,
        sha256="fixture-sha",
        family="dem",
        x=103.0,
        y=201.5,
        neighborhood_size=3,
    )

    assert result["status"] == "value"
    assert result["row_one_based"] == 2
    assert result["column_one_based"] == 2
    assert result["raw"]["value"] == pytest.approx(5.75)
    assert result["raw"]["value_text"] == "5.75"
    assert result["neighborhood"]["value_text"] == [
        ["1.25", "2.5", "NoData"],
        ["4", "5.75", "6"],
        ["Outside", "Outside", "Outside"],
    ]


def test_identify_returns_nodata_not_estimate(tmp_path: Path) -> None:
    source = tmp_path / "fixture.tif"
    _write_fixture(source)

    result = identify_raster(
        source,
        sha256="fixture-sha",
        family="dem",
        x=105.0,
        y=204.5,
        neighborhood_size=3,
    )

    assert result["status"] == "nodata"
    assert result["raw"] == {"value": None, "value_text": "NoData", "is_nodata": True}


def test_lossless_cog_preserves_base_pixels(tmp_path: Path) -> None:
    source = tmp_path / "fixture.tif"
    destination = tmp_path / "cache" / "source.cog.tif"
    _write_fixture(source)

    build_lossless_cog(source, destination, data_kind="continuous")
    with rasterio.open(source) as source_dataset, rasterio.open(destination) as cache_dataset:
        assert cache_dataset.driver == "GTiff"
        assert np.array_equal(source_dataset.read(1), cache_dataset.read(1))
        assert cache_dataset.nodata == source_dataset.nodata
        assert cache_dataset.transform == source_dataset.transform


@pytest.mark.parametrize("origin_header", ["xllcorner", "xllcenter"])
def test_ascii_corner_and_center_headers_share_the_same_affine_grid(tmp_path: Path, origin_header: str) -> None:
    source = tmp_path / f"{origin_header}.asc"
    x_origin = 10.0 if origin_header == "xllcorner" else 11.0
    y_origin = 20.0 if origin_header == "xllcorner" else 21.0
    source.write_text(
        "\n".join(
            [
                "ncols 2",
                "nrows 2",
                f"{origin_header} {x_origin}",
                f"yll{origin_header[3:]} {y_origin}",
                "cellsize 2",
                "NODATA_value -9999",
                "1 2",
                "3 4",
                "",
            ]
        ),
        encoding="ascii",
    )

    profile = read_raster_profile(source, sha256="ascii-sha", family="dem")

    assert profile["bounds"] == {"xmin": 10.0, "ymin": 20.0, "xmax": 14.0, "ymax": 24.0}
    assert profile["transform"] == {"a": 2.0, "b": 0.0, "c": 10.0, "d": 0.0, "e": -2.0, "f": 24.0}
    center = identify_raster(source, sha256="ascii-sha", family="dem", x=11.0, y=23.0)
    assert center["status"] == "value"
    assert center["row"] == 0 and center["column"] == 0
    assert center["raw"]["value"] == 1


def test_identify_uses_half_open_bounds_and_rejects_right_top_edge(tmp_path: Path) -> None:
    source = tmp_path / "fixture.tif"
    _write_fixture(source)

    outside = identify_raster(source, sha256="fixture-sha", family="dem", x=106.0, y=206.0)

    assert outside["status"] == "outside"
    assert outside["row"] is None and outside["column"] is None


def test_nan_is_reported_as_nodata_and_rotated_grid_is_unsupported(tmp_path: Path) -> None:
    nan_source = tmp_path / "nan.tif"
    values = np.array([[1.0, np.nan], [3.0, 4.0]], dtype="float32")
    with rasterio.open(
        nan_source,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        transform=from_origin(0, 4, 1, 1),
    ) as dataset:
        dataset.write(values, 1)

    nan_value = identify_raster(nan_source, sha256="nan-sha", family="dem", x=1.5, y=3.5)
    assert nan_value["status"] == "nodata"
    assert nan_value["raw"]["value"] is None

    rotated_source = tmp_path / "rotated.tif"
    with rasterio.open(
        rotated_source,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="int16",
        transform=Affine(1, 0.2, 0, 0, -1, 2),
    ) as dataset:
        dataset.write(np.ones((2, 2), dtype="int16"), 1)

    profile = read_raster_profile(rotated_source, sha256="rotated-sha", family="dem")
    assert profile["status"] == "unsupported"
    assert profile["capabilities"]["display"] is False
