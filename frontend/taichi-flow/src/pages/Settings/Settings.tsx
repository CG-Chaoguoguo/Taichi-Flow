import { useTaichiFlowStore } from "../../stores/taichiFlowStore";

export function Settings() {
  const theme = useTaichiFlowStore((state) => state.theme);
  const setTheme = useTaichiFlowStore((state) => state.setTheme);

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "32px" }}>
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <div style={{ marginBottom: 24 }}>
          <h1 className="tf-display" style={{ marginBottom: 4 }}>
            设置
          </h1>
          <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
            管理界面主题、工作区显示和日志级别。
          </p>
        </div>

        <div
          style={{
            padding: 24,
            borderRadius: "var(--radius-xlarge)",
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            boxShadow: "var(--shadow-rest)",
            marginBottom: 24,
          }}
        >
          <h2 className="tf-subtitle" style={{ marginBottom: 16 }}>
            外观
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              { key: "light", label: "浅色", desc: "Linear 浅色主题" },
              { key: "dark", label: "深色", desc: "Linear 深色主题" },
              { key: "high-contrast", label: "高对比度", desc: "提升可访问性" },
              { key: "system", label: "跟随系统", desc: "自动适配系统主题" },
            ].map((t) => (
              <label
                key={t.key}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: 12,
                  borderRadius: "var(--radius-large)",
                  border: "1px solid var(--color-border)",
                  background: "var(--color-surface)",
                  cursor: "pointer",
                }}
              >
                <input type="radio" name="theme" value={t.key} checked={theme === t.key} onChange={() => setTheme(t.key as typeof theme)} />
                <div>
                  <div className="tf-body" style={{ fontWeight: 500 }}>
                    {t.label}
                  </div>
                  <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                    {t.desc}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div
          style={{
            padding: 24,
            borderRadius: "var(--radius-xlarge)",
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            boxShadow: "var(--shadow-rest)",
          }}
        >
          <h2 className="tf-subtitle" style={{ marginBottom: 16 }}>
            关于
          </h2>
          <div className="tf-body" style={{ color: "var(--color-foreground-secondary)", marginBottom: 12 }}>
            Taichi-Flow 计算工作台
          </div>
          <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
            版本 0.1.0 · 基于 Linear 设计语言 · React + Vite + Zustand
          </div>
          <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", marginTop: 8 }}>
            当前界面通过 Taichi-Flow REST API 与持久化工作区交互；主题与无障碍偏好保存在浏览器本地。
          </div>
        </div>
      </div>
    </div>
  );
}
