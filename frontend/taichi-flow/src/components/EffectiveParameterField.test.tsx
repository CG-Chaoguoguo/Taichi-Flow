import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EffectiveParameterField } from "./EffectiveParameterField";
import type { ParameterCatalogEntry } from "../types";

const entry: ParameterCatalogEntry = {
  key: "hydrology.dfs_face_flux_variant",
  label: "DFS face-flux variant",
  label_zh: "面通量平均变种",
  runtime_status: "production_consumed",
  editable: true,
  value_type: "enum",
  allowed_values: ["both_thin_weighted", "arithmetic_mean_chamoli"],
  allowed_value_labels_zh: {
    both_thin_weighted: "双薄层加权平均",
    arithmetic_mean_chamoli: "算术平均",
  },
};

describe("EffectiveParameterField", () => {
  it("renders Chinese labels for enum options", () => {
    const onChange = vi.fn();
    render(
      <EffectiveParameterField
        entry={entry}
        defaultValue="both_thin_weighted"
        overrideValue={undefined}
        effectiveValue="both_thin_weighted"
        disabled={false}
        onChange={onChange}
        onReset={() => undefined}
      />,
    );
    const select = screen.getByTestId("enum-select-hydrology.dfs_face_flux_variant") as HTMLSelectElement;
    expect(select).toHaveValue("both_thin_weighted");
    expect(screen.getByRole("option", { name: "双薄层加权平均" })).toHaveValue("both_thin_weighted");
    fireEvent.change(select, { target: { value: "arithmetic_mean_chamoli" } });
    expect(onChange).toHaveBeenCalledWith("arithmetic_mean_chamoli");
  });

  it("renders an Auto option and resets when Auto is selected", () => {
    const onChange = vi.fn();
    const onReset = vi.fn();
    render(
      <EffectiveParameterField
        entry={entry}
        defaultValue="both_thin_weighted"
        overrideValue={undefined}
        effectiveValue="both_thin_weighted"
        disabled={false}
        autoCapable
        onChange={onChange}
        onReset={onReset}
      />,
    );
    const select = screen.getByTestId("enum-select-hydrology.dfs_face_flux_variant") as HTMLSelectElement;
    expect(select).toHaveValue("");
    expect(screen.getByRole("option", { name: "自动（按方案识别）" })).toHaveValue("");
    expect(screen.getByText("自动识别")).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "arithmetic_mean_chamoli" } });
    expect(onChange).toHaveBeenCalledWith("arithmetic_mean_chamoli");
    fireEvent.change(select, { target: { value: "" } });
    expect(onReset).toHaveBeenCalled();
  });
});
