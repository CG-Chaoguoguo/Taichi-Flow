"""Diagnose Chamoli CUDA vs Fortran t=45s residuals without claiming parity."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from docs.audit._run_chamoli_window import align_arrays, read_ascii_grid

ACTUAL = Path(r"C:\Users\Administrator\Desktop\Taichi-Flow\artifacts\chamoli_cuda_t45\solver_output")
REFERENCE = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\results")
OUT = Path(r"C:\Users\Administrator\Desktop\Taichi-Flow\artifacts\chamoli_cuda_t45\flow_depth_diag_t45.json")


def stats(path: Path) -> dict:
    arr = read_ascii_grid(path)
    finite = arr[np.isfinite(arr) & (arr > -9990.0)]
    wet = finite[np.abs(finite) > 1.0e-12]
    return {
        "path": str(path),
        "shape": list(arr.shape),
        "finite_count": int(finite.size),
        "wet_count": int(wet.size),
        "min": float(np.min(finite)) if finite.size else None,
        "max": float(np.max(finite)) if finite.size else None,
        "sum": float(np.sum(finite)) if finite.size else None,
        "wet_sum": float(np.sum(wet)) if wet.size else None,
        "mean_wet": float(np.mean(wet)) if wet.size else None,
    }


def main() -> None:
    actual_path = ACTUAL / "Flow_depth_Taichi_45.0.txt"
    reference_path = REFERENCE / "Flow_depth_EDDA_45.0.asc"
    actual_raw = read_ascii_grid(actual_path)
    reference_raw = read_ascii_grid(reference_path)
    actual, reference = align_arrays(actual_raw, reference_raw)
    valid = np.isfinite(actual) & np.isfinite(reference) & (reference > -9990.0) & (actual > -9990.0)
    wet_a = valid & (np.abs(actual) > 1.0e-12)
    wet_r = valid & (np.abs(reference) > 1.0e-12)
    overlap = wet_a & wet_r
    only_a = wet_a & ~wet_r
    only_r = wet_r & ~wet_a
    diff = np.zeros_like(actual)
    diff[valid] = actual[valid] - reference[valid]
    abs_diff = np.abs(diff)
    max_idx = np.unravel_index(int(np.argmax(abs_diff)), abs_diff.shape)
    payload = {
        "actual": stats(actual_path),
        "reference": stats(reference_path),
        "aligned_shape": list(actual.shape),
        "raw_shapes": {"actual": list(actual_raw.shape), "reference": list(reference_raw.shape)},
        "wet_actual": int(np.count_nonzero(wet_a)),
        "wet_reference": int(np.count_nonzero(wet_r)),
        "wet_overlap": int(np.count_nonzero(overlap)),
        "wet_only_actual": int(np.count_nonzero(only_a)),
        "wet_only_reference": int(np.count_nonzero(only_r)),
        "max_abs_error": float(np.max(abs_diff)),
        "max_abs_location": [int(max_idx[0]), int(max_idx[1])],
        "value_at_max_actual": float(actual[max_idx]),
        "value_at_max_reference": float(reference[max_idx]),
        "rmse_all_valid": float(np.sqrt(np.mean(np.square(diff[valid])))),
        "rmse_wet_union": float(np.sqrt(np.mean(np.square(diff[wet_a | wet_r])))) if np.any(wet_a | wet_r) else None,
        "sum_actual_valid": float(np.sum(actual[valid])),
        "sum_reference_valid": float(np.sum(reference[valid])),
        "sum_ratio": float(np.sum(actual[valid]) / np.sum(reference[valid])) if np.sum(reference[valid]) else None,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
