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
    {
      key: "hydrology.dfs_face_flux_variant",
      label: "DFS face-flux variant",
      label_zh: "面通量平均变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["both_thin_weighted"],
    },
    {
      key: "time.dt_max",
      label: "Max dt",
      label_zh: "最大时间步",
      group: "time",
      runtime_status: "production_consumed",
      editable: true,
    },
    {
      key: "soil.c",
      label: "Cohesion",
      label_zh: "黏聚力",
      group: "soil",
      runtime_status: "production_consumed",
      editable: true,
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
    "time.dt_max": 2,
    "soil.c": 10000,
    "spatial_zones.zones": {
      "1": { zone_id: 1, phi: 42, K_sat_top: 8e-6, K_sat_bottom: 2e-7, cvero: 0.6 },
      "2": { zone_id: 2, phi: 20, K_sat_top: 4e-6, K_sat_bottom: 9e-7, cvero: 0.3 },
    },
  },
  parameter_patch: {},
  effective_parameters: {
    "edda.registry_version": "1.0.0",
    "edda.run_controls.simulate_rainfall": true,
    "time.dt_max": 2,
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

  it("keeps scientific parameters and hides compute gates and rainfall summary", () => {
    const onDraftChange = vi.fn();
    const { container } = render(
      <ParameterModule
        scenario={scenario}
        draftPatch={{}}
        draftBindings={[]}
        onDraftChange={onDraftChange}
      />,
    );

    expect(screen.queryByTestId("edda-compute-controls")).toBeNull();
    expect(container.querySelector(".tf-rainfall-summary-card")).toBeNull();
    expect(screen.queryByText("面通量平均变种")).toBeNull();
    expect(screen.queryByText("干面速度清零变种")).toBeNull();
    expect(screen.queryByText("人工黏性权重变种")).toBeNull();
    expect(screen.queryByText("侵蚀速度模变种")).toBeNull();
    expect(screen.getByText("最大时间步")).toBeInTheDocument();
  });

  it("shows the zone soil editor and locks global cohesion when multiple zones exist", () => {
    const onDraftChange = vi.fn();
    const { container } = render(
      <ParameterModule
        scenario={scenario}
        draftPatch={{}}
        draftBindings={[]}
        onDraftChange={onDraftChange}
      />,
    );
    expect(screen.getByTestId("zone-soil-summary")).toBeInTheDocument();
    expect(screen.getByText("分区双层土参数")).toBeInTheDocument();
    expect(screen.queryByTestId("zone-soil-workspace")).toBeNull();
    const cohesion = container.querySelector('[data-parameter-key="soil.c"]');
    expect(cohesion?.textContent).toMatch(/只读/);
  });
});
