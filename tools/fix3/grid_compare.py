"""Fail-closed grid comparison for FIX3 residual acceptance.

This intentionally does not reuse legacy residual helpers that transpose,
crop, or truncate input grids.  A comparison is meaningful only when both
files describe the same canonical grid and NoData domain.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np


GRID_PARSE_CACHE_SCHEMA = "fix3-grid-parse-cache-v1"


class GridComparisonError(ValueError):
    """Raised when a grid pair cannot be compared without changing its meaning."""


@dataclass(frozen=True)
class AsciiGrid:
    path: Path
    data: np.ndarray
    ncols: int
    nrows: int
    x_origin_key: str
    x_origin: float
    y_origin_key: str
    y_origin: float
    cellsize: float
    nodata: float
    sha256: str

    @property
    def cell_area(self) -> float:
        return self.cellsize * self.cellsize

    @property
    def georeference(self) -> dict[str, float | str]:
        return {
            "x_origin_key": self.x_origin_key,
            "x_origin": self.x_origin,
            "y_origin_key": self.y_origin_key,
            "y_origin": self.y_origin,
            "cellsize": self.cellsize,
            "row_order": "north_to_south",
        }


def _parse_header_value(path: Path, line_number: int, line: str) -> tuple[str, str]:
    fields = line.split()
    if len(fields) != 2:
        raise GridComparisonError(
            f"{path}: header line {line_number} must contain exactly a key and a value."
        )
    return fields[0].lower(), fields[1]


def _float(path: Path, name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise GridComparisonError(f"{path}: {name} is not numeric: {value!r}") from exc
    if not np.isfinite(parsed):
        raise GridComparisonError(f"{path}: {name} must be finite.")
    return parsed


def _parse_cache_file(cache_dir: Path, content_sha256: str) -> Path:
    return cache_dir / f"{GRID_PARSE_CACHE_SCHEMA}-{content_sha256}.npz"


def _load_parse_cache(cache_dir: Path, source: Path, content_sha256: str) -> AsciiGrid | None:
    cache_path = _parse_cache_file(cache_dir, content_sha256)
    if not cache_path.is_file():
        return None
    try:
        with np.load(cache_path, allow_pickle=False) as payload:
            if str(payload["schema_version"].item()) != GRID_PARSE_CACHE_SCHEMA:
                return None
            data = np.asarray(payload["data"], dtype=np.float64)
            data.setflags(write=False)
            return AsciiGrid(
                path=source,
                data=data,
                ncols=int(payload["ncols"].item()),
                nrows=int(payload["nrows"].item()),
                x_origin_key=str(payload["x_origin_key"].item()),
                x_origin=float(payload["x_origin"].item()),
                y_origin_key=str(payload["y_origin_key"].item()),
                y_origin=float(payload["y_origin"].item()),
                cellsize=float(payload["cellsize"].item()),
                nodata=float(payload["nodata"].item()),
                sha256=content_sha256,
            )
    except (KeyError, OSError, ValueError):
        # A partial cache must never become a comparison input. Re-parse the
        # authoritative text and replace it below instead.
        return None


def _store_parse_cache(cache_dir: Path, grid: AsciiGrid) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _parse_cache_file(cache_dir, grid.sha256)
    temporary = target.with_name(f"{target.stem}.tmp.npz")
    try:
        np.savez_compressed(
            temporary,
            schema_version=np.asarray(GRID_PARSE_CACHE_SCHEMA),
            data=grid.data,
            ncols=np.asarray(grid.ncols),
            nrows=np.asarray(grid.nrows),
            x_origin_key=np.asarray(grid.x_origin_key),
            x_origin=np.asarray(grid.x_origin),
            y_origin_key=np.asarray(grid.y_origin_key),
            y_origin=np.asarray(grid.y_origin),
            cellsize=np.asarray(grid.cellsize),
            nodata=np.asarray(grid.nodata),
        )
        temporary.replace(target)
    except OSError:
        # Caching is an optimization only; a permissions or transient I/O
        # problem cannot make a correct direct comparison fail or pass.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def read_ascii_grid_strict(path: str | Path, *, cache_dir: str | Path | None = None) -> AsciiGrid:
    """Read an ESRI ASCII grid without shape repair, crop, or transpose.

    When ``cache_dir`` is supplied, parsed arrays are keyed by raw content
    hash and this reader's schema version. Statistics changes can therefore
    reuse a parse while source bytes or reader semantics cannot.
    """
    source = Path(path)
    raw = source.read_bytes()
    content_sha256 = sha256(raw).hexdigest()
    cache_root = Path(cache_dir) if cache_dir is not None else None
    if cache_root is not None:
        cached = _load_parse_cache(cache_root, source, content_sha256)
        if cached is not None:
            return cached
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GridComparisonError(f"{source}: grid must be UTF-8 text.") from exc
    lines = text.splitlines()
    if len(lines) < 6:
        raise GridComparisonError(f"{source}: expected six ESRI ASCII header lines.")

    header: dict[str, str] = {}
    for line_number, line in enumerate(lines[:6], start=1):
        key, value = _parse_header_value(source, line_number, line)
        if key in header:
            raise GridComparisonError(f"{source}: duplicate header key {key!r}.")
        header[key] = value

    required = {"ncols", "nrows", "cellsize", "nodata_value"}
    missing = sorted(required - set(header))
    if missing:
        raise GridComparisonError(f"{source}: missing required header key(s): {', '.join(missing)}.")
    x_keys = [key for key in ("xllcorner", "xllcenter") if key in header]
    y_keys = [key for key in ("yllcorner", "yllcenter") if key in header]
    if len(x_keys) != 1 or len(y_keys) != 1:
        raise GridComparisonError(f"{source}: header must contain exactly one xll* and one yll* origin.")

    try:
        ncols = int(header["ncols"])
        nrows = int(header["nrows"])
    except ValueError as exc:
        raise GridComparisonError(f"{source}: ncols and nrows must be integers.") from exc
    if ncols <= 0 or nrows <= 0:
        raise GridComparisonError(f"{source}: ncols and nrows must be positive.")
    # Prevent inputs such as `2.0`, silently accepted by float-based readers.
    if header["ncols"] != str(ncols) or header["nrows"] != str(nrows):
        raise GridComparisonError(f"{source}: ncols and nrows must use canonical integer syntax.")

    x_key, y_key = x_keys[0], y_keys[0]
    cellsize = _float(source, "cellsize", header["cellsize"])
    if cellsize <= 0.0:
        raise GridComparisonError(f"{source}: cellsize must be positive.")
    # This is intentionally vectorized: a formal Chamoli validation reads
    # thousands of full grids.  ``fromstring`` is not allowed to repair a
    # malformed file: token count, parsed count, finiteness, and exact shape
    # are each checked below before it can become a comparison input.
    body = "\n".join(lines[6:])
    token_count = len(re.findall(r"\S+", body))
    values = np.fromstring(body, sep=" ", dtype=np.float64)
    expected_count = ncols * nrows
    if token_count != expected_count or values.size != expected_count:
        raise GridComparisonError(
            f"{source}: expected exactly {expected_count} finite numeric raster values, "
            f"found {token_count} token(s) and {values.size} parsed value(s)."
        )
    if not np.all(np.isfinite(values)):
        raise GridComparisonError(f"{source}: grid values must be finite.")
    data = values.reshape((nrows, ncols))
    grid = AsciiGrid(
        path=source,
        data=data,
        ncols=ncols,
        nrows=nrows,
        x_origin_key=x_key,
        x_origin=_float(source, x_key, header[x_key]),
        y_origin_key=y_key,
        y_origin=_float(source, y_key, header[y_key]),
        cellsize=cellsize,
        nodata=_float(source, "nodata_value", header["nodata_value"]),
        sha256=content_sha256,
    )
    if cache_root is not None:
        _store_parse_cache(cache_root, grid)
    return grid


def _ensure_same_grid(candidate: AsciiGrid, reference: AsciiGrid) -> None:
    if (candidate.nrows, candidate.ncols) != (reference.nrows, reference.ncols):
        raise GridComparisonError(
            "shape mismatch: "
            f"candidate {(candidate.nrows, candidate.ncols)} != "
            f"reference {(reference.nrows, reference.ncols)}."
        )
    for name in ("x_origin_key", "x_origin", "y_origin_key", "y_origin", "cellsize", "nodata"):
        candidate_value = getattr(candidate, name)
        reference_value = getattr(reference, name)
        if candidate_value != reference_value:
            raise GridComparisonError(
                f"{name} mismatch: candidate={candidate_value!r}, reference={reference_value!r}."
            )
    candidate_nodata = candidate.data == candidate.nodata
    reference_nodata = reference.data == reference.nodata
    if not np.array_equal(candidate_nodata, reference_nodata):
        raise GridComparisonError("NoData mask mismatch; comparison would change the canonical DEM domain.")
    valid = ~candidate_nodata
    if not np.all(np.isfinite(candidate.data[valid])) or not np.all(np.isfinite(reference.data[valid])):
        raise GridComparisonError("valid-domain values must be finite.")
    if not np.any(valid):
        raise GridComparisonError("canonical DEM valid domain is empty.")


def _nse(candidate: np.ndarray, reference: np.ndarray) -> float | None:
    denominator = float(np.sum((reference - float(np.mean(reference))) ** 2))
    if denominator == 0.0:
        return None
    return float(1.0 - np.sum((candidate - reference) ** 2) / denominator)


def _ratio(candidate: np.ndarray, reference: np.ndarray, *, metric: str, cell_area: float) -> tuple[float | None, str]:
    if metric == "erosion_depth":
        numerator = float(np.sum(candidate * cell_area))
        denominator = float(np.sum(reference * cell_area))
    elif metric == "flow_velocity":
        numerator = float(np.sum(np.abs(candidate) * cell_area))
        denominator = float(np.sum(np.abs(reference) * cell_area))
    else:
        raise GridComparisonError(f"unsupported metric {metric!r}; use erosion_depth or flow_velocity.")
    if denominator == 0.0:
        return None, "not_determinable_zero_reference"
    return numerator / denominator, "determined"


def compare_ascii_grids(
    candidate_path: str | Path,
    reference_path: str | Path,
    *,
    metric: str,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Compare one exact grid pair and return provenance-bound metrics."""
    candidate = read_ascii_grid_strict(candidate_path, cache_dir=cache_dir)
    reference = read_ascii_grid_strict(reference_path, cache_dir=cache_dir)
    _ensure_same_grid(candidate, reference)
    valid = candidate.data != candidate.nodata
    candidate_values = candidate.data[valid]
    reference_values = reference.data[valid]
    ratio, ratio_status = _ratio(
        candidate_values,
        reference_values,
        metric=metric,
        cell_area=candidate.cell_area,
    )
    return {
        "metric": metric,
        "grid_parse_cache_schema": GRID_PARSE_CACHE_SCHEMA if cache_dir is not None else None,
        "candidate": {"path": str(candidate.path), "sha256": candidate.sha256},
        "reference": {"path": str(reference.path), "sha256": reference.sha256},
        "shape": [candidate.nrows, candidate.ncols],
        "georeference": candidate.georeference,
        "nodata": candidate.nodata,
        "valid_cell_count": int(np.count_nonzero(valid)),
        "nse": _nse(candidate_values, reference_values),
        "rmse": float(np.sqrt(np.mean((candidate_values - reference_values) ** 2))),
        "ratio": ratio,
        "ratio_status": ratio_status,
    }


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict FIX3 ESRI ASCII comparison")
    parser.add_argument("candidate")
    parser.add_argument("reference")
    parser.add_argument("--metric", choices=("erosion_depth", "flow_velocity"), required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(json.dumps(compare_ascii_grids(args.candidate, args.reference, metric=args.metric), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
