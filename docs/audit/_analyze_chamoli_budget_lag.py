"""Zero-cost Chamoli volume/wavefront lag analysis from existing t=900 grids.

Uses artifacts/chamoli_cuda_t900_wavefront and the Fortran oracle ASC files.
Does not rerun CUDA. Cell area is hardcoded to 30 m * 30 m because Taichi
writer headers currently emit cellsize 1.0.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from docs.audit._run_chamoli_window import align_arrays, find_grid, read_ascii_grid, write_json

REPO = Path(r"C:\Users\Administrator\Desktop\Taichi-Flow")
ACTUAL_DIR = REPO / "artifacts" / "chamoli_cuda_t900_wavefront" / "solver_output"
REFERENCE_DIR = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\results"
)
GLACIER = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\data\tutorial\glacier.asc"
)
LANDSLIDE = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\Data\tutorial\landslide.asc"
)
OUT_DIR = REPO / "artifacts" / "chamoli_cuda_t900_wavefront"
CELL_AREA = 30.0 * 30.0
WET_EPS = 1.0e-12
NODATA = -9990.0
CHECKPOINTS = [float(t) for t in range(45, 901, 45)]
FAMILIES = (
    "Flow_depth_EDDA",
    "Erosion_depth_EDDA",
    "Deposit_depth_EDDA",
    "SFdepthEDDA",
    "DFdepthEDDA",
    "FFdepthEDDA",
    "Total_depth_EDDA",
)
INFLOW_CELL_IDS = (5902, 11693, 39153, 3932, 1131)


def valid_mask(actual: np.ndarray, reference: np.ndarray) -> np.ndarray:
    return np.isfinite(actual) & np.isfinite(reference) & (reference > NODATA) & (actual > NODATA)


def load_pair(family: str, checkpoint: float) -> tuple[np.ndarray, np.ndarray] | None:
    actual_path = find_grid(ACTUAL_DIR, family, checkpoint)
    reference_path = find_grid(REFERENCE_DIR, family, checkpoint)
    if actual_path is None or reference_path is None:
        return None
    return align_arrays(read_ascii_grid(actual_path), read_ascii_grid(reference_path))


def volume_row(actual: np.ndarray, reference: np.ndarray) -> dict:
    valid = valid_mask(actual, reference)
    a = actual[valid]
    r = reference[valid]
    vol_a = float(np.sum(a) * CELL_AREA)
    vol_r = float(np.sum(r) * CELL_AREA)
    wet_a = valid & (np.abs(actual) > WET_EPS)
    wet_r = valid & (np.abs(reference) > WET_EPS)
    diff = actual - reference
    abs_diff = np.abs(diff)
    abs_diff[~valid] = 0.0
    peak_idx = np.unravel_index(int(np.argmax(abs_diff)), abs_diff.shape)
    return {
        "vol_taichi_m3": vol_a,
        "vol_fortran_m3": vol_r,
        "vol_delta_m3": vol_a - vol_r,
        "vol_ratio": (vol_a / vol_r) if vol_r else None,
        "sum_taichi": float(np.sum(a)),
        "sum_fortran": float(np.sum(r)),
        "wet_taichi": int(np.count_nonzero(wet_a)),
        "wet_fortran": int(np.count_nonzero(wet_r)),
        "wet_only_taichi": int(np.count_nonzero(wet_a & ~wet_r)),
        "wet_only_fortran": int(np.count_nonzero(wet_r & ~wet_a)),
        "wet_overlap": int(np.count_nonzero(wet_a & wet_r)),
        "max_abs": float(np.max(abs_diff)) if np.any(valid) else None,
        "max_abs_ij": [int(peak_idx[0]), int(peak_idx[1])],
        "taichi_at_peak": float(actual[peak_idx]),
        "fortran_at_peak": float(reference[peak_idx]),
        "taichi_minus_fortran_at_peak": float(diff[peak_idx]),
    }


def first_wet_frame(stack: np.ndarray) -> np.ndarray:
    """stack shape (n_frames, ny, nx). Returns frame index 1..n, 0 if never wet."""
    wet = np.abs(stack) > WET_EPS
    n = stack.shape[0]
    arrival = np.zeros(stack.shape[1:], dtype=np.int16)
    still_dry = np.ones(stack.shape[1:], dtype=bool)
    for k in range(n):
        newly = wet[k] & still_dry
        arrival[newly] = k + 1
        still_dry &= ~newly
    return arrival


def spatial_context(only_r: np.ndarray, glacier: np.ndarray | None, landslide: np.ndarray | None) -> dict:
    ys, xs = np.where(only_r)
    if ys.size == 0:
        return {"count": 0}
    out: dict = {
        "count": int(ys.size),
        "centroid_ij": [float(np.mean(ys)), float(np.mean(xs))],
        "bbox": [int(np.min(ys)), int(np.min(xs)), int(np.max(ys)), int(np.max(xs))],
    }
    if glacier is not None:
        g = glacier[only_r]
        g = g[np.isfinite(g) & (g > NODATA)]
        out["glacier_overlap"] = int(np.count_nonzero(g > 0.0))
        out["glacier_median"] = float(np.median(g)) if g.size else None
    if landslide is not None:
        s = landslide[only_r]
        s = s[np.isfinite(s) & (s > NODATA)]
        out["landslide_overlap"] = int(np.count_nonzero(s > 0.0))
    return out


def load_optional_raster(path: Path, reference_shape: tuple[int, int]) -> np.ndarray | None:
    if not path.exists():
        alt = Path(str(path).replace("Data", "data"))
        if alt.exists():
            path = alt
        else:
            return None
    raw = read_ascii_grid(path)
    if raw.shape == reference_shape:
        return raw
    aligned, _ = align_arrays(raw, np.zeros(reference_shape))
    return aligned


def main() -> None:
    frames: list[dict] = []
    flow_a_stack: list[np.ndarray] = []
    flow_r_stack: list[np.ndarray] = []
    ref_shape: tuple[int, int] | None = None
    glacier = None
    landslide = None

    for t in CHECKPOINTS:
        block: dict = {"t": t}
        missing = []
        for family in FAMILIES:
            pair = load_pair(family, t)
            if pair is None:
                missing.append(family)
                continue
            actual, reference = pair
            if ref_shape is None:
                ref_shape = reference.shape
                glacier = load_optional_raster(GLACIER, ref_shape)
                landslide = load_optional_raster(LANDSLIDE, ref_shape)
            block[family] = volume_row(actual, reference)
            if family == "Flow_depth_EDDA":
                flow_a_stack.append(actual)
                flow_r_stack.append(reference)
                valid = valid_mask(actual, reference)
                only_r = valid & (np.abs(reference) > WET_EPS) & ~(np.abs(actual) > WET_EPS)
                only_a = valid & (np.abs(actual) > WET_EPS) & ~(np.abs(reference) > WET_EPS)
                block["fortran_only_spatial"] = spatial_context(only_r, glacier, landslide)
                block["taichi_only_spatial"] = spatial_context(only_a, glacier, landslide)
        block["missing_families"] = missing
        frames.append(block)
        fd = block.get("Flow_depth_EDDA", {})
        er = block.get("Erosion_depth_EDDA", {})
        de = block.get("Deposit_depth_EDDA", {})
        print(
            f"t={t:6.0f}  flow dV={fd.get('vol_delta_m3'):+.0f} "
            f"ratio={fd.get('vol_ratio')} wet F-only={fd.get('wet_only_fortran')} "
            f"T-only={fd.get('wet_only_taichi')}  "
            f"ero dV={er.get('vol_delta_m3'):+.0f}  dep dV={de.get('vol_delta_m3'):+.0f}  "
            f"peak={fd.get('max_abs'):.2f} @{fd.get('max_abs_ij')} "
            f"T={fd.get('taichi_at_peak'):.2f} F={fd.get('fortran_at_peak'):.2f}"
        )

    arrival = None
    if flow_a_stack and flow_r_stack:
        a_stack = np.stack(flow_a_stack, axis=0)
        r_stack = np.stack(flow_r_stack, axis=0)
        arr_a = first_wet_frame(a_stack)
        arr_r = first_wet_frame(r_stack)
        both = (arr_a > 0) & (arr_r > 0)
        only_r_ever = (arr_r > 0) & (arr_a == 0)
        only_a_ever = (arr_a > 0) & (arr_r == 0)
        lag = np.zeros_like(arr_a, dtype=np.int16)
        lag[both] = arr_a[both] - arr_r[both]
        arrival = {
            "n_frames": int(a_stack.shape[0]),
            "frame_dt_s": 45.0,
            "both_wet_cells": int(np.count_nonzero(both)),
            "fortran_only_ever": int(np.count_nonzero(only_r_ever)),
            "taichi_only_ever": int(np.count_nonzero(only_a_ever)),
            "taichi_later_frames_mean": float(np.mean(lag[both])) if np.any(both) else None,
            "taichi_later_frames_median": float(np.median(lag[both])) if np.any(both) else None,
            "taichi_later_by_1plus": int(np.count_nonzero(lag > 0)),
            "taichi_earlier_by_1plus": int(np.count_nonzero(lag < 0)),
            "same_arrival_frame": int(np.count_nonzero(lag == 0) - np.count_nonzero(~both)),
            "same_arrival_on_both": int(np.count_nonzero((lag == 0) & both)),
            "max_lag_frames": int(np.max(lag)) if lag.size else 0,
            "min_lag_frames": int(np.min(lag)) if lag.size else 0,
            "fortran_only_ever_spatial": spatial_context(only_r_ever, glacier, landslide),
            "taichi_only_ever_spatial": spatial_context(only_a_ever, glacier, landslide),
        }
        late = lag > 0
        arrival["late_spatial"] = spatial_context(late, glacier, landslide)

    def first_diverge(key: str, vol_key: str, threshold: float) -> dict | None:
        for frame in frames:
            row = frame.get(key) or {}
            val = row.get(vol_key)
            if val is None:
                continue
            if abs(float(val)) >= threshold:
                return {"t": frame["t"], vol_key: val, "max_abs": row.get("max_abs")}
        return None

    conclusion = {
        "inflow_volume_t900_m3": 47.5 * 900.0,
        "cell_area_m2": CELL_AREA,
        "first_flow_volume_diverge_1000m3": first_diverge("Flow_depth_EDDA", "vol_delta_m3", 1000.0),
        "first_erosion_volume_diverge_1000m3": first_diverge("Erosion_depth_EDDA", "vol_delta_m3", 1000.0),
        "first_deposit_volume_diverge_1000m3": first_diverge("Deposit_depth_EDDA", "vol_delta_m3", 1000.0),
        "first_flow_maxabs_gt_10": first_diverge("Flow_depth_EDDA", "max_abs", 10.0),
        "t315_flow": next((f.get("Flow_depth_EDDA") for f in frames if f["t"] == 315.0), None),
        "t900_flow": next((f.get("Flow_depth_EDDA") for f in frames if f["t"] == 900.0), None),
        "t315_erosion": next((f.get("Erosion_depth_EDDA") for f in frames if f["t"] == 315.0), None),
        "t900_erosion": next((f.get("Erosion_depth_EDDA") for f in frames if f["t"] == 900.0), None),
        "branch_hint": None,
    }
    t45 = next((f for f in frames if f["t"] == 45.0), {})
    t315 = next((f for f in frames if f["t"] == 315.0), {})
    flow45 = t45.get("Flow_depth_EDDA") or {}
    flow315 = t315.get("Flow_depth_EDDA") or {}
    ero45 = t45.get("Erosion_depth_EDDA") or {}
    ero315 = t315.get("Erosion_depth_EDDA") or {}
    hints = []
    if abs(float(ero315.get("vol_delta_m3") or 0.0)) > abs(float(flow315.get("vol_delta_m3") or 0.0)):
        hints.append("erosion_volume_dominates_flow_volume_gap")
    if int(flow315.get("wet_only_fortran") or 0) > 0 and int(flow315.get("wet_only_taichi") or 0) == 0:
        hints.append("position_lag_fortran_only_wet")
    if abs(float(flow45.get("vol_ratio") or 1.0) - 1.0) < 0.05 and abs(float(flow315.get("vol_ratio") or 1.0) - 1.0) > 0.10:
        hints.append("volume_ratio_grows_with_time")
    if arrival and (arrival.get("taichi_later_by_1plus") or 0) > (arrival.get("taichi_earlier_by_1plus") or 0):
        hints.append("arrival_time_taichi_later")
    conclusion["hints"] = hints
    if "erosion_volume_dominates_flow_volume_gap" in hints and "position_lag_fortran_only_wet" not in hints:
        conclusion["branch_hint"] = "erosion_first"
    elif "position_lag_fortran_only_wet" in hints and "erosion_volume_dominates_flow_volume_gap" not in hints:
        conclusion["branch_hint"] = "position_lag_volume_ok"
    elif "position_lag_fortran_only_wet" in hints:
        conclusion["branch_hint"] = "mixed_lag_and_source"
    else:
        conclusion["branch_hint"] = "inspect_frames"

    payload = {
        "actual_dir": str(ACTUAL_DIR),
        "reference_dir": str(REFERENCE_DIR),
        "cell_area_m2": CELL_AREA,
        "inflow_cell_ids": list(INFLOW_CELL_IDS),
        "frames": frames,
        "arrival": arrival,
        "conclusion": conclusion,
        "parity_claim": False,
    }
    out_json = OUT_DIR / "budget_lag_analysis.json"
    write_json(out_json, payload)
    print("\n== conclusion ==")
    print(json.dumps(conclusion, indent=2, ensure_ascii=False, default=str))
    print(f"wrote {out_json}")


if __name__ == "__main__":
    main()
