import type { QueueItem, Scenario } from "../types";

/** Queue/simulation states that represent an actual computation and must stay immutable. */
const ACTIVE_QUEUE_STATES = new Set(["starting", "running", "stopping"]);
const ACTIVE_SCENARIO_STATES = new Set(["starting", "running", "stopping"]);

export function scenarioHasActiveComputation(scenario: Scenario | null | undefined, queue: QueueItem[] = []): boolean {
  if (!scenario) return false;
  if (ACTIVE_SCENARIO_STATES.has(scenario.status)) return true;
  return queue.some((item) => item.scenario_id === scenario.scenario_id && ACTIVE_QUEUE_STATES.has(item.status));
}

/**
 * Editing is a property of the current lifecycle, not of whether the scenario
 * has ever run. Historical snapshots remain immutable while a new draft can be
 * created from them on the first save.
 */
export function canEditScenario(scenario: Scenario | null | undefined, queue: QueueItem[] = []): boolean {
  if (!scenario || scenario.archived || scenario.status === "archived") return false;
  // Legacy scenarios have no structured template/baseline to safely derive a draft from.
  if (!scenario.parameter_template_id) return false;
  return !scenarioHasActiveComputation(scenario, queue);
}

export function hasHistoricalSnapshot(scenario: Scenario | null | undefined): boolean {
  if (!scenario) return false;
  return Boolean(scenario.latest_simulation_id || scenario.input_revision_id);
}
