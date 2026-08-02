import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Calculator,
  Download,
  FolderKanban,
  Layers,
  List,
  PanelLeft,
  Settings,
  AlertCircle,
  CheckCircle2,
  Cpu,
  Moon,
  Sun,
  Monitor,
  X,
} from "lucide-react";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import { IconButton } from "../components/IconButton";

const primaryNavItems = [
  { id: "projects", label: "项目", icon: FolderKanban, path: "/projects" },
  { id: "scenarios", label: "方案", icon: Layers, path: "/projects/:projectId/scenarios", requiresProject: true },
  { id: "calculate", label: "计算", icon: Calculator, path: "/projects/:projectId/scenarios/:scenarioId/calculate", requiresProject: true },
  { id: "queue", label: "队列", icon: List, path: "/projects/:projectId/queue", requiresProject: true },
  { id: "export", label: "导出", icon: Download, path: "/projects/:projectId/export", requiresProject: true },
];

function getActiveNavId(pathname: string): string {
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return "settings";
  if (/\/queue(?:\/|$)/.test(pathname)) return "queue";
  if (/\/export(?:\/|$)/.test(pathname)) return "export";
  if (/\/scenarios\/[^/]+\/calculate(?:\/|$)/.test(pathname)) return "calculate";
  if (/\/scenarios(?:\/|$)/.test(pathname)) return "scenarios";
  return "projects";
}

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const serviceOnline = useTaichiFlowStore((state) => state.serviceOnline);
  const metrics = useTaichiFlowStore((state) => state.metrics);
  const theme = useTaichiFlowStore((state) => state.theme);
  const setTheme = useTaichiFlowStore((state) => state.setTheme);
  const toasts = useTaichiFlowStore((state) => state.toasts);
  const removeToast = useTaichiFlowStore((state) => state.removeToast);
  const [collapsed, setCollapsed] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const activeRoute = getActiveNavId(location.pathname);

  const resolvedTheme =
    theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;

  return (
    <div style={{ display: "flex", height: "100vh", width: "100vw", overflow: "hidden" }}>
      {/* 左侧导航 */}
      <aside
        style={{
          width: collapsed ? 56 : 180,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
          transition: "width 200ms ease",
        }}
      >
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            padding: "0 12px",
            borderBottom: "1px solid var(--color-border)",
            gap: 8,
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: "var(--radius-medium)",
              background: "var(--color-surface-secondary)",
              border: "1px solid var(--color-border-strong)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--color-brand)",
              fontWeight: 700,
              fontSize: 12,
              flexShrink: 0,
            }}
          >
            TF
          </div>
          {!collapsed && (
            <span className="tf-subtitle" style={{ color: "var(--color-foreground)" }}>
              Taichi-Flow
            </span>
          )}
        </div>

        <nav style={{ flex: 1, padding: "8px 0", display: "flex", flexDirection: "column", gap: 2 }}>
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeRoute === item.id;
            const isDisabled = Boolean(item.requiresProject && !activeProject);
            return (
              <button
                key={item.id}
                type="button"
                disabled={isDisabled}
                aria-disabled={isDisabled}
                aria-current={isActive ? "page" : undefined}
                aria-label={item.label}
                title={isDisabled ? "请先新建或打开项目" : collapsed ? item.label : undefined}
                onClick={() => {
                  const projectId = activeProject?.project_id || "";
                  const scenarioId = location.pathname.match(/\/scenarios\/([^/]+)/)?.[1] || "";
                  if (item.id === "calculate" && !scenarioId) {
                    navigate(`/projects/${projectId}/scenarios`);
                    return;
                  }
                  navigate(item.path.replace(":projectId", projectId).replace(":scenarioId", scenarioId));
                }}
                style={{
                  width: "calc(100% - 16px)",
                  margin: "0 8px",
                  height: 36,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "0 10px",
                  borderRadius: "var(--radius-medium)",
                  background: isActive && !isDisabled ? "var(--color-brand-bg-subtle)" : "transparent",
                  color: isDisabled
                    ? "var(--color-foreground-tertiary)"
                    : isActive
                      ? "var(--color-brand)"
                      : "var(--color-foreground-secondary)",
                  border: "none",
                  cursor: isDisabled ? "not-allowed" : "pointer",
                  opacity: isDisabled ? 0.48 : 1,
                  fontSize: 13,
                  fontWeight: isActive ? 600 : 400,
                  textAlign: "left",
                  transition: "background-color 120ms ease, color 120ms ease",
                }}
                onMouseEnter={(e) => {
                  if (!isActive && !isDisabled) e.currentTarget.style.backgroundColor = "var(--color-surface-hover)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = isActive && !isDisabled ? "var(--color-brand-bg-subtle)" : "transparent";
                }}
              >
                <Icon size={18} />
                {!collapsed && <span>{item.label}</span>}
              </button>
            );
          })}
        </nav>

        <div
          data-testid="sidebar-footer"
          style={{
            borderTop: "1px solid var(--color-border)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 2,
            padding: "8px 0",
          }}
        >
          <button
            type="button"
            aria-label="设置"
            aria-current={activeRoute === "settings" ? "page" : undefined}
            title={collapsed ? "设置" : undefined}
            onClick={() => navigate("/settings")}
            style={{
              width: "calc(100% - 16px)",
              height: 36,
              margin: "0 8px",
              padding: "0 10px",
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "flex-start",
              gap: 10,
              border: "none",
              borderRadius: "var(--radius-medium)",
              background: activeRoute === "settings" ? "var(--color-brand-bg-subtle)" : "transparent",
              color: activeRoute === "settings" ? "var(--color-brand)" : "var(--color-foreground-secondary)",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: activeRoute === "settings" ? 600 : 400,
            }}
          >
            <Settings size={18} />
            {!collapsed && <span>设置</span>}
          </button>
          <button
            type="button"
            aria-label={collapsed ? "展开导航" : "折叠导航"}
            title={collapsed ? "展开导航" : "折叠导航"}
            onClick={() => setCollapsed((current) => !current)}
            style={{
              width: "calc(100% - 16px)",
              height: 36,
              margin: "0 8px",
              padding: "0 10px",
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "flex-start",
              gap: 10,
              border: "none",
              borderRadius: "var(--radius-medium)",
              background: "transparent",
              color: "var(--color-foreground-tertiary)",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            <PanelLeft size={18} style={{ transform: collapsed ? "rotate(180deg)" : "none" }} />
            {!collapsed && <span>收起侧栏</span>}
          </button>
        </div>
      </aside>

      {/* 主内容区 */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* 顶部上下文条 */}
        <header
          style={{
            height: 56,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 20px",
            borderBottom: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface)",
          }}
        >
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 16, minWidth: 0, overflow: "hidden" }}>
            <span className="tf-subtitle tf-ellipsis" style={{ color: "var(--color-foreground)", maxWidth: 190, flexShrink: 0 }}>
              {activeProject ? activeProject.name : "未选择项目"}
            </span>
            {activeProject && (
              <span
                className="tf-caption tf-ellipsis"
                title={activeProject.root_path}
                style={{ color: "var(--color-foreground-tertiary)", flex: "1 1 140px", minWidth: 60, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {activeProject.root_path}
              </span>
            )}
            {activeProject && (
              <span
                className="tf-caption"
                style={{
                  padding: "2px 8px",
                  borderRadius: "var(--radius-medium)",
                  background: "var(--color-surface-tertiary)",
                  color: "var(--color-foreground-secondary)",
                }}
              >
                输入版本由当前场景修订决定
              </span>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-foreground-secondary)" }}>
              <Cpu size={14} />
              <span className="tf-caption">CPU {metrics.cpu_percent ?? 0}%</span>
              <Monitor size={14} />
              <span className="tf-caption">GPU {metrics.gpu_percent ?? 0}%</span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
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
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 8px",
                borderRadius: "var(--radius-medium)",
                background: serviceOnline ? "var(--color-success-bg)" : "var(--color-error-bg)",
                color: serviceOnline ? "var(--color-success)" : "var(--color-error)",
              }}
            >
              {serviceOnline ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
              <span className="tf-caption">{serviceOnline ? "服务在线" : "服务离线"}</span>
            </div>

            <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", minWidth: 80, textAlign: "right" }}>
              {currentTime.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          </div>
        </header>

        {/* 页面内容 */}
        <main style={{ flex: 1, minHeight: 0, overflow: "hidden", position: "relative" }}>
          <Outlet />
        </main>
      </div>

      {/* Toast 层 */}
      <div
        style={{
          position: "fixed",
          top: 68,
          right: 20,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          zIndex: 1000,
          maxWidth: 360,
        }}
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            style={{
              padding: "12px 16px",
              borderRadius: "var(--radius-large)",
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              boxShadow: "var(--shadow-dialog)",
              display: "flex",
              alignItems: "center",
              gap: 10,
              animation: "tf-toast-in 200ms ease",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background:
                  toast.type === "success"
                    ? "var(--color-success)"
                    : toast.type === "error"
                    ? "var(--color-error)"
                    : toast.type === "warning"
                    ? "var(--color-warning)"
                    : "var(--color-info)",
              }}
            />
            <span className="tf-body" style={{ flex: 1, color: "var(--color-foreground)" }}>
              {toast.message}
            </span>
            <button
              onClick={() => removeToast(toast.id)}
              aria-label="关闭提示"
              title="关闭提示"
              style={{ display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-foreground-tertiary)" }}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes tf-toast-in {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
