import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ComputePolicyResolution, QueueItem, Scenario } from "../../types";
import { InspectorPanel } from "./InspectorPanel";

vi.mock("../../components/layout/ResizablePaneGroup", () => ({
  ResizablePaneGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ResizablePane: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ResizeHandle: () => <div />,
  CollapsedPaneRail: () => null,
  PanelCollapseButton: () => null,
}));

const resolution: ComputePolicyResolution = {
  status: "resolved",
  source: "auto",
  requested: "auto",
  detected: { simulate_shallow_landslide: false, dfs_failure_source_variant: "precomputed_unsfin_schedule", evidence: [] },
  effective: { mode: "disabled", simulate_shallow_landslide: false, configured_variant: "precomputed_unsfin_schedule", active_variant: null },
  numeric_variants: {},
  settings_snapshot: {},
  warnings: [],
  resolution_id: "cpr-inspector",
  resolution_hash: "inspector",
};

const failedScenario: Scenario = {
  scenario_id: "scenario-failed",
  project_id: "project-inspector",
  name: "失败的资格运行",
  input_revision_id: "rev-1",
  parameter_template_id: "pt-reference-v1",
  parameter_baseline: {},
  parameter_patch: {},
  effective_parameters: {},
  input_bindings: [],
  binding_state: "runtime_snapshot",
  status: "failed",
  progress: 0,
  latest_simulation_id: "sim-failed",
  result_family_count: 0,
  file_count: 0,
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
};

const failedQueueItem: QueueItem = {
  queue_item_id: "queue-failed",
  project_id: "project-inspector",
  scenario_id: "scenario-failed",
  scenario_name: "失败的资格运行",
  position: 1,
  status: "failed",
  simulation_id: "sim-failed",
  effective_config: {},
  compute_policy_resolution: resolution,
  enqueued_at: "2026-08-31T00:00:00Z",
  started_at: "2026-08-31T00:00:00Z",
  finished_at: "2026-08-31T00:00:01Z",
  progress: 0,
  summary: "failed",
};

describe("InspectorPanel failed-run controls", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      editorSelection: { kind: "scenario", scenarioId: "scenario-failed" },
      scenarios: [failedScenario],
      queue: [failedQueueItem],
      inputFiles: [],
      activeProject: null,
      parameterCatalog: {
        catalog_version: "test",
        editable_statuses: [],
        parameters: [],
        status_counts: {},
      },
      scenarioConfigurations: {
        "scenario-failed": {
          scenario_id: "scenario-failed",
          baseline: {},
          overrides: {},
          effective: {},
          bindings: [],
          validation: { valid: true, errors: [], warnings: [], issues: [] },
          compute_policy_resolution: resolution,
          version: 1,
        },
      },
      fetchParameterCatalog: vi.fn(async () => undefined),
      fetchScenarioConfiguration: vi.fn(async () => ({
        scenario_id: "scenario-failed",
        baseline: {},
        overrides: {},
        effective: {},
        bindings: [],
        validation: { valid: true, errors: [], warnings: [], issues: [] },
        compute_policy_resolution: resolution,
        version: 1,
      })),
      retryQueueItem: vi.fn(async () => undefined),
      setDockTab: vi.fn(),
      addToast: vi.fn(),
    });
  });

  it("keeps failed scenarios read-only for edits but exposes the run retry action", () => {
    render(
      <MemoryRouter>
        <InspectorPanel
          scenarioId="scenario-failed"
          onFocusLayer={vi.fn()}
          draftPatch={{}}
          draftBindings={[]}
          draftControls={{}}
          dirty={false}
          saving={false}
          onDraftChange={vi.fn()}
          onBindingsChange={vi.fn()}
          onControlsChange={vi.fn()}
          onSave={vi.fn(async () => undefined)}
          onOpenRainfall={vi.fn()}
          onOpenZoneSoil={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "运行" }));

    expect(screen.getByRole("button", { name: "重新加入队列" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
  });
});
