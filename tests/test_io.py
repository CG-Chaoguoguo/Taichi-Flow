"""
Unit tests for I/O utilities.
"""
import pytest
import numpy as np
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

from edda.io import (
    NoDataHandler,
    detect_nodata_value,
    fill_nodata_auto,
    ResultExporter,
    RainfallReader,
    generate_design_storm,
)


class TestNoDataHandler:
    """Test NoData handling functionality."""

    def test_detect_nodata(self):
        """Test NoData detection."""
        # Create test data with NoData
        data = np.random.rand(10, 10)
        data[0:2, 0:2] = -9999

        handler = NoDataHandler(data, nodata_value=-9999)
        mask = handler.get_nodata_mask()

        assert np.sum(mask) == 4
        assert mask[0, 0] == True
        assert mask[5, 5] == False

    def test_detect_nodata_nan(self):
        """Test NaN detection."""
        data = np.random.rand(10, 10)
        data[0:2, 0:2] = np.nan

        handler = NoDataHandler(data)
        mask = handler.get_nodata_mask()

        assert np.sum(mask) == 4

    def test_fill_nearest(self):
        """Test nearest neighbor filling."""
        data = np.ones((10, 10))
        data[4:6, 4:6] = -9999

        handler = NoDataHandler(data, nodata_value=-9999)
        filled = handler.fill_nearest()

        assert not np.any(np.isclose(filled, -9999))
        assert np.allclose(filled, 1.0)

    def test_fill_interpolate_linear(self):
        """Test linear interpolation filling."""
        data = np.ones((10, 10))
        data[4:6, 4:6] = -9999

        handler = NoDataHandler(data, nodata_value=-9999)
        filled = handler.fill_interpolate(method='linear')

        assert not np.any(np.isclose(filled, -9999))
        assert np.all(np.isfinite(filled))

    def test_fill_mean(self):
        """Test mean filling."""
        data = np.ones((10, 10))
        data[4:6, 4:6] = -9999

        handler = NoDataHandler(data, nodata_value=-9999)
        filled = handler.fill_mean(kernel_size=3)

        assert not np.any(np.isclose(filled, -9999))
        assert np.allclose(filled, 1.0, atol=0.1)

    def test_detect_nodata_value(self):
        """Test automatic NoData value detection."""
        data = np.random.rand(100, 100)
        data[0:10, 0:10] = -9999

        nodata = detect_nodata_value(data)
        assert nodata == -9999

    def test_fill_nodata_auto(self):
        """Test automatic NoData filling."""
        data = np.ones((10, 10))
        data[4:6, 4:6] = -9999

        filled = fill_nodata_auto(data, nodata_value=-9999, method='nearest')

        assert not np.any(np.isclose(filled, -9999))
        assert np.allclose(filled, 1.0)


class TestResultExporter:
    """Test result export functionality."""

    def test_export_geotiff_2d(self):
        """Test GeoTIFF export for 2D data."""
        data = np.random.rand(10, 10)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "test.tif"

            exporter = ResultExporter(data)
            exporter.to_geotiff(str(output_file))

            assert output_file.exists()

            # Verify file can be read
            import rasterio
            with rasterio.open(output_file) as src:
                assert src.count == 1
                assert src.height == 10
                assert src.width == 10

    def test_export_geotiff_3d(self):
        """Test GeoTIFF export for 3D data."""
        data = np.random.rand(5, 10, 10)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "test.tif"

            exporter = ResultExporter(data)
            exporter.to_geotiff(str(output_file))

            assert output_file.exists()

            # Verify file can be read
            import rasterio
            with rasterio.open(output_file) as src:
                assert src.count == 5
                assert src.height == 10
                assert src.width == 10

    def test_export_csv_2d(self):
        """Test CSV export for 2D data."""
        data = np.random.rand(5, 5)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "test.csv"

            exporter = ResultExporter(data)
            exporter.to_csv(str(output_file))

            assert output_file.exists()

            # Verify file can be read
            import pandas as pd
            df = pd.read_csv(output_file)
            assert 'row' in df.columns
            assert 'col' in df.columns
            assert 'value' in df.columns

    def test_export_ascii_grid(self):
        """Test ASCII grid export."""
        data = np.random.rand(5, 5)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "test.asc"

            exporter = ResultExporter(data)
            exporter.to_ascii_grid(str(output_file))

            assert output_file.exists()

            # Verify header
            with open(output_file, 'r') as f:
                header = [f.readline() for _ in range(6)]
                assert 'ncols' in header[0]
                assert 'nrows' in header[1]


class TestRainfallReader:
    """Test rainfall data reading functionality."""

    def test_read_simple_format(self):
        """Test reading simple rainfall format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            rainfall_file = Path(tmpdir) / "rainfall.txt"
            rainfall_values = np.array([0, 5, 10, 15, 10, 5, 0])
            np.savetxt(rainfall_file, rainfall_values)

            # Read file
            reader = RainfallReader(str(rainfall_file))
            df = reader.read_simple_format(time_step_minutes=60)

            assert len(df) == 7
            assert 'time' in df.columns
            assert 'rainfall' in df.columns
            assert np.allclose(df['rainfall'].values, rainfall_values)

    def test_read_csv(self):
        """Test reading CSV rainfall data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test CSV
            rainfall_file = Path(tmpdir) / "rainfall.csv"
            import pandas as pd

            times = pd.date_range('2024-01-01', periods=5, freq='1h')
            rainfall = [0, 5, 10, 5, 0]
            df = pd.DataFrame({'time': times, 'rainfall': rainfall})
            df.to_csv(rainfall_file, index=False)

            # Read file
            reader = RainfallReader(str(rainfall_file))
            result = reader.read_csv()

            assert len(result) == 5
            assert np.allclose(result['rainfall'].values, rainfall)

    def test_interpolate_to_timesteps(self):
        """Test rainfall interpolation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            rainfall_file = Path(tmpdir) / "rainfall.txt"
            rainfall_values = np.array([0, 10, 0])
            np.savetxt(rainfall_file, rainfall_values)

            # Read and interpolate
            reader = RainfallReader(str(rainfall_file))
            reader.read_simple_format(time_step_minutes=60)

            # Interpolate to finer time steps
            start_time = reader.time_series['time'].iloc[0]
            target_times = [start_time + timedelta(minutes=30*i) for i in range(5)]
            interpolated = reader.interpolate_to_timesteps(target_times, method='linear')

            assert len(interpolated) == 5
            assert interpolated[0] == 0
            assert interpolated[2] == 10
            assert interpolated[4] == 0

    def test_constant_rainfall(self):
        """Test constant rainfall generation."""
        reader = RainfallReader.__new__(RainfallReader)
        df = reader.get_constant_rainfall(intensity=10.0, duration_hours=2.0, dt_minutes=60.0)

        assert len(df) == 2
        assert np.allclose(df['rainfall'].values, 10.0)

    def test_generate_design_storm_constant(self):
        """Test constant design storm generation."""
        df = generate_design_storm(intensity=20.0, duration_hours=1.0, dt_minutes=10.0, pattern='constant')

        assert len(df) == 6
        assert np.allclose(df['rainfall'].values, 20.0 * (10.0 / 60.0))

    def test_generate_design_storm_triangular(self):
        """Test triangular design storm generation."""
        df = generate_design_storm(intensity=20.0, duration_hours=1.0, dt_minutes=10.0, pattern='triangular')

        assert len(df) == 6
        # Peak should be at middle
        peak_idx = len(df) // 2
        assert df['rainfall'].iloc[peak_idx] >= df['rainfall'].iloc[0]
        assert df['rainfall'].iloc[peak_idx] >= df['rainfall'].iloc[-1]

    def test_generate_design_storm_chicago(self):
        """Test Chicago design storm generation."""
        df = generate_design_storm(intensity=20.0, duration_hours=1.0, dt_minutes=10.0, pattern='chicago')

        assert len(df) == 6
        # Peak should be at 1/3 duration
        peak_idx = len(df) // 3
        assert df['rainfall'].iloc[peak_idx] >= df['rainfall'].iloc[0]

    def test_interval_average_matches_fortran_boundary_semantics(self):
        """Match the supplied dfs.F90 rainfall interval selection at boundaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rainfall_file = Path(tmpdir) / "rainfall.csv"

            start = np.datetime64("2000-01-01T00:00:00")
            times = start + np.array([0, 3600, 7200, 10800], dtype="timedelta64[s]")
            rainfall_mm_hr = np.array([1.2, 0.2, 2.2, 4.3], dtype=np.float64)
            pd.DataFrame({
                "time": times.astype("datetime64[s]").astype(str),
                "rainfall": rainfall_mm_hr,
            }).to_csv(rainfall_file, index=False)

            reader = RainfallReader(str(rainfall_file))
            reader.read_csv()

            cri_mps = rainfall_mm_hr / 3600.0 / 1000.0
            capt_s = np.array([0.0, 3600.0, 7200.0, 10800.0, 14400.0], dtype=np.float64)

            def fortran_interval_average(t_start: float, t_end: float) -> float:
                dt = t_end - t_start
                nper = len(cri_mps)
                for j in range(nper):
                    if capt_s[j] <= t_start and t_end <= capt_s[j + 1]:
                        return float(cri_mps[j])
                    if t_start <= capt_s[j + 1] <= t_end:
                        if j < nper - 1:
                            return float(
                                ((capt_s[j + 1] - t_start) * cri_mps[j]
                                 + (t_end - capt_s[j + 1]) * cri_mps[j + 1]) / dt
                            )
                        return float((capt_s[j + 1] - t_start) * cri_mps[j] / dt)
                    if j == nper - 1 and capt_s[j + 1] < t_start:
                        return 0.0
                return 0.0

            probes = [
                (0.0, 2.0),
                (3599.0, 3600.0),
                (3599.0, 3601.0),
                (3600.0, 3602.0),
                (7199.5, 7201.5),
                (10800.0, 10802.0),
            ]

            for t_start, t_end in probes:
                expected = fortran_interval_average(t_start, t_end)
                actual = reader.get_interval_average_rainfall(t_start, t_end)
                assert actual == pytest.approx(expected, rel=0.0, abs=1e-18)

    def test_interval_average_matches_fortran_case_schedule_around_all_capt_boundaries(self):
        """Stress rainfall interval logic around all forcing boundaries used by EDDA."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rainfall_file = Path(tmpdir) / "rainfall.csv"

            cri_mps = np.array([
                3.33333e-07, 5.55556e-08, 6.11111e-07, 1.19444e-06, 1.52778e-06,
                1.5e-06, 1.30556e-06, 1.0e-06, 6.38889e-07, 0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 3.88889e-07, 1.19444e-06, 8.33333e-08, 2.77778e-08,
                5.55556e-08, 0.0, 2.77778e-08, 3.05556e-07, 1.63889e-06,
                7.91667e-06, 1.86111e-06, 5.83333e-07, 2.55556e-06, 2.77778e-08,
                3.0e-06, 6.72222e-06, 2.52778e-06, 1.19444e-06, 1.52778e-06,
                9.16667e-07, 1.33333e-06, 8.61111e-07, 1.11111e-07, 8.33333e-08,
            ], dtype=np.float64)
            capt_s = np.arange(40, dtype=np.float64) * 3600.0
            start = np.datetime64("2000-01-01T00:00:00")
            times = start + capt_s[:-1].astype("timedelta64[s]")
            rainfall_mm_hr = cri_mps * 3600.0 * 1000.0
            pd.DataFrame({
                "time": times.astype("datetime64[s]").astype(str),
                "rainfall": rainfall_mm_hr,
            }).to_csv(rainfall_file, index=False)

            reader = RainfallReader(str(rainfall_file))
            reader.read_csv()

            def fortran_interval_average(t_start: float, t_end: float) -> float:
                dt = t_end - t_start
                nper = len(cri_mps)
                for j in range(nper):
                    if capt_s[j] <= t_start and t_end <= capt_s[j + 1]:
                        return float(cri_mps[j])
                    if t_start <= capt_s[j + 1] <= t_end:
                        if j < nper - 1:
                            return float(
                                ((capt_s[j + 1] - t_start) * cri_mps[j]
                                 + (t_end - capt_s[j + 1]) * cri_mps[j + 1]) / dt
                            )
                        return float((capt_s[j + 1] - t_start) * cri_mps[j] / dt)
                    if j == nper - 1 and capt_s[j + 1] < t_start:
                        return 0.0
                return 0.0

            max_abs_diff = 0.0
            for boundary in capt_s[1:-1]:
                for offset in (-2.0, -1.9999, -1.5, -1.0, -0.5, -1e-6, 0.0, 1e-6, 0.5, 1.0, 1.5):
                    for dt in (1e-6, 0.1, 0.5, 1.0, 1.5, 2.0):
                        t_start = max(0.0, boundary + offset)
                        t_end = t_start + dt
                        expected = fortran_interval_average(t_start, t_end)
                        actual = reader.get_interval_average_rainfall(t_start, t_end)
                        max_abs_diff = max(max_abs_diff, abs(actual - expected))

            assert max_abs_diff <= 1e-18


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
