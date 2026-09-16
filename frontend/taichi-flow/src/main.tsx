import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyTheme, readStoredTheme } from "./themePreference";
import "./index.css";

function ThemeInitializer({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    applyTheme(readStoredTheme(localStorage));
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(readStoredTheme(localStorage));
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return <>{children}</>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeInitializer>
      <App />
    </ThemeInitializer>
  </StrictMode>
);
