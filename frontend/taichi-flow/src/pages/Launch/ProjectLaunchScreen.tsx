import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertCircle, Check, Loader2 } from "lucide-react";
import { LAUNCH_STEPS, useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";

export function ProjectLaunchScreen() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const launchProject = useTaichiFlowStore((state) => state.launchProject);
  const launchState = useTaichiFlowStore((state) => state.launchState);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const projectHistory = useTaichiFlowStore((state) => state.projectHistory);
  const startedRef = useRef(false);

  const displayName =
    activeProject?.project_id === projectId
      ? activeProject.name
      : projectHistory.find((item) => item.project_id === projectId)?.name || "正在打开项目";
  const displayPath =
    activeProject?.project_id === projectId
      ? activeProject.root_path
      : projectHistory.find((item) => item.project_id === projectId)?.root_path || "";

  useEffect(() => {
    if (!projectId || startedRef.current) return;
    startedRef.current = true;
    void launchProject(projectId).catch(() => undefined);
  }, [launchProject, projectId]);

  useEffect(() => {
    if (launchState.status !== "ready" || !projectId) return;
    const scenarioId = scenarios[0]?.scenario_id;
    const timer = window.setTimeout(() => {
      if (scenarioId) {
        navigate(`/editor/${projectId}/scenarios/${scenarioId}`, { replace: true });
      } else {
        navigate(`/editor/${projectId}`, { replace: true });
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [launchState.status, navigate, projectId, scenarios]);

  const currentIndex = LAUNCH_STEPS.findIndex((step) => step.key === launchState.currentStep);

  return (
    <div className="tf-launch-root tf-mica" role="status" aria-live="polite">
      <div className="tf-launch-screen tf-animate-in">
      <div className="tf-logo tf-launch-logo">TF</div>
      <div className="tf-launch-heading">
        <h1 className="tf-display">{displayName}</h1>
        {displayPath ? <p className="tf-caption tf-text-tertiary">{displayPath}</p> : null}
      </div>

      <ul className="tf-launch-steps">
        {LAUNCH_STEPS.map((step, index) => {
          const done = launchState.status === "ready" || (currentIndex >= 0 && index < currentIndex);
          const active = launchState.status === "loading" && step.key === launchState.currentStep;
          return (
            <li key={step.key} className={`tf-launch-step${done ? " is-done" : ""}${active ? " is-active" : ""}`}>
              <span className="tf-launch-step-icon" aria-hidden>
                {done ? <Check size={14} /> : active ? <Loader2 size={14} className="tf-spin" /> : "○"}
              </span>
              <span>{step.label}</span>
            </li>
          );
        })}
      </ul>

      <div className="tf-progress tf-launch-progress" aria-valuenow={launchState.progress} aria-valuemin={0} aria-valuemax={100}>
        <div className="tf-progress-fill" style={{ width: `${launchState.progress}%` }} />
      </div>

      {launchState.status === "error" ? (
        <div className="tf-launch-error">
          <AlertCircle size={16} />
          <span className="tf-body">{launchState.error || "启动失败"}</span>
          <Button variant="secondary" size="small" onClick={() => navigate("/projects", { replace: true })}>
            返回启动器
          </Button>
          <Button
            size="small"
            onClick={() => {
              void launchProject(projectId).catch(() => undefined);
            }}
          >
            重试
          </Button>
        </div>
      ) : (
        <p className="tf-caption tf-text-secondary">正在启动项目编辑器…</p>
      )}
      </div>
    </div>
  );
}
