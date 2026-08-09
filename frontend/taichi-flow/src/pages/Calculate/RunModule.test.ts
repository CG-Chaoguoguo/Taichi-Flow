import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { QueueItem, Scenario } from "../../types";
import { selectScenarioQueueItem } from "./RunModule";
import { RunModule } from "./RunModule";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";


const scenario = {
  scenario_id: "scenario-1",
  latest_simulation_id: "sim-new",
} as Scenario;


function queueItem(queueItemId: string, simulationId: string, status: QueueItem["status"]): QueueItem {
  return {
    queue_item_id: queueItemId,
    project_id: "project-1",
    scenario_id: "scenario-1",
    scenario_name: "Scenario",
    position: 1,
    status,
    simulation_id: simulationId,
    enqueued_at: "2026-08-06T00:00:00Z",
    started_at: "2026-08-06T00:00:01Z",
    finished_at: status === "running" ? null : "2026-08-06T00:00:02Z",
    progress: status === "running" ? 25 : 1,
    summary: status,
  };
}


describe("selectScenarioQueueItem", () => {
  it("uses the queue item for the scenario's latest simulation after a retry", () => {
    const queue = [
      queueItem("queue-old", "sim-old", "failed"),
      queueItem("queue-new", "sim-new", "running"),
    ];

    expect(selectScenarioQueueItem(queue, scenario)?.simulation_id).toBe("sim-new");
  });

  it("prefers a newly staged item over the previous terminal simulation", () => {
    const queue = [
      queueItem("queue-old", "sim-new", "completed"),
      { ...queueItem("queue-staged", "", "waiting"), started_at: null, finished_at: null, progress: 0 },
    ];

    expect(selectScenarioQueueItem(queue, scenario)?.queue_item_id).toBe("queue-staged");
  });
});

describe("RunModule queue membership", () => {
  const scenarioWithConfig: Scenario = {
    scenario_id: "scenario-1",
    project_id: "project-1",
    name: "Scenario",
    input_revision_id: null,
    parameter_patch: {},
    effective_parameters: {},
    input_bindings: [],
    status: "completed",
    progress: 100,
    latest_simulation_id: "sim-old",
    result_family_count: 2,
    file_count: 4,
    created_at: "2026-08-06T00:00:00Z",
    updated_at: "2026-08-06T00:00:00Z",
  };

  beforeEach(() => {
    useTaichiFlowStore.setState({
      queue: [],
      metrics: { cpu_percent: 12, gpu_percent: 35, gpu_name: "GPU" },
      activeProject: { project_id: "project-1" } as never,
      scenarioConfigurations: { "scenario-1": { scenario_id: "scenario-1", validation: { valid: true, errors: [], warnings: [] } } } as never,
      enqueueScenario: vi.fn(),
      fetchScenarioConfiguration: vi.fn(),
    });
  });

  it("returns to preflight and enqueue when the visible queue item was deleted", () => {
    render(createElement(RunModule, { scenario: scenarioWithConfig }));
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeInTheDocument();
    expect(screen.queryByText(/运行输入快照/)).not.toBeInTheDocument();
    expect(screen.queryByText(/查看运行日志/)).not.toBeInTheDocument();
  });

  it("hides the snapshot reminder while an item is waiting", () => {
    useTaichiFlowStore.setState({
      queue: [{ ...queueItem("queue-waiting", "", "waiting"), started_at: null, finished_at: null, progress: 0 }],
    });
    render(createElement(RunModule, {
      scenario: { ...scenarioWithConfig, status: "waiting", binding_state: "runtime_snapshot", input_revision_id: "rev-1" },
    }));
    expect(screen.getByText("待运行")).toBeInTheDocument();
    expect(screen.queryByText(/运行输入快照/)).not.toBeInTheDocument();
    expect(screen.queryByText(/队列位置/)).not.toBeInTheDocument();
  });
});
