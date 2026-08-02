"""
Rainfall data reader for time series and spatial rainfall data.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RainfallReader:
    """
    Read and process rainfall time series data from various formats.
    """

    def __init__(self, rainfall_file: str):
        """
        Initialize rainfall reader.

        Args:
            rainfall_file: Path to rainfall data file (CSV or text)
        """
        self.rainfall_file = Path(rainfall_file)
        if not self.rainfall_file.exists():
            raise FileNotFoundError(f"Rainfall file not found: {rainfall_file}")

        self.time_series = None
        self.spatial_data = None
        self.spatial_interval_bounds_s = None
        self.metadata = {}

    def _get_time_seconds(self) -> np.ndarray:
        """
        Convert time series timestamps to seconds since first record.

        Returns:
            1D array of seconds from series start.
        """
        if self.time_series is None:
            raise ValueError("No rainfall data loaded. Call read() first.")

        time_origin = self.time_series['time'].iloc[0]
        return (self.time_series['time'] - time_origin).dt.total_seconds().to_numpy(dtype=np.float64)

    def _get_interval_bounds_seconds(self) -> np.ndarray:
        """
        Build interval boundaries for piecewise-constant rainfall forcing.

        For N rainfall records, returns N+1 boundaries where record k applies on:
            [bounds[k], bounds[k+1]).
        """
        times_sec = self._get_time_seconds()
        n = len(times_sec)
        bounds = np.zeros(n + 1, dtype=np.float64)
        bounds[:-1] = times_sec

        if n >= 2:
            dt_last = times_sec[-1] - times_sec[-2]
        elif 'time_step' in self.metadata:
            dt_last = float(self.metadata['time_step'].total_seconds())
        else:
            dt_last = 3600.0

        if dt_last <= 0.0:
            dt_last = 3600.0

        bounds[-1] = times_sec[-1] + dt_last
        return bounds

    def read_csv(
        self,
        time_column: str = 'time',
        rainfall_column: str = 'rainfall',
        time_format: Optional[str] = None,
        delimiter: str = ','
    ) -> pd.DataFrame:
        """
        Read rainfall time series from CSV file.

        Args:
            time_column: Name of time column
            rainfall_column: Name of rainfall column
            time_format: Time format string (e.g., '%Y-%m-%d %H:%M:%S')
            delimiter: CSV delimiter

        Returns:
            DataFrame with time and rainfall columns
        """
        logger.info(f"Reading rainfall CSV: {self.rainfall_file}")

        try:
            # Read CSV file
            df = pd.read_csv(self.rainfall_file, delimiter=delimiter)

            # Check required columns
            if time_column not in df.columns:
                raise ValueError(f"Time column '{time_column}' not found in CSV")
            if rainfall_column not in df.columns:
                raise ValueError(f"Rainfall column '{rainfall_column}' not found in CSV")

            # Parse time column
            if time_format:
                df[time_column] = pd.to_datetime(df[time_column], format=time_format)
            else:
                df[time_column] = pd.to_datetime(df[time_column])

            # Sort by time
            df = df.sort_values(time_column).reset_index(drop=True)

            # Store time series
            self.time_series = df[[time_column, rainfall_column]].copy()
            self.time_series.columns = ['time', 'rainfall']

            # Calculate metadata
            self.metadata = {
                'start_time': self.time_series['time'].iloc[0],
                'end_time': self.time_series['time'].iloc[-1],
                'n_records': len(self.time_series),
                'total_rainfall': float(self.time_series['rainfall'].sum()),
                'max_intensity': float(self.time_series['rainfall'].max()),
                'mean_intensity': float(self.time_series['rainfall'].mean()),
            }

            # Calculate time step if uniform
            time_diffs = self.time_series['time'].diff().dropna()
            if len(time_diffs) > 0:
                unique_diffs = time_diffs.unique()
                if len(unique_diffs) == 1:
                    self.metadata['time_step'] = time_diffs.iloc[0]
                    logger.info(f"Uniform time step: {self.metadata['time_step']}")
                else:
                    logger.warning("Non-uniform time steps detected")

            logger.info(f"Read {len(self.time_series)} rainfall records")
            logger.info(f"Time range: {self.metadata['start_time']} to {self.metadata['end_time']}")
            logger.info(f"Total rainfall: {self.metadata['total_rainfall']:.2f} mm")

            return self.time_series

        except Exception as e:
            # Auto-detection intentionally tries CSV before falling back to the
            # original one-value-per-line forcing format. Keep this failure
            # quiet so normal fallback does not look like a physics error.
            logger.debug(f"Rainfall CSV parse failed: {e}")
            raise

    def read_simple_format(
        self,
        start_time: Optional[datetime] = None,
        time_step_minutes: float = 60.0
    ) -> pd.DataFrame:
        """
        Read simple rainfall format (one value per line).

        Args:
            start_time: Start time for the series (default: now)
            time_step_minutes: Time step in minutes

        Returns:
            DataFrame with time and rainfall columns
        """
        logger.info(f"Reading simple rainfall format: {self.rainfall_file}")

        try:
            # Read rainfall values
            rainfall_values = np.loadtxt(self.rainfall_file)

            # Generate time series
            if start_time is None:
                start_time = datetime.now()

            time_delta = timedelta(minutes=time_step_minutes)
            times = [start_time + i * time_delta for i in range(len(rainfall_values))]

            # Create DataFrame
            self.time_series = pd.DataFrame({
                'time': times,
                'rainfall': rainfall_values
            })

            # Calculate metadata
            self.metadata = {
                'start_time': self.time_series['time'].iloc[0],
                'end_time': self.time_series['time'].iloc[-1],
                'n_records': len(self.time_series),
                'time_step': time_delta,
                'total_rainfall': float(self.time_series['rainfall'].sum()),
                'max_intensity': float(self.time_series['rainfall'].max()),
                'mean_intensity': float(self.time_series['rainfall'].mean()),
            }

            logger.info(f"Read {len(self.time_series)} rainfall records")
            logger.info(f"Total rainfall: {self.metadata['total_rainfall']:.2f} mm")

            return self.time_series

        except Exception as e:
            logger.error(f"Error reading simple rainfall format: {e}")
            raise

    def interpolate_to_timesteps(
        self,
        target_times: np.ndarray,
        method: str = 'linear'
    ) -> np.ndarray:
        """
        Interpolate rainfall to simulation time steps.

        Args:
            target_times: Target time points (as datetime or numeric)
            method: Interpolation method ('linear', 'nearest', 'previous', 'next')

        Returns:
            Interpolated rainfall values
        """
        if self.time_series is None:
            raise ValueError("No rainfall data loaded. Call read_csv() or read_simple_format() first.")

        logger.info(f"Interpolating rainfall to {len(target_times)} time steps using {method} method")

        # Convert times to numeric for interpolation
        if isinstance(target_times[0], (datetime, pd.Timestamp)):
            # Convert to seconds since start
            time_origin = self.time_series['time'].iloc[0]
            source_times = (self.time_series['time'] - time_origin).dt.total_seconds().values
            target_times_numeric = np.array([(t - time_origin).total_seconds() for t in target_times])
        else:
            source_times = self.time_series['time'].values
            target_times_numeric = target_times

        source_rainfall = self.time_series['rainfall'].values

        # Perform interpolation
        if method == 'linear':
            interpolated = np.interp(target_times_numeric, source_times, source_rainfall)
        elif method == 'nearest':
            indices = np.searchsorted(source_times, target_times_numeric)
            indices = np.clip(indices, 0, len(source_times) - 1)
            interpolated = source_rainfall[indices]
        elif method == 'previous':
            indices = np.searchsorted(source_times, target_times_numeric, side='right') - 1
            indices = np.clip(indices, 0, len(source_times) - 1)
            interpolated = source_rainfall[indices]
        elif method == 'next':
            indices = np.searchsorted(source_times, target_times_numeric, side='left')
            indices = np.clip(indices, 0, len(source_times) - 1)
            interpolated = source_rainfall[indices]
        else:
            raise ValueError(f"Unknown interpolation method: {method}")

        logger.info(f"Interpolation complete. Total rainfall: {np.sum(interpolated):.2f} mm")

        return interpolated

    def get_constant_rainfall(self, intensity: float, duration_hours: float, dt_minutes: float = 1.0) -> pd.DataFrame:
        """
        Generate constant rainfall time series.

        Args:
            intensity: Rainfall intensity (mm/hr)
            duration_hours: Duration in hours
            dt_minutes: Time step in minutes

        Returns:
            DataFrame with time and rainfall columns
        """
        logger.info(f"Generating constant rainfall: {intensity} mm/hr for {duration_hours} hours")

        n_steps = int(duration_hours * 60 / dt_minutes)
        rainfall_per_step = intensity * (dt_minutes / 60.0)

        start_time = datetime.now()
        time_delta = timedelta(minutes=dt_minutes)
        times = [start_time + i * time_delta for i in range(n_steps)]

        self.time_series = pd.DataFrame({
            'time': times,
            'rainfall': np.full(n_steps, rainfall_per_step)
        })

        self.metadata = {
            'start_time': self.time_series['time'].iloc[0],
            'end_time': self.time_series['time'].iloc[-1],
            'n_records': len(self.time_series),
            'time_step': time_delta,
            'total_rainfall': float(self.time_series['rainfall'].sum()),
            'max_intensity': intensity,
            'mean_intensity': intensity,
        }

        logger.info(f"Generated {n_steps} time steps, total rainfall: {self.metadata['total_rainfall']:.2f} mm")

        return self.time_series

    def read_spatial_rainfall(
        self,
        rainfall_dir: str,
        file_pattern: str = 'rainfall_*.tif',
        interval_bounds_s: Optional[List[float]] = None,
    ) -> Tuple[np.ndarray, List[str]]:
        """
        Read spatial rainfall distribution from raster files.

        Args:
            rainfall_dir: Directory containing rainfall raster files
            file_pattern: File pattern for rainfall files

        Returns:
            rainfall_stack: 3D array [time, height, width]
            file_list: List of file paths
        """
        import rasterio
        from glob import glob

        logger.info(f"Reading spatial rainfall from: {rainfall_dir}")

        rainfall_path = Path(rainfall_dir)
        if not rainfall_path.exists():
            raise FileNotFoundError(f"Rainfall directory not found: {rainfall_dir}")

        # Find rainfall files
        file_list = sorted(glob(str(rainfall_path / file_pattern)))

        if len(file_list) == 0:
            raise FileNotFoundError(f"No rainfall files found matching pattern: {file_pattern}")

        logger.info(f"Found {len(file_list)} rainfall files")

        # Read first file to get dimensions
        with rasterio.open(file_list[0]) as src:
            height, width = src.shape
            self.metadata['transform'] = src.transform
            self.metadata['crs'] = src.crs

        # Read all files
        rainfall_stack = np.zeros((len(file_list), height, width), dtype=np.float32)

        for i, file_path in enumerate(file_list):
            with rasterio.open(file_path) as src:
                rainfall_stack[i] = src.read(1)

        self.spatial_data = rainfall_stack
        if interval_bounds_s is not None:
            bounds = np.asarray(interval_bounds_s, dtype=np.float64)
            if bounds.ndim != 1 or bounds.size != len(file_list) + 1:
                raise ValueError(
                    "Spatial rainfall interval_bounds_s must contain one more "
                    f"boundary than the number of files: got {bounds.size}, "
                    f"expected {len(file_list) + 1}."
                )
            if np.any(np.diff(bounds) <= 0.0):
                raise ValueError("Spatial rainfall interval_bounds_s must be strictly increasing.")
            self.spatial_interval_bounds_s = bounds
            self.metadata['interval_bounds_s'] = bounds.tolist()

        logger.info(f"Loaded spatial rainfall: {rainfall_stack.shape}")
        logger.info(f"Total rainfall: {np.sum(rainfall_stack):.2f} mm")

        return rainfall_stack, file_list

    def read(self):
        """
        Auto-detect format and read rainfall data.

        Tries to read as CSV first, then falls back to simple format.
        """
        try:
            # Try CSV format first
            self.read_csv()
            logger.info("Successfully read rainfall as CSV format")
        except Exception as e:
            logger.info(f"CSV read failed ({e}), trying simple format...")
            try:
                # Try simple format (one value per line)
                self.read_simple_format(time_step_minutes=60.0)
                logger.info("Successfully read rainfall as simple format")
            except Exception as e2:
                logger.error(f"Failed to read rainfall in any format: {e2}")
                raise

    def get_rainfall_at_time(self, t: float) -> float:
        """
        Get rainfall intensity at a specific time.

        Args:
            t: Time in seconds from start

        Returns:
            Rainfall intensity in m/s
        """
        if self.time_series is None:
            raise ValueError("No rainfall data loaded. Call read() first.")

        bounds = self._get_interval_bounds_seconds()
        rainfall_mm_hr = self.time_series['rainfall'].to_numpy(dtype=np.float64)

        t_sec = float(max(t, 0.0))
        idx = int(np.searchsorted(bounds, t_sec, side='right') - 1)

        if idx < 0:
            idx = 0
        if idx >= len(rainfall_mm_hr):
            # Beyond the final rainfall interval -> zero rainfall (matches original EDDA).
            return 0.0

        return float(rainfall_mm_hr[idx] / 3600.0 / 1000.0)

    def get_interval_average_rainfall(self, t_start: float, t_end: float) -> float:
        """
        Compute time-averaged rainfall intensity over [t_start, t_end].

        This mirrors original EDDA's interval-weighted rainfall treatment when a
        simulation step crosses rainfall period boundaries.

        Args:
            t_start: Interval start time (s)
            t_end: Interval end time (s)

        Returns:
            Average rainfall intensity over the interval (m/s)
        """
        if self.time_series is None:
            raise ValueError("No rainfall data loaded. Call read() first.")

        t0 = float(max(t_start, 0.0))
        t1 = float(max(t_end, 0.0))
        if t1 <= t0:
            return self.get_rainfall_at_time(t0)

        bounds = self._get_interval_bounds_seconds()
        rainfall_m_s = self.time_series['rainfall'].to_numpy(dtype=np.float64) / 3600.0 / 1000.0

        integral = 0.0
        for k in range(len(rainfall_m_s)):
            seg0 = max(t0, bounds[k])
            seg1 = min(t1, bounds[k + 1])
            if seg1 > seg0:
                integral += rainfall_m_s[k] * (seg1 - seg0)

        return float(integral / (t1 - t0))

    def get_spatial_rainfall_at_time(self, t: float, dt_hours: float = 1.0) -> Optional[np.ndarray]:
        """
        Get spatial rainfall field at a specific time.

        Args:
            t: Time in seconds from start
            dt_hours: Time step between rainfall files (hours)

        Returns:
            2D rainfall array (mm/hr) or None if no spatial data
        """
        if self.spatial_data is None:
            return None

        if self.spatial_interval_bounds_s is not None:
            bounds = self.spatial_interval_bounds_s
            t_sec = max(float(t), 0.0)
            idx = int(np.searchsorted(bounds, t_sec, side='right') - 1)
        else:
            t_hours = max(float(t), 0.0) / 3600.0
            idx = int(t_hours / dt_hours)

        if idx < 0:
            idx = 0
        if idx >= self.spatial_data.shape[0]:
            # Beyond forcing series -> zero rainfall.
            return np.zeros_like(self.spatial_data[0], dtype=np.float32)

        return self.spatial_data[idx]

    def get_spatial_interval_average_rainfall(self, t_start: float, t_end: float, dt_hours: float = 1.0) -> Optional[np.ndarray]:
        """
        Compute interval-averaged spatial rainfall over [t_start, t_end].

        Input spatial data are interpreted as mm/hr for each forcing period.
        Returned array is m/s average over the requested interval.
        """
        if self.spatial_data is None:
            return None

        t0 = float(max(t_start, 0.0))
        t1 = float(max(t_end, 0.0))
        if t1 <= t0:
            rain_mm_hr = self.get_spatial_rainfall_at_time(t0, dt_hours=dt_hours)
            if rain_mm_hr is None:
                return None
            return rain_mm_hr.astype(np.float64) / 3600.0 / 1000.0

        n_periods = self.spatial_data.shape[0]
        integral_depth = np.zeros_like(self.spatial_data[0], dtype=np.float64)

        for k in range(n_periods):
            if self.spatial_interval_bounds_s is not None:
                b0 = float(self.spatial_interval_bounds_s[k])
                b1 = float(self.spatial_interval_bounds_s[k + 1])
            else:
                period_sec = float(dt_hours) * 3600.0
                b0 = k * period_sec
                b1 = (k + 1) * period_sec
            overlap = max(0.0, min(t1, b1) - max(t0, b0))
            if overlap > 0.0:
                # depth contribution in meters
                integral_depth += self.spatial_data[k].astype(np.float64) * overlap / (3600.0 * 1000.0)

        return integral_depth / (t1 - t0)

    def get_statistics(self) -> Dict[str, float]:
        """
        Get rainfall statistics.

        Returns:
            Dictionary with statistics
        """
        if self.time_series is None and self.spatial_data is None:
            raise ValueError("No rainfall data loaded.")

        return self.metadata.copy()


def read_rainfall_csv(
    csv_file: str,
    time_column: str = 'time',
    rainfall_column: str = 'rainfall',
    time_format: Optional[str] = None
) -> pd.DataFrame:
    """
    Convenience function to read rainfall CSV.

    Args:
        csv_file: Path to CSV file
        time_column: Name of time column
        rainfall_column: Name of rainfall column
        time_format: Time format string

    Returns:
        DataFrame with time and rainfall columns
    """
    reader = RainfallReader(csv_file)
    return reader.read_csv(time_column, rainfall_column, time_format)


def generate_design_storm(
    intensity: float,
    duration_hours: float,
    dt_minutes: float = 1.0,
    pattern: str = 'constant'
) -> pd.DataFrame:
    """
    Generate design storm rainfall.

    Args:
        intensity: Peak rainfall intensity (mm/hr)
        duration_hours: Storm duration in hours
        dt_minutes: Time step in minutes
        pattern: Storm pattern ('constant', 'triangular', 'chicago')

    Returns:
        DataFrame with time and rainfall columns
    """
    n_steps = int(duration_hours * 60 / dt_minutes)
    start_time = datetime.now()
    time_delta = timedelta(minutes=dt_minutes)
    times = [start_time + i * time_delta for i in range(n_steps)]

    if pattern == 'constant':
        rainfall = np.full(n_steps, intensity * (dt_minutes / 60.0))

    elif pattern == 'triangular':
        # Peak at middle
        peak_idx = n_steps // 2
        rainfall = np.zeros(n_steps)
        rainfall[:peak_idx] = np.linspace(0, intensity, peak_idx) * (dt_minutes / 60.0)
        rainfall[peak_idx:] = np.linspace(intensity, 0, n_steps - peak_idx) * (dt_minutes / 60.0)

    elif pattern == 'chicago':
        # Chicago design storm (peak at 1/3 duration)
        peak_idx = n_steps // 3
        rainfall = np.zeros(n_steps)
        # Rising limb
        rainfall[:peak_idx] = (np.arange(peak_idx) / peak_idx) ** 2 * intensity * (dt_minutes / 60.0)
        # Falling limb
        remaining = n_steps - peak_idx
        rainfall[peak_idx:] = intensity * (1 - (np.arange(remaining) / remaining) ** 0.5) * (dt_minutes / 60.0)

    else:
        raise ValueError(f"Unknown pattern: {pattern}")

    df = pd.DataFrame({
        'time': times,
        'rainfall': rainfall
    })

    logger.info(f"Generated {pattern} design storm: {intensity} mm/hr, {duration_hours} hours")
    logger.info(f"Total rainfall: {np.sum(rainfall):.2f} mm")

    return df
