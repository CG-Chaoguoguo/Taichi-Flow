from __future__ import annotations

from pathlib import Path

import numpy as np

from edda.io.dem_reader import DEMReader
from edda.io.result_exporter import ResultExporter


ASCII_GRID = """ncols 3
nrows 2
xllcorner 100
yllcorner 200
cellsize 20
NODATA_value -9999
1 2 3
4 -9999 6
"""


def test_extensionless_ascii_grid_preserves_missing_crs_as_none(tmp_path: Path) -> None:
    blob_path = tmp_path / "sha256_blob_without_suffix"
    blob_path.write_text(ASCII_GRID, encoding="utf-8")

    elevation, metadata = DEMReader(str(blob_path)).read()

    assert elevation.shape == (2, 3)
    assert metadata["crs"] is None
    assert metadata["transform"] is None


def test_extensionless_ascii_grid_can_reach_geotiff_fallback(tmp_path: Path) -> None:
    blob_path = tmp_path / "sha256_blob_without_suffix"
    blob_path.write_text(ASCII_GRID, encoding="utf-8")
    elevation, metadata = DEMReader(str(blob_path)).read()
    output_path = tmp_path / "result.tif"

    ResultExporter(
        data=np.asarray(elevation, dtype=np.float64),
        transform=metadata.get("transform"),
        crs=metadata.get("crs"),
        nodata_value=-9999.0,
    ).to_geotiff(str(output_path))

    assert output_path.is_file()
