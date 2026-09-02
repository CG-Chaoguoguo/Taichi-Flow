import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ZoneSoilEditor, countSpatialZones, parseZoneSoilRows } from "./ZoneSoilEditor";

const chamoliZones = {
  "1": { zone_id: 1, K_sat_top: 8e-6, K_sat_bottom: 2e-7, phi: 42, cvero: 0.6, alpha_top: 0.7 },
  "2": { zone_id: 2, K_sat_top: 4e-6, K_sat_bottom: 9e-7, phi: 20, cvero: 0.3, alpha_top: 0.7 },
};

describe("ZoneSoilEditor", () => {
  it("parses zone rows in id order", () => {
    expect(countSpatialZones(chamoliZones)).toBe(2);
    expect(parseZoneSoilRows(chamoliZones).map((row) => row.zone_id)).toEqual([1, 2]);
  });

  it("edits one zone without rewriting the other", () => {
    const onDraftChange = vi.fn();
    render(
      <ZoneSoilEditor
        draftPatch={{}}
        baseline={{ "spatial_zones.zones": chamoliZones }}
        onDraftChange={onDraftChange}
        canEdit
      />,
    );
    expect(screen.getByTestId("zone-soil-editor")).toBeInTheDocument();
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
      <ZoneSoilEditor
        draftPatch={{}}
        baseline={{ "spatial_zones.zones": { "1": chamoliZones["1"] } }}
        onDraftChange={onDraftChange}
        canEdit
      />,
    );
    const input = screen.getByLabelText("分区 1 顶层 φ") as HTMLInputElement;
    expect(input).toBeDisabled();
    fireEvent.change(input, { target: { value: "10" } });
    expect(onDraftChange).not.toHaveBeenCalled();
  });
});
