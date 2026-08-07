import type { InputBinding, RainfallPeriod, RainfallTimeline } from "./types";

export const MAX_RAINFALL_PERIODS = 10_000;

const isRaster = (source: RainfallPeriod["source"]) => ["raster", "rifil", "raster_rifil"].includes(String(source || ""));
const periodId = (index: number) => `period-${String(index).padStart(4, "0")}`;
const bindingKey = (index: number) => `rainfall.period.${String(index).padStart(4, "0")}`;
const closeEnough = (left: number, right: number, scale = 1) => Math.abs(left - right) <= Math.max(1e-9, Math.abs(scale) * 1e-9);

export function regularTimeline(startValue: number, endValue: number, intervalValue: number, source = "user"): RainfallTimeline {
  const start = Number(startValue);
  const end = Number(endValue);
  const interval = Number(intervalValue);
  if (![start, end, interval].every(Number.isFinite)) throw new Error("降雨时间轴必须使用有限数值。");
  if (end <= start) throw new Error("降雨结束时间必须大于开始时间。");
  if (interval <= 0) throw new Error("降雨时段间隔必须大于 0。");
  const rawCount = (end - start) / interval;
  const periodCount = Math.round(rawCount);
  if (periodCount < 1 || !closeEnough(start + periodCount * interval, end, interval)) {
    throw new Error("降雨起止时间之差必须能被时段间隔整除。");
  }
  if (periodCount > MAX_RAINFALL_PERIODS) throw new Error(`降雨时段数不能超过 ${MAX_RAINFALL_PERIODS}。`);
  const boundaries = Array.from({ length: periodCount + 1 }, (_, index) => start + index * interval);
  boundaries[boundaries.length - 1] = end;
  return {
    mode: "regular",
    start_s: start,
    end_s: end,
    interval_s: interval,
    period_count: periodCount,
    boundaries_s: boundaries,
    source,
  };
}

export function deriveRainfallTimeline(periods: RainfallPeriod[], source = "period_rows_compat"): RainfallTimeline {
  if (!periods.length) {
    return { mode: "regular", start_s: 0, end_s: 3600, interval_s: 3600, period_count: 1, boundaries_s: [0, 3600], source };
  }
  const boundaries = [Number(periods[0].start_s ?? 0), ...periods.map((period) => Number(period.end_s ?? 0))];
  const deltas = boundaries.slice(1).map((value, index) => value - boundaries[index]);
  const regular = deltas.every((delta) => delta > 0 && closeEnough(delta, deltas[0], deltas[0]));
  return {
    mode: regular ? "regular" : "custom",
    start_s: boundaries[0],
    end_s: boundaries[boundaries.length - 1],
    interval_s: regular ? deltas[0] : null,
    period_count: periods.length,
    boundaries_s: boundaries,
    source,
  };
}

export function resizeRainfallTimeline(
  periods: RainfallPeriod[],
  bindings: InputBinding[],
  timeline: RainfallTimeline,
): { periods: RainfallPeriod[]; bindings: InputBinding[] } {
  if (timeline.mode !== "regular" || timeline.boundaries_s.length !== timeline.period_count + 1) {
    throw new Error("只能使用有效的等间隔时间轴生成降雨时段。");
  }
  const fallbackRaster = periods.length > 0 && isRaster(periods[periods.length - 1].source);
  const nextPeriods = Array.from({ length: timeline.period_count }, (_, offset): RainfallPeriod => {
    const index = offset + 1;
    const id = periodId(index);
    const existing = periods[offset];
    const retainedBinding = bindings.find((binding) =>
      binding.active !== false
      && Boolean(binding.asset_id)
      && (binding.binding_key === bindingKey(index) || binding.period_id === id),
    );
    const raster = existing ? isRaster(existing.source) : Boolean(retainedBinding?.asset_id) || fallbackRaster;
    return {
      ...existing,
      period_id: id,
      index,
      start_s: timeline.boundaries_s[offset],
      end_s: timeline.boundaries_s[offset + 1],
      source: raster ? "raster" : "uniform",
      asset_id: raster ? (existing?.asset_id || retainedBinding?.asset_id || null) : null,
      cri_mps: raster ? null : Math.max(0, Number(existing?.cri_mps || 0)),
    };
  });

  const nextById = new Map(nextPeriods.map((period) => [period.period_id, period]));
  const nextBindings = bindings.map((binding) => {
    if (binding.role !== "rainfall-period") return binding;
    const id = binding.period_id || (binding.ordinal ? periodId(binding.ordinal) : null);
    const period = id ? nextById.get(id) : undefined;
    return { ...binding, active: binding.active !== false && Boolean(period && isRaster(period.source)) };
  });
  for (const period of nextPeriods) {
    if (!isRaster(period.source) || !period.asset_id) continue;
    const key = bindingKey(period.index);
    const existingIndex = nextBindings.findIndex((binding) => binding.binding_key === key);
    const nextBinding: InputBinding = {
      ...(existingIndex >= 0 ? nextBindings[existingIndex] : {}),
      binding_key: key,
      asset_id: period.asset_id,
      family: "rainfall",
      role: "rainfall-period",
      period_id: period.period_id,
      ordinal: period.index,
      active: true,
    };
    if (existingIndex >= 0) nextBindings[existingIndex] = nextBinding;
    else nextBindings.push(nextBinding);
  }
  return { periods: nextPeriods, bindings: nextBindings };
}
