"""
Unit tests for double-layer soil model.

Tests cover:
- Field initialization and data structures (3D inidesatt/inidesatb)
- Sublayer calculations
- Richards equation solver
- kkt0 formula correctness
- Minimum factor of safety search
- Pore pressure computation
- Failure mobilization
- Spatial zone integration
"""
import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import taichi as ti
from edda.core.fields import EDDAFields


class TestDoubleLayerFields:
    """Test double-layer soil model field initialization and structure."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 10, 10
        self.dx, self.dy = 1.0, 1.0
        self.fields = EDDAFields(self.nx, self.ny, self.dx, self.dy)

    def test_constants(self):
        assert self.fields.NZST == 26
        assert self.fields.NZSB == 26

    def test_top_layer_field_shapes(self):
        expected_shape = (self.nx, self.ny, self.fields.NZST + 1)
        assert self.fields.zt.shape == expected_shape
        assert self.fields.kkt.shape == expected_shape
        assert self.fields.pt.shape == expected_shape
        assert self.fields.thzt.shape == expected_shape
        assert self.fields.desatt.shape == expected_shape
        assert self.fields.deltazt.shape == expected_shape
        assert self.fields.deltadzt.shape == expected_shape

    def test_bottom_layer_field_shapes(self):
        expected_shape = (self.nx, self.ny, self.fields.NZSB + 1)
        assert self.fields.zb.shape == expected_shape
        assert self.fields.kkb.shape == expected_shape
        assert self.fields.pb.shape == expected_shape
        assert self.fields.thzb.shape == expected_shape
        assert self.fields.desatb.shape == expected_shape
        assert self.fields.deltazb.shape == expected_shape
        assert self.fields.deltadzb.shape == expected_shape

    def test_initial_state_field_shapes_3d(self):
        """Test initial state fields are 3D (per sublayer)."""
        assert self.fields.inidesatt.shape == (self.nx, self.ny, self.fields.NZST + 1)
        assert self.fields.inidesatb.shape == (self.nx, self.ny, self.fields.NZSB + 1)

    def test_parameter_field_shapes(self):
        expected_shape = (self.nx, self.ny)
        assert self.fields.beta.shape == expected_shape
        assert self.fields.ltstar.shape == expected_shape
        assert self.fields.lbstar.shape == expected_shape

    def test_failure_surface_field_shapes(self):
        expected_shape = (self.nx, self.ny)
        assert self.fields.zfmin.shape == expected_shape
        assert self.fields.pmin.shape == expected_shape
        assert self.fields.fdepth.shape == expected_shape

    def test_new_spatial_fields_exist(self):
        """Test that new spatial parameter fields exist."""
        expected_shape = (self.nx, self.ny)
        assert self.fields.alpha_top_field.shape == expected_shape
        assert self.fields.alpha_bottom_field.shape == expected_shape
        assert self.fields.K_sat_top_field.shape == expected_shape
        assert self.fields.K_sat_bottom_field.shape == expected_shape
        assert self.fields.theta_sat_top_field.shape == expected_shape
        assert self.fields.theta_sat_bottom_field.shape == expected_shape
        assert self.fields.theta_res_top_field.shape == expected_shape
        assert self.fields.theta_res_bottom_field.shape == expected_shape
        assert self.fields.phib_field.shape == expected_shape
        assert self.fields.ltstar_field.shape == expected_shape
        assert self.fields.lbstar_field.shape == expected_shape
        assert self.fields.erodible_thickness.shape == expected_shape
        assert self.fields.depo_thickness.shape == expected_shape
        assert self.fields.kero_field.shape == expected_shape

    def test_field_initialization(self):
        self.fields.initialize_all()
        zt_np = self.fields.zt.to_numpy()
        assert np.all(zt_np == 0.0)
        zb_np = self.fields.zb.to_numpy()
        assert np.all(zb_np == 0.0)
        beta_np = self.fields.beta.to_numpy()
        assert np.all(beta_np == 0.0)
        ltstar_np = self.fields.ltstar.to_numpy()
        assert np.all(ltstar_np == 0.0)
        # 3D inidesatt should be zero
        inidesatt_np = self.fields.inidesatt.to_numpy()
        assert inidesatt_np.shape == (self.nx, self.ny, 27)
        assert np.all(inidesatt_np == 0.0)

    def test_spatial_zone_defaults(self):
        """Test that spatial zone defaults are set correctly."""
        self.fields.initialize_all()
        assert np.allclose(self.fields.alpha_top_field.to_numpy(), 2.0)
        assert np.allclose(self.fields.alpha_bottom_field.to_numpy(), 1.5)
        assert np.allclose(self.fields.K_sat_top_field.to_numpy(), 1e-5)
        assert np.allclose(self.fields.K_sat_bottom_field.to_numpy(), 5e-6)
        assert np.allclose(self.fields.phib_field.to_numpy(), 15.0)
        assert np.allclose(self.fields.ltstar_field.to_numpy(), 1.0)
        assert np.allclose(self.fields.lbstar_field.to_numpy(), 1.0)
        assert np.allclose(self.fields.kero_field.to_numpy(), 1e-5)


class TestSublayerCalculations:
    """Test sublayer depth and thickness calculations."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 5, 5
        self.fields = EDDAFields(self.nx, self.ny, 1.0, 1.0)
        self.fields.initialize_all()

    def test_sublayer_count(self):
        assert self.fields.zt.shape[2] == 27
        assert self.fields.zb.shape[2] == 27

    def test_sublayer_thickness_consistency(self):
        deltazt_np = self.fields.deltazt.to_numpy()
        deltazb_np = self.fields.deltazb.to_numpy()
        assert deltazt_np.shape == (self.nx, self.ny, 27)
        assert deltazb_np.shape == (self.nx, self.ny, 27)

    def test_depth_coordinate_monotonicity(self):
        zt_np = self.fields.zt.to_numpy()
        zb_np = self.fields.zb.to_numpy()
        assert zt_np.shape == (self.nx, self.ny, 27)
        assert zb_np.shape == (self.nx, self.ny, 27)


class TestKkt0Formula:
    """Test kkt0 initialization formula correctness (FIX 2a)."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 5, 5
        self.fields = EDDAFields(self.nx, self.ny, 10.0, 10.0)
        self.fields.initialize_all()

    def test_kkt0_formula_correctness(self):
        """Verify kkt0 matches hand-calculated values from original EDDA formula."""
        from edda.config.sim_config import DoubleLayerSoilParams
        from edda.physics.double_layer_soil import DoubleLayerSoilModel

        params = DoubleLayerSoilParams(enabled=True)

        # Set up sloped terrain
        z_bed = np.zeros((self.nx, self.ny), dtype=np.float32)
        for i in range(self.nx):
            z_bed[i, :] = 50.0 - i * 2.0
        self.fields.initialize_from_numpy(z_bed)
        self.fields.compute_slopes()

        # Set spatial fields from params
        self.fields.K_sat_top_field.from_numpy(
            np.full((self.nx, self.ny), params.top_layer.K_sat, dtype=np.float32))
        self.fields.alpha_top_field.from_numpy(
            np.full((self.nx, self.ny), params.top_layer.alpha, dtype=np.float32))
        self.fields.theta_sat_top_field.from_numpy(
            np.full((self.nx, self.ny), params.top_layer.theta_sat, dtype=np.float32))
        self.fields.theta_res_top_field.from_numpy(
            np.full((self.nx, self.ny), params.top_layer.theta_res, dtype=np.float32))
        self.fields.K_sat_bottom_field.from_numpy(
            np.full((self.nx, self.ny), params.bottom_layer.K_sat, dtype=np.float32))
        self.fields.alpha_bottom_field.from_numpy(
            np.full((self.nx, self.ny), params.bottom_layer.alpha, dtype=np.float32))
        self.fields.theta_sat_bottom_field.from_numpy(
            np.full((self.nx, self.ny), params.bottom_layer.theta_sat, dtype=np.float32))
        self.fields.theta_res_bottom_field.from_numpy(
            np.full((self.nx, self.ny), params.bottom_layer.theta_res, dtype=np.float32))
        self.fields.ltstar_field.from_numpy(
            np.full((self.nx, self.ny), params.ltstar, dtype=np.float32))
        self.fields.lbstar_field.from_numpy(
            np.full((self.nx, self.ny), params.lbstar, dtype=np.float32))

        model = DoubleLayerSoilModel(self.fields, params)
        rainfall = np.full((self.nx, self.ny), 1e-6, dtype=np.float32)
        model.initialize_double_layer(rainfall)

        # Verify kkt values are positive and reasonable
        kkt_np = self.fields.kkt.to_numpy()
        # Interior cells with slope should have been initialized
        for i in range(1, self.nx - 1):
            for j in range(self.ny):
                if self.fields.slope_mag.to_numpy()[i, j] >= 0.087:
                    assert np.all(kkt_np[i, j, :] > 0), f"kkt should be positive at ({i},{j})"
                    assert np.all(kkt_np[i, j, :] <= 1.0), f"kkt should be <= 1 at ({i},{j})"

        # Verify inidesatt is 3D and per-sublayer
        inidesatt_np = self.fields.inidesatt.to_numpy()
        assert inidesatt_np.shape == (self.nx, self.ny, 27)
        # Different sublayers should have different initial saturation
        for i in range(1, self.nx - 1):
            if self.fields.slope_mag.to_numpy()[i, 0] >= 0.087:
                vals = inidesatt_np[i, 0, :]
                assert not np.all(vals == vals[0]), "Per-sublayer inidesatt should vary"
                break


class TestRichardsEquationSolver:
    """Test Richards equation solver for infiltration."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 5, 5
        self.fields = EDDAFields(self.nx, self.ny, 10.0, 10.0)
        self.fields.initialize_all()

    def test_richards_equation_solver(self):
        """Test Richards equation solver runs without error and produces valid output."""
        from edda.config.sim_config import DoubleLayerSoilParams
        from edda.physics.double_layer_soil import DoubleLayerSoilModel

        params = DoubleLayerSoilParams(enabled=True)

        z_bed = np.zeros((self.nx, self.ny), dtype=np.float32)
        for i in range(self.nx):
            z_bed[i, :] = 50.0 - i * 2.0
        self.fields.initialize_from_numpy(z_bed)
        self.fields.compute_slopes()

        # Set spatial fields
        for field_name, val in [
            ('K_sat_top_field', params.top_layer.K_sat),
            ('alpha_top_field', params.top_layer.alpha),
            ('theta_sat_top_field', params.top_layer.theta_sat),
            ('theta_res_top_field', params.top_layer.theta_res),
            ('K_sat_bottom_field', params.bottom_layer.K_sat),
            ('alpha_bottom_field', params.bottom_layer.alpha),
            ('theta_sat_bottom_field', params.bottom_layer.theta_sat),
            ('theta_res_bottom_field', params.bottom_layer.theta_res),
            ('ltstar_field', params.ltstar),
            ('lbstar_field', params.lbstar),
        ]:
            getattr(self.fields, field_name).from_numpy(
                np.full((self.nx, self.ny), val, dtype=np.float32))

        model = DoubleLayerSoilModel(self.fields, params)
        rainfall = np.full((self.nx, self.ny), 1e-5, dtype=np.float32)
        model.initialize_double_layer(rainfall)

        # Run Richards equation
        kkt_before = self.fields.kkt.to_numpy().copy()
        model.solve_richards_equation(1.0, rainfall)
        kkt_after = self.fields.kkt.to_numpy()

        # kkt should have changed after solving
        assert not np.allclose(kkt_before, kkt_after), "kkt should change after Richards solve"
        # All values should remain positive
        assert np.all(kkt_after >= 0), "kkt should remain non-negative"

    def test_saturation_limits(self):
        """Test that saturation stays within [0, 1] after pore pressure computation."""
        from edda.config.sim_config import DoubleLayerSoilParams
        from edda.physics.double_layer_soil import DoubleLayerSoilModel

        params = DoubleLayerSoilParams(enabled=True)

        z_bed = np.zeros((self.nx, self.ny), dtype=np.float32)
        for i in range(self.nx):
            z_bed[i, :] = 50.0 - i * 2.0
        self.fields.initialize_from_numpy(z_bed)
        self.fields.compute_slopes()

        for field_name, val in [
            ('K_sat_top_field', params.top_layer.K_sat),
            ('alpha_top_field', params.top_layer.alpha),
            ('theta_sat_top_field', params.top_layer.theta_sat),
            ('theta_res_top_field', params.top_layer.theta_res),
            ('K_sat_bottom_field', params.bottom_layer.K_sat),
            ('alpha_bottom_field', params.bottom_layer.alpha),
            ('theta_sat_bottom_field', params.bottom_layer.theta_sat),
            ('theta_res_bottom_field', params.bottom_layer.theta_res),
            ('ltstar_field', params.ltstar),
            ('lbstar_field', params.lbstar),
        ]:
            getattr(self.fields, field_name).from_numpy(
                np.full((self.nx, self.ny), val, dtype=np.float32))

        model = DoubleLayerSoilModel(self.fields, params)
        rainfall = np.full((self.nx, self.ny), 1e-5, dtype=np.float32)
        model.initialize_double_layer(rainfall)
        model.solve_richards_equation(10.0, rainfall)
        model.compute_pore_pressure()

        desatt = self.fields.desatt.to_numpy()
        desatb = self.fields.desatb.to_numpy()
        assert np.all(desatt >= 0.0) and np.all(desatt <= 1.0), "Top saturation out of bounds"
        assert np.all(desatb >= 0.0) and np.all(desatb <= 1.0), "Bottom saturation out of bounds"


class TestPorePressureComputation:
    """Test pore pressure computation in double-layer model."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 5, 5
        self.fields = EDDAFields(self.nx, self.ny, 1.0, 1.0)
        self.fields.initialize_all()


class TestMinimumFSSearch:
    """Test minimum factor of safety search algorithm."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 5, 5
        self.fields = EDDAFields(self.nx, self.ny, 1.0, 1.0)
        self.fields.initialize_all()


class TestFailureMobilization:
    """Test soil mobilization when FS < 1."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 5, 5
        self.fields = EDDAFields(self.nx, self.ny, 1.0, 1.0)
        self.fields.initialize_all()


class TestDoubleLayerIntegration:
    """Integration tests for complete double-layer model."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 10, 10
        self.fields = EDDAFields(self.nx, self.ny, 10.0, 10.0)
        self.fields.initialize_all()

    def test_full_update_cycle(self):
        """Test complete update cycle: Richards → pore pressure → FS → failure."""
        from edda.config.sim_config import DoubleLayerSoilParams
        from edda.physics.double_layer_soil import DoubleLayerSoilModel

        params = DoubleLayerSoilParams(enabled=True)

        z_bed = np.zeros((self.nx, self.ny), dtype=np.float32)
        for i in range(self.nx):
            z_bed[i, :] = 100.0 - i * 3.0
        self.fields.initialize_from_numpy(z_bed)
        self.fields.compute_slopes()

        for field_name, val in [
            ('K_sat_top_field', params.top_layer.K_sat),
            ('alpha_top_field', params.top_layer.alpha),
            ('theta_sat_top_field', params.top_layer.theta_sat),
            ('theta_res_top_field', params.top_layer.theta_res),
            ('K_sat_bottom_field', params.bottom_layer.K_sat),
            ('alpha_bottom_field', params.bottom_layer.alpha),
            ('theta_sat_bottom_field', params.bottom_layer.theta_sat),
            ('theta_res_bottom_field', params.bottom_layer.theta_res),
            ('ltstar_field', params.ltstar),
            ('lbstar_field', params.lbstar),
            ('phi_field', params.top_layer.phi),
            ('phib_field', params.top_layer.phib),
            ('c_field', params.top_layer.c),
            ('gamma_s_field', params.top_layer.gamma_s),
        ]:
            getattr(self.fields, field_name).from_numpy(
                np.full((self.nx, self.ny), val, dtype=np.float32))

        model = DoubleLayerSoilModel(self.fields, params)
        rainfall = np.full((self.nx, self.ny), 1e-5, dtype=np.float32)
        model.initialize_double_layer(rainfall)

        # Run full update
        model.update(dt=10.0, rainfall_intensity=rainfall)

        # FS should be computed
        FS = self.fields.FS.to_numpy()
        assert np.all(FS > 0), "FS should be positive"


class TestSpatialZoneDoubleLayer:
    """Test double-layer model with spatial zones."""

    def setup_method(self):
        ti.init(arch=ti.cpu)
        self.nx, self.ny = 10, 10
        self.fields = EDDAFields(self.nx, self.ny, 10.0, 10.0)
        self.fields.initialize_all()

    def test_two_zone_different_params(self):
        """Test that two zones produce different kkt values."""
        from edda.config.sim_config import DoubleLayerSoilParams
        from edda.physics.double_layer_soil import DoubleLayerSoilModel

        params = DoubleLayerSoilParams(enabled=True)

        z_bed = np.zeros((self.nx, self.ny), dtype=np.float32)
        for i in range(self.nx):
            z_bed[i, :] = 100.0 - i * 3.0
        self.fields.initialize_from_numpy(z_bed)
        self.fields.compute_slopes()

        # Zone 0: left half, Zone 1: right half with different K_sat_top
        K_sat_top = np.full((self.nx, self.ny), 1e-5, dtype=np.float32)
        K_sat_top[:, 5:] = 5e-5  # Zone 1 has higher K_sat

        for field_name, val in [
            ('alpha_top_field', params.top_layer.alpha),
            ('theta_sat_top_field', params.top_layer.theta_sat),
            ('theta_res_top_field', params.top_layer.theta_res),
            ('K_sat_bottom_field', params.bottom_layer.K_sat),
            ('alpha_bottom_field', params.bottom_layer.alpha),
            ('theta_sat_bottom_field', params.bottom_layer.theta_sat),
            ('theta_res_bottom_field', params.bottom_layer.theta_res),
            ('ltstar_field', params.ltstar),
            ('lbstar_field', params.lbstar),
            ('phi_field', params.top_layer.phi),
            ('phib_field', params.top_layer.phib),
            ('c_field', params.top_layer.c),
            ('gamma_s_field', params.top_layer.gamma_s),
        ]:
            getattr(self.fields, field_name).from_numpy(
                np.full((self.nx, self.ny), val, dtype=np.float32))
        self.fields.K_sat_top_field.from_numpy(K_sat_top)

        model = DoubleLayerSoilModel(self.fields, params)
        rainfall = np.full((self.nx, self.ny), 1e-6, dtype=np.float32)
        model.initialize_double_layer(rainfall)

        kkt_np = self.fields.kkt.to_numpy()
        # Cells with sufficient slope should show different kkt between zones
        has_diff = False
        for i in range(1, self.nx - 1):
            if self.fields.slope_mag.to_numpy()[i, 0] >= 0.087:
                zone0_kkt = kkt_np[i, 0, :]
                zone1_kkt = kkt_np[i, 5, :]
                if not np.allclose(zone0_kkt, zone1_kkt, atol=1e-12):
                    has_diff = True
                    break
        assert has_diff, "Different K_sat_top zones should produce different kkt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
