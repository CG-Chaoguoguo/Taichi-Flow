"""Path-free rainfall timeline normalization shared by templates and imports."""

from __future__ import annotations

import math
from typing import Any, Iterable, Optional


MAX_RAINFALL_PERIODS = 10000


def regular_boundaries(start_s: float, end_s: float, interval_s: float) -> list[float]:
    start = float(start_s)
    end = float(end_s)
    interval = float(interval_s)
    if not all(math.isfinite(value) for value in (start, end, interval)):
        raise ValueError("降雨时间轴必须使用有限数值。")
    if end <= start:
        raise ValueError("降雨结束时间必须大于开始时间。")
    if interval <= 0:
        raise ValueError("降雨时段间隔必须大于 0。")
    count_float = (end - start) / interval
    count = int(round(count_float))
    tolerance = max(1.0e-9, abs(interval) * 1.0e-9)
    if count < 1 or not math.isclose(start + count * interval, end, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError("降雨起止时间之差必须能被时段间隔整除。")
    if count > MAX_RAINFALL_PERIODS:
        raise ValueError(f"降雨时段数不能超过 {MAX_RAINFALL_PERIODS}。")
    boundaries = [start + index * interval for index in range(count + 1)]
    boundaries[-1] = end
    return boundaries


def timeline_from_boundaries(
    boundaries_s: Iterable[Any],
    *,
    source: str,
    declared_period_count: Optional[int] = None,
    declared_end_s: Optional[float] = None,
) -> dict[str, Any]:
    boundaries = [float(value) for value in boundaries_s]
    deltas = [right - left for left, right in zip(boundaries, boundaries[1:])]
    regular = bool(deltas) and all(
        delta > 0 and math.isclose(delta, deltas[0], rel_tol=0.0, abs_tol=max(1.0e-9, abs(deltas[0]) * 1.0e-9))
        for delta in deltas
    )
    return {
        "mode": "regular" if regular else "custom",
        "start_s": boundaries[0] if boundaries else None,
        "end_s": boundaries[-1] if boundaries else None,
        "interval_s": deltas[0] if regular else None,
        "period_count": max(0, len(boundaries) - 1),
        "boundaries_s": boundaries,
        "source": source,
        "declared_period_count": int(declared_period_count) if declared_period_count is not None else None,
        "declared_end_s": float(declared_end_s) if declared_end_s is not None else None,
    }
