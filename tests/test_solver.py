"""
Test solver implementation.
"""
import pytest
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from edda.solver.time_stepper import TimeStepper, AdaptiveTimeStepper


class TestTimeStepper:
    """Test time stepping functionality."""

    def test_initialization(self):
        """Test time stepper initialization."""
        stepper = TimeStepper(
            t_start=0.0,
            t_end=100.0,
            dt_initial=0.1,
            CFL=0.5
        )
        assert stepper.t_current == 0.0
        assert stepper.dt_current == 0.1
        assert not stepper.is_finished()

    def test_cfl_computation(self):
        """Test CFL-based time step computation."""
        stepper = TimeStepper(
            t_start=0.0,
            t_end=100.0,
            dt_initial=0.1,
            dt_min=0.01,
            dt_max=1.0,
            CFL=0.5,
            dx=10.0,
            dy=10.0
        )

        # Test with different wave speeds
        max_wave_speed = 5.0  # m/s
        dt = stepper.compute_dt_cfl(max_wave_speed)

        # dt should be CFL * dx / max_wave_speed
        expected_dt = 0.5 * 10.0 / 5.0  # = 1.0
        assert abs(dt - expected_dt) < 1e-6

    def test_time_advancement(self):
        """Test time advancement."""
        stepper = TimeStepper(
            t_start=0.0,
            t_end=10.0,
            dt_initial=1.0
        )

        # Advance time
        should_continue = stepper.advance(1.0)
        assert should_continue
        assert stepper.t_current == 1.0
        assert stepper.step_count == 1

        # Advance to end
        for _ in range(9):
            stepper.advance(1.0)

        assert stepper.is_finished()
        assert stepper.t_current >= 10.0

    def test_output_scheduling(self):
        """Test output scheduling."""
        stepper = TimeStepper(
            t_start=0.0,
            t_end=100.0,
            dt_initial=0.1,
            dt_output=10.0
        )

        # Should not output initially
        assert not stepper.should_output()

        # Advance to output time
        stepper.t_current = 10.0
        assert stepper.should_output()

        # Mark output
        stepper.mark_output()
        assert stepper.output_count == 1
        assert not stepper.should_output()

    def test_progress_calculation(self):
        """Test progress calculation."""
        stepper = TimeStepper(
            t_start=0.0,
            t_end=100.0,
            dt_initial=1.0
        )

        assert stepper.get_progress() == 0.0

        stepper.t_current = 50.0
        assert abs(stepper.get_progress() - 50.0) < 1e-6

        stepper.t_current = 100.0
        assert abs(stepper.get_progress() - 100.0) < 1e-6

    def test_statistics(self):
        """Test statistics collection."""
        stepper = TimeStepper(
            t_start=0.0,
            t_end=10.0,
            dt_initial=0.1
        )

        # Run some steps
        for _ in range(10):
            stepper.advance(0.1)

        stats = stepper.get_statistics()
        assert stats['step_count'] == 10
        assert stats['t_current'] == 1.0
        assert 'progress' in stats


class TestAdaptiveTimeStepper:
    """Test adaptive time stepping."""

    def test_error_based_adaptation(self):
        """Test error-based time step adaptation."""
        stepper = AdaptiveTimeStepper(
            t_start=0.0,
            t_end=100.0,
            dt_initial=0.1,
            error_tolerance=1e-3
        )

        # Test with large error (should reduce dt)
        dt = stepper.adapt_with_error(
            max_wave_speed=5.0,
            error_estimate=1e-2  # Error > tolerance
        )
        assert dt < stepper.dt_initial

        # Test with small error (should increase dt)
        stepper.dt_current = 0.1
        dt = stepper.adapt_with_error(
            max_wave_speed=5.0,
            error_estimate=1e-4  # Error < tolerance
        )
        # dt might increase (up to 2x)

    def test_step_rejection(self):
        """Test step rejection."""
        stepper = AdaptiveTimeStepper(
            t_start=0.0,
            t_end=100.0,
            dt_initial=1.0,
            dt_min=0.01
        )

        initial_dt = stepper.dt_current
        stepper.reject_step()

        assert stepper.rejected_steps == 1
        assert stepper.dt_current == 0.5 * initial_dt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
