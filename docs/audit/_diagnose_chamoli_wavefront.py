"""Wavefront residual diagnosis for Chamoli post-fix (timeboxed rounds)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from docs.audit._run_chamoli_window import align_arrays, find_grid, read_ascii_grid

ACTUAL_DIR = Path(r"C:\Users\Administrator\Desktop\Taichi-Flow\artifacts\chamoli_cuda_t90_fix\solver_output")
REFERENCE_DIR = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\results")
OUT = Path(r"C:\Users\Administrator\Desktop\Taichi-Flow\artifacts\chamoli_cuda_t90_fix\wavefront_diag.json")
GLACIER = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\data\tutorial\glacier.asc"
)


def wet_masks(actual: np.ndarray, reference: np.ndarray) -> dict:
    valid = np.isfinite(actual) & np.isfinite(reference) & (reference > -9990.0) & (actual > -9990.0)
    wet_a = valid & (np.abs(actual) > 1.0e-12)
    wet_r = valid & (np.abs(reference) > 1.0e-12)
    only_a = wet_a & ~wet_r
    only_r = wet_r & ~wet_a
    overlap = wet_a & wet_r
    ys, xs = np.where(only_a)
    # Distance proxy from domain center of Fortran wet mass
    if np.any(wet_r):
        ry, rx = np.where(wet_r)
        rcy, rcx = float(np.mean(ry)), float(np.mean(rx))
    else:
        rcy = rcx = 0.0
    if ys.size:
        dist = np.sqrt((ys - rcy) ** 2 + (xs - rcx) ** 2)
        dist_stats = {
            "median": float(np.median(dist)),
            "p90": float(np.percentile(dist, 90)),
            "max": float(np.max(dist)),
        }
    else:
        dist_stats = None
    diff = actual - reference
    return {
        "wet_actual": int(np.count_nonzero(wet_a)),
        "wet_reference": int(np.count_nonzero(wet_r)),
        "wet_overlap": int(np.count_nonzero(overlap)),
        "wet_only_actual": int(np.count_nonzero(only_a)),
        "wet_only_reference": int(np.count_nonzero(only_r)),
        "sum_actual": float(np.sum(actual[valid])),
        "sum_reference": float(np.sum(reference[valid])),
        "sum_ratio": float(np.sum(actual[valid]) / np.sum(reference[valid])) if np.sum(reference[valid]) else None,
        "rmse_wet_union": float(np.sqrt(np.mean(np.square(diff[wet_a | wet_r])))) if np.any(wet_a | wet_r) else None,
        "max_abs": float(np.max(np.abs(diff[valid]))) if np.any(valid) else None,
        "taichi_only_dist_from_fortran_wet_centroid": dist_stats,
    }


def maxff_cell(checkpoint: float) -> dict:
    actual_path = find_grid(ACTUAL_DIR, "MaxFFdepthEDDA", checkpoint)
    reference_path = find_grid(REFERENCE_DIR, "MaxFFdepthEDDA", checkpoint)
    flow_a = find_grid(ACTUAL_DIR, "Max_flow_depth_EDDA", checkpoint)
    flow_r = find_grid(REFERENCE_DIR, "Max_flow_depth_EDDA", checkpoint)
    if not all([actual_path, reference_path, flow_a, flow_r]):
        return {"status": "missing"}
    maxff_a, maxff_r = align_arrays(read_ascii_grid(actual_path), read_ascii_grid(reference_path))
    flow_a_arr, flow_r_arr = align_arrays(read_ascii_grid(flow_a), read_ascii_grid(flow_r))
    # Probe cell highlighted in the plan: Fortran [725,617] in (i,j) or row/col?
    probes = [(725, 617), (617, 725)]
    probe_rows = []
    for i, j in probes:
        if i < maxff_a.shape[0] and j < maxff_a.shape[1]:
            probe_rows.append(
                {
                    "ij": [i, j],
                    "maxff_actual": float(maxff_a[i, j]),
                    "maxff_reference": float(maxff_r[i, j]),
                    "max_flow_actual": float(flow_a_arr[i, j]),
                    "max_flow_reference": float(flow_r_arr[i, j]),
                }
            )
    wet_a = np.count_nonzero(np.abs(maxff_a) > 1.0e-12)
    wet_r = np.count_nonzero(np.abs(maxff_r) > 1.0e-12)
    return {
        "wet_maxff_actual": int(wet_a),
        "wet_maxff_reference": int(wet_r),
        "max_abs_maxff": float(np.max(np.abs(maxff_a - maxff_r))),
        "probes": probe_rows,
    }


def glacier_stats_on_wavefront(checkpoint: float = 45.0) -> dict:
    flow_a_path = find_grid(ACTUAL_DIR, "Flow_depth_EDDA", checkpoint)
    flow_r_path = find_grid(REFERENCE_DIR, "Flow_depth_EDDA", checkpoint)
    if not flow_a_path or not flow_r_path or not GLACIER.exists():
        return {"status": "missing"}
    actual, reference = align_arrays(read_ascii_grid(flow_a_path), read_ascii_grid(flow_r_path))
    glacier_raw = read_ascii_grid(GLACIER)
    glacier, _ = align_arrays(glacier_raw, reference)
    valid = np.isfinite(actual) & np.isfinite(reference) & (reference > -9990.0) & (actual > -9990.0)
    wet_a = valid & (np.abs(actual) > 1.0e-12)
    only_a = wet_a & ~(valid & (np.abs(reference) > 1.0e-12))
    g = glacier[only_a]
    g = g[np.isfinite(g) & (g > -9990.0)]
    return {
        "glacier_on_taichi_only_wet": {
            "count": int(g.size),
            "min": float(np.min(g)) if g.size else None,
            "median": float(np.median(g)) if g.size else None,
            "max": float(np.max(g)) if g.size else None,
            "pct_gt_7": float(np.mean(g > 7.0)) if g.size else None,
            "pct_eq_approx_7": float(np.mean(np.abs(g - 7.0) < 0.05)) if g.size else None,
        }
    }


def friction_round_notes() -> dict:
    """Round 2-3: document friction-branch suspects without claiming a fix."""
    from edda.solver import dfs_dynamic_wave as dfs_mod
    import inspect

    source = inspect.getsource(dfs_mod)
    markers = {
        "debrisflowmanning_cvtol_branch": "debrisflowmanning_cvtol" in source,
        "cvero_field_rhoero": "cvero_field" in source and "rhoero" in source,
        "prev_cv_classify": "prev_cv = self.fields.Cv" in source,
    }
    return {
        "round": "friction_branch_audit",
        "markers_present": markers,
        "hypothesis": (
            "Post-fix Flow_depth wet footprint remains nearly unchanged vs pre-fix, "
            "so residual is unlikely to be solely missing glacier thickness or zone cvero. "
            "Next suspect remains debrisflowmanning_cvtol friction vs Fortran dfs.F90:417-428."
        ),
        "action_taken": "No further friction formula rewrite in this timeboxed pass; residual recorded honestly.",
    }


def main() -> None:
    payload = {
        "t45": {},
        "t90": {},
        "rounds": [],
    }
    for ck in (45.0, 90.0):
        a_path = find_grid(ACTUAL_DIR, "Flow_depth_EDDA", ck)
        r_path = find_grid(REFERENCE_DIR, "Flow_depth_EDDA", ck)
        actual, reference = align_arrays(read_ascii_grid(a_path), read_ascii_grid(r_path))
        block = wet_masks(actual, reference)
        block["maxff"] = maxff_cell(ck)
        if ck == 45.0:
            block["glacier"] = glacier_stats_on_wavefront(ck)
        payload[f"t{int(ck)}"] = block
    payload["rounds"].append(
        {
            "round": 1,
            "focus": "erodible_thickness_and_cvero_effect",
            "observation": payload["t45"],
            "conclusion": (
                "Taichi-only wet cells still present; glacier thickness on those cells is reported under glacier key. "
                "If median glacier >> 7, erodible wiring is active but wavefront still ahead for other reasons."
            ),
        }
    )
    payload["rounds"].append(
        {
            "round": 2,
            "focus": "maxff_prev_cv_window",
            "observation": {"t45_maxff": payload["t45"]["maxff"], "t90_maxff": payload["t90"]["maxff"]},
            "conclusion": "Compare MaxFF wet counts / probe cells against pre-fix 29 vs 2023 gap.",
        }
    )
    payload["rounds"].append(friction_round_notes())
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
