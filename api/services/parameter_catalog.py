"""Frontend-safe parameter catalog for Taichi Flow."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api.services.edda_switch_registry import (
    EDDA_SWITCH_BY_KEY,
    EDDA_SWITCH_REGISTRY,
    REGISTRY_VERSION as EDDA_SWITCH_REGISTRY_VERSION,
)
from api.services.reference_config_parser import ReferenceConfigParseResult


# Config-path keys accepted by scenario parameter_patch / runtime overrides.
EDITABLE_PARAMETERS = {
    "hydrology.use_background_flux_offset",
    "hydrology.K_sat",
    "hydrology.rizero_initial",
    "hydrology.depthwt_initial",
    "soil.gamma_s",
    "soil.c",
    "soil.phi",
    "soil.gamma_w",
    "soil.depth",
    "soil.double_layer.lbstar",
    "soil.double_layer.ltstar",
    "soil.double_layer.min_slope_angle_deg",
    "soil.double_layer.nzsb",
    "soil.double_layer.nzst",
    "soil.double_layer.uww",
    "rheology.n_manning",
    "rheology.limitfr",
    "rheology.alpha1",
    "rheology.alpha2",
    "rheology.beta1",
    "rheology.beta2",
    "rheology.cs",
    "rheology.kresis",
    "rheology.shallown",
    "erosion.d50",
    "erosion.coedepo",
    "erosion.k_deposition",
    "time.t_end",
    "time.dt_max",
    "time.dt_min",
    "time.dt_decrease",
    "time.dt_increase",
    "time.toldh",
    "time.toldhp",
    "time.dt_output",
    "time.wavemax",
    # Input-source mode switches (applied via scenario_config_overrides)
    "rainfall.mode",
    "rainfall.timeline",
    "rainfall.periods",
    "manning.source",
}

# edda_in field -> display metadata (Chinese name + English abbrev + group).
PARAMETER_META: Dict[str, Dict[str, str]] = {
    "hydrology.use_background_flux_offset": {"label_zh": "背景入渗偏移", "abbrev": "background_flux_offset", "group": "hydrology"},
    "hydrology.K_sat": {"label_zh": "饱和导水率", "abbrev": "K_sat", "group": "hydrology"},
    "hydrology.rizero_initial": {"label_zh": "初始入渗率", "abbrev": "rizero", "group": "hydrology"},
    "hydrology.depthwt_initial": {"label_zh": "初始地下水深", "abbrev": "depth", "group": "hydrology"},
    "soil.gamma_s": {"label_zh": "土体重度", "abbrev": "gamma_s", "group": "soil"},
    "soil.c": {"label_zh": "黏聚力", "abbrev": "c", "group": "soil"},
    "soil.phi": {"label_zh": "内摩擦角", "abbrev": "phi", "group": "soil"},
    "soil.gamma_w": {"label_zh": "水重度", "abbrev": "uww", "group": "soil"},
    "soil.depth": {"label_zh": "土层厚度", "abbrev": "depth", "group": "soil"},
    "soil.double_layer.lbstar": {"label_zh": "下层厚度", "abbrev": "lbstar", "group": "soil"},
    "soil.double_layer.ltstar": {"label_zh": "上层厚度", "abbrev": "ltstar", "group": "soil"},
    "soil.double_layer.min_slope_angle_deg": {"label_zh": "最小坡度角", "abbrev": "min_slope_angle_deg", "group": "soil"},
    "soil.double_layer.nzsb": {"label_zh": "下层分层数", "abbrev": "nzsb", "group": "soil"},
    "soil.double_layer.nzst": {"label_zh": "上层分层数", "abbrev": "nzst", "group": "soil"},
    "soil.double_layer.uww": {"label_zh": "水重度", "abbrev": "uww", "group": "soil"},
    "rheology.n_manning": {"label_zh": "曼宁糙率", "abbrev": "manning", "group": "rheology"},
    "rheology.limitfr": {"label_zh": "弗劳德数限制", "abbrev": "limitfr", "group": "rheology"},
    "rheology.alpha1": {"label_zh": "二次流变系数 α1", "abbrev": "alpha1", "group": "rheology"},
    "rheology.alpha2": {"label_zh": "二次流变系数 α2", "abbrev": "alpha2", "group": "rheology"},
    "rheology.beta1": {"label_zh": "二次流变系数 β1", "abbrev": "beta1", "group": "rheology"},
    "rheology.beta2": {"label_zh": "二次流变系数 β2", "abbrev": "beta2", "group": "rheology"},
    "rheology.cs": {"label_zh": "悬移质系数", "abbrev": "cs", "group": "rheology"},
    "rheology.kresis": {"label_zh": "粘滞阻力系数", "abbrev": "kresis", "group": "rheology"},
    "rheology.shallown": {"label_zh": "浅水摩阻系数", "abbrev": "shallown", "group": "rheology"},
    "erosion.d50": {"label_zh": "中值粒径", "abbrev": "d50", "group": "erosion"},
    "erosion.coedepo": {"label_zh": "淤积系数", "abbrev": "coedepo", "group": "erosion"},
    "erosion.k_deposition": {"label_zh": "淤积速率系数", "abbrev": "coedepo", "group": "erosion"},
    "time.t_end": {"label_zh": "模拟结束时间", "abbrev": "simul", "group": "time"},
    "time.dt_max": {"label_zh": "最大时间步", "abbrev": "dtmax", "group": "time"},
    "time.dt_min": {"label_zh": "最小时间步", "abbrev": "dtmin", "group": "time"},
    "time.dt_decrease": {"label_zh": "拒步缩减系数", "abbrev": "dtd", "group": "time"},
    "time.dt_increase": {"label_zh": "接受步增长系数", "abbrev": "dti", "group": "time"},
    "time.toldh": {"label_zh": "绝对水深变化限", "abbrev": "toldh", "group": "time"},
    "time.toldhp": {"label_zh": "相对水深变化限", "abbrev": "toldhp", "group": "time"},
    "time.dt_output": {"label_zh": "输出间隔", "abbrev": "tout", "group": "time"},
    "time.wavemax": {"label_zh": "动波稳定系数", "abbrev": "wavemax", "group": "time"},
    "spatial_zones.zone_file": {"label_zh": "分区栅格文件", "abbrev": "zonfil", "group": "spatial_zones"},
    "spatial_zones.zones": {"label_zh": "分区参数", "abbrev": "zones", "group": "spatial_zones"},
    "rainfall.mode": {"label_zh": "降雨模式", "abbrev": "rainfall_mode", "group": "inputs"},
    "rainfall.timeline": {"label_zh": "降雨时间轴", "abbrev": "capt", "group": "inputs"},
    "rainfall.periods": {"label_zh": "降雨时段", "abbrev": "cri", "group": "inputs"},
    "manning.source": {"label_zh": "曼宁来源", "abbrev": "manning_source", "group": "inputs"},
}

READONLY_DISPLAY_PARAMETERS = {
    "spatial_zones.zone_file",
    "spatial_zones.zones",
}

# ``background_flux_offset`` now has one canonical, strict EDDA control path.
# Keep the historical hydrology alias writable for direct-config compatibility,
# but never expose both paths in the authoring UI as competing sources of truth.
STATIC_CATALOG_HIDDEN_ALIASES = {
    "hydrology.use_background_flux_offset",
}

EDDA_CONTROL_META_ZH: Dict[str, Dict[str, str]] = {
    "background_flux_offset": {
        "label": "背景入渗通量偏移",
        "description": "按原始入渗契约启用背景通量偏移；在降雨与入渗源项装配前冻结。",
    },
    "simulate_rainfall": {
        "label": "模拟降雨",
        "description": "控制降雨源项是否进入 DFS 强迫装配，不改变降雨时段定义。",
    },
    "simulate_infiltration": {
        "label": "模拟入渗",
        "description": "控制 Green-Ampt 入渗源项；关闭时入渗率归零，其他水量源项保持独立。",
    },
    "simulate_outflow_cell": {
        "label": "模拟出流单元",
        "description": "启用 outflow.txt 专用单元掩膜及接受步出流采样。",
    },
    "simulate_erosion": {
        "label": "模拟侵蚀",
        "description": "控制侵蚀率与候选床面变化源项，结果输出仍由独立保存开关控制。",
    },
    "simulate_water_and_solid_separately": {
        "label": "水固分相计算",
        "description": "控制水相与固相的独立淤积候选装配，并作为淤积/总深度输出的前置门禁。",
    },
    "save_flow_depth": {
        "label": "保存流深",
        "description": "在每个输出边界写出已提交的 Flow_depth 标量网格。",
    },
    "save_max_flow_depth": {
        "label": "保存最大流深",
        "description": "写出由接受时间步单调累计的 Max_flow_depth 网格。",
    },
    "save_flow_velocity": {
        "label": "保存流速",
        "description": "按原始四方向面速度绝对值公式写出 Flow_velocity 标量网格。",
    },
    "save_max_flow_velocity": {
        "label": "保存最大流速",
        "description": "写出由接受时间步单调累计的 Max_flow_velocity 网格。",
    },
    "save_erosion_depth": {
        "label": "保存侵蚀深度",
        "description": "在侵蚀过程启用时写出原始床面减当前床面的正侵蚀深度。",
    },
    "save_deposition_depth": {
        "label": "保存淤积深度",
        "description": "在水固分相计算启用时写出当前床面相对原始床面的正增量。",
    },
    "save_total_depth": {
        "label": "保存总深度",
        "description": "在水固分相计算启用时写出流深与床面增量之和。",
    },
    "save_max_solid_depth": {
        "label": "保存最大固相深度",
        "description": "写出接受时间步累计的 h×Cv 最大值，并保留原始浅层阈值。",
    },
    "save_volumetric_sediment_concentration": {
        "label": "保存体积含沙浓度",
        "description": "写出体积含沙浓度 Cv，并按原始浅水深规则置零。",
    },
    "save_outflow_process": {
        "label": "保存出流过程",
        "description": "在出流单元模拟启用时写出末态 OUTNQ 过程文件。",
    },
    "save_runoff_grids": {"label": "保存径流栅格"},
    "save_fs_min_legacy": {"label": "保存最小安全系数（旧）"},
    "save_fs_depth_at_min": {"label": "保存最小安全系数时水深"},
    "save_fs_pore_pressure_at_min": {"label": "保存最小安全系数时孔压"},
    "save_infiltration_rate": {"label": "保存入渗率"},
    "save_basal_flux": {"label": "保存基底通量"},
    "save_deposit_distribution": {"label": "保存淤积分布"},
    "save_pf": {"label": "保存 PF 结果"},
    "save_road_risk": {"label": "保存道路风险"},
    "save_road_warning": {"label": "保存道路预警"},
    "save_detached_trace": {"label": "保存脱落体轨迹"},
    "pressure_head_fs_listing_flag": {"label": "压力水头/安全系数列表开关"},
    "slope_failure_output_count": {"label": "边坡失稳输出时刻数"},
    "slope_failure_output_times_s": {"label": "边坡失稳输出时刻"},
    "skip_other_timesteps": {"label": "跳过其他时间步"},
    "use_analytic_fillable_porosity": {"label": "使用解析可填充孔隙率"},
    "estimate_positive_pressure_head": {"label": "估算正压力水头"},
    "use_psi0_negative_inverse_alpha": {"label": "使用 ψ₀=-1/α"},
    "log_mass_balance_results": {"label": "记录质量平衡结果"},
    "flow_direction_mode": {"label": "流向模式"},
    "use_full_dynamic_wave": {"label": "使用完整动波"},
    "simulate_inflow_hydrograph": {"label": "模拟入流过程"},
    "simulate_shallow_landslide": {"label": "模拟浅层滑坡"},
    "simulate_debris_flow": {"label": "模拟泥石流"},
    "simulate_drainage_flow": {"label": "模拟排水管网流"},
    "simulate_barrier": {"label": "模拟拦挡设施"},
    "save_fs_min_grid": {"label": "保存最小安全系数栅格"},
    "save_drainage_nodal_flow": {"label": "保存排水节点流量"},
    "save_drainage_conduit_flow": {"label": "保存排水管道流量"},
}

EDDA_STATUS_LABELS_ZH = {
    "production_consumed": "生产已闭环",
    "config_fallback_consumed": "配置回退已闭环",
    "parsed_only": "仅解析",
    "mapped_only": "仅映射",
    "metadata_only": "仅审计元数据",
    "partial": "部分闭环",
    "unsupported": "生产未支持",
    "blocked": "已阻断",
}

EDDA_RESTRICTION_MESSAGES_ZH = {
    "parsed_only": "仅完成输入解析，尚无运行时消费证据，当前保持只读。",
    "mapped_only": "仅完成配置映射，尚无生产运行时消费证据，当前保持只读。",
    "metadata_only": "仅作为审计元数据记录，不改变求解与输出行为。",
    "partial": "仅部分语义闭环；未验证分支继续由后端门禁阻断。",
    "unsupported": "生产链路尚未端到端实现，当前不可启用。",
    "blocked": "该控制已被语义门禁阻断。",
}

CASE_CONFIG_OVERRIDE_PATHS = {
    "alpha1": ["rheology.alpha1"],
    "alpha2": ["rheology.alpha2"],
    "background_flux_offset": ["hydrology.use_background_flux_offset"],
    "beta1": ["rheology.beta1"],
    "beta2": ["rheology.beta2"],
    "coedepo": ["erosion.coedepo", "erosion.k_deposition"],
    "cs": ["rheology.cs"],
    "d50": ["erosion.d50"],
    "depth": ["soil.depth", "hydrology.depthwt_initial"],
    "dtmax": ["time.dt_max"],
    "dtmin": ["time.dt_min"],
    "dtd": ["time.dt_decrease"],
    "dti": ["time.dt_increase"],
    "kresis": ["rheology.kresis"],
    "lbstar": ["soil.double_layer.lbstar"],
    "limitfr": ["rheology.limitfr"],
    "ltstar": ["soil.double_layer.ltstar"],
    "manning_global": ["rheology.n_manning"],
    "min_slope_angle_deg": ["soil.double_layer.min_slope_angle_deg"],
    "nzsb": ["soil.double_layer.nzsb"],
    "nzst": ["soil.double_layer.nzst"],
    "rizero": ["hydrology.rizero_initial"],
    "shallown": ["rheology.shallown"],
    "simul": ["time.t_end"],
    "toldh": ["time.toldh"],
    "toldhp": ["time.toldhp"],
    "tout": ["time.dt_output"],
    "uww": ["soil.gamma_w", "soil.double_layer.uww"],
    "wavemax": ["time.wavemax"],
    "zones": ["spatial_zones.zones"],
    "zonfil": ["spatial_zones.zone_file"],
}

CONFIG_PATHS = {
    **{key: paths[0] for key, paths in CASE_CONFIG_OVERRIDE_PATHS.items()},
    **{path: path for path in EDITABLE_PARAMETERS | READONLY_DISPLAY_PARAMETERS},
    "rainfall_mode": "rainfall",
    "rainfall_source": "rainfall",
    "manning_source": "rheology.n_manning",
    "water_table_source": "hydrology.depthwt_initial",
    "initial_infiltration_source": "hydrology.rizero_initial",
    "dfs_infiltration_variant": "hydrology.dfs_infiltration_variant",
    "dfs_face_flux_variant": "hydrology.dfs_face_flux_variant",
    "dfs_failure_source_variant": "hydrology.dfs_failure_source_variant",
    "outflow_point_source": "native_inputs.files.outflow",
    "inflow_source": "native_inputs.files.inflow",
}

LABELS = {
    "alpha1": "Quadratic rheology alpha1",
    "alpha2": "Quadratic rheology alpha2",
    "background_flux_offset": "Background infiltration offset",
    "beta1": "Quadratic rheology beta1",
    "beta2": "Quadratic rheology beta2",
    "coedepo": "Deposition coefficient",
    "cs": "Suspension coefficient",
    "d50": "Median particle diameter",
    "depth": "Soil depth / initial water table fallback",
    "dtmax": "Maximum timestep",
    "dtmin": "Minimum timestep",
    "dtd": "Rejected-step timestep decrement",
    "dti": "Accepted-step timestep increment",
    "kresis": "Viscous resistance coefficient",
    "lbstar": "Bottom layer thickness",
    "ltstar": "Top layer thickness",
    "manning_global": "Global Manning roughness",
    "min_slope_angle_deg": "Minimum slope angle threshold",
    "nzsb": "Bottom-layer sublayer count",
    "nzst": "Top-layer sublayer count",
    "rizero": "Initial infiltration fallback",
    "simul": "Simulation end time",
    "toldh": "Absolute depth-change limiter",
    "toldhp": "Relative depth-change limiter",
    "tout": "Output interval",
    "uww": "Water unit weight",
    "wavemax": "Dynamic-wave stability coefficient",
    "zones": "Spatial zone parameters",
    "zonfil": "Zone raster file",
    "hydrology.use_background_flux_offset": "Background infiltration offset",
    "hydrology.K_sat": "Saturated hydraulic conductivity",
    "soil.gamma_s": "Soil unit weight",
    "soil.c": "Cohesion",
    "soil.phi": "Friction angle",
    "soil.gamma_w": "Water unit weight",
    "rheology.n_manning": "Manning roughness",
    "rheology.limitfr": "Froude limiter",
    "rainfall_mode": "Rainfall mode",
    "rainfall_source": "Rainfall source",
    "rainfall.mode": "Rainfall mode",
    "rainfall.timeline": "Rainfall timeline",
    "rainfall.periods": "Rainfall periods",
    "manning_source": "Manning source",
    "manning.source": "Manning source",
    "water_table_source": "Initial water table source",
    "initial_infiltration_source": "Initial infiltration source",
    "dfs_infiltration_variant": "DFS infiltration variant",
    "dfs_face_flux_variant": "DFS face-flux variant",
    "dfs_failure_source_variant": "Failure-source variant",
    "outflow_point_source": "Outflow observation source",
    "inflow_source": "Inflow forcing source",
}


def _case_override_paths(field_name: str) -> List[str]:
    return list(CASE_CONFIG_OVERRIDE_PATHS.get(field_name, []))


def _runtime_status(row: Dict[str, Any]) -> str:
    evidence = row.get("evidence") or {}
    if row.get("consumed"):
        if evidence.get("input_state") == "config_fallback" or evidence.get("resolved_via_fallback"):
            return "config_fallback_consumed"
        return "production_consumed"
    if row.get("mapped"):
        status = str(row.get("status") or evidence.get("production_status") or "")
        if "partial" in status:
            return "partial"
        return "mapped_only"
    if row.get("parsed"):
        return "parsed_only"
    return "metadata_only"


def _meta_for(key: str) -> Dict[str, str]:
    return PARAMETER_META.get(key, {})


def _entry_from_audit(row: Dict[str, Any]) -> Dict[str, Any]:
    key = str(row.get("parameter"))
    evidence = row.get("evidence") or {}
    status = _runtime_status(row)
    meta = _meta_for(key)
    return {
        "key": key,
        "label": LABELS.get(key, key.replace("_", " ").replace(".", " / ")),
        "label_zh": meta.get("label_zh"),
        "abbrev": meta.get("abbrev"),
        "group": meta.get("group") or (CONFIG_PATHS.get(key) or key).split(".")[0],
        "config_path": CONFIG_PATHS.get(key),
        "parser_field": evidence.get("family") or meta.get("abbrev") or key,
        "runtime_consumer": evidence.get("runtime_stage") or CONFIG_PATHS.get(key),
        "activation_condition": evidence.get("activation_condition"),
        "runtime_status": status,
        "editable": key in EDITABLE_PARAMETERS and status in {
            "production_consumed",
            "config_fallback_consumed",
        },
        "output_evidence": row.get("output_evidence") or [],
        "evidence": evidence,
    }


def _unsupported_entries(provenance: Optional[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    reference_audit = (provenance or {}).get("reference_config_audit") or {}
    for row in reference_audit.get("unsupported_flags") or []:
        key = str(row.get("flag") or row.get("parameter") or "unsupported")
        yield {
            "key": key,
            "label": key.replace("_", " "),
            "config_path": None,
            "parser_field": key,
            "runtime_consumer": None,
            "activation_condition": row.get("activation_condition"),
            "runtime_status": "unsupported",
            "editable": False,
            "output_evidence": [],
            "evidence": row,
        }


def build_parameter_catalog(
    parameter_audit: Optional[Dict[str, Any]] = None,
    runtime_input_manifest: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a frontend-safe parameter catalog from runtime evidence."""
    rows = list((parameter_audit or {}).get("parameters") or [])
    catalog = [_entry_from_audit(row) for row in rows]
    catalog.extend(_unsupported_entries(provenance))

    seen = set()
    deduped = []
    for entry in catalog:
        key = entry["key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    status_counts: Dict[str, int] = {}
    for entry in deduped:
        status = entry["runtime_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "catalog_version": "taichi-flow-parameter-catalog-v1",
        "editable_statuses": ["production_consumed", "config_fallback_consumed"],
        "parameters": deduped,
        "status_counts": status_counts,
        "input_source_registry": (runtime_input_manifest or {}).get("input_source_registry", {}),
    }


def build_static_parameter_catalog() -> Dict[str, Any]:
    """Return the edda_in-aligned catalog before a case is parsed or a run starts."""
    parameters = []
    for key in sorted(EDITABLE_PARAMETERS | READONLY_DISPLAY_PARAMETERS):
        if key in STATIC_CATALOG_HIDDEN_ALIASES:
            continue
        meta = _meta_for(key)
        editable = key in EDITABLE_PARAMETERS
        parameters.append(
            {
                "key": key,
                "label": LABELS.get(key, key),
                "label_zh": meta.get("label_zh") or LABELS.get(key, key),
                "abbrev": meta.get("abbrev") or key.split(".")[-1],
                "group": meta.get("group") or key.split(".")[0],
                "config_path": CONFIG_PATHS.get(key) or key,
                "parser_field": meta.get("abbrev"),
                "runtime_consumer": CONFIG_PATHS.get(key) or key,
                "activation_condition": "direct_config_payload",
                "runtime_status": "production_consumed" if editable else "mapped_only",
                "editable": editable,
                "output_evidence": [],
                "evidence": {"source": "static_catalog", "edda_in": True},
            }
        )
    for spec in EDDA_SWITCH_REGISTRY:
        localized = EDDA_CONTROL_META_ZH.get(spec.key, {})
        parameters.append(
            {
                "key": spec.taichi_config_path,
                "control_key": spec.key,
                "control_family": "edda",
                "source_index": spec.source_index,
                "label": spec.key.replace("_", " ").title(),
                "label_zh": localized.get("label"),
                "description_zh": localized.get("description") or EDDA_RESTRICTION_MESSAGES_ZH.get(spec.status),
                "abbrev": spec.original_variable,
                "group": (
                    "compute_process"
                    if spec.group == "run_control"
                    else "compute_outputs"
                ),
                "config_path": spec.taichi_config_path,
                "parser_field": spec.taichi_parser_field,
                "runtime_consumer": spec.taichi_runtime_consumer,
                "activation_condition": spec.activation_condition,
                "runtime_status": spec.status,
                "status_label_zh": EDDA_STATUS_LABELS_ZH[spec.status],
                "editable": spec.frontend_policy == "editable",
                "frontend_policy": spec.frontend_policy,
                "value_type": spec.value_type,
                "allowed_values": list(spec.allowed_values),
                "status_reason": spec.status_reason,
                "source_stage": spec.consumption_stage,
                "dependencies": list(spec.dependencies),
                "dependency_paths": [
                    EDDA_SWITCH_BY_KEY[key].taichi_config_path
                    for key in spec.dependencies
                ],
                "affected_output_families": list(spec.affected_output_families),
                "original_variable": spec.original_variable,
                "output_evidence": list(spec.affected_output_families),
                "evidence": {
                    "source": "edda_switch_registry",
                    "registry_version": EDDA_SWITCH_REGISTRY_VERSION,
                    "fortran_read_location": spec.fortran_read_location,
                    "real_case_activation_evidence": spec.real_case_activation_evidence,
                },
            }
        )
    status_counts: Dict[str, int] = {}
    for entry in parameters:
        status_counts[entry["runtime_status"]] = status_counts.get(entry["runtime_status"], 0) + 1
    return {
        "catalog_version": "taichi-flow-parameter-catalog-v3",
        "editable_statuses": ["production_consumed", "config_fallback_consumed"],
        "parameters": parameters,
        "status_counts": status_counts,
        "input_source_registry": {},
        "control_registry": {
            "registry_version": EDDA_SWITCH_REGISTRY_VERSION,
            "entry_count": len(EDDA_SWITCH_REGISTRY),
            "editable_count": sum(
                spec.frontend_policy == "editable" for spec in EDDA_SWITCH_REGISTRY
            ),
            "restricted_count": sum(
                spec.frontend_policy != "editable" for spec in EDDA_SWITCH_REGISTRY
            ),
        },
    }


def build_case_config_interface(parsed: ReferenceConfigParseResult) -> Dict[str, Any]:
    """Build a parsed legacy case-config interface without constructing a solver."""
    audit = parsed.to_audit_dict()
    # Parsers and offline migration adapters may provide only the fields that
    # were present in a case.  Keep the catalog shape deterministic without
    # turning absent legacy values into editable runtime parameters.
    defaults = {
        "simul": 0.0,
        "tout": 0.0,
        "dtmin": 0.0,
        "dtmax": 0.0,
        "dti": 0.0,
        "dtd": 0.0,
        "toldh": 0.0,
        "toldhp": 0.0,
        "wavemax": 0.0,
        "rainfall_mode": "",
        "cri_mps": [],
        "capt_s": [],
        "manning_source": "",
        "manning_global": 0.0,
        "alpha1": 0.0,
        "beta1": 0.0,
        "alpha2": 0.0,
        "beta2": 0.0,
        "kresis": 0.0,
        "limitfr": 0.0,
        "shallown": 0.0,
        "d50": 0.0,
        "cvstar": 0.0,
        "coedepo": 0.0,
        "cs": 0.0,
        "nzsb": 0,
        "nzst": 0,
        "uww": 0.0,
        "ltstar_raw": 0.0,
        "lbstar": 0.0,
        "zmax": 0.0,
        "depth": 0.0,
        "rizero": 0.0,
        "min_slope_angle_deg": 0.0,
        "zones": {},
    }
    for name, default in defaults.items():
        if not hasattr(parsed, name):
            setattr(parsed, name, default)
    parsed_values = {
        "time": {
            "simul": parsed.simul,
            "tout": parsed.tout,
            "dtmin": parsed.dtmin,
            "dtmax": parsed.dtmax,
            "dti": parsed.dti,
            "dtd": parsed.dtd,
            "toldh": parsed.toldh,
            "toldhp": parsed.toldhp,
            "wavemax": parsed.wavemax,
        },
        "rainfall": {
            "mode": parsed.rainfall_mode,
            "cri_mps": parsed.cri_mps,
            "capt_s": parsed.capt_s,
            "periods": [
                {
                    "index": idx + 1,
                    "start_s": parsed.capt_s[idx] if idx < len(parsed.capt_s) else None,
                    "end_s": parsed.capt_s[idx + 1] if idx + 1 < len(parsed.capt_s) else None,
                    "cri_mps": cri,
                    "source": "rifil" if cri < 0 else "uniform_cri",
                }
                for idx, cri in enumerate(parsed.cri_mps)
            ],
        },
        "manning": {
            "source": parsed.manning_source,
            "global": parsed.manning_global,
        },
        "rheology": {
            "alpha1": parsed.alpha1,
            "beta1": parsed.beta1,
            "alpha2": parsed.alpha2,
            "beta2": parsed.beta2,
            "kresis": parsed.kresis,
            "manning_global": parsed.manning_global,
            "limitfr": parsed.limitfr,
            "shallown": parsed.shallown,
            "d50": parsed.d50,
            "cvstar": parsed.cvstar,
            "coedepo": parsed.coedepo,
            "cs": parsed.cs,
        },
        "double_layer": {
            "nzsb": parsed.nzsb,
            "nzst": parsed.nzst,
            "uww": parsed.uww,
            "ltstar": parsed.ltstar_raw,
            "lbstar": parsed.lbstar,
            "zmax": parsed.zmax,
            "depth": parsed.depth,
            "rizero": parsed.rizero,
            "min_slope_angle_deg": parsed.min_slope_angle_deg,
        },
        "zones": {
            str(zone_id): {
                "zone_id": zone.zone_id,
                "bottom": asdict(zone.bottom),
                "top": asdict(zone.top),
            }
            for zone_id, zone in parsed.zones.items()
        },
    }
    file_inputs: List[Dict[str, Any]] = []
    for family, ref in audit.get("file_inputs", {}).items():
        file_inputs.append(
            {
                "family": family,
                "raw_paths": ref.get("raw_paths") or [],
                "resolved_paths": ref.get("resolved_paths") or [],
                "exists": ref.get("exists") or [],
                "production_status": ref.get("production_status"),
                "activation_condition": ref.get("activation_condition"),
                "runtime_status": _file_runtime_status(ref),
                "editable": False,
                "notes": ref.get("notes"),
                "blocked_reason": ref.get("blocked_reason"),
                "expected_output_families": ref.get("expected_output_families") or [],
            }
        )

    parameters = []
    for field_name in audit.get("supported_fields") or []:
        override_paths = _case_override_paths(field_name)
        config_path = override_paths[0] if override_paths else CONFIG_PATHS.get(field_name)
        parameters.append(
            {
                "key": field_name,
                "label": LABELS.get(field_name, field_name),
                "config_path": config_path,
                "override_paths": override_paths,
                "parser_field": field_name,
                "runtime_consumer": config_path,
                "activation_condition": None,
                "runtime_status": "mapped_only",
                "editable": False,
                "output_evidence": [],
                "evidence": {
                    "source": "case_config_parse",
                    "override_payload_field": "overrides",
                    "override_paths": override_paths,
                },
            }
        )
    for field_name in audit.get("recognized_unsupported_fields") or []:
        parameters.append(
            {
                "key": field_name,
                "label": field_name,
                "config_path": None,
                "parser_field": field_name,
                "runtime_consumer": None,
                "activation_condition": None,
                "runtime_status": "unsupported",
                "editable": False,
                "output_evidence": [],
                "evidence": {"source": "case_config_parse"},
            }
        )

    return {
        "case_config_file": parsed.reference_config_file,
        "case_base_dir": parsed.reference_base_dir,
        "case_config_name": Path(parsed.reference_config_file).name,
        "file_inputs": file_inputs,
        "parsed_values": parsed_values,
        "parameter_catalog": {
            "catalog_version": "taichi-flow-case-config-catalog-v1",
            "editable_statuses": ["production_consumed", "config_fallback_consumed"],
            "parameters": parameters,
        },
        "runtime_status": {
            "source_mode": "legacy_case_config",
            "supported_field_count": len(audit.get("supported_fields") or []),
            "recognized_unsupported_field_count": len(audit.get("recognized_unsupported_fields") or []),
            "unrecognized_field_count": len(audit.get("unrecognized_fields") or []),
        },
        "audit": audit,
    }


def _file_runtime_status(ref: Dict[str, Any]) -> str:
    status = str(ref.get("production_status") or "")
    if "production-reachable" in status:
        return "production_consumed"
    if status == "partial":
        return "partial"
    if "recognized" in status:
        return "metadata_only"
    return "unsupported"
