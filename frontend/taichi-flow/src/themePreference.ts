export const TAICHI_FLOW_PREFERENCES_STORAGE_KEY = "taichi-flow-preferences";

export type ThemeMode = "light" | "dark" | "system" | "high-contrast";
export type ResolvedTheme = Exclude<ThemeMode, "system">;

const THEME_MODES = new Set<ThemeMode>(["light", "dark", "system", "high-contrast"]);

export function readStoredTheme(storage: Pick<Storage, "getItem">): ThemeMode {
  try {
    const saved = storage.getItem(TAICHI_FLOW_PREFERENCES_STORAGE_KEY);
    if (!saved) return "dark";
    const theme = JSON.parse(saved)?.state?.theme;
    return THEME_MODES.has(theme) ? theme : "dark";
  } catch {
    return "dark";
  }
}

export function resolveTheme(theme: ThemeMode, prefersDark?: boolean): ResolvedTheme {
  if (theme !== "system") return theme;
  const systemPrefersDark = prefersDark
    ?? (typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false);
  return systemPrefersDark ? "dark" : "light";
}

export function applyTheme(theme: ThemeMode): ResolvedTheme {
  const resolved = resolveTheme(theme);
  document.documentElement.setAttribute("data-theme", resolved);
  return resolved;
}
