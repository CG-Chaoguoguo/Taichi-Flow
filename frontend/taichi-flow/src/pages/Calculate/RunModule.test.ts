import { describe, expect, it } from "vitest";
import type { QueueItem, Scenario } from "../../types";
import { selectScenarioQueueItem } from "./RunModule";


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
