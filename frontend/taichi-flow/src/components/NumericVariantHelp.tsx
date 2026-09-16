import { NUMERIC_VARIANT_HELP } from "../constants/numericVariantHelp";
import type { VARIANT_GATE_KEYS } from "../constants/computeGates";
import type { ParameterCatalogEntry } from "../types";
import "./NumericVariantHelp.css";

export function NumericVariantHelp({ entry, value, resolvedValue }: {
  entry: ParameterCatalogEntry;
  value: unknown;
  resolvedValue?: unknown;
}) {
  const help = NUMERIC_VARIANT_HELP[entry.key as typeof VARIANT_GATE_KEYS[number]];
  const automatic = value == null || value === "" || value === "auto";
  const selected = String(automatic ? resolvedValue : value);
  const explanation = help?.options[selected];
  const label = entry.allowed_value_labels_zh?.[selected] || selected;
  return (
    <span className="tf-numeric-variant-help">
      <strong>{automatic ? "自动（按当前方案识别）" : label}</strong>
      {automatic && explanation && <span>当前方案解析：{label}。以下说明对应此解析结果。</span>}
      {explanation ? (
        <>
          <span><b>计算原理</b>{explanation.principle}</span>
          <span><b>主要影响</b>{explanation.impact}</span>
          <span><b>适用条件</b>{explanation.applicability}</span>
        </>
      ) : automatic ? (
        <>
          <span>{help?.overview || entry.description_zh}</span>
          <span>按当前方案输入与 Fortran 源码解析；此处尚无可用的具体变体说明，实际计算以入队解析结果为准。</span>
          <span>选择具体选项可查看其计算原理与适用条件；保存后仅覆盖当前方案副本的识别结果。</span>
        </>
      ) : (
        <span>该选项暂无专属解释，请核对方案源码与参数目录。{entry.description_zh}</span>
      )}
    </span>
  );
}
