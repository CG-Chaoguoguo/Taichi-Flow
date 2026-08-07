import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScenarioDeleteDialog } from "./ScenarioDialogs";
import type { Scenario, ScenarioDeletePreview } from "../types";

const scenario = { scenario_id: "scenario-1", name: "Disposable" } as Scenario;

function preview(overrides: Partial<ScenarioDeletePreview> = {}): ScenarioDeletePreview {
  return {
    scenario_id: scenario.scenario_id,
    disposition: "archive",
    can_remove: true,
    can_archive: true,
    can_permanently_delete: true,
    blocking_queue_item_ids: [],
    active_simulation_ids: [],
    run_count: 2,
    result_family_count: 1,
    queue_item_count: 2,
    output_count: 4,
    export_count: 1,
    derived_scenario_count: 0,
    preserves_history: true,
    ...overrides,
  };
}

describe("ScenarioDeleteDialog", () => {
  it("prioritizes permanent deletion while keeping archive as a secondary action", () => {
    render(
      <ScenarioDeleteDialog
        open
        scenario={scenario}
        preview={preview()}
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onPermanentDelete={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "删除方案" })).toBeInTheDocument();
    expect(screen.getByText(/永久删除将移除/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "移入归档" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "永久删除" })).toBeInTheDocument();
    expect(screen.getByText("2 条队列记录")).toBeInTheDocument();
    expect(screen.getByText("4 个输出")).toBeInTheDocument();
  });

  it("blocks irreversible deletion while an active calculation exists", () => {
    render(
      <ScenarioDeleteDialog
        open
        scenario={scenario}
        preview={preview({ can_permanently_delete: false, active_simulation_ids: ["sim-1"], can_archive: false, can_remove: false })}
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onPermanentDelete={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "永久删除" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("活动计算");
  });
});
