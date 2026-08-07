import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildLibraryAutoMapping, RainfallProcessEditor, sortRainfallFiles } from "./RainfallProcessEditor";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { InputBinding, InputFile, RainfallPeriod } from "../types";

const periods: RainfallPeriod[] = [
  { period_id: "period-0001", index: 1, start_s: 0, end_s: 3600, source: "uniform", cri_mps: 1e-6 },
  { period_id: "period-0002", index: 2, start_s: 3600, end_s: 7200, source: "raster", asset_id: "rain-2" },
];

const assets: InputFile[] = [
  {
    file_id: "rain-2",
    family: "rainfall",
    name: "ri2.asc",
    status: "ready",
    size: 100,
    updated_at: "2026-08-03T00:00:00Z",
    roles: ["rainfall-period"],
  },
];

const bindings: InputBinding[] = [
  {
    binding_key: "rainfall.period.0002",
    asset_id: "rain-2",
    family: "rainfall",
    role: "rainfall-period",
    period_id: "period-0002",
    ordinal: 2,
    active: true,
  },
];

describe("RainfallProcessEditor", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({ addToast: vi.fn() });
  });

  it("shows mm/h by default, stores m/s, and never exposes the legacy -1 sentinel", () => {
    const onChange = vi.fn();
    render(
      <RainfallProcessEditor
        periods={periods}
        bindings={bindings}
        assets={assets}
        canEdit
        onChange={onChange}
      />,
    );

    expect(screen.queryByText(/-1/)).not.toBeInTheDocument();
    const intensity = screen.getByLabelText("第 1 时段雨强") as HTMLInputElement;
    expect(Number(intensity.value)).toBeCloseTo(3.6);
    fireEvent.change(intensity, { target: { value: "7.2" } });
    const [nextPeriods] = onChange.mock.calls[onChange.mock.calls.length - 1] as [RainfallPeriod[], InputBinding[]];
    expect(nextPeriods[0].cri_mps).toBeCloseTo(2e-6);
  });

  it("switches one period independently and binds a typed asset", () => {
    const onChange = vi.fn();
    function Harness() {
      const [currentPeriods, setCurrentPeriods] = useState(periods);
      const [currentBindings, setCurrentBindings] = useState(bindings);
      return (
        <RainfallProcessEditor
          periods={currentPeriods}
          bindings={currentBindings}
          assets={assets}
          canEdit
          onChange={(nextPeriods, nextBindings) => {
            onChange(nextPeriods, nextBindings);
            setCurrentPeriods(nextPeriods);
            setCurrentBindings(nextBindings);
          }}
        />
      );
    }
    render(<Harness />);

    fireEvent.change(screen.getByLabelText("第 1 时段来源"), { target: { value: "raster" } });
    fireEvent.click(screen.getByRole("button", { name: "为第 1 时段选择栅格资产" }));
    fireEvent.click(screen.getByRole("button", { name: /ri2\.asc/ }));
    const [nextPeriods, nextBindings] = onChange.mock.calls[onChange.mock.calls.length - 1] as [RainfallPeriod[], InputBinding[]];
    expect(nextPeriods[0]).toMatchObject({ source: "raster", asset_id: "rain-2" });
    expect(nextBindings).toContainEqual(expect.objectContaining({ binding_key: "rainfall.period.0001", asset_id: "rain-2" }));
  });

  it("clears all rainfall assets without changing raster period structure", () => {
    const onChange = vi.fn();
    render(
      <RainfallProcessEditor
        periods={periods}
        bindings={bindings}
        assets={assets}
        canEdit
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "取消全部降雨绑定" }));
    const [nextPeriods, nextBindings] = onChange.mock.calls[onChange.mock.calls.length - 1] as [RainfallPeriod[], InputBinding[]];
    expect(nextPeriods[0]).toMatchObject({ source: "uniform", cri_mps: 1e-6 });
    expect(nextPeriods[1]).toMatchObject({ source: "raster", asset_id: null });
    expect(nextBindings.filter((binding) => binding.role === "rainfall-period")).toHaveLength(0);
  });

  it("sorts batch files by numeric ordinal instead of lexicographic order", () => {
    const files = [new File([""], "ri10.asc"), new File([""], "ri2.asc"), new File([""], "ri1.asc")];
    expect(sortRainfallFiles(files).map((file) => file.name)).toEqual(["ri1.asc", "ri2.asc", "ri10.asc"]);
  });

  it("previews and applies a complete 72-file mapping before changing the draft", async () => {
    const batchPeriods: RainfallPeriod[] = Array.from({ length: 72 }, (_, index) => ({
      period_id: `period-${String(index + 1).padStart(4, "0")}`,
      index: index + 1,
      start_s: index * 3600,
      end_s: (index + 1) * 3600,
      source: "raster",
      asset_id: null,
    }));
    const files = Array.from({ length: 72 }, (_, index) => new File([String(index)], `ri${index + 1}.asc`));
    const uploaded: InputFile[] = files.map((file, index) => ({
      file_id: `rain-${index + 1}`,
      family: "rainfall",
      name: file.name,
      status: "ready",
      size: file.size,
      updated_at: "2026-08-03T00:00:00Z",
      roles: ["rainfall-period"],
    }));
    const onUpload = vi.fn().mockResolvedValue(uploaded);
    const onChange = vi.fn();
    const { container } = render(
      <RainfallProcessEditor
        periods={batchPeriods}
        bindings={[]}
        assets={uploaded}
        canEdit
        onUpload={onUpload}
        onChange={onChange}
      />,
    );

    const input = container.querySelector<HTMLInputElement>('input[type="file"]:not([webkitdirectory])');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files } });

    await waitFor(() => expect(container.querySelectorAll(".tf-mapping-item")).toHaveLength(72));
    expect(onChange).not.toHaveBeenCalled();
    expect(onUpload).toHaveBeenCalledWith(files);

    fireEvent.click(screen.getByRole("button", { name: "应用映射" }));
    const [nextPeriods, nextBindings] = onChange.mock.calls[onChange.mock.calls.length - 1] as [RainfallPeriod[], InputBinding[]];
    expect(nextPeriods).toHaveLength(72);
    expect(nextPeriods.every((period, index) => period.asset_id === `rain-${index + 1}`)).toBe(true);
    expect(nextBindings).toHaveLength(72);
    expect(nextBindings[71]).toMatchObject({
      binding_key: "rainfall.period.0072",
      ordinal: 72,
      asset_id: "rain-72",
      active: true,
    });
  });

  it("auto-binds library assets by filename ordinal without overwriting existing bindings", () => {
    const batchPeriods: RainfallPeriod[] = Array.from({ length: 3 }, (_, index) => ({
      period_id: `period-${String(index + 1).padStart(4, "0")}`,
      index: index + 1,
      start_s: index * 3600,
      end_s: (index + 1) * 3600,
      source: "raster",
      asset_id: index === 1 ? "rain-2" : null,
    }));
    const libraryAssets: InputFile[] = Array.from({ length: 3 }, (_, index) => ({
      file_id: `rain-${index + 1}`,
      family: "rainfall",
      name: `ri${index + 1}.asc`,
      status: "ready",
      size: 10,
      updated_at: "2026-08-03T00:00:00Z",
      roles: ["rainfall-period"],
    }));
    const existingBindings: InputBinding[] = [
      {
        binding_key: "rainfall.period.0002",
        asset_id: "rain-2",
        family: "rainfall",
        role: "rainfall-period",
        period_id: "period-0002",
        ordinal: 2,
        active: true,
      },
    ];
    const onChange = vi.fn();
    render(
      <RainfallProcessEditor
        periods={batchPeriods}
        bindings={existingBindings}
        assets={libraryAssets}
        canEdit
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "按文件名自动绑定" }));
    expect(onChange).toHaveBeenCalled();
    const [nextPeriods, nextBindings] = onChange.mock.calls[onChange.mock.calls.length - 1] as [RainfallPeriod[], InputBinding[]];
    expect(nextPeriods[0].asset_id).toBe("rain-1");
    expect(nextPeriods[1].asset_id).toBe("rain-2");
    expect(nextPeriods[2].asset_id).toBe("rain-3");
    expect(nextBindings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ binding_key: "rainfall.period.0001", asset_id: "rain-1" }),
        expect.objectContaining({ binding_key: "rainfall.period.0002", asset_id: "rain-2" }),
        expect.objectContaining({ binding_key: "rainfall.period.0003", asset_id: "rain-3" }),
      ]),
    );
  });

  it("does not expose a filename-sort toggle in the rainfall toolbar", () => {
    render(
      <RainfallProcessEditor
        periods={periods}
        bindings={bindings}
        assets={assets}
        canEdit
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "按文件名排序" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "已按文件名排序" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "按文件名自动绑定" })).toBeInTheDocument();
  });

  it("surfaces ambiguous library ordinals in mapping preview and blocks apply", () => {
    const batchPeriods: RainfallPeriod[] = [
      { period_id: "period-0001", index: 1, start_s: 0, end_s: 3600, source: "raster", asset_id: null },
    ];
    const libraryAssets: InputFile[] = [
      { file_id: "dup-a", family: "rainfall", name: "ri1.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
      { file_id: "dup-b", family: "rainfall", name: "rain1.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
    ];
    const onChange = vi.fn();
    render(
      <RainfallProcessEditor
        periods={batchPeriods}
        bindings={[]}
        assets={libraryAssets}
        canEdit
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "按文件名自动绑定" }));
    expect(screen.getByText("库内自动映射")).toBeInTheDocument();
    expect(screen.getByText(/存在多个候选/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用映射" })).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("buildLibraryAutoMapping skips already-bound periods", () => {
    const result = buildLibraryAutoMapping(
      [
        { period_id: "period-0001", index: 1, start_s: 0, end_s: 3600, source: "raster", asset_id: null },
        { period_id: "period-0002", index: 2, start_s: 3600, end_s: 7200, source: "raster", asset_id: "rain-2" },
      ],
      [
        { file_id: "rain-1", family: "rainfall", name: "ri1.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
        { file_id: "rain-2", family: "rainfall", name: "ri2.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
      ],
      [
        { period_id: "period-0001", index: 1, start_s: 0, end_s: 3600, source: "raster", asset_id: null },
        { period_id: "period-0002", index: 2, start_s: 3600, end_s: 7200, source: "raster", asset_id: "rain-2" },
      ],
      [
        {
          binding_key: "rainfall.period.0002",
          asset_id: "rain-2",
          family: "rainfall",
          role: "rainfall-period",
          period_id: "period-0002",
          ordinal: 2,
          active: true,
        },
      ],
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ targetIndex: 1, asset: expect.objectContaining({ file_id: "rain-1" }) });
  });
});
