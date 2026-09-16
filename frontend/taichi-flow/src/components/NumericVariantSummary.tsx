import { VARIANT_GATE_KEYS } from "../constants/computeGates";
import type { ComputePolicyResolution, ParameterCatalogEntry } from "../types";

type VariantSource = "case_baseline" | "global_override" | "missing" | string;

function sourceChipLabel(source?: string): string {
  if (source === "scenario_override") return "当前方案覆盖";
  if (source === "global_override") return "全局覆盖";
  if (source === "case_baseline") return "案例基线";
  if (!source) return "缺失";
  return "缺失";
}

function resolveEntry(
  catalogEntries: ParameterCatalogEntry[] | undefined,
  key: string,
): ParameterCatalogEntry | undefined {
  return catalogEntries?.find((entry) => entry.key === key);
}

function valueLabelZh(entry: ParameterCatalogEntry | undefined, value: unknown): string {
  if (value == null || value === "") return "—";
  const text = String(value);
  const mapped = entry?.allowed_value_labels_zh?.[text];
  return mapped || text;
}

export function NumericVariantSummary({
  resolution,
  catalogEntries,
}: {
  resolution?: ComputePolicyResolution;
  catalogEntries?: ParameterCatalogEntry[];
}) {
  const variants = resolution?.numeric_variants || {};
  const rows = VARIANT_GATE_KEYS.map((key) => {
    const entry = resolveEntry(catalogEntries, key);
    const payload = variants[key];
    const source = (payload?.source as VariantSource | undefined) || undefined;
    const hasValue = payload != null && payload.value != null && String(payload.value).length > 0;
    return {
      key,
      labelZh: entry?.label_zh || entry?.label || key,
      valueZh: hasValue ? valueLabelZh(entry, payload?.value) : "—",
      source: hasValue ? source || "missing" : "missing",
    };
  });

  const overrideCount = rows.filter((row) => row.source === "global_override").length;
  const headerChip =
    !resolution
      ? "解析中"
      : rows.some((row) => row.source === "scenario_override")
        ? "含方案覆盖"
        : overrideCount > 0
        ? "含全局覆盖"
        : rows.every((row) => row.source === "missing")
          ? "缺失"
          : "案例基线";

  return (
    <div className="tf-card tf-card-flush" data-testid="numeric-variant-summary">
      <div className="tf-row tf-justify-between tf-gap-2">
        <span className="tf-body tf-font-medium">数值变种生效值</span>
        <span className={`tf-source-chip${overrideCount > 0 ? " is-override" : ""}`}>{headerChip}</span>
      </div>
      <div className="tf-stack-sm tf-mt-1" data-testid="numeric-variant-summary-list">
        {rows.map((row) => (
          <div className="tf-row tf-justify-between tf-gap-2" data-testid={`numeric-variant-row-${row.key}`} key={row.key}>
            <div className="tf-caption">
              <span className="tf-text-secondary">{row.labelZh}</span>
              <span className="tf-text-tertiary"> · </span>
              <span>{row.valueZh}</span>
            </div>
            <span className={`tf-source-chip${row.source === "global_override" ? " is-override" : ""}`}>
              {sourceChipLabel(row.source)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
