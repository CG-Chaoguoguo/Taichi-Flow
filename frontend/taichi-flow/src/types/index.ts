export type ProjectInfo = {
  project_id: string;
  name: string;
  description: string;
  root_path: string;
  state_path?: string;
  created_at: string;
  updated_at: string;
  available?: boolean;
};

export type InputRevision = {
  revision_id: string;
  project_id: string;
  version_tag: string;
  created_at: string;
  status: "ready" | "validating" | "warning" | "invalid";
  file_count: number;
  summary: string;
  validation?: { valid?: boolean; errors?: string[]; warnings?: string[] };
};

export type InputFileStatus = "uploading" | "parsing" | "visualizing" | "metadata_only" | "ready" | "warning" | "invalid" | "unsupported";
export type InputFamily =
  | "dem"
  | "slope"
  | "zones"
  | "thickness"
  | "manning"
  | "rainfall"
  | "groundwater"
  | "infiltration"
  | "boundary"
  | "outflow"
  | "inflow"
  | "monitoring"
  | "config"
  | "native";

export type InputFile = {
  file_id: string;
  family: InputFamily;
  name: string;
  status: InputFileStatus;
  size: number;
  updated_at: string;
  sha256?: string;
  summary?: string;
  warnings?: string[];
  errors?: string[];
};

export type ScenarioStatus = "draft" | "ready" | "queued" | "running" | "completed" | "failed" | "stopped" | "interrupted" | "archived";
export type Scenario = {
  scenario_id: string;
  project_id: string;
  name: string;
  input_revision_id: string;
  base_scenario_id?: string | null;
  parameter_patch: Record<string, unknown>;
  effective_parameters: Record<string, unknown>;
  status: ScenarioStatus;
  progress: number;
  latest_simulation_id: string | null;
  result_family_count: number;
  file_count: number;
  created_at: string;
  updated_at: string;
};

export type SimulationStatus = "pending" | "starting" | "running" | "stopping" | "completed" | "failed" | "stopped" | "interrupted";
export type SimulationRun = {
  simulation_id: string;
  scenario_id: string;
  project_id: string;
  status: SimulationStatus;
  progress: number;
  current_time: number;
  end_time: number;
  step_count: number;
  output_count: number;
  start_time: string | null;
  end_time_actual: string | null;
  error: string | null;
  elapsed_seconds: number;
  terminal_log?: string[];
  output_dir?: string;
  resource_summary?: Record<string, unknown>;
};

export type QueueItemStatus = "queued" | "starting" | "running" | "completed" | "failed" | "stopped" | "interrupted" | "cancelled" | "waiting" | "canceled";
export type QueueItem = {
  queue_item_id: string;
  project_id: string;
  scenario_id: string;
  scenario_name: string;
  position: number;
  status: QueueItemStatus;
  simulation_id: string | null;
  retry_of?: string | null;
  enqueued_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: number;
  summary: string;
};

export type ResultFile = {
  filename: string;
  source_filename?: string;
  file_path?: string;
  file_size?: number;
  size?: number;
  file_type?: string;
  family: string;
  sha256?: string;
  description?: string;
};

export type ResultFamily = {
  family_id: string;
  name: string;
  label: string;
  file_count: number;
  total_size: number;
  files: ResultFile[];
  metadata?: Record<string, unknown>;
};

export type ExportStatus = "queued" | "running" | "completed" | "failed" | "estimating" | "generating" | "ready" | "expired";
export type ExportJob = {
  export_id: string;
  project_id: string;
  scenario_id: string;
  simulation_id: string;
  status: ExportStatus;
  selected_families: string[];
  selected_files: string[];
  include_parameters_json: boolean;
  include_parameters_csv: boolean;
  file_count: number;
  total_size: number;
  archive_path?: string | null;
  download_url?: string | null;
  error?: string | null;
  created_at: string;
  completed_at: string | null;
};

export type SystemMetrics = { cpu_percent: number | null; gpu_percent: number | null; gpu_name?: string | null };
export type DirectoryLocation = { name: string; path: string; writable: boolean };
export type DirectoryListing = {
  current_path: string | null;
  parent_path: string | null;
  roots: DirectoryLocation[];
  directories: DirectoryLocation[];
  can_select: boolean;
};
export type ParameterCatalogEntry = {
  key: string;
  label: string;
  config_path?: string | null;
  parser_field?: string | null;
  runtime_consumer?: string | null;
  activation_condition?: string | null;
  runtime_status: string;
  editable: boolean;
};
export type ParameterCatalog = { catalog_version: string; editable_statuses: string[]; parameters: ParameterCatalogEntry[]; status_counts: Record<string, number> };
export type ToastType = "success" | "warning" | "error" | "info";
export type Toast = { id: string; type: ToastType; message: string };
