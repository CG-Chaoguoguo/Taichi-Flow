import type {
  CaseConfigInterface,
  AssetBatchDeleteResult,
  AssetDeletePreview,
  InputBinding,
  ExportJob,
  InputFile,
  InputRevision,
  ParameterCatalog,
  ParameterImportPreview,
  ParameterTemplate,
  ProjectInfo,
  RuntimeLock,
  QueueItem,
  QueueDeletePreview,
  QueueBatchDeleteResult,
  QueueStartResult,
  ResultFamily,
  Scenario,
  ScenarioConfiguration,
  SimulationRun,
  DirectoryListing,
  SystemMetrics,
  LegacyMigrationPlan,
  MapState,
  MapStateResponse,
  RasterIdentifyResponse,
  RasterProfile,
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

function mapRuntimeLock(value: unknown): RuntimeLock {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const allowed = new Set<RuntimeLock["statuses"][number]>(["starting", "running", "stopping"]);
  return {
    locked: Boolean(record.locked),
    simulation_ids: Array.isArray(record.simulation_ids) ? record.simulation_ids.map(String) : [],
    statuses: Array.isArray(record.statuses)
      ? record.statuses.map(String).filter((status): status is RuntimeLock["statuses"][number] => allowed.has(status as RuntimeLock["statuses"][number]))
      : [],
  };
}

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
    roles: Array.isArray(value.roles) ? value.roles.map(String) : [],
    media_type: value.media_type == null ? null : String(value.media_type),
    raster_metadata: value.raster_metadata && typeof value.raster_metadata === "object"
      ? value.raster_metadata as InputFile["raster_metadata"]
      : undefined,
    archived: Boolean(value.archived),
    deduplicated: Boolean(value.deduplicated),
    deletable: value.deletable === undefined ? true : Boolean(value.deletable),
    runtime_lock: mapRuntimeLock(value.runtime_lock),
    draft_reference_count: Number(value.draft_reference_count || 0),
    queued_reference_count: Number(value.queued_reference_count || 0),
  };
}

function mapDeletePreview(value: Record<string, unknown>): AssetDeletePreview {
  return {
    asset_ids: Array.isArray(value.asset_ids) ? value.asset_ids.map(String) : [],
    assets: Array.isArray(value.assets) ? value.assets.map((asset) => mapUpload(asset as Record<string, unknown>)) : [],
    runtime_locked: Array.isArray(value.runtime_locked)
      ? value.runtime_locked.map((item) => ({
          asset_id: String((item as Record<string, unknown>).asset_id),
          name: String((item as Record<string, unknown>).name),
          ...mapRuntimeLock(item),
        }))
      : [],
    detached_binding_count: Number(value.detached_binding_count || 0),
    affected_scenario_ids: Array.isArray(value.affected_scenario_ids) ? value.affected_scenario_ids.map(String) : [],
    cancelled_queue_item_ids: Array.isArray(value.cancelled_queue_item_ids) ? value.cancelled_queue_item_ids.map(String) : [],
  };
}

export const inputApi = {
  listInputFiles: async (projectId: string): Promise<InputFile[]> => {
    const response = await request<{ assets: Record<string, unknown>[] }>(`/projects/${encodeURIComponent(projectId)}/assets`);
    return response.assets.map((item) => mapUpload(item));
  },
  upload: async (projectId: string, family: string, file: File, signal?: AbortSignal): Promise<InputFile> => {
    const form = new FormData();
    form.append("file", file, file.name);
    const value = await request<Record<string, unknown>>(`/projects/${encodeURIComponent(projectId)}/uploads/${encodeURIComponent(family)}`, { method: "POST", body: form, signal });
    return mapUpload(value);
  },
  uploadFromPath: async (projectId: string, family: string, path: string): Promise<InputFile> => {
    const value = await request<Record<string, unknown>>(`/projects/${encodeURIComponent(projectId)}/uploads/from-path`, json({ family, path }));
    return mapUpload(value);
  },
  uploadBatch: async (projectId: string, family: string, files: File[], signal?: AbortSignal): Promise<InputFile[]> => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file, file.name));
    const response = await request<{ assets: Record<string, unknown>[] }>(
      `/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(family)}`,
      { method: "POST", body: form, signal },
    );
    return response.assets.map((item) => mapUpload(item));
  },
  deleteUpload: (projectId: string, uploadId: string) =>
    request<void>(`/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(uploadId)}`, { method: "DELETE" }),
  previewDelete: async (projectId: string, assetIds: string[]): Promise<AssetDeletePreview> => {
    const response = await request<Record<string, unknown>>(
      `/projects/${encodeURIComponent(projectId)}/assets/delete-preview`,
      json({ asset_ids: assetIds }),
    );
    return mapDeletePreview(response);
  },
  batchDelete: (projectId: string, assetIds: string[]) => request<AssetBatchDeleteResult>(
    `/projects/${encodeURIComponent(projectId)}/assets/batch-delete`,
    json({ asset_ids: assetIds }),
  ),
  getRasterProfile: (projectId: string, assetId: string) => request<RasterProfile>(
    `/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/raster-profile`,
  ),
  prepareRaster: (projectId: string, assetId: string) => request<RasterProfile>(
    `/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/raster/prepare`,
    json({}),
  ),
  identifyRasters: (projectId: string, payload: {
    coordinate: { x: number; y: number };
    asset_ids: string[];
    active_asset_id?: string | null;
    neighborhood_size?: 3 | 5;
  }) => request<RasterIdentifyResponse>(
    `/projects/${encodeURIComponent(projectId)}/raster/identify`,
    json(payload),
  ),
  rasterCogUrl: (projectId: string, assetId: string) => (
    `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/raster/cog`
  ),
  fetchRasterPreview: async (
    projectId: string,
    uploadId: string,
    mode: "downsample" | "full" = "downsample",
  ): Promise<{
    blobUrl: string;
    width: number;
    height: number;
    bounds: { xmin: number; ymin: number; xmax: number; ymax: number };
    min: number;
    max: number;
    nodata: number | null;
    capped: boolean;
    mode: string;
  }> => {
    const response = await fetch(
      `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/uploads/${encodeURIComponent(uploadId)}/preview?mode=${encodeURIComponent(mode)}`,
    );
    if (!response.ok) {
      let payload: ApiErrorPayload = {};
      try {
        payload = (await response.json()) as ApiErrorPayload;
      } catch {
        payload.message = await response.text().catch(() => response.statusText);
      }
      throw new TaichiFlowApiError(payload, `预览失败 (${response.status})`);
    }
    const blob = await response.blob();
    const boundsRaw = (response.headers.get("X-Raster-Bounds") || "0,0,1,1").split(",").map(Number);
    return {
      blobUrl: URL.createObjectURL(blob),
      width: Number(response.headers.get("X-Raster-Width") || 0),
      height: Number(response.headers.get("X-Raster-Height") || 0),
      bounds: {
        xmin: boundsRaw[0] ?? 0,
        ymin: boundsRaw[1] ?? 0,
        xmax: boundsRaw[2] ?? 1,
        ymax: boundsRaw[3] ?? 1,
      },
      min: Number(response.headers.get("X-Value-Min") || 0),
      max: Number(response.headers.get("X-Value-Max") || 1),
      nodata: response.headers.get("X-Nodata") != null ? Number(response.headers.get("X-Nodata")) : null,
      capped: response.headers.get("X-Preview-Capped") === "true",
      mode: response.headers.get("X-Preview-Mode") || mode,
    };
  },
  listInputRevisions: async (projectId: string): Promise<InputRevision[]> => {
    const response = await request<{ revisions: InputRevision[] }>(`/projects/${encodeURIComponent(projectId)}/input-revisions`);
    return response.revisions;
  },
  createRevision: (projectId: string, payload: { version_tag?: string; upload_ids: string[]; parent_revision_id?: string }) => request<InputRevision>(`/projects/${encodeURIComponent(projectId)}/input-revisions`, json(payload)),
  validateRevision: (projectId: string, revisionId: string) => request<{ valid: boolean; errors: string[]; warnings: string[] }>(`/projects/${encodeURIComponent(projectId)}/input-revisions/${encodeURIComponent(revisionId)}/validate`, json({})),
  getConfigInterface: (projectId: string, revisionId: string) =>
    request<CaseConfigInterface>(
      `/projects/${encodeURIComponent(projectId)}/input-revisions/${encodeURIComponent(revisionId)}/config-interface`,
    ),
};

export const mapStateApi = {
  get: (projectId: string) => request<MapStateResponse>(
    `/projects/${encodeURIComponent(projectId)}/map-state`,
  ),
  update: (projectId: string, state: MapState, expectedVersion?: number) => request<MapStateResponse>(
    `/projects/${encodeURIComponent(projectId)}/map-state`,
    putJson({ state, expected_version: expectedVersion }),
  ),
};

export const casesApi = {
  parseConfig: (payload: { case_config_file: string; case_base_dir?: string }) =>
    request<CaseConfigInterface>("/cases/parse-config", json(payload)),
};

export const scenarioApi = {
  listScenarios: async (projectId: string): Promise<Scenario[]> => (await request<{ scenarios: Scenario[] }>(`/projects/${encodeURIComponent(projectId)}/scenarios`)).scenarios,
  createScenario: (projectId: string, name: string, baseScenarioId?: string, inputRevisionId?: string) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios`, json({ name, base_scenario_id: baseScenarioId, input_revision_id: inputRevisionId })),
  getConfiguration: (projectId: string, scenarioId: string) => request<ScenarioConfiguration>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}/configuration`),
  updateScenario: (
    projectId: string,
    scenarioId: string,
    updates: {
      name?: string;
      parameter_patch?: Record<string, unknown>;
      input_revision_id?: string | null;
      input_bindings?: InputBinding[];
      parameter_template_id?: string | null;
      expected_version?: number;
    },
  ) => request<Scenario>(
    `/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}`,
    putJson(updates),
  ),
  duplicateScenario: (projectId: string, scenarioId: string) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}/duplicate`, json({})),
  archiveScenario: (projectId: string, scenarioId: string) => request<Scenario>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}/archive`, json({})),
  deleteScenario: (projectId: string, scenarioId: string) => request<void>(`/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(scenarioId)}`, { method: "DELETE" }),
};

export const parameterApi = {
  listTemplates: async (projectId: string): Promise<ParameterTemplate[]> => (
    await request<{ templates: ParameterTemplate[] }>(`/projects/${encodeURIComponent(projectId)}/parameter-templates`)
  ).templates,
  previewImport: async (projectId: string, scenarioId: string, file: File): Promise<ParameterImportPreview> => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<ParameterImportPreview>(
      `/projects/${encodeURIComponent(projectId)}/parameter-imports/preview?scenario_id=${encodeURIComponent(scenarioId)}`,
      { method: "POST", body: form },
    );
  },
  applyImport: async (projectId: string, scenarioId: string, expectedVersion: number, file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<{ scenario: Scenario; template: ParameterTemplate; diff: ParameterImportPreview["diff"]; ignored_file_references: ParameterImportPreview["ignored_file_references"] }>(
      `/projects/${encodeURIComponent(projectId)}/parameter-imports/apply?scenario_id=${encodeURIComponent(scenarioId)}&expected_version=${expectedVersion}`,
      { method: "POST", body: form },
    );
  },
};

export const migrationApi = {
  previewLegacy: (projectId: string, scenarioId: string) => request<LegacyMigrationPlan>(
    `/projects/${encodeURIComponent(projectId)}/migrations/legacy/preview`,
    json({ scenario_id: scenarioId }),
  ),
  commitLegacy: (projectId: string, scenarioId: string, expectedVersion: number) => request<{
    scenario: Scenario;
    report: Record<string, unknown>;
    report_path: string;
  }>(
    `/projects/${encodeURIComponent(projectId)}/migrations/legacy/commit`,
    json({ scenario_id: scenarioId, expected_version: expectedVersion }),
  ),
};

export const queueApi = {
  getQueue: async (projectId: string): Promise<QueueItem[]> => (await request<{ items: QueueItem[] }>(`/projects/${encodeURIComponent(projectId)}/queue`)).items,
  enqueueScenario: (projectId: string, scenarioId: string) => request<QueueItem>(`/projects/${encodeURIComponent(projectId)}/queue`, json({ scenario_id: scenarioId })),
  startQueue: (projectId: string) => request<QueueStartResult>(`/projects/${encodeURIComponent(projectId)}/queue/start`, json({})),
  reorderQueue: async (projectId: string, itemId: string, newPosition: number): Promise<QueueItem[]> => (await request<{ items: QueueItem[] }>(`/projects/${encodeURIComponent(projectId)}/queue/order`, putJson({ item_id: itemId, new_position: newPosition }))).items,
  previewDelete: (projectId: string, queueItemIds: string[]) => request<QueueDeletePreview>(`/projects/${encodeURIComponent(projectId)}/queue/delete-preview`, json({ queue_item_ids: queueItemIds })),
  batchDelete: (projectId: string, queueItemIds: string[]) => request<QueueBatchDeleteResult>(`/projects/${encodeURIComponent(projectId)}/queue/batch-delete`, json({ queue_item_ids: queueItemIds })),
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
