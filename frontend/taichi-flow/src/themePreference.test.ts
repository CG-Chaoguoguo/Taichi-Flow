import { describe, expect, it } from "vitest";
import {
  applyTheme,
  readStoredTheme,
  resolveTheme,
  TAICHI_FLOW_PREFERENCES_STORAGE_KEY,
} from "./themePreference";

describe("theme preference", () => {
  it("hydrates the current Zustand preference key", () => {
    const storage = {
      getItem: (key: string) => key === TAICHI_FLOW_PREFERENCES_STORAGE_KEY
        ? JSON.stringify({ state: { theme: "high-contrast" } })
        : null,
    };

    expect(readStoredTheme(storage)).toBe("high-contrast");
  });

  it("falls back safely and resolves the system theme", () => {
    expect(readStoredTheme({ getItem: () => "not-json" })).toBe("dark");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("applies high contrast to the document root", () => {
    applyTheme("high-contrast");
    expect(document.documentElement).toHaveAttribute("data-theme", "high-contrast");
  });
});
