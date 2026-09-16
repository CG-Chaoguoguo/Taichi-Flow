import type { VARIANT_GATE_KEYS } from "./computeGates";

type VariantKey = typeof VARIANT_GATE_KEYS[number];
interface VariantHelp {
  overview: string;
  options: Record<string, { principle: string; impact: string; applicability: string }>;
}

// Presentation copy traced to HydrologyParams, DFS kernels and frame writers.
// Does not select defaults or resolve a case's effective value.
export const NUMERIC_VARIANT_HELP: Record<VariantKey, VariantHelp> = {
  "hydrology.dfs_face_flux_variant": {
    "overview": "决定相邻网格通流条件及面上的水深、浓度和密度平均方式。",
    "options": {
      "both_thin_weighted": {
        "principle": "两侧流深都不超过薄层阈值 TOL 时关闭面；水深按面积平均，浓度与密度按水深和面积加权。",
        "impact": "较深网格对面浓度、密度贡献更大，影响阻力和输运。",
        "applicability": "对应 BJ / NO.5 类加权公式，以案例源码为准。"
      },
      "arithmetic_mean_chamoli": {
        "principle": "两侧都不超过 TOL 时关闭面；水深按面积平均，浓度只按面积平均，密度取算术平均。",
        "impact": "浅水侧仍参与浓度平均，改变面阻力与通量。",
        "applicability": "对应 Chamoli 面平均公式。"
      },
      "asymmetric_head_guard": {
        "principle": "薄水侧的水面高程不低于另一侧时关闭面；水深、浓度与密度取算术平均。",
        "impact": "改变薄水前缘通流条件，面宽也采用方向相关处理。",
        "applicability": "对应 EntireBanzigou 类非对称水头门控。"
      }
    }
  },
  "hydrology.dfs_manningbar_variant": {
    "overview": "决定浓度超过阈值后，侵蚀与面动量计算采用的曼宁系数。",
    "options": {
      "exponential_cv": {
        "principle": "固相体积分数 cv 超过 CVTOL 时，以 n × manningb × exp(manningm × cv) 修正曼宁系数。",
        "impact": "阻力随浓度和参数变化；曼宁项与该系数的平方有关。",
        "applicability": "对应 BJ_HXL 指数浓度公式。"
      },
      "debrisflowmanning_cvtol": {
        "principle": "cv 超过 CVTOL 时，侵蚀分支用固定 debrisflowmanning；面通量保留基础面平均系数。",
        "impact": "侵蚀与面通量采用不同处理，不是所有位置都改用固定值。",
        "applicability": "对应 Chamoli；需提供匹配的泥石流曼宁参数。"
      }
    }
  },
  "hydrology.dfs_dry_face_velocity_variant": {
    "overview": "决定预测速度算出后，是否因供水侧过薄而额外清零。",
    "options": {
      "keep_velocity_bj": {
        "principle": "保留增量加旧速度得到的预测速度，不额外按干燥供水侧清零。",
        "impact": "仍受面门控、符号反转和速度上限约束。",
        "applicability": "对应 BJ 干面速度处理。"
      },
      "zero_dry_face_chamoli": {
        "principle": "按预测流向检查供水侧；流深不超过 TOL 时，在符号反转处理前清零预测速度。",
        "impact": "影响湿干前缘的速度状态和通量。",
        "applicability": "对应 Chamoli 的两条干面清零语句。"
      }
    }
  },
  "hydrology.dfs_artivis_variant": {
    "overview": "决定人工黏性数值平滑项对水深差或速度差的响应。",
    "options": {
      "depth_ratio_bj": {
        "principle": "权重为 0.02 × abs(h₁ − h₂) / (h₁ + h₂)，h 为相邻预测流深。",
        "impact": "水深相对差越大，平滑项权重越大；等深时为零。",
        "applicability": "对应 BJ 水深比公式；不是物理流体黏度。"
      },
      "velocity_ratio_chamoli": {
        "principle": "权重为 0.02 × abs(v₂ − v₁) / (abs(v₂) + abs(v₁) + 1)，对角方向再除以 √2。",
        "impact": "直接响应速度跳变；等速时为零。",
        "applicability": "对应 Chamoli 速度比公式，不能据此认定普遍更稳定。"
      }
    }
  },
  "hydrology.dfs_absubar_variant": {
    "overview": "决定侵蚀和沉积使用的代表速度 absubar 如何从方向速度重建。",
    "options": {
      "max_component_bj": {
        "principle": "方向速度取绝对值，构造正交与对角速度模并取较大者；半速度缩放由 Fortran 速度状态开关控制。",
        "impact": "绝对值合成不保留方向抵消，影响剪应力与侵蚀沉积。",
        "applicability": "对应 BJ；需同时匹配速度状态的取值时刻。"
      },
      "signed_mean_chamoli": {
        "principle": "由原始方向速度的带符号差重建 vx、vy，再取速度模；对角项用字面量 0.707。",
        "impact": "保留方向抵消效应，不使用 BJ 半速度缩放。",
        "applicability": "对应 Chamoli 有符号合成公式。"
      },
      "weighted_signed_test31": {
        "principle": "使用 Test31 独立的原始方向速度带符号表达式，保留 0.4142、0.707、0.2929 权重。",
        "impact": "改变正交与对角方向的贡献，不能替换为 Chamoli 合成式。",
        "applicability": "对应 Test31，需保留原式权重与字面量精度。"
      }
    }
  },
  "hydrology.dfs_flow_velocity_writer_variant": {
    "overview": "决定 Flow_velocity 输出记录的速度统计口径。",
    "options": {
      "half_sum_abs_fv_bj": {
        "principle": "输出前四个方向速度绝对值之和的一半：0.5 × Σ abs(fv₁…fv₄)。",
        "impact": "这是方向速度统计量，不等同于二维合成速度模。",
        "applicability": "用于对照 BJ 流速输出。"
      },
      "absubar_chamoli": {
        "principle": "输出步开始时源项计算使用的 absubar。",
        "impact": "受侵蚀速度模变体影响，与步末方向速度统计的时相不同。",
        "applicability": "用于对照 Chamoli 流速输出，需匹配 absubar 变体。"
      }
    }
  },
  "hydrology.dfs_erosion_depth_writer_variant": {
    "overview": "决定 Erosion_depth 表示床面净降低还是累计侵蚀量。",
    "options": {
      "net_bed_change_bj": {
        "principle": "以初始床面减当前床面，取非负值作为输出基础。",
        "impact": "沉积回填会抵消床面降低，因此不等同于累计侵蚀量。",
        "applicability": "用于对照 BJ 净床面变化；仍遵循输出阈值与掩膜。"
      },
      "cumulative_erodph_chamoli": {
        "principle": "以累计侵蚀变量 erodph 作为输出基础。",
        "impact": "反映侵蚀累计口径，数值还受累计侵蚀时间步变体影响。",
        "applicability": "用于对照 Chamoli 累计侵蚀；仍遵循输出阈值与掩膜。"
      }
    }
  },
  "hydrology.dfs_sfdf_classify_cv_variant": {
    "overview": "决定 SF / DF / FF 流态分箱使用哪一时刻的固相浓度。",
    "options": {
      "previous_committed_cv": {
        "principle": "使用上一已接受时间步提交的 Cv 判定流态分箱。",
        "impact": "本步浓度跨越阈值时，分类可能与本步预测口径不同。",
        "applicability": "仅在泥石流曼宁阈值分支执行分箱；保留既有上步浓度语义，BJ 无该组输出。"
      },
      "predicted_step_cv_chamoli": {
        "principle": "使用本步 frhopredi1 推导的预测浓度进行流态分箱。",
        "impact": "分类响应本步预测浓度，不等同于最终提交浓度。",
        "applicability": "对应 Chamoli；仅在曼宁面平均选择泥石流曼宁阈值时执行分箱。"
      }
    }
  },
  "hydrology.dfs_cvlimit_variant": {
    "overview": "决定浓度限制 cvlimit 与密度限制的坡度来源和截断条件。",
    "options": {
      "tanslo_cycle_cvstar_clamp_bj": {
        "principle": "使用 tanslo；负坡时跳过更新，cvlimit 小于 0 或超过 cvstar 时改为 cvstar。",
        "impact": "负坡分支保留先前限制值，截断阈值为 cvstar。",
        "applicability": "对应 BJ 负坡保持与浓度上限语义。"
      },
      "tan_slo_unit_clamp_chamoli": {
        "principle": "每步从 tan(slo) 重算；cvlimit 小于 0 或超过 1 时改为 cvstar。",
        "impact": "cvstar 与 1 之间的值可能保留；1 是触发阈值，截断目标仍是 cvstar。",
        "applicability": "对应 Chamoli，需匹配原始坡度与浓度参数。"
      }
    }
  },
  "hydrology.dfs_erodph_dt_variant": {
    "overview": "决定侵蚀率累计到 erodph 时使用哪个时间步长度。",
    "options": {
      "accepted_dt_bj": {
        "principle": "用本次已接受时间步 dt 累计侵蚀量。",
        "impact": "累计量与本步实际推进的时间间隔对应。",
        "applicability": "对应 BJ 累计侵蚀顺序。"
      },
      "post_dti_dt_chamoli": {
        "principle": "用加上 dti 并经过时间步上限处理后的 dt_next 累计侵蚀量。",
        "impact": "dt_next 与本步 dt 不同时，即使侵蚀率相同，累计结果也不同。",
        "applicability": "用于复现 Chamoli 原始语句顺序，不应作为通用精度改进。"
      }
    }
  },
  "hydrology.dfs_barrier_flux_variant": {
    "overview": "决定面通量形成后，挡墙与冲刷条件如何清零或折减 qq / qqmass。",
    "options": {
      "bj_barrier_branch": {
        "principle": "按 flexible / rigid / else 三支处理；无挡墙栅格时走 else，保留已形成的面通量。",
        "impact": "没有挡墙时不额外清零负向面，流动范围由普通面核决定。",
        "applicability": "对应 BJ 族 dfs.F90:886-916 的 if/elseif/else 结构。"
      },
      "chamoli_scour_kill_or": {
        "principle": "在 qq 形成后执行 Chamoli `elseif(fvpredi<0 .or. rigid(nq)>0)`；邻居水面低于其原始地面时清零负向面，并同步镜像面。",
        "impact": "即使没有挡墙栅格，冲刷区负向面也可能被清零，从而改变流动范围与侵蚀分布。",
        "applicability": "对应 Chamoli dfs.F90:866-921；检测器匹配该 `.or.` 语句。"
      }
    }
  },
  "hydrology.dfs_commit_cv_eps_variant": {
    "overview": "决定接受步提交固相浓度后，是否把小于 eps 的 cv 归零。",
    "options": {
      "no_clamp_bj": {
        "principle": "提交 `cv=(frho-rhow)/(rhos-rhow)`，不再按 eps 归零。",
        "impact": "浅水或数值噪声可能留下极小浓度。",
        "applicability": "对应 BJ 提交路径，源码无 `where(cv<eps)`。"
      },
      "eps_clamp_chamoli": {
        "principle": "提交浓度后执行 `where(cv<eps) cv=0.`。",
        "impact": "小于求解器 eps 的浓度被清零，影响后续源项与 Cv 输出。",
        "applicability": "对应 Chamoli dfs.F90:1285。"
      }
    }
  }
};
