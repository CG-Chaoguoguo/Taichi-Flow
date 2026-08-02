import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";

function renderShell(path = "/projects") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="projects/*" element={<div>项目页</div>} />
          <Route path="settings" element={<div>设置页</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell project-aware navigation", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({ activeProject: null, activeProjectId: null, toasts: [] });
  });

  it("disables project-scoped navigation and keeps projects and settings available", () => {
    renderShell();

    for (const label of ["方案", "计算", "队列", "导出"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "项目" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "设置" })).toBeEnabled();
    expect(screen.getByTestId("sidebar-footer")).toContainElement(screen.getByRole("button", { name: "设置" }));
    expect(screen.getByTestId("sidebar-footer")).toContainElement(screen.getByRole("button", { name: "折叠导航" }));
  });

  it("enables project navigation, highlights the exact nested route, and preserves footer controls when collapsed", () => {
    useTaichiFlowStore.setState({
      activeProject: {
        project_id: "project-1",
        name: "测试项目",
        description: "",
        root_path: "C:\\Projects\\a-very-long-project-root-that-must-not-wrap-inside-the-header",
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      },
      activeProjectId: "project-1",
    });

    renderShell("/projects/project-1/queue");
    for (const label of ["方案", "计算", "队列", "导出"]) {
      expect(screen.getByRole("button", { name: label })).toBeEnabled();
    }
    expect(screen.getByRole("button", { name: "队列" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "项目" })).not.toHaveAttribute("aria-current");
    expect(screen.getByTitle("C:\\Projects\\a-very-long-project-root-that-must-not-wrap-inside-the-header")).toHaveStyle({ whiteSpace: "nowrap", overflow: "hidden" });

    fireEvent.click(screen.getByRole("button", { name: "折叠导航" }));
    expect(screen.getByRole("button", { name: "展开导航" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "设置" })).toBeInTheDocument();
  });
});
