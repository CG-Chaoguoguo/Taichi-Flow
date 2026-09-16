import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, useNavigate } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { UnsavedChangesGuard } from "./UnsavedChangesGuard";
import { normalizeTheme, readStoredTheme } from "../themePreference";

function mount(save = vi.fn(async () => undefined)) {
  function Editor() {
    const navigate = useNavigate();
    return <><UnsavedChangesGuard dirty save={save} /><button onClick={() => navigate("/next")}>离开</button></>;
  }
  const router = createMemoryRouter([{ path: "/", element: <Editor /> }, { path: "/next", element: <p>目标页面</p> }]);
  render(<RouterProvider router={router} />);
  fireEvent.click(screen.getByText("离开"));
  return save;
}

describe("unsaved navigation", () => {
  it("cancels without losing the editor", async () => {
    const save = mount();
    fireEvent.click(await screen.findByText("取消"));
    expect(screen.getByText("离开")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
  it("discards without saving", async () => {
    const save = mount();
    fireEvent.click(await screen.findByText("放弃修改"));
    expect(await screen.findByText("目标页面")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
  it("saves before proceeding", async () => {
    const save = mount();
    fireEvent.click(await screen.findByText("保存并继续"));
    expect(await screen.findByText("目标页面")).toBeInTheDocument();
    expect(save).toHaveBeenCalledOnce();
  });
  it("keeps the editor and error on a failed save", async () => {
    mount(vi.fn().mockRejectedValue(new Error("版本冲突")));
    fireEvent.click(await screen.findByText("保存并继续"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("版本冲突"));
    expect(screen.queryByText("目标页面")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("取消"));
    expect(screen.getByText("离开")).toBeInTheDocument();
  });
});

it("migrates obsolete and invalid themes consistently", () => {
  for (const theme of ["high-contrast", "invalid", null]) {
    expect(normalizeTheme(theme)).toBe("dark");
    expect(readStoredTheme({ getItem: () => JSON.stringify({ state: { theme } }) })).toBe("dark");
  }
  expect(normalizeTheme("system")).toBe("system");
  expect(normalizeTheme("light")).toBe("light");
});
