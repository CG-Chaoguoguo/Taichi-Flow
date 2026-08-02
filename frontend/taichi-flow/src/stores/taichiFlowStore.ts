import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { ExportJob, InputFile, InputRevision, ParameterCatalog, ProjectInfo, QueueItem, ResultFamily, Scenario, SimulationRun, SystemMetrics, Toast } from "../types";
import { exportApi, inputApi, projectApi, queueApi, resultApi, scenarioApi, systemApi } from "../api/taichiFlowAdapter";

type ThemeMode = "light" | "dark" | "system" | "high-contrast";
type LoadingState = Record<string, boolean>;
type ErrorState = Record<string, string | null>;

interface TaichiFlowStore {
  activeProject: ProjectInfo | null;
  activeProjectId: string | null;
  projectHistory: ProjectInfo[];
  recentProjectIds: string[];
  theme: ThemeMode;
  serviceOnline: boolean;
  metrics: SystemMetrics;
  parameterCatalog: ParameterCatalog | null;
  toasts: Toast[];
  scenarios: Scenario[];
  queue: QueueItem[];
  inputFiles: InputFile[];
  inputRevisions: InputRevision[];
  resultFamilies: Record<string, ResultFamily[]>;
  exports: ExportJob[];
  runningSimulations: Record<string, SimulationRun>;
  loading: LoadingState;
  errors: ErrorState;
  setTheme: (theme: ThemeMode) => void;
  setActiveProject: (project: ProjectInfo | null) => void;
  removeFromHistory: (projectId: string) => void;
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
  createProject: (name: string, rootPath: string, description?: string) => Promise<ProjectInfo>;
  openProject: (rootPath: string) => Promise<ProjectInfo>;
  fetchProjectList: () => Promise<ProjectInfo[]>;
  fetchScenarios: () => Promise<void>;
  createScenario: (name: string, baseScenarioId?: string) => Promise<Scenario>;
  updateScenario: (scenarioId: string, updates: Partial<Scenario>) => Promise<void>;
  duplicateScenario: (scenarioId: string) => Promise<Scenario>;
  archiveScenario: (scenarioId: string) => Promise<void>;
  deleteScenario: (scenarioId: string) => Promise<void>;
  fetchInputFiles: () => Promise<void>;
  fetchInputRevisions: () => Promise<void>;
  uploadInput: (family: string, file: File) => Promise<InputFile>;
  createInputRevision: (uploadIds: string[], versionTag?: string) => Promise<InputRevision>;
  fetchQueue: () => Promise<void>;
  enqueueScenario: (scenarioId: string) => Promise<void>;
  reorderQueue: (itemId: string, newPosition: number) => Promise<void>;
  cancelQueueItem: (itemId: string) => Promise<void>;
  stopRunningItem: (itemId: string) => Promise<void>;
  retryQueueItem: (itemId: string) => Promise<void>;
  fetchResultFamilies: (simulationId: string) => Promise<void>;
  createExport: (scenarioId: string, simulationId: string, options: Partial<ExportJob>) => Promise<ExportJob>;
  fetchExports: () => Promise<void>;
  refreshMetrics: () => Promise<void>;
  checkService: () => Promise<void>;
  fetchParameterCatalog: () => Promise<void>;
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
      toasts: [],
      scenarios: [],
      queue: [],
      inputFiles: [],
      inputRevisions: [],
      resultFamilies: {},
      exports: [],
      runningSimulations: {},
      loading: {},
      errors: {},

      setTheme: (theme) => {
        set({ theme });
        const resolved = theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;
        document.documentElement.setAttribute("data-theme", resolved === "high-contrast" ? "high-contrast" : resolved);
      },
      setActiveProject: (project) => {
        set({ activeProject: project, activeProjectId: project?.project_id || null });
        if (!project) return;
        set((state) => ({
          projectHistory: [project, ...state.projectHistory.filter((item) => item.project_id !== project.project_id)].slice(0, 8),
          recentProjectIds: [project.project_id, ...state.recentProjectIds.filter((id) => id !== project.project_id)].slice(0, 8),
        }));
        void get().fetchScenarios();
        void get().fetchInputFiles();
        void get().fetchInputRevisions();
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

      createProject: async (name, rootPath, description) => {
        const project = await projectApi.create({ name, root_path: rootPath, description });
        get().setActiveProject(project);
        get().addToast({ type: "success", message: `项目“${name}”已创建` });
        return project;
      },
      openProject: async (rootPath) => {
        const project = await projectApi.import({ root_path: rootPath });
        get().setActiveProject(project);
        return project;
      },
      fetchProjectList: async () => {
        try {
          const projects = (await projectApi.list()).projects;
          const activeId = get().activeProjectId;
          const active = projects.find((project) => project.project_id === activeId);
          if (active) get().setActiveProject(active);
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
        const scenario = await scenarioApi.createScenario(project.project_id, name, baseScenarioId, get().inputRevisions.find((revision) => revision.status === "ready")?.revision_id);
        set((state) => ({ scenarios: [...state.scenarios, scenario] }));
        return scenario;
      },
      updateScenario: async (scenarioId, updates) => {
        const project = get().activeProject;
        if (!project) return;
        const scenario = await scenarioApi.updateScenario(project.project_id, scenarioId, updates);
        set((state) => ({ scenarios: state.scenarios.map((item) => (item.scenario_id === scenarioId ? scenario : item)) }));
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
          set({ inputFiles: await inputApi.listInputFiles(project.project_id) });
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
        await get().fetchInputFiles();
        return uploaded;
      },
      createInputRevision: async (uploadIds, versionTag) => {
        const project = get().activeProject;
        if (!project) throw new Error("请先选择项目");
        const revision = await inputApi.createRevision(project.project_id, { upload_ids: uploadIds, version_tag: versionTag });
        await get().fetchInputRevisions();
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
      enqueueScenario: async (scenarioId) => {
        const project = get().activeProject;
        if (!project) return;
        await queueApi.enqueueScenario(project.project_id, scenarioId);
        await get().fetchQueue();
        await get().fetchScenarios();
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
        try {
          const families = await resultApi.listResultFamilies(project.project_id, simulationId);
          set((state) => ({ resultFamilies: { ...state.resultFamilies, [simulationId]: families } }));
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, results: errorMessage(error) } }));
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
        try {
          set({ parameterCatalog: await systemApi.parameterCatalog() });
        } catch (error) {
          set((state) => ({ errors: { ...state.errors, parameters: errorMessage(error) } }));
        }
      },
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
      name: "taichi-flow-preferences",
      storage: safeStorage,
      partialize: (state) => ({ theme: state.theme, activeProjectId: state.activeProjectId, recentProjectIds: state.recentProjectIds }),
      merge: (persisted, current) => {
        const saved = persisted as { theme?: ThemeMode; activeProjectId?: unknown; recentProjectIds?: unknown; projectHistory?: unknown };
        const recent = Array.isArray(saved.recentProjectIds) ? saved.recentProjectIds : [];
        const history = Array.isArray(saved.projectHistory) ? saved.projectHistory : [];
        const savedIds = (recent.length ? recent : history).filter((id): id is string => typeof id === "string");
        return { ...current, theme: saved.theme || current.theme, activeProjectId: typeof saved.activeProjectId === "string" ? saved.activeProjectId : null, recentProjectIds: savedIds, projectHistory: [] };
      },
    },
  ),
);
