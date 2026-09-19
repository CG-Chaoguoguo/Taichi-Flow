import { useLocation, useNavigate, useParams } from "react-router-dom";

export function useScenarioSettings() {
  const location = useLocation();
  const navigate = useNavigate();
  const { projectId, scenarioId } = useParams();
  const editorPath = projectId && scenarioId ? `/editor/${projectId}/scenarios/${scenarioId}` : null;
  const isSettings = Boolean(editorPath && location.pathname === `${editorPath}/settings`);
  const state = location.state as { settingsReturnTo?: string } | null;
  const candidate = state?.settingsReturnTo;
  const returnTo = editorPath && candidate && (candidate === editorPath || candidate.startsWith(`${editorPath}?`) || candidate.startsWith(`${editorPath}#`))
    ? candidate : editorPath || "/projects";
  const openSettings = () => {
    if (editorPath) navigate(`${editorPath}/settings`, { state: { settingsReturnTo: location.pathname + location.search + location.hash } });
  };
  const returnFromSettings = () => navigate(returnTo, { replace: true });
  return { available: Boolean(editorPath), isSettings, openSettings, returnFromSettings };
}
