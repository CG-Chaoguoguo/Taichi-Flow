import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { NUMERIC_VARIANT_HELP } from "../../constants/numericVariantHelp";
import { VARIANT_GATE_KEYS } from "../../constants/computeGates";
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
      allowed_values: ["both_thin_weighted", "arithmetic_mean_chamoli", "asymmetric_head_guard"],
      allowed_value_labels_zh: {
        both_thin_weighted: "双薄层加权平均",
        arithmetic_mean_chamoli: "算术平均",
        asymmetric_head_guard: "非对称水头保护",
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
      allowed_values: ["exponential_cv", "debrisflowmanning_cvtol"],
      allowed_value_labels_zh: { exponential_cv: "指数浓度加权", debrisflowmanning_cvtol: "泥石流曼宁阈值" },
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
      allowed_values: ["max_component_bj", "signed_mean_chamoli", "weighted_signed_test31"],
      allowed_value_labels_zh: {
        max_component_bj: "分量最大模",
        signed_mean_chamoli: "有符号合成速度",
        weighted_signed_test31: "Test31加权有符号速度",
      },
    },
    {
      key: "hydrology.dfs_flow_velocity_writer_variant",
      label: "DFS flow-velocity writer variant",
      label_zh: "流速写出口径",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["half_sum_abs_fv_bj", "absubar_chamoli"],
      allowed_value_labels_zh: {
        half_sum_abs_fv_bj: "半和四向绝对值",
        absubar_chamoli: "Chamoli有向合成absubar",
      },
    },
    {
      key: "hydrology.dfs_erosion_depth_writer_variant",
      label: "DFS erosion-depth writer variant",
      label_zh: "侵蚀深度写出口径",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["net_bed_change_bj", "cumulative_erodph_chamoli"],
      allowed_value_labels_zh: {
        net_bed_change_bj: "净床面变化",
        cumulative_erodph_chamoli: "累计侵蚀erodph",
      },
    },
    {
      key: "hydrology.dfs_sfdf_classify_cv_variant",
      label: "DFS SF/DF/FF classify-cv variant",
      label_zh: "SF-DF-FF分箱浓度时相",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["previous_committed_cv", "predicted_step_cv_chamoli"],
      allowed_value_labels_zh: {
        previous_committed_cv: "上步已提交Cv",
        predicted_step_cv_chamoli: "本步预测cv",
      },
    },
    {
      key: "hydrology.dfs_cvlimit_variant",
      label: "DFS cvlimit clamp variant",
      label_zh: "cvlimit钳制变种",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["tanslo_cycle_cvstar_clamp_bj", "tan_slo_unit_clamp_chamoli"],
      allowed_value_labels_zh: {
        tanslo_cycle_cvstar_clamp_bj: "BJ负坡保持·cvstar上限",
        tan_slo_unit_clamp_chamoli: "Chamoli每步重算·1.0上限",
      },
    },
    {
      key: "hydrology.dfs_erodph_dt_variant",
      label: "DFS cumulative erodph timestep variant",
      label_zh: "累计侵蚀erodph时步口径",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["accepted_dt_bj", "post_dti_dt_chamoli"],
      allowed_value_labels_zh: {
        accepted_dt_bj: "接受步dt",
        post_dti_dt_chamoli: "dti后dt_next",
      },
    },
    {
      key: "hydrology.dfs_barrier_flux_variant",
      label: "DFS barrier / scour face-flux kill variant",
      label_zh: "挡墙/冲刷面通量清零口径",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["bj_barrier_branch", "chamoli_scour_kill_or"],
      allowed_value_labels_zh: {
        bj_barrier_branch: "BJ挡墙分支·无墙不清零",
        chamoli_scour_kill_or: "Chamoli负向面·低于原地面清零",
      },
    },
    {
      key: "hydrology.dfs_commit_cv_eps_variant",
      label: "DFS committed cv eps clamp variant",
      label_zh: "提交步cv<eps归零口径",
      group: "hydrology",
      runtime_status: "production_consumed",
      editable: true,
      value_type: "enum",
      allowed_values: ["no_clamp_bj", "eps_clamp_chamoli"],
      allowed_value_labels_zh: {
        no_clamp_bj: "不归零",
        eps_clamp_chamoli: "cv<eps归零",
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

  it.each(VARIANT_GATE_KEYS)("keeps %s in a local draft and resets without saving global defaults", (key) => {
    function Harness() {
      const [draft, setDraft] = useState<Record<string, unknown>>({});
      return <ComputeGateSettingsPanel baseline={{}} effective={{}} draft={draft} onChange={setDraft} />;
    }
    render(<Harness />);
    const entry = catalog.parameters.find((item) => item.key === key)!;
    fireEvent.focus(screen.getByRole("button", { name: `${entry.label_zh}说明` }));
    const select = screen.getByTestId(`enum-select-${key}`);
    expect(screen.getByRole("tooltip")).toHaveTextContent("自动（按当前方案识别）");
    expect(Object.keys(NUMERIC_VARIANT_HELP[key].options).sort()).toEqual([...entry.allowed_values!].sort());
    for (const value of entry.allowed_values!) {
      fireEvent.change(select, { target: { value: String(value) } });
      expect(screen.getByRole("tooltip")).toHaveTextContent(NUMERIC_VARIANT_HELP[key].options[String(value)].principle);
      expect(screen.getByRole("tooltip")).toHaveTextContent(NUMERIC_VARIANT_HELP[key].options[String(value)].applicability);
      expect(screen.getByRole("tooltip")).not.toHaveTextContent("当前方案解析：");
    }
    fireEvent.change(select, { target: { value: "" } });
    expect(select).toHaveValue("");
    expect(screen.getByRole("tooltip")).toHaveTextContent("此处尚无可用的具体变体说明");
    expect(useTaichiFlowStore.getState().saveComputeGateDefaults).not.toHaveBeenCalled();
  });

  it("resets a saved override to the scenario baseline", () => {
    function Harness() {
      const [draft, setDraft] = useState<Record<string, unknown>>({ "hydrology.dfs_face_flux_variant": "arithmetic_mean_chamoli" });
      return <ComputeGateSettingsPanel baseline={{}} effective={{ "hydrology.dfs_face_flux_variant": "both_thin_weighted" }} draft={draft} onChange={setDraft} />;
    }
    render(<Harness />);
    fireEvent.focus(screen.getByRole("button", { name: "面通量平均变种说明" }));
    fireEvent.change(screen.getByTestId("enum-select-hydrology.dfs_face_flux_variant"), { target: { value: "" } });
    expect(screen.getByRole("tooltip")).toHaveTextContent(NUMERIC_VARIANT_HELP["hydrology.dfs_face_flux_variant"].options.both_thin_weighted.principle);
    expect(screen.getByRole("tooltip")).toHaveTextContent("自动（按当前方案识别）");
    expect(screen.getByRole("tooltip")).toHaveTextContent("当前方案解析：双薄层加权平均");
  });

  it("keeps help aligned when the parent restores or replaces the scenario draft", () => {
    const key = "hydrology.dfs_face_flux_variant";
    const props = { baseline: { [key]: "both_thin_weighted" }, effective: {}, onChange: vi.fn() };
    const { rerender } = render(<ComputeGateSettingsPanel {...props} draft={{ [key]: "arithmetic_mean_chamoli" }} />);
    fireEvent.focus(screen.getByRole("button", { name: "面通量平均变种说明" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("对应 Chamoli");
    rerender(<ComputeGateSettingsPanel {...props} draft={{}} />);
    expect(screen.getByRole("tooltip")).toHaveTextContent("当前方案解析：双薄层加权平均");
    rerender(<ComputeGateSettingsPanel {...props} draft={{ [key]: "future_variant" }} />);
    expect(screen.getByRole("tooltip")).toHaveTextContent("该选项暂无专属解释");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("对应 Chamoli");
  });

  it("allows help inspection in a frozen scenario without changing controls", () => {
    const key = "hydrology.dfs_face_flux_variant";
    const onChange = vi.fn();
    render(<ComputeGateSettingsPanel baseline={{ [key]: "both_thin_weighted" }} effective={{}} draft={{}} onChange={onChange} disabled />);
    expect(screen.getByTestId(`enum-select-${key}`)).toBeDisabled();
    fireEvent.focus(screen.getByRole("button", { name: "面通量平均变种说明" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("计算原理");
    expect(onChange).not.toHaveBeenCalled();
  });
});
