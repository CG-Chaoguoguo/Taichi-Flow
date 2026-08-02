"""
Zone reader for spatial heterogeneous soil parameters.

This module reads zone raster files and maps zone-specific parameters
to spatial fields for heterogeneous soil properties.
"""
import numpy as np
import rasterio
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ZoneReader:
    """
    Read zone raster files and apply zone-specific parameters to spatial fields.

    Supports common raster formats (GeoTIFF, ASCII grid) and validates zone IDs
    against configuration.
    """

    def __init__(self, zone_file: str):
        """
        Initialize zone reader.

        Args:
            zone_file: Path to zone raster file (GeoTIFF or ASCII grid)
        """
        self.zone_file = Path(zone_file)
        if not self.zone_file.exists():
            raise FileNotFoundError(f"Zone file not found: {zone_file}")

        self.zone_grid = None
        self.transform = None
        self.crs = None
        self.nodata_value = None
        self.metadata = {}

    def read_zone_grid(self) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Read zone raster file and return zone ID array.

        Returns:
            zone_grid: 2D numpy array of zone IDs (integer)
            metadata: Dictionary containing spatial metadata

        Raises:
            FileNotFoundError: If zone file doesn't exist
            ValueError: If zone file format is invalid
        """
        logger.info(f"Reading zone file: {self.zone_file}")

        try:
            with rasterio.open(self.zone_file) as src:
                # Read zone data
                self.zone_grid = src.read(1, masked=False).astype(np.int32)

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

                logger.info(f"Zone grid dimensions: {src.width} x {src.height}")
                logger.info(f"Grid spacing: dx={self.metadata['dx']:.2f}m, dy={self.metadata['dy']:.2f}m")
                logger.info(f"CRS: {src.crs}")
                logger.info(f"NoData value: {src.nodata}")

        except rasterio.errors.RasterioIOError as e:
            raise ValueError(f"Failed to read zone file: {e}")

        # Handle NoData values - set them to -1 to distinguish from valid zone IDs
        if self.nodata_value is not None:
            nodata_mask = np.isclose(self.zone_grid, self.nodata_value)
            self.zone_grid[nodata_mask] = -1

        # Get unique zone IDs
        unique_zones = np.unique(self.zone_grid)
        unique_zones = unique_zones[unique_zones >= 0]  # Exclude NoData (-1)
        logger.info(f"Found {len(unique_zones)} unique zones: {unique_zones.tolist()}")

        return self.zone_grid, self.metadata

    def validate_zones(self, zone_config: Dict[int, Any]) -> bool:
        """
        Validate that all zone IDs in the grid have corresponding configuration.

        Args:
            zone_config: Dictionary mapping zone IDs to zone parameters

        Returns:
            True if all zones are valid, False otherwise

        Raises:
            ValueError: If zone grid hasn't been read yet or if invalid zones found
        """
        if self.zone_grid is None:
            raise ValueError("Zone grid not loaded. Call read_zone_grid() first.")

        # Get unique zone IDs (excluding NoData)
        unique_zones = np.unique(self.zone_grid)
        unique_zones = unique_zones[unique_zones >= 0]

        # Check if all zones have configuration
        missing_zones = []
        for zone_id in unique_zones:
            if zone_id not in zone_config:
                missing_zones.append(zone_id)

        if missing_zones:
            raise ValueError(
                f"Missing configuration for zones: {missing_zones}. "
                f"Please add parameters for these zones in the configuration file."
            )

        logger.info("Zone validation successful - all zones have configuration")
        return True

    def apply_zone_parameters(
        self,
        zone_config: Dict[int, Any],
        grid_shape: Tuple[int, int],
        default_params: Optional[Dict[str, float]] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Map zone parameters to spatial fields based on zone IDs.

        Args:
            zone_config: Dictionary mapping zone IDs to zone parameter objects
            grid_shape: Expected grid shape (nx, ny)
            default_params: Default parameters for cells with no zone assignment

        Returns:
            zone_mask: 2D array of zone IDs (nx, ny)
            zone_params: 2D array of parameters (num_zones, num_params)
                        Order: K_sat, theta_s, theta_i, psi_f, c, phi, gamma_s, gamma_w, depth,
                               n_manning, alpha1, beta1, alpha2, beta2

        Raises:
            ValueError: If zone grid hasn't been read or dimensions don't match
        """
        if self.zone_grid is None:
            raise ValueError("Zone grid not loaded. Call read_zone_grid() first.")

        # Check grid dimensions
        if self.zone_grid.shape != (grid_shape[1], grid_shape[0]):
            raise ValueError(
                f"Zone grid shape {self.zone_grid.shape} doesn't match "
                f"expected shape {(grid_shape[1], grid_shape[0])} (ny, nx)"
            )

        # Validate zones
        self.validate_zones(zone_config)

        # Get unique zone IDs and create mapping
        unique_zones = np.unique(self.zone_grid)
        unique_zones = unique_zones[unique_zones >= 0]
        num_zones = len(unique_zones)

        logger.info(f"Mapping parameters for {num_zones} zones")

        # Keep zone parameters in double precision. The production DFS path
        # uses these values directly in late thin-front threshold decisions,
        # so down-casting them here would silently break the configured
        # precision of the solver.
        zone_params = np.zeros((num_zones, 27), dtype=np.float64)

        # Fill parameter array for each zone
        for idx, zone_id in enumerate(unique_zones):
            if zone_id in zone_config:
                zone_obj = zone_config[zone_id]

                # Extract parameters in the correct order
                zone_params[idx, 0] = zone_obj.K_sat
                zone_params[idx, 1] = zone_obj.theta_s
                zone_params[idx, 2] = zone_obj.theta_i
                zone_params[idx, 3] = zone_obj.psi_f
                zone_params[idx, 4] = zone_obj.c
                zone_params[idx, 5] = zone_obj.phi
                zone_params[idx, 6] = zone_obj.gamma_s
                zone_params[idx, 7] = zone_obj.gamma_w
                zone_params[idx, 8] = zone_obj.depth
                zone_params[idx, 9] = zone_obj.n_manning
                zone_params[idx, 10] = zone_obj.alpha1
                zone_params[idx, 11] = zone_obj.beta1
                zone_params[idx, 12] = zone_obj.alpha2
                zone_params[idx, 13] = zone_obj.beta2
                # Double-layer and erosion parameters
                zone_params[idx, 14] = zone_obj.alpha_top
                zone_params[idx, 15] = zone_obj.alpha_bottom
                zone_params[idx, 16] = zone_obj.K_sat_top
                zone_params[idx, 17] = zone_obj.K_sat_bottom
                zone_params[idx, 18] = zone_obj.theta_sat_top
                zone_params[idx, 19] = zone_obj.theta_sat_bottom
                zone_params[idx, 20] = zone_obj.theta_res_top
                zone_params[idx, 21] = zone_obj.theta_res_bottom
                zone_params[idx, 22] = zone_obj.phib
                zone_params[idx, 23] = zone_obj.kero
                zone_params[idx, 24] = zone_obj.ltstar
                zone_params[idx, 25] = zone_obj.lbstar
                zone_params[idx, 26] = zone_obj.ctao

        # Create zone mask with remapped indices (0 to num_zones-1)
        zone_mask = np.zeros_like(self.zone_grid, dtype=np.int32)
        for idx, zone_id in enumerate(unique_zones):
            zone_mask[self.zone_grid == zone_id] = idx

        # Handle NoData cells - assign to zone 0 with default parameters if provided
        if default_params is not None:
            nodata_mask = self.zone_grid < 0
            zone_mask[nodata_mask] = 0
            logger.info(f"Assigned {np.sum(nodata_mask)} NoData cells to default zone")

        # Transpose to match (nx, ny) convention
        zone_mask = zone_mask.T

        logger.info("Zone parameter mapping complete")

        return zone_mask, zone_params

    def get_zone_statistics(self) -> Dict[int, Dict[str, Any]]:
        """
        Calculate statistics for each zone.

        Returns:
            Dictionary mapping zone IDs to statistics (cell count, percentage)

        Raises:
            ValueError: If zone grid hasn't been read yet
        """
        if self.zone_grid is None:
            raise ValueError("Zone grid not loaded. Call read_zone_grid() first.")

        unique_zones = np.unique(self.zone_grid)
        unique_zones = unique_zones[unique_zones >= 0]

        total_cells = np.sum(self.zone_grid >= 0)
        stats = {}

        for zone_id in unique_zones:
            count = np.sum(self.zone_grid == zone_id)
            percentage = 100.0 * count / total_cells if total_cells > 0 else 0.0
            stats[int(zone_id)] = {
                'cell_count': int(count),
                'percentage': float(percentage),
            }

        return stats
