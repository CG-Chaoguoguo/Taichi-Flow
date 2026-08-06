import { describe, expect, it } from "vitest";
import {
  DEFAULT_EDITOR_LAYOUT,
  normalizeEditorLayoutPreferences,
} from "./editorLayout";

describe("editor layout preferences", () => {
  it("keeps valid global values and schema version", () => {
    const normalized = normalizeEditorLayoutPreferences({
      schemaVersion: 1,
      outer: { outlinerPx: 288.4, inspectorPx: 412.2 },
      dockPx: 318.7,
      inspectorAssetRatio: 0.6,
      assetFamilyPx: 192.8,
      collapsed: { outliner: true, inspector: false, dock: true, inspectorDetails: false, assetFamilies: true },
    });

    expect(normalized).toEqual({
      schemaVersion: 1,
      outer: { outlinerPx: 288, inspectorPx: 412 },
      dockPx: 319,
      inspectorAssetRatio: 0.6,
      assetFamilyPx: 193,
      collapsed: { outliner: true, inspector: false, dock: true, inspectorDetails: false, assetFamilies: true },
    });
  });

  it("clamps invalid values without changing unrelated preference defaults", () => {
    expect(normalizeEditorLayoutPreferences({
      outer: { outlinerPx: 1, inspectorPx: 9999 },
      dockPx: -20,
      inspectorAssetRatio: 4,
      assetFamilyPx: 999,
      collapsed: { outliner: "yes" },
    })).toEqual({
      ...DEFAULT_EDITOR_LAYOUT,
      outer: { outlinerPx: 176, inspectorPx: 560 },
      dockPx: 160,
      inspectorAssetRatio: 0.75,
      assetFamilyPx: 280,
    });
  });
});
