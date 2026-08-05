import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { InputFile } from "../../types";
import { AssetContentBrowser } from "./AssetContentBrowser";

const demFile: InputFile = {
  file_id: "file-dem",
  family: "dem",
  name: "bcdem.asc",
  status: "ready",
  size: 2265000,
  updated_at: "2026-08-02T00:00:00Z",
};

const rainfallFile: InputFile = {
  file_id: "file-rain",
  family: "rainfall",
  name: "rain.txt",
  status: "ready",
  size: 512,
  updated_at: "2026-08-02T00:00:00Z",
};

describe("AssetContentBrowser", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      inputFiles: [demFile, rainfallFile],
      layerVisibility: { "file-dem": true },
      layerOrder: ["file-dem", "file-rain"],
      editorSelection: { kind: "input", family: "all" },
      fetchInputFiles: vi.fn(async () => undefined),
      uploadInputs: vi.fn(async () => [demFile]),
      previewInputDeletion: vi.fn(async () => ({
        asset_ids: [],
        assets: [],
        runtime_locked: [],
        detached_binding_count: 0,
        affected_scenario_ids: [],
        cancelled_queue_item_ids: [],
      })),
      deleteInputFiles: vi.fn(async () => ({
        deleted_ids: [],
        detached_binding_count: 0,
        cancelled_queue_item_ids: [],
        retained_snapshot_blob_count: 0,
      })),
      toggleLayerVisibility: vi.fn(),
      reorderLayer: vi.fn(),
      setInputFamily: (family) => useTaichiFlowStore.setState({ editorSelection: { kind: "input", family } }),
      addToast: vi.fn(),
    });
  });

  it("filters by family sidebar and search", () => {
    const onFocusAsset = vi.fn();
    render(<AssetContentBrowser onFocusAsset={onFocusAsset} />);

    expect(screen.getByText("bcdem.asc")).toBeInTheDocument();
    expect(screen.getByText("rain.txt")).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("complementary", { name: "资产类型" })).getByRole("button", { name: /地形栅格/ }));
    expect(screen.getByText("bcdem.asc")).toBeInTheDocument();
    expect(screen.queryByText("rain.txt")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /全部文件/ }));
    fireEvent.change(screen.getByLabelText("搜索资产"), { target: { value: "rain" } });
    expect(screen.queryByText("bcdem.asc")).not.toBeInTheDocument();
    expect(screen.getByText("rain.txt")).toBeInTheDocument();
  });

  it("notifies parent when an asset card is selected", () => {
    const onFocusAsset = vi.fn();
    render(<AssetContentBrowser onFocusAsset={onFocusAsset} />);
    fireEvent.click(screen.getByRole("button", { name: /bcdem\.asc/ }));
    expect(onFocusAsset).toHaveBeenCalledWith(expect.objectContaining({ file_id: "file-dem", name: "bcdem.asc" }));
  });

  it("keeps 全部文件 selected when an asset card is clicked", () => {
    const onFocusAsset = vi.fn();
    render(<AssetContentBrowser onFocusAsset={onFocusAsset} />);
    expect(useTaichiFlowStore.getState().editorSelection).toEqual({ kind: "input", family: "all" });
    fireEvent.click(screen.getByRole("button", { name: /bcdem\.asc/ }));
    expect(onFocusAsset).toHaveBeenCalled();
    expect(useTaichiFlowStore.getState().editorSelection).toEqual({ kind: "input", family: "all" });
    expect(screen.getByRole("button", { name: /全部文件/ }).className).toContain("is-active");
  });

  it("keeps selection and visibility controls as sibling buttons", () => {
    render(<AssetContentBrowser onFocusAsset={() => undefined} />);
    const card = screen.getByRole("listitem", { name: "bcdem.asc" });
    expect(card.querySelector("button button")).toBeNull();
    expect(card.querySelectorAll("button")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "在画布中隐藏" })).toBeInTheDocument();
  });

  it("switches between grid and list views", () => {
    render(<AssetContentBrowser onFocusAsset={() => undefined} />);
    expect(screen.getByLabelText("项目输入资产网格")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "列表视图" }));
    expect(screen.getByLabelText("项目输入资产")).toBeInTheDocument();
  });

  it("toggles delete selection from grid cards and supports select-all deselect", () => {
    render(<AssetContentBrowser onFocusAsset={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByText("已选 0 项")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /bcdem\.asc/ }));
    expect(screen.getByText("已选 1 项")).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "bcdem.asc" }).className).toContain("is-delete-selected");

    fireEvent.click(screen.getByLabelText("全选当前筛选结果中可删除的文件"));
    expect(screen.getByText("已选 2 项")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /bcdem\.asc/ }));
    expect(screen.getByText("已选 1 项")).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "bcdem.asc" }).className).not.toContain("is-delete-selected");
  });

  it("keeps delete selection highlight when switching to list view", () => {
    render(<AssetContentBrowser onFocusAsset={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: /bcdem\.asc/ }));
    fireEvent.click(screen.getByRole("button", { name: "列表视图" }));
    expect(screen.getByText("已选 1 项")).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "bcdem.asc" }).className).toContain("is-delete-selected");
  });

  it("toggles natural filename sort in the asset toolbar", () => {
    const rain10: InputFile = {
      file_id: "a10",
      family: "rainfall",
      name: "ri10.asc",
      status: "ready",
      size: 1,
      updated_at: "2026-08-03T00:00:00Z",
    };
    const rain2: InputFile = {
      file_id: "a2",
      family: "rainfall",
      name: "ri2.asc",
      status: "ready",
      size: 1,
      updated_at: "2026-08-03T00:00:00Z",
    };
    const rain1: InputFile = {
      file_id: "a1",
      family: "rainfall",
      name: "ri1.asc",
      status: "ready",
      size: 1,
      updated_at: "2026-08-03T00:00:00Z",
    };
    useTaichiFlowStore.setState({
      inputFiles: [rain10, rain2, rain1],
      layerVisibility: {},
      layerOrder: ["a10", "a2", "a1"],
      editorSelection: { kind: "input", family: "rainfall" },
    });

    render(<AssetContentBrowser onFocusAsset={() => undefined} />);

    const namesBefore = screen.getAllByRole("listitem").map((item) => item.getAttribute("aria-label"));
    expect(namesBefore).toEqual(["ri10.asc", "ri2.asc", "ri1.asc"]);

    fireEvent.click(screen.getByRole("button", { name: "按文件名排序" }));
    expect(screen.getByRole("button", { name: "取消按文件名排序" })).toHaveAttribute("aria-pressed", "true");
    const namesSorted = screen.getAllByRole("listitem").map((item) => item.getAttribute("aria-label"));
    expect(namesSorted).toEqual(["ri1.asc", "ri2.asc", "ri10.asc"]);

    fireEvent.click(screen.getByRole("button", { name: "列表视图" }));
    expect(screen.queryByTitle("拖拽排序")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消按文件名排序" }));
    const namesRestored = screen.getAllByRole("listitem").map((item) => item.getAttribute("aria-label"));
    expect(namesRestored).toEqual(["ri10.asc", "ri2.asc", "ri1.asc"]);
    expect(screen.getAllByTitle("拖拽排序").length).toBeGreaterThan(0);
  });
});
