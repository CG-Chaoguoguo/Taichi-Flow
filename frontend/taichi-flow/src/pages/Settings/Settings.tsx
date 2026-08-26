import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { ComputeGateSettingsPanel } from "./ComputeGateSettingsPanel";

export function Settings() {
  const theme = useTaichiFlowStore((state) => state.theme);
  const setTheme = useTaichiFlowStore((state) => state.setTheme);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const navigate = useNavigate();
  const editorPath = activeProject
    ? `/editor/${activeProject.project_id}${scenarios[0] ? `/scenarios/${scenarios[0].scenario_id}` : ""}`
    : null;

  useEffect(() => {
    if (window.location.hash !== "#compute-gates") return;
    document.getElementById("compute-gates")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <div className="tf-page">
      <div className="tf-page-content tf-page-content--narrow tf-animate-in">
        <div className="tf-page-header">
          <div>
            <h1 className="tf-display tf-mb-2">设置</h1>
            <p className="tf-body tf-text-secondary">管理界面主题、计算门禁和数值变种。</p>
          </div>
          {editorPath ? (
            <Button variant="secondary" size="small" onClick={() => navigate(editorPath)}>
              返回项目编辑器
            </Button>
          ) : null}
        </div>

        <div className="tf-card tf-mb-6">
          <h2 className="tf-subtitle tf-card-header">外观</h2>
          <div className="tf-stack">
            {[
              { key: "light", label: "浅色", desc: "Fluent 2 浅色 Mica 主题" },
              { key: "dark", label: "深色", desc: "Fluent 2 深色 Mica 主题（默认）" },
              { key: "high-contrast", label: "高对比度", desc: "提升可访问性，禁用 Acrylic 模糊" },
              { key: "system", label: "跟随系统", desc: "自动适配系统主题" },
            ].map((t) => (
              <label key={t.key} className="tf-list-item">
                <input type="radio" name="theme" value={t.key} checked={theme === t.key} onChange={() => setTheme(t.key as typeof theme)} />
                <div>
                  <div className="tf-body tf-font-medium">{t.label}</div>
                  <div className="tf-caption tf-text-tertiary">{t.desc}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        <ComputeGateSettingsPanel />

        <div className="tf-card">
          <h2 className="tf-subtitle tf-card-header">关于</h2>
          <div className="tf-body tf-text-secondary tf-mb-2">Taichi-Flow 计算工作台</div>
          <div className="tf-caption tf-text-tertiary">版本 0.1.0 · Fluent 2 视觉语言 · React + Vite + Zustand</div>
          <div className="tf-caption tf-text-tertiary tf-mt-2">
            当前界面通过 Taichi-Flow REST API 与持久化工作区交互；主题与无障碍偏好保存在浏览器本地，计算门禁保存在工作台设置中。
          </div>
        </div>
      </div>
    </div>
  );
}
