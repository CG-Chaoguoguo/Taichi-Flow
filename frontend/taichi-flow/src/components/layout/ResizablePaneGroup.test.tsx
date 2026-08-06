import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  PanelCollapseButton,
  ResizablePane,
  ResizablePaneGroup,
  ResizeHandle,
} from "./ResizablePaneGroup";

function Demo({ onToggle }: { onToggle: () => void }) {
  return (
    <ResizablePaneGroup id="test-group" orientation="horizontal">
      <ResizablePane id="test-leading" defaultSize={240} minSize={176} maxSize={360}>
        <PanelCollapseButton label="方案栏" collapsed={false} direction="left" onToggle={onToggle} />
      </ResizablePane>
      <ResizeHandle
        id="test-splitter"
        leadingPanelId="test-leading"
        label="方案栏与内容之间的调整条"
        leadingMinSize={176}
        leadingMaxSize={360}
        onToggleCollapse={onToggle}
      />
      <ResizablePane id="test-trailing" minSize={360}>
        <div>内容</div>
      </ResizablePane>
    </ResizablePaneGroup>
  );
}

describe("ResizablePaneGroup", () => {
  it("exposes an accessible separator and explicit collapse action", () => {
    const onToggle = vi.fn();
    render(<Demo onToggle={onToggle} />);

    const separator = screen.getByRole("separator", { name: "方案栏与内容之间的调整条" });
    expect(separator).toHaveAttribute("aria-orientation", "vertical");
    expect(screen.getByRole("button", { name: "折叠方案栏" })).toBeInTheDocument();

    fireEvent.keyDown(separator, { key: "Enter" });
    expect(onToggle).toHaveBeenCalledTimes(1);
    fireEvent.doubleClick(separator);
    expect(separator).toHaveAttribute("title", expect.stringContaining("双击重置"));
  });
});
