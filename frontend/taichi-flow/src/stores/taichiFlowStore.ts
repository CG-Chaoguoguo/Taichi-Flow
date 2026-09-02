import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { EMPTY_COMPUTE_POLICY_RESOLUTION, type AssetBatchDeleteResult, type AssetDeletePreview, type CaseConfigInterface, type ExportJob, type InputBinding, type InputFile, type InputRevision, type ParameterCatalog, type ParameterTemplate, type ProjectInfo, type QueueItem, type ResultFamily, type ResultMetadata, type Scenario, type ScenarioConfiguration, type SimulationRun, type SystemMetrics, type Toast, type ComputeGateDefaults } from "../types";
import { exportApi, inputApi, parameterApi, projectApi, queueApi, resultApi, scenarioApi, settingsApi, systemApi } from "../api/taichiFlowAdapter";
import { DEFAULT_INPUT_FAMILY, type InputFamilyFilter } from "../constants/inputFamilies";
import { isVisualizableInput } from "../constants/visualizableInputs";
import { applyTheme, TAICHI_FLOW_PREFERENCES_STORAGE_KEY, type ThemeMode } from "../themePreference";
import {
  DEFAULT_EDITOR_LAYOUT,
  normalizeEditorLayoutPreferences,
  type EditorLayoutPreferencesV1,
} from "../layout/editorLayout";

type LoadingState = Record<string, boolean>;
type ErrorState = Record<string, string | null>;
export type CanvasPreviewMode = "downsample" | "full";

export type RasterPreviewMeta = {
  blobUrl: string;
  width: number;
  height: number;
  bounds: { xmin: number; ymin: number; xmax: number; ymax: number };
  min: number;
  max: number;
  nodata: number | null;
  capped: boolean;
  mode: string;
  status: "ready" | "error";
  error?: string;
};

export type ScenarioUpdateDraft = {
  name?: string;
  parameter_patch?: Record<string, unknown>;
  input_revision_id?: string | null;
  input_bindings?: InputBinding[];
  parameter_template_id?: string | null;
  control_overrides?: Record<string, unknown>;
  expected_version?: number;
};

export type EditorSelection =
  | { kind: "input"; family: InputFamilyFilter }
  | { kind: "scenario"; scenarioId: string }
  | { kind: "queue"; queueItemId: string }
  | { kind: "result"; scenarioId: string };

export type DockTab = "assets" | "queue" | "terminal" | "export" | null;

export type LaunchState = {
  status: "idle" | "loading" | "ready" | "error";
  progress: number;
  currentStep: string;
  error?: string;
};

export const LAUNCH_STEPS = [
  { key: "open", label: "打开项目目录" },
  { key: "inputs", label: "加载输入文件" },
  { key: "scenarios", label: "加载参数方案" },
  { key: "queue", label: "同步模拟队列" },
  { key: "ready", label: "准备编辑器" },
] as const;

interface TaichiFlowStore {
  activeProject: ProjectInfo | null;
  activeProjectId: string | null;
  projectHistory: ProjectInfo[];
  recentProjectIds: string[];
  theme: ThemeMode;
  serviceOnline: boolean;
  metrics: SystemMetrics;
  parameterCatalog: ParameterCatalog | null;
  computeGateDefaults: ComputeGateDefaults | null;
  parameterTemplates: ParameterTemplate[];
  scenarioConfigurations: Record<string, ScenarioConfiguration>;
  caseConfigInterface: CaseConfigInterface | null;
  toasts: Toast[];
  scenarios: Scenario[];
  queue: QueueItem[];
  inputFiles: InputFile[];
  inputRevisions: InputRevision[];
  layerVisibility: Record<string, boolean>;
  layerOrder: string[];
  canvasPreviewMode: CanvasPreviewMode;
  rasterPreviews: Record<string, RasterPreviewMeta>;
  resultFamilies: Record<string, ResultFamily[]>;
  resultMetadata: Record<string, ResultMetadata>;
  exports: ExportJob[];
  runningSimulations: Record<string, SimulationRun>;
  loading: LoadingState;
  errors: ErrorState;
  launchState: LaunchState;
  editorSelection: EditorSelection | null;
  dockTab: DockTab;
  editorLayout: EditorLayoutPreferencesV1;
  setTheme: (theme: ThemeMode) => void;
  setActiveProject: (project: ProjectInfo | null, options?: { hydrate?: boolean }) => void;
  removeFromHistory: (projectId: string) => void;
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
  createProject: (name: string, rootPath: string, description?: string) => Promise<ProjectInfo>;
  openProject: (rootPath: string) => Promise<ProjectInfo>;
  launchProject: (projectId: string) => Promise<void>;
  closeProject: () => void;
  setEditorSelection: (selection: EditorSelection | null) => void;
  setInputFamily: (family: InputFamilyFilter) => void;
  setDockTab: (tab: DockTab) => void;
  updateEditorLayout: (updater: (current: EditorLayoutPreferencesV1) => EditorLayoutPreferencesV1) => void;
  replaceEditorLayout: (layout: EditorLayoutPreferencesV1) => void;
  resetEditorLayout: () => void;
  reorderLayer: (fromId: string, toId: string) => void;
  setCanvasPreviewMode: (mode: CanvasPreviewMode) => void;
  fetchRasterPreview: (fileId: string) => Promise<RasterPreviewMeta | null>;
  clearRasterPreviews: () => void;
  fetchProjectList: () => Promise<ProjectInfo[]>;
  fetchScenarios: () => Promise<void>;
  createScenario: (name: string, baseScenarioId?: string) => Promise<Scenario>;
  updateScenario: (scenarioId: string, updates: ScenarioUpdateDraft) => Promise<Scenario>;
  duplicateScenario: (scenarioId: string) => Promise<Scenario>;
  archiveScenario: (scenarioId: string) => Promise<void>;
  deleteScenario: (scenarioId: string) => Promise<void>;
  fetchInputFiles: () => Promise<void>;
  fetchInputRevisions: () => Promise<void>;
  uploadInput: (family: string, file: File) => Promise<InputFile>;
  uploadInputs: (family: string, files: File[]) => Promise<InputFile[]>;
  uploadInputFromPath: (family: string, path: string) => Promise<InputFile>;
  previewInputDeletion: (fileIds: string[]) => Promise<AssetDeletePreview>;
  deleteInputFiles: (fileIds: string[]) => Promise<AssetBatchDeleteResult>;
  deleteInputFile: (fileId: string) => Promise<void>;
  setLayerVisibility: (fileId: string, visible: boolean) => void;
  toggleLayerVisibility: (fileId: string) => void;
  createInputRevision: (uploadIds: string[], versionTag?: string) => Promise<InputRevision>;
  fetchQueue: () => Promise<void>;
  enqueueScenario: (scenarioId: string, runtimeProfile?: string) => Promise<void>;
  reorderQueue: (itemId: string, newPosition: number) => Promise<void>;
  cancelQueueItem: (itemId: string) => Promise<void>;
  stopRunningItem: (itemId: string) => Promise<void>;
  retryQueueItem: (itemId: string) => Promise<void>;
  fetchResultFamilies: (simulationId: string) => Promise<void>;
  fetchResultMetadata: (simulationId: string) => Promise<void>;
  createExport: (scenarioId: string, simulationId: string, options: Partial<ExportJob>) => Promise<ExportJob>;
  fetchExports: () => Promise<void>;
  refreshMetrics: () => Promise<void>;
  checkService: () => Promise<void>;
  fetchParameterCatalog: () => Promise<void>;
  fetchComputeGateDefaults: () => Promise<void>;
  saveComputeGateDefaults: (values: Record<string, unknown>) => Promise<void>;
  fetchParameterTemplates: () => Promise<void>;
  fetchScenarioConfiguration: (scenarioId: string) => Promise<ScenarioConfiguration | null>;
  fetchCaseConfigInterface: (revisionId?: string | null) => Promise<CaseConfigInterface | null>;
  clearCaseConfigInterface: () => void;
  startPolling: () => () => void;
}

const safeStorage = createJSONStorage(() => {
  try {
    return window.localStorage;
  } catch {
    return {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    } as unknown as Storage;
  }
});

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : "请求失败");
const id = () => `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

export const useTaichiFlowStore = create<TaichiFlowStore>()(
  persist(
    (set, get) => ({
      activeProject: null,
      activeProjectId: null,
      projectHistory: [],
      recentProjectIds: [],
      theme: "dark",
      serviceOnline: false,
      metrics: { cpu_percent: null, gpu_percent: null, gpu_name: null },
      parameterCatalog: null,
      computeGateDefaults: null,
      parameterTemplates: [],
      scenarioConfigurations: {},
      caseConfigInterface: null,
      toasts: [],
      scenarios: [],
      queue: [],
      inputFiles: [],
      inputRevisions: [],
      layerVisibility: {},
      layerOrder: [],
      canvasPreviewMode: "downsample",
      rasterPreviews: {},
      resultFamilies: {},
      resultMetadata: {},
      exports: [],
      runningSimulations: {},
      loading: {},
      errors: {},
      launchState: { status: "idle", progress: 0, currentStep: "" },
      editorSelection: null,
      dockTab: "assets",
      editorLayout: normalizeEditorLayoutPreferences(DEFAULT_EDITOR_LAYOUT),

      setTheme: (theme) => {
        set({ theme });
        applyTheme(theme);
      },
      setActiveProject: (project, options) => {
        const hydrate = options?.hydrate !== false;
        set({ activeProject: project, activeProjectId: project?.project_id || null });
        if (!project) return;
        set((state) => ({
          projectHistory: [project, ...state.projectHistory.filter((item) => item.project_id !== project.project_id)].slice(0, 8),
          recentProjectIds: [project.project_id, ...state.recentProjectIds.filter((id) => id !== project.project_id)].slice(0, 8),
        }));
        if (!hydrate) return;
        void get().fetchScenarios();
        void get().fetchInputFiles();
        void get().fetchInputRevisions();
        void get().fetchParameterTemplates();
        void get().fetchQueue();
        void get().fetchExports();
      },
      removeFromHistory: (projectId) => set((state) => ({
        projectHistory: state.projectHistory.filter((project) => project.project_id !== projectId),
        recentProjectIds: state.recentProjectIds.filter((id) => id !== projectId),
      })),
      addToast: (toast) => {
        const toastId = id();
        set((state) => ({ toasts: [...state.toasts, { ...toast, id: toastId }] }));
        window.setTimeout(() => get().removeToast(toastId), 4000);
      },
      removeToast: (toastId) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== toastId) })),
      setEditorSelection: (selection) => set({ editorSelection: selection }),
      setInputFamily: (family) => set({ editorSelection: { kind: "input", family } }),
      setDockTab: (tab) => set({ dockTab: tab }),
      updateEditorLayout: (updater) => set((state) => ({ editorLayout: normalizeEditorLayoutPreferences(updater(state.editorLayout)) })),
      replaceEditorLayout: (layout) => set({ editorLayout: normalizeEditorLayoutPreferences(layout) }),
      resetEditorLayout: () => set({ editorLayout: normalizeEditorLayoutPreferences(DEFAULT_EDITOR_LAYOUT) }),
      reorderLayer: (fromId, toId) => {
        if (fromId === toId) return;
        set((state) => {
          const order = [...state.layerOrder];
          const fromIndex = order.indexOf(fromId);
          const toIndex = order.indexOf(toId);
          if (fromIndex < 0 || toIndex < 0) return state;
          order.splice(fromIndex, 1);
          order.splice(toIndex, 0, fromId);
          return { layerOrder: order };
        });
      },
      setCanvasPreviewMode: (mode) => {
        const previous = get().rasterPreviews;
        for (const meta of Object.values(previous)) {
          if (meta.blobUrl) URL.revokeObjectURL(meta.blobUrl);
        }
        set({ canvasPreviewMode: mode, rasterPreviews: {} });
      },
      clearRasterPreviews: () => {
        const previous = get().rasterPreviews;
        for (const meta of Object.values(previous)) {
          if (meta.blobUrl) URL.revokeObjectURL(meta.blobUrl);
        }
        set({ rasterPreviews: {} });
      },
      fetchRasterPreview: async (fileId) => {
        const project = get().activeProject;
        if (!project) return null;
        const cached = get().rasterPreviews[fileId];
        if (cached?.status === "ready" && cached.mode === get().canvasPreviewMode) return cached;
        try {
          const preview = await inputApi.fetchRasterPreview(project.project_id, fileId, get().canvasPreviewMode);
          const meta: RasterPreviewMeta = { ...preview, status: "ready" };
          set((state) => {
            const previous = state.rasterPreviews[fileId];
            if (previous?.blobUrl && previous.blobUrl !== meta.blobUrl) URL.revokeObjectURL(previous.blobUrl);
            return { rasterPreviews: { ...state.rasterPreviews, [fileId]: meta } };
          });
          return meta;
        } catch (error) {
          const meta: RasterPreviewMeta = {
            blobUrl: "",
            width: 0,
            height: 0,
            bounds: { xmin: 0, ymin: 0, xmax: 1, ymax: 1 },
            min: 0,
            max: 1,
            nodata: null,
            capped: false,
            mode: get().canvasPreviewMode,
            status: "error",
            error: errorMessage(error),
          };
          set((state) => ({ rasterPreviews: { ...state.rasterPreviews, [fileId]: meta } }));
          return meta;
        }
      },

      createProject: async (name, rootPath, description) => {
        const project = await projectApi.create({ name, root_path: rootPath, description });
        get().setActiveProject(project, { hydrate: false });
        get().addToast({ type: "success", message: `项目“${name}”已创建` });
        return project;
      },
      openProject: async (rootPath) => {
        const project = await projectApi.import({ root_path: rootPath });
        get().setActiveProject(project, { hydrate: false });
        return project;
      },
      launchProject: async (projectId) => {
        const total = LAUNCH_STEPS.length;
        const setStep = (index: number, key: string) => {
          set({
            launchState: {
              status: "loading",
              progress: Math.round(((index + 1) / total) * 100),
              currentStep: key,
            },
          });
        };
        set({
          launchState: { status: "loading", progress: 0, currentStep: "open" },
          editorSelection: null,
          dockTab: "assets",
          scenarios: [],
          inputFiles: [],
          queue: [],
          layerOrder: [],
          layerVisibility: {},
          scenarioConfigurations: {},
        });
        try {
          setStep(0, "open");
          let project =
            get().activeProject?.project_id === projectId
              ? get().activeProject
              : get().projectHistory.find((item) => item.project_id === projectId) || null;
          if (!project) {
            const projects = (await projectApi.list()).projects;
            project = projects.find((item) => item.project_id === projectId) || null;
          }
          if (!project) throw new Error("未找到项目，请从启动器重新打开");
          const opened = await projectApi.import({ root_path: project.root_path });
          get().setActiveProject(opened, { hydrate: false });

          setStep(1, "inputs");
          await get().fetchInputFiles();
          await get().fetchInputRevisions();

          setStep(2, "scenarios");
          await get().fetchScenarios();
          await get().fetchParameterTemplates();

          setStep(3, "queue");
          await get().fetchQueue();

          setStep(4, "ready");
          await get().fetchExports();
          const scenarios = get().scenarios;
          if (scenarios[0]) {
            set({ editorSelection: { kind: "scenario", scenarioId: scenarios[0].scenario_id } });
          } else {
            set({ editorSelection: { kind: "input", family: DEFAULT_INPUT_FAMILY } });
          }
          set({ launchState: { status: "ready", progress: 100, currentStep: "ready" } });
        } catch (error) {
          set({
            launchState: {
              status: "error",
              progress: get().launchState.progress,
              currentStep: get().launchState.currentStep,
              error: errorMessage(error),
            },
          });
          throw error;
        }
      },
      closeProject: () => {
        get().clearRasterPreviews();
        set({
          activeProject: null,
          activeProjectId: null,
          scenarios: [],
          queue: [],
          inputFiles: [],
          inputRevisions: [],
          parameterTemplates: [],
          scenarioConfigurations: {},
          layerVisibility: {},
          layerOrder: [],
          resultFamilies: {},
          exports: [],
          editorSelection: null,
          dockTab: "assets",
          launchState: { status: "idle", progress: 0, currentStep: "" },
        });
      },
      fetchProjectList: async () => {
        try {
          const projects = (await projectApi.list()).projects;
          const activeId = get().activeProjectId;
          const active = projects.find((project) => project.project_id === activeId);
          if (active && !get().activeProject) get().setActiveProject(active, { hydrate: false });
          const recentIds = get().recentProjectIds;
          const recentProjects = recentIds.map((id) => projects.find((project) => project.project_id === id)).filter((project): project is ProjectInfo => Boolean(project));
          set({ projectHistory: recentProjects, serviceOnline: true });
          return projects;
        } catch (error) {
          set((state) => ({ serviceOnline: false, errors: { ...state.errors, projects: errorMessage(error) } }));
          return [];
        }
      },

      fetchScenarios: async () => {
        const project = get().activeProject;
        if (!project) return;
        set((state) => ({ loading: { ...state.loading, scenarios: true }, errors: { ...state.errors, scenarios: null } }));
        try {
          set({ scenarios: await scenarioApi.listScenarios(project.project_id) });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, scenarios: errorMessage(error) } }));
        } finally {
          set((state) => ({ loading: { ...state.loading, scenarios: false } }));
        }
      },
      createScenario: async (name, baseScenarioId) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const scenario = await scenarioApi.createScenario(project.project_id, name, baseScenarioId);
        set((state) => ({ scenarios: [...state.scenarios, scenario] }));
        return scenario;
      },
      updateScenario: async (scenarioId, updates) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const scenario = await scenarioApi.updateScenario(project.project_id, scenarioId, updates);
        set((state) => ({
          scenarios: state.scenarios.map((item) => (item.scenario_id === scenarioId ? scenario : item)),
          scenarioConfigurations: {
            ...state.scenarioConfigurations,
            [scenarioId]: {
              scenario_id: scenarioId,
              parameter_template_id: scenario.parameter_template_id,
              baseline: scenario.parameter_baseline || {},
              overrides: scenario.parameter_patch || {},
              control_overrides: scenario.control_overrides || {},
              configuration_ownership: scenario.configuration_ownership,
              case_fingerprint: scenario.case_fingerprint,
              effective: scenario.effective_parameters || {},
              compute_policy_resolution: scenario.compute_policy_resolution
                || state.scenarioConfigurations[scenarioId]?.compute_policy_resolution
                || EMPTY_COMPUTE_POLICY_RESOLUTION,
              bindings: scenario.input_bindings || [],
              validation: state.scenarioConfigurations[scenarioId]?.validation || { valid: false, errors: [], warnings: [] },
              version: scenario.version || 1,
            },
          },
        }));
        return scenario;
      },
      duplicateScenario: async (scenarioId) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const scenario = await scenarioApi.duplicateScenario(project.project_id, scenarioId);
        set((state) => ({ scenarios: [...state.scenarios, scenario] }));
        return scenario;
      },
      archiveScenario: async (scenarioId) => {
        const project = get().activeProject;
        if (!project) return;
        const scenario = await scenarioApi.archiveScenario(project.project_id, scenarioId);
        set((state) => ({ scenarios: state.scenarios.map((item) => (item.scenario_id === scenarioId ? scenario : item)) }));
      },
      deleteScenario: async (scenarioId) => {
        const project = get().activeProject;
        if (!project) return;
        await scenarioApi.deleteScenario(project.project_id, scenarioId);
        set((state) => ({ scenarios: state.scenarios.filter((item) => item.scenario_id !== scenarioId) }));
      },

      fetchInputFiles: async () => {
        const project = get().activeProject;
        if (!project) return;
        try {
          const files = await inputApi.listInputFiles(project.project_id);
          set((state) => {
            const nextVisibility = { ...state.layerVisibility };
            const liveIds = new Set(files.map((file) => file.file_id));
            for (const fileId of Object.keys(nextVisibility)) {
              if (!liveIds.has(fileId)) delete nextVisibility[fileId];
            }
            let hasVisibleRaster = files.some(
              (file) => isVisualizableInput(file) && nextVisibility[file.file_id] === true,
            );
            const defaultRasterId = files.find((file) => file.family === "dem" && isVisualizableInput(file))?.file_id;
            for (const file of files) {
              if (isVisualizableInput(file) && nextVisibility[file.file_id] === undefined) {
                const visibleByDefault = !hasVisibleRaster && file.file_id === defaultRasterId;
                nextVisibility[file.file_id] = visibleByDefault;
                hasVisibleRaster = hasVisibleRaster || visibleByDefault;
              }
            }
            const keptOrder = state.layerOrder.filter((fileId) => liveIds.has(fileId));
            const keptSet = new Set(keptOrder);
            const appended = files.map((file) => file.file_id).filter((fileId) => !keptSet.has(fileId));
            const nextPreviews = { ...state.rasterPreviews };
            for (const fileId of Object.keys(nextPreviews)) {
              if (!liveIds.has(fileId)) {
                if (nextPreviews[fileId]?.blobUrl) URL.revokeObjectURL(nextPreviews[fileId].blobUrl);
                delete nextPreviews[fileId];
              }
            }
            return {
              inputFiles: files,
              layerVisibility: nextVisibility,
              layerOrder: [...keptOrder, ...appended],
              rasterPreviews: nextPreviews,
            };
          });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, inputs: errorMessage(error) } }));
        }
      },
      fetchInputRevisions: async () => {
        const project = get().activeProject;
        if (!project) return;
        try {
          set({ inputRevisions: await inputApi.listInputRevisions(project.project_id) });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, revisions: errorMessage(error) } }));
        }
      },
      uploadInput: async (family, file) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const uploaded = await inputApi.upload(project.project_id, family, file);
        if (isVisualizableInput(uploaded)) {
          set((state) => ({ layerVisibility: { ...state.layerVisibility, [uploaded.file_id]: true } }));
        }
        await get().fetchInputFiles();
        return uploaded;
      },
      uploadInputs: async (family, files) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        if (!files.length) return [];
        const uploaded = await inputApi.uploadBatch(project.project_id, family, files);
        await get().fetchInputFiles();
        return uploaded;
      },
      uploadInputFromPath: async (family, path) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const uploaded = await inputApi.uploadFromPath(project.project_id, family, path);
        if (isVisualizableInput(uploaded)) {
          set((state) => ({ layerVisibility: { ...state.layerVisibility, [uploaded.file_id]: true } }));
        }
        await get().fetchInputFiles();
        return uploaded;
      },
      previewInputDeletion: async (fileIds) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        return inputApi.previewDelete(project.project_id, fileIds);
      },
      deleteInputFiles: async (fileIds) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const result = await inputApi.batchDelete(project.project_id, fileIds);
        const deleted = new Set(result.deleted_ids);
        set((state) => {
          const nextVisibility = { ...state.layerVisibility };
          const nextPreviews = { ...state.rasterPreviews };
          for (const fileId of deleted) {
            delete nextVisibility[fileId];
            const preview = state.rasterPreviews[fileId];
            if (preview?.blobUrl) URL.revokeObjectURL(preview.blobUrl);
            delete nextPreviews[fileId];
          }
          return {
            layerVisibility: nextVisibility,
            layerOrder: state.layerOrder.filter((id) => !deleted.has(id)),
            rasterPreviews: nextPreviews,
          };
        });
        await Promise.all([get().fetchInputFiles(), get().fetchScenarios(), get().fetchQueue()]);
        await Promise.all(get().scenarios.map((scenario) => get().fetchScenarioConfiguration(scenario.scenario_id)));
        return result;
      },
      deleteInputFile: async (fileId) => {
        await get().deleteInputFiles([fileId]);
      },
      setLayerVisibility: (fileId, visible) => {
        set((state) => ({ layerVisibility: { ...state.layerVisibility, [fileId]: visible } }));
      },
      toggleLayerVisibility: (fileId) => {
        set((state) => ({
          layerVisibility: {
            ...state.layerVisibility,
            [fileId]: !(state.layerVisibility[fileId] ?? true),
          },
        }));
      },
      createInputRevision: async (uploadIds, versionTag) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const revision = await inputApi.createRevision(project.project_id, { upload_ids: uploadIds, version_tag: versionTag });
        await get().fetchInputRevisions();
        await get().fetchScenarios();
        return revision;
      },

      fetchQueue: async () => {
        const project = get().activeProject;
        if (!project) return;
        try {
          set({ queue: await queueApi.getQueue(project.project_id) });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, queue: errorMessage(error) } }));
        }
      },
      enqueueScenario: async (scenarioId, runtimeProfile) => {
        const project = get().activeProject;
        if (!project) return;
        await queueApi.enqueueScenario(project.project_id, scenarioId, runtimeProfile);
        await get().fetchQueue();
        await get().fetchScenarios();
        set({ dockTab: "queue" });
      },
      reorderQueue: async (itemId, newPosition) => {
        const project = get().activeProject;
        if (!project) return;
        set({ queue: await queueApi.reorderQueue(project.project_id, itemId, newPosition) });
      },
      cancelQueueItem: async (itemId) => {
        const project = get().activeProject;
        if (!project) return;
        await queueApi.cancelQueueItem(project.project_id, itemId);
        await get().fetchQueue();
        await get().fetchScenarios();
      },
      stopRunningItem: async (itemId) => {
        const project = get().activeProject;
        if (!project) return;
        await queueApi.stopRunningItem(project.project_id, itemId);
        await get().fetchQueue();
        await get().fetchScenarios();
      },
      retryQueueItem: async (itemId) => {
        const project = get().activeProject;
        if (!project) return;
        await queueApi.retryQueueItem(project.project_id, itemId);
        await get().fetchQueue();
        await get().fetchScenarios();
      },

      fetchResultFamilies: async (simulationId) => {
        const project = get().activeProject;
        if (!project) return;
        set((state) => ({ loading: { ...state.loading, [`results:${simulationId}`]: true }, errors: { ...state.errors, results: null } }));
        try {
          const families = await resultApi.listResultFamilies(project.project_id, simulationId);
          set((state) => ({ resultFamilies: { ...state.resultFamilies, [simulationId]: families } }));
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, results: errorMessage(error) } }));
        } finally {
          set((state) => ({ loading: { ...state.loading, [`results:${simulationId}`]: false } }));
        }
      },
      fetchResultMetadata: async (simulationId) => {
        const project = get().activeProject;
        if (!project) return;
        const loadingKey = `resultMetadata:${simulationId}`;
        set((state) => ({ loading: { ...state.loading, [loadingKey]: true }, errors: { ...state.errors, resultMetadata: null } }));
        try {
          const metadata = await resultApi.metadata(project.project_id, simulationId);
          set((state) => ({ resultMetadata: { ...state.resultMetadata, [simulationId]: metadata } }));
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, resultMetadata: errorMessage(error) } }));
        } finally {
          set((state) => ({ loading: { ...state.loading, [loadingKey]: false } }));
        }
      },
      createExport: async (scenarioId, simulationId, options) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const job = await exportApi.createExport(project.project_id, scenarioId, simulationId, options);
        set((state) => ({ exports: [job, ...state.exports] }));
        return job;
      },
      fetchExports: async () => {
        const project = get().activeProject;
        if (!project) return;
        try {
          set({ exports: await exportApi.getExports(project.project_id) });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, exports: errorMessage(error) } }));
        }
      },
      refreshMetrics: async () => {
        try {
          set({ metrics: await systemApi.metrics(), serviceOnline: true });
        } catch (error) {
          set((state) => ({ serviceOnline: false, errors: { ...state.errors, metrics: errorMessage(error) } }));
        }
      },
      checkService: async () => {
        try {
          await systemApi.health();
          set({ serviceOnline: true });
        } catch {
          set({ serviceOnline: false });
        }
      },
      fetchParameterCatalog: async () => {
        set((state) => ({ loading: { ...state.loading, parameters: true }, errors: { ...state.errors, parameters: null } }));
        try {
          set({ parameterCatalog: await systemApi.parameterCatalog() });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, parameters: errorMessage(error) } }));
        } finally {
          set((state) => ({ loading: { ...state.loading, parameters: false } }));
        }
      },
      fetchComputeGateDefaults: async () => {
        set((state) => ({ loading: { ...state.loading, computeGates: true }, errors: { ...state.errors, computeGates: null } }));
        try {
          set({ computeGateDefaults: await settingsApi.getComputeGates() });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, computeGates: errorMessage(error) } }));
        } finally {
          set((state) => ({ loading: { ...state.loading, computeGates: false } }));
        }
      },
      saveComputeGateDefaults: async (values) => {
        set((state) => ({ loading: { ...state.loading, computeGates: true }, errors: { ...state.errors, computeGates: null } }));
        try {
          set({ computeGateDefaults: await settingsApi.putComputeGates(values) });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, computeGates: errorMessage(error) } }));
          throw error;
        } finally {
          set((state) => ({ loading: { ...state.loading, computeGates: false } }));
        }
      },
      fetchParameterTemplates: async () => {
        const projectId = get().activeProjectId;
        if (!projectId) return;
        try {
          set({ parameterTemplates: await parameterApi.listTemplates(projectId) });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, parameterTemplates: errorMessage(error) } }));
        }
      },
      fetchScenarioConfiguration: async (scenarioId) => {
        const projectId = get().activeProjectId;
        if (!projectId) return null;
        try {
          const configuration = await scenarioApi.getConfiguration(projectId, scenarioId);
          set((state) => ({
            scenarioConfigurations: { ...state.scenarioConfigurations, [scenarioId]: configuration },
          }));
          return configuration;
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, scenarioConfiguration: errorMessage(error) } }));
          return null;
        }
      },
      fetchCaseConfigInterface: async (revisionId) => {
        const projectId = get().activeProjectId;
        if (!projectId) {
          set({ caseConfigInterface: null });
          return null;
        }
        let resolvedRevisionId = revisionId || null;
        if (!resolvedRevisionId) {
          const revisions = get().inputRevisions;
          const ready = revisions.find((item) => item.status === "ready") || revisions[0];
          resolvedRevisionId = ready?.revision_id || null;
        }
        if (!resolvedRevisionId) {
          set({ caseConfigInterface: null });
          return null;
        }
        try {
          const iface = await inputApi.getConfigInterface(projectId, resolvedRevisionId);
          set({ caseConfigInterface: iface });
          return iface;
        } catch (error) {
          set((state) => ({
            caseConfigInterface: null,
            errors: { ...state.errors, caseConfig: errorMessage(error) },
          }));
          return null;
        }
      },
      clearCaseConfigInterface: () => set({ caseConfigInterface: null }),
      startPolling: () => {
        let visible = !document.hidden;
        const onVisibility = () => { visible = !document.hidden; };
        document.addEventListener("visibilitychange", onVisibility);
        void get().fetchProjectList();
        void get().refreshMetrics();
        void get().fetchParameterCatalog();
        const metricsTimer = window.setInterval(() => { void get().refreshMetrics(); void get().checkService(); }, 3000);
        const dataTimer = window.setInterval(() => {
          if (visible && get().activeProject) {
            void get().fetchQueue();
            void get().fetchScenarios();
            void get().fetchExports();
          }
        }, 1500);
        return () => {
          window.clearInterval(metricsTimer);
          window.clearInterval(dataTimer);
          document.removeEventListener("visibilitychange", onVisibility);
        };
      },
    }),
    {
      name: TAICHI_FLOW_PREFERENCES_STORAGE_KEY,
      storage: safeStorage,
      partialize: (state) => ({
        theme: state.theme,
        activeProjectId: state.activeProjectId,
        recentProjectIds: state.recentProjectIds,
        canvasPreviewMode: state.canvasPreviewMode,
        editorLayout: state.editorLayout,
      }),
      merge: (persisted, current) => {
        const saved = persisted as {
          theme?: ThemeMode;
          activeProjectId?: unknown;
          recentProjectIds?: unknown;
          projectHistory?: unknown;
          canvasPreviewMode?: CanvasPreviewMode;
          editorLayout?: unknown;
        };
        const recent = Array.isArray(saved.recentProjectIds) ? saved.recentProjectIds : [];
        const history = Array.isArray(saved.projectHistory) ? saved.projectHistory : [];
        const savedIds = (recent.length ? recent : history).filter((id): id is string => typeof id === "string");
        const previewMode = saved.canvasPreviewMode === "full" || saved.canvasPreviewMode === "downsample" ? saved.canvasPreviewMode : current.canvasPreviewMode;
        return {
          ...current,
          theme: saved.theme || current.theme,
          activeProjectId: typeof saved.activeProjectId === "string" ? saved.activeProjectId : null,
          recentProjectIds: savedIds,
          projectHistory: [],
          canvasPreviewMode: previewMode,
          editorLayout: normalizeEditorLayoutPreferences(saved.editorLayout),
        };
      },
    },
  ),
);
