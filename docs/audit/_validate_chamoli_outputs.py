"""Strict, streaming validation for Chamoli EDDA-compatible ASCII outputs.

This helper is intentionally an audit-only tool.  It never runs a solver and
never mutates a simulation directory.  In particular, it rejects a shape or
NODATA-mask mismatch rather than applying the historical audit helper's
transpose/cropping fallback.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np


TIME_GRID_RE = re.compile(r"^(?P<family>.+Taichi)_(?P<time>\d+(?:\.\d+)?)\.txt$")
REQUIRED_FAMILIES = (
    "Deposit_depth_Taichi",
    "DFdepthTaichi",
    "Erosion_depth_Taichi",
    "faildphTaichi",
    "FFdepthTaichi",
    "Flow_depth_Taichi",
    "Flow_velocity_Taichi",
    "LS_ScarTaichi",
    "Max_flow_depth_Taichi",
    "Max_flow_velocity_Taichi",
    "MaxDFdepthTaichi",
    "MaxFFdepthTaichi",
    "MaxSFdepthTaichi",
    "SFdepthTaichi",
    "Total_depth_Taichi",
    "Volumetric_sediment_conceTaichi",
)
HEADER_KEYS = ("ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_header(path: Path) -> dict[str, float]:
    header: dict[str, float] = {}
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for _ in range(6):
            line = handle.readline()
            if not line:
                raise ValueError(f"{path}: missing ESRI ASCII header line")
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"{path}: invalid ESRI ASCII header: {line!r}")
            key = parts[0].lower()
            if key not in HEADER_KEYS:
                raise ValueError(f"{path}: unexpected ESRI ASCII header key {parts[0]!r}")
            header[key] = float(parts[1])
    missing = [key for key in HEADER_KEYS if key not in header]
    if missing:
        raise ValueError(f"{path}: incomplete ESRI ASCII header; missing {missing}")
    return header


def _read_grid(path: Path) -> tuple[dict[str, float], np.ndarray]:
    header = _read_header(path)
    values = np.loadtxt(path, dtype=np.float64, skiprows=6)
    values = np.atleast_2d(values)
    expected_shape = (int(header["nrows"]), int(header["ncols"]))
    if values.shape != expected_shape:
        raise ValueError(
            f"{path}: payload shape {values.shape} does not match header {expected_shape}"
        )
    return header, values


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return None


def _compare_grids(left: Path, right: Path) -> dict[str, Any]:
    row: dict[str, Any] = {
        "left": str(left),
        "right": str(right),
        "left_sha256": _sha256(left),
        "right_sha256": _sha256(right),
    }
    try:
        left_header, left_grid = _read_grid(left)
        right_header, right_grid = _read_grid(right)
    except (OSError, UnicodeError, ValueError) as exc:
        row.update({"status": "parse_error", "error": str(exc)})
        return row

    header_mismatches = {
        key: {"left": left_header[key], "right": right_header[key]}
        for key in HEADER_KEYS
        if left_header[key] != right_header[key]
    }
    layout_mismatches = {
        key: header_mismatches[key]
        for key in ("ncols", "nrows", "nodata_value")
        if key in header_mismatches
    }
    spatial_metadata_mismatches = {
        key: header_mismatches[key]
        for key in ("xllcorner", "yllcorner", "cellsize")
        if key in header_mismatches
    }
    row.update(
        {
            "header": left_header,
            "shape": list(left_grid.shape),
            "header_mismatches": header_mismatches,
            "layout_mismatches": layout_mismatches,
            "spatial_metadata_mismatches": spatial_metadata_mismatches,
            "left_nonfinite_count": int(np.count_nonzero(~np.isfinite(left_grid))),
            "right_nonfinite_count": int(np.count_nonzero(~np.isfinite(right_grid))),
        }
    )
    # A changed xll/yll/cellsize header is material evidence for a geospatial
    # export audit, but it is not a numerical-layout mismatch.  We continue to
    # compare payloads only when row/column count and NODATA semantics match;
    # transpose or crop is never attempted.
    if layout_mismatches or left_grid.shape != right_grid.shape:
        row["status"] = "layout_mismatch"
        return row

    nodata = left_header["nodata_value"]
    left_mask = left_grid == nodata
    right_mask = right_grid == nodata
    mask_mismatch_count = int(np.count_nonzero(left_mask ^ right_mask))
    row["mask_mismatch_count"] = mask_mismatch_count
    if mask_mismatch_count:
        row["status"] = "mask_mismatch"
        return row

    valid = ~left_mask
    if not np.all(np.isfinite(left_grid[valid])) or not np.all(np.isfinite(right_grid[valid])):
        row["status"] = "nonfinite"
        return row

    left_values = left_grid[valid]
    right_values = right_grid[valid]
    difference = left_values - right_values
    abs_difference = np.abs(difference)
    mismatch_count = int(np.count_nonzero(left_values != right_values))
    row.update(
        {
            "valid_cell_count": int(left_values.size),
            "exact_mismatch_count": mismatch_count,
            "mae": _number(float(np.mean(abs_difference))) if left_values.size else 0.0,
            "rmse": _number(float(np.sqrt(np.mean(np.square(difference))))) if left_values.size else 0.0,
            "max_abs_error": _number(float(np.max(abs_difference))) if left_values.size else 0.0,
            "status": (
                "identical_with_spatial_metadata_mismatch"
                if mismatch_count == 0 and spatial_metadata_mismatches
                else "identical"
                if mismatch_count == 0
                else "residual_with_spatial_metadata_mismatch"
                if spatial_metadata_mismatches
                else "residual"
            ),
        }
    )
    return row


def _time_key(value: float) -> str:
    return f"{value:.1f}"


def _collect_time_grids(directory: Path) -> dict[tuple[str, str], Path]:
    grids: dict[tuple[str, str], Path] = {}
    for path in directory.glob("*Taichi_*.txt"):
        match = TIME_GRID_RE.match(path.name)
        if not match:
            continue
        key = (match.group("family"), _time_key(float(match.group("time"))))
        if key in grids:
            raise ValueError(f"duplicate time grid for {key}: {grids[key]} and {path}")
        grids[key] = path
    return grids


def _inventory(
    grids: dict[tuple[str, str], Path], *, expected_t_end: float, output_interval: float
) -> dict[str, Any]:
    expected_times = {_time_key(output_interval * step) for step in range(1, int(expected_t_end / output_interval) + 1)}
    actual_families = {family for family, _ in grids}
    actual_times = {time for _, time in grids}
    missing_families = sorted(set(REQUIRED_FAMILIES) - actual_families)
    unexpected_families = sorted(actual_families - set(REQUIRED_FAMILIES))
    missing_pairs = [
        {"family": family, "time_s": time}
        for family in REQUIRED_FAMILIES
        for time in sorted(expected_times, key=float)
        if (family, time) not in grids
    ]
    unexpected_pairs = [
        {"family": family, "time_s": time}
        for family, time in sorted(grids, key=lambda item: (item[0], float(item[1])))
        if family not in REQUIRED_FAMILIES or time not in expected_times
    ]
    expected_count = len(REQUIRED_FAMILIES) * len(expected_times)
    return {
        "status": "pass"
        if not (missing_families or unexpected_families or missing_pairs or unexpected_pairs)
        else "fail",
        "expected_grid_count": expected_count,
        "actual_grid_count": len(grids),
        "expected_families": list(REQUIRED_FAMILIES),
        "actual_families": sorted(actual_families),
        "expected_times_s": sorted(expected_times, key=float),
        "actual_times_s": sorted(actual_times, key=float),
        "missing_families": missing_families,
        "unexpected_families": unexpected_families,
        "missing_pairs": missing_pairs,
        "unexpected_pairs": unexpected_pairs,
    }


def _records_for_inventory(grids: dict[tuple[str, str], Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for (family, time), path in sorted(grids.items(), key=lambda item: (item[0][0], float(item[0][1]))):
        try:
            header, grid = _read_grid(path)
            nodata = header["nodata_value"]
            records.append(
                {
                    "family": family,
                    "time_s": float(time),
                    "path": str(path),
                    "sha256": _sha256(path),
                    "status": "valid"
                    if int(np.count_nonzero(~np.isfinite(grid[grid != nodata]))) == 0
                    else "nonfinite",
                    "shape": list(grid.shape),
                    "header": header,
                    "valid_cell_count": int(np.count_nonzero(grid != nodata)),
                    "nonfinite_count": int(np.count_nonzero(~np.isfinite(grid[grid != nodata]))),
                }
            )
        except (OSError, UnicodeError, ValueError) as exc:
            records.append(
                {
                    "family": family,
                    "time_s": float(time),
                    "path": str(path),
                    "status": "parse_error",
                    "error": str(exc),
                }
            )
    return records


def _compare_baseline(
    actual_grids: dict[tuple[str, str], Path], baseline_dir: Path, checkpoints: list[float]
) -> list[dict[str, Any]]:
    baseline_grids = _collect_time_grids(baseline_dir)
    records: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        time = _time_key(checkpoint)
        for family in REQUIRED_FAMILIES:
            actual = actual_grids.get((family, time))
            baseline = baseline_grids.get((family, time))
            record: dict[str, Any] = {"family": family, "time_s": checkpoint}
            if actual is None or baseline is None:
                record.update(
                    {
                        "status": "missing",
                        "actual": str(actual) if actual else None,
                        "baseline": str(baseline) if baseline else None,
                    }
                )
            else:
                record.update(_compare_grids(actual, baseline))
            records.append(record)
    return records


def _write_csv(path: Path, groups: dict[str, list[dict[str, Any]]]) -> None:
    rows: list[dict[str, Any]] = []
    for group, records in groups.items():
        for record in records:
            flat = {key: value for key, value in record.items() if not isinstance(value, (dict, list))}
            flat["group"] = group
            rows.append(flat)
    fields = sorted({key for row in rows for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual-dir", required=True, type=Path)
    parser.add_argument("--expected-t-end", required=True, type=float)
    parser.add_argument("--output-interval", required=True, type=float)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--csv-out", required=True, type=Path)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--baseline-checkpoints", default="45,90,135,180")
    args = parser.parse_args()

    actual_dir = args.actual_dir.resolve()
    if not actual_dir.is_dir():
        raise SystemExit(f"actual directory does not exist: {actual_dir}")
    try:
        actual_grids = _collect_time_grids(actual_dir)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    inventory = _inventory(
        actual_grids,
        expected_t_end=float(args.expected_t_end),
        output_interval=float(args.output_interval),
    )
    integrity = _records_for_inventory(actual_grids)
    baseline: list[dict[str, Any]] = []
    if args.baseline_dir:
        baseline = _compare_baseline(
            actual_grids,
            args.baseline_dir.resolve(),
            [float(value) for value in args.baseline_checkpoints.split(",") if value.strip()],
        )

    integrity_ok = all(record.get("status") == "valid" for record in integrity)
    baseline_ok = not baseline or all(
        record.get("status") in {"identical", "identical_with_spatial_metadata_mismatch"}
        for record in baseline
    )
    payload = {
        "schema_version": 1,
        "actual_dir": str(actual_dir),
        "inventory": inventory,
        "integrity": integrity,
        "optimization_baseline": {
            "directory": str(args.baseline_dir.resolve()) if args.baseline_dir else None,
            "records": baseline,
            "status": "pass" if baseline_ok else "fail",
        },
        "verdict": "pass" if inventory["status"] == "pass" and integrity_ok and baseline_ok else "fail",
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(args.csv_out, {"integrity": integrity, "optimization_baseline": baseline})
    print(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "actual_grid_count": inventory["actual_grid_count"],
                "expected_grid_count": inventory["expected_grid_count"],
                "integrity_ok": integrity_ok,
                "baseline_ok": baseline_ok,
                "json_out": str(args.json_out),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
