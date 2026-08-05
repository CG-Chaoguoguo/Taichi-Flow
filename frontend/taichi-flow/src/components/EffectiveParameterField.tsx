import { RotateCcw } from "lucide-react";
import type { ParameterCatalogEntry } from "../types";

function displayValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object") return Array.isArray(value) ? `${value.length} 项` : "结构化值";
  return String(value);
}

export function EffectiveParameterField({
  entry,
  defaultValue,
  overrideValue,
  effectiveValue,
  unit,
  disabled,
  onChange,
  onReset,
}: {
  entry: ParameterCatalogEntry;
  defaultValue: unknown;
  overrideValue: unknown;
  effectiveValue: unknown;
  unit?: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onReset: () => void;
}) {
  const changed = overrideValue !== undefined;
  const title = entry.label_zh
    ? `${entry.label_zh}${entry.abbrev ? `（${entry.abbrev}）` : ""}`
    : entry.label;
  const editableScalar = entry.editable && (effectiveValue == null || ["string", "number", "boolean"].includes(typeof effectiveValue));
  return (
    <div className={`tf-param-entry tf-effective-field${changed ? " is-changed" : ""}`} data-parameter-key={entry.key}>
      <div className="tf-row tf-justify-between tf-gap-2">
        <label className="tf-body tf-font-medium" htmlFor={`parameter-${entry.key}`}>
          {title}{unit ? <span className="tf-text-tertiary"> · {unit}</span> : null}
        </label>
        <span className={`tf-source-chip${changed ? " is-override" : ""}`}>{changed ? "方案覆盖" : "模板默认"}</span>
      </div>
      {editableScalar ? (
        <div className="tf-row tf-gap-1 tf-mt-2">
          <input
            id={`parameter-${entry.key}`}
            className="tf-input tf-flex-1"
            type={typeof effectiveValue === "number" ? "number" : "text"}
            step="any"
            value={displayValue(effectiveValue) === "—" ? "" : displayValue(effectiveValue)}
            disabled={disabled || !entry.editable}
            onChange={(event) => onChange(event.target.value)}
          />
          <button
            type="button"
            className="tf-icon-button tf-icon-button-sm"
            aria-label={`重置${title}`}
            title="重置为模板默认值"
            disabled={disabled || !changed}
            onClick={onReset}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      ) : (
        <div className="tf-structured-value tf-mt-2">{displayValue(effectiveValue)}</div>
      )}
      <div className="tf-parameter-provenance tf-mt-1">
        <span>默认：{displayValue(defaultValue)}</span>
        <span>有效：{displayValue(effectiveValue)}</span>
        <span>{entry.editable ? "可编辑" : "只读"} · {entry.runtime_status}</span>
      </div>
    </div>
  );
}
