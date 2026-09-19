import type { InputFamily, InputFile } from "../types";

/** Raster-like input families that GIS tools can convert to viewable GeoTIFF. */
export const VISUALIZABLE_FAMILIES: ReadonlySet<InputFamily> = new Set([
  "dem",
  "slope",
  "zones",
  "thickness",
  "trigger",
  "manning",
  "rainfall",
  "groundwater",
  "infiltration",
]);

const RASTER_EXTENSIONS = [".asc", ".tif", ".tiff", ".img", ".dem"] as const;

function hasRasterExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return RASTER_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export function isVisualizableInput(file: Pick<InputFile, "family" | "name">): boolean {
  if (!VISUALIZABLE_FAMILIES.has(file.family as InputFamily)) return false;
  return hasRasterExtension(file.name);
}
