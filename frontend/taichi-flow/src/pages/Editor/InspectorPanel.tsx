import { ArchiveRestore, Database, Play, Save, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { AssetBindingField } from "../../components/AssetBindingField";
import { Button } from "../../components/Button";
import { LegacyMigrationWizard } from "../../components/LegacyMigrationWizard";
import { RasterLayerInspector } from "../../components/RasterLayerInspector";
import { StatusBadge } from "../../components/StatusBadge";
import { ValidationSummary } from "../../components/ValidationSummary";
import { ALL_INPUT_FAMILY, DEFAULT_INPUT_FAMILY, INPUT_FAMILY_LABELS } from "../../constants/inputFamilies";
import {
  DEFAULT_RASTER_SYMBOLOGY,
  useRasterViewportOptional,
} from "../../contexts/RasterViewportContext";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { InputBinding, InputFile, Scenario } from "../../types";
import { InputModule } from "../Calculate/InputModule";
import { ParameterModule } from "../Calculate/ParameterModule";
import { ResultModule } from "../Calculate/ResultModule";
import { RunModule } from "../Calculate/RunModule";
import {
  CollapsedPaneRail,
  PanelCollapseButton,
  ResizablePane,
  ResizablePaneGroup,
  ResizeHandle,
} from "../../components/layout/ResizablePaneGroup";

const PREVIEW_SCENARIO: Scenario = {
  scenario_id: "",
  project_id: "",
  name: "未选择方案",
  input_revision_id: null,
  parameter_template_id: null,
  parameter_baseline: {},
  parameter_patch: {},
  effective_parameters: {},
  input_bindings: [],
  version: 1,
  status: "draft",
  progress: 0,
  latest_simulation_id: null,
  result_family_count: 0,
  file_count: 0,
  created_at: "",
  updated_at: "",
};

type InspectorTab = "parameters" | "bindings" | "run";

const BINDING_FIELDS: Array<{ key: string; label: string; family: InputFile["family"]; role: string }> = [
  { key: "dem.primary", label: "主 DEM", family: "dem", role: "primary" },
  { key: "zones.primary", label: "分区栅格", family: "zones", role: "zones" },
  { key: "slope.primary", label: "坡度栅格", family: "slope", role: "slope" },
  { key: "thickness.primary", label: "土层厚度", family: "thickness", role: "thickness" },
  { key: "groundwater.initial", label: "初始水深", family: "groundwater", role: "groundwater" },
  { key: "infiltration.initial", label: "入渗初值", family: "infiltration", role: "infiltration" },
];

type InspectorPanelProps = {
  scenarioId?: string;
  focusedAssetId?: string | null;
  onFocusLayer: (layerId: string) => void;
  draftPatch: Record<string, unknown>;
  draftBindings: InputBinding[];
  dirty: boolean;
  saving: boolean;
  onDraftChange: (patch: Record<string, unknown>) => void;
  onBindingsChange: (bindings: InputBinding[]) => void;
  onSave: () => Promise<void>;
  onOpenRainfall: () => void;
  onToggleCollapse?: () => void;
  inspectorDetailsCollapsed?: boolean;
  inspectorAssetRatio?: number;
  onToggleDetails?: () => void;
  onInspectorLayoutChanged?: (ratio: number, isUserInteraction: boolean) => void;
};

function RasterDetailsPane({ focusedAssetId }: { focusedAssetId?: string | null }) {
  const viewport = useRasterViewportOptional();
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const assetId = focusedAssetId || viewport?.activeLayerId || "";
  const file = inputFiles.find((item) => item.file_id === assetId);
  const profile = assetId && viewport ? viewport.profiles[assetId] : undefined;

  if (!viewport) {
    return (
      <div className="tf-inspector-details-empty tf-caption tf-text-tertiary" role="status">
        栅格视口未就绪
      </div>
    );
  }

  if (!assetId) {
    return (
      <div className="tf-inspector-details-empty tf-caption tf-text-tertiary" role="status">
        选择资产或点击地图识别像元
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="tf-inspector-details-empty tf-stack-sm" role="status">
        <div className="tf-body tf-font-medium">{file?.name || assetId}</div>
        <div className="tf-caption tf-text-tertiary">
          {file
            ? `${INPUT_FAMILY_LABELS[file.family] || file.family} · ${(file.size / 1024).toFixed(1)} KB · ${file.status}`
            : "该资产暂无可视化栅格档案"}
        </div>
      </div>
    );
  }

  return (
    <RasterLayerInspector
      profile={profile}
      identify={viewport.identify}
      identifyLoading={viewport.identifyLoading}
      symbology={viewport.symbology[profile.asset_id] || DEFAULT_RASTER_SYMBOLOGY}
      onSymbologyChange={(next) => viewport.setSymbologyForAsset(profile.asset_id, next)}
    />
  );
}

export function InspectorPanel({
  scenarioId,
  focusedAssetId = null,
  onFocusLayer,
  draftPatch,
  draftBindings,
  dirty,
  saving,
  onDraftChange,
  onBindingsChange,
  onSave,
  onOpenRainfall,
  onToggleCollapse,
  inspectorDetailsCollapsed = false,
  inspectorAssetRatio = 0.45,
  onToggleDetails,
  onInspectorLayoutChanged,
}: InspectorPanelProps) {
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const queue = useTaichiFlowStore((state) => state.queue);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const configurations = useTaichiFlowStore((state) => state.scenarioConfigurations);
  const setDockTab = useTaichiFlowStore((state) => state.setDockTab);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [tab, setTab] = useState<InspectorTab>("parameters");

  const scenarioFromSelection = editorSelection?.kind === "scenario" || editorSelection?.kind === "result"
    ? scenarios.find((item) => item.scenario_id === editorSelection.scenarioId)
    : undefined;
  const scenarioFromRoute = scenarioId ? scenarios.find((item) => item.scenario_id === scenarioId) : undefined;
  const queueItem = editorSelection?.kind === "queue" ? queue.find((item) => item.queue_item_id === editorSelection.queueItemId) : undefined;
  const scenarioFromQueue = queueItem ? scenarios.find((item) => item.scenario_id === queueItem.scenario_id) : undefined;
  const scenario = scenarioFromSelection || scenarioFromQueue || scenarioFromRoute;
  const displayScenario = scenario ?? PREVIEW_SCENARIO;
  const kind = editorSelection?.kind || (scenario ? "scenario" : "input");
  const selectedFamily = editorSelection?.kind === "input" ? editorSelection.family : DEFAULT_INPUT_FAMILY;
  const isLegacy = Boolean(scenario && !scenario.parameter_template_id);
  const canEdit = Boolean(scenario && !isLegacy && ["draft", "ready"].includes(scenario.status));
  const configuration = scenario ? configurations[scenario.scenario_id] : null;

  const title = kind === "input"
    ? `资产库 · ${selectedFamily === ALL_INPUT_FAMILY ? "全部文件" : INPUT_FAMILY_LABELS[selectedFamily] || selectedFamily}`
    : kind === "result" ? `结果 · ${displayScenario.name}`
      : kind === "queue" ? `队列 · ${queueItem?.scenario_name || "任务"}`
        : `方案 · ${displayScenario.name}`;

  const setBinding = (field: typeof BINDING_FIELDS[number], asset: InputFile) => {
    const next: InputBinding = { binding_key: field.key, asset_id: asset.file_id, family: field.family, role: field.role, active: true };
    const index = draftBindings.findIndex((item) => item.binding_key === field.key);
    onBindingsChange(index >= 0 ? draftBindings.map((item, offset) => offset === index ? next : item) : [...draftBindings, next]);
  };

  const showDetailsPane = kind === "input" || kind === "result";

  return (
    <aside className="tf-inspector" aria-label="属性检视">
      <div className="tf-inspector-header tf-inspector-header-actions">
        {onToggleCollapse ? <PanelCollapseButton label="检视器" collapsed={false} direction="right" onToggle={onToggleCollapse} /> : null}
        <div className="tf-flex-1 tf-ellipsis">{title}{dirty ? <span className="tf-unsaved-dot" title="有未保存修改">●</span> : null}</div>
        {scenario && kind !== "input" ? <StatusBadge variant={displayScenario.status} dot /> : null}
        {scenario && (kind === "scenario" || kind === "queue") ? (
          <Button
            size="small"
            variant="primary"
            icon={<Save size={14} />}
            disabled={!canEdit || !dirty || saving}
            data-qoder="save-scenario"
            onClick={() => void onSave().then(() => addToast({ type: "success", message: "方案参数与输入绑定已原子保存" })).catch((error) => addToast({ type: "error", message: error instanceof Error ? error.message : "保存失败" }))}
          >
            {saving ? "保存中" : "保存方案"}
          </Button>
        ) : null}
      </div>
      <ResizablePaneGroup
        id={`inspector-${kind}`}
        orientation="vertical"
        className={`tf-inspector-body${showDetailsPane ? " tf-inspector-split" : ""}`}
        onLayoutChanged={(layout, meta) => onInspectorLayoutChanged?.((layout["inspector-assets"] || inspectorAssetRatio * 100) / 100, meta.isUserInteraction)}
      >
        <ResizablePane
          id="inspector-assets"
          defaultSize={showDetailsPane ? `${inspectorAssetRatio * 100}%` : "100%"}
          minSize={showDetailsPane ? 96 : 0}
          maxSize={showDetailsPane ? "80%" : "100%"}
          className={showDetailsPane ? "tf-inspector-pane tf-inspector-pane--assets" : "tf-inspector-pane tf-inspector-pane--full"}
        >
          {kind === "input" ? (
            <InputModule
              selectedFamily={selectedFamily}
              readOnly={false}
              compact
              focusedAssetId={focusedAssetId}
              onFocusLayer={onFocusLayer}
            />
          ) : null}

          {(kind === "scenario" || kind === "queue") && scenario ? (
            <>
              <nav className="tf-inspector-tabs" aria-label="方案检视器标签">
                <button type="button" className={tab === "parameters" ? "is-active" : ""} onClick={() => setTab("parameters")}><SlidersHorizontal size={14} />参数</button>
                <button type="button" className={tab === "bindings" ? "is-active" : ""} onClick={() => setTab("bindings")}><Database size={14} />输入绑定</button>
                <button type="button" className={tab === "run" ? "is-active" : ""} onClick={() => setTab("run")}><Play size={14} />运行</button>
              </nav>

              {tab === "parameters" ? (
                isLegacy ? (
                  <div className="tf-module-body tf-stack tf-module-scroll">
                    <div className="tf-legacy-readonly-state" role="status">
                      <ArchiveRestore size={18} />
                      <strong>历史方案参数只读</strong>
                      <span>此方案仍按 edda_in 兼容链路运行。为避免把 -1 等内部哨兵值误显示为可编辑参数，请先通过显式迁移向导创建参数模板和输入绑定快照。</span>
                      <Button variant="secondary" size="small" onClick={() => setTab("bindings")}>前往迁移向导</Button>
                    </div>
                  </div>
                ) : (
                  <ParameterModule
                    scenario={displayScenario}
                    readOnly={!canEdit}
                    draftPatch={draftPatch}
                    draftBindings={draftBindings}
                    onDraftChange={onDraftChange}
                    onBindingsChange={onBindingsChange}
                    onOpenRainfall={onOpenRainfall}
                    validation={configuration?.validation}
                  />
                )
              ) : null}

              {tab === "bindings" ? (
                <div className="tf-module-body tf-stack tf-module-scroll">
                  <div className="tf-info-banner">方案只引用资产 ID；文件路径不会进入参数。</div>
                  <LegacyMigrationWizard scenario={scenario} />
                  {BINDING_FIELDS.map((field) => {
                    const binding = draftBindings.find((item) => item.binding_key === field.key);
                    return (
                      <AssetBindingField
                        key={field.key}
                        label={field.label}
                        pickerLabel={`选择${field.label} 资产`}
                        family={field.family}
                        binding={binding}
                        assets={inputFiles}
                        disabled={!canEdit}
                        onSelect={(asset) => setBinding(field, asset)}
                        onClear={() => onBindingsChange(draftBindings.map((item) => item.binding_key === field.key ? { ...item, active: false } : item))}
                      />
                    );
                  })}
                  <button type="button" className="tf-binding-summary-link" disabled={isLegacy} onClick={onOpenRainfall}>
                    <span>降雨时段绑定</span><strong>{draftBindings.filter((item) => item.role === "rainfall-period" && item.active).length}</strong><span>打开编辑器 →</span>
                  </button>
                  {isLegacy ? <div className="tf-validation-summary is-neutral">迁移完成后将执行结构化参数与输入绑定预检。</div> : <ValidationSummary validation={configuration?.validation} />}
                </div>
              ) : null}

              {tab === "run" ? (
                <div className="tf-inspector-section tf-stack">
                  {isLegacy ? <div className="tf-validation-summary is-neutral">历史方案保持只读兼容；请复制或迁移后再发起新运行。</div> : <ValidationSummary validation={configuration?.validation} />}
                  <RunModule scenario={displayScenario} readOnly={!configuration?.validation?.valid} />
                  <button type="button" className="tf-link-button" onClick={() => setDockTab("queue")}>打开队列</button>
                </div>
              ) : null}
            </>
          ) : null}

          {kind === "scenario" && !scenario ? <div className="tf-empty-state tf-body">请选择或创建方案以编辑参数。</div> : null}
          {kind === "result" ? <div className="tf-inspector-section"><ResultModule scenario={displayScenario} readOnly={!scenario} /></div> : null}
        </ResizablePane>

        {showDetailsPane ? (
          <>
            <ResizeHandle
              id="inspector-details-splitter"
              leadingPanelId="inspector-assets"
              label="检视器资产与数据详情之间的调整条"
              leadingMinSize={96}
              onToggleCollapse={onToggleDetails}
            />
            <ResizablePane
              id="inspector-details"
              defaultSize={`${(1 - inspectorAssetRatio) * 100}%`}
              minSize={96}
              maxSize="80%"
              collapsed={inspectorDetailsCollapsed}
              collapsedSize={36}
              className="tf-inspector-pane tf-inspector-pane--details"
            >
              {inspectorDetailsCollapsed ? (
                <CollapsedPaneRail label="数据详情" direction="bottom" onExpand={onToggleDetails} />
              ) : (
                <div className="tf-inspector-details-content" aria-label="图层数据">
                  <div className="tf-inspector-details-header tf-caption tf-font-semibold tf-text-secondary">数据</div>
                  <div className="tf-inspector-details-body">
                    <RasterDetailsPane focusedAssetId={focusedAssetId} />
                  </div>
                </div>
              )}
            </ResizablePane>
          </>
        ) : null}
      </ResizablePaneGroup>
    </aside>
  );
}
