import { FileDiff, RotateCcw, Search, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { parameterApi } from "../../api/taichiFlowAdapter";
import { Button } from "../../components/Button";
import { EffectiveParameterField } from "../../components/EffectiveParameterField";
import { EddaComputeControlsSection } from "../../components/EddaComputeControlsSection";
import { ManningModeEditor } from "../../components/ManningModeEditor";
import { ZoneSoilEditor, ZONE_TAKEN_OVER_KEYS, countSpatialZones } from "../../components/ZoneSoilEditor";
import { ParameterGroupSection } from "../../components/ParameterGroupSection";
import { isGateParameterKey } from "../../constants/computeGates";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { InputBinding, ParameterCatalogEntry, ParameterImportPreview, Scenario, ValidationIssue, ValidationState } from "../../types";

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

const MODE_EDITOR_KEYS = new Set(["rainfall.mode", "rainfall.periods", "rainfall.timeline", "manning.source", "spatial_zones.zones"]);
const UNIT_BY_KEY: Record<string, string> = {
  "time.t_start": "s",
  "time.t_end": "s",
  "time.dt_output": "s",
  "compute.numerical_observe_stride": "步",
  "hydrology.rho_w": "kg/m³",
  "hydrology.viscosity": "Pa·s",
  "rheology.rho_s": "kg/m³",
  "rheology.d50": "m",
  "rheology.n_manning": "—",
  "rheology.debrisflowmanning": "—",
  "rheology.cvlandslide": "—",
  "rheology.cvglacier": "—",
};

export function ParameterModule({
  scenario,
  readOnly = false,
  draftPatch,
  draftBindings = [],
  draftControls = {},
  onDraftChange,
  onBindingsChange = () => undefined,
  onControlsChange = () => undefined,
  validation,
}: {
  scenario: Scenario;
  readOnly?: boolean;
  draftPatch: Record<string, unknown>;
  draftBindings?: InputBinding[];
  draftControls?: Record<string, unknown>;
  onDraftChange: (patch: Record<string, unknown>) => void;
  onBindingsChange?: (bindings: InputBinding[]) => void;
  onControlsChange?: (controls: Record<string, unknown>) => void;
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
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(["time"]));
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!catalog) void fetchParameterCatalog();
  }, [catalog, fetchParameterCatalog]);

  const rainfallEnabled = (
    scenario.effective_parameters?.["edda.run_controls.simulate_rainfall"]
    ?? scenario.parameter_baseline?.["edda.run_controls.simulate_rainfall"]
  ) !== false;

  const entries = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (catalog?.parameters || []).filter((entry) => {
      if (entry.control_family === "edda" || isGateParameterKey(entry.key)) return false;
      if (MODE_EDITOR_KEYS.has(entry.key)) return false;
      if (entry.key === "time.t_end" && rainfallEnabled) return false;
      if (!(entry.editable || entry.label_zh || entry.abbrev)) return false;
      if (!needle) return true;
      return [entry.label, entry.label_zh, entry.abbrev, entry.key, entry.parser_field]
        .filter(Boolean).join(" ").toLowerCase().includes(needle);
    });
  }, [catalog, rainfallEnabled, search]);

  const canEdit = !readOnly && (scenario.status === "draft" || scenario.status === "ready");
  const zoneCount = countSpatialZones(
    draftPatch["spatial_zones.zones"] === undefined
      ? scenario.parameter_baseline?.["spatial_zones.zones"]
      : draftPatch["spatial_zones.zones"],
  );
  const multiZone = zoneCount > 1;
  const eddaEntries = useMemo(
    () => (catalog?.parameters || []).filter((entry) => entry.control_family === "edda"),
    [catalog],
  );
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
    if (zoneCount > 0) next.add("soil");
    for (const [group, groupEntries] of groups) {
      if (groupEntries.some((entry) => draftPatch[entry.key] !== undefined) || issueCountForGroup(groupEntries) > 0) next.add(group);
    }
    return next;
  }, [draftPatch, groups, validationIssues, zoneCount]);
  useEffect(() => {
    setExpandedGroups(autoExpandedGroups);
  }, [scenario.scenario_id, autoExpandedGroups]);
  const manningIssues = validationIssues.filter((issue) => issue.parameter_key?.startsWith("manning.") || issue.parameter_key === "rheology.n_manning" || issue.binding_key === "manning.raster");

  const changeParameter = (entry: ParameterCatalogEntry, raw: string) => {
    onDraftChange({ ...draftPatch, [entry.key]: parseValue(raw) });
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
      <Button variant="ghost" size="small" icon={<RotateCcw size={14} />} disabled={!canEdit} onClick={() => onDraftChange({})}>重置全部覆盖</Button>
      {!canEdit ? <div className="tf-caption tf-text-tertiary">当前方案不可变；请复制为新方案后再修改。</div> : null}

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
      <ZoneSoilEditor
        draftPatch={draftPatch}
        baseline={scenario.parameter_baseline || {}}
        onDraftChange={onDraftChange}
        canEdit={canEdit}
        readOnly={readOnly}
      />
      {scenario.configuration_ownership === "reference_case" && catalog?.control_registry && eddaEntries.length ? (
        <EddaComputeControlsSection
          entries={eddaEntries}
          controlRegistry={catalog.control_registry}
          baseline={scenario.parameter_baseline || {}}
          draftPatch={draftControls}
          canEdit={canEdit}
          onDraftChange={onControlsChange}
          title="Chamoli 计算控制"
          subtitle="原始 edda_in 快照归当前方案所有；BJ 全局设置不会覆盖这些值"
          overrideChipLabel="方案覆盖"
          baselineChipLabel="Chamoli 默认"
        />
      ) : null}
      {scenario.configuration_ownership === "reference_case" ? (
        <div className="tf-info-banner tf-caption">
          zfil → glacier.asc 已作为 thickness.primary 绑定；ltstar=-1 按原始 Chamoli 语义由栅格厚度链路处理，未把它误当成可编辑标量。
        </div>
      ) : null}
      {validationIssues.filter((issue) => issue.parameter_key === "spatial_zones.zones")[0] ? (
        <div className="tf-caption tf-text-danger" role="status">
          {validationIssues.filter((issue) => issue.parameter_key === "spatial_zones.zones")[0].message}
        </div>
      ) : null}

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
              const takenOver = multiZone && ZONE_TAKEN_OVER_KEYS.includes(entry.key as typeof ZONE_TAKEN_OVER_KEYS[number]);
              const fieldEntry = takenOver ? { ...entry, editable: false } : entry;
              const defaultValue = scenario.parameter_baseline?.[entry.key];
              const overrideValue = takenOver ? undefined : draftPatch[entry.key];
              const effectiveValue = overrideValue === undefined ? defaultValue : overrideValue;
              return (
                <EffectiveParameterField
                  key={entry.key}
                  entry={fieldEntry}
                  defaultValue={defaultValue}
                  overrideValue={overrideValue}
                  effectiveValue={effectiveValue}
                  unit={UNIT_BY_KEY[entry.key]}
                  disabled={!canEdit || takenOver}
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
