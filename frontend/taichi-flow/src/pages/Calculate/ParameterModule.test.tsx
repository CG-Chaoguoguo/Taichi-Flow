import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ParameterCatalog, Scenario } from "../../types";
import { ParameterModule } from "./ParameterModule";

const scenario: Scenario = {
  scenario_id: "scenario-parameter-test",
  project_id: "project-1",
  name: "参数检视器测试",
  input_revision_id: null,
  parameter_template_id: "template-1",
  parameter_baseline: {
    "time.t_end": 7200,
    "hydrology.rho_w": 1000,
    "soil.alpha": 0.5,
    "rainfall.periods": [{ period_id: "period-0001", index: 1, start_s: 0, end_s: 7200, source: "uniform", cri_mps: 0 }],
  },
  parameter_patch: {},
  effective_parameters: {},
  input_bindings: [],
  version: 1,
  status: "draft",
  progress: 0,
  latest_simulation_id: null,
  result_family_count: 0,
  file_count: 0,
  created_at: "",
  updated_at: "",
};

const catalog: ParameterCatalog = {
  catalog_version: "test",
  editable_statuses: ["production_consumed"],
  status_counts: { production_consumed: 3 },
  parameters: [
    { key: "time.t_end", label: "simulation end", label_zh: "模拟结束时间", abbrev: "t_end", group: "time", runtime_status: "production_consumed", editable: true },
    { key: "hydrology.rho_w", label: "water density", label_zh: "水密度", abbrev: "rho_w", group: "hydrology", runtime_status: "production_consumed", editable: true },
    { key: "soil.alpha", label: "soil parameter", label_zh: "土壤参数", abbrev: "alpha", group: "soil", runtime_status: "production_consumed", editable: true },
  ],
};

describe("ParameterModule grouped inspector", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      activeProject: { project_id: "project-1", name: "P", description: "", root_path: "C:/P", created_at: "", updated_at: "" },
      activeProjectId: "project-1",
      parameterCatalog: catalog,
      parameterTemplates: [],
      inputFiles: [],
      loading: { parameters: false },
      errors: {},
      fetchParameterCatalog: vi.fn(async () => undefined),
      fetchParameterTemplates: vi.fn(async () => undefined),
      fetchScenarios: vi.fn(async () => undefined),
      fetchScenarioConfiguration: vi.fn(async () => null),
      addToast: vi.fn(),
    });
  });

  it("keeps normal field geometry, auto-opens time and issue groups, and supports search", () => {
    render(
      <ParameterModule
        scenario={scenario}
        draftPatch={{ "time.t_end": 9000 }}
        onDraftChange={() => undefined}
        validation={{
          valid: false,
          errors: ["水密度不一致"],
          warnings: [],
          issues: [{ code: "hydrology_issue", severity: "error", message: "水密度不一致", parameter_key: "hydrology.rho_w" }],
        }}
      />,
    );

    expect(screen.getByTestId("parameter-module")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /时间.*1 项.*已改 1/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /水文.*1 项.*问题 1/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /土体.*1 项/ })).toHaveAttribute("aria-expanded", "false");

    const soilGroup = screen.getByTestId("parameter-group-soil");
    expect(soilGroup.querySelector("[hidden]")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /土体.*1 项/ }));
    expect(screen.getByRole("button", { name: /土体.*1 项/ })).toHaveAttribute("aria-expanded", "true");
    expect(soilGroup.querySelector("[hidden]")).toBeNull();

    fireEvent.change(screen.getByPlaceholderText(/搜索中文名/), { target: { value: "土壤" } });
    expect(screen.queryByTestId("parameter-group-time")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /土体.*1 项/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("土壤参数（alpha）")).toBeInTheDocument();
  });

  it("shows an actionable error state when the catalog cannot load", () => {
    const retry = vi.fn(async () => undefined);
    useTaichiFlowStore.setState({ parameterCatalog: null, loading: { parameters: false }, errors: { parameters: "服务暂时不可用" }, fetchParameterCatalog: retry });
    render(
      <ParameterModule
        scenario={scenario}
        draftPatch={{}}
        onDraftChange={() => undefined}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("服务暂时不可用");
    retry.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
