"""Cellwise ASC diff between same-code OPT and baseline-emulation Chamoli windows."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_WINDOW_PATH = Path(__file__).resolve().with_name("_run_chamoli_window.py")
_SPEC = importlib.util.spec_from_file_location("chamoli_window_helpers", _WINDOW_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load {_WINDOW_PATH}")
_WINDOW = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_WINDOW)

FAMILIES = _WINDOW.FAMILIES
find_grid = _WINDOW.find_grid
read_ascii_grid = _WINDOW.read_ascii_grid
align_arrays = _WINDOW.align_arrays
write_json = _WINDOW.write_json


def _finite_stats(left, right) -> dict[str, Any]:
    import numpy as np

    a, b = align_arrays(left, right)
    finite = np.isfinite(a) & np.isfinite(b)
    if not np.any(finite):
        return {
            "status": "empty",
            "n_finite": 0,
            "n_diff": 0,
            "max_abs": None,
            "mean_abs": None,
            "rms": None,
        }
    delta = np.abs(a[finite] - b[finite])
    n_diff = int(np.count_nonzero(delta > 0.0))
    return {
        "status": "identical" if n_diff == 0 else "bit_level_or_numeric",
        "n_finite": int(finite.sum()),
        "n_diff": n_diff,
        "max_abs": float(delta.max()),
        "mean_abs": float(delta.mean()),
        "rms": float(math.sqrt(float(np.mean(delta * delta)))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff OPT vs baseline Chamoli ASC families.")
    parser.add_argument("--opt-dir", required=True)
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoints", default="45,90,135,180")
    args = parser.parse_args()

    opt_dir = Path(args.opt_dir).resolve()
    base_dir = Path(args.baseline_dir).resolve()
    checkpoints = [float(part.strip()) for part in str(args.checkpoints).split(",") if part.strip()]
    frames: list[dict[str, Any]] = []
    nonzero = 0
    missing = 0
    for checkpoint in checkpoints:
        families: list[dict[str, Any]] = []
        for label, stem in FAMILIES:
            left = find_grid(opt_dir, stem, checkpoint)
            right = find_grid(base_dir, stem, checkpoint)
            if left is None or right is None:
                families.append(
                    {
                        "family": label,
                        "status": "missing",
                        "opt": None if left is None else str(left),
                        "baseline": None if right is None else str(right),
                    }
                )
                missing += 1
                continue
            stats = _finite_stats(read_ascii_grid(left), read_ascii_grid(right))
            stats.update({"family": label, "opt": str(left), "baseline": str(right)})
            if stats.get("n_diff", 0):
                nonzero += 1
            families.append(stats)
        frames.append({"checkpoint": checkpoint, "families": families})

    payload = {
        "opt_dir": str(opt_dir),
        "baseline_dir": str(base_dir),
        "checkpoints": checkpoints,
        "nonzero_family_frames": nonzero,
        "missing_family_frames": missing,
        "frames": frames,
        "verdict": (
            "identical"
            if nonzero == 0 and missing == 0
            else ("bit_level_or_numeric" if nonzero else "incomplete")
        ),
    }
    write_json(Path(args.output), payload)
    print(json.dumps({k: payload[k] for k in ("verdict", "nonzero_family_frames", "missing_family_frames")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
