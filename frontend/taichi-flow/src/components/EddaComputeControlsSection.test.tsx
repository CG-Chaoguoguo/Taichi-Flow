import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ParameterCatalogEntry } from "../types";
import { EddaComputeControlsSection } from "./EddaComputeControlsSection";

const entries = [
  {
    key: "edda.run_controls.simulate_rainfall",
    control_key: "simulate_rainfall",
    control_family: "edda",
    source_index: 23,
    label: "Simulate Rainfall",
    label_zh: "模拟降雨",
    description_zh: "控制降雨源项是否进入 DFS 强迫装配。",
    group: "compute_process",
    config_path: "edda.run_controls.simulate_rainfall",
    parser_field: "flags.simulate_rainfall",
    runtime_consumer: "DFS rainfall staging",
    activation_condition: "simulate_rainfall=true",
    runtime_status: "production_consumed",
    status_label_zh: "生产已闭环",
    editable: true,
    frontend_policy: "editable",
    value_type: "boolean",
    allowed_values: [false, true],
    dependencies: [],
    dependency_paths: [],
    affected_output_families: [],
    original_variable: "rainsimul",
  },
  {
    key: "edda.run_controls.simulate_erosion",
    control_key: "simulate_erosion",
    control_family: "edda",
    source_index: 29,
    label: "Simulate Erosion",
    label_zh: "模拟侵蚀",
    description_zh: "控制侵蚀源项。",
    group: "compute_process",
    config_path: "edda.run_controls.simulate_erosion",
    parser_field: "flags.simulate_erosion",
    runtime_consumer: "DFS erosion staging",
    activation_condition: "simulate_erosion=true",
    runtime_status: "production_consumed",
    status_label_zh: "生产已闭环",
    editable: true,
    frontend_policy: "editable",
    value_type: "boolean",
    allowed_values: [false, true],
    dependencies: [],
    dependency_paths: [],
    affected_output_families: ["Erosion_depth_*"],
    original_variable: "erosionsimul",
  },
  {
    key: "edda.output_controls.save_erosion_depth",
    control_key: "save_erosion_depth",
    control_family: "edda",
    source_index: 38,
    label: "Save Erosion Depth",
    label_zh: "保存侵蚀深度",
    description_zh: "写出侵蚀深度。",
    group: "compute_outputs",
    config_path: "edda.output_controls.save_erosion_depth",
    parser_field: "flags.save_erosion_depth",
    runtime_consumer: "Erosion_depth writer",
    activation_condition: "simulate_erosion && save_erosion_depth",
    runtime_status: "production_consumed",
    status_label_zh: "生产已闭环",
    editable: true,
    frontend_policy: "editable",
    value_type: "boolean",
    allowed_values: [false, true],
    dependencies: ["simulate_erosion"],
    dependency_paths: ["edda.run_controls.simulate_erosion"],
    affected_output_families: ["Erosion_depth_*"],
    original_variable: "erodepthsave",
  },
  {
    key: "edda.run_controls.simulate_debris_flow",
    control_key: "simulate_debris_flow",
    control_family: "edda",
    source_index: 28,
    label: "Simulate Debris Flow",
    label_zh: null,
    description_zh: "仅部分语义闭环；未验证分支继续由后端门禁阻断。",
    group: "compute_process",
    config_path: "edda.run_controls.simulate_debris_flow",
    parser_field: "flags.simulate_debris_flow",
    runtime_consumer: "strict solver selection",
    activation_condition: "true selects DFS; false selects WFS",
    runtime_status: "partial",
    status_label_zh: "部分闭环",
    editable: false,
    frontend_policy: "read_only",
    value_type: "boolean",
    allowed_values: [false, true],
    dependencies: [],
    dependency_paths: [],
    affected_output_families: [],
    original_variable: "debrissimul",
  },
] as ParameterCatalogEntry[];

describe("EddaComputeControlsSection", () => {
  it("edits only production controls and keeps dependent and partial semantics explicit", () => {
    const onDraftChange = vi.fn();
    render(
      <EddaComputeControlsSection
        entries={entries}
        controlRegistry={{ registry_version: "1.0.0", entry_count: 4, editable_count: 3, restricted_count: 1 }}
        baseline={{
          "edda.registry_version": "1.0.0",
          "edda.run_controls.simulate_rainfall": true,
          "edda.run_controls.simulate_erosion": false,
          "edda.output_controls.save_erosion_depth": true,
          "edda.run_controls.simulate_debris_flow": true,
        }}
        draftPatch={{}}
        canEdit
        onDraftChange={onDraftChange}
      />,
    );

    expect(screen.getByRole("heading", { name: "计算" })).toBeInTheDocument();
    const rainfall = screen.getByRole("switch", { name: "模拟降雨" });
    expect(rainfall).toHaveAttribute("aria-checked", "true");
    fireEvent.click(rainfall);
    expect(onDraftChange).toHaveBeenCalledWith({
      "edda.run_controls.simulate_rainfall": false,
    });

    const outputSection = screen.getByRole("group", { name: "结果输出" });
    expect(within(outputSection).getByText("需同时启用：模拟侵蚀")).toBeInTheDocument();
    expect(screen.getByText("受限能力（1）")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /simulate_debris_flow/i })).not.toBeInTheDocument();
  });
});
