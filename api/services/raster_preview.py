"""Generate PNG previews for uploaded raster inputs (.asc / .tif)."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Tuple

import numpy as np

from edda.io.spatial_input_loader import SpatialInputLoader

PreviewMode = Literal["downsample", "full"]

DOWNSAMPLE_MAX = 512
FULL_CAP = 4096


@dataclass
class RasterPreviewResult:
    png_bytes: bytes
    width: int
    height: int
    bounds: Tuple[float, float, float, float]
    value_min: float
    value_max: float
    nodata: float | None
    capped: bool
    mode: str


def _png_rgba(rgba: np.ndarray) -> bytes:
    """Encode HxWx4 uint8 array as PNG without Pillow."""
    height, width, channels = rgba.shape
    if channels != 4:
        raise ValueError("expected RGBA array")
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter: None
        raw.extend(rgba[row].tobytes())
    compressed = zlib.compress(bytes(raw), level=6)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def _parse_bounds(metadata: Dict[str, Any], width: int, height: int) -> Tuple[float, float, float, float]:
    bounds = metadata.get("bounds")
    if bounds is not None:
        if hasattr(bounds, "left"):
            return (float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top))
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            # ASCII loader stores (xmin, xmax, ymin, ymax)
            xmin, xmax, ymin, ymax = bounds
            return (float(xmin), float(ymin), float(xmax), float(ymax))
    xll = float(metadata.get("xllcorner", 0.0))
    yll = float(metadata.get("yllcorner", 0.0))
    dx = float(metadata.get("dx") or metadata.get("cellsize") or 1.0)
    dy = float(metadata.get("dy") or metadata.get("cellsize") or 1.0)
    return (xll, yll, xll + width * dx, yll + height * dy)


def _downsample(data: np.ndarray, max_size: int) -> Tuple[np.ndarray, bool]:
    height, width = data.shape[:2]
    longest = max(height, width)
    if longest <= max_size:
        return data, False
    scale = max_size / float(longest)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    # nearest-neighbor via indexing
    ys = (np.linspace(0, height - 1, new_h)).astype(np.int32)
    xs = (np.linspace(0, width - 1, new_w)).astype(np.int32)
    return data[ys][:, xs], True


def _colormap(norm: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Blue → cyan → green → yellow → red."""
    stops = np.array(
        [
            [0.0, 37, 99, 235],
            [0.25, 34, 211, 238],
            [0.5, 34, 197, 94],
            [0.75, 251, 191, 36],
            [1.0, 239, 68, 68],
        ],
        dtype=np.float64,
    )
    t = np.clip(norm, 0.0, 1.0)
    rgba = np.zeros((*norm.shape, 4), dtype=np.uint8)
    for i in range(len(stops) - 1):
        t0, t1 = stops[i, 0], stops[i + 1, 0]
        mask = (t >= t0) & (t <= t1 if i == len(stops) - 2 else t < t1)
        if not np.any(mask):
            continue
        local = (t[mask] - t0) / max(t1 - t0, 1e-9)
        for c in range(3):
            rgba[mask, c] = np.round(stops[i, c + 1] + local * (stops[i + 1, c + 1] - stops[i, c + 1])).astype(np.uint8)
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    return rgba


def build_raster_preview(
    path: Path,
    *,
    mode: PreviewMode = "downsample",
    max_size: int = DOWNSAMPLE_MAX,
) -> RasterPreviewResult:
    data, metadata = SpatialInputLoader(str(path)).read()
    data = np.asarray(data, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError("only single-band rasters are supported for preview")

    height, width = data.shape
    bounds = _parse_bounds(metadata, width, height)
    nodata = metadata.get("nodata")
    if nodata is None:
        nodata = metadata.get("nodata_value")

    valid = np.isfinite(data)
    if nodata is not None:
        valid &= ~np.isclose(data, float(nodata))

    capped = False
    preview = data
    preview_valid = valid
    if mode == "downsample":
        preview, _ = _downsample(data, max_size)
        preview_valid, _ = _downsample(valid.astype(np.float64), max_size)
        preview_valid = preview_valid > 0.5
    else:
        preview, capped = _downsample(data, FULL_CAP)
        preview_valid, _ = _downsample(valid.astype(np.float64), FULL_CAP if capped else max(width, height))
        preview_valid = preview_valid > 0.5

    if np.any(preview_valid):
        vmin = float(np.min(preview[preview_valid]))
        vmax = float(np.max(preview[preview_valid]))
    else:
        vmin, vmax = 0.0, 1.0
    span = vmax - vmin if vmax > vmin else 1.0
    norm = np.zeros_like(preview, dtype=np.float64)
    norm[preview_valid] = (preview[preview_valid] - vmin) / span
    alpha = preview_valid.astype(np.float64)
    rgba = _colormap(norm, alpha)
    png = _png_rgba(rgba)
    out_h, out_w = rgba.shape[:2]
    return RasterPreviewResult(
        png_bytes=png,
        width=out_w,
        height=out_h,
        bounds=bounds,
        value_min=vmin,
        value_max=vmax,
        nodata=float(nodata) if nodata is not None else None,
        capped=capped,
        mode=mode,
    )
