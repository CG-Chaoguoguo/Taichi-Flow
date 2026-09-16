const STATIC_GATE_PARAMETER_KEYS = new Set([
  "edda.registry_version",
  "hydrology.dfs_face_flux_variant",
  "hydrology.dfs_manningbar_variant",
  "hydrology.dfs_dry_face_velocity_variant",
  "hydrology.dfs_artivis_variant",
  "hydrology.dfs_absubar_variant",
  "hydrology.dfs_flow_velocity_writer_variant",
  "hydrology.dfs_erosion_depth_writer_variant",
  "hydrology.dfs_sfdf_classify_cv_variant",
  "hydrology.dfs_cvlimit_variant",
  "hydrology.dfs_erodph_dt_variant",
  "hydrology.dfs_barrier_flux_variant",
  "hydrology.dfs_commit_cv_eps_variant",
  "hydrology.dfs_failure_source_policy",
  "experimental.enable_live_doublelayer_in_dfs",
  "boundary_conditions.mode",
  "boundary_conditions.default_type",
  "boundary_conditions.include_nodata",
]);

export function isGateParameterKey(key: string): boolean {
  if (STATIC_GATE_PARAMETER_KEYS.has(key)) return true;
  return (
    key.startsWith("edda.run_controls.")
    || key.startsWith("edda.output_controls.")
    || key.startsWith("experimental.")
  );
}

export const FAILURE_SOURCE_POLICY_KEY = "hydrology.dfs_failure_source_policy";
export const EXPERIMENTAL_LIVE_KEY = "experimental.enable_live_doublelayer_in_dfs";

export const VARIANT_GATE_KEYS = [
  "hydrology.dfs_face_flux_variant",
  "hydrology.dfs_manningbar_variant",
  "hydrology.dfs_dry_face_velocity_variant",
  "hydrology.dfs_artivis_variant",
  "hydrology.dfs_absubar_variant",
  "hydrology.dfs_flow_velocity_writer_variant",
  "hydrology.dfs_erosion_depth_writer_variant",
  "hydrology.dfs_sfdf_classify_cv_variant",
  "hydrology.dfs_cvlimit_variant",
  "hydrology.dfs_erodph_dt_variant",
  "hydrology.dfs_barrier_flux_variant",
  "hydrology.dfs_commit_cv_eps_variant",
] as const;

export const BOUNDARY_GATE_KEYS = [
  "boundary_conditions.mode",
  "boundary_conditions.default_type",
  "boundary_conditions.include_nodata",
] as const;
