"""
Integration tests for EDDA-Taichi system.
"""
import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver
from edda.io.dem_reader import DEMReader
from edda.backend.backend_manager import BackendManager


class TestIntegration:
    """Integration tests for complete workflow."""

    def test_end_to_end_simulation(self, tmp_path):
        """Test complete simulation workflow."""
        # Create synthetic DEM
        nx, ny = 50, 50
        elevation = np.random.rand(ny, nx) * 100 + 1000

        # Save DEM
        dem_file = tmp_path / "test_dem.npy"
        np.save(dem_file, elevation)

        # Create configuration
        config = SimulationConfig(
            dem_file=str(dem_file),
            output_dir=str(tmp_path / "output"),
            time={"t_end": 10.0, "dt_output": 5.0}
        )

        # Note: Full simulation test would require Taichi initialization
        # This is a structure test
        assert config.dem_file == str(dem_file)
        assert config.time.t_end == 10.0

    def test_backend_initialization(self):
        """Test backend initialization."""
        manager = BackendManager()
        available = manager.get_available_backends()

        assert 'cpu' in available
        assert len(available) > 0

    def test_dem_processing_workflow(self, tmp_path):
        """Test DEM reading and processing."""
        # Create test DEM
        elevation = np.random.rand(100, 100) * 500 + 1000

        # Add NoData
        elevation[10:20, 10:20] = -9999

        # Save as numpy (simplified)
        dem_file = tmp_path / "test_dem.npy"
        np.save(dem_file, elevation)

        # Test would load with DEMReader in real scenario
        loaded = np.load(dem_file)
        assert loaded.shape == (100, 100)

    def test_configuration_serialization(self, tmp_path):
        """Test configuration save/load."""
        config = SimulationConfig(
            dem_file="test.tif",
            output_dir="./output"
        )

        # Save
        config_file = tmp_path / "config.yaml"
        config.to_yaml(str(config_file))

        # Load
        loaded_config = SimulationConfig.from_yaml(str(config_file))

        assert loaded_config.dem_file == config.dem_file
        assert loaded_config.time.CFL == config.time.CFL


class TestAPIIntegration:
    """Integration tests for API."""

    def test_api_imports(self):
        """Test API module imports."""
        try:
            from api import app
            from api.routes import realtime, results_v2, workbench
            assert True
        except ImportError as e:
            pytest.fail(f"API import failed: {e}")

    def test_client_example_structure(self):
        """Test API client example structure."""
        from examples.api_client_example import EDDAClient

        client = EDDAClient("http://localhost:8000")
        assert client.base_url == "http://localhost:8000"
        assert client.api_url == "http://localhost:8000/api"


class TestFrontendIntegration:
    """Integration tests for frontend."""

    def test_frontend_imports(self):
        """Test the production Taichi-Flow React UI files exist."""
        frontend_dir = Path(__file__).parent.parent / "frontend"
        react_dir = frontend_dir / "taichi-flow"

        assert (react_dir / "package.json").exists()
        assert (react_dir / "src" / "api" / "taichiFlowAdapter.ts").exists()
        assert (react_dir / "src" / "stores" / "taichiFlowStore.ts").exists()
        assert (react_dir / "src" / "pages" / "Projects" / "ProjectList.tsx").exists()
        assert (react_dir / "src" / "pages" / "Calculate" / "RunModule.tsx").exists()
        assert not (frontend_dir / "edda-taichi").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
