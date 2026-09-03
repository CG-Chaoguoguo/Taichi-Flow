"""Numeric text-format compatibility helpers for original EDDA writers.

The original ``ssvgrd`` routine writes exact zeros with ``F2.0`` and all
other values with ``G12.4``. Two local comparison utilities historically used
slightly different numeric projections of that field: the original comparison
helper models the standard fixed/scientific branch, while the CUDA candidate
report rounds values that fit the fixed branch to four decimal places before
parsing them. Both projections live here so production code does not import
the ignored ``tools`` tree.
"""

from __future__ import annotations

import numpy as np


def _standard_g12p4(source: np.ndarray) -> np.ndarray:
    """Project values through the historical ``G12.4`` comparison helper."""

    result = np.zeros_like(source, dtype=np.float64)
    finite = np.isfinite(source)
    nonzero = finite & (source != 0.0)
    result[finite & ~nonzero] = 0.0
    result[~finite] = source[~finite]
    if not np.any(nonzero):
        return result

    # Choose the branch after the value is rounded to field precision. This
    # preserves the observed 0.099968 -> 0.1000 boundary behavior.
    rounded_to_4_decimal_places = np.round(source, 4)
    rounded_magnitude = np.abs(rounded_to_4_decimal_places)
    fixed_branch = nonzero & (rounded_magnitude >= 0.1) & (rounded_magnitude < 10000.0)
    if np.any(fixed_branch):
        fixed_values = source[fixed_branch]
        fixed_magnitudes = rounded_magnitude[fixed_branch]
        digits_left = np.zeros(fixed_values.shape, dtype=np.int64)
        ge_one = fixed_magnitudes >= 1.0
        digits_left[ge_one] = np.floor(np.log10(fixed_magnitudes[ge_one])).astype(np.int64) + 1
        decimals = np.maximum(4 - digits_left, 0)
        fixed_result = np.empty_like(fixed_values, dtype=np.float64)
        for decimal_count in range(0, 5):
            mask = decimals == decimal_count
            if np.any(mask):
                fixed_result[mask] = np.round(fixed_values[mask], decimal_count)
        result[fixed_branch] = fixed_result

    g_branch = nonzero & ~fixed_branch
    if np.any(g_branch):
        g_values = source[g_branch]
        result[g_branch] = np.fromiter(
            (float(f"{float(value):.4g}") for value in g_values),
            dtype=np.float64,
            count=int(g_values.size),
        )
    return result


def _candidate_g12p4(source: np.ndarray) -> np.ndarray:
    """Project the fixed-width values used by the CUDA candidate report.

    The candidate report's historical helper retained four decimal places in
    the fixed branch. Its branch decision is shared with the standard helper
    so values just below 0.1 retain the observed ``0.1000`` boundary result.
    """

    result = np.zeros_like(source, dtype=np.float64)
    finite = np.isfinite(source)
    nonzero = finite & (source != 0.0)
    result[finite & ~nonzero] = 0.0
    result[~finite] = source[~finite]
    if not np.any(nonzero):
        return result

    rounded_to_4_decimal_places = np.round(source, 4)
    rounded_magnitude = np.abs(rounded_to_4_decimal_places)
    fixed_branch = nonzero & (rounded_magnitude >= 0.1) & (rounded_magnitude < 10000.0)
    result[fixed_branch] = rounded_to_4_decimal_places[fixed_branch]

    g_branch = nonzero & ~fixed_branch
    if np.any(g_branch):
        g_values = source[g_branch]
        result[g_branch] = np.fromiter(
            (float(f"{float(value):.4g}") for value in g_values),
            dtype=np.float64,
            count=int(g_values.size),
        )
    return result


def fortran_ssvgrd_g12p4_numeric(values: np.ndarray) -> np.ndarray:
    """Return the standard numeric projection of an original ``G12.4`` field.

    The input shape is preserved. NaN and infinity are carried through, and
    exact zeros remain zero as produced by the writer's ``F2.0`` branch.
    """

    source = np.asarray(values, dtype=np.float64)
    return _standard_g12p4(source)


def fortran_ssvgrd_g12p4_numeric_candidate(values: np.ndarray) -> np.ndarray:
    """Return the legacy fixed-decimal projection used by CUDA reports."""

    source = np.asarray(values, dtype=np.float64)
    return _candidate_g12p4(source)


__all__ = [
    "fortran_ssvgrd_g12p4_numeric",
    "fortran_ssvgrd_g12p4_numeric_candidate",
]
