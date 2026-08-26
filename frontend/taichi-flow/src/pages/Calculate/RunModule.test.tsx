import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ComputePolicyResolution, Scenario } from "../../types";
import { RunModule } from "./RunModule";

const scenario: Scenario = {
  scenario_id: "scenario-run",
  project_id: "project-run",
  name: "运行方案",
  input_revision_id: "rev-1",
  parameter_template_id: "pt-bj-hxl-v3",
  parameter_baseline: {},
  parameter_patch: {},
  effective_parameters: {},
  input_bindings: [],
  status: "ready",
  progress: 0,
  latest_simulation_id: null,
  result_family_count: 0,
  file_count: 0,
  created_at: "2026-08-09T00:00:00Z",
  updated_at: "2026-08-09T00:00:00Z",
};

const disabledResolution: ComputePolicyResolution = {
  status: "resolved",
  source: "auto",
  requested: "auto",
  detected: { simulate_shallow_landslide: false, dfs_failure_source_variant: "precomputed_unsfin_schedule", evidence: [] },
  effective: { mode: "disabled", simulate_shallow_landslide: false, configured_variant: "precomputed_unsfin_schedule", active_variant: null },
  numeric_variants: {},
  settings_snapshot: {},
  warnings: [],
  resolution_id: "cpr-test",
  resolution_hash: "test",
};

describe("RunModule runtime profile", () => {
  const enqueueScenario = vi.fn(async () => undefined);

  beforeEach(() => {
    enqueueScenario.mockClear();
    useTaichiFlowStore.setState({
      queue: [],
      metrics: { cpu_percent: 1, gpu_percent: 2, gpu_name: "test" },
      enqueueScenario,
      cancelQueueItem: vi.fn(),
      stopRunningItem: vi.fn(),
      retryQueueItem: vi.fn(),
      activeProject: {
        project_id: "project-run",
        name: "run",
        description: "",
        root_path: "C:\\tmp",
        created_at: "2026-08-09T00:00:00Z",
        updated_at: "2026-08-09T00:00:00Z",
      },
      parameterCatalog: {
        catalog_version: "taichi-flow-parameter-catalog-v3",
        editable_statuses: [],
        parameters: [],
        status_counts: {},
        runtime_profiles: {
          user_selectable: [
            { name: "cuda_production_default", label_zh: "CUDA 加速" },
            { name: "compat_default_off", label_zh: "CPU 兼容" },
          ],
        },
      },
      fetchParameterCatalog: vi.fn(async () => undefined),
      scenarioConfigurations: {
        "scenario-run": {
          scenario_id: "scenario-run",
          baseline: {},
          overrides: {},
          effective: {},
          bindings: [],
          validation: { valid: true, errors: [], warnings: [], issues: [] },
          compute_policy_resolution: disabledResolution,
          version: 1,
        },
      },
      fetchScenarioConfiguration: vi.fn(async () => ({
        scenario_id: "scenario-run",
        baseline: {},
        overrides: {},
        effective: {},
        bindings: [],
        validation: { valid: true, errors: [], warnings: [], issues: [] },
        compute_policy_resolution: disabledResolution,
        version: 1,
      })),
    });
  });

  it("passes the selected CPU runtime profile when enqueueing", async () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );

    const select = screen.getByTestId("run-runtime-profile") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "compat_default_off" } });
    fireEvent.click(screen.getByRole("button", { name: "加入模拟队列" }));

    expect(enqueueScenario).toHaveBeenCalledWith("scenario-run", "compat_default_off");
  });

  it("shows a read-only failure-source policy summary", () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("failure-source-policy-summary")).toHaveTextContent("自动 → 关闭浅层失稳");
  });
});
