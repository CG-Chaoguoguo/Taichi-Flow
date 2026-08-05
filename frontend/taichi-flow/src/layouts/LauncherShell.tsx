import { useEffect, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { AlertCircle, CheckCircle2, Moon, Monitor, Settings, Sun, X } from "lucide-react";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import { IconButton } from "../components/IconButton";

export function LauncherShell() {
  const navigate = useNavigate();
  const serviceOnline = useTaichiFlowStore((state) => state.serviceOnline);
  const theme = useTaichiFlowStore((state) => state.theme);
  const setTheme = useTaichiFlowStore((state) => state.setTheme);
  const toasts = useTaichiFlowStore((state) => state.toasts);
  const removeToast = useTaichiFlowStore((state) => state.removeToast);
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const resolvedTheme =
    theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;

  return (
    <div className="tf-launcher-root tf-mica">
      <header className="tf-launcher-topbar">
        <div className="tf-launcher-brand">
          <div className="tf-logo">TF</div>
          <span className="tf-subtitle">Taichi-Flow</span>
          <span className="tf-chip">启动器</span>
        </div>
        <div className="tf-row">
          <div className={`tf-service-status ${serviceOnline ? "online" : "offline"}`}>
            {serviceOnline ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
            <span className="tf-caption">{serviceOnline ? "服务在线" : "服务离线"}</span>
          </div>
          <IconButton
            icon={resolvedTheme === "dark" ? <Moon size={16} /> : <Sun size={16} />}
            label="切换主题"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            size="small"
          />
          <IconButton
            icon={<Monitor size={16} />}
            label="高对比度"
            active={theme === "high-contrast"}
            onClick={() => setTheme(theme === "high-contrast" ? "light" : "high-contrast")}
            size="small"
          />
          <IconButton icon={<Settings size={16} />} label="设置" onClick={() => navigate("/settings")} size="small" />
          <span className="tf-caption tf-topbar-time">
            {currentTime.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </header>

      <main className="tf-launcher-content">
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
