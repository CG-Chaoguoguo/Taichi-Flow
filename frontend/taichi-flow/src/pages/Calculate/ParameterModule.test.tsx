import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ParameterCatalog, Scenario } from "../../types";
import { ParameterModule } from "./ParameterModule";

const catalog: ParameterCatalog = {
  catalog_version: "taichi-flow-parameter-catalog-v3",
  editable_statuses: ["production_consumed", "config_fallback_consumed"],
  status_counts: { production_consumed: 1 },
  control_registry: {
    registry_version: "1.0.0",
    entry_count: 1,
    editable_count: 1,
    restricted_count: 0,
  },
  parameters: [
    {
      key: "edda.run_controls.simulate_rainfall",
      control_key: "simulate_rainfall",
      control_family: "edda",
      source_index: 23,
      label: "Simulate Rainfall",
      label_zh: "模拟降雨",
      description_zh: "控制降雨源项。",
      group: "compute_process",
      runtime_status: "production_consumed",
      status_label_zh: "生产已闭环",
      editable: true,
      frontend_policy: "editable",
      value_type: "boolean",
      dependencies: [],
      dependency_paths: [],
    },
  ],
};

const scenario: Scenario = {
  scenario_id: "scenario-controls",
  project_id: "project-controls",
  name: "控制方案",
  input_revision_id: null,
  parameter_template_id: "pt-bj-hxl-v3",
  parameter_baseline: {
    "edda.registry_version": "1.0.0",
    "edda.run_controls.simulate_rainfall": true,
  },
  parameter_patch: {},
  effective_parameters: {
    "edda.registry_version": "1.0.0",
    "edda.run_controls.simulate_rainfall": true,
  },
  input_bindings: [],
  status: "draft",
  progress: 0,
  latest_simulation_id: null,
  result_family_count: 0,
  file_count: 0,
  created_at: "2026-08-09T00:00:00Z",
  updated_at: "2026-08-09T00:00:00Z",
};

describe("ParameterModule compute controls integration", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      parameterCatalog: catalog,
      inputFiles: [],
      activeProject: null,
    });
  });

  it("places canonical compute controls first and shares the scenario draft", () => {
    const onDraftChange = vi.fn();
    const { container } = render(
      <ParameterModule
        scenario={scenario}
        draftPatch={{}}
        draftBindings={[]}
        onDraftChange={onDraftChange}
      />,
    );

    const compute = screen.getByTestId("edda-compute-controls");
    const rainfall = container.querySelector(".tf-rainfall-summary-card");
    expect(rainfall).not.toBeNull();
    expect(compute.compareDocumentPosition(rainfall as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("switch", { name: "模拟降雨" })).toHaveAttribute("aria-checked", "true");
  });
});
