"""
Basic tests for EDDA configuration and data structures.
"""
import pytest
import numpy as np
from pathlib import Path
import sys
from types import SimpleNamespace

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from edda.config.sim_config import SimulationConfig, HydrologyParams, SoilParams
from edda.backend.backend_manager import BackendManager


class TestConfiguration:
    """Test configuration management."""

    def test_default_config(self):
        """Test default configuration creation."""
        config = SimulationConfig(
            dem_file="test.tif",
            output_dir="./output"
        )
        assert config.dem_file == "test.tif"
        assert config.hydrology.K_sat == 1e-5
        assert config.time.CFL == 0.5

    def test_config_to_dict(self):
        """Test configuration serialization."""
        config = SimulationConfig(
            dem_file="test.tif",
            output_dir="./output"
        )
        data = config.to_dict()
        assert isinstance(data, dict)
        assert data['dem_file'] == "test.tif"

    def test_config_from_dict(self):
        """Test configuration deserialization."""
        data = {
            'dem_file': 'test.tif',
            'output_dir': './output',
        }
        config = SimulationConfig.from_dict(data)
        assert config.dem_file == "test.tif"


class TestBackendManager:
    """Test backend manager."""

    def test_get_available_backends(self):
        """Test backend detection."""
        backends = BackendManager.get_available_backends()
        assert isinstance(backends, list)
        assert 'cpu' in backends  # CPU should always be available

    def test_recommend_backend(self):
        """Test backend recommendation."""
        backend = BackendManager.recommend_backend()
        assert backend in ['cuda', 'vulkan', 'metal', 'cpu']

    def test_backend_initialization(self):
        """Test backend initialization."""
        manager = BackendManager()
        manager.initialize(backend='cpu')
        assert manager.is_initialized
        assert manager.get_backend() == 'cpu'

    def test_auto_backend_uses_project_priority_order(self, monkeypatch):
        """Auto backend should use project priority cuda > vulkan > cpu."""
        manager = BackendManager()
        init_calls = []

        monkeypatch.setattr(
            BackendManager,
            "get_available_backends",
            staticmethod(lambda: ['cuda', 'vulkan', 'cpu']),
        )

        def fake_init(*args, **kwargs):
            init_calls.append(kwargs.get('arch'))

        monkeypatch.setattr("edda.backend.backend_manager.ti.init", fake_init)
        monkeypatch.setattr(
            manager,
            "_detect_device_info",
            lambda: setattr(manager, "device_info", {"backend": manager.backend}),
        )

        manager.initialize(backend='auto')

        assert manager.is_initialized
        assert manager.get_backend() == 'cuda'
        assert init_calls[0] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
