import type { InputFamily } from "../types";

export const ALL_INPUT_FAMILY = "all" as const;

export type InputFamilyFilter = InputFamily | typeof ALL_INPUT_FAMILY;

export const INPUT_FAMILIES: { id: InputFamily; label: string }[] = [
  { id: "dem", label: "地形栅格" },
  { id: "slope", label: "坡度栅格" },
  { id: "zones", label: "分区栅格" },
    { id: "thickness", label: "上层厚度" },
  { id: "trigger", label: "触发滑坡" },
  { id: "manning", label: "空间曼宁" },
  { id: "rainfall", label: "降雨文件" },
  { id: "groundwater", label: "地下水深" },
  { id: "infiltration", label: "初始入渗" },
  { id: "boundary", label: "边界文件" },
  { id: "outflow", label: "出流边界" },
  { id: "inflow", label: "入流过程" },
  { id: "monitoring", label: "监测点选择" },
  { id: "config", label: "参数配置" },
];

export const INPUT_FAMILY_LABELS = Object.fromEntries(
  INPUT_FAMILIES.map(({ id, label }) => [id, label]),
) as Record<string, string>;

INPUT_FAMILY_LABELS[ALL_INPUT_FAMILY] = "全部文件";

export const DEFAULT_INPUT_FAMILY: InputFamily = "dem";

export function isInputFamily(value: string): value is InputFamily {
  return INPUT_FAMILIES.some((item) => item.id === value);
}

export function isInputFamilyFilter(value: string): value is InputFamilyFilter {
  return value === ALL_INPUT_FAMILY || isInputFamily(value);
}
