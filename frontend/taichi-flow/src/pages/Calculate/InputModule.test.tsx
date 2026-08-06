import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InputModule } from "./InputModule";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { InputFile } from "../../types";

const demFile: InputFile = {
  file_id: "file-dem",
  family: "dem",
  name: "bcdem.asc",
  status: "ready",
  size: 1024,
  updated_at: "2026-08-02T00:00:00Z",
};

const slopeFile: InputFile = {
  file_id: "file-slope",
  family: "slope",
  name: "bcslope.asc",
  status: "ready",
  size: 2048,
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

describe("InputModule family filtering", () => {
  const previewInputDeletion = vi.fn(async (ids: string[]) => ({
    asset_ids: ids,
    assets: [slopeFile],
    runtime_locked: [],
    detached_binding_count: 1,
    affected_scenario_ids: ["scenario-1"],
    cancelled_queue_item_ids: ["queue-1"],
  }));
  const deleteInputFiles = vi.fn(async (ids: string[]) => ({
    deleted_ids: ids,
    detached_binding_count: 1,
    cancelled_queue_item_ids: ["queue-1"],
    retained_snapshot_blob_count: 0,
  }));
  const toggleLayerVisibility = vi.fn();
  const reorderLayer = vi.fn();

  beforeEach(() => {
    previewInputDeletion.mockClear();
    deleteInputFiles.mockClear();
    toggleLayerVisibility.mockClear();
    reorderLayer.mockClear();
    useTaichiFlowStore.setState({
      inputFiles: [demFile, slopeFile, rainfallFile],
      layerVisibility: { "file-slope": true, "file-dem": true },
      layerOrder: ["file-dem", "file-slope", "file-rain"],
      fetchInputFiles: vi.fn(async () => undefined),
      uploadInputs: vi.fn(async () => [demFile]),
      previewInputDeletion,
      deleteInputFiles,
      deleteInputFile: vi.fn(async () => undefined),
      toggleLayerVisibility,
      reorderLayer,
      createInputRevision: vi.fn(async () => ({
        revision_id: "rev-1",
        project_id: "p1",
        version_tag: "v1",
        created_at: "2026-08-02T00:00:00Z",
        status: "ready" as const,
        file_count: 2,
        summary: "",
      })),
      addToast: vi.fn(),
    });
  });

  it("only renders files for the selected family", () => {
    render(<InputModule selectedFamily="slope" onFocusLayer={() => undefined} />);
    expect(screen.getByText("bcslope.asc")).toBeInTheDocument();
    expect(screen.queryByText("bcdem.asc")).not.toBeInTheDocument();
    expect(screen.getByText("1/1 个文件就绪")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资产" })).toBeInTheDocument();
    expect(screen.queryByLabelText("输入文件族")).not.toBeInTheDocument();
  });

  it("shows empty state for a family with no files", () => {
    render(<InputModule selectedFamily="boundary" onFocusLayer={() => undefined} />);
    expect(screen.getByText("该类型暂无资产，请点击“上传资产”。")).toBeInTheDocument();
    expect(screen.getByText("0/0 个文件就绪")).toBeInTheDocument();
  });

  it("shows all files and disables upload in all mode", () => {
    render(<InputModule selectedFamily="all" onFocusLayer={() => undefined} />);
    expect(screen.getByText("bcdem.asc")).toBeInTheDocument();
    expect(screen.getByText("bcslope.asc")).toBeInTheDocument();
    expect(screen.getByText("rain.txt")).toBeInTheDocument();
    expect(screen.getByText("3/3 个文件就绪")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资产" })).toBeDisabled();
    expect(screen.getByText(/不会隐式改变任何方案/)).toBeInTheDocument();
  });

  it("uses explicit selection mode and confirms batch deletion impact", async () => {
    render(<InputModule selectedFamily="slope" onFocusLayer={() => undefined} />);
    const deleteButton = screen.getByRole("button", { name: "删除文件" });
    fireEvent.click(deleteButton);
    const checkbox = screen.getByRole("checkbox", { name: "选择 bcslope.asc" });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "删除 1 项" }));
    await waitFor(() => expect(previewInputDeletion).toHaveBeenCalledWith(["file-slope"]));
    expect(screen.getByRole("dialog", { name: "确认删除文件" })).toBeInTheDocument();
    const deleteActions = screen.getAllByRole("button", { name: "删除 1 项" });
    fireEvent.click(deleteActions[deleteActions.length - 1]);
    await waitFor(() => expect(deleteInputFiles).toHaveBeenCalledWith(["file-slope"]));
  });

  it("keeps runtime-locked assets visible but disables their selection", () => {
    useTaichiFlowStore.setState({
      inputFiles: [{ ...slopeFile, runtime_lock: { locked: true, simulation_ids: ["sim-1"], statuses: ["running"] } }],
      layerOrder: ["file-slope"],
    });
    render(<InputModule selectedFamily="slope" onFocusLayer={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "删除文件" }));
    expect(screen.getByRole("checkbox", { name: "选择 bcslope.asc" })).toBeDisabled();
    expect(screen.getByText("计算引用中")).toBeInTheDocument();
  });

  it("renders eye toggle for visualizable rasters and keeps badge for non-rasters", () => {
    const { rerender } = render(<InputModule selectedFamily="slope" onFocusLayer={() => undefined} />);
    const eye = screen.getByRole("button", { name: "在画布中隐藏" });
    fireEvent.click(eye);
    expect(toggleLayerVisibility).toHaveBeenCalledWith("file-slope");
    expect(screen.queryByText("就绪")).not.toBeInTheDocument();

    rerender(<InputModule selectedFamily="rainfall" onFocusLayer={() => undefined} />);
    expect(screen.getByText("就绪")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "在画布中隐藏" })).not.toBeInTheDocument();
  });

  it("reorders layers on drop", () => {
    render(<InputModule selectedFamily="all" onFocusLayer={() => undefined} />);
    const source = screen.getByText("bcdem.asc").closest(".tf-list-item");
    const target = screen.getByText("bcslope.asc").closest(".tf-list-item");
    expect(source).toBeTruthy();
    expect(target).toBeTruthy();
    const dataTransfer = {
      effectAllowed: "move",
      setData: vi.fn(),
      getData: vi.fn(() => "file-dem"),
    };
    fireEvent.dragStart(source!, { dataTransfer });
    fireEvent.drop(target!, { dataTransfer });
    expect(reorderLayer).toHaveBeenCalledWith("file-dem", "file-slope");
  });
});
