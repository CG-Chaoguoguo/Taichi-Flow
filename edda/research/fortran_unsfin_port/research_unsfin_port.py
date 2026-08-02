"""Research-only scaffold for the original EDDA `unsfin` schedule path.

This module is deliberately not imported by production runtime code.  It can
validate `gindx/fdepth` scaffold evidence from original outputs and validate a
supplied `tfail` artifact, but it never infers `tfail` from `LS_Scar` or
`faildph`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from edda.io.spatial_input_loader import SpatialInputLoader


@dataclass(frozen=True)
class UnsfinScaffold:
    """Research container for original failure scaffold arrays."""

    gindx: np.ndarray
    fdepth: np.ndarray
    tfail_s: Optional[np.ndarray]
    source: str


def _active_mask(gindx: np.ndarray, fdepth: np.ndarray) -> np.ndarray:
    return (np.asarray(gindx) > 0) & (np.asarray(fdepth) > 0.0)


def load_original_grid(path: str | Path) -> np.ndarray:
    """Load an original EDDA ASCII grid as a research array."""
    grid, _ = SpatialInputLoader(str(path)).read()
    return np.asarray(grid, dtype=np.float64)


def scaffold_from_ls_scar_and_faildph(
    ls_scar: np.ndarray,
    faildph: np.ndarray,
    *,
    infer_tfail: bool = False,
) -> UnsfinScaffold:
    """
    Build only the observable `gindx/fdepth` scaffold from original outputs.

    `LS_Scar` and `faildph` do not encode first failure time.  Passing
    `infer_tfail=True` raises to make accidental misuse explicit.
    """
    if infer_tfail:
        raise ValueError("LS_Scar/faildph cannot be used to infer per-cell tfail timing.")
    ls_arr = np.asarray(ls_scar, dtype=np.float64)
    fd_arr = np.asarray(faildph, dtype=np.float64)
    if ls_arr.shape != fd_arr.shape:
        raise ValueError(f"LS_Scar shape {ls_arr.shape} does not match faildph shape {fd_arr.shape}.")
    gindx = np.where(ls_arr > 0.0, 1, 0).astype(np.int32)
    fdepth = np.where(gindx > 0, fd_arr, 0.0).astype(np.float64)
    return UnsfinScaffold(
        gindx=gindx,
        fdepth=fdepth,
        tfail_s=None,
        source="original_outputs_scaffold_only",
    )


def validate_unsfin_scaffold(scaffold: UnsfinScaffold) -> Dict[str, Any]:
    """Summarize scaffold evidence without claiming schedule timing."""
    gindx = np.asarray(scaffold.gindx)
    fdepth = np.asarray(scaffold.fdepth, dtype=np.float64)
    if gindx.shape != fdepth.shape:
        raise ValueError(f"gindx shape {gindx.shape} does not match fdepth shape {fdepth.shape}.")
    active = _active_mask(gindx, fdepth)
    summary: Dict[str, Any] = {
        "source": scaffold.source,
        "shape": list(gindx.shape),
        "gindx_nonzero_count": int(np.count_nonzero(gindx > 0)),
        "fdepth_nonzero_count": int(np.count_nonzero(fdepth > 0.0)),
        "active_scaffold_count": int(np.count_nonzero(active)),
        "fdepth_sum": float(np.sum(fdepth[active])) if np.any(active) else 0.0,
        "fdepth_max": float(np.max(fdepth[active])) if np.any(active) else 0.0,
        "tfail_status": "absent_not_inferred",
        "validated_provider_status": "scaffold_only",
    }
    if scaffold.tfail_s is None:
        return summary

    tfail = np.asarray(scaffold.tfail_s, dtype=np.float64)
    if tfail.shape != gindx.shape:
        raise ValueError(f"tfail shape {tfail.shape} does not match gindx shape {gindx.shape}.")
    tfail_active = tfail[active & np.isfinite(tfail)]
    summary.update(
        {
            "tfail_status": "supplied",
            "tfail_finite_count": int(np.count_nonzero(np.isfinite(tfail))),
            "tfail_active_count": int(tfail_active.size),
            "tfail_min": float(np.min(tfail_active)) if tfail_active.size else None,
            "tfail_max": float(np.max(tfail_active)) if tfail_active.size else None,
            "tfail_lte_600_count": int(np.count_nonzero(tfail_active <= 600.0)),
            "validated_provider_status": "schedule_supplied",
        }
    )
    return summary


def attach_supplied_tfail(scaffold: UnsfinScaffold, tfail_s: np.ndarray) -> UnsfinScaffold:
    """Attach a separately supplied original `tfail` artifact to a scaffold."""
    tfail = np.asarray(tfail_s, dtype=np.float64)
    if tfail.shape != scaffold.gindx.shape:
        raise ValueError(f"tfail shape {tfail.shape} does not match scaffold shape {scaffold.gindx.shape}.")
    return UnsfinScaffold(
        gindx=np.asarray(scaffold.gindx, dtype=np.int32),
        fdepth=np.asarray(scaffold.fdepth, dtype=np.float64),
        tfail_s=tfail,
        source=f"{scaffold.source}+supplied_tfail",
    )
