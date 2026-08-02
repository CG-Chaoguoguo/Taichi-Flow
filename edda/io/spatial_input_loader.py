"""Generic single-band raster loader for production native input families."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import rasterio

from edda.io.dem_reader import read_ascii_grid


class SpatialInputLoader:
    """Read single-band spatial inputs used by the native EDDA input chain."""

    def __init__(self, input_file: str):
        self.input_file = Path(input_file)
        if not self.input_file.exists():
            raise FileNotFoundError(f"Spatial input file not found: {input_file}")

    def read(self) -> Tuple[np.ndarray, Dict[str, Any]]:
        suffix = self.input_file.suffix.lower()
        if suffix in {".asc", ".txt"}:
            data, metadata = read_ascii_grid(str(self.input_file))
            metadata.setdefault("transform", None)
            metadata.setdefault("crs", None)
            metadata.setdefault("nodata", metadata.get("nodata_value", -9999.0))
            return data, metadata

        with rasterio.open(self.input_file) as src:
            data = src.read(1, masked=False)
            metadata = {
                "width": src.width,
                "height": src.height,
                "crs": str(src.crs),
                "transform": src.transform,
                "bounds": src.bounds,
                "nodata": src.nodata,
                "dtype": src.dtypes[0],
                "dx": abs(src.transform[0]),
                "dy": abs(src.transform[4]),
            }
        return data, metadata


def fill_raster_nodata(data: np.ndarray, nodata_value: Any, fallback: float) -> np.ndarray:
    """Replace nodata values using a deterministic constant fallback."""
    if nodata_value is None:
        return data
    mask = np.isclose(data, nodata_value)
    if not np.any(mask):
        return data
    return np.where(mask, fallback, data)
