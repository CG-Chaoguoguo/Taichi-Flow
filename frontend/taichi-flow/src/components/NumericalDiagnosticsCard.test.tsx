import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NumericalDiagnosticsCard } from "./NumericalDiagnosticsCard";

describe("probe evidence integrity", () => {
  it("does not turn numerical completion into diagnostic success after a write failure", () => {
    render(<NumericalDiagnosticsCard diagnostics={{status:"completed",erosion_probe_diagnostics:{enabled:true,diagnostics_incomplete:true,write_error:"disk full",captured_record_count:5,written_record_count:3,buffered_record_count:2}}} />);
    expect(screen.getByTestId("erosion-probe-integrity")).toHaveTextContent("不完整，不能用于验收");
    expect(screen.getByRole("alert")).toHaveTextContent("disk full");
  });
  it("requires closed capture, drained buffer, and matching counts for complete evidence", () => {
    render(<NumericalDiagnosticsCard diagnostics={{status:"completed",erosion_probe_diagnostics:{enabled:true,diagnostics_incomplete:false,capture_active:false,captured_record_count:3,written_record_count:3,buffered_record_count:0}}} />);
    expect(screen.getByTestId("erosion-probe-integrity")).toHaveTextContent("完整落盘");
  });
});
