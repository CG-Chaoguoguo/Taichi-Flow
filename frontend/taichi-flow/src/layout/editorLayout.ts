export const EDITOR_LAYOUT_SCHEMA_VERSION = 1 as const;

export type EditorLayoutPreferencesV1 = {
  schemaVersion: typeof EDITOR_LAYOUT_SCHEMA_VERSION;
  outer: {
    outlinerPx: number;
    inspectorPx: number;
  };
  dockPx: number;
  inspectorAssetRatio: number;
  assetFamilyPx: number;
  collapsed: {
    outliner: boolean;
    inspector: boolean;
    dock: boolean;
    inspectorDetails: boolean;
    assetFamilies: boolean;
  };
};

export const DEFAULT_EDITOR_LAYOUT: EditorLayoutPreferencesV1 = {
  schemaVersion: EDITOR_LAYOUT_SCHEMA_VERSION,
  outer: {
    outlinerPx: 240,
    inspectorPx: 360,
  },
  dockPx: 220,
  inspectorAssetRatio: 0.45,
  assetFamilyPx: 160,
  collapsed: {
    outliner: false,
    inspector: false,
    dock: false,
    inspectorDetails: false,
    assetFamilies: false,
  },
};

function finiteNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function bool(value: unknown, fallback: boolean) {
  return typeof value === "boolean" ? value : fallback;
}

/**
 * Normalizes persisted layout state without allowing an invalid window or an
 * older schema to corrupt the rest of the preference store.
 */
export function normalizeEditorLayoutPreferences(value: unknown): EditorLayoutPreferencesV1 {
  const source = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const outer = source.outer && typeof source.outer === "object" ? source.outer as Record<string, unknown> : {};
  const collapsed = source.collapsed && typeof source.collapsed === "object"
    ? source.collapsed as Record<string, unknown>
    : {};

  return {
    schemaVersion: EDITOR_LAYOUT_SCHEMA_VERSION,
    outer: {
      outlinerPx: Math.round(clamp(finiteNumber(outer.outlinerPx, DEFAULT_EDITOR_LAYOUT.outer.outlinerPx), 176, 360)),
      inspectorPx: Math.round(clamp(finiteNumber(outer.inspectorPx, DEFAULT_EDITOR_LAYOUT.outer.inspectorPx), 300, 560)),
    },
    dockPx: Math.round(clamp(finiteNumber(source.dockPx, DEFAULT_EDITOR_LAYOUT.dockPx), 160, 440)),
    inspectorAssetRatio: clamp(finiteNumber(source.inspectorAssetRatio, DEFAULT_EDITOR_LAYOUT.inspectorAssetRatio), 0.25, 0.75),
    assetFamilyPx: Math.round(clamp(finiteNumber(source.assetFamilyPx, DEFAULT_EDITOR_LAYOUT.assetFamilyPx), 128, 280)),
    collapsed: {
      outliner: bool(collapsed.outliner, DEFAULT_EDITOR_LAYOUT.collapsed.outliner),
      inspector: bool(collapsed.inspector, DEFAULT_EDITOR_LAYOUT.collapsed.inspector),
      dock: bool(collapsed.dock, DEFAULT_EDITOR_LAYOUT.collapsed.dock),
      inspectorDetails: bool(collapsed.inspectorDetails, DEFAULT_EDITOR_LAYOUT.collapsed.inspectorDetails),
      assetFamilies: bool(collapsed.assetFamilies, DEFAULT_EDITOR_LAYOUT.collapsed.assetFamilies),
    },
  };
}

export function cloneEditorLayoutPreferences(value: EditorLayoutPreferencesV1): EditorLayoutPreferencesV1 {
  return normalizeEditorLayoutPreferences(JSON.parse(JSON.stringify(value)));
}
