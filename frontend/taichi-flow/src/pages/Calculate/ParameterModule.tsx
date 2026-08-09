import { FileDiff, RotateCcw, Search, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { parameterApi } from "../../api/taichiFlowAdapter";
import { Button } from "../../components/Button";
import { EffectiveParameterField } from "../../components/EffectiveParameterField";
import { ManningModeEditor } from "../../components/ManningModeEditor";
import { ParameterGroupSection } from "../../components/ParameterGroupSection";
import { deriveRainfallTimeline, regularTimeline, resizeRainfallTimeline } from "../../rainfallTimeline";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { InputBinding, ParameterCatalogEntry, ParameterImportPreview, RainfallPeriod, RainfallTimeline, Scenario, ValidationIssue, ValidationState } from "../../types";
import { hasHistoricalSnapshot } from "../../utils/scenarioEditability";

const EMPTY_VALIDATION_ISSUES: ValidationIssue[] = [];

function parseValue(value: string): number | boolean | string {
  if (value === "true") return true;
  if (value === "false") return false;
  if (value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return value;
}

const GROUP_LABELS: Record<string, string> = {
  time: "时间",
  hydrology: "水文",
  soil: "土体",
  rheology: "流变",
  erosion: "侵蚀",
  spatial_zones: "分区",
  inputs: "输入源",
  runtime: "运行时",
};

const GROUP_ORDER = ["time", "hydrology", "soil", "rheology", "erosion", "spatial_zones", "inputs", "runtime"];

const MODE_EDITOR_KEYS = new Set(["rainfall.mode", "rainfall.periods", "rainfall.timeline", "manning.source"]);
const UNIT_BY_KEY: Record<string, string> = {
  "time.t_start": "s",
  "time.t_end": "s",
  "time.dt_output": "s",
  "hydrology.rho_w": "kg/m³",
  "hydrology.viscosity": "Pa·s",
  "rheology.rho_s": "kg/m³",
  "rheology.d50": "m",
  "rheology.n_manning": "—",
};

function getPeriods(draftPatch: Record<string, unknown>, baseline: Record<string, unknown>): RainfallPeriod[] {
  const value = draftPatch["rainfall.periods"] ?? baseline["rainfall.periods"];
  return Array.isArray(value) ? value as RainfallPeriod[] : [];
}

function getTimeline(draftPatch: Record<string, unknown>, baseline: Record<string, unknown>, periods: RainfallPeriod[]): RainfallTimeline {
  const value = draftPatch["rainfall.timeline"] ?? baseline["rainfall.timeline"];
  if (value && typeof value === "object" && Array.isArray((value as RainfallTimeline).boundaries_s)) {
    return value as RainfallTimeline;
  }
  return deriveRainfallTimeline(periods);
}

export function ParameterModule({
  scenario,
  readOnly = false,
  draftPatch,
  draftBindings = [],
  onDraftChange,
  onBindingsChange = () => undefined,
  onOpenRainfall = () => undefined,
  validation,
}: {
  scenario: Scenario;
  readOnly?: boolean;
  draftPatch: Record<string, unknown>;
  draftBindings?: InputBinding[];
  onDraftChange: (patch: Record<string, unknown>) => void;
  onBindingsChange?: (bindings: InputBinding[]) => void;
  onOpenRainfall?: () => void;
  validation?: ValidationState | null;
  onSave?: () => Promise<void>;
}) {
  const catalog = useTaichiFlowStore((state) => state.parameterCatalog);
  const catalogLoading = useTaichiFlowStore((state) => Boolean(state.loading.parameters));
  const catalogError = useTaichiFlowStore((state) => state.errors.parameters || null);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const fetchParameterCatalog = useTaichiFlowStore((state) => state.fetchParameterCatalog);
  const fetchParameterTemplates = useTaichiFlowStore((state) => state.fetchParameterTemplates);
  const fetchScenarios = useTaichiFlowStore((state) => state.fetchScenarios);
  const fetchScenarioConfiguration = useTaichiFlowStore((state) => state.fetchScenarioConfiguration);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [search, setSearch] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<ParameterImportPreview | null>(null);
  const [importing, setImporting] = useState(false);
  const [pendingEndTime, setPendingEndTime] = useState<number | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(["time"]));
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!catalog) void fetchParameterCatalog();
  }, [catalog, fetchParameterCatalog]);

  const entries = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (catalog?.parameters || []).filter((entry) => {
      if (MODE_EDITOR_KEYS.has(entry.key)) return false;
      if (!(entry.editable || entry.label_zh || entry.abbrev)) return false;
      if (!needle) return true;
      return [entry.label, entry.label_zh, entry.abbrev, entry.key, entry.parser_field]
        .filter(Boolean).join(" ").toLowerCase().includes(needle);
    });
  }, [catalog, search]);

  const canEdit = !readOnly;
  const groups = useMemo(() => {
    const grouped = new Map<string, ParameterCatalogEntry[]>();
    for (const entry of entries) {
      const group = entry.group || entry.config_path?.split(".")[0] || "runtime";
      grouped.set(group, [...(grouped.get(group) || []), entry]);
    }
    return Array.from(grouped.entries()).sort(([left], [right]) => {
      const leftIndex = GROUP_ORDER.indexOf(left);
      const rightIndex = GROUP_ORDER.indexOf(right);
      return (leftIndex < 0 ? GROUP_ORDER.length : leftIndex) - (rightIndex < 0 ? GROUP_ORDER.length : rightIndex) || left.localeCompare(right);
    });
  }, [entries]);
  const validationIssues = validation?.issues ?? EMPTY_VALIDATION_ISSUES;
  const issueForEntry = (entry: ParameterCatalogEntry) => validationIssues.filter((issue) => issue.parameter_key === entry.key);
  const issueCountForGroup = (groupEntries: ParameterCatalogEntry[]) => groupEntries.reduce((count, entry) => count + issueForEntry(entry).length, 0);
  const autoExpandedGroups = useMemo(() => {
    const next = new Set<string>(["time"]);
    for (const [group, groupEntries] of groups) {
      if (groupEntries.some((entry) => draftPatch[entry.key] !== undefined) || issueCountForGroup(groupEntries) > 0) next.add(group);
    }
    return next;
  }, [draftPatch, groups, validationIssues]);
  useEffect(() => {
    setExpandedGroups(autoExpandedGroups);
  }, [scenario.scenario_id, autoExpandedGroups]);
  const periods = getPeriods(draftPatch, scenario.parameter_baseline || {});
  const rainfallTimeline = getTimeline(draftPatch, scenario.parameter_baseline || {}, periods);
  const uniformCount = periods.filter((period) => !["raster", "rifil", "raster_rifil"].includes(String(period.source))).length;
  const rasterCount = periods.length - uniformCount;
  const rainfallIssues = validationIssues.filter((issue) => issue.parameter_key?.startsWith("rainfall.") || issue.binding_key?.startsWith("rainfall."));
  const manningIssues = validationIssues.filter((issue) => issue.parameter_key?.startsWith("manning.") || issue.parameter_key === "rheology.n_manning" || issue.binding_key === "manning.raster");
  const reconciledTimeline = useMemo(() => {
    if (pendingEndTime == null) return { value: null, error: null };
    const interval = rainfallTimeline.interval_s
      ?? (rainfallTimeline.boundaries_s.length > 1 ? rainfallTimeline.boundaries_s[1] - rainfallTimeline.boundaries_s[0] : 0);
    try {
      return {
        value: regularTimeline(Number(rainfallTimeline.start_s ?? 0), pendingEndTime, Number(interval), "simulation_end_sync"),
        error: null,
      };
    } catch (reason) {
      return { value: null, error: reason instanceof Error ? reason.message : "无法按当前间隔重算降雨时段。" };
    }
  }, [pendingEndTime, rainfallTimeline]);

  const changeParameter = (entry: ParameterCatalogEntry, raw: string) => {
    const value = parseValue(raw);
    if (entry.key === "time.t_end" && typeof value === "number" && periods.length) {
      const currentEnd = Number(periods[periods.length - 1]?.end_s || 0);
      if (value !== currentEnd) {
        setPendingEndTime(value);
        return;
      }
    }
    onDraftChange({ ...draftPatch, [entry.key]: value });
  };

  const confirmEndTime = () => {
    if (pendingEndTime == null) return;
    if (!reconciledTimeline.value) return;
    const resized = resizeRainfallTimeline(periods, draftBindings, reconciledTimeline.value);
    onDraftChange({
      ...draftPatch,
      "time.t_end": pendingEndTime,
      "rainfall.timeline": reconciledTimeline.value,
      "rainfall.periods": resized.periods,
    });
    onBindingsChange(resized.bindings);
    setPendingEndTime(null);
  };

  const resetAllOverrides = () => {
    if (!canEdit) return;
    onDraftChange({});
    // Rainfall raster rows are template structure; reset only removes their
    // asset bindings and deliberately leaves DEM/terrain/soil bindings intact.
    onBindingsChange(draftBindings.filter((binding) => binding.role !== "rainfall-period"));
  };

  const previewImport = async (file: File) => {
    if (!activeProject) return;
    setImporting(true);
    try {
      setImportFile(file);
      setImportPreview(await parameterApi.previewImport(activeProject.project_id, scenario.scenario_id, file));
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "参数配置解析失败" });
    } finally {
      setImporting(false);
    }
  };

  const applyImport = async () => {
    if (!activeProject || !importFile || !importPreview) return;
    setImporting(true);
    try {
      await parameterApi.applyImport(activeProject.project_id, scenario.scenario_id, scenario.version || 1, importFile);
      await Promise.all([fetchScenarios(), fetchParameterTemplates(), fetchScenarioConfiguration(scenario.scenario_id)]);
      setImportPreview(null);
      setImportFile(null);
      addToast({ type: "success", message: "参数已导入；文件路径全部忽略，输入绑定未改变" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "参数导入失败" });
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="tf-module-body tf-stack tf-module-scroll tf-parameter-module" data-testid="parameter-module">
      <div className="tf-row tf-gap-2">
        <div className="tf-search-box tf-flex-1"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索中文名 / 缩写 / 键名…" /></div>
        <input ref={importInput} hidden type="file" accept=".txt,.in" onChange={(event) => { const file = event.target.files?.[0]; if (file) void previewImport(file); event.target.value = ""; }} />
        <Button size="small" icon={<Upload size={14} />} disabled={!canEdit || importing} onClick={() => importInput.current?.click()}>导入参数</Button>
      </div>
      <Button variant="ghost" size="small" icon={<RotateCcw size={14} />} disabled={!canEdit} onClick={resetAllOverrides}>重置全部覆盖</Button>
      {!canEdit ? <div className="tf-caption tf-text-tertiary">当前计算正在进行，参数与输入绑定暂时锁定。</div> : null}
      {canEdit && hasHistoricalSnapshot(scenario) ? <div className="tf-caption tf-text-tertiary">修改将形成新草稿，历史运行快照与结果不会改变。</div> : null}

      {importPreview ? (
        <section className="tf-import-preview">
          <div className="tf-row tf-gap-2"><FileDiff size={16} /><strong>参数差异预览</strong></div>
          <div className="tf-caption tf-text-tertiary">{importPreview.diff.length} 项变化 · 已忽略 {importPreview.ignored_file_references.count} 个文件路径引用</div>
          <div className="tf-import-diff-list">
            {importPreview.diff.slice(0, 12).map((item) => <div key={item.key}><span className="tf-mono">{item.key}</span><span>{String(item.before ?? "—")}</span><span>→</span><span>{String(item.after ?? "—")}</span></div>)}
            {importPreview.diff.length > 12 ? <div className="tf-caption">另有 {importPreview.diff.length - 12} 项…</div> : null}
          </div>
          <div className="tf-row tf-gap-2"><Button variant="ghost" size="small" onClick={() => setImportPreview(null)}>取消</Button><Button variant="primary" size="small" disabled={importing} onClick={() => void applyImport()}>确认覆盖参数</Button></div>
        </section>
      ) : null}

      {pendingEndTime != null ? (
        <section className="tf-time-reconcile">
          <strong>终止时间与降雨时间轴不一致</strong>
          <div className="tf-caption tf-text-tertiary">
            新模拟终止时间为 {pendingEndTime} s。请选择是否按现有间隔重新计算时段，系统不会静默拉长最后一段。
          </div>
          {reconciledTimeline.value ? (
            <div className="tf-caption">同步后为 {reconciledTimeline.value.period_count} 个时段，每段 {reconciledTimeline.value.interval_s} s。</div>
          ) : (
            <div className="tf-caption tf-text-danger">{reconciledTimeline.error}</div>
          )}
          <div className="tf-row tf-gap-2">
            <Button size="small" disabled={!reconciledTimeline.value} onClick={() => confirmEndTime()}>
              {pendingEndTime > Number(rainfallTimeline.end_s || 0) ? "扩展并重算时段" : "截断并重算时段"}
            </Button>
            <Button variant="ghost" size="small" onClick={() => setPendingEndTime(null)}>取消</Button>
          </div>
        </section>
      ) : null}

      <section className="tf-card tf-card-flush tf-rainfall-summary-card">
        <div className="tf-body tf-group-header tf-font-semibold">降雨过程</div>
        <div className="tf-card-body-sm tf-stack tf-gap-2">
          <div className="tf-rainfall-summary-metrics"><span><strong>{periods.length}</strong> 时段</span><span><strong>{uniformCount}</strong> 均匀</span><span><strong>{rasterCount}</strong> 栅格</span></div>
          <div className="tf-caption tf-text-tertiary">雨强默认按 mm/h 编辑，后端统一存储 m/s；栅格通过逐时段资产绑定表达。</div>
          <Button size="small" fullWidth disabled={!periods.length} onClick={onOpenRainfall}>在中央工作区编辑降雨过程</Button>
          {rainfallIssues[0] ? <div className="tf-caption tf-text-danger" role="status">{rainfallIssues[0].message}</div> : null}
        </div>
      </section>

      <ManningModeEditor
        draftPatch={draftPatch}
        baseline={scenario.parameter_baseline || {}}
        bindings={draftBindings}
        assets={inputFiles}
        onDraftChange={onDraftChange}
        onBindingsChange={onBindingsChange}
        canEdit={canEdit}
        readOnly={readOnly}
      />
      {manningIssues[0] ? <div className="tf-caption tf-text-danger" role="status">{manningIssues[0].message}</div> : null}

      {!catalog && (catalogLoading || !catalogError) ? <div className="tf-empty tf-body tf-text-tertiary" role="status">正在加载参数证据目录…</div> : null}
      {!catalog && catalogError ? (
        <div className="tf-empty tf-stack-sm" role="alert">
          <strong>参数目录加载失败</strong>
          <span className="tf-caption tf-text-tertiary">{catalogError}</span>
          <Button size="small" variant="secondary" onClick={() => void fetchParameterCatalog()}>重试</Button>
        </div>
      ) : null}
      {catalog && entries.length === 0 ? <div className="tf-empty tf-body tf-text-tertiary" role="status">未找到匹配的可编辑参数</div> : null}
      {catalog && groups.map(([group, groupEntries]) => (
        <ParameterGroupSection
          key={group}
          group={group}
          label={GROUP_LABELS[group] || group}
          fieldCount={groupEntries.length}
          modifiedCount={groupEntries.filter((entry) => draftPatch[entry.key] !== undefined).length}
          issueCount={issueCountForGroup(groupEntries)}
          expanded={search.trim().length > 0 || expandedGroups.has(group)}
          onToggle={() => setExpandedGroups((current) => {
            const next = new Set(current);
            if (next.has(group)) next.delete(group); else next.add(group);
            return next;
          })}
        >
            {groupEntries.map((entry) => {
              const defaultValue = scenario.parameter_baseline?.[entry.key];
              const overrideValue = draftPatch[entry.key];
              const effectiveValue = overrideValue === undefined ? defaultValue : overrideValue;
              return (
                <EffectiveParameterField
                  key={entry.key}
                  entry={entry}
                  defaultValue={defaultValue}
                  overrideValue={overrideValue}
                  effectiveValue={effectiveValue}
                  unit={UNIT_BY_KEY[entry.key]}
                  disabled={!canEdit}
                  onChange={(value) => changeParameter(entry, value)}
                  onReset={() => { const next = { ...draftPatch }; delete next[entry.key]; onDraftChange(next); }}
                />
              );
            })}
        </ParameterGroupSection>
      ))}
    </div>
  );
}
