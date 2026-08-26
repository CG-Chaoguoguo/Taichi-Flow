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
  parent_revision_id?: string | null;
};

export type RasterMetadata = {
  rows?: number;
  cols?: number;
  cell_size?: number;
  origin?: { x?: number; y?: number };
  crs?: string | null;
  nodata?: number | null;
  extent?: number[] | null;
  cell_size_x?: number | null;
  cell_size_y?: number | null;
  geotransform?: { a: number; b: number; c: number; d: number; e: number; f: number };
  raster_profile_version?: string;
};

export type RasterStatistics = {
  valid_count?: number;
  nodata_count?: number;
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  stddev?: number | null;
  histogram?: { edges: number[]; counts: number[] };
  unique_values?: Array<{ value: number | string | null; value_text: string; count: number }>;
  categorical_overflow?: boolean;
};

export type RasterProfile = {
  asset_id: string;
  name?: string;
  source_sha256: string;
  profile_version: string;
  status: "pending" | "preparing" | "ready" | "unsupported" | "error";
  error?: string;
  unsupported_reason?: string | null;
  driver?: string;
  family?: string;
  data_kind?: "continuous" | "categorical" | string;
  width?: number;
  height?: number;
  band_count?: number;
  dtype?: string | null;
  nodata?: number | string | null;
  transform?: { a: number; b: number; c: number; d: number; e: number; f: number };
  bounds?: { xmin: number; ymin: number; xmax: number; ymax: number };
  crs?: string | null;
  unit?: string | null;
  north_up?: boolean;
  statistics?: RasterStatistics;
  capabilities?: { display?: boolean; identify?: boolean; statistics?: boolean };
  cache_path?: string | null;
  profile_url?: string;
  cog_url?: string | null;
};

export type RasterIdentifyLayer = {
  asset_id: string;
  name?: string;
  family?: string;
  source_sha256: string;
  status: "value" | "nodata" | "outside" | "unsupported" | "error" | string;
  coordinate: { x: number; y: number };
  sampled_from: "source_base" | string;
  dtype?: string | null;
  nodata?: number | string | null;
  unit?: string | null;
  row?: number | null;
  column?: number | null;
  row_one_based?: number | null;
  column_one_based?: number | null;
  cell_center?: { x: number; y: number } | null;
  raw: { value: number | string | null; value_text: string; is_nodata: boolean };
  neighborhood?: {
    size: number;
    center: { row: number; column: number };
    values: Array<Array<number | string | null>>;
    value_text: string[][];
  };
  message?: string;
};

export type RasterIdentifyResponse = {
  coordinate: { x: number; y: number };
  active_asset_id?: string | null;
  layers: RasterIdentifyLayer[];
};

export type MapLayerState = {
  asset_id: string;
  visible: boolean;
  order: number;
  opacity: number;
  renderer?: {
    kind?: "continuous" | "categorical";
    stretch?: "minmax" | "percent_clip" | "stddev" | "none";
    color_ramp?: string;
    invert?: boolean;
    gamma?: number;
    resampling?: "nearest" | "bilinear";
  };
};

export type MapState = {
  layers: MapLayerState[];
  active_layer_id?: string | null;
  view?: { center?: [number, number] | null; resolution?: number | null; rotation?: number };
};

export type MapStateResponse = {
  project_id: string;
  version: number;
  state: MapState;
  updated_at: string;
};

export type InputBinding = {
  binding_key: string;
  asset_id: string;
  family: string;
  role: string;
  period_id?: string | null;
  ordinal?: number | null;
  active: boolean;
  metadata?: Record<string, unknown>;
  raster_metadata?: RasterMetadata;
};

export type InputFileStatus = "uploading" | "parsing" | "visualizing" | "metadata_only" | "ready" | "warning" | "invalid" | "unsupported";
export type RuntimeLock = {
  locked: boolean;
  simulation_ids: string[];
  statuses: Array<"starting" | "running" | "stopping">;
};
export type InputFamily =
  | "dem"
  | "slope"
  | "zones"
  | "thickness"
  | "trigger"
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
  roles?: string[];
  media_type?: string | null;
  raster_metadata?: RasterMetadata;
  archived?: boolean;
  deduplicated?: boolean;
  deletable?: boolean;
  runtime_lock?: RuntimeLock;
  draft_reference_count?: number;
  queued_reference_count?: number;
};

export type AssetDeletePreview = {
  asset_ids: string[];
  assets: InputFile[];
  runtime_locked: Array<RuntimeLock & { asset_id: string; name: string }>;
  detached_binding_count: number;
  affected_scenario_ids: string[];
  cancelled_queue_item_ids: string[];
};

export type AssetBatchDeleteResult = {
  deleted_ids: string[];
  detached_binding_count: number;
  cancelled_queue_item_ids: string[];
  retained_snapshot_blob_count: number;
};

export type ScenarioStatus = "draft" | "ready" | "queued" | "running" | "completed" | "failed" | "stopped" | "interrupted" | "archived";
export type Scenario = {
  scenario_id: string;
  project_id: string;
  name: string;
  input_revision_id: string | null;
  base_scenario_id?: string | null;
  parameter_template_id?: string | null;
  parameter_baseline?: Record<string, unknown>;
  parameter_patch: Record<string, unknown>;
  effective_parameters: Record<string, unknown>;
  compute_policy_resolution?: ComputePolicyResolution;
  input_bindings?: InputBinding[];
  binding_state?: "draft" | "runtime_snapshot";
  version?: number;
  status: ScenarioStatus;
  progress: number;
  latest_simulation_id: string | null;
  result_family_count: number;
  file_count: number;
  work_dir?: string;
  created_at: string;
  updated_at: string;
};

export type SimulationStatus = "pending" | "starting" | "running" | "stopping" | "completed" | "failed" | "stopped" | "interrupted";
export type SimulationRun = {
  simulation_id: string;
  scenario_id: string;
  input_revision_id?: string | null;
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
  effective_config?: Record<string, unknown>;
  compute_policy_resolution: ComputePolicyResolution;
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
  scenario_version?: number | null;
  input_revision_id?: string | null;
  cancel_reason?: string | null;
  retry_of?: string | null;
  runtime_profile?: string | null;
  effective_config: Record<string, unknown>;
  compute_policy_resolution: ComputePolicyResolution;
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
export type DirectoryLocation = {
  name: string;
  path: string;
  writable: boolean;
  kind?: "directory" | "file";
  size?: number | null;
};
export type DirectoryListing = {
  current_path: string | null;
  parent_path: string | null;
  roots: DirectoryLocation[];
  directories: DirectoryLocation[];
  files?: DirectoryLocation[];
  can_select: boolean;
};
export type ParameterCatalogEntry = {
  key: string;
  control_key?: string | null;
  control_family?: string | null;
  source_index?: number | null;
  label: string;
  label_zh?: string | null;
  description_zh?: string | null;
  abbrev?: string | null;
  group?: string | null;
  config_path?: string | null;
  parser_field?: string | null;
  runtime_consumer?: string | null;
  activation_condition?: string | null;
  runtime_status: string;
  status_label_zh?: string | null;
  editable: boolean;
  frontend_policy?: "editable" | "read_only" | string;
  value_type?: "boolean" | "integer" | "number_array" | "enum" | string;
  allowed_values?: unknown[];
  allowed_value_labels_zh?: Record<string, string> | null;
  dependencies?: string[];
  dependency_paths?: string[];
  affected_output_families?: string[];
  original_variable?: string | null;
  source_stage?: string | null;
  status_reason?: string | null;
};
export type EddaControlRegistrySummary = {
  registry_version: string;
  entry_count: number;
  editable_count: number;
  restricted_count: number;
};
export type RuntimeProfileOption = {
  name: string;
  default_backend?: string;
  label_zh?: string;
  description_zh?: string;
  description?: string;
};

export type ParameterCatalog = {
  catalog_version: string;
  editable_statuses: string[];
  parameters: ParameterCatalogEntry[];
  status_counts: Record<string, number>;
  control_registry?: EddaControlRegistrySummary | null;
  gate_parameter_keys?: string[];
  runtime_profiles?: {
    default_profile?: string;
    user_selectable?: RuntimeProfileOption[];
  } | null;
};

export type ComputeGateDefaults = {
  catalog_version: string;
  values: Record<string, unknown>;
  baseline: Record<string, unknown>;
  effective: Record<string, unknown>;
  updated_at?: string | null;
};

export type RainfallPeriod = {
  period_id?: string;
  index: number;
  start_s?: number | null;
  end_s?: number | null;
  cri_mps?: number | null;
  source?: "uniform" | "raster" | "uniform_cri" | "rifil" | string | null;
  asset_id?: string | null;
};

export type RainfallTimeline = {
  mode: "regular" | "custom";
  start_s: number | null;
  end_s: number | null;
  interval_s: number | null;
  period_count: number;
  boundaries_s: number[];
  source?: string;
  declared_period_count?: number | null;
  declared_end_s?: number | null;
};

export type ParameterTemplate = {
  template_id: string;
  version: number;
  name: string;
  description: string;
  source_kind: string;
  source_hash?: string | null;
  values: Record<string, unknown>;
  field_provenance: Record<string, unknown>;
  created_at: string;
};

export type ValidationIssue = {
  code: string;
  severity: "error" | "warning";
  message: string;
  parameter_key?: string;
  binding_key?: string;
  period_id?: string;
};

export type ValidationState = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  issues?: ValidationIssue[];
};

export type ComputePolicyDetected = {
  simulate_shallow_landslide: boolean | null;
  dfs_failure_source_variant: string | null;
  topology?: string | null;
  topology_status?: string | null;
  evidence: Array<Record<string, unknown>>;
};

export type ComputePolicyEffective = {
  mode: "disabled" | "precomputed" | "live" | null;
  simulate_shallow_landslide: boolean | null;
  configured_variant?: string | null;
  active_variant?: string | null;
};

export type ComputePolicyResolutionCommon = {
  source: "auto" | "global_override" | "direct_api_compatibility" | string;
  requested: "auto" | "disabled" | "precomputed" | "live" | string;
  detected: ComputePolicyDetected;
  effective: ComputePolicyEffective;
  numeric_variants: Record<string, { source?: string; value?: unknown }>;
  settings_snapshot: Record<string, unknown>;
  warnings: string[];
  resolution_id: string;
  resolution_hash: string;
};

export type ComputePolicyResolution =
  | (ComputePolicyResolutionCommon & { status: "resolved" })
  | (ComputePolicyResolutionCommon & {
      status: "blocked";
      blocking_issue: { code: string; severity?: string; message: string; details?: Record<string, unknown> };
    })
  | (ComputePolicyResolutionCommon & { status: "legacy_unrecorded" });

export const EMPTY_COMPUTE_POLICY_RESOLUTION: ComputePolicyResolution = {
  status: "blocked",
  source: "auto",
  requested: "auto",
  detected: {
    simulate_shallow_landslide: null,
    dfs_failure_source_variant: null,
    evidence: [],
  },
  effective: { mode: null, simulate_shallow_landslide: null, active_variant: null },
  numeric_variants: {},
  settings_snapshot: {},
  warnings: [],
  blocking_issue: { code: "configuration_refresh_required", message: "正在等待方案计算策略解析。" },
  resolution_id: "cpr-unresolved",
  resolution_hash: "unresolved",
};

export type ScenarioConfiguration = {
  scenario_id: string;
  parameter_template_id?: string | null;
  baseline: Record<string, unknown>;
  overrides: Record<string, unknown>;
  effective: Record<string, unknown>;
  bindings: InputBinding[];
  validation: ValidationState;
  compute_policy_resolution: ComputePolicyResolution;
  version: number;
};

export type ParameterImportPreview = {
  source_kind: string;
  source_name: string;
  source_hash: string;
  values: Record<string, unknown>;
  diff: Array<{ key: string; before: unknown; after: unknown }>;
  ignored_file_references: { count: number; families: string[] };
};

export type LegacyMigrationReference = {
  native_family: string;
  family: string;
  ordinal: number;
  path: string;
  exists: boolean;
  active: boolean;
  binding_key: string;
  role: string;
  period_id?: string | null;
};

export type LegacyMigrationPlan = {
  scenario_id: string;
  scenario_version: number;
  source_hash: string;
  source_kind: string;
  input_revision_id: string;
  existing_file_count: number;
  missing_file_count: number;
  file_references: LegacyMigrationReference[];
  proposed_bindings: LegacyMigrationReference[];
  unresolved_active_bindings: LegacyMigrationReference[];
  unresolved_active_count: number;
  warnings: string[];
  requires_confirmation: boolean;
};

export type FileInputAudit = {
  family: string;
  raw_paths?: string[];
  resolved_paths?: string[];
  exists?: boolean[];
  production_status?: string | null;
  activation_condition?: string | null;
  runtime_status?: string | null;
  editable?: boolean;
  notes?: string | null;
  blocked_reason?: string | null;
};

export type CaseConfigInterface = {
  case_config_file?: string;
  case_base_dir?: string;
  case_config_name?: string;
  project_id?: string;
  revision_id?: string;
  file_inputs: FileInputAudit[];
  parsed_values: {
    time?: Record<string, number>;
    rainfall?: {
      mode?: string;
      cri_mps?: number[];
      capt_s?: number[];
      periods?: RainfallPeriod[];
    };
    manning?: {
      source?: string;
      global?: number;
    };
    rheology?: Record<string, number>;
    double_layer?: Record<string, number>;
    zones?: Record<string, unknown>;
  };
  parameter_catalog?: ParameterCatalog;
  runtime_status?: {
    source_mode?: string;
    supported_field_count?: number;
    recognized_unsupported_field_count?: number;
    unrecognized_field_count?: number;
  };
  audit?: {
    rainfall_mode?: string;
    manning_source?: string;
    flags?: Record<string, unknown>;
    extension_flags?: Record<string, unknown>;
    recognized_unsupported_fields?: string[];
    audit_notes?: string[];
  };
};

export type ToastType = "success" | "warning" | "error" | "info";
export type Toast = { id: string; type: ToastType; message: string };
