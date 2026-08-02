import { useEffect, useState, type PropsWithChildren } from "react";
import { BrowserRouter, HashRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { AppShell } from "./layouts/AppShell";
import { ProjectList } from "./pages/Projects/ProjectList";
import { ProjectOverview } from "./pages/Projects/ProjectOverview";
import { ScenarioManagement } from "./pages/Scenarios/ScenarioManagement";
import { CalculateWorkspace } from "./pages/Calculate/CalculateWorkspace";
import { SimulationQueue } from "./pages/Queue/SimulationQueue";
import { ExportData } from "./pages/Export/ExportData";
import { Settings } from "./pages/Settings/Settings";
import { useTaichiFlowStore } from "./stores/taichiFlowStore";

const Router =
  typeof window !== "undefined" && (window as Window & { taichiFlowDesktop?: unknown }).taichiFlowDesktop
    ? HashRouter
    : BrowserRouter;

export function ProjectRouteGuard({ children }: PropsWithChildren) {
  const { projectId } = useParams();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const activeProjectId = useTaichiFlowStore((state) => state.activeProjectId);
  const fetchProjectList = useTaichiFlowStore((state) => state.fetchProjectList);
  const [restoring, setRestoring] = useState(Boolean(activeProjectId && !activeProject));

  useEffect(() => {
    if (activeProject || !activeProjectId) {
      setRestoring(false);
      return;
    }
    let cancelled = false;
    setRestoring(true);
    void fetchProjectList().finally(() => {
      if (!cancelled) setRestoring(false);
    });
    return () => {
      cancelled = true;
    };
  }, [activeProject, activeProjectId, fetchProjectList]);

  if (activeProject && activeProject.project_id === projectId) return children;
  if (restoring) {
    return <div role="status" className="tf-body" style={{ padding: 32, color: "var(--color-foreground-secondary)" }}>正在恢复活动项目…</div>;
  }
  return <Navigate to="/projects" replace />;
}

function AppContent() {
  const startPolling = useTaichiFlowStore((state) => state.startPolling);

  useEffect(() => {
    const cleanup = startPolling();
    return cleanup;
  }, [startPolling]);

  return (
    <Router>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/projects" replace />} />
          <Route path="projects" element={<ProjectList />} />
          <Route path="projects/:projectId" element={<ProjectRouteGuard><ProjectOverview /></ProjectRouteGuard>} />
          <Route path="projects/:projectId/scenarios" element={<ProjectRouteGuard><ScenarioManagement /></ProjectRouteGuard>} />
          <Route path="projects/:projectId/scenarios/:scenarioId/calculate" element={<ProjectRouteGuard><CalculateWorkspace /></ProjectRouteGuard>} />
          <Route path="projects/:projectId/queue" element={<ProjectRouteGuard><SimulationQueue /></ProjectRouteGuard>} />
          <Route path="projects/:projectId/export" element={<ProjectRouteGuard><ExportData /></ProjectRouteGuard>} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default function App() {
  return <AppContent />;
}
