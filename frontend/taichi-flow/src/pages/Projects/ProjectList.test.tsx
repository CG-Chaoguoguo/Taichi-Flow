import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { systemApi } from "../../api/taichiFlowAdapter";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { ProjectList } from "./ProjectList";

const createdProject = {
  project_id: "project-1",
  name: "山区洪水",
  description: "",
  root_path: "C:\\Projects\\mountain-flood",
  created_at: "2026-08-02T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
};

describe("ProjectList directory selection", () => {
  const fetchProjectList = vi.fn(async () => []);
  const createProject = vi.fn(async () => createdProject);

  beforeEach(() => {
    window.taichiFlowDesktop = undefined;
    fetchProjectList.mockClear();
    createProject.mockClear();
    useTaichiFlowStore.setState({
      activeProject: null,
      activeProjectId: null,
      projectHistory: [],
      toasts: [],
      fetchProjectList,
      createProject,
    });
  });

  afterEach(() => {
    window.taichiFlowDesktop = undefined;
  });

  it("browses a local folder, fills the required path, and creates the project", async () => {
    vi.spyOn(systemApi, "directories").mockImplementation(async (path?: string) => {
      if (!path) {
        return {
          current_path: null,
          parent_path: null,
          roots: [{ name: "C:", path: "C:\\Projects", writable: true }],
          directories: [],
          can_select: false,
        };
      }
      return {
        current_path: "C:\\Projects",
        parent_path: null,
        roots: [{ name: "C:", path: "C:\\Projects", writable: true }],
        directories: [{ name: "mountain-flood", path: "C:\\Projects\\mountain-flood", writable: true }],
        can_select: true,
      };
    });

    render(<MemoryRouter><ProjectList /></MemoryRouter>);
    fireEvent.click(screen.getAllByRole("button", { name: "新建项目" })[0]);

    expect(screen.getByText("项目名称为必填项")).toBeInTheDocument();
    expect(screen.getByText("请选择或输入本地根目录")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("项目名称（必填）"), { target: { value: "山区洪水" } });
    fireEvent.click(screen.getByRole("button", { name: "选择目录" }));

    const directoryDialog = await screen.findByRole("dialog", { name: "选择本机目录" });
    fireEvent.click(within(directoryDialog).getByRole("button", { name: "C:" }));
    await waitFor(() => expect(within(directoryDialog).getByText("C:\\Projects")).toBeInTheDocument());
    fireEvent.click(within(directoryDialog).getByRole("button", { name: "选择此文件夹" }));

    expect(screen.getByLabelText("本地根目录（必填）")).toHaveValue("C:\\Projects");
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(createProject).toHaveBeenCalledWith("山区洪水", "C:\\Projects"));
  });

  it("uses the Electron native picker without opening the browser directory dialog", async () => {
    const selectDirectory = vi.fn(async () => ({ canceled: false, path: "D:\\Research\\case-a" }));
    window.taichiFlowDesktop = { selectDirectory };

    render(<MemoryRouter><ProjectList /></MemoryRouter>);
    fireEvent.click(screen.getAllByRole("button", { name: "新建项目" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "选择目录" }));

    await waitFor(() => expect(selectDirectory).toHaveBeenCalledWith({ defaultPath: undefined }));
    expect(screen.queryByRole("dialog", { name: "选择本机目录" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("本地根目录（必填）")).toHaveValue("D:\\Research\\case-a"));
  });
});
