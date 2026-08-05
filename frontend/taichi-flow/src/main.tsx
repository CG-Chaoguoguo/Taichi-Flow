import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyTheme, readStoredTheme } from "./themePreference";
import "./index.css";

function ThemeInitializer({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    applyTheme(readStoredTheme(localStorage));
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
