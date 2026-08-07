"""
Test physics modules for EDDA simulation.
"""
import sys
sys.path.insert(0, '/c/Users/Administrator/EDDA-Taichi')

import taichi as ti
import numpy as np

# Initialize Taichi
ti.init(arch=ti.cpu)

from edda.core.fields import EDDAFields
from edda.config.sim_config import (
    HydrologyParams,
    SoilParams,
    RheologyParams,
    ErosionParams,
)
from edda.physics import (
    HydrologyModel,
    StabilityModel,
    RheologyModel,
    ErosionModel,
    DepositionModel,
)


def test_hydrology():
    """Test hydrology module."""
    print("Testing hydrology module...")

    # Create fields
    nx, ny = 10, 10
    dx, dy = 10.0, 10.0
    fields = EDDAFields(nx, ny, dx, dy)
    fields.initialize_all()

    # Create hydrology model
    params = HydrologyParams()
    hydro = HydrologyModel(fields, params)

    # Set uniform rainfall
    hydro.set_uniform_rainfall(1e-5)  # 1e-5 m/s = 0.036 mm/hr

    # Run one time step
    dt = 1.0
    hydro.step(dt)

    # Check results
    infiltration = fields.infiltration.to_numpy()
    print(f"  Infiltration range: [{infiltration.min():.2e}, {infiltration.max():.2e}] m/s")
    print("  Hydrology module: OK")


def test_stability():
    """Test stability module."""
    print("Testing stability module...")

    # Create fields
    nx, ny = 10, 10
    dx, dy = 10.0, 10.0
    fields = EDDAFields(nx, ny, dx, dy)
    fields.initialize_all()

    # Set some slopes
    z_bed = np.zeros((nx, ny))
    for i in range(nx):
        for j in range(ny):
            z_bed[i, j] = 100.0 - i * 2.0  # 2m drop per cell
    fields.initialize_from_numpy(z_bed)
    fields.compute_slopes()

    # Create stability model
    params = SoilParams()
    stability = StabilityModel(fields, params)

    # Run one time step
    stability.step(check_failure=False)

    # Check results
    FS = fields.FS.to_numpy()
    print(f"  Factor of safety range: [{FS.min():.2f}, {FS.max():.2f}]")
    print("  Stability module: OK")


def test_rheology():
    """Test rheology module."""
    print("Testing rheology module...")

    # Create fields
    nx, ny = 10, 10
    dx, dy = 10.0, 10.0
    fields = EDDAFields(nx, ny, dx, dy)
    fields.initialize_all()

    # Set some flow conditions
    for i in range(nx):
        for j in range(ny):
            fields.h[i, j] = 1.0
            fields.u[i, j] = 2.0
            fields.v[i, j] = 0.0
            fields.Cv[i, j] = 0.3  # Debris flow

    # Create rheology model
    params = RheologyParams()
    rheology = RheologyModel(fields, params)

    # Update properties
    rheology.update_properties()

    # Check results
    rho = fields.rho.to_numpy()
    tau_y = fields.tau_y.to_numpy()
    print(f"  Density range: [{rho.min():.1f}, {rho.max():.1f}] kg/m³")
    print(f"  Yield stress range: [{tau_y.min():.1f}, {tau_y.max():.1f}] Pa")
    print("  Rheology module: OK")


def test_erosion():
    """Test erosion module."""
    print("Testing erosion module...")

    # Create fields
    nx, ny = 10, 10
    dx, dy = 10.0, 10.0
    fields = EDDAFields(nx, ny, dx, dy)
    fields.initialize_all()

    # Set some flow conditions
    z_bed = np.zeros((nx, ny))
    for i in range(nx):
        for j in range(ny):
            z_bed[i, j] = 100.0 - i * 2.0
            fields.h[i, j] = 1.0
            fields.u[i, j] = 5.0
            fields.v[i, j] = 0.0
            fields.Cv[i, j] = 0.1
            fields.rho[i, j] = 1100.0
    fields.initialize_from_numpy(z_bed)
    fields.compute_slopes()

    # Create erosion model
    erosion = ErosionModel(
        fields,
        tau_c=10.0,
        k_erosion=1e-5,
        rho_sediment=2650.0,
        rho_water=1000.0,
        phi=30.0
    )

    # Set erodible thickness (required for erosion to work)
    erodible = np.full((nx, ny), 2.0, dtype=np.float32)
    fields.erodible_thickness.from_numpy(erodible)

    # Set erosion coefficient in spatial field
    kero = np.full((nx, ny), 1e-5, dtype=np.float32)
    fields.kero_field.from_numpy(kero)

    # Run one time step
    dt = 0.1
    erosion.step(dt)

    # Check results
    erosion_rate = fields.erosion_rate.to_numpy()
    print(f"  Erosion rate range: [{erosion_rate.min():.2e}, {erosion_rate.max():.2e}] m/s")
    print("  Erosion module: OK")


def test_deposition():
    """Test deposition module."""
    print("Testing deposition module...")

    # Create fields
    nx, ny = 10, 10
    dx, dy = 10.0, 10.0
    fields = EDDAFields(nx, ny, dx, dy)
    fields.initialize_all()

    # Set some flow conditions with low velocity
    for i in range(nx):
        for j in range(ny):
            fields.h[i, j] = 1.0
            fields.u[i, j] = 0.2  # Low velocity for deposition
            fields.v[i, j] = 0.0
            fields.Cv[i, j] = 0.3

    # Set cvlimit_temp (normally set by erosion step)
    cvlimit = np.full((nx, ny), 0.2, dtype=np.float32)
    fields.cvlimit_temp.from_numpy(cvlimit)

    # Create deposition model
    params = ErosionParams()
    deposition = DepositionModel(fields, params)

    # Run one time step
    dt = 0.1
    deposition.step(dt)

    # Check results
    deposition_rate = fields.deposition_rate.to_numpy()
    print(f"  Deposition rate range: [{deposition_rate.min():.2e}, {deposition_rate.max():.2e}] m/s")
    print("  Deposition module: OK")


if __name__ == "__main__":
    print("=" * 60)
    print("EDDA Physics Modules Test")
    print("=" * 60)

    test_hydrology()
    test_stability()
    test_rheology()
    test_erosion()
    test_deposition()

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)
