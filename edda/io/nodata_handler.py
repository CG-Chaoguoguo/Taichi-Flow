"""
NoData processing utilities for handling missing data in raster datasets.
"""
import numpy as np
from scipy import interpolate, ndimage
from typing import Tuple, Optional, Literal
import logging

logger = logging.getLogger(__name__)


class NoDataHandler:
    """
    Handle NoData values in raster datasets with various filling strategies.
    """

    def __init__(self, data: np.ndarray, nodata_value: Optional[float] = None):
        """
        Initialize NoData handler.

        Args:
            data: 2D numpy array containing the raster data
            nodata_value: Value representing NoData (None for NaN/inf detection)
        """
        self.data = data.copy()
        self.nodata_value = nodata_value
        self.mask = self._detect_nodata()

    def _detect_nodata(self) -> np.ndarray:
        """
        Automatically detect NoData values.

        Returns:
            Boolean mask where True indicates NoData
        """
        if self.nodata_value is not None:
            # Use specified NoData value
            mask = np.isclose(self.data, self.nodata_value)
        else:
            # Detect NaN and inf values
            mask = ~np.isfinite(self.data)

        nodata_count = np.sum(mask)
        total_cells = mask.size
        nodata_percent = 100.0 * nodata_count / total_cells

        logger.info(f"Detected {nodata_count} NoData cells ({nodata_percent:.2f}%)")

        return mask

    def get_nodata_mask(self) -> np.ndarray:
        """
        Get the NoData mask.

        Returns:
            Boolean array where True indicates NoData
        """
        return self.mask.copy()

    def fill_nearest(self) -> np.ndarray:
        """
        Fill NoData using nearest neighbor interpolation.

        Returns:
            Filled data array
        """
        if not np.any(self.mask):
            logger.info("No NoData values to fill.")
            return self.data.copy()

        logger.info("Filling NoData using nearest neighbor interpolation...")

        filled = self.data.copy()

        # Get indices of valid and invalid points
        valid_mask = ~self.mask
        indices = np.indices(self.data.shape)

        # Find nearest valid neighbor for each NoData cell
        if np.any(valid_mask):
            # Use distance transform to find nearest valid cells
            distances, nearest_indices = ndimage.distance_transform_edt(
                self.mask, return_indices=True
            )

            # Fill NoData cells with nearest valid values
            filled[self.mask] = self.data[tuple(nearest_indices[:, self.mask])]

        logger.info("Nearest neighbor filling complete.")
        return filled

    def fill_interpolate(self, method: Literal['linear', 'cubic'] = 'linear') -> np.ndarray:
        """
        Fill NoData using interpolation.

        Args:
            method: Interpolation method ('linear' or 'cubic')

        Returns:
            Filled data array
        """
        if not np.any(self.mask):
            logger.info("No NoData values to fill.")
            return self.data.copy()

        logger.info(f"Filling NoData using {method} interpolation...")

        filled = self.data.copy()
        valid_mask = ~self.mask

        if not np.any(valid_mask):
            raise ValueError("No valid data points for interpolation.")

        # Get coordinates of valid and invalid points
        rows, cols = np.indices(self.data.shape)
        valid_points = np.column_stack((rows[valid_mask], cols[valid_mask]))
        valid_values = self.data[valid_mask]
        invalid_points = np.column_stack((rows[self.mask], cols[self.mask]))

        try:
            # Perform interpolation
            interpolated = interpolate.griddata(
                valid_points,
                valid_values,
                invalid_points,
                method=method,
                fill_value=np.nan
            )

            # Fill interpolated values
            filled[self.mask] = interpolated

            # If any NaN remain after interpolation, use nearest neighbor
            remaining_nan = np.isnan(filled)
            if np.any(remaining_nan):
                logger.warning(f"{np.sum(remaining_nan)} cells could not be interpolated, using nearest neighbor.")
                distances, nearest_indices = ndimage.distance_transform_edt(
                    remaining_nan, return_indices=True
                )
                filled[remaining_nan] = self.data[tuple(nearest_indices[:, remaining_nan])]

        except Exception as e:
            logger.error(f"Interpolation failed: {e}. Falling back to nearest neighbor.")
            return self.fill_nearest()

        logger.info("Interpolation filling complete.")
        return filled

    def fill_mean(self, kernel_size: int = 3) -> np.ndarray:
        """
        Fill NoData using local mean of surrounding valid cells.

        Args:
            kernel_size: Size of the kernel for computing local mean (must be odd)

        Returns:
            Filled data array
        """
        if not np.any(self.mask):
            logger.info("No NoData values to fill.")
            return self.data.copy()

        if kernel_size % 2 == 0:
            raise ValueError("kernel_size must be odd.")

        logger.info(f"Filling NoData using local mean (kernel size: {kernel_size})...")

        filled = self.data.copy()

        # Iteratively fill NoData cells
        max_iterations = 100
        for iteration in range(max_iterations):
            # Create a copy for this iteration
            temp = filled.copy()

            # Apply mean filter
            mean_filtered = ndimage.uniform_filter(
                np.where(self.mask, np.nan, filled),
                size=kernel_size,
                mode='constant',
                cval=np.nan
            )

            # Count valid neighbors
            valid_count = ndimage.uniform_filter(
                (~self.mask).astype(float),
                size=kernel_size,
                mode='constant',
                cval=0
            )

            # Fill NoData cells where we have valid neighbors
            can_fill = self.mask & (valid_count > 0) & np.isfinite(mean_filtered)
            temp[can_fill] = mean_filtered[can_fill]

            # Update mask
            self.mask = self.mask & ~can_fill
            filled = temp

            if not np.any(self.mask):
                logger.info(f"All NoData filled after {iteration + 1} iterations.")
                break

        # If any NoData remain, use nearest neighbor
        if np.any(self.mask):
            logger.warning(f"{np.sum(self.mask)} cells remain after {max_iterations} iterations, using nearest neighbor.")
            distances, nearest_indices = ndimage.distance_transform_edt(
                self.mask, return_indices=True
            )
            filled[self.mask] = self.data[tuple(nearest_indices[:, self.mask])]

        logger.info("Mean filling complete.")
        return filled

    def handle_boundary_nodata(self, fill_value: Optional[float] = None) -> np.ndarray:
        """
        Handle NoData values at boundaries by extending valid data.

        Args:
            fill_value: Value to use for boundary NoData (None for edge extension)

        Returns:
            Filled data array
        """
        if not np.any(self.mask):
            logger.info("No NoData values to fill.")
            return self.data.copy()

        logger.info("Handling boundary NoData...")

        filled = self.data.copy()

        if fill_value is not None:
            # Fill with specified value
            filled[self.mask] = fill_value
        else:
            # Extend edges
            # Top edge
            for i in range(filled.shape[0]):
                valid_cols = np.where(~self.mask[i, :])[0]
                if len(valid_cols) > 0:
                    # Fill left side
                    if valid_cols[0] > 0:
                        filled[i, :valid_cols[0]] = filled[i, valid_cols[0]]
                    # Fill right side
                    if valid_cols[-1] < filled.shape[1] - 1:
                        filled[i, valid_cols[-1]+1:] = filled[i, valid_cols[-1]]

            # Fill remaining using nearest neighbor
            remaining_mask = np.isnan(filled) if fill_value is None else self.mask
            if np.any(remaining_mask):
                distances, nearest_indices = ndimage.distance_transform_edt(
                    remaining_mask, return_indices=True
                )
                filled[remaining_mask] = self.data[tuple(nearest_indices[:, remaining_mask])]

        logger.info("Boundary NoData handling complete.")
        return filled


def detect_nodata_value(data: np.ndarray, threshold: float = 0.01) -> Optional[float]:
    """
    Automatically detect NoData value from data distribution.

    Args:
        data: Input raster data
        threshold: Minimum fraction of cells to consider as NoData value

    Returns:
        Detected NoData value or None
    """
    # Check for common NoData values
    common_nodata = [-9999, -3.4028235e+38, -32768, -99999]

    for nodata in common_nodata:
        count = np.sum(np.isclose(data, nodata))
        if count > 0 and count / data.size >= threshold:
            logger.info(f"Detected NoData value: {nodata} ({count} cells)")
            return nodata

    # Check for extreme values
    if np.any(~np.isfinite(data)):
        logger.info("Detected NaN/inf as NoData")
        return None

    return None


def fill_nodata_auto(
    data: np.ndarray,
    nodata_value: Optional[float] = None,
    method: Literal['nearest', 'linear', 'cubic', 'mean'] = 'linear'
) -> np.ndarray:
    """
    Automatically fill NoData values using specified method.

    Args:
        data: Input raster data
        nodata_value: NoData value (None for auto-detection)
        method: Filling method

    Returns:
        Filled data array
    """
    handler = NoDataHandler(data, nodata_value)

    if method == 'nearest':
        return handler.fill_nearest()
    elif method == 'linear':
        return handler.fill_interpolate(method='linear')
    elif method == 'cubic':
        return handler.fill_interpolate(method='cubic')
    elif method == 'mean':
        return handler.fill_mean()
    else:
        raise ValueError(f"Unknown method: {method}")
