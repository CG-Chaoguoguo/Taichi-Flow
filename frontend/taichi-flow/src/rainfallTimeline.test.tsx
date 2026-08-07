import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RainfallProcessEditor } from "./components/RainfallProcessEditor";
import { deriveRainfallTimeline, regularTimeline, resizeRainfallTimeline } from "./rainfallTimeline";
import type { InputBinding, RainfallPeriod } from "./types";

const periods: RainfallPeriod[] = [
  { period_id: "period-0001", index: 1, start_s: 0, end_s: 3600, source: "uniform", cri_mps: 1e-6 },
  { period_id: "period-0002", index: 2, start_s: 3600, end_s: 7200, source: "raster", asset_id: "rain-2" },
  { period_id: "period-0003", index: 3, start_s: 7200, end_s: 10800, source: "raster", asset_id: "rain-3" },
];

const bindings: InputBinding[] = [2, 3].map((ordinal) => ({
  binding_key: `rainfall.period.${String(ordinal).padStart(4, "0")}`,
  asset_id: `rain-${ordinal}`,
  family: "rainfall",
  role: "rainfall-period",
  period_id: `period-${String(ordinal).padStart(4, "0")}`,
  ordinal,
  active: true,
}));

describe("rainfall timeline", () => {
  it("derives period count and boundaries only from start, end, and interval", () => {
    const timeline = regularTimeline(0, 259200, 3600, "edda_in.capt");
    expect(timeline.period_count).toBe(72);
    expect(timeline.boundaries_s).toHaveLength(73);
    expect(timeline.boundaries_s[timeline.boundaries_s.length - 1]).toBe(259200);
    expect(() => regularTimeline(0, 10000, 3600)).toThrow(/整除/);
  });

  it("preserves exact irregular capt boundaries as a custom imported timeline", () => {
    const timeline = deriveRainfallTimeline([
      { index: 1, start_s: 0, end_s: 1800 },
      { index: 2, start_s: 1800, end_s: 5400 },
    ]);
    expect(timeline).toMatchObject({ mode: "custom", period_count: 2, boundaries_s: [0, 1800, 5400] });
  });

  it("deactivates truncated bindings and does not resurrect them when the timeline expands again", () => {
    const shrunk = resizeRainfallTimeline(periods, bindings, regularTimeline(0, 7200, 3600));
    expect(shrunk.periods).toHaveLength(2);
    expect(shrunk.bindings.find((binding) => binding.ordinal === 3)?.active).toBe(false);

    const expanded = resizeRainfallTimeline(shrunk.periods, shrunk.bindings, regularTimeline(0, 10800, 3600));
    expect(expanded.periods).toHaveLength(3);
    expect(expanded.periods[2]).toMatchObject({ source: "raster", asset_id: null });
    expect(expanded.bindings.find((binding) => binding.ordinal === 3)?.active).toBe(false);
  });

  it("applies a new timeline and explicitly synchronizes the simulation end", () => {
    const onChange = vi.fn();
    render(
      <RainfallProcessEditor
        periods={periods.slice(0, 2)}
        bindings={bindings.slice(0, 1)}
        assets={[]}
        canEdit
        timeline={regularTimeline(0, 7200, 3600)}
        simulationEndS={7200}
        onChange={onChange}
      />,
    );

    expect(screen.getByLabelText("第 1 时段开始时间")).toHaveAttribute("readonly");
    fireEvent.change(screen.getByLabelText("降雨结束时间"), { target: { value: "10800" } });
    fireEvent.click(screen.getByRole("button", { name: "应用时间轴" }));

    const [nextPeriods, , nextTimeline, nextSimulationEnd] = onChange.mock.calls[onChange.mock.calls.length - 1] as [
      RainfallPeriod[], InputBinding[], ReturnType<typeof regularTimeline>, number,
    ];
    expect(nextPeriods).toHaveLength(3);
    expect(nextTimeline).toMatchObject({ start_s: 0, end_s: 10800, interval_s: 3600, period_count: 3 });
    expect(nextSimulationEnd).toBe(10800);
  });
});
