"""
Result export functionality for various output formats.
"""
import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.crs import CRS
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)


class ResultExporter:
    """
    Export simulation results to various formats (GeoTIFF, NetCDF, CSV).
    """

    def __init__(
        self,
        data: np.ndarray,
        transform: Optional[Affine] = None,
        crs: Optional[CRS] = None,
        nodata_value: Optional[float] = None
    ):
        """
        Initialize result exporter.

        Args:
            data: 2D or 3D numpy array (for time series: [time, height, width])
            transform: Affine transformation matrix
            crs: Coordinate reference system
            nodata_value: Value representing NoData
        """
        self.data = data
        self.transform = transform
        self.crs = crs
        self.nodata_value = nodata_value if nodata_value is not None else -9999.0

    def to_geotiff(
        self,
        output_file: str,
        band_names: Optional[List[str]] = None,
        compress: str = 'lzw',
        dtype: str = 'float32'
    ) -> None:
        """
        Export to GeoTIFF format with proper georeferencing.

        Args:
            output_file: Output file path
            band_names: Names for each band (for 3D data)
            compress: Compression method ('lzw', 'deflate', 'none')
            dtype: Output data type
        """
        logger.info(f"Exporting to GeoTIFF: {output_file}")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle 2D or 3D data
        if self.data.ndim == 2:
            height, width = self.data.shape
            count = 1
            data_to_write = self.data[np.newaxis, :, :]
        elif self.data.ndim == 3:
            count, height, width = self.data.shape
            data_to_write = self.data
        else:
            raise ValueError(f"Data must be 2D or 3D, got shape {self.data.shape}")

        # Set default transform if not provided
        if self.transform is None:
            logger.warning("No transform provided, using default identity transform")
            self.transform = Affine.identity()

        # Set default CRS if not provided.  Rasterio-backed readers may expose
        # an absent CRS as the string ``"None"`` (for example when an ESRI
        # ASCII grid is staged without a companion .prj file).  Passing that
        # sentinel through to GDAL makes the first result write fail with
        # ``The WKT could not be parsed``; treat it exactly like a missing CRS.
        if self.crs is None or (
            isinstance(self.crs, str) and self.crs.strip().lower() in {"", "none", "null"}
        ):
            logger.warning("No CRS provided, using EPSG:4326")
            self.crs = CRS.from_epsg(4326)

        # Configure output profile
        profile = {
            'driver': 'GTiff',
            'height': height,
            'width': width,
            'count': count,
            'dtype': dtype,
            'crs': self.crs,
            'transform': self.transform,
            'nodata': self.nodata_value,
            'compress': compress,
            'tiled': True,
            'blockxsize': 256,
            'blockysize': 256,
        }

        # Write to file
        with rasterio.open(output_path, 'w', **profile) as dst:
            for i in range(count):
                dst.write(data_to_write[i].astype(dtype), i + 1)

                # Set band description if provided
                if band_names and i < len(band_names):
                    dst.set_band_description(i + 1, band_names[i])

        logger.info(f"GeoTIFF export complete: {output_file}")

    def to_netcdf(
        self,
        output_file: str,
        time_coords: Optional[np.ndarray] = None,
        variable_name: str = 'data',
        variable_attrs: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Export to NetCDF format for time series data.

        Args:
            output_file: Output file path
            time_coords: Time coordinates (for 3D data)
            variable_name: Name of the data variable
            variable_attrs: Attributes for the variable
        """
        try:
            import xarray as xr
        except ImportError:
            raise ImportError("xarray is required for NetCDF export. Install with: pip install xarray netcdf4")

        logger.info(f"Exporting to NetCDF: {output_file}")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare coordinates
        if self.data.ndim == 2:
            height, width = self.data.shape
            y_coords = np.arange(height)
            x_coords = np.arange(width)

            # Create DataArray
            da = xr.DataArray(
                self.data,
                dims=['y', 'x'],
                coords={'y': y_coords, 'x': x_coords},
                name=variable_name
            )

        elif self.data.ndim == 3:
            time_steps, height, width = self.data.shape
            y_coords = np.arange(height)
            x_coords = np.arange(width)

            if time_coords is None:
                time_coords = np.arange(time_steps)

            # Create DataArray
            da = xr.DataArray(
                self.data,
                dims=['time', 'y', 'x'],
                coords={'time': time_coords, 'y': y_coords, 'x': x_coords},
                name=variable_name
            )
        else:
            raise ValueError(f"Data must be 2D or 3D, got shape {self.data.shape}")

        # Add attributes
        if variable_attrs:
            da.attrs.update(variable_attrs)

        # Add CRS information if available
        if self.crs:
            da.attrs['crs'] = str(self.crs)

        # Add transform information if available
        if self.transform:
            da.attrs['transform'] = list(self.transform)

        # Add NoData value
        da.attrs['_FillValue'] = self.nodata_value

        # Convert to Dataset and save
        ds = da.to_dataset()
        ds.to_netcdf(output_path)

        logger.info(f"NetCDF export complete: {output_file}")

    def to_csv(
        self,
        output_file: str,
        include_coords: bool = True,
        time_index: Optional[int] = None
    ) -> None:
        """
        Export to CSV format for point data.

        Args:
            output_file: Output file path
            include_coords: Include spatial coordinates
            time_index: Time index to export (for 3D data, None exports all)
        """
        logger.info(f"Exporting to CSV: {output_file}")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle 2D or 3D data
        if self.data.ndim == 2:
            data_to_export = self.data
            height, width = self.data.shape
        elif self.data.ndim == 3:
            if time_index is not None:
                data_to_export = self.data[time_index]
                height, width = data_to_export.shape
            else:
                # Export all time steps
                time_steps, height, width = self.data.shape
                data_to_export = self.data.reshape(time_steps, -1)
        else:
            raise ValueError(f"Data must be 2D or 3D, got shape {self.data.shape}")

        # Create DataFrame
        if self.data.ndim == 2 or time_index is not None:
            # Single time step
            rows, cols = np.indices(data_to_export.shape)
            df_data = {
                'row': rows.flatten(),
                'col': cols.flatten(),
                'value': data_to_export.flatten()
            }

            # Add spatial coordinates if available
            if include_coords and self.transform is not None:
                x_coords, y_coords = rasterio.transform.xy(
                    self.transform,
                    rows.flatten(),
                    cols.flatten()
                )
                df_data['x'] = x_coords
                df_data['y'] = y_coords

            df = pd.DataFrame(df_data)

            # Remove NoData values
            df = df[~np.isclose(df['value'], self.nodata_value)]

        else:
            # Multiple time steps
            time_steps, n_cells = data_to_export.shape
            df_data = {
                'time': np.repeat(np.arange(time_steps), n_cells),
                'cell_id': np.tile(np.arange(n_cells), time_steps),
                'value': data_to_export.flatten()
            }

            df = pd.DataFrame(df_data)

            # Remove NoData values
            df = df[~np.isclose(df['value'], self.nodata_value)]

        # Save to CSV
        df.to_csv(output_path, index=False)

        logger.info(f"CSV export complete: {output_file} ({len(df)} rows)")

    def to_ascii_grid(self, output_file: str, time_index: int = 0) -> None:
        """
        Export to ESRI ASCII Grid format.

        Args:
            output_file: Output file path
            time_index: Time index to export (for 3D data)
        """
        logger.info(f"Exporting to ASCII Grid: {output_file}")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get data to export
        if self.data.ndim == 2:
            data_to_export = self.data
        elif self.data.ndim == 3:
            data_to_export = self.data[time_index]
        else:
            raise ValueError(f"Data must be 2D or 3D, got shape {self.data.shape}")

        height, width = data_to_export.shape

        # Get grid parameters from transform
        if self.transform is not None:
            xllcorner = self.transform.c
            yllcorner = self.transform.f + height * self.transform.e
            cellsize = abs(self.transform.a)
        else:
            xllcorner = 0.0
            yllcorner = 0.0
            cellsize = 1.0

        # Write ASCII grid
        with open(output_path, 'w') as f:
            f.write(f"ncols         {width}\n")
            f.write(f"nrows         {height}\n")
            f.write(f"xllcorner     {xllcorner}\n")
            f.write(f"yllcorner     {yllcorner}\n")
            f.write(f"cellsize      {cellsize}\n")
            f.write(f"NODATA_value  {self.nodata_value}\n")

            # Write data
            np.savetxt(f, data_to_export, fmt='%.6f')

        logger.info(f"ASCII Grid export complete: {output_file}")


def export_results(
    data: np.ndarray,
    output_file: str,
    format: str = 'geotiff',
    transform: Optional[Affine] = None,
    crs: Optional[CRS] = None,
    nodata_value: Optional[float] = None,
    **kwargs
) -> None:
    """
    Export results to specified format.

    Args:
        data: Data to export
        output_file: Output file path
        format: Output format ('geotiff', 'netcdf', 'csv', 'ascii')
        transform: Affine transformation matrix
        crs: Coordinate reference system
        nodata_value: NoData value
        **kwargs: Additional format-specific arguments
    """
    exporter = ResultExporter(data, transform, crs, nodata_value)

    if format.lower() in ['geotiff', 'tif', 'tiff']:
        exporter.to_geotiff(output_file, **kwargs)
    elif format.lower() in ['netcdf', 'nc']:
        exporter.to_netcdf(output_file, **kwargs)
    elif format.lower() == 'csv':
        exporter.to_csv(output_file, **kwargs)
    elif format.lower() in ['ascii', 'asc']:
        exporter.to_ascii_grid(output_file, **kwargs)
    else:
        raise ValueError(f"Unknown format: {format}")
