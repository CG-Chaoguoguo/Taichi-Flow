import type {
  ExportJob,
  InputFile,
  InputRevision,
  ParameterCatalog,
  ProjectInfo,
  QueueItem,
  ResultFamily,
  Scenario,
  SimulationRun,
  DirectoryListing,
  SystemMetrics,
} from "../types";

type ApiErrorPayload = { code?: string; message?: string; details?: unknown; request_id?: string };
export class TaichiFlowApiError extends Error {
  readonly code: string;
  readonly details: unknown;
  readonly requestId?: string;

  constructor(payload: ApiErrorPayload, fallback: string) {
    super(payload.message || fallback);
    this.name = "TaichiFlowApiError";
    this.code = payload.code || "api_error";
    this.details = payload.details;
    this.requestId = payload.request_id;
  }
}

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env || {};
const desktopApiUrl = typeof window !== "undefined"
  ? String((window as Window & { taichiFlowDesktop?: { apiUrl?: string } }).taichiFlowDesktop?.apiUrl || "")
  : "";
const configuredApiUrl = (env.VITE_TAICHI_FLOW_API_URL || desktopApiUrl || "").replace(/\/$/, "");
export const API_BASE_URL = configuredApiUrl;
export const API_PREFIX = `${API_BASE_URL}/api`;

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(`${API_PREFIX}${path}`, { ...init, headers });
  if (!response.ok) {
    let payload: ApiErrorPayload = {};
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      payload.message = await response.text().catch(() => response.statusText);
    }
    throw new TaichiFlowApiError(payload, `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (payload: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(payload) });
const putJson = (payload: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(payload) });

export const projectApi = {
  list: () => request<{ projects: ProjectInfo[]; count: number }>("/projects"),
  create: (payload: { name: string; root_path: string; description?: string }) => request<ProjectInfo>("/projects", json(payload)),
  import: (payload: { root_path: string; name?: string; description?: string }) => request<ProjectInfo>("/projects/import", json(payload)),
  get: (projectId: string) => request<ProjectInfo>(`/projects/${encodeURIComponent(projectId)}`),
  update: (projectId: string, payload: { name?: string; description?: string }) => request<ProjectInfo>(`/projects/${encodeURIComponent(projectId)}`, putJson(payload)),
};

function mapUpload(value: Record<string, unknown>): InputFile {
  return {
    file_id: String(value.upload_id),
    family: String(value.family) as InputFile["family"],
    name: String(value.name),
    status: value.status === "ready" ? "ready" : value.status === "invalid" ? "invalid" : "warning",
    size: Number(value.size || 0),
    updated_at: String(value.created_at || ""),
    sha256: value.sha256 ? String(value.sha256) : undefined,
    summary: value.summary ? String(value.summary) : undefined,
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
    errors: Array.isArray(value.errors) ? value.errors.map(String) : [],
  };
}

export const inputApi = {
  listInputFiles: async (projectId: string): Promise<InputFile[]> => {
    const response = await request<{ uploads: Record<string, unknown>[] }>(`/projects/${encodeURIComponent(projectId)}/uploads`);
    return response.uploads.map((item) => mapUpload(item));
  },
  upload: async (projectId: string, family: string, file: File, signal?: AbortSignal): Promise<InputFile> => {
    const form = new FormData();
    form.append("file", file, file.name);
    const value = await request<Record<string, unknown>>(`/projects/${encodeURIComponent(projectId)}/uploads/${encodeURIComponent(family)}`, { method: "POST", body: form, signal });
    return mapUpload(value);
  },
  listInputRevisions: async (projectId: string): Promise<InputRevision[]> => {
    const response = await request<{ revisions: InputRevision[] }>(`/projects/${encodeURIComponent(projectId)}/input-revisions`);
    return response.revisions;
  },
  createRevision: (projectId: string, payload: { version_tag?: string; upload_ids: string[]; parent_revision_id?: string }) => request<InputRevision>(`/projects/${encodeURIComponent(projectId)}/input-revisions`, json(payload)),
  validateRevision: (projectId: string, revisionId: string) => request<{ valid: boolean; errors: string[]; warnings: string[] }>(`/projects/${encodeURIComponent(projectId)}/input-revisions/${encodeURIComponent(revisionId)}/validate`, json({})),
};

export const scenarioApi = {
  listScenarios: async (projectId: string): Promise<Scenario[]> => (await request<{ scenarios: Scenario[] }>(`/projects/${encodeURIComponent(projectId)}/scenarios`)).scenarios,
  createScenario: (projectId: string, name: string, baseScenarioId?: string, inputRevisionId?: string) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios`, json({ name, base_scenario_id: baseScenarioId, input_revision_id: inputRevisionId })),
  updateScenario: (projectId: string, scenarioId: string, updates: Partial<Scenario>) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}`, putJson({ name: updates.name, parameter_patch: updates.parameter_patch })),
  duplicateScenario: (projectId: string, scenarioId: string) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}/duplicate`, json({})),
  archiveScenario: (projectId: string, scenarioId: string) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}/archive`, json({})),
  deleteScenario: (projectId: string, scenarioId: string) => request<void>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}`, { method: "DELETE" }),
};

export const queueApi = {
  getQueue: async (projectId: string): Promise<QueueItem[]> => (await request<{ items: QueueItem[] }>(`/projects/${encodeURIComponent(projectId)}/queue`)).items,
  enqueueScenario: (projectId: string, scenarioId: string) => request<QueueItem>(`/projects/${encodeURIComponent(projectId)}/queue`, json({ scenario_id: scenarioId })),
  reorderQueue: async (projectId: string, itemId: string, newPosition: number): Promise<QueueItem[]> => (await request<{ items: QueueItem[] }>(`/projects/${encodeURIComponent(projectId)}/queue/order`, putJson({ item_id: itemId, new_position: newPosition }))).items,
  cancelQueueItem: (projectId: string, itemId: string) => request<QueueItem>(`/projects/${encodeURIComponent(projectId)}/queue/${encodeURIComponent(itemId)}`, { method: "DELETE" }),
  stopRunningItem: (projectId: string, itemId: string) => request<QueueItem>(`/projects/${encodeURIComponent(projectId)}/queue/${encodeURIComponent(itemId)}/stop`, json({})),
  retryQueueItem: (projectId: string, itemId: string) => request<QueueItem>(`/projects/${encodeURIComponent(projectId)}/queue/${encodeURIComponent(itemId)}/retry`, json({})),
};

export const runApi = {
  list: async (projectId: string): Promise<SimulationRun[]> => (await request<{ simulations: SimulationRun[] }>(`/projects/${encodeURIComponent(projectId)}/simulations`)).simulations,
  get: (simulationId: string) => request<SimulationRun>(`/simulations/${encodeURIComponent(simulationId)}`),
  stop: (simulationId: string) => request<SimulationRun>(`/simulations/${encodeURIComponent(simulationId)}/stop`, json({})),
  terminal: (projectId: string, simulationId: string) => request<{ entries: string[] }>(`/projects/${encodeURIComponent(projectId)}/simulations/${encodeURIComponent(simulationId)}/terminal`),
};

export const resultApi = {
  listResultFamilies: async (projectId: string, simulationId: string): Promise<ResultFamily[]> => {
    const response = await request<{ families: Array<Record<string, unknown>> }>(`/projects/${encodeURIComponent(projectId)}/results/${encodeURIComponent(simulationId)}`);
    return response.families.map((family) => ({
      family_id: String(family.name),
      name: String(family.name),
      label: String(family.label || family.name),
      file_count: Number(family.file_count || 0),
      total_size: Number(family.total_size || 0),
      files: Array.isArray(family.files) ? (family.files as ResultFamily["files"]) : [],
    }));
  },
  metadata: (projectId: string, simulationId: string) => request<Record<string, unknown>>(`/projects/${encodeURIComponent(projectId)}/results/${encodeURIComponent(simulationId)}/metadata`),
  downloadUrl: (projectId: string, simulationId: string, filename: string) => `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/results/${encodeURIComponent(simulationId)}/files/${filename.split("/").map(encodeURIComponent).join("/")}`,
  zipUrl: (projectId: string, simulationId: string) => `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/results/${encodeURIComponent(simulationId)}/download.zip`,
};

export const exportApi = {
  createExport: (projectId: string, _scenarioId: string, simulationId: string, options: { selected_families?: string[]; selected_files?: string[] }) => request<ExportJob>(`/projects/${encodeURIComponent(projectId)}/exports`, json({ simulation_id: simulationId, families: options.selected_families || [], filenames: options.selected_files || [] })),
  getExports: async (projectId: string): Promise<ExportJob[]> => (await request<{ exports: ExportJob[] }>(`/projects/${encodeURIComponent(projectId)}/exports`)).exports,
  get: (projectId: string, exportId: string) => request<ExportJob>(`/projects/${encodeURIComponent(projectId)}/exports/${encodeURIComponent(exportId)}`),
  downloadUrl: (projectId: string, exportId: string) => `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/exports/${encodeURIComponent(exportId)}/download`,
};

export const systemApi = {
  metrics: () => request<SystemMetrics>("/system/metrics"),
  health: () => request<{ status: string }>("/health"),
  parameterCatalog: () => request<ParameterCatalog>("/parameters/catalog"),
  directories: (path?: string) => request<DirectoryListing>(`/system/directories${path ? `?path=${encodeURIComponent(path)}` : ""}`),
};

export { request };
