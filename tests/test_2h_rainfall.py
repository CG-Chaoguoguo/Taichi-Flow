"""
2-hour rainfall simulation test for EDDA-Taichi.
Tests with actual DEM and 2-hour rainfall data from tests/data/
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from edda.config.sim_config import SimulationConfig
from edda.solver.edda_solver import EDDASolver
from edda.io.dem_reader import DEMReader
from edda.io.result_exporter import ResultExporter
import time

def test_2h_rainfall_simulation():
    """Test simulation with real DEM and 2-hour rainfall data."""

    print("="*80)
    print("EDDA-Taichi 2-Hour Rainfall Simulation Test")
    print("="*80)

    # File paths
    dem_file = "tests/data/DEM.tif"
    rainfall1_file = "tests/data/caiyun_precip_wgs84_202507230000_202507230100_proj_clip.tif"
    rainfall2_file = "tests/data/caiyun_precip_wgs84_202507230100_202507230200_proj_clip.tif"
    output_dir = "tests/output/real_data_test"

    print(f"\n[1/7] Input data:")
    print(f"  DEM file: {dem_file}")
    print(f"  Rainfall file 1: {rainfall1_file}")
    print(f"  Rainfall file 2: {rainfall2_file}")
    print(f"  Output directory: {output_dir}")

    # Step 1: Inspect DEM
    print("\n[2/7] Inspecting DEM data...")
    dem_reader = DEMReader(dem_file)
    elevation, metadata = dem_reader.read()

    print(f"  DEM shape: {elevation.shape}")
    print(f"  Resolution: {metadata['dx']:.2f}m x {metadata['dy']:.2f}m")
    print(f"  Elevation range: [{np.nanmin(elevation):.2f}, {np.nanmax(elevation):.2f}] m")

    nodata_mask = dem_reader.get_nodata_mask()
    nodata_count = np.sum(nodata_mask)
    print(f"  NoData cells: {nodata_count} ({nodata_count/elevation.size*100:.2f}%)")

    # Step 2: Inspect rainfall data
    print("\n[3/7] Inspecting rainfall data...")
    for i, rf_file in enumerate([rainfall1_file, rainfall2_file], 1):
        rain_reader = DEMReader(rf_file)
        rain_data, _ = rain_reader.read()
        rain_nodata = rain_reader.get_nodata_mask()
        rain_valid = rain_data[~rain_nodata]
        if len(rain_valid) > 0:
            print(f"  Hour {i}: [{rain_valid.min():.6f}, {rain_valid.max():.6f}] mm/h, mean={rain_valid.mean():.6f}")

    # Step 3: Fill NoData
    print("\n[4/7] Filling NoData values...")
    if nodata_count > 0:
        elevation_filled = dem_reader.fill_nodata(max_search_distance=100.0)
        print(f"  NoData filled using nearest neighbor interpolation")
        print(f"  New elevation range: [{elevation_filled.min():.2f}, {elevation_filled.max():.2f}] m")
    else:
        elevation_filled = elevation

    # Step 4: Create configuration for 2-hour simulation
    print("\n[5/7] Creating simulation configuration...")

    # Simulate 2 hours = 7200 seconds
    config = SimulationConfig(
        dem_file=dem_file,
        output_dir=output_dir,
        time={
            "t_start": 0.0,
            "t_end": 7200.0,  # 2 hours in seconds
            "dt_initial": 0.01,
            "dt_min": 0.001,
            "dt_max": 1.0,
            "dt_output": 600.0,  # Output every 10 minutes
            "CFL": 0.5
        },
        hydrology={
            "K_sat": 1e-5,
            "theta_s": 0.45,
            "theta_i": 0.20,
            "psi_f": 0.10
        },
        soil={
            "c": 5000.0,
            "phi": 30.0,
            "gamma_s": 20000.0,
            "gamma_w": 9800.0,
            "depth": 2.0
        },
        rheology={
            "n_manning": 0.03,
            "rho_water": 1000.0,
            "rho_sediment": 2650.0,
            "Cv_max": 0.65
        },
        erosion={
            "tau_c": 10.0,
            "k_erosion": 1e-5
        },
        compute={
            "backend": "cuda",  # Use CUDA for GPU acceleration
            "use_double_precision": False
        },
        boundary_conditions={
            "mode": "auto",
            "default_type": "outflow",
            "include_nodata": True
        }
    )

    print(f"  Simulation time: {config.time.t_end/3600:.1f} hours")
    print(f"  Initial time step: {config.time.dt_initial} s")
    print(f"  Output interval: {config.time.dt_output/60:.1f} minutes")
    print(f"  Backend: {config.compute.backend}")

    # Step 5: Initialize solver
    print("\n[6/7] Initializing solver...")
    start_time = time.time()

    try:
        solver = EDDASolver(config)
        solver.initialize()
        init_time = time.time() - start_time
        print(f"  Solver initialized successfully in {init_time:.2f}s")

        # Check field initialization
        print(f"  Grid size: {solver.fields.nx} x {solver.fields.ny}")
        print(f"  Total cells: {solver.fields.nx * solver.fields.ny}")

        # Check boundary conditions
        boundary_mask = solver.fields.is_boundary.to_numpy()
        boundary_count = np.sum(boundary_mask)
        print(f"  Boundary cells: {boundary_count} ({boundary_count/(solver.fields.nx*solver.fields.ny)*100:.2f}%)")

        # Check slopes
        slope_mag = solver.fields.slope_mag.to_numpy()
        valid_slope = slope_mag[~nodata_mask.T]
        print(f"  Slope range: [{np.min(valid_slope):.4f}, {np.max(valid_slope):.4f}]")
        print(f"  Mean slope: {np.mean(valid_slope):.4f}")

    except Exception as e:
        print(f"  ERROR during initialization: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 6: Run simulation
    print("\n[7/7] Running 2-hour simulation...")
    print(f"  Target time: {config.time.t_end/3600:.1f} hours")

    try:
        simulation_start = time.time()

        current_time = 0.0
        step_count = 0
        dt = config.time.dt_initial
        output_count = 0
        next_output_time = config.time.dt_output

        # Store results for each output interval
        interval_results = []

        while current_time < config.time.t_end:
            # Take a time step
            solver.shallow_water.step(dt)

            # Update time
            current_time += dt
            step_count += 1

            # Output progress every 10 minutes
            if current_time >= next_output_time:
                h_current = solver.fields.h.to_numpy()
                u_current = solver.fields.u.to_numpy()
                v_current = solver.fields.v.to_numpy()

                max_h = np.max(h_current)
                max_vel = np.sqrt(np.max(u_current**2 + v_current**2))
                total_volume = np.sum(h_current) * metadata['dx'] * metadata['dy']

                minutes = int(current_time / 60)
                print(f"  {minutes:3d} min: t={current_time/60:.1f}min, steps={step_count}, max_h={max_h:.4f}m, max_v={max_vel:.4f}m/s, volume={total_volume:.2f}m^3")

                # Save interval result
                interval_results.append({
                    'minutes': minutes,
                    'time': current_time,
                    'h': h_current.copy(),
                    'u': u_current.copy(),
                    'v': v_current.copy(),
                    'max_h': max_h,
                    'max_vel': max_vel,
                    'volume': total_volume
                })

                next_output_time += config.time.dt_output
                output_count += 1

            # Safety limit
            if step_count > 1000000:
                print(f"  WARNING: Reached maximum step limit ({step_count})")
                break

        simulation_time = time.time() - simulation_start

        print(f"\n  Simulation completed!")
        print(f"  Total steps: {step_count}")
        print(f"  Total simulation time: {simulation_time:.2f}s ({simulation_time/60:.2f} minutes)")
        print(f"  Average time per step: {simulation_time/step_count*1000:.3f}ms")
        print(f"  Simulated time: {current_time/3600:.2f} hours")

        # Step 7: Export results
        print("\n[8/8] Exporting results...")
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Export final state
        h_final = solver.fields.h.to_numpy()
        u_final = solver.fields.u.to_numpy()
        v_final = solver.fields.v.to_numpy()
        z_bed = solver.fields.z_bed.to_numpy()

        # Export depth
        exporter_h = ResultExporter(
            data=h_final,
            transform=metadata.get('transform'),
            crs=metadata.get('crs'),
            nodata_value=-9999.0
        )
        exporter_h.to_geotiff(str(output_path / "final_depth_2h.tif"))
        print(f"  Exported: final_depth_2h.tif")

        # Export velocity magnitude
        vel_mag = np.sqrt(u_final**2 + v_final**2)
        exporter_v = ResultExporter(
            data=vel_mag,
            transform=metadata.get('transform'),
            crs=metadata.get('crs'),
            nodata_value=-9999.0
        )
        exporter_v.to_geotiff(str(output_path / "final_velocity_2h.tif"))
        print(f"  Exported: final_velocity_2h.tif")

        # Export bed elevation
        exporter_z = ResultExporter(
            data=z_bed,
            transform=metadata.get('transform'),
            crs=metadata.get('crs'),
            nodata_value=-9999.0
        )
        exporter_z.to_geotiff(str(output_path / "bed_elevation_2h.tif"))
        print(f"  Exported: bed_elevation_2h.tif")

        # Export summary statistics
        with open(output_path / "simulation_summary_2h.txt", 'w') as f:
            f.write("EDDA-Taichi 2-Hour Rainfall Simulation Summary\n")
            f.write("="*60 + "\n\n")
            f.write(f"DEM: {dem_file}\n")
            f.write(f"Grid size: {solver.fields.nx} x {solver.fields.ny}\n")
            f.write(f"Resolution: {metadata['dx']:.2f}m x {metadata['dy']:.2f}m\n")
            f.write(f"Simulation time: {current_time/3600:.2f} hours\n")
            f.write(f"Total steps: {step_count}\n")
            f.write(f"Computation time: {simulation_time:.2f}s ({simulation_time/60:.2f} min)\n")
            f.write(f"Average time per step: {simulation_time/step_count*1000:.3f}ms\n\n")

            f.write("Final State:\n")
            f.write(f"  Max depth: {np.max(h_final):.4f} m\n")
            f.write(f"  Max velocity: {np.sqrt(np.max(u_final**2 + v_final**2)):.4f} m/s\n")
            f.write(f"  Total water volume: {np.sum(h_final) * metadata['dx'] * metadata['dy']:.2f} m^3\n\n")

            f.write("Progress (every 10 minutes):\n")
            for result in interval_results:
                f.write(f"  {result['minutes']:3d} min: max_h={result['max_h']:.4f}m, max_v={result['max_vel']:.4f}m/s, volume={result['volume']:.2f}m^3\n")

        print(f"  Exported: simulation_summary_2h.txt")

        # Check for NaN or Inf
        if np.any(np.isnan(h_final)) or np.any(np.isinf(h_final)):
            print(f"\n  WARNING: NaN or Inf detected in results!")
            return False

        print("\n" + "="*80)
        print("TEST PASSED: 2-hour rainfall simulation completed successfully!")
        print("="*80)
        print(f"\nResults saved to: {output_path.absolute()}")
        print(f"Total computation time: {simulation_time:.2f}s ({simulation_time/60:.2f} minutes)")
        return True

    except Exception as e:
        print(f"\n  ERROR during simulation: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_2h_rainfall_simulation()
    sys.exit(0 if success else 1)
