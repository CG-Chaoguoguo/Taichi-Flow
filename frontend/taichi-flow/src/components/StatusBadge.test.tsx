import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("never wraps status text when a surrounding card gets narrow", () => {
    render(<StatusBadge variant="success">当前打开</StatusBadge>);
    expect(screen.getByText("当前打开")).toHaveStyle({ whiteSpace: "nowrap", flexShrink: "0" });
  });
});
