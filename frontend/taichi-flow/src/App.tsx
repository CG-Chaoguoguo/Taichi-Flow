import { useEffect, useState, type PropsWithChildren } from "react";
import { BrowserRouter, HashRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { LauncherShell } from "./layouts/LauncherShell";
import { ProjectEditorShell } from "./layouts/ProjectEditorShell";
import { ProjectList } from "./pages/Projects/ProjectList";
import { ProjectLaunchScreen } from "./pages/Launch/ProjectLaunchScreen";
import { EditorIndexRedirect, ProjectEditor } from "./pages/Editor/ProjectEditor";
import { Settings } from "./pages/Settings/Settings";
import { isActiveScenario, useTaichiFlowStore } from "./stores/taichiFlowStore";

const Router =
  typeof window !== "undefined" && (window as Window & { taichiFlowDesktop?: unknown }).taichiFlowDesktop
    ? HashRouter
    : BrowserRouter;

function LegacyEditorRedirect({ dock }: { dock?: "queue" | "export" }) {
  const { projectId = "", scenarioId } = useParams();
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const targetScenario = scenarioId && scenarios.some((scenario) => scenario.scenario_id === scenarioId && isActiveScenario(scenario))
    ? scenarioId
    : scenarios.find(isActiveScenario)?.scenario_id;
  if (!projectId) return <Navigate to="/projects" replace />;
  if (!targetScenario) return <Navigate to={`/launch/${projectId}`} replace />;
  const query = dock ? `?dock=${dock}` : "";
  return <Navigate to={`/editor/${projectId}/scenarios/${targetScenario}${query}`} replace />;
}

export function EditorRouteGuard({ children }: PropsWithChildren) {
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
    return (
      <div role="status" className="tf-body" style={{ padding: 32, color: "var(--color-foreground-secondary)" }}>
        正在恢复活动项目…
      </div>
    );
  }
  // Closing the project clears activeProject while navigating to /projects — don't bounce back to launch.
  if (!activeProjectId) return <Navigate to="/projects" replace />;
  if (projectId) return <Navigate to={`/launch/${projectId}`} replace />;
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
        <Route path="/" element={<LauncherShell />}>
          <Route index element={<Navigate to="/projects" replace />} />
          <Route path="projects" element={<ProjectList />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        <Route path="/launch/:projectId" element={<ProjectLaunchScreen />} />

        <Route path="/editor/:projectId" element={<ProjectEditorShell />}>
          <Route
            index
            element={
              <EditorRouteGuard>
                <EditorIndexRedirect />
              </EditorRouteGuard>
            }
          />
          <Route
            path="scenarios/:scenarioId"
            element={
              <EditorRouteGuard>
                <ProjectEditor />
              </EditorRouteGuard>
            }
          />
        </Route>

        <Route path="/projects/:projectId" element={<Navigate to="/projects" replace />} />
        <Route path="/projects/:projectId/scenarios" element={<LegacyEditorRedirect />} />
        <Route path="/projects/:projectId/scenarios/:scenarioId/calculate" element={<LegacyEditorRedirect />} />
        <Route path="/projects/:projectId/queue" element={<LegacyEditorRedirect dock="queue" />} />
        <Route path="/projects/:projectId/export" element={<LegacyEditorRedirect dock="export" />} />
        <Route path="/calculate" element={<Navigate to="/projects" replace />} />
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
    </Router>
  );
}

export default function App() {
  return <AppContent />;
}
