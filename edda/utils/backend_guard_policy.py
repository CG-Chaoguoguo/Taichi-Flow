"""Backend comparison guard policies for evidence gates.

This module is intentionally comparison-only. It must not be imported by
solver runtime code to alter physical state, timestep lifecycle, mutation
kernels, or output/export behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Mapping

import numpy as np


BACKEND_COMPARISON_CONTEXT = "backend"
CPU_REFERENCE_VS_KERNEL_CONTEXT = "cpu_reference_vs_kernel"

DEFAULT_POLICY_NAME = "default_strict_backend_policy"
QMASSNET_POLICY_NAME = "qmassnet_fortran_cpu_cuda_backend_policy"


@dataclass(frozen=True)
class GuardTolerance:
    """Resolved tolerance and policy metadata for a field comparison."""

    rtol: float
    atol: float
    policy_name: str
    policy_applied: bool
    policy_scope: str
    reason: str


DEFAULT_TOLERANCE = GuardTolerance(
    rtol=1.0e-9,
    atol=1.0e-12,
    policy_name=DEFAULT_POLICY_NAME,
    policy_applied=False,
    policy_scope="all fields and non-CPU/CUDA backend comparison contexts",
    reason="default strict tolerance",
)

QMASSNET_CPU_CUDA_TOLERANCE = GuardTolerance(
    rtol=1.0e-8,
    atol=1.0e-10,
    policy_name=QMASSNET_POLICY_NAME,
    policy_applied=True,
    policy_scope="qmassnet_fortran CPU/CUDA backend comparisons only",
    reason=(
        "Test31 qmassnet_fortran CPU/CUDA accumulation-order drift is "
        "non-mutation-amplified and non-material downstream"
    ),
)


def _normalize_backend(backend: str | None) -> str | None:
    if backend is None:
        return None
    value = backend.strip().lower()
    if value == "x64":
        return "cpu"
    return value


def is_cpu_cuda_backend_pair(left_backend: str | None, right_backend: str | None) -> bool:
    """Return true only for CPU/CUDA backend pairs.

    Unknown or missing backends fail closed by returning false.
    """

    pair = {_normalize_backend(left_backend), _normalize_backend(right_backend)}
    return pair == {"cpu", "cuda"}


def resolve_guard_tolerance(
    *,
    field_name: str,
    comparison_context: str,
    left_backend: str | None = None,
    right_backend: str | None = None,
) -> GuardTolerance:
    """Resolve field-specific tolerance for a comparison context.

    The only relaxed policy is qmassnet_fortran under CPU/CUDA backend
    comparisons. All other fields and contexts use the strict default policy.
    """

    if (
        field_name == "qmassnet_fortran"
        and comparison_context == BACKEND_COMPARISON_CONTEXT
        and is_cpu_cuda_backend_pair(left_backend, right_backend)
    ):
        return QMASSNET_CPU_CUDA_TOLERANCE
    return DEFAULT_TOLERANCE


def _array_sha256(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(str(contiguous.shape).encode("ascii"))
    digest.update(str(contiguous.dtype).encode("ascii"))
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


def compare_guarded_arrays(
    left: np.ndarray,
    right: np.ndarray,
    *,
    field_name: str,
    comparison_context: str,
    left_backend: str | None = None,
    right_backend: str | None = None,
    mask: np.ndarray | None = None,
) -> dict[str, object]:
    """Compare arrays and return tolerance plus exact-hash diagnostics."""

    left_array = np.asarray(left)
    right_array = np.asarray(right)
    tolerance = resolve_guard_tolerance(
        field_name=field_name,
        comparison_context=comparison_context,
        left_backend=left_backend,
        right_backend=right_backend,
    )
    metadata = asdict(tolerance)
    result: dict[str, object] = {
        "field_name": field_name,
        "comparison_context": comparison_context,
        "left_backend": left_backend,
        "right_backend": right_backend,
        "left_shape": list(left_array.shape),
        "right_shape": list(right_array.shape),
        "left_dtype": str(left_array.dtype),
        "right_dtype": str(right_array.dtype),
        "left_sha256": _array_sha256(left_array),
        "right_sha256": _array_sha256(right_array),
        "exact_hash_match": _array_sha256(left_array) == _array_sha256(right_array),
        **metadata,
    }
    if left_array.shape != right_array.shape:
        result.update(
            {
                "shape_match": False,
                "tolerance_pass": False,
                "fail_count": max(int(left_array.size), int(right_array.size), 1),
                "max_abs": None,
                "max_rel": None,
            }
        )
        return result

    shape_mask = np.ones(left_array.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    if shape_mask.shape != left_array.shape:
        raise ValueError("mask shape must match compared arrays")

    left_selected = left_array[shape_mask]
    right_selected = right_array[shape_mask]
    diff = np.abs(left_selected - right_selected)
    denom = np.maximum(np.abs(left_selected), np.abs(right_selected))
    rel = np.divide(diff, denom, out=np.zeros_like(diff, dtype=np.float64), where=denom != 0)
    close = np.isclose(
        left_selected,
        right_selected,
        rtol=tolerance.rtol,
        atol=tolerance.atol,
        equal_nan=True,
    )
    fail_count = int(close.size - np.count_nonzero(close))
    result.update(
        {
            "shape_match": True,
            "compared_count": int(close.size),
            "tolerance_pass": fail_count == 0,
            "fail_count": fail_count,
            "max_abs": float(np.max(diff)) if diff.size else 0.0,
            "max_rel": float(np.max(rel)) if rel.size else 0.0,
        }
    )
    return result


def summarize_guarded_comparisons(comparisons: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    """Summarize a set of guarded comparison results without masking failures."""

    fail_count_total = 0
    policy_applied_fields: list[str] = []
    failed_fields: list[str] = []
    for field_name, result in comparisons.items():
        fail_count = int(result.get("fail_count", 0))
        fail_count_total += fail_count
        if result.get("policy_applied"):
            policy_applied_fields.append(field_name)
        if not result.get("tolerance_pass", False):
            failed_fields.append(field_name)
    return {
        "field_count": len(comparisons),
        "tolerance_fail_count_total": fail_count_total,
        "all_tolerance_pass": fail_count_total == 0,
        "policy_applied_fields": policy_applied_fields,
        "failed_fields": failed_fields,
    }


__all__ = [
    "BACKEND_COMPARISON_CONTEXT",
    "CPU_REFERENCE_VS_KERNEL_CONTEXT",
    "DEFAULT_POLICY_NAME",
    "QMASSNET_POLICY_NAME",
    "DEFAULT_TOLERANCE",
    "QMASSNET_CPU_CUDA_TOLERANCE",
    "GuardTolerance",
    "compare_guarded_arrays",
    "is_cpu_cuda_backend_pair",
    "resolve_guard_tolerance",
    "summarize_guarded_comparisons",
]
