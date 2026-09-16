import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NumericVariantSummary } from "./NumericVariantSummary";
import type { ComputePolicyResolution, ParameterCatalogEntry } from "../types";

const catalogEntries: ParameterCatalogEntry[] = [
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
    allowed_values: ["exponential_cv", "debrisflowmanning_cvtol"],
    allowed_value_labels_zh: {
      exponential_cv: "指数浓度加权",
      debrisflowmanning_cvtol: "泥石流曼宁",
    },
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
];

const resolution: ComputePolicyResolution = {
  status: "resolved",
  source: "auto",
  requested: "auto",
  detected: {
    simulate_shallow_landslide: false,
    dfs_failure_source_variant: "precomputed_unsfin_schedule",
    evidence: [],
  },
  effective: {
    mode: "disabled",
    simulate_shallow_landslide: false,
    configured_variant: "precomputed_unsfin_schedule",
    active_variant: null,
  },
  numeric_variants: {
    "hydrology.dfs_face_flux_variant": { source: "case_baseline", value: "arithmetic_mean_chamoli" },
    "hydrology.dfs_manningbar_variant": { source: "case_baseline", value: "debrisflowmanning_cvtol" },
    "hydrology.dfs_dry_face_velocity_variant": { source: "case_baseline", value: "zero_dry_face_chamoli" },
    "hydrology.dfs_artivis_variant": { source: "case_baseline", value: "velocity_ratio_chamoli" },
    "hydrology.dfs_absubar_variant": { source: "case_baseline", value: "signed_mean_chamoli" },
    "hydrology.dfs_flow_velocity_writer_variant": { source: "case_baseline", value: "absubar_chamoli" },
    "hydrology.dfs_erosion_depth_writer_variant": { source: "case_baseline", value: "cumulative_erodph_chamoli" },
    "hydrology.dfs_sfdf_classify_cv_variant": { source: "case_baseline", value: "predicted_step_cv_chamoli" },
    "hydrology.dfs_cvlimit_variant": { source: "global_override", value: "tanslo_cycle_cvstar_clamp_bj" },
    "hydrology.dfs_erodph_dt_variant": { source: "case_baseline", value: "post_dti_dt_chamoli" },
    "hydrology.dfs_barrier_flux_variant": { source: "case_baseline", value: "chamoli_scour_kill_or" },
    "hydrology.dfs_commit_cv_eps_variant": { source: "case_baseline", value: "eps_clamp_chamoli" },
  },
  settings_snapshot: {},
  warnings: [],
  resolution_id: "cpr-nvs",
  resolution_hash: "nvs",
};

describe("NumericVariantSummary", () => {
  it("renders Chinese labels, values, and source chips from catalog + resolution", () => {
    render(<NumericVariantSummary resolution={resolution} catalogEntries={catalogEntries} />);

    expect(screen.getByTestId("numeric-variant-summary")).toHaveTextContent("数值变种生效值");
    expect(screen.getByTestId("numeric-variant-summary")).toHaveTextContent("含全局覆盖");
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_flow_velocity_writer_variant")).toHaveTextContent(
      "流速写出口径",
    );
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_flow_velocity_writer_variant")).toHaveTextContent(
      "Chamoli有向合成absubar",
    );
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_flow_velocity_writer_variant")).toHaveTextContent(
      "案例基线",
    );
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_cvlimit_variant")).toHaveTextContent(
      "BJ负坡保持·cvstar上限",
    );
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_cvlimit_variant")).toHaveTextContent("全局覆盖");
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_barrier_flux_variant")).toHaveTextContent(
      "Chamoli负向面·低于原地面清零",
    );
    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_commit_cv_eps_variant")).toHaveTextContent(
      "cv<eps归零",
    );
  });

  it("renders the Test31 lineage label from the shared catalog without a parallel UI branch", () => {
    render(
      <NumericVariantSummary
        catalogEntries={catalogEntries}
        resolution={{
          ...resolution,
          numeric_variants: {
            ...resolution.numeric_variants,
            "hydrology.dfs_absubar_variant": {
              source: "case_baseline",
              value: "weighted_signed_test31",
            },
          },
        }}
      />,
    );

    expect(screen.getByTestId("numeric-variant-row-hydrology.dfs_absubar_variant")).toHaveTextContent(
      "Test31加权有符号速度",
    );
  });
});
