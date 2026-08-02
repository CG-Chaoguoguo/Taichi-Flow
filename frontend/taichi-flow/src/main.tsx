import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

function ThemeInitializer({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    let theme = "dark";
    try {
      const saved = localStorage.getItem("taichi-flow-fluent-store");
      if (saved) {
        const parsed = JSON.parse(saved);
        theme = parsed.state?.theme || "dark";
      }
    } catch {
      // ignore storage/read errors
    }
    const resolved =
      theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;
    document.documentElement.setAttribute("data-theme", resolved === "high-contrast" ? "high-contrast" : resolved);
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
