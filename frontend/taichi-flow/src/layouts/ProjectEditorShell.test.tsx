import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ProjectEditorShell } from "./ProjectEditorShell";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";

describe("ProjectEditorShell", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      activeProject: {
        project_id: "project-1",
        name: "测试项目",
        description: "",
        root_path: "C:\\Projects\\editor-test",
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      },
      activeProjectId: "project-1",
      scenarios: [{
        scenario_id: "scenario-1",
        project_id: "project-1",
        name: "很长但必须保持单行的验收方案名称",
        input_revision_id: null,
        parameter_patch: {},
        effective_parameters: {},
        status: "draft",
        progress: 0,
        latest_simulation_id: null,
        result_family_count: 0,
        file_count: 0,
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      }],
      editorSelection: { kind: "scenario", scenarioId: "scenario-1" },
      toasts: [],
      serviceOnline: true,
      theme: "dark",
      canvasPreviewMode: "downsample",
      metrics: { cpu_percent: 10, gpu_percent: 5, gpu_name: null },
      setCanvasPreviewMode: () => undefined,
      addToast: () => undefined,
      closeProject: () => {
        useTaichiFlowStore.setState({ activeProject: null, activeProjectId: null });
      },
    });
  });

  it("shows project context and returns to launcher", () => {
    render(
      <MemoryRouter initialEntries={["/editor/project-1"]}>
        <Routes>
          <Route path="/editor/:projectId" element={<ProjectEditorShell />}>
            <Route index element={<div>编辑器内容</div>} />
          </Route>
          <Route path="/projects" element={<div>启动器项目页</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("测试项目")).toBeInTheDocument();
    expect(screen.getByTitle("C:\\Projects\\editor-test")).toBeInTheDocument();
    expect(screen.getByTitle("方案：很长但必须保持单行的验收方案名称")).toHaveClass("tf-editor-scenario-chip");
    expect(screen.getByText("编辑器内容")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /返回启动器/ }));
    expect(screen.getByText("启动器项目页")).toBeInTheDocument();
  });
});
