import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NumericalDiagnostics } from "../types";
import { NumericalDiagnosticsCard } from "./NumericalDiagnosticsCard";

function renderLinkCard(backend: NonNullable<NumericalDiagnostics["backend"]>) {
  render(
    <NumericalDiagnosticsCard
      diagnostics={{
        status: "completed",
        backend,
        classification: { conservation_closure: true },
      }}
    />,
  );
}

describe("backend link status", () => {
  it("treats a requested CPU run on a CPU-family live arch as a passing link", () => {
    renderLinkCard({ requested_backend: "cpu", live_arch: "x64", manager_backend: "cpu" });
    expect(screen.getByText("运行链路通过")).toBeInTheDocument();
  });

  it("treats a requested CUDA run on a live CUDA arch as a passing link", () => {
    renderLinkCard({ requested_backend: "cuda", live_arch: "cuda", manager_backend: "cuda", fallback_active: false });
    expect(screen.getByText("运行链路通过")).toBeInTheDocument();
  });

  it("does not pass when CUDA fallback is active", () => {
    renderLinkCard({ requested_backend: "cuda", live_arch: "cuda", manager_backend: "cpu", fallback_active: true });
    expect(screen.getByText("需要复核")).toBeInTheDocument();
    expect(screen.queryByText("运行链路通过")).not.toBeInTheDocument();
  });

  it("does not claim pass when requested_backend is missing", () => {
    renderLinkCard({ live_arch: "cuda", manager_backend: "cuda", fallback_active: false });
    expect(screen.getByText("需要复核")).toBeInTheDocument();
    expect(screen.queryByText("运行链路通过")).not.toBeInTheDocument();
  });

  it("still requires conservation closure for a passing CPU link", () => {
    render(
      <NumericalDiagnosticsCard
        diagnostics={{
          status: "completed",
          backend: { requested_backend: "cpu", live_arch: "x64", manager_backend: "cpu" },
          classification: { conservation_closure: false },
        }}
      />,
    );
    expect(screen.getByTestId("numerical-link-status")).toHaveTextContent("需要复核");
    expect(screen.queryByText("运行链路通过")).not.toBeInTheDocument();
  });
});

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
