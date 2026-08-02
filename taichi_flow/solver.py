"""Public solver alias for Taichi Flow.

The implementation is intentionally delegated to the compatibility solver so
the architecture refactor does not change equations, update order, or output
semantics.
"""

from edda.solver.edda_solver import EDDASolver


class FlowSolver(EDDASolver):
    """Taichi Flow solver public entrypoint."""


__all__ = ["FlowSolver"]
