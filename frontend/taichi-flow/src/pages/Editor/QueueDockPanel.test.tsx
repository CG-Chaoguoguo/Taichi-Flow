import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueueDockPanel } from "./QueueDockPanel";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { QueueItem } from "../../types";

function item(id: string, position: number, queueOrder: number | null, status: QueueItem["status"]): QueueItem {
  return {
    queue_item_id: id,
    project_id: "project-1",
    scenario_id: id,
    scenario_name: id,
    position,
    queue_order: queueOrder,
    status,
    simulation_id: status === "completed" ? `sim-${id}` : null,
    enqueued_at: `2026-08-07T00:00:0${position}Z`,
    started_at: null,
    finished_at: status === "completed" ? "2026-08-07T00:01:00Z" : null,
    progress: status === "completed" ? 100 : 0,
    summary: status,
  };
}

describe("QueueDockPanel display order", () => {
  const reorderQueue = vi.fn();

  beforeEach(() => {
    reorderQueue.mockReset();
    useTaichiFlowStore.setState({
      queue: [
        item("waiting-a", 8, 1, "waiting"),
        item("waiting-b", 9, 2, "waiting"),
        item("terminal-c", 4, null, "completed"),
      ],
      startQueueBatch: vi.fn(),
      previewQueueDeletion: vi.fn(),
      deleteQueueItems: vi.fn(),
      stopRunningItem: vi.fn(),
      reorderQueue,
      retryQueueItem: vi.fn(),
      setEditorSelection: vi.fn(),
    });
  });

  it("uses continuous visible ordinals instead of historical positions", () => {
    const { container } = render(<QueueDockPanel />);
    const ordinals = [...container.querySelectorAll(".tf-dock-queue-main > span:first-child")].map((node) => node.textContent);
    expect(ordinals).toEqual(["1", "2", "3"]);
    expect(container.textContent).not.toContain("#8");
    expect(container.querySelectorAll(".tf-dock-queue-drag-handle")).toHaveLength(0);
  });

  it("keeps whole-row drag sorting and sends the waiting relative position", () => {
    const { container } = render(<QueueDockPanel />);
    const rows = [...container.querySelectorAll<HTMLElement>(".tf-dock-queue-row")];
    expect(rows[0].draggable).toBe(true);

    fireEvent.dragStart(rows[1], { dataTransfer: { effectAllowed: "move", setData: vi.fn() } });
    fireEvent.dragOver(rows[0], { dataTransfer: { effectAllowed: "move" } });
    fireEvent.drop(rows[0]);

    expect(reorderQueue).toHaveBeenCalledWith("waiting-b", 1);
  });
});
