"""
Adaptive time stepping for EDDA simulation.
Uses CFL condition to ensure numerical stability.
"""
import taichi as ti
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TimeStepper:
    """
    Adaptive time stepping based on CFL condition.

    The CFL (Courant-Friedrichs-Lewy) condition ensures numerical stability:
        dt <= CFL * min(dx, dy) / max_wave_speed

    where max_wave_speed = |u| + sqrt(g*h)
    """

    def __init__(
        self,
        t_start: float = 0.0,
        t_end: float = 3600.0,
        dt_initial: float = 0.1,
        dt_min: float = 1e-4,
        dt_max: float = 1.0,
        dt_output: float = 60.0,
        CFL: float = 0.5,
        dx: float = 10.0,
        dy: float = 10.0
    ):
        """
        Initialize time stepper.

        Args:
            t_start: Start time (s)
            t_end: End time (s)
            dt_initial: Initial time step (s)
            dt_min: Minimum allowed time step (s)
            dt_max: Maximum allowed time step (s)
            dt_output: Output interval (s)
            CFL: CFL number for stability (typically 0.3-0.5)
            dx: Grid spacing in x direction (m)
            dy: Grid spacing in y direction (m)
        """
        self.t_start = t_start
        self.t_end = t_end
        self.dt_initial = dt_initial
        self.dt_min = dt_min
        self.dt_max = dt_max
        self.dt_output = dt_output
        self.CFL = CFL
        self.dx = dx
        self.dy = dy

        # Current state
        self.t_current = t_start
        self.dt_current = dt_initial
        self.step_count = 0
        self.output_count = 0
        self.t_last_output = t_start

        # Statistics
        self.dt_history = []
        self.total_steps = 0
        self.rejected_steps = 0

        logger.info(f"TimeStepper initialized: t_end={t_end}s, CFL={CFL}, dt_output={dt_output}s")

    def compute_dt_cfl(self, max_wave_speed: float) -> float:
        """
        Compute time step based on CFL condition.

        Args:
            max_wave_speed: Maximum wave speed in domain (m/s)

        Returns:
            Computed time step (s)
        """
        if max_wave_speed < 1e-10:
            # No flow, use maximum time step
            return self.dt_max

        # CFL condition: dt = CFL * dx / max_wave_speed
        min_grid_spacing = min(self.dx, self.dy)
        dt_cfl = self.CFL * min_grid_spacing / max_wave_speed

        # Clamp to allowed range
        dt = np.clip(dt_cfl, self.dt_min, self.dt_max)

        return dt

    def adapt_time_step(self, max_wave_speed: float) -> float:
        """
        Adapt time step based on CFL condition.

        Args:
            max_wave_speed: Maximum wave speed in domain

        Returns:
            Adapted time step
        """
        dt_new = self.compute_dt_cfl(max_wave_speed)

        # Smooth time step changes (avoid large jumps)
        if self.dt_current > 0:
            # Limit time step change to factor of 2
            dt_new = np.clip(dt_new, 0.5 * self.dt_current, 2.0 * self.dt_current)

        # Ensure we don't overshoot output time
        t_next_output = self.t_last_output + self.dt_output
        if self.t_current + dt_new > t_next_output:
            dt_new = t_next_output - self.t_current

        # Ensure we don't overshoot end time
        if self.t_current + dt_new > self.t_end:
            dt_new = self.t_end - self.t_current

        self.dt_current = dt_new
        self.dt_history.append(dt_new)

        return dt_new

    def advance(self, dt: Optional[float] = None) -> bool:
        """
        Advance time by one step.

        Args:
            dt: Time step (if None, use current dt)

        Returns:
            True if simulation should continue, False if finished
        """
        if dt is None:
            dt = self.dt_current

        self.t_current = float(self.t_current + dt)
        self.step_count += 1
        self.total_steps += 1

        # Check if simulation is finished
        if self.t_current >= self.t_end:
            logger.info(f"Simulation finished at t={self.t_current:.2f}s")
            return False

        return True

    def reject_step(self, dt_retry: Optional[float] = None) -> float:
        """
        Reject the current candidate step without advancing simulation time.

        Args:
            dt_retry: Replacement dt for the retry. If omitted, halve current dt.

        Returns:
            The dt that will be used for the retry.
        """
        self.rejected_steps += 1

        if dt_retry is None:
            dt_retry = 0.5 * self.dt_current

        dt_retry = float(np.clip(dt_retry, self.dt_min, self.dt_max))
        self.dt_current = dt_retry
        return self.dt_current

    def should_output(self) -> bool:
        """
        Check if output should be written at current time.

        Returns:
            True if output should be written
        """
        if self.t_current - self.t_last_output >= self.dt_output - 1e-6:
            return True
        return False

    def mark_output(self):
        """Mark that output has been written at current time."""
        self.t_last_output = self.t_current
        self.output_count += 1
        logger.info(f"Output #{self.output_count} at t={self.t_current:.2f}s")

    def get_progress(self) -> float:
        """
        Get simulation progress as percentage.

        Returns:
            Progress (0-100)
        """
        if self.t_end <= self.t_start:
            return 100.0
        return 100.0 * (self.t_current - self.t_start) / (self.t_end - self.t_start)

    def get_remaining_time_estimate(self) -> float:
        """
        Estimate remaining simulation time.

        Returns:
            Estimated remaining time (s)
        """
        if self.step_count == 0 or self.dt_current <= 0:
            return 0.0

        remaining_sim_time = self.t_end - self.t_current
        avg_dt = np.mean(self.dt_history[-100:]) if self.dt_history else self.dt_current
        estimated_steps = remaining_sim_time / avg_dt

        return estimated_steps

    def get_statistics(self) -> dict:
        """
        Get time stepping statistics.

        Returns:
            Dictionary with statistics
        """
        stats = {
            't_current': self.t_current,
            'dt_current': self.dt_current,
            'step_count': self.step_count,
            'output_count': self.output_count,
            'progress': self.get_progress(),
            'total_steps': self.total_steps,
            'rejected_steps': self.rejected_steps,
        }

        if self.dt_history:
            stats['dt_min_used'] = np.min(self.dt_history)
            stats['dt_max_used'] = np.max(self.dt_history)
            stats['dt_mean'] = np.mean(self.dt_history)
            stats['dt_std'] = np.std(self.dt_history)

        return stats

    def log_statistics(self):
        """Log time stepping statistics."""
        stats = self.get_statistics()
        logger.info("=" * 60)
        logger.info("Time Stepping Statistics:")
        logger.info(f"  Current time: {stats['t_current']:.2f}s")
        logger.info(f"  Current dt: {stats['dt_current']:.4f}s")
        logger.info(f"  Total steps: {stats['total_steps']}")
        logger.info(f"  Output count: {stats['output_count']}")
        logger.info(f"  Progress: {stats['progress']:.1f}%")

        if 'dt_mean' in stats:
            logger.info(f"  dt range: [{stats['dt_min_used']:.4f}, {stats['dt_max_used']:.4f}]s")
            logger.info(f"  dt mean: {stats['dt_mean']:.4f}s ± {stats['dt_std']:.4f}s")

        logger.info("=" * 60)

    def reset(self):
        """Reset time stepper to initial state."""
        self.t_current = self.t_start
        self.dt_current = self.dt_initial
        self.step_count = 0
        self.output_count = 0
        self.t_last_output = self.t_start
        self.dt_history = []
        self.total_steps = 0
        self.rejected_steps = 0
        logger.info("TimeStepper reset")

    def is_finished(self) -> bool:
        """
        Check if simulation is finished.

        Returns:
            True if simulation has reached end time
        """
        return self.t_current >= self.t_end

    def get_time_info(self) -> dict:
        """
        Get current time information.

        Returns:
            Dictionary with time information
        """
        return {
            't_current': self.t_current,
            't_end': self.t_end,
            'dt_current': self.dt_current,
            'step_count': self.step_count,
            'progress': self.get_progress(),
            'is_finished': self.is_finished(),
        }


class AdaptiveTimeStepper(TimeStepper):
    """
    Enhanced adaptive time stepper with error control.
    """

    def __init__(self, *args, error_tolerance: float = 1e-3, **kwargs):
        """
        Initialize adaptive time stepper with error control.

        Args:
            error_tolerance: Relative error tolerance for time step adaptation
            *args, **kwargs: Arguments passed to TimeStepper
        """
        super().__init__(*args, **kwargs)
        self.error_tolerance = error_tolerance
        self.error_history = []

    def adapt_with_error(
        self,
        max_wave_speed: float,
        error_estimate: Optional[float] = None
    ) -> float:
        """
        Adapt time step based on CFL and error estimate.

        Args:
            max_wave_speed: Maximum wave speed
            error_estimate: Estimated local truncation error

        Returns:
            Adapted time step
        """
        # CFL-based time step
        dt_cfl = self.compute_dt_cfl(max_wave_speed)

        # Error-based time step adjustment
        if error_estimate is not None and error_estimate > 0:
            self.error_history.append(error_estimate)

            # Adjust time step based on error
            if error_estimate > self.error_tolerance:
                # Error too large, reduce time step
                factor = 0.9 * (self.error_tolerance / error_estimate) ** 0.5
                dt_error = self.dt_current * max(factor, 0.5)
            elif error_estimate < 0.5 * self.error_tolerance:
                # Error small, can increase time step
                factor = 0.9 * (self.error_tolerance / error_estimate) ** 0.5
                dt_error = self.dt_current * min(factor, 2.0)
            else:
                # Error acceptable, keep current time step
                dt_error = self.dt_current

            # Use minimum of CFL and error-based time steps
            dt_new = min(dt_cfl, dt_error)
        else:
            dt_new = dt_cfl

        # Apply constraints
        dt_new = np.clip(dt_new, self.dt_min, self.dt_max)

        # Smooth changes
        if self.dt_current > 0:
            dt_new = np.clip(dt_new, 0.5 * self.dt_current, 2.0 * self.dt_current)

        # Ensure we hit output times
        t_next_output = self.t_last_output + self.dt_output
        if self.t_current + dt_new > t_next_output:
            dt_new = t_next_output - self.t_current

        # Ensure we don't overshoot end time
        if self.t_current + dt_new > self.t_end:
            dt_new = self.t_end - self.t_current

        self.dt_current = dt_new
        self.dt_history.append(dt_new)

        return dt_new

    def reject_step(self):
        """Reject current time step and reduce dt."""
        self.rejected_steps += 1
        self.dt_current *= 0.5
        self.dt_current = max(self.dt_current, self.dt_min)
        logger.warning(f"Step rejected, reducing dt to {self.dt_current:.4f}s")
