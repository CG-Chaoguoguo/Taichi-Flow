import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RasterViewportProvider } from "../../contexts/RasterViewportContext";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { Scenario } from "../../types";
import { InspectorPanel } from "./InspectorPanel";

const scenario: Scenario = {
  scenario_id: "scn-1",
  project_id: "tf-1",
  name: "结构化方案",
  input_revision_id: null,
  parameter_template_id: "pt-bj-hxl-v1",
  parameter_baseline: {
    "time.t_end": 7200,
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
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
};

describe("InspectorPanel structured scenario flow", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      activeProject: { project_id: "tf-1", name: "P", description: "", root_path: "C:/P", created_at: "", updated_at: "" },
      activeProjectId: "tf-1",
      scenarios: [scenario],
      queue: [],
      inputFiles: [],
      editorSelection: { kind: "scenario", scenarioId: scenario.scenario_id },
      parameterCatalog: { catalog_version: "1", editable_statuses: [], status_counts: {}, parameters: [] },
      scenarioConfigurations: {
        [scenario.scenario_id]: {
          scenario_id: scenario.scenario_id,
          parameter_template_id: scenario.parameter_template_id,
          baseline: scenario.parameter_baseline || {},
          overrides: {},
          effective: {},
          bindings: [],
          validation: { valid: false, errors: ["缺少 DEM"], warnings: [] },
          version: 1,
        },
      },
      fetchParameterCatalog: vi.fn(async () => undefined),
      fetchScenarios: vi.fn(async () => undefined),
      fetchInputFiles: vi.fn(async () => undefined),
      fetchParameterTemplates: vi.fn(async () => undefined),
      addToast: vi.fn(),
    });
  });

  it("has one save action and three compact inspector tabs", () => {
    const onSave = vi.fn(async () => undefined);
    render(
      <InspectorPanel
        scenarioId={scenario.scenario_id}
        onFocusLayer={() => undefined}
        draftPatch={{}}
        draftBindings={[]}
        dirty
        saving={false}
        onDraftChange={() => undefined}
        onBindingsChange={() => undefined}
        onSave={onSave}
        onOpenRainfall={() => undefined}
      />,
    );
    expect(screen.getAllByRole("button", { name: "保存方案" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "参数" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "输入绑定" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存方案" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("uses the full inspector height for scenario parameters instead of a raster details split", () => {
    render(
      <InspectorPanel
        scenarioId={scenario.scenario_id}
        onFocusLayer={() => undefined}
        draftPatch={{}}
        draftBindings={[]}
        dirty={false}
        saving={false}
        onDraftChange={() => undefined}
        onBindingsChange={() => undefined}
        onSave={async () => undefined}
        onOpenRainfall={() => undefined}
      />,
    );
    expect(screen.getByTestId("parameter-module")).toBeInTheDocument();
    expect(screen.queryByLabelText("图层数据")).not.toBeInTheDocument();
  });

  it("shows explicit binding controls and validation instead of legacy paths", () => {
    render(
      <InspectorPanel
        scenarioId={scenario.scenario_id}
        onFocusLayer={() => undefined}
        draftPatch={{}}
        draftBindings={[]}
        dirty={false}
        saving={false}
        onDraftChange={() => undefined}
        onBindingsChange={() => undefined}
        onSave={async () => undefined}
        onOpenRainfall={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "输入绑定" }));
    expect(screen.getByRole("button", { name: "选择主 DEM 资产" })).toBeInTheDocument();
    expect(screen.getByText("缺少 DEM")).toBeInTheDocument();
    expect(screen.queryByText(/edda_in.*路径/)).not.toBeInTheDocument();
  });

  it("shows asset library and details panes in input selection mode", () => {
    useTaichiFlowStore.setState({
      editorSelection: { kind: "input", family: "dem" },
      inputFiles: [{
        file_id: "file-dem",
        family: "dem",
        name: "bcdem.asc",
        status: "ready",
        size: 1024,
        updated_at: "2026-08-02T00:00:00Z",
      }],
      layerVisibility: { "file-dem": true },
      layerOrder: ["file-dem"],
    });
    render(
      <RasterViewportProvider>
        <InspectorPanel
          scenarioId={scenario.scenario_id}
          focusedAssetId={null}
          onFocusLayer={() => undefined}
          draftPatch={{}}
          draftBindings={[]}
          dirty={false}
          saving={false}
          onDraftChange={() => undefined}
          onBindingsChange={() => undefined}
          onSave={async () => undefined}
          onOpenRainfall={() => undefined}
        />
      </RasterViewportProvider>,
    );
    expect(screen.getByLabelText("属性检视")).toBeInTheDocument();
    expect(screen.getByLabelText("图层数据")).toBeInTheDocument();
    expect(screen.getByText("数据")).toBeInTheDocument();
    expect(screen.getByText("选择资产或点击地图识别像元")).toBeInTheDocument();
    expect(screen.getByText("bcdem.asc")).toBeInTheDocument();
  });

  it("keeps unmigrated legacy parameters read-only and routes to the migration wizard", () => {
    const legacyScenario = { ...scenario, parameter_template_id: null };
    useTaichiFlowStore.setState({
      scenarios: [legacyScenario],
      editorSelection: { kind: "scenario", scenarioId: legacyScenario.scenario_id },
    });
    render(
      <InspectorPanel
        scenarioId={legacyScenario.scenario_id}
        onFocusLayer={() => undefined}
        draftPatch={{}}
        draftBindings={[]}
        dirty={false}
        saving={false}
        onDraftChange={() => undefined}
        onBindingsChange={() => undefined}
        onSave={async () => undefined}
        onOpenRainfall={() => undefined}
      />,
    );
    expect(screen.getByText("历史方案参数只读")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "在中央工作区编辑降雨过程" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "前往迁移向导" }));
    expect(screen.getByRole("button", { name: "生成迁移预览" })).toBeInTheDocument();
  });
});
