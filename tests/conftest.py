"""Keep process-global Taichi allocations and precision isolated per test.

Solver kernels/fields live in the Taichi Program beyond Python object scope.
Without a reset, a long DFS suite accumulates fields and can be OOM-killed;
collection/import order can also select a different default precision. There
are deliberately no module/session-scoped live solver fixtures in this suite.
"""
import gc

import pytest

from edda.backend.backend_manager import reset_taichi_runtime


@pytest.fixture(autouse=True)
def isolated_taichi_runtime():
    reset_taichi_runtime()
    try:
        yield
    finally:
        reset_taichi_runtime()
        gc.collect()
