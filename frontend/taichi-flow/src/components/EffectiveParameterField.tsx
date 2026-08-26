import { RotateCcw } from "lucide-react";
import type { ParameterCatalogEntry } from "../types";

function displayValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object") return Array.isArray(value) ? `${value.length} 项` : "结构化值";
  return String(value);
}

function zoneRows(value: unknown): Array<Record<string, unknown>> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.values(value as Record<string, Record<string, unknown>>)
    .filter((row) => row && typeof row === "object")
    .map((row) => row)
    .sort((a, b) => Number(a.zone_id ?? 0) - Number(b.zone_id ?? 0));
}

function formatZoneScalar(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  return String(value);
}

function ZonesParameterPreview({ value }: { value: unknown }) {
  const rows = zoneRows(value);
  if (!rows.length) {
    return <div className="tf-structured-value tf-mt-2">{displayValue(value)}</div>;
  }
  return (
    <div className="tf-structured-value tf-mt-2" data-testid="zones-cvero-preview">
      <div className="tf-text-tertiary tf-mb-1">分区参数（只读，含 cvero）</div>
      <div className="tf-overflow-auto">
        <table className="tf-table tf-table-compact">
          <thead>
            <tr>
              <th>区号</th>
              <th>kero</th>
              <th>ctao</th>
              <th>cvero</th>
              <th>K_sat</th>
              <th>phi</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.zone_id)}>
                <td>{formatZoneScalar(row.zone_id)}</td>
                <td>{formatZoneScalar(row.kero)}</td>
                <td>{formatZoneScalar(row.ctao)}</td>
                <td>{formatZoneScalar(row.cvero)}</td>
                <td>{formatZoneScalar(row.K_sat)}</td>
                <td>{formatZoneScalar(row.phi)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
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
  overrideChipLabel = "方案覆盖",
  baselineChipLabel = "模板默认",
  autoCapable = false,
  autoOptionLabel = "自动（按方案识别）",
  autoChipLabel = "自动识别",
  disabledValues = [],
  provenanceMode = "resolved",
  resetLabel = "重置为模板默认值",
  supportingText,
  saveState = "idle",
}: {
  entry: ParameterCatalogEntry;
  defaultValue: unknown;
  overrideValue: unknown;
  effectiveValue: unknown;
  unit?: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onReset: () => void;
  overrideChipLabel?: string;
  baselineChipLabel?: string;
  autoCapable?: boolean;
  autoOptionLabel?: string;
  autoChipLabel?: string;
  disabledValues?: string[];
  provenanceMode?: "resolved" | "deferred";
  resetLabel?: string;
  supportingText?: string;
  saveState?: "idle" | "saving" | "saved" | "error";
}) {
  const changed = overrideValue !== undefined;
  const title = entry.label_zh
    ? `${entry.label_zh}${entry.abbrev ? `（${entry.abbrev}）` : ""}`
    : entry.label;
  const allowedValues = Array.isArray(entry.allowed_values)
    ? entry.allowed_values.map((item) => String(item))
    : [];
  const labels = entry.allowed_value_labels_zh || {};
  const optionLabel = (option: string) => labels[option] || labels[option.toLowerCase()] || option;
  const isEnumSelect =
    entry.editable &&
    entry.value_type === "enum" &&
    allowedValues.length > 0 &&
    (effectiveValue == null || typeof effectiveValue === "string" || autoCapable);
  const selectValue = autoCapable && !changed
    ? ""
    : (displayValue(effectiveValue) === "—" ? "" : displayValue(effectiveValue));
  const chipLabel = autoCapable && !changed ? autoChipLabel : changed ? overrideChipLabel : baselineChipLabel;
  const isBoolean =
    entry.editable &&
    !isEnumSelect &&
    (entry.value_type === "boolean" || typeof effectiveValue === "boolean");
  const editableScalar =
    entry.editable &&
    !isEnumSelect &&
    !isBoolean &&
    (effectiveValue == null || ["string", "number"].includes(typeof effectiveValue));
  const isZonesPreview = entry.key === "spatial_zones.zones";
  const checked = effectiveValue === true;
  return (
    <div className={`tf-param-entry tf-effective-field${changed ? " is-changed" : ""}`} data-parameter-key={entry.key}>
      <div className="tf-row tf-justify-between tf-gap-2">
        <label className="tf-body tf-font-medium" htmlFor={`parameter-${entry.key}`}>
          {title}{unit ? <span className="tf-text-tertiary"> · {unit}</span> : null}
        </label>
        <span className={`tf-source-chip${changed ? " is-override" : ""}`}>{chipLabel}</span>
      </div>
      {isEnumSelect ? (
        <div className="tf-row tf-gap-1 tf-mt-2">
          <select
            id={`parameter-${entry.key}`}
            className="tf-input tf-flex-1"
            data-testid={`enum-select-${entry.key}`}
            value={selectValue}
            disabled={disabled || !entry.editable}
            onChange={(event) => {
              if (autoCapable && event.target.value === "") {
                onReset();
                return;
              }
              onChange(event.target.value);
            }}
          >
            {autoCapable ? <option value="">{autoOptionLabel}</option> : null}
            {allowedValues.map((option) => (
              <option key={option} value={option} disabled={disabledValues.includes(option)}>
                {optionLabel(option)}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="tf-icon-button tf-icon-button-sm"
            aria-label={`重置${title}`}
             title={resetLabel}
            disabled={disabled || !changed}
            onClick={onReset}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      ) : isBoolean ? (
        <div className="tf-row tf-gap-1 tf-mt-2 tf-justify-between">
          <button
            type="button"
            id={`parameter-${entry.key}`}
            role="switch"
            aria-label={title}
            aria-checked={checked}
            className="tf-switch"
            disabled={disabled || !entry.editable}
            onClick={() => onChange(checked ? "false" : "true")}
          >
            <span className="tf-switch-thumb" />
          </button>
          <button
            type="button"
            className="tf-icon-button tf-icon-button-sm"
            aria-label={`重置${title}`}
             title={resetLabel}
            disabled={disabled || !changed}
            onClick={onReset}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      ) : editableScalar ? (
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
             title={resetLabel}
            disabled={disabled || !changed}
            onClick={onReset}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      ) : isZonesPreview ? (
        <ZonesParameterPreview value={effectiveValue} />
      ) : (
        <div className="tf-structured-value tf-mt-2">{displayValue(effectiveValue)}</div>
      )}
      <div className="tf-parameter-provenance tf-mt-1">
        <span>默认：{provenanceMode === "deferred" ? "随方案解析" : isZonesPreview ? `${zoneRows(defaultValue).length || "—"} 区` : displayValue(defaultValue)}</span>
        <span>有效：{provenanceMode === "deferred" ? "随方案解析" : isZonesPreview ? `${zoneRows(effectiveValue).length || "—"} 区` : displayValue(effectiveValue)}</span>
        <span>{entry.editable ? "可编辑" : "只读"} · {entry.runtime_status}</span>
      </div>
      {supportingText ? <div className="tf-caption tf-text-tertiary tf-mt-1">{supportingText}</div> : null}
      {saveState === "saving" ? <div className="tf-caption tf-text-info tf-mt-1">正在保存…</div> : null}
      {saveState === "error" ? <div className="tf-caption tf-text-danger tf-mt-1">保存失败，已恢复上次确认值。</div> : null}
    </div>
  );
}
