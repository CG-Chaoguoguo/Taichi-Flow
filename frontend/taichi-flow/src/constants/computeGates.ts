const STATIC_GATE_PARAMETER_KEYS = new Set([
  "edda.registry_version",
  "hydrology.dfs_face_flux_variant",
  "hydrology.dfs_manningbar_variant",
  "hydrology.dfs_dry_face_velocity_variant",
  "hydrology.dfs_artivis_variant",
  "hydrology.dfs_absubar_variant",
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
] as const;

export const BOUNDARY_GATE_KEYS = [
  "boundary_conditions.mode",
  "boundary_conditions.default_type",
  "boundary_conditions.include_nodata",
] as const;
