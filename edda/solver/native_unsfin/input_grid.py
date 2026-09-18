"""Strict, shared input boundary for native UNSFIN active-order field packs.

The legacy config retains its original path strings. Only the file-system
boundary translates separators. Scientific inputs are never resampled, filled,
rounded to zone IDs, or paired by active-cell count alone.
"""
from __future__ import annotations

import math
import os
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping


def resolve_native_input_path(case_dir: Path, raw: str) -> Path:
    token = str(raw).strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1]
    if not token or "\x00" in token:
        raise ValueError("Empty or invalid native input path")
    windows = PureWindowsPath(token)
    if token.startswith(("\\\\", "//")):
        raise ValueError(f"UNC/network native input path requires explicit local remapping: {raw!r}")
    if windows.drive:
        if not windows.is_absolute():
            raise ValueError(f"Drive-relative native input path is ambiguous: {raw!r}")
        if os.name != "nt":
            raise ValueError(f"Foreign Windows drive requires explicit local remapping: {raw!r}")
    elif token.startswith("\\"):
        raise ValueError(f"Root-relative Windows input path is ambiguous: {raw!r}")
    path = Path(token.replace("\\", "/"))
    if not path.is_absolute():
        path = Path(case_dir) / path
    if not path.is_file():
        raise FileNotFoundError(f"Native input file not found: {path}")
    return path


def _geometry(header: Mapping[str, float], path: Path) -> tuple[int, int, float, float, float]:
    for key in ("nrows", "ncols", "cellsize", "nodata_value"):
        if key not in header or not math.isfinite(header[key]):
            raise ValueError(f"Missing/nonfinite ASCII header {key}: {path}")
    nrows, ncols = header["nrows"], header["ncols"]
    if nrows <= 0 or ncols <= 0 or not nrows.is_integer() or not ncols.is_integer():
        raise ValueError(f"Invalid ASCII grid dimensions: {path}")
    size = header["cellsize"]
    if size <= 0:
        raise ValueError(f"Nonpositive ASCII cell size: {path}")
    origin = []
    for axis in ("x", "y"):
        corner, center = axis + "llcorner", axis + "llcenter"
        if (corner in header) == (center in header):
            raise ValueError(f"Require exactly one {axis} origin: {path}")
        value = header[corner] if corner in header else header[center] - size / 2.0
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite ASCII origin: {path}")
        origin.append(value)
    return int(nrows), int(ncols), *origin, size


def _same_geometry(reference: tuple[int, int, float, float, float], candidate: tuple[int, int, float, float, float]) -> bool:
    """Compare normalized grid geometry without turning binary round-off into a remap."""
    if reference[:2] != candidate[:2]:
        return False
    # Grid spacing sets a strict, scale-aware absolute bound.  Eight ULPs
    # covers center-to-corner normalization such as 0.15 - 0.1 / 2 while
    # keeping any meaningful spatial displacement fail-closed.
    scale = min(reference[4], candidate[4])
    for expected, actual in zip(reference[2:], candidate[2:]):
        tolerance = max(scale * 1.0e-12, 8.0 * math.ulp(expected), 8.0 * math.ulp(actual))
        if not math.isclose(expected, actual, rel_tol=0.0, abs_tol=tolerance):
            return False
    return True


def read_ascii_active_values(path: Path, *, integer: bool = False) -> tuple[list[float], list[tuple[int, int]], dict[str, Any]]:
    """Read finite rectangular ESRI ASCII; return Fortran's one-based row order."""
    path = Path(path)
    with path.open(encoding="utf-8-sig", errors="strict") as handle:
        header: dict[str, float] = {}
        for _ in range(6):
            parts = handle.readline().split()
            if len(parts) != 2 or parts[0].lower() in header:
                raise ValueError(f"Malformed/duplicate ASCII header: {path}")
            try:
                header[parts[0].lower()] = float(parts[1])
            except ValueError as exc:
                raise ValueError(f"Invalid ASCII header value: {path}") from exc
        nrows, ncols, *_ = _geometry(header, path)
        nodata = header["nodata_value"]
        values: list[float] = []
        mapping: list[tuple[int, int]] = []
        row = 0
        for line in handle:
            if not line.strip():
                continue
            row += 1
            parts = line.split()
            if row > nrows or len(parts) != ncols:
                raise ValueError(f"ASCII payload shape does not match header at row {row}: {path}")
            for col, raw in enumerate(parts, 1):
                value = float(raw)
                if value == nodata:
                    continue
                if not math.isfinite(value):
                    raise ValueError(f"Nonfinite active value at ({row},{col}): {path}")
                if integer and not value.is_integer():
                    raise ValueError(f"Nonintegral zone ID at ({row},{col}): {path}")
                values.append(value)
                mapping.append((row, col))
        if row != nrows:
            raise ValueError(f"ASCII row count {row} does not match {nrows}: {path}")
    return values, mapping, header


def load_aligned_active_inputs(case_dir: Path, paths: Mapping[str, str]):
    """Fail closed unless geometry AND ordered active coordinates agree."""
    grids = {}
    reference_geometry = reference_mapping = None
    for family in ("slope", "zone", "ltstar"):
        path = resolve_native_input_path(case_dir, paths[family])
        values, mapping, header = read_ascii_active_values(path, integer=family == "zone")
        geometry = _geometry(header, path)
        if reference_mapping is None:
            reference_geometry, reference_mapping = geometry, mapping
        else:
            if not _same_geometry(reference_geometry, geometry):
                raise ValueError(f"Grid geometry mismatch: slope vs {family}: {path}")
            if mapping != reference_mapping:
                raise ValueError(f"Active-cell mapping mismatch: slope vs {family}: {path}")
        grids[family] = (values, mapping, header)
    return grids
