"""Authoritative raster metadata, cache and pixel-identification services.

The workbench used to render a colourized PNG and estimate a value from the
horizontal mouse position.  This module deliberately keeps the source raster
as the authority: GDAL/Rasterio supplies the affine transform, masks, dtype and
raw pixel values.  Display derivatives are optional and are never used for
identification.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

import numpy as np

try:  # Rasterio is part of the Taichi-Flow runtime environment.
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.shutil import copy as rio_copy
    from rasterio.windows import Window
except Exception:  # pragma: no cover - surfaced as a structured API error.
    rasterio = None  # type: ignore[assignment]
    Resampling = None  # type: ignore[assignment,misc]
    rio_copy = None  # type: ignore[assignment]
    Window = None  # type: ignore[assignment,misc]


PROFILE_VERSION = "1"
CACHE_VERSION = "v1"
WINDOW_SIZE = 512
CONTINUOUS_FAMILIES = {
    "dem",
    "slope",
    "thickness",
    "trigger",
    "manning",
    "manningfil",
    "rainfall",
    "rifil",
    "groundwater",
    "infiltration",
}
CATEGORICAL_FAMILIES = {"zones", "zonfil"}
_CACHE_LOCKS: dict[str, Lock] = {}
_CACHE_LOCKS_GUARD = Lock()


class RasterEngineError(RuntimeError):
    """A raster operation failure with a stable public error code."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _require_rasterio() -> None:
    if rasterio is None:
        raise RasterEngineError("rasterio_unavailable", "当前 Python 环境未安装 Rasterio/GDAL。")


@contextmanager
def _raster_env() -> Iterator[None]:
    _require_rasterio()
    # PAM sidecars must never be written beside user inputs while the browser
    # is only inspecting them.
    with rasterio.Env(GDAL_PAM_ENABLED="NO"):
        yield


def data_kind_for_family(family: str | None) -> str:
    normalized = str(family or "").strip().lower()
    return "categorical" if normalized in CATEGORICAL_FAMILIES else "continuous"


def _is_north_up(transform: Any) -> bool:
    return (
        abs(float(transform.b)) <= 1e-12
        and abs(float(transform.d)) <= 1e-12
        and float(transform.a) > 0
        and float(transform.e) < 0
    )


def _transform_payload(transform: Any) -> dict[str, float]:
    return {
        "a": float(transform.a),
        "b": float(transform.b),
        "c": float(transform.c),
        "d": float(transform.d),
        "e": float(transform.e),
        "f": float(transform.f),
    }


def _bounds_payload(bounds: Any) -> dict[str, float]:
    return {
        "xmin": float(bounds.left),
        "ymin": float(bounds.bottom),
        "xmax": float(bounds.right),
        "ymax": float(bounds.top),
    }


def _format_value(value: Any, dtype: str) -> str:
    if value is None:
        return "NoData"
    np_dtype = np.dtype(dtype)
    if np.issubdtype(np_dtype, np.integer):
        return str(int(value))
    if np.issubdtype(np_dtype, np.floating):
        # Nine significant digits round-trip float32; seventeen do the same
        # for float64.  This is more useful than a fixed three-decimal label.
        digits = 9 if np_dtype.itemsize <= 4 else 17
        return format(float(value), f".{digits}g")
    return str(value)


def _json_value(value: Any) -> int | float | str | None:
    if value is None:
        return None
    scalar = np.asarray(value).item()
    if isinstance(scalar, (np.integer, int)):
        return int(scalar)
    if isinstance(scalar, (np.floating, float)):
        return float(scalar)
    return str(scalar)


def _windows(width: int, height: int, size: int = WINDOW_SIZE) -> Iterator[Any]:
    if Window is None:
        return
    for row_off in range(0, height, size):
        for col_off in range(0, width, size):
            yield Window(
                col_off,
                row_off,
                min(size, width - col_off),
                min(size, height - row_off),
            )


def _valid_values(data: Any) -> np.ndarray:
    array = np.asarray(data.data if np.ma.isMaskedArray(data) else data)
    mask = np.ma.getmaskarray(data) if np.ma.isMaskedArray(data) else np.zeros(array.shape, dtype=bool)
    valid = (~mask) & np.isfinite(array)
    return np.asarray(array[valid])


def _scan_statistics(dataset: Any, *, data_kind: str) -> dict[str, Any]:
    minimum: float | None = None
    maximum: float | None = None
    valid_count = 0
    nodata_count = 0
    sum_value = 0.0
    sum_square = 0.0
    unique: dict[str, tuple[Any, int]] = {}
    categorical_overflow = False

    for window in _windows(dataset.width, dataset.height):
        data = dataset.read(1, window=window, masked=True)
        values = _valid_values(data)
        nodata_count += int(data.size - values.size)
        if values.size == 0:
            continue
        values_float = values.astype(np.float64, copy=False)
        current_min = float(np.min(values_float))
        current_max = float(np.max(values_float))
        minimum = current_min if minimum is None else min(minimum, current_min)
        maximum = current_max if maximum is None else max(maximum, current_max)
        valid_count += int(values.size)
        sum_value += float(np.sum(values_float, dtype=np.float64))
        sum_square += float(np.sum(values_float * values_float, dtype=np.float64))
        if data_kind == "categorical" and not categorical_overflow:
            for item in values.tolist():
                key = _format_value(item, dataset.dtypes[0])
                if key in unique:
                    unique[key] = (unique[key][0], unique[key][1] + 1)
                elif len(unique) < 4096:
                    unique[key] = (item, 1)
                else:
                    categorical_overflow = True
                    unique.clear()
                    break

    if valid_count:
        mean = sum_value / valid_count
        variance = max(0.0, (sum_square / valid_count) - (mean * mean))
        standard_deviation = variance ** 0.5
    else:
        mean = None
        standard_deviation = None

    result: dict[str, Any] = {
        "valid_count": valid_count,
        "nodata_count": nodata_count,
        "min": minimum,
        "max": maximum,
        "mean": mean,
        "stddev": standard_deviation,
    }
    if data_kind == "categorical":
        result["categorical_overflow"] = categorical_overflow
        result["unique_values"] = [
            {"value": _json_value(value), "value_text": key, "count": count}
            for key, (value, count) in sorted(unique.items(), key=lambda item: item[0])
        ] if not categorical_overflow else []

    if minimum is None or maximum is None:
        result["histogram"] = {"edges": [], "counts": []}
        return result

    if minimum == maximum:
        result["histogram"] = {"edges": [minimum, maximum], "counts": [valid_count]}
        return result

    edges = np.linspace(minimum, maximum, 257, dtype=np.float64)
    counts = np.zeros(256, dtype=np.int64)
    for window in _windows(dataset.width, dataset.height):
        values = _valid_values(dataset.read(1, window=window, masked=True)).astype(np.float64, copy=False)
        if values.size:
            counts += np.histogram(values, bins=edges)[0]
    result["histogram"] = {"edges": edges.tolist(), "counts": counts.tolist()}
    return result


def _profile_from_dataset(dataset: Any, *, sha256: str, family: str) -> dict[str, Any]:
    data_kind = data_kind_for_family(family)
    transform = dataset.transform
    north_up = _is_north_up(transform)
    single_band = int(dataset.count) == 1
    supported = single_band and north_up and dataset.width > 0 and dataset.height > 0
    unsupported_reason = None
    if not single_band:
        unsupported_reason = "仅支持单波段栅格。"
    elif not north_up:
        unsupported_reason = "旋转或剪切栅格暂不支持正式浏览。"

    statistics = _scan_statistics(dataset, data_kind=data_kind) if single_band else {}
    nodata = dataset.nodata
    tags = {str(key).lower(): value for key, value in dataset.tags(1).items()}
    unit = tags.get("unit") or tags.get("units") or tags.get("unittype")
    crs = dataset.crs.to_string() if dataset.crs else None
    return {
        "profile_version": PROFILE_VERSION,
        "status": "ready" if supported else "unsupported",
        "unsupported_reason": unsupported_reason,
        "driver": str(dataset.driver),
        "family": family,
        "data_kind": data_kind,
        "width": int(dataset.width),
        "height": int(dataset.height),
        "band_count": int(dataset.count),
        "dtype": str(dataset.dtypes[0]) if dataset.dtypes else None,
        "nodata": _json_value(nodata),
        "transform": _transform_payload(transform),
        "bounds": _bounds_payload(dataset.bounds),
        "crs": crs,
        "unit": str(unit) if unit is not None else None,
        "north_up": north_up,
        "statistics": statistics,
        "capabilities": {
            "display": supported,
            "identify": supported,
            "statistics": single_band,
        },
        "source_sha256": sha256,
    }


def read_raster_profile(path: Path, *, sha256: str, family: str) -> dict[str, Any]:
    with _raster_env():
        try:
            with rasterio.open(path) as dataset:
                return _profile_from_dataset(dataset, sha256=sha256, family=family)
        except RasterEngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RasterEngineError("raster_profile_failed", f"无法读取栅格元数据：{exc}") from exc


def cache_path(cache_root: Path, sha256: str, data_kind: str) -> Path:
    return cache_root / "raster-cache" / CACHE_VERSION / sha256 / data_kind / "source.cog.tif"


def _cache_lock(key: str) -> Lock:
    with _CACHE_LOCKS_GUARD:
        return _CACHE_LOCKS.setdefault(key, Lock())


def build_lossless_cog(source_path: Path, destination: Path, *, data_kind: str) -> Path:
    """Create a lossless, tiled COG without altering the source file."""
    _require_rasterio()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    if rio_copy is None:
        raise RasterEngineError("cog_unavailable", "当前 GDAL/Rasterio 不支持 COG 写入。")

    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    overview_resampling = "nearest" if data_kind == "categorical" else "average"
    try:
        with _raster_env():
            rio_copy(
                str(source_path),
                str(temporary),
                driver="COG",
                compress="DEFLATE",
                predictor=2,
                blocksize=256,
                overview_resampling=overview_resampling,
                BIGTIFF="IF_SAFER",
            )
        temporary.replace(destination)
    except Exception as exc:  # noqa: BLE001
        temporary.unlink(missing_ok=True)
        raise RasterEngineError("cog_build_failed", f"无法生成无损栅格缓存：{exc}") from exc
    return destination


def prepare_raster(path: Path, cache_root: Path, *, sha256: str, family: str) -> tuple[dict[str, Any], Path | None]:
    data_kind = data_kind_for_family(family)
    profile = read_raster_profile(path, sha256=sha256, family=family)
    if profile["status"] != "ready":
        return profile, None
    destination = cache_path(cache_root, sha256, data_kind)
    lock = _cache_lock(str(destination))
    with lock:
        build_lossless_cog(path, destination, data_kind=data_kind)
    profile = dict(profile)
    profile["cache"] = {
        "format": "COG",
        "path": str(destination),
        "data_kind": data_kind,
    }
    return profile, destination


def _cell_value(dataset: Any, row: int, column: int) -> tuple[Any, bool]:
    data = dataset.read(1, window=Window(column, row, 1, 1), masked=True)
    if data.size == 0 or bool(np.ma.getmaskarray(data).reshape(-1)[0]):
        return None, True
    value = np.asarray(data).reshape(-1)[0]
    if not np.isfinite(value):
        return None, True
    return value, False


def identify_raster(
    path: Path,
    *,
    sha256: str,
    family: str,
    x: float,
    y: float,
    neighborhood_size: int = 3,
) -> dict[str, Any]:
    with _raster_env():
        try:
            with rasterio.open(path) as dataset:
                profile = _profile_from_dataset(dataset, sha256=sha256, family=family)
                base = {
                    "asset_id": None,
                    "source_sha256": sha256,
                    "family": family,
                    "status": "unsupported" if profile["status"] != "ready" else "outside",
                    "coordinate": {"x": float(x), "y": float(y)},
                    "sampled_from": "source_base",
                    "dtype": profile.get("dtype"),
                    "nodata": profile.get("nodata"),
                    "unit": profile.get("unit"),
                    "row": None,
                    "column": None,
                    "row_one_based": None,
                    "column_one_based": None,
                    "cell_center": None,
                    "raw": {"value": None, "value_text": "NoData", "is_nodata": True},
                }
                if profile["status"] != "ready":
                    base["message"] = profile.get("unsupported_reason")
                    return base

                row, column = dataset.index(float(x), float(y))
                if row < 0 or column < 0 or row >= dataset.height or column >= dataset.width:
                    return base

                value, is_nodata = _cell_value(dataset, row, column)
                center_x, center_y = dataset.xy(row, column, offset="center")
                base.update(
                    {
                        "status": "nodata" if is_nodata else "value",
                        "row": int(row),
                        "column": int(column),
                        "row_one_based": int(row + 1),
                        "column_one_based": int(column + 1),
                        "cell_center": {"x": float(center_x), "y": float(center_y)},
                        "raw": {
                            "value": _json_value(value),
                            "value_text": _format_value(value, profile["dtype"]) if not is_nodata else "NoData",
                            "is_nodata": is_nodata,
                        },
                    }
                )
                if neighborhood_size in {3, 5}:
                    radius = neighborhood_size // 2
                    values: list[list[Any]] = []
                    value_text: list[list[str]] = []
                    for neighbor_row in range(row - radius, row + radius + 1):
                        row_values: list[Any] = []
                        row_text: list[str] = []
                        for neighbor_column in range(column - radius, column + radius + 1):
                            if (
                                neighbor_row < 0
                                or neighbor_column < 0
                                or neighbor_row >= dataset.height
                                or neighbor_column >= dataset.width
                            ):
                                row_values.append(None)
                                row_text.append("Outside")
                                continue
                            neighbor_value, neighbor_nodata = _cell_value(dataset, neighbor_row, neighbor_column)
                            row_values.append(None if neighbor_nodata else _json_value(neighbor_value))
                            row_text.append(
                                "NoData" if neighbor_nodata else _format_value(neighbor_value, profile["dtype"])
                            )
                        values.append(row_values)
                        value_text.append(row_text)
                    base["neighborhood"] = {
                        "size": neighborhood_size,
                        "center": {"row": int(radius), "column": int(radius)},
                        "values": values,
                        "value_text": value_text,
                    }
                return base
        except RasterEngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RasterEngineError("raster_identify_failed", f"无法读取栅格像元：{exc}") from exc
