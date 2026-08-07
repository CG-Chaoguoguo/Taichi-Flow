/** Win11/Explorer-style filename ordinal + natural sort helpers. */

export function filenameOrdinal(name: string): number | null {
  const matches = name.match(/\d+/g);
  if (!matches?.length) return null;
  const value = Number(matches[matches.length - 1]);
  return Number.isFinite(value) ? value : null;
}

export function compareFilenamesNatural(a: string, b: string): number {
  const leftOrdinal = filenameOrdinal(a);
  const rightOrdinal = filenameOrdinal(b);
  if (leftOrdinal != null && rightOrdinal != null && leftOrdinal !== rightOrdinal) {
    return leftOrdinal - rightOrdinal;
  }
  if (leftOrdinal != null && rightOrdinal == null) return -1;
  if (leftOrdinal == null && rightOrdinal != null) return 1;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

export function sortFilesByFilename(files: File[]): File[] {
  return [...files].sort((left, right) => compareFilenamesNatural(left.name, right.name));
}

export function sortAssetsByFilename<T extends { name: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => compareFilenamesNatural(left.name, right.name));
}

/** Alias kept for RainfallProcessEditor upload batch sorting. */
export function sortRainfallFiles(files: File[]): File[] {
  return sortFilesByFilename(files);
}
