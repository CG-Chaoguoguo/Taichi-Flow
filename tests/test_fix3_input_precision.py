from __future__ import annotations

import math

import numpy as np

from edda.io.dem_reader import DEMReader, is_esri_ascii_grid
from edda.io.result_exporter import ResultExporter
from edda.io.spatial_input_loader import SpatialInputLoader


def _write_ascii_blob(path) -> None:
    path.write_text(
        "\n".join(
            (
                "ncols 2",
                "nrows 2",
                "xllcorner 0.0",
                "yllcorner 0.0",
                "cellsize 30.0",
                "NODATA_value -9999",
                "5253.389 5224.500",
                "5226.359 5199.000",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def test_content_addressed_ascii_blob_preserves_float64_dem_precision(tmp_path) -> None:
    blob = tmp_path / "6a093976dfa8370402bb6060edc88b3b"
    _write_ascii_blob(blob)

    assert is_esri_ascii_grid(blob)
    elevation, metadata = DEMReader(str(blob)).read()

    assert elevation.dtype == np.float64
    assert metadata["nodata"] == -9999
    assert metadata["transform"].c == 0.0
    assert metadata["transform"].f == 60.0
    assert metadata["transform"].a == 30.0
    assert metadata["transform"].e == -30.0
    expected_slope = math.atan((5253.389 - 5224.500) / 30.0)
    f32_slope = math.atan(float(np.float32(5253.389) - np.float32(5224.500)) / 30.0)
    assert math.isclose(math.atan((elevation[0, 0] - elevation[0, 1]) / 30.0), expected_slope, rel_tol=0.0, abs_tol=1e-15)
    assert not math.isclose(expected_slope, f32_slope, rel_tol=0.0, abs_tol=1e-8)


def test_content_addressed_ascii_blob_uses_same_spatial_input_path(tmp_path) -> None:
    blob = tmp_path / "immutable-input-blob"
    _write_ascii_blob(blob)

    data, metadata = SpatialInputLoader(str(blob)).read()

    assert data.dtype == np.float64
    assert data.shape == (2, 2)
    assert metadata["dx"] == 30.0
    assert metadata["transform"].c == 0.0
    assert metadata["transform"].f == 60.0


def test_ascii_dem_transform_is_preserved_by_ascii_result_export(tmp_path) -> None:
    blob = tmp_path / "immutable-input-blob"
    _write_ascii_blob(blob)
    elevation, metadata = DEMReader(str(blob)).read()
    output = tmp_path / "result.asc"

    ResultExporter(elevation, transform=metadata["transform"], nodata_value=-9999.0).to_ascii_grid(str(output))

    header = output.read_text(encoding="ascii").splitlines()[:6]
    assert header[2] == "xllcorner     0.0"
    assert header[3] == "yllcorner     0.0"
    assert header[4] == "cellsize      30.0"
