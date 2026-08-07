import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScenarioOutliner } from "./ScenarioOutliner";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";

describe("ScenarioOutliner create dialog", () => {
  const createScenario = vi.fn(async (name: string) => ({
    scenario_id: "sc-new",
    project_id: "p1",
    name,
    input_revision_id: null,
    parameter_template_id: "pt-bj-hxl-v1",
    parameter_baseline: {},
    parameter_patch: {},
    effective_parameters: {},
    input_bindings: [],
    version: 1,
    status: "draft" as const,
    progress: 0,
    latest_simulation_id: null,
    result_family_count: 0,
    file_count: 0,
    created_at: "2026-08-02T00:00:00Z",
    updated_at: "2026-08-02T00:00:00Z",
  }));

  beforeEach(() => {
    createScenario.mockClear();
    useTaichiFlowStore.setState({
      scenarios: [],
      queue: [],
      editorSelection: { kind: "scenario", scenarioId: "sc-1" },
      setEditorSelection: vi.fn(),
      createScenario,
      duplicateScenario: vi.fn(),
      deleteScenario: vi.fn(),
      addToast: vi.fn(),
    });
  });

  it("opens a naming dialog and creates with the typed name", async () => {
    const onSelectScenario = vi.fn();
    render(<ScenarioOutliner onSelectScenario={onSelectScenario} />);

    fireEvent.click(screen.getByRole("button", { name: "新建方案" }));
    expect(screen.getByRole("dialog", { name: "新建方案" })).toBeInTheDocument();

    const input = screen.getByLabelText("方案名称");
    fireEvent.change(input, { target: { value: "高摩阻方案" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(createScenario).toHaveBeenCalledWith("高摩阻方案"));
    await waitFor(() => expect(onSelectScenario).toHaveBeenCalledWith("sc-new"));
  });

  it("does not render the redundant project input family picker", () => {
    render(<ScenarioOutliner onSelectScenario={() => undefined} />);
    expect(screen.queryByLabelText("输入文件族")).not.toBeInTheDocument();
    expect(screen.queryByText("项目输入")).not.toBeInTheDocument();
    expect(screen.getByText("方案")).toBeInTheDocument();
  });

  it("opens the archive manager and restores a scenario", async () => {
    const archived = {
      scenario_id: "sc-archived",
      project_id: "p1",
      name: "历史方案",
      input_revision_id: null,
      parameter_template_id: "pt-bj-hxl-v1",
      parameter_baseline: {},
      parameter_patch: {},
      effective_parameters: {},
      input_bindings: [],
      version: 1,
      status: "archived" as const,
      archived: true,
      progress: 100,
      latest_simulation_id: "sim-1",
      result_family_count: 1,
      file_count: 2,
      created_at: "2026-08-02T00:00:00Z",
      updated_at: "2026-08-02T00:00:00Z",
    };
    const restoreScenario = vi.fn(async () => ({ ...archived, status: "completed" as const, archived: false }));
    const onSelectScenario = vi.fn();
    useTaichiFlowStore.setState({ scenarios: [archived], restoreScenario });

    render(<ScenarioOutliner onSelectScenario={onSelectScenario} />);
    fireEvent.click(screen.getByRole("button", { name: "查看归档方案（1）" }));
    expect(screen.getByRole("dialog", { name: "归档方案" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(restoreScenario).toHaveBeenCalledWith("sc-archived"));
    await waitFor(() => expect(onSelectScenario).toHaveBeenCalledWith("sc-archived"));
  });
});
