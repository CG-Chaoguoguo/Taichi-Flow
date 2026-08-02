"""
EDDA solver package.

Contains the main solver and supporting components:
- ShallowWaterSolver: HLLC Riemann solver for shallow water equations
- TimeStepper: Adaptive time stepping with CFL condition
- EDDASolver: Main solver integrating all physics modules
"""
from edda.solver.shallow_water import ShallowWaterSolver
from edda.solver.time_stepper import TimeStepper, AdaptiveTimeStepper
from edda.solver.edda_solver import EDDASolver, run_simulation

__all__ = [
    'ShallowWaterSolver',
    'TimeStepper',
    'AdaptiveTimeStepper',
    'EDDASolver',
    'run_simulation',
]
