import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ManningModeEditor } from "./ManningModeEditor";
import type { CaseConfigInterface } from "../types";

const sampleConfig: CaseConfigInterface = {
  file_inputs: [{ family: "manningfil", exists: [false] }],
  parsed_values: {
    manning: { source: "global_initiation_manning", global: 0.1 },
  },
};

describe("ManningModeEditor", () => {
  it("writes global manning patch when editing scalar", () => {
    const onDraftChange = vi.fn();
    render(
      <ManningModeEditor
        draftPatch={{}}
        onDraftChange={onDraftChange}
        caseConfig={sampleConfig}
        canEdit
      />,
    );
    fireEvent.change(screen.getByLabelText(/全局曼宁系数/), { target: { value: "0.05" } });
    expect(onDraftChange).toHaveBeenCalled();
    const calls = onDraftChange.mock.calls;
    const next = calls[calls.length - 1]?.[0] as Record<string, unknown>;
    expect(next["manning.source"]).toBe("global");
    expect(next["rheology.n_manning"]).toBe(0.05);
  });

  it("prompts upload when switching to spatial manning without file", () => {
    function Harness() {
      const [patch, setPatch] = React.useState<Record<string, unknown>>({});
      return (
        <ManningModeEditor
          draftPatch={patch}
          onDraftChange={setPatch}
          caseConfig={sampleConfig}
          canEdit
        />
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "空间曼宁" }));
    expect(screen.getByText(/未绑定空间曼宁资产/)).toBeInTheDocument();
  });
});
