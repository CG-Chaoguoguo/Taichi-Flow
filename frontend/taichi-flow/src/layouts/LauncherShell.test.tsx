import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { LauncherShell } from "./LauncherShell";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";

function renderLauncher(path = "/projects") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<LauncherShell />}>
          <Route path="projects" element={<div>项目页</div>} />
          <Route path="settings" element={<div>设置页</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("LauncherShell", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      activeProject: null,
      activeProjectId: null,
      toasts: [],
      serviceOnline: true,
      theme: "dark",
    });
  });

  it("renders launcher chrome without workspace navigation entries", () => {
    renderLauncher();
    expect(screen.getByText("启动器")).toBeInTheDocument();
    expect(screen.getByText("项目页")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "方案" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "计算" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "队列" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "导出" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "设置" })).toBeInTheDocument();
  });

  it("navigates to settings from the launcher topbar", () => {
    renderLauncher();
    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    expect(screen.getByText("设置页")).toBeInTheDocument();
  });
});
