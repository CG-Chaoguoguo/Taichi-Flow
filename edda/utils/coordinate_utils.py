"""
Coordinate transformation utilities for handling different CRS and projections.
"""
import numpy as np
from typing import Tuple, Optional, Union, List
import logging

logger = logging.getLogger(__name__)


class CoordinateTransformer:
    """
    Handle coordinate transformations between different CRS.
    """

    def __init__(self, source_crs: Union[str, int], target_crs: Union[str, int]):
        """
        Initialize coordinate transformer.

        Args:
            source_crs: Source CRS (EPSG code or WKT string)
            target_crs: Target CRS (EPSG code or WKT string)
        """
        try:
            from pyproj import CRS, Transformer
        except ImportError:
            raise ImportError("pyproj is required for coordinate transformations. Install with: pip install pyproj")

        # Parse CRS
        if isinstance(source_crs, int):
            self.source_crs = CRS.from_epsg(source_crs)
        else:
            self.source_crs = CRS.from_string(source_crs)

        if isinstance(target_crs, int):
            self.target_crs = CRS.from_epsg(target_crs)
        else:
            self.target_crs = CRS.from_string(target_crs)

        # Create transformer
        self.transformer = Transformer.from_crs(
            self.source_crs,
            self.target_crs,
            always_xy=True
        )

        logger.info(f"Created transformer: {self.source_crs.name} -> {self.target_crs.name}")

    def transform_point(self, x: float, y: float) -> Tuple[float, float]:
        """
        Transform a single point.

        Args:
            x: X coordinate in source CRS
            y: Y coordinate in source CRS

        Returns:
            (x_transformed, y_transformed) in target CRS
        """
        x_t, y_t = self.transformer.transform(x, y)
        return x_t, y_t

    def transform_points(
        self,
        x: np.ndarray,
        y: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Transform multiple points.

        Args:
            x: Array of X coordinates in source CRS
            y: Array of Y coordinates in source CRS

        Returns:
            (x_transformed, y_transformed) arrays in target CRS
        """
        x_t, y_t = self.transformer.transform(x, y)
        return x_t, y_t

    def transform_bounds(
        self,
        left: float,
        bottom: float,
        right: float,
        top: float
    ) -> Tuple[float, float, float, float]:
        """
        Transform bounding box.

        Args:
            left: Left boundary in source CRS
            bottom: Bottom boundary in source CRS
            right: Right boundary in source CRS
            top: Top boundary in source CRS

        Returns:
            (left, bottom, right, top) in target CRS
        """
        # Transform corners
        x_coords = [left, right, left, right]
        y_coords = [bottom, bottom, top, top]

        x_t, y_t = self.transformer.transform(x_coords, y_coords)

        # Get new bounds
        left_t = min(x_t)
        right_t = max(x_t)
        bottom_t = min(y_t)
        top_t = max(y_t)

        return left_t, bottom_t, right_t, top_t


def detect_crs(crs_input: Union[str, int, None]) -> Optional[str]:
    """
    Detect and validate CRS.

    Args:
        crs_input: CRS as EPSG code, WKT string, or None

    Returns:
        Validated CRS string or None
    """
    if crs_input is None:
        logger.warning("No CRS provided")
        return None

    try:
        from pyproj import CRS
    except ImportError:
        raise ImportError("pyproj is required for CRS detection. Install with: pip install pyproj")

    try:
        if isinstance(crs_input, int):
            crs = CRS.from_epsg(crs_input)
        else:
            crs = CRS.from_string(str(crs_input))

        logger.info(f"Detected CRS: {crs.name} (EPSG:{crs.to_epsg()})")
        return crs.to_wkt()

    except Exception as e:
        logger.error(f"Failed to detect CRS: {e}")
        return None


def validate_crs_match(crs1: Union[str, int], crs2: Union[str, int]) -> bool:
    """
    Check if two CRS are the same.

    Args:
        crs1: First CRS
        crs2: Second CRS

    Returns:
        True if CRS match
    """
    try:
        from pyproj import CRS
    except ImportError:
        raise ImportError("pyproj is required for CRS validation. Install with: pip install pyproj")

    try:
        if isinstance(crs1, int):
            c1 = CRS.from_epsg(crs1)
        else:
            c1 = CRS.from_string(str(crs1))

        if isinstance(crs2, int):
            c2 = CRS.from_epsg(crs2)
        else:
            c2 = CRS.from_string(str(crs2))

        match = c1 == c2
        if not match:
            logger.warning(f"CRS mismatch: {c1.name} vs {c2.name}")
        else:
            logger.info(f"CRS match: {c1.name}")

        return match

    except Exception as e:
        logger.error(f"Failed to validate CRS: {e}")
        return False


def grid_to_geographic(
    row: Union[int, np.ndarray],
    col: Union[int, np.ndarray],
    transform,
    crs: Optional[Union[str, int]] = None,
    target_crs: int = 4326
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert grid coordinates to geographic coordinates.

    Args:
        row: Row index/indices
        col: Column index/indices
        transform: Affine transform from rasterio
        crs: Source CRS (None to skip transformation)
        target_crs: Target CRS (default: EPSG:4326 - WGS84)

    Returns:
        (lon, lat) or (x, y) coordinates
    """
    try:
        import rasterio.transform
    except ImportError:
        raise ImportError("rasterio is required for grid transformations. Install with: pip install rasterio")

    scalar_input = np.isscalar(row) and np.isscalar(col)

    # Convert grid to projected coordinates using cell corner, consistent with
    # affine transform origin semantics used across this project.
    x, y = rasterio.transform.xy(transform, row, col, offset='ul')

    # Convert to arrays for downstream processing
    x = np.asarray(x)
    y = np.asarray(y)

    # Transform to target CRS if source CRS is provided
    if crs is not None:
        transformer = CoordinateTransformer(crs, target_crs)
        x, y = transformer.transform_points(x, y)

    if scalar_input:
        return float(x), float(y)
    return x, y


def geographic_to_grid(
    x: Union[float, np.ndarray],
    y: Union[float, np.ndarray],
    transform,
    crs: Optional[Union[str, int]] = None,
    source_crs: int = 4326
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert geographic coordinates to grid coordinates.

    Args:
        x: X coordinate(s) (longitude if geographic)
        y: Y coordinate(s) (latitude if geographic)
        transform: Affine transform from rasterio
        crs: Target CRS of the grid (None to skip transformation)
        source_crs: Source CRS of input coordinates (default: EPSG:4326)

    Returns:
        (row, col) grid indices
    """
    try:
        import rasterio.transform
    except ImportError:
        raise ImportError("rasterio is required for grid transformations. Install with: pip install rasterio")

    scalar_input = np.isscalar(x) and np.isscalar(y)

    # Convert to arrays if needed
    if not isinstance(x, np.ndarray):
        x = np.array([x]) if scalar_input else np.array(x)
        y = np.array([y]) if scalar_input else np.array(y)

    # Transform from source CRS if target CRS is provided
    if crs is not None:
        transformer = CoordinateTransformer(source_crs, crs)
        x, y = transformer.transform_points(x, y)

    # Convert to grid coordinates
    row, col = rasterio.transform.rowcol(transform, x, y)

    row_arr = np.array(row)
    col_arr = np.array(col)

    if scalar_input:
        return int(row_arr[0]), int(col_arr[0])
    return row_arr, col_arr


def ensure_consistent_crs(
    datasets: List[Tuple[np.ndarray, dict]],
    target_crs: Optional[Union[str, int]] = None
) -> List[Tuple[np.ndarray, dict]]:
    """
    Ensure all datasets use consistent CRS.

    Args:
        datasets: List of (data, metadata) tuples
        target_crs: Target CRS (None to use first dataset's CRS)

    Returns:
        List of datasets with consistent CRS
    """
    if len(datasets) == 0:
        return []

    # Determine target CRS
    if target_crs is None:
        target_crs = datasets[0][1].get('crs')
        if target_crs is None:
            logger.warning("No CRS found in first dataset, skipping CRS alignment")
            return datasets

    logger.info(f"Aligning datasets to CRS: {target_crs}")

    aligned_datasets = []

    for i, (data, metadata) in enumerate(datasets):
        source_crs = metadata.get('crs')

        if source_crs is None:
            logger.warning(f"Dataset {i} has no CRS, skipping transformation")
            aligned_datasets.append((data, metadata))
            continue

        # Check if transformation is needed
        if validate_crs_match(source_crs, target_crs):
            logger.info(f"Dataset {i} already in target CRS")
            aligned_datasets.append((data, metadata))
        else:
            logger.warning(f"Dataset {i} requires CRS transformation - not implemented for raster data")
            logger.warning("Please reproject raster data externally using GDAL or rasterio")
            aligned_datasets.append((data, metadata))

    return aligned_datasets


def get_utm_zone(lon: float, lat: float) -> int:
    """
    Get UTM zone for given coordinates.

    Args:
        lon: Longitude
        lat: Latitude

    Returns:
        EPSG code for UTM zone
    """
    # Calculate UTM zone
    zone_number = int((lon + 180) / 6) + 1

    # Determine hemisphere
    if lat >= 0:
        # Northern hemisphere
        epsg_code = 32600 + zone_number
    else:
        # Southern hemisphere
        epsg_code = 32700 + zone_number

    logger.info(f"UTM zone for ({lon}, {lat}): EPSG:{epsg_code}")

    return epsg_code


def calculate_grid_spacing(transform) -> Tuple[float, float]:
    """
    Calculate grid spacing from affine transform.

    Args:
        transform: Affine transform from rasterio

    Returns:
        (dx, dy) grid spacing in CRS units
    """
    dx = abs(transform[0])
    dy = abs(transform[4])

    logger.info(f"Grid spacing: dx={dx:.6f}, dy={dy:.6f}")

    return dx, dy


def create_transform(
    xmin: float,
    ymax: float,
    dx: float,
    dy: float
) -> 'Affine':
    """
    Create affine transform from grid parameters.

    Args:
        xmin: Minimum X coordinate (left edge)
        ymax: Maximum Y coordinate (top edge)
        dx: Grid spacing in X direction
        dy: Grid spacing in Y direction (positive value)

    Returns:
        Affine transform
    """
    try:
        from rasterio.transform import Affine
    except ImportError:
        raise ImportError("rasterio is required. Install with: pip install rasterio")

    # Create transform (note: dy is negative in affine transform)
    transform = Affine.translation(xmin, ymax) * Affine.scale(dx, -dy)

    logger.info(f"Created transform: origin=({xmin}, {ymax}), spacing=({dx}, {dy})")

    return transform


def get_bounds_from_transform(
    transform,
    width: int,
    height: int
) -> Tuple[float, float, float, float]:
    """
    Calculate bounds from transform and dimensions.

    Args:
        transform: Affine transform
        width: Grid width
        height: Grid height

    Returns:
        (left, bottom, right, top) bounds
    """
    left = transform.c
    top = transform.f
    right = left + width * transform.a
    bottom = top + height * transform.e

    return left, bottom, right, top
