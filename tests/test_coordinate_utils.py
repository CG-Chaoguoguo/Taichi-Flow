"""
Unit tests for coordinate utilities.
"""
import pytest
import numpy as np
from rasterio.transform import Affine

from edda.utils import (
    CoordinateTransformer,
    detect_crs,
    validate_crs_match,
    grid_to_geographic,
    geographic_to_grid,
    get_utm_zone,
    calculate_grid_spacing,
    create_transform,
    get_bounds_from_transform,
)


class TestCoordinateTransformer:
    """Test coordinate transformation functionality."""

    def test_transform_point_wgs84_to_utm(self):
        """Test transforming a point from WGS84 to UTM."""
        # Point in Beijing area (lon, lat)
        lon, lat = 116.4, 39.9

        # Transform to UTM Zone 50N
        transformer = CoordinateTransformer(4326, 32650)
        x, y = transformer.transform_point(lon, lat)

        # Check that coordinates are in reasonable range for UTM
        assert 400000 < x < 600000
        assert 4000000 < y < 5000000

    def test_transform_points_array(self):
        """Test transforming multiple points."""
        lons = np.array([116.0, 116.5, 117.0])
        lats = np.array([39.0, 39.5, 40.0])

        transformer = CoordinateTransformer(4326, 32650)
        x, y = transformer.transform_points(lons, lats)

        assert len(x) == 3
        assert len(y) == 3
        assert np.all(x > 0)
        assert np.all(y > 0)

    def test_transform_bounds(self):
        """Test transforming bounding box."""
        # Bounding box in WGS84
        left, bottom, right, top = 116.0, 39.0, 117.0, 40.0

        transformer = CoordinateTransformer(4326, 32650)
        left_t, bottom_t, right_t, top_t = transformer.transform_bounds(left, bottom, right, top)

        assert left_t < right_t
        assert bottom_t < top_t

    def test_identity_transform(self):
        """Test transformation with same source and target CRS."""
        x, y = 100.0, 200.0

        transformer = CoordinateTransformer(4326, 4326)
        x_t, y_t = transformer.transform_point(x, y)

        assert np.isclose(x_t, x)
        assert np.isclose(y_t, y)


class TestCRSDetection:
    """Test CRS detection and validation."""

    def test_detect_crs_epsg(self):
        """Test CRS detection from EPSG code."""
        crs_wkt = detect_crs(4326)
        assert crs_wkt is not None
        assert 'WGS 84' in crs_wkt or 'WGS84' in crs_wkt

    def test_detect_crs_string(self):
        """Test CRS detection from string."""
        crs_wkt = detect_crs('EPSG:4326')
        assert crs_wkt is not None

    def test_validate_crs_match_same(self):
        """Test CRS validation for matching CRS."""
        assert validate_crs_match(4326, 'EPSG:4326')

    def test_validate_crs_match_different(self):
        """Test CRS validation for different CRS."""
        assert not validate_crs_match(4326, 32650)


class TestGridConversions:
    """Test grid coordinate conversions."""

    def test_grid_to_geographic_single(self):
        """Test converting single grid coordinate to geographic."""
        # Create a simple transform
        transform = Affine.translation(116.0, 40.0) * Affine.scale(0.01, -0.01)

        x, y = grid_to_geographic(0, 0, transform)

        assert np.isclose(x, 116.0)
        assert np.isclose(y, 40.0)

    def test_grid_to_geographic_array(self):
        """Test converting multiple grid coordinates."""
        transform = Affine.translation(116.0, 40.0) * Affine.scale(0.01, -0.01)

        rows = np.array([0, 10, 20])
        cols = np.array([0, 10, 20])

        x, y = grid_to_geographic(rows, cols, transform)

        assert len(x) == 3
        assert len(y) == 3
        assert np.isclose(x[0], 116.0)
        assert np.isclose(y[0], 40.0)

    def test_geographic_to_grid_single(self):
        """Test converting geographic coordinate to grid."""
        transform = Affine.translation(116.0, 40.0) * Affine.scale(0.01, -0.01)

        row, col = geographic_to_grid(116.0, 40.0, transform)

        assert np.isclose(row, 0)
        assert np.isclose(col, 0)

    def test_geographic_to_grid_array(self):
        """Test converting multiple geographic coordinates."""
        transform = Affine.translation(116.0, 40.0) * Affine.scale(0.01, -0.01)

        x = np.array([116.0, 116.1, 116.2])
        y = np.array([40.0, 39.9, 39.8])

        rows, cols = geographic_to_grid(x, y, transform)

        assert len(rows) == 3
        assert len(cols) == 3
        assert np.isclose(rows[0], 0)
        assert np.isclose(cols[0], 0)

    def test_grid_geographic_roundtrip(self):
        """Test roundtrip conversion."""
        transform = Affine.translation(116.0, 40.0) * Affine.scale(0.01, -0.01)

        # Start with grid coordinates
        row_orig, col_orig = 10, 20

        # Convert to geographic
        x, y = grid_to_geographic(row_orig, col_orig, transform)

        # Convert back to grid
        row_back, col_back = geographic_to_grid(x, y, transform)

        assert np.isclose(row_back, row_orig)
        assert np.isclose(col_back, col_orig)


class TestUTMZone:
    """Test UTM zone calculation."""

    def test_get_utm_zone_northern(self):
        """Test UTM zone for northern hemisphere."""
        # Beijing
        epsg = get_utm_zone(116.4, 39.9)
        assert epsg == 32650  # UTM Zone 50N

    def test_get_utm_zone_southern(self):
        """Test UTM zone for southern hemisphere."""
        # Sydney
        epsg = get_utm_zone(151.2, -33.9)
        assert epsg == 32756  # UTM Zone 56S

    def test_get_utm_zone_equator(self):
        """Test UTM zone near equator."""
        epsg = get_utm_zone(0.0, 0.0)
        assert 32600 < epsg < 32700  # Northern hemisphere


class TestTransformUtilities:
    """Test transform utility functions."""

    def test_calculate_grid_spacing(self):
        """Test grid spacing calculation."""
        transform = Affine.translation(0, 0) * Affine.scale(10.0, -5.0)

        dx, dy = calculate_grid_spacing(transform)

        assert np.isclose(dx, 10.0)
        assert np.isclose(dy, 5.0)

    def test_create_transform(self):
        """Test transform creation."""
        xmin, ymax = 100.0, 200.0
        dx, dy = 10.0, 5.0

        transform = create_transform(xmin, ymax, dx, dy)

        assert np.isclose(transform.c, xmin)
        assert np.isclose(transform.f, ymax)
        assert np.isclose(transform.a, dx)
        assert np.isclose(abs(transform.e), dy)

    def test_get_bounds_from_transform(self):
        """Test bounds calculation from transform."""
        transform = Affine.translation(100.0, 200.0) * Affine.scale(10.0, -5.0)
        width, height = 10, 20

        left, bottom, right, top = get_bounds_from_transform(transform, width, height)

        assert np.isclose(left, 100.0)
        assert np.isclose(top, 200.0)
        assert np.isclose(right, 100.0 + 10 * 10.0)
        assert np.isclose(bottom, 200.0 - 20 * 5.0)

    def test_transform_roundtrip(self):
        """Test creating transform and extracting bounds."""
        xmin, ymax = 100.0, 200.0
        dx, dy = 10.0, 5.0
        width, height = 10, 20

        # Create transform
        transform = create_transform(xmin, ymax, dx, dy)

        # Get bounds
        left, bottom, right, top = get_bounds_from_transform(transform, width, height)

        # Verify
        assert np.isclose(left, xmin)
        assert np.isclose(top, ymax)
        assert np.isclose(right, xmin + width * dx)
        assert np.isclose(bottom, ymax - height * dy)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
