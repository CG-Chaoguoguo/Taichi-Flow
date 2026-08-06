import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useProjectAssets } from "./useProjectAssets";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { InputFile } from "../types";

const files: InputFile[] = [
  { file_id: "a", family: "dem", name: "a.asc", status: "ready", size: 1, updated_at: "2026-08-02T00:00:00Z" },
  { file_id: "b", family: "slope", name: "b.asc", status: "ready", size: 1, updated_at: "2026-08-02T00:00:00Z" },
  { file_id: "c", family: "zones", name: "c.asc", status: "ready", size: 1, updated_at: "2026-08-02T00:00:00Z" },
  { file_id: "d", family: "rainfall", name: "d.txt", status: "ready", size: 1, updated_at: "2026-08-02T00:00:00Z" },
];

describe("useProjectAssets selection", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      inputFiles: files,
      layerVisibility: {},
      layerOrder: ["a", "b", "c", "d"],
      fetchInputFiles: vi.fn(async () => undefined),
      uploadInputs: vi.fn(async () => []),
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
      addToast: vi.fn(),
    });
  });

  it("toggles a single item on plain click", () => {
    const { result } = renderHook(() => useProjectAssets({ selectedFamily: "all" }));
    act(() => {
      result.current.setSelectionMode(true);
      result.current.handleSelectionClick("a", 0, { shiftKey: false, ctrlKey: false, metaKey: false }, files);
    });
    expect([...result.current.selectedAssetIds]).toEqual(["a"]);
    act(() => {
      result.current.handleSelectionClick("a", 0, { shiftKey: false, ctrlKey: false, metaKey: false }, files);
    });
    expect([...result.current.selectedAssetIds]).toEqual([]);
  });

  it("selects a contiguous range with Shift", () => {
    const { result } = renderHook(() => useProjectAssets({ selectedFamily: "all" }));
    act(() => {
      result.current.setSelectionMode(true);
      result.current.handleSelectionClick("a", 0, { shiftKey: false, ctrlKey: false, metaKey: false }, files);
      result.current.handleSelectionClick("c", 2, { shiftKey: true, ctrlKey: false, metaKey: false }, files);
    });
    expect([...result.current.selectedAssetIds].sort()).toEqual(["a", "b", "c"]);
  });

  it("appends a Shift range when Ctrl is held", () => {
    const { result } = renderHook(() => useProjectAssets({ selectedFamily: "all" }));
    act(() => {
      result.current.setSelectionMode(true);
      result.current.handleSelectionClick("d", 3, { shiftKey: false, ctrlKey: false, metaKey: false }, files);
      result.current.handleSelectionClick("a", 0, { shiftKey: false, ctrlKey: false, metaKey: false }, files);
      result.current.handleSelectionClick("b", 1, { shiftKey: true, ctrlKey: true, metaKey: false }, files);
    });
    expect([...result.current.selectedAssetIds].sort()).toEqual(["a", "b", "d"]);
  });

  it("toggles an individual item with Ctrl without clearing others", () => {
    const { result } = renderHook(() => useProjectAssets({ selectedFamily: "all" }));
    act(() => {
      result.current.setSelectionMode(true);
      result.current.handleSelectionClick("a", 0, { shiftKey: false, ctrlKey: false, metaKey: false }, files);
      result.current.handleSelectionClick("c", 2, { shiftKey: false, ctrlKey: true, metaKey: false }, files);
    });
    expect([...result.current.selectedAssetIds].sort()).toEqual(["a", "c"]);
    act(() => {
      result.current.handleSelectionClick("a", 0, { shiftKey: false, ctrlKey: true, metaKey: false }, files);
    });
    expect([...result.current.selectedAssetIds]).toEqual(["c"]);
  });
});
