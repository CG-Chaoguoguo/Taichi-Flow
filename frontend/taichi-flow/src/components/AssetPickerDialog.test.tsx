import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InputFile } from "../types";
import { AssetPickerDialog } from "./AssetPickerDialog";

const assets: InputFile[] = [
  { file_id: "a10", family: "rainfall", name: "ri10.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
  { file_id: "a2", family: "rainfall", name: "ri2.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
  { file_id: "a1", family: "rainfall", name: "ri1.asc", status: "ready", size: 1, updated_at: "2026-08-03T00:00:00Z" },
];

describe("AssetPickerDialog", () => {
  it("toggles natural filename sort from the footer", () => {
    render(
      <AssetPickerDialog
        open
        title="选择降雨资产"
        family="rainfall"
        assets={assets}
        sortable
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const namesBefore = screen.getAllByRole("button", { name: /选择资产/ }).map((button) => button.textContent || "");
    expect(namesBefore[0]).toContain("ri10.asc");

    fireEvent.click(screen.getByRole("button", { name: "按文件名排序" }));
    const namesAfter = screen.getAllByRole("button", { name: /选择资产/ }).map((button) => button.textContent || "");
    expect(namesAfter[0]).toContain("ri1.asc");
    expect(namesAfter[1]).toContain("ri2.asc");
    expect(namesAfter[2]).toContain("ri10.asc");
    expect(screen.getByText("共 3 项")).toBeInTheDocument();
  });
});
