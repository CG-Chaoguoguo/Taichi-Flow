import { describe, expect, it } from "vitest";
import { canEditScenario, scenarioHasActiveComputation } from "./scenarioEditability";
import type { QueueItem, Scenario } from "../types";

const scenario = (status: Scenario["status"]): Scenario => ({
  scenario_id: "scenario-1",
  project_id: "project-1",
  name: "Scenario",
  input_revision_id: status === "completed" ? "revision-1" : null,
  parameter_template_id: "template-1",
  parameter_patch: {},
  effective_parameters: {},
  status,
  progress: status === "completed" ? 100 : 0,
  latest_simulation_id: status === "completed" ? "simulation-1" : null,
  result_family_count: status === "completed" ? 1 : 0,
  file_count: 0,
  created_at: "",
  updated_at: "",
});

const queueItem = (status: QueueItem["status"]): QueueItem => ({
  queue_item_id: "queue-1",
  project_id: "project-1",
  scenario_id: "scenario-1",
  scenario_name: "Scenario",
  position: 8,
  queue_order: 1,
  status,
  simulation_id: null,
  enqueued_at: "",
  started_at: null,
  finished_at: null,
  progress: 0,
  summary: "",
});

describe("scenario editability", () => {
  it("allows terminal, waiting, and queued scenarios to form a new draft", () => {
    for (const status of ["completed", "failed", "stopped", "interrupted", "cancelled", "waiting", "queued"] as const) {
      expect(canEditScenario(scenario(status))).toBe(true);
    }
  });

  it("locks only actual active computation states, including queue races", () => {
    expect(canEditScenario(scenario("running"))).toBe(false);
    expect(scenarioHasActiveComputation(scenario("waiting"), [queueItem("starting")])).toBe(true);
    expect(canEditScenario(scenario("waiting"), [queueItem("queued")])).toBe(true);
  });

  it("keeps archived and legacy scenarios read-only", () => {
    expect(canEditScenario({ ...scenario("completed"), archived: true })).toBe(false);
    expect(canEditScenario({ ...scenario("completed"), parameter_template_id: null })).toBe(false);
  });
});
