import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, it, expect, vi } from "vitest";
import { ProjectActions } from "./ProjectActions";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { ProjectInfo } from "../types";

const project = { project_id: "p", name: "Test", root_path: "C:/isolated/test" } as ProjectInfo;
const preview = { project_id: "p", name: "Test", root_path: project.root_path, scenario_count: 2, run_count: 1, blocked_reasons: [], allowed: true, retry: false, confirmation_token: "bound-token" };
beforeEach(() => useTaichiFlowStore.setState({
  previewProjectDelete: vi.fn(async (_id, mode) => ({ ...preview, mode })),
  deleteProject: vi.fn(async () => undefined),
}));

it("opens with focus, navigates with arrows and restores focus on Escape without opening the card", () => {
  const card = vi.fn();
  render(<div onClick={card}><ProjectActions project={project} onChanged={vi.fn()} /></div>);
  const trigger = screen.getByRole("button", { name: "项目操作：Test" });
  fireEvent.click(trigger);
  expect(screen.getByRole("menuitem", { name: "从列表移除" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
  expect(screen.getByRole("menuitem", { name: "彻底删除项目" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  expect(trigger).toHaveFocus();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(card).not.toHaveBeenCalled();
});

it("shows a short confirmation without a name input and allows cancellation", async () => {
  render(<ProjectActions project={project} onChanged={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "项目操作：Test" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "彻底删除项目" }));
  const button = await screen.findByRole("button", { name: "确认" });
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByText(project.root_path)).not.toBeInTheDocument();
  expect(within(screen.getByRole("dialog")).getAllByRole("button")).toHaveLength(2);
  expect(button).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(useTaichiFlowStore.getState().deleteProject).not.toHaveBeenCalled();
});

it("leaves failed removal visible and offers revalidation", async () => {
  useTaichiFlowStore.setState({ deleteProject: vi.fn().mockRejectedValue(new Error("项目有运行任务")) });
  render(<ProjectActions project={project} onChanged={vi.fn(async () => undefined)} />);
  fireEvent.click(screen.getByRole("button", { name: "项目操作：Test" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "从列表移除" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("项目有运行任务");
  expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
});

it("confirms permanent deletion without requiring typing", async () => {
  render(<ProjectActions project={project} onChanged={vi.fn(async () => undefined)} />);
  fireEvent.click(screen.getByRole("button", { name: "项目操作：Test" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "彻底删除项目" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认" }));
  expect(useTaichiFlowStore.getState().deleteProject).toHaveBeenCalledWith({ ...preview, mode: "permanent" }, "Test");
});
