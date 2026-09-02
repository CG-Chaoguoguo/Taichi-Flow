"""
DEM (Digital Elevation Model) reader supporting multiple formats.
"""
import numpy as np
import rasterio
from rasterio.fill import fillnodata
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class DEMReader:
    """
    Read and process DEM files in various formats.
    Supports GeoTIFF, ASCII Grid, and other GDAL-compatible formats.
    """

    def __init__(self, dem_file: str):
        """
        Initialize DEM reader.

        Args:
            dem_file: Path to DEM file
        """
        self.dem_file = Path(dem_file)
        if not self.dem_file.exists():
            raise FileNotFoundError(f"DEM file not found: {dem_file}")

        self.elevation = None
        self.transform = None
        self.crs = None
        self.nodata_value = None
        self.metadata = {}

    def read(self) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Read DEM file and return elevation data with metadata.

        Returns:
            elevation: 2D numpy array of elevation values
            metadata: Dictionary containing spatial metadata
        """
        logger.info(f"Reading DEM file: {self.dem_file}")

        suffix = self.dem_file.suffix.lower()
        if suffix in {".asc", ".txt"}:
            self.elevation, self.metadata = read_ascii_grid(str(self.dem_file))
            self.transform = None
            self.crs = None
            self.nodata_value = self.metadata.get('nodata', self.metadata.get('nodata_value'))
            self.metadata.setdefault('transform', None)
            self.metadata.setdefault('crs', None)
            logger.info(f"DEM dimensions: {self.metadata['width']} x {self.metadata['height']}")
            logger.info(f"Grid spacing: dx={self.metadata['dx']:.2f}m, dy={self.metadata['dy']:.2f}m")
            logger.info(f"NoData value: {self.nodata_value}")
            return self.elevation, self.metadata

        with rasterio.open(self.dem_file) as src:
            # Read elevation data
            self.elevation = src.read(1, masked=False)

            # Read metadata
            self.transform = src.transform
            self.crs = src.crs
            self.nodata_value = src.nodata
            self.metadata = {
                'width': src.width,
                'height': src.height,
                'crs': str(src.crs),
                'transform': src.transform,
                'bounds': src.bounds,
                'nodata': src.nodata,
                'dtype': src.dtypes[0],
            }

            # Calculate grid spacing
            self.metadata['dx'] = abs(src.transform[0])
            self.metadata['dy'] = abs(src.transform[4])

            logger.info(f"DEM dimensions: {src.width} x {src.height}")
            logger.info(f"Grid spacing: dx={self.metadata['dx']:.2f}m, dy={self.metadata['dy']:.2f}m")
            logger.info(f"CRS: {src.crs}")
            logger.info(f"NoData value: {src.nodata}")

        return self.elevation, self.metadata

    def get_nodata_mask(self) -> np.ndarray:
        """
        Get boolean mask of NoData cells.

        Returns:
            mask: Boolean array where True indicates NoData
        """
        if self.elevation is None:
            raise ValueError("DEM not loaded. Call read() first.")

        if self.nodata_value is not None:
            mask = np.isclose(self.elevation, self.nodata_value)
        else:
            # Check for NaN or inf values
            mask = ~np.isfinite(self.elevation)

        nodata_count = np.sum(mask)
        total_cells = mask.size
        nodata_percent = 100.0 * nodata_count / total_cells

        logger.info(f"NoData cells: {nodata_count} ({nodata_percent:.2f}%)")

        return mask

    def fill_nodata(self, max_search_distance: float = 100.0, smoothing_iterations: int = 0) -> np.ndarray:
        """
        Fill NoData values using interpolation.

        Args:
            max_search_distance: Maximum distance to search for valid pixels (in pixels)
            smoothing_iterations: Number of smoothing iterations

        Returns:
            filled_elevation: Elevation array with NoData filled
        """
        if self.elevation is None:
            raise ValueError("DEM not loaded. Call read() first.")

        logger.info("Filling NoData values...")

        # Create a masked array
        mask = self.get_nodata_mask()

        if not np.any(mask):
            logger.info("No NoData values found.")
            return self.elevation.copy()

        # Use rasterio's fillnodata function
        filled = self.elevation.copy()
        # rasterio.fill.fillnodata uses 0 for cells to interpolate and >0 for
        # cells that may contribute values. Convert our True=NoData mask to
        # that convention explicitly.
        filled_mask = (~mask).astype(np.uint8)

        filled = fillnodata(
            filled,
            mask=filled_mask,
            max_search_distance=max_search_distance,
            smoothing_iterations=smoothing_iterations
        )

        logger.info("NoData filling complete.")

        return filled

    def get_grid_coordinates(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get grid coordinates (X, Y) for each cell center.

        Returns:
            X: 2D array of X coordinates
            Y: 2D array of Y coordinates
        """
        if self.transform is None:
            raise ValueError("DEM not loaded. Call read() first.")

        height, width = self.elevation.shape

        # Create coordinate arrays
        cols, rows = np.meshgrid(np.arange(width), np.arange(height))

        # Transform to spatial coordinates
        X, Y = rasterio.transform.xy(self.transform, rows, cols)
        X = np.array(X)
        Y = np.array(Y)

        return X, Y

    def get_extent(self) -> Tuple[float, float, float, float]:
        """
        Get spatial extent of DEM.

        Returns:
            (xmin, xmax, ymin, ymax)
        """
        if self.metadata is None or 'bounds' not in self.metadata:
            raise ValueError("DEM not loaded. Call read() first.")

        bounds = self.metadata['bounds']
        return (bounds.left, bounds.right, bounds.bottom, bounds.top)

    def get_statistics(self) -> Dict[str, float]:
        """
        Calculate elevation statistics.

        Returns:
            Dictionary with min, max, mean, std statistics
        """
        if self.elevation is None:
            raise ValueError("DEM not loaded. Call read() first.")

        # Mask NoData values
        mask = self.get_nodata_mask()
        valid_data = self.elevation[~mask]

        if len(valid_data) == 0:
            raise ValueError("No valid elevation data found.")

        stats = {
            'min': float(np.min(valid_data)),
            'max': float(np.max(valid_data)),
            'mean': float(np.mean(valid_data)),
            'std': float(np.std(valid_data)),
            'median': float(np.median(valid_data)),
        }

        logger.info(f"Elevation statistics: min={stats['min']:.2f}m, max={stats['max']:.2f}m, "
                   f"mean={stats['mean']:.2f}m, std={stats['std']:.2f}m")

        return stats


def read_ascii_grid(ascii_file: str) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Read ASCII Grid format (ESRI ASCII Raster).

    Args:
        ascii_file: Path to ASCII grid file

    Returns:
        elevation: 2D numpy array
        metadata: Dictionary with grid metadata
    """
    logger.info(f"Reading ASCII grid: {ascii_file}")

    metadata = {}

    with open(ascii_file, 'r') as f:
        # Read header
        for _ in range(6):
            line = f.readline().strip().split()
            key = line[0].lower()
            value = float(line[1]) if '.' in line[1] else int(line[1])
            metadata[key] = value

        # Read elevation data
        elevation = np.loadtxt(f)

    # Extract key parameters
    ncols = int(metadata.get('ncols', 0))
    nrows = int(metadata.get('nrows', 0))
    xllcorner = metadata.get('xllcorner', 0.0)
    yllcorner = metadata.get('yllcorner', 0.0)
    cellsize = metadata.get('cellsize', 1.0)
    nodata = metadata.get('nodata_value', -9999.0)

    metadata['width'] = ncols
    metadata['height'] = nrows
    metadata['dx'] = cellsize
    metadata['dy'] = cellsize
    metadata['nodata'] = nodata
    metadata['bounds'] = (xllcorner, xllcorner + ncols * cellsize,
                         yllcorner, yllcorner + nrows * cellsize)

    logger.info(f"ASCII grid dimensions: {ncols} x {nrows}")
    logger.info(f"Cell size: {cellsize}m")

    return elevation, metadata
