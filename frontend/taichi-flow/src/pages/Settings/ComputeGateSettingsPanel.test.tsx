import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ParameterCatalog } from "../../types";
import { ComputeGateSettingsPanel } from "./ComputeGateSettingsPanel";

const catalog: ParameterCatalog = {
  catalog_version: "taichi-flow-parameter-catalog-v3",
  editable_statuses: ["production_consumed"],
  status_counts: { production_consumed: 3 },
  control_registry: {
    registry_version: "1.0.0",
    entry_count: 1,
    editable_count: 1,
    restricted_count: 0,
  },
  parameters: [
    {
      key: "edda.run_controls.simulate_rainfall",
      control_key: "simulate_rainfall",
      control_family: "edda",
      label: "Simulate Rainfall",
      label_zh: "模拟降雨",
      group: "compute_process",
      runtime_status: "production_consumed",
      editable: true,
      frontend_policy: "editable",
      value_type: "boolean",
    },
    {
      key: "hydrology.dfs_face_flux_variant",
      label: "DFS face-flux variant",
      label_zh: "面通量平均变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["both_thin_weighted", "arithmetic_mean_chamoli"],
      allowed_value_labels_zh: {
        both_thin_weighted: "双薄层加权平均",
        arithmetic_mean_chamoli: "算术平均",
      },
    },
    {
      key: "hydrology.dfs_manningbar_variant",
      label: "DFS Manning-bar variant",
      label_zh: "曼宁面平均变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["exponential_cv"],
      allowed_value_labels_zh: { exponential_cv: "指数浓度加权" },
    },
    {
      key: "hydrology.dfs_dry_face_velocity_variant",
      label: "DFS dry-face velocity variant",
      label_zh: "干面速度清零变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["keep_velocity_bj", "zero_dry_face_chamoli"],
      allowed_value_labels_zh: {
        keep_velocity_bj: "保持预测速度",
        zero_dry_face_chamoli: "干面上游清零",
      },
    },
    {
      key: "hydrology.dfs_artivis_variant",
      label: "DFS artificial-viscosity variant",
      label_zh: "人工黏性权重变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["depth_ratio_bj", "velocity_ratio_chamoli"],
      allowed_value_labels_zh: {
        depth_ratio_bj: "水深比权重",
        velocity_ratio_chamoli: "速度比权重",
      },
    },
    {
      key: "hydrology.dfs_absubar_variant",
      label: "DFS erosion velocity-magnitude variant",
      label_zh: "侵蚀速度模变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["max_component_bj", "signed_mean_chamoli"],
      allowed_value_labels_zh: {
        max_component_bj: "分量最大模",
        signed_mean_chamoli: "有符号合成速度",
      },
    },
    {
      key: "hydrology.dfs_failure_source_policy",
      label: "Failure-source policy",
      label_zh: "失稳源策略",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["disabled", "precomputed", "live"],
      allowed_value_labels_zh: {
        disabled: "关闭浅层失稳台账（triggerslide 不受影响）",
        precomputed: "串行预计算 UNSFIN 台账（原 EDDA）",
        live: "实时双层（Taichi 实验）",
      },
    },
    {
      key: "experimental.enable_live_doublelayer_in_dfs",
      label: "Unlock live double-layer",
      label_zh: "解锁实时双层实验路径",
      group: "experimental",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "boolean",
    },
    {
      key: "boundary_conditions.mode",
      label: "Boundary mode",
      label_zh: "边界模式",
      group: "boundary",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["auto", "file", "manual"],
      allowed_value_labels_zh: { auto: "自动检测", file: "边界文件", manual: "手动指定" },
    },
    {
      key: "boundary_conditions.default_type",
      label: "Default boundary type",
      label_zh: "默认边界类型",
      group: "boundary",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["outflow", "wall", "periodic"],
      allowed_value_labels_zh: { outflow: "出流", wall: "固壁", periodic: "周期" },
    },
    {
      key: "boundary_conditions.include_nodata",
      label: "Include nodata boundary",
      label_zh: "含NODATA边界",
      group: "boundary",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "boolean",
    },
  ],
};

describe("ComputeGateSettingsPanel", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      parameterCatalog: catalog,
      computeGateDefaults: {
        catalog_version: catalog.catalog_version,
        values: {},
        baseline: {
          "edda.run_controls.simulate_rainfall": true,
          "hydrology.dfs_face_flux_variant": "both_thin_weighted",
          "hydrology.dfs_manningbar_variant": "exponential_cv",
          "hydrology.dfs_dry_face_velocity_variant": "keep_velocity_bj",
          "hydrology.dfs_artivis_variant": "depth_ratio_bj",
          "hydrology.dfs_absubar_variant": "max_component_bj",
          "boundary_conditions.mode": "auto",
          "boundary_conditions.default_type": "outflow",
          "boundary_conditions.include_nodata": true,
        },
        effective: {},
      },
      loading: {},
      errors: {},
      fetchParameterCatalog: vi.fn(async () => undefined),
      fetchComputeGateDefaults: vi.fn(async () => undefined),
      saveComputeGateDefaults: vi.fn(async () => undefined),
      addToast: vi.fn(),
    });
  });

  it("renders Chinese labels for compute gates, variants, and boundary types", () => {
    render(<ComputeGateSettingsPanel />);

    expect(screen.getByTestId("compute-gate-settings")).toBeInTheDocument();
    expect(screen.getByTestId("edda-compute-controls")).toBeInTheDocument();
    expect(screen.getByTestId("variant-gate-settings")).toBeInTheDocument();
    expect(screen.getByTestId("boundary-gate-settings")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "双薄层加权平均" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "干面上游清零" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "速度比权重" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "有符号合成速度" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "自动检测" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "出流" })).toBeInTheDocument();
    expect(screen.getByTestId("failure-source-policy-settings")).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "自动（按方案识别）" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("option", { name: "自动（按 fssimul 与 Fortran 源码）" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "关闭浅层失稳台账（triggerslide 不受影响）" })).toBeInTheDocument();
    expect(screen.getByTestId("live-policy-locked-hint")).toBeInTheDocument();
  });
});
