import { useEffect, useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, CheckCircle2, Cpu, Monitor, Moon, Sun, X } from "lucide-react";
import { isActiveScenario, useTaichiFlowStore } from "../stores/taichiFlowStore";
import { IconButton } from "../components/IconButton";
import { Button } from "../components/Button";
import { EditorSettingsPopover } from "../components/EditorSettingsPopover";

export function ProjectEditorShell() {
  const navigate = useNavigate();
  const { projectId } = useParams<{ projectId: string }>();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const closeProject = useTaichiFlowStore((state) => state.closeProject);
  const serviceOnline = useTaichiFlowStore((state) => state.serviceOnline);
  const metrics = useTaichiFlowStore((state) => state.metrics);
  const theme = useTaichiFlowStore((state) => state.theme);
  const setTheme = useTaichiFlowStore((state) => state.setTheme);
  const toasts = useTaichiFlowStore((state) => state.toasts);
  const removeToast = useTaichiFlowStore((state) => state.removeToast);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const resolvedTheme =
    theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;

  const selectedScenarioId =
    editorSelection?.kind === "scenario" || editorSelection?.kind === "result"
      ? editorSelection.scenarioId
      : undefined;
  const selectedScenario = scenarios.find((item) => item.scenario_id === selectedScenarioId && isActiveScenario(item));

  const handleBackToLauncher = () => {
    navigate("/projects");
    closeProject();
  };

  return (
    <div className="tf-editor-root tf-mica">
      <header className="tf-editor-menubar">
        <div className="tf-row tf-min-w-0 tf-flex-1">
          <Button variant="secondary" size="small" icon={<ArrowLeft size={14} />} onClick={handleBackToLauncher}>
            返回启动器
          </Button>
          <div className="tf-logo">TF</div>
          <div className="tf-min-w-0">
            <div className="tf-subtitle tf-ellipsis">{activeProject?.name || "项目编辑器"}</div>
            {activeProject ? (
              <div className="tf-caption tf-ellipsis tf-text-tertiary" title={activeProject.root_path}>
                {activeProject.root_path}
              </div>
            ) : null}
          </div>
          {selectedScenario ? (
            <span className="tf-chip tf-editor-scenario-chip" title={`方案：${selectedScenario.name}`}>
              方案：{selectedScenario.name}
            </span>
          ) : null}
          {projectId && activeProject && activeProject.project_id !== projectId ? (
            <span className="tf-chip">上下文不同步</span>
          ) : null}
        </div>

        <div className="tf-row">
          <div className="tf-row tf-topbar-metrics">
            <Cpu size={14} />
            <span className="tf-caption">CPU {metrics.cpu_percent ?? 0}%</span>
            <Monitor size={14} />
            <span className="tf-caption">GPU {metrics.gpu_percent ?? 0}%</span>
          </div>
          <IconButton
            icon={resolvedTheme === "dark" ? <Moon size={16} /> : <Sun size={16} />}
            label="切换主题"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            size="small"
          />
          <EditorSettingsPopover />
          <div className={`tf-service-status ${serviceOnline ? "online" : "offline"}`}>
            {serviceOnline ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
            <span className="tf-caption">{serviceOnline ? "服务在线" : "服务离线"}</span>
          </div>
          <span className="tf-caption tf-topbar-time">
            {currentTime.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </header>

      <main className="tf-editor-shell-content">
        <Outlet />
      </main>

      <div className="tf-toast-container">
        {toasts.map((toast) => (
          <div key={toast.id} className="tf-toast tf-acrylic">
            <span
              className={`tf-toast-dot tf-toast-dot--${
                toast.type === "success" || toast.type === "error" || toast.type === "warning" ? toast.type : "info"
              }`}
            />
            <span className="tf-body tf-toast-message">{toast.message}</span>
            <button onClick={() => removeToast(toast.id)} aria-label="关闭提示" title="关闭提示" className="tf-focus-ring tf-toast-close">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
