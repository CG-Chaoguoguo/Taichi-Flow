import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ZoneSoilSummaryCard, ZoneSoilWorkspace, countSpatialZones, parseZoneSoilRows } from "./ZoneSoilEditor";

const referenceZones = {
  "1": { zone_id: 1, K_sat_top: 8e-6, K_sat_bottom: 2e-7, phi: 42, cvero: 0.6, alpha_top: 0.7 },
  "2": { zone_id: 2, K_sat_top: 4e-6, K_sat_bottom: 9e-7, phi: 20, cvero: 0.3, alpha_top: 0.7 },
};

describe("ZoneSoilEditor", () => {
  it("parses zone rows in id order", () => {
    expect(countSpatialZones(referenceZones)).toBe(2);
    expect(parseZoneSoilRows(referenceZones).map((row) => row.zone_id)).toEqual([1, 2]);
  });

  it("edits one zone without rewriting the other", () => {
    const onDraftChange = vi.fn();
    render(
      <ZoneSoilWorkspace
        draftPatch={{}}
        baseline={{ "spatial_zones.zones": referenceZones }}
        onDraftChange={onDraftChange}
        canEdit
      />,
    );
    expect(screen.getByTestId("zone-soil-workspace")).toBeInTheDocument();
    const input = screen.getByLabelText("分区 2 顶层 φ") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "24" } });
    const [next] = onDraftChange.mock.calls[0] as [Record<string, unknown>];
    const zones = next["spatial_zones.zones"] as Record<string, Record<string, unknown>>;
    expect(zones["1"].phi).toBe(42);
    expect(zones["2"].phi).toBe(24);
    expect(zones["2"].K_sat_bottom).toBe(9e-7);
  });

  it("keeps a single-zone matrix read-only", () => {
    const onDraftChange = vi.fn();
    render(
      <ZoneSoilWorkspace
        draftPatch={{}}
        baseline={{ "spatial_zones.zones": { "1": referenceZones["1"] } }}
        onDraftChange={onDraftChange}
        canEdit
      />,
    );
    const input = screen.getByLabelText("分区 1 顶层 φ") as HTMLInputElement;
    expect(input).toBeDisabled();
    fireEvent.change(input, { target: { value: "10" } });
    expect(onDraftChange).not.toHaveBeenCalled();
    expect(screen.getByText("当前方案仅 1 个分区，矩阵只读。")).toBeInTheDocument();
  });

  it("resets an override back to the template baseline", () => {
    const onDraftChange = vi.fn();
    render(
      <ZoneSoilWorkspace
        draftPatch={{ "spatial_zones.zones": { ...referenceZones, "2": { ...referenceZones["2"], phi: 24 } } }}
        baseline={{ "spatial_zones.zones": referenceZones }}
        onDraftChange={onDraftChange}
        canEdit
      />,
    );
    expect(screen.getByText("方案覆盖")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重置为模板默认值" }));
    const [next] = onDraftChange.mock.calls[0] as [Record<string, unknown>];
    expect(next["spatial_zones.zones"]).toBeUndefined();
  });

  it("returns to the canvas when requested", () => {
    const onClose = vi.fn();
    render(
      <ZoneSoilWorkspace
        draftPatch={{}}
        baseline={{ "spatial_zones.zones": referenceZones }}
        onDraftChange={vi.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "返回画布" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("opens the workspace from the summary card", () => {
    const onOpen = vi.fn();
    render(
      <ZoneSoilSummaryCard
        draftPatch={{}}
        baseline={{ "spatial_zones.zones": referenceZones }}
        onDraftChange={vi.fn()}
        onOpen={onOpen}
      />,
    );
    expect(screen.getByTestId("zone-soil-summary")).toBeInTheDocument();
    expect(screen.getByText("2 区")).toBeInTheDocument();
    expect(screen.getByText("模板默认")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /分区双层土参数/ }));
    expect(onOpen).toHaveBeenCalled();
  });
});
