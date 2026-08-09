"""Production-owned data contracts for native UNSFIN schedules.

The solver must remain importable from a clean source checkout.  Diagnostic
generators may produce this shape, but the runtime contract itself belongs to
the production package and cannot depend on ignored ``tools/`` modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class LedgerArrays:
    """Immutable arrays and provenance consumed by the UNSFIN provider."""

    gindx: np.ndarray
    tfail_s: np.ndarray
    fdepth_m: np.ndarray
    fsdepth_m: np.ndarray | None
    meta: dict[str, Any]
