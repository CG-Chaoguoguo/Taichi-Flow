import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { Layout, LayoutChangedMeta } from "react-resizable-panels";
import { RasterViewportProvider } from "../../contexts/RasterViewportContext";
import { isActiveScenario, useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { normalizeEditorLayoutPreferences, type EditorLayoutPreferencesV1 } from "../../layout/editorLayout";
import { TAICHI_FLOW_PREFERENCES_STORAGE_KEY } from "../../themePreference";
import {
  CollapsedPaneRail,
  ResizablePane,
  ResizablePaneGroup,
  ResizeHandle,
} from "../../components/layout/ResizablePaneGroup";
import { isVisualizableInput } from "../../constants/visualizableInputs";
import { VisualizationCanvas } from "../Calculate/VisualizationCanvas";
import { RainfallProcessEditor } from "../../components/RainfallProcessEditor";
import type { InputBinding, InputFile, RainfallPeriod, RainfallTimeline } from "../../types";
import type { WorkspaceModule } from "../Calculate/CalculateWorkspace";
import { ScenarioOutliner } from "./ScenarioOutliner";
import { InspectorPanel } from "./InspectorPanel";
import { BottomDock } from "./BottomDock";
import { canEditScenario } from "../../utils/scenarioEditability";

function selectionToModule(kind: string | undefined): WorkspaceModule {
  if (kind === "input") return "input";
  if (kind === "result") return "result";
  if (kind === "queue") return "run";
  return "parameter";
}

function layoutPixels(layout: Layout, panelId: string, groupSizePx: number) {
  return Math.round((layout[panelId] || 0) * groupSizePx / 100);
}

export function ProjectEditor() {
  const { projectId = "", scenarioId } = useParams<{ projectId: string; scenarioId?: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const queue = useTaichiFlowStore((state) => state.queue);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const layerVisibility = useTaichiFlowStore((state) => state.layerVisibility);
  const layerOrder = useTaichiFlowStore((state) => state.layerOrder);
  const setLayerVisibility = useTaichiFlowStore((state) => state.setLayerVisibility);
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const setEditorSelection = useTaichiFlowStore((state) => state.setEditorSelection);
  const setDockTab = useTaichiFlowStore((state) => state.setDockTab);
  const editorLayout = useTaichiFlowStore((state) => state.editorLayout);
  const updateEditorLayout = useTaichiFlowStore((state) => state.updateEditorLayout);
  const replaceEditorLayout = useTaichiFlowStore((state) => state.replaceEditorLayout);
  const updateScenario = useTaichiFlowStore((state) => state.updateScenario);
  const fetchScenarioConfiguration = useTaichiFlowStore((state) => state.fetchScenarioConfiguration);
  const uploadInputs = useTaichiFlowStore((state) => state.uploadInputs);
  const [canvasState, setCanvasState] = useState({ zoom: 1, offsetX: 0, offsetY: 0, selectedLayer: "" });
  const [workspaceMode, setWorkspaceMode] = useState<"canvas" | "rainfall">("canvas");
  const [draftPatch, setDraftPatch] = useState<Record<string, unknown>>({});
  const [draftBindings, setDraftBindings] = useState<InputBinding[]>([]);
  const [saving, setSaving] = useState(false);
  const [compactWindow, setCompactWindow] = useState(() => typeof window !== "undefined" && window.innerWidth < 1280);
  const layoutCommitTimer = useRef<number | undefined>(undefined);

  const scheduleLayoutUpdate = useCallback((updater: (current: EditorLayoutPreferencesV1) => EditorLayoutPreferencesV1) => {
    if (layoutCommitTimer.current) window.clearTimeout(layoutCommitTimer.current);
    layoutCommitTimer.current = window.setTimeout(() => {
      updateEditorLayout(updater);
      layoutCommitTimer.current = undefined;
    }, 150);
  }, [updateEditorLayout]);

  useEffect(() => () => {
    if (layoutCommitTimer.current) window.clearTimeout(layoutCommitTimer.current);
  }, []);

  useEffect(() => {
    const onWindowResize = () => setCompactWindow(window.innerWidth < 1280);
    window.addEventListener("resize", onWindowResize);
    return () => window.removeEventListener("resize", onWindowResize);
  }, []);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== TAICHI_FLOW_PREFERENCES_STORAGE_KEY || !event.newValue) return;
      try {
        const persisted = JSON.parse(event.newValue) as { state?: { editorLayout?: unknown } };
        if (persisted.state && "editorLayout" in persisted.state) {
          replaceEditorLayout(normalizeEditorLayoutPreferences(persisted.state.editorLayout));
        }
      } catch {
        // An invalid preference payload must not disturb the active editor.
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [replaceEditorLayout]);

  const togglePane = useCallback((key: keyof EditorLayoutPreferencesV1["collapsed"]) => {
    updateEditorLayout((current) => ({
      ...current,
      collapsed: { ...current.collapsed, [key]: !current.collapsed[key] },
    }));
  }, [updateEditorLayout]);

  const handleShellLayoutChanged = useCallback((layout: Layout, meta: LayoutChangedMeta, groupSizePx: number) => {
    if (!meta.isUserInteraction || !groupSizePx) return;
    const dockPx = layoutPixels(layout, "editor-dock", groupSizePx);
    scheduleLayoutUpdate((current) => ({
      ...current,
      dockPx: current.collapsed.dock ? current.dockPx : Math.max(160, Math.min(440, dockPx)),
    }));
  }, [scheduleLayoutUpdate]);

  const handleBodyLayoutChanged = useCallback((layout: Layout, meta: LayoutChangedMeta, groupSizePx: number) => {
    if (!meta.isUserInteraction || !groupSizePx) return;
    const outlinerPx = layoutPixels(layout, "editor-outliner", groupSizePx);
    const inspectorPx = layoutPixels(layout, "editor-inspector", groupSizePx);
    scheduleLayoutUpdate((current) => ({
      ...current,
      outer: {
        outlinerPx: current.collapsed.outliner ? current.outer.outlinerPx : Math.max(176, Math.min(360, outlinerPx)),
        inspectorPx: current.collapsed.inspector ? current.outer.inspectorPx : Math.max(300, Math.min(560, inspectorPx)),
      },
    }));
  }, [scheduleLayoutUpdate]);

  const handleInspectorLayoutChanged = useCallback((ratio: number, isUserInteraction: boolean) => {
    if (!isUserInteraction) return;
    scheduleLayoutUpdate((current) => ({
      ...current,
      inspectorAssetRatio: current.collapsed.inspectorDetails ? current.inspectorAssetRatio : Math.min(0.75, Math.max(0.25, ratio)),
    }));
  }, [scheduleLayoutUpdate]);

  const handleAssetLayoutChanged = useCallback((familyPx: number, isUserInteraction: boolean) => {
    if (!isUserInteraction) return;
    scheduleLayoutUpdate((current) => ({
      ...current,
      assetFamilyPx: current.collapsed.assetFamilies ? current.assetFamilyPx : Math.max(128, Math.min(280, familyPx)),
    }));
  }, [scheduleLayoutUpdate]);

  const focusedAssetId = canvasState.selectedLayer || null;

  const visibleLayers = useMemo(() => {
    const byId = new Map(inputFiles.map((file) => [file.file_id, file]));
    const ordered = layerOrder.map((id) => byId.get(id)).filter((file): file is NonNullable<typeof file> => Boolean(file));
    const extras = inputFiles.filter((file) => !layerOrder.includes(file.file_id));
    return [...ordered, ...extras]
      .filter((file) => isVisualizableInput(file) && layerVisibility[file.file_id] !== false)
      .map((file) => ({ fileId: file.file_id, name: file.name, family: file.family }));
  }, [inputFiles, layerOrder, layerVisibility]);

  useEffect(() => {
    const dock = searchParams.get("dock");
    if (dock === "assets" || dock === "queue" || dock === "terminal" || dock === "export") {
      setDockTab(dock);
    }
  }, [searchParams, setDockTab]);

  useEffect(() => {
    if (!scenarioId) return;
    // Route scenario changes only — Outliner may select inputs/queue without changing the URL.
    setEditorSelection({ kind: "scenario", scenarioId });
  }, [scenarioId, setEditorSelection]);

  useEffect(() => {
    if (!scenarioId || scenarios.length === 0) return;
    const routeScenario = scenarios.find((scenario) => scenario.scenario_id === scenarioId);
    if (routeScenario && isActiveScenario(routeScenario)) return;
    const next = scenarios.find(isActiveScenario);
    if (next) {
      setEditorSelection({ kind: "scenario", scenarioId: next.scenario_id });
      navigate(`/editor/${projectId}/scenarios/${next.scenario_id}`, { replace: true });
    } else {
      setEditorSelection({ kind: "input", family: "all" });
      navigate(`/editor/${projectId}`, { replace: true });
    }
  }, [navigate, projectId, scenarioId, scenarios, setEditorSelection]);

  const activeModule = useMemo(() => selectionToModule(editorSelection?.kind), [editorSelection?.kind]);
  const selectedScenario = useMemo(() => {
    if (scenarioId) return scenarios.find((scenario) => scenario.scenario_id === scenarioId && isActiveScenario(scenario));
    if (editorSelection?.kind === "scenario" || editorSelection?.kind === "result") {
      return scenarios.find((scenario) => scenario.scenario_id === editorSelection.scenarioId && isActiveScenario(scenario));
    }
    return undefined;
  }, [editorSelection, scenarioId, scenarios]);

  useEffect(() => {
    setDraftPatch({ ...(selectedScenario?.parameter_patch || {}) });
    setDraftBindings([...(selectedScenario?.input_bindings || [])]);
    setWorkspaceMode("canvas");
    if (selectedScenario) void fetchScenarioConfiguration(selectedScenario.scenario_id);
  }, [fetchScenarioConfiguration, selectedScenario?.scenario_id]);

  const baselinePeriods = selectedScenario?.parameter_baseline?.["rainfall.periods"];
  const draftPeriods = (Array.isArray(draftPatch["rainfall.periods"])
    ? draftPatch["rainfall.periods"]
    : Array.isArray(baselinePeriods) ? baselinePeriods : []) as RainfallPeriod[];
  const baselineTimeline = selectedScenario?.parameter_baseline?.["rainfall.timeline"];
  const draftTimeline = (draftPatch["rainfall.timeline"] ?? baselineTimeline) as RainfallTimeline | undefined;
  const simulationEndCandidate = Number(draftPatch["time.t_end"] ?? selectedScenario?.parameter_baseline?.["time.t_end"]);
  const draftSimulationEnd = Number.isFinite(simulationEndCandidate) ? simulationEndCandidate : null;
  const dirty = Boolean(selectedScenario) && (
    JSON.stringify(draftPatch) !== JSON.stringify(selectedScenario?.parameter_patch || {})
    || JSON.stringify(draftBindings) !== JSON.stringify(selectedScenario?.input_bindings || [])
  );

  const handleRainfallChange = (
    periods: RainfallPeriod[],
    bindings: InputBinding[],
    timeline?: RainfallTimeline,
    simulationEndS?: number,
  ) => {
    const rasterCount = periods.filter((period) => ["raster", "rifil", "raster_rifil"].includes(String(period.source))).length;
    const mode = rasterCount === 0 ? "uniform" : rasterCount === periods.length ? "raster" : "mixed";
    setDraftPatch((current) => {
      const next: Record<string, unknown> = { ...current, "rainfall.mode": mode, "rainfall.periods": periods };
      if (timeline) next["rainfall.timeline"] = timeline;
      if (simulationEndS != null) next["time.t_end"] = simulationEndS;
      return next;
    });
    setDraftBindings(bindings);
  };

  const saveScenario = async () => {
    if (!selectedScenario) return;
    setSaving(true);
    try {
      const saved = await updateScenario(selectedScenario.scenario_id, {
        parameter_patch: draftPatch,
        input_bindings: draftBindings,
        expected_version: selectedScenario.version || 1,
      });
      setDraftPatch({ ...(saved.parameter_patch || {}) });
      setDraftBindings([...(saved.input_bindings || [])]);
      await fetchScenarioConfiguration(saved.scenario_id);
    } finally {
      setSaving(false);
    }
  };

  const handleDraftChange = (next: Record<string, unknown>) => {
    setDraftPatch(next);
  };

  const handleBindingsChange = (next: InputBinding[]) => {
    setDraftBindings(next);
  };

  const selectedScenarioCanEdit = canEditScenario(selectedScenario, queue);

  const handleSelectScenario = (nextScenarioId: string) => {
    navigate(`/editor/${projectId}/scenarios/${nextScenarioId}`, { replace: true });
  };

  const handleScenarioRemoved = (_scenarioId: string, nextScenarioId?: string) => {
    if (!nextScenarioId) {
      setEditorSelection({ kind: "input", family: "all" });
      navigate(`/editor/${projectId}`, { replace: true });
    }
  };

  const focusAsset = (fileOrId: InputFile | string) => {
    const layerId = typeof fileOrId === "string" ? fileOrId : fileOrId.file_id;
    setLayerVisibility(layerId, true);
    setCanvasState((current) => ({ ...current, selectedLayer: layerId }));
  };

  if (!activeProject || activeProject.project_id !== projectId) {
    return (
      <div className="tf-empty-state tf-body" role="status">
        正在打开项目编辑器…
      </div>
    );
  }

  const focusPanels = workspaceMode === "rainfall" && compactWindow;
  const outlinerCollapsed = editorLayout.collapsed.outliner || focusPanels;
  const inspectorCollapsed = editorLayout.collapsed.inspector || focusPanels;
  const dockCollapsed = editorLayout.collapsed.dock || focusPanels;

  return (
    <RasterViewportProvider>
      <ResizablePaneGroup
        id="editor-shell"
        orientation="vertical"
        className={`tf-editor-layout${workspaceMode === "rainfall" ? " is-rainfall-mode" : ""}`}
        onLayoutChanged={handleShellLayoutChanged}
      >
        <ResizablePane id="editor-main" minSize={320} className="tf-editor-main-panel">
          <ResizablePaneGroup id="editor-body" orientation="horizontal" className="tf-editor-body" onLayoutChanged={handleBodyLayoutChanged}>
            <ResizablePane
              id="editor-outliner"
              defaultSize={editorLayout.outer.outlinerPx}
              minSize={176}
              maxSize={360}
              collapsed={editorLayout.collapsed.outliner}
              forceCollapsed={focusPanels}
              collapsedSize={36}
              groupResizeBehavior="preserve-pixel-size"
              className="tf-resizable-pane--outliner"
            >
              {outlinerCollapsed ? (
                <CollapsedPaneRail label="方案栏" direction="left" temporary={focusPanels} onExpand={focusPanels ? undefined : () => togglePane("outliner")} />
              ) : (
                <ScenarioOutliner
                  selectedScenarioId={scenarioId || scenarios.find(isActiveScenario)?.scenario_id}
                  onSelectScenario={handleSelectScenario}
                  onScenarioRemoved={handleScenarioRemoved}
                  onToggleCollapse={() => togglePane("outliner")}
                />
              )}
            </ResizablePane>
            <ResizeHandle
              id="editor-outliner-splitter"
              leadingPanelId="editor-outliner"
              label="方案栏与中央画布之间的调整条"
              leadingMinSize={176}
              leadingMaxSize={360}
              onToggleCollapse={focusPanels ? undefined : () => togglePane("outliner")}
            />
            <ResizablePane id="editor-viewport" minSize={360} className="tf-editor-viewport" groupResizeBehavior="preserve-relative-size">
              {workspaceMode === "rainfall" && selectedScenario ? (
                <RainfallProcessEditor
                  periods={draftPeriods}
                  bindings={draftBindings}
                  assets={inputFiles}
                  canEdit={selectedScenarioCanEdit}
                  timeline={draftTimeline}
                  simulationEndS={draftSimulationEnd}
                  onChange={handleRainfallChange}
                  onUpload={(files) => uploadInputs("rainfall", files)}
                  onClose={() => setWorkspaceMode("canvas")}
                />
              ) : (
                <VisualizationCanvas
                  projectId={projectId}
                  state={canvasState}
                  setState={setCanvasState}
                  activeModule={activeModule}
                  visibleLayers={visibleLayers}
                />
              )}
            </ResizablePane>
            <ResizeHandle
              id="editor-inspector-splitter"
              leadingPanelId="editor-viewport"
              label="中央画布与检视器之间的调整条"
              leadingMinSize={360}
              onToggleCollapse={focusPanels ? undefined : () => togglePane("inspector")}
            />
            <ResizablePane
              id="editor-inspector"
              defaultSize={editorLayout.outer.inspectorPx}
              minSize={300}
              maxSize="45vw"
              collapsed={editorLayout.collapsed.inspector}
              forceCollapsed={focusPanels}
              collapsedSize={36}
              groupResizeBehavior="preserve-pixel-size"
              className="tf-resizable-pane--inspector"
            >
              {inspectorCollapsed ? (
                <CollapsedPaneRail label="检视器" direction="right" temporary={focusPanels} onExpand={focusPanels ? undefined : () => togglePane("inspector")} />
              ) : (
                <InspectorPanel
                  scenarioId={scenarioId}
                  focusedAssetId={focusedAssetId}
                  onFocusLayer={focusAsset}
                  draftPatch={draftPatch}
                  draftBindings={draftBindings}
                  dirty={dirty}
                  saving={saving}
                   onDraftChange={handleDraftChange}
                   onBindingsChange={handleBindingsChange}
                  onSave={saveScenario}
                  onOpenRainfall={() => setWorkspaceMode("rainfall")}
                  onToggleCollapse={() => togglePane("inspector")}
                  inspectorDetailsCollapsed={editorLayout.collapsed.inspectorDetails}
                  inspectorAssetRatio={editorLayout.inspectorAssetRatio}
                  onToggleDetails={() => togglePane("inspectorDetails")}
                  onInspectorLayoutChanged={handleInspectorLayoutChanged}
                />
              )}
            </ResizablePane>
          </ResizablePaneGroup>
        </ResizablePane>
        <ResizeHandle
          id="editor-dock-splitter"
          leadingPanelId="editor-main"
          label="主工作区与底部资产坞之间的调整条"
          leadingMinSize={320}
          onToggleCollapse={focusPanels ? undefined : () => togglePane("dock")}
        />
        <ResizablePane
          id="editor-dock"
          defaultSize={editorLayout.dockPx}
          minSize={160}
          maxSize="52vh"
          collapsed={editorLayout.collapsed.dock}
          forceCollapsed={focusPanels}
          collapsedSize={36}
          groupResizeBehavior="preserve-pixel-size"
          className="tf-editor-dock-panel"
        >
          {dockCollapsed ? (
            <CollapsedPaneRail label="底部资产坞" direction="bottom" temporary={focusPanels} onExpand={focusPanels ? undefined : () => togglePane("dock")} />
          ) : (
            <BottomDock
              focusedAssetId={focusedAssetId}
              onFocusAsset={focusAsset}
              onToggleCollapse={() => togglePane("dock")}
              assetFamiliesCollapsed={editorLayout.collapsed.assetFamilies}
              onToggleAssetFamilies={() => togglePane("assetFamilies")}
              assetFamilyPx={editorLayout.assetFamilyPx}
              onAssetLayoutChanged={handleAssetLayoutChanged}
            />
          )}
        </ResizablePane>
      </ResizablePaneGroup>
    </RasterViewportProvider>
  );
}

export function EditorIndexRedirect() {
  // A project with no scenarios is still a valid asset-library workspace.  Do
  // not strand users on an empty redirect while they need to upload, select,
  // or delete draft assets before creating a calculation scenario.
  return <ProjectEditor />;
}
