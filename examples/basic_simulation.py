"""
Basic EDDA simulation example.

This example demonstrates how to:
1. Create a simple synthetic DEM
2. Configure simulation parameters
3. Run a debris flow simulation
4. Visualize results
"""
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_synthetic_dem(nx=100, ny=100, slope=0.1):
    """
    Create a synthetic DEM for testing.

    Args:
        nx: Number of cells in x direction
        ny: Number of cells in y direction
        slope: Average slope

    Returns:
        elevation: 2D array of elevations
    """
    logger.info(f"Creating synthetic DEM: {nx}x{ny}, slope={slope}")

    # Create a sloping terrain
    x = np.linspace(0, nx, nx)
    y = np.linspace(0, ny, ny)
    X, Y = np.meshgrid(x, y)

    # Base slope
    elevation = 1000.0 - slope * X

    # Add some roughness
    roughness = 5.0 * np.sin(X / 10) * np.cos(Y / 10)
    elevation += roughness

    # Add a channel
    channel_center = ny // 2
    channel_width = 10
    for i in range(nx):
        for j in range(ny):
            dist_from_center = abs(j - channel_center)
            if dist_from_center < channel_width:
                # Deepen the channel
                depth = 10.0 * (1.0 - dist_from_center / channel_width)
                elevation[j, i] -= depth

    return elevation.astype(np.float32)


def save_synthetic_dem(elevation, filename, dx=10.0, dy=10.0):
    """
    Save synthetic DEM to GeoTIFF format.

    Args:
        elevation: 2D elevation array
        filename: Output filename
        dx: Grid spacing in x (m)
        dy: Grid spacing in y (m)
    """
    try:
        import rasterio
        from rasterio.transform import from_origin

        ny, nx = elevation.shape

        # Create transform
        transform = from_origin(0.0, ny * dy, dx, dy)

        # Write GeoTIFF
        with rasterio.open(
            filename,
            'w',
            driver='GTiff',
            height=ny,
            width=nx,
            count=1,
            dtype=elevation.dtype,
            crs='EPSG:32633',  # UTM Zone 33N
            transform=transform,
        ) as dst:
            dst.write(elevation, 1)

        logger.info(f"Saved DEM to {filename}")

    except ImportError:
        logger.warning("rasterio not available, saving as numpy array")
        np.save(filename.replace('.tif', '.npy'), elevation)


def create_example_config(dem_file, output_dir="./output_example"):
    """
    Create example simulation configuration.

    Args:
        dem_file: Path to DEM file
        output_dir: Output directory

    Returns:
        SimulationConfig instance
    """
    config = SimulationConfig(
        # Input files
        dem_file=dem_file,
        rainfall_file=None,  # Will use constant rainfall

        # Output settings
        output_dir=output_dir,
        output_format="geotiff",
        save_intermediate=True,

        # Time parameters
        time={
            't_start': 0.0,
            't_end': 600.0,  # 10 minutes
            'dt_initial': 0.1,
            'dt_min': 0.01,
            'dt_max': 1.0,
            'dt_output': 60.0,  # Output every minute
            'CFL': 0.5,
        },

        # Compute parameters
        compute={
            'backend': 'auto',  # Auto-select best backend
            'use_double_precision': False,
        }
    )

    return config


def visualize_results(solver):
    """
    Visualize simulation results.

    Args:
        solver: EDDASolver instance with results
    """
    logger.info("Visualizing results...")

    results = solver.get_results()
    if not results:
        logger.warning("No results to visualize")
        return

    # Get final state
    final_state = results[-1]['state']

    # Create figure with subplots
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # Plot flow depth
    ax = axes[0, 0]
    im = ax.imshow(final_state['h'], cmap='Blues', origin='lower')
    ax.set_title('Flow Depth (m)')
    ax.set_xlabel('X (cells)')
    ax.set_ylabel('Y (cells)')
    plt.colorbar(im, ax=ax)

    # Plot velocity magnitude
    ax = axes[0, 1]
    velocity = np.sqrt(final_state['u']**2 + final_state['v']**2)
    im = ax.imshow(velocity, cmap='Reds', origin='lower')
    ax.set_title('Velocity (m/s)')
    ax.set_xlabel('X (cells)')
    ax.set_ylabel('Y (cells)')
    plt.colorbar(im, ax=ax)

    # Plot concentration
    ax = axes[1, 0]
    im = ax.imshow(final_state['Cv'], cmap='YlOrBr', origin='lower', vmin=0, vmax=0.65)
    ax.set_title('Sediment Concentration')
    ax.set_xlabel('X (cells)')
    ax.set_ylabel('Y (cells)')
    plt.colorbar(im, ax=ax)

    # Plot erosion/deposition
    ax = axes[1, 1]
    net_change = final_state['deposition_depth'] - final_state['erosion_depth']
    im = ax.imshow(net_change, cmap='RdBu_r', origin='lower')
    ax.set_title('Net Bed Change (m)\n(+deposition, -erosion)')
    ax.set_xlabel('X (cells)')
    ax.set_ylabel('Y (cells)')
    plt.colorbar(im, ax=ax)

    plt.tight_layout()

    # Save figure
    output_file = Path(solver.config.output_dir) / "results_visualization.png"
    plt.savefig(output_file, dpi=150)
    logger.info(f"Saved visualization to {output_file}")

    plt.show()


def main():
    """Run basic simulation example."""
    logger.info("=" * 60)
    logger.info("EDDA Basic Simulation Example")
    logger.info("=" * 60)

    # Create output directory
    output_dir = Path("./output_example")
    output_dir.mkdir(exist_ok=True)

    # Create synthetic DEM
    dem_file = output_dir / "synthetic_dem.tif"
    if not dem_file.exists():
        elevation = create_synthetic_dem(nx=100, ny=100, slope=0.1)
        save_synthetic_dem(elevation, str(dem_file))
    else:
        logger.info(f"Using existing DEM: {dem_file}")

    # Create configuration
    config = create_example_config(str(dem_file), str(output_dir))

    # Save configuration
    config_file = output_dir / "config.yaml"
    config.to_yaml(str(config_file))
    logger.info(f"Saved configuration to {config_file}")

    # Create and initialize solver
    logger.info("Initializing solver...")
    solver = EDDASolver(config)
    solver.initialize()

    # Run simulation
    logger.info("Running simulation...")
    solver.run()

    # Export final results
    logger.info("Exporting results...")
    solver.export_final_results(format='geotiff')

    # Visualize results
    try:
        visualize_results(solver)
    except Exception as e:
        logger.warning(f"Visualization failed: {e}")

    logger.info("=" * 60)
    logger.info("Example complete!")
    logger.info(f"Results saved to: {output_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
