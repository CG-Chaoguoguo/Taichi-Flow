import { Calculator, LockKeyhole, RotateCcw } from "lucide-react";
import type { EddaControlRegistrySummary, ParameterCatalogEntry } from "../types";
import { HelpTip } from "./HelpTip";

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function controlTitle(entry: ParameterCatalogEntry): string {
  return entry.label_zh || entry.label || entry.control_key || entry.key;
}

function currentValue(
  entry: ParameterCatalogEntry,
  baseline: Record<string, unknown>,
  draftPatch: Record<string, unknown>,
): unknown {
  return hasOwn(draftPatch, entry.key) ? draftPatch[entry.key] : baseline[entry.key];
}

export function EddaComputeControlsSection({
  entries,
  controlRegistry,
  baseline,
  draftPatch,
  canEdit,
  onDraftChange,
  title = "计算",
  subtitle = "原 EDDA 控制按语义证据门禁写入当前计算方案",
  overrideChipLabel = "方案覆盖",
  baselineChipLabel = "模板默认",
}: {
  entries: ParameterCatalogEntry[];
  controlRegistry: EddaControlRegistrySummary;
  baseline: Record<string, unknown>;
  draftPatch: Record<string, unknown>;
  canEdit: boolean;
  onDraftChange: (patch: Record<string, unknown>) => void;
  title?: string;
  subtitle?: string;
  overrideChipLabel?: string;
  baselineChipLabel?: string;
}) {
  const byPath = new Map(entries.map((entry) => [entry.key, entry]));
  const editable = entries.filter((entry) => entry.editable && entry.value_type === "boolean");
  const processControls = editable.filter((entry) => entry.group === "compute_process");
  const outputControls = editable.filter((entry) => entry.group === "compute_outputs");
  const restricted = entries.filter((entry) => !entry.editable);
  const snapshotComplete = baseline["edda.registry_version"] === controlRegistry.registry_version
    && entries.length === controlRegistry.entry_count
    && entries.every((entry) => hasOwn(baseline, entry.key) || hasOwn(draftPatch, entry.key));

  const renderControl = (entry: ParameterCatalogEntry) => {
    const title = controlTitle(entry);
    const checked = currentValue(entry, baseline, draftPatch) === true;
    const changed = hasOwn(draftPatch, entry.key);
    const missingDependencies = (entry.dependency_paths || []).filter(
      (path) => (hasOwn(draftPatch, path) ? draftPatch[path] : baseline[path]) !== true,
    );
    return (
      <div className={`tf-edda-control${changed ? " is-changed" : ""}`} key={entry.key} data-parameter-key={entry.key}>
        <div className="tf-edda-control-copy">
          <div className="tf-row tf-gap-1">
            <span className="tf-body tf-font-medium">{title}</span>
            {entry.description_zh ? <HelpTip content={entry.description_zh} /> : null}
            <span className={`tf-source-chip${changed ? " is-override" : ""}`}>{changed ? overrideChipLabel : baselineChipLabel}</span>
          </div>
          {missingDependencies.length ? (
            <div className="tf-caption tf-text-warning">
              需同时启用：{missingDependencies.map((path) => controlTitle(byPath.get(path) || { key: path, label: path, runtime_status: "", editable: false })).join("、")}
            </div>
          ) : null}
        </div>
        <div className="tf-edda-control-actions">
          {changed ? (
            <button
              type="button"
              className="tf-icon-button tf-icon-button-sm"
              aria-label={`重置${title}`}
              title="重置为模板默认值"
              disabled={!canEdit}
              onClick={() => {
                const next = { ...draftPatch };
                delete next[entry.key];
                onDraftChange(next);
              }}
            >
              <RotateCcw size={13} />
            </button>
          ) : null}
          <button
            type="button"
            role="switch"
            aria-label={title}
            aria-checked={checked}
            className="tf-switch"
            disabled={!canEdit || !snapshotComplete}
            onClick={() => onDraftChange({ ...draftPatch, [entry.key]: !checked })}
          >
            <span className="tf-switch-thumb" />
          </button>
        </div>
      </div>
    );
  };

  return (
    <section className="tf-card tf-card-flush tf-edda-compute-card" data-testid="edda-compute-controls">
      <header className="tf-edda-compute-header">
        <Calculator size={17} aria-hidden="true" />
        <div className="tf-flex-1">
          <div className="tf-row tf-gap-1">
            <h2 className="tf-body tf-font-semibold">{title}</h2>
            {subtitle ? <HelpTip content={subtitle} /> : null}
          </div>
        </div>
        <span className="tf-edda-control-count">{controlRegistry.editable_count} 项可编辑</span>
      </header>

      {!snapshotComplete ? (
        <div className="tf-banner tf-banner-warning" role="status">
          当前方案没有完整的 {controlRegistry.entry_count} 项控制快照。请基于最新模板新建方案，或重新导入 edda_in 参数后再编辑。
        </div>
      ) : null}

      <div className="tf-edda-control-groups">
        <section className="tf-edda-control-group" role="group" aria-label="计算过程">
          <div className="tf-edda-control-group-title"><span>计算过程</span><span>{processControls.length}</span></div>
          {processControls.map(renderControl)}
        </section>
        <section className="tf-edda-control-group" role="group" aria-label="结果输出">
          <div className="tf-edda-control-group-title"><span>结果输出</span><span>{outputControls.length}</span></div>
          {outputControls.map(renderControl)}
        </section>
      </div>

      {restricted.length ? (
        <details className="tf-edda-restricted">
          <summary><LockKeyhole size={14} aria-hidden="true" />受限能力（{restricted.length}）</summary>
          <div className="tf-edda-restricted-list">
            {restricted.map((entry) => (
              <div className="tf-edda-restricted-row" key={entry.key}>
                <div>
                  <strong className="tf-row tf-gap-1">
                    {controlTitle(entry)}
                    {entry.description_zh ? <HelpTip content={entry.description_zh} /> : null}
                  </strong>
                  <span className="tf-mono">{entry.original_variable || entry.control_key}</span>
                </div>
                <span>{entry.status_label_zh || entry.runtime_status}</span>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
