import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HelpTip } from "./HelpTip";

describe("HelpTip", () => {
  it("shows the explanation on hover and associates aria-describedby", () => {
    render(<HelpTip content="每个分区有独立的顶层参数。" />);
    const trigger = screen.getByRole("button", { name: "说明" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.mouseEnter(screen.getByTestId("help-tip"));
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("每个分区有独立的顶层参数。");
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
  });

  it("opens on keyboard focus and closes on Escape", () => {
    render(<HelpTip content="原始快照归当前方案所有。" />);
    const trigger = screen.getByRole("button", { name: "说明" });
    trigger.focus();
    fireEvent.focus(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("原始快照归当前方案所有。");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("renders nothing when content is empty", () => {
    const { container } = render(<HelpTip content="   " />);
    expect(container).toBeEmptyDOMElement();
  });
});
