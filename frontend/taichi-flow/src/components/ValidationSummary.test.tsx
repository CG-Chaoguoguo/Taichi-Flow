import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ValidationSummary } from "./ValidationSummary";

describe("ValidationSummary", () => {
  it("keeps long preflight failures compact in the inspector", () => {
    render(
      <ValidationSummary
        validation={{
          valid: false,
          errors: ["error-1", "error-2", "error-3", "error-4", "error-5"],
          warnings: ["warning-1", "warning-2", "warning-3"],
        }}
      />,
    );
    expect(screen.getByText("5 项阻断问题")).toBeInTheDocument();
    expect(screen.getByText("error-3")).toBeInTheDocument();
    expect(screen.queryByText("error-4")).not.toBeInTheDocument();
    expect(screen.getByText("另有 2 项，请在对应的中央编辑器中定位和修正。")).toBeInTheDocument();
    expect(screen.getByText("另有 1 项警告。")).toBeInTheDocument();
  });
});
