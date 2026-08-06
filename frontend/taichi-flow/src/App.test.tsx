import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { EditorRouteGuard } from "./App";
import { useTaichiFlowStore } from "./stores/taichiFlowStore";

function renderGuard(projectId = "project-1") {
  return render(
    <MemoryRouter initialEntries={[`/editor/${projectId}/scenarios/scn-1`]}>
      <Routes>
        <Route path="/projects" element={<div>项目列表</div>} />
        <Route path="/launch/:projectId" element={<div>启动页</div>} />
        <Route
          path="/editor/:projectId/scenarios/:scenarioId"
          element={
            <EditorRouteGuard>
              <div>编辑器页面</div>
            </EditorRouteGuard>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("EditorRouteGuard", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({ activeProject: null, activeProjectId: null });
  });

  it("redirects to projects when no project context exists", async () => {
    renderGuard();
    expect(await screen.findByText("项目列表")).toBeInTheDocument();
    expect(screen.queryByText("编辑器页面")).not.toBeInTheDocument();
  });

  it("redirects to launch when a persisted project id needs reopening", async () => {
    useTaichiFlowStore.setState({
      activeProject: null,
      activeProjectId: "project-1",
      fetchProjectList: async () => [],
    });
    renderGuard();
    expect(await screen.findByText("启动页")).toBeInTheDocument();
  });

  it("allows the matching active project", () => {
    useTaichiFlowStore.setState({
      activeProject: {
        project_id: "project-1",
        name: "测试项目",
        description: "",
        root_path: "C:\\Projects\\test",
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      },
      activeProjectId: "project-1",
    });
    renderGuard();
    expect(screen.getByText("编辑器页面")).toBeInTheDocument();
  });
});
