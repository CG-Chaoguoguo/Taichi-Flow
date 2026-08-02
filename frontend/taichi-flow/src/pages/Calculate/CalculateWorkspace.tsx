import { useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Check, Database, Play, Settings2, BarChart3, Save } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { VisualizationCanvas } from "./VisualizationCanvas";
import { InputModule } from "./InputModule";
import { ParameterModule } from "./ParameterModule";
import { RunModule } from "./RunModule";
import { ResultModule } from "./ResultModule";
import { StatusBadge } from "../../components/StatusBadge";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";

export type WorkspaceModule = "input" | "parameter" | "run" | "result";

export function CalculateWorkspace() {
  const { projectId, scenarioId } = useParams<{ projectId: string; scenarioId: string }>();
  const navigate = useNavigate();
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const inputRevisions = useTaichiFlowStore((state) => state.inputRevisions);
  const updateScenario = useTaichiFlowStore((state) => state.updateScenario);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [activeModule, setActiveModule] = useState<WorkspaceModule>("input");
  const [canvasState, setCanvasState] = useState({ zoom: 1, offsetX: 0, offsetY: 0, selectedLayer: "" });

  const handleSave = async () => {
    if (!scenario) return;
    try {
      await updateScenario(scenario.scenario_id, { parameter_patch: scenario.parameter_patch });
      addToast({ type: "success", message: "方案已保存" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "保存方案失败" });
    }
  };

  const scenario = useMemo(() => scenarios.find((s) => s.scenario_id === scenarioId), [scenarios, scenarioId]);

  if (!scenario || !activeProject) {
    return (
      <div style={{ padding: 48 }}>
        <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          方案不存在或项目未选择。
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* 顶部方案栏 */}
      <div
        style={{
          height: 56,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 20px",
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-surface)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <IconButton
            icon={<ArrowLeft size={18} />}
            label="返回方案管理"
            onClick={() => navigate(`/projects/${projectId}/scenarios`)}
            size="small"
          />
          <div>
            <div className="tf-subtitle" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {scenario.name}
              <StatusBadge variant={scenario.status} dot />
            </div>
            <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
              输入版本 {inputRevisions.find((revision) => revision.revision_id === scenario.input_revision_id)?.version_tag || scenario.input_revision_id} · {scenario.scenario_id}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", display: "flex", alignItems: "center", gap: 4 }}>
            <Check size={14} />
            已保存
          </span>
          <Button variant="secondary" size="small" icon={<Save size={14} />} disabled={scenario.status === "completed" || scenario.status === "archived" || scenario.status === "running" || scenario.status === "queued"} onClick={() => void handleSave()}>
            保存方案
          </Button>
        </div>
      </div>

      {/* 主体 */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* 左侧画布：始终保持挂载 */}
        <div style={{ width: "65%", minWidth: 0, borderRight: "1px solid var(--color-border)", position: "relative" }}>
          <VisualizationCanvas state={canvasState} setState={setCanvasState} activeModule={activeModule} />
        </div>

        {/* 右侧抽屉 */}
        <div
          style={{
            width: "35%",
            minWidth: 360,
            maxWidth: 520,
            display: "flex",
            flexDirection: "column",
            background: "var(--color-surface)",
            overflow: "hidden",
          }}
        >
          <ModuleAccordion title="输入" icon={<Database size={16} />} summary={`${inputFiles.filter((file) => file.status === "ready").length}/${inputFiles.length} 就绪`} isActive={activeModule === "input"} onClick={() => setActiveModule("input")}>
            <InputModule onFocusLayer={(id) => setCanvasState((s) => ({ ...s, selectedLayer: id }))} />
          </ModuleAccordion>
          <ModuleAccordion
            title="参数"
            icon={<Settings2 size={16} />}
            summary={`${Object.keys(scenario.parameter_patch || {}).length} 项变更`}
            isActive={activeModule === "parameter"}
            onClick={() => setActiveModule("parameter")}
          >
            <ParameterModule scenario={scenario} />
          </ModuleAccordion>
          <ModuleAccordion title="运行" icon={<Play size={16} />} summary={scenario.status === "running" ? "运行中" : "待模拟"} isActive={activeModule === "run"} onClick={() => setActiveModule("run")}>
            <RunModule scenario={scenario} />
          </ModuleAccordion>
          <ModuleAccordion
            title="结果"
            icon={<BarChart3 size={16} />}
            summary={`${scenario.result_family_count} 个结果族`}
            isActive={activeModule === "result"}
            onClick={() => setActiveModule("result")}
          >
            <ResultModule scenario={scenario} />
          </ModuleAccordion>
        </div>
      </div>
    </div>
  );
}

function ModuleAccordion({
  title,
  icon,
  summary,
  isActive,
  onClick,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  summary: string;
  isActive: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  const contentRef = useRef<HTMLDivElement>(null);

  return (
    <div
      style={{
        borderBottom: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
        flex: isActive ? 1 : undefined,
        minHeight: isActive ? 200 : 48,
        transition: "flex 200ms ease",
      }}
    >
      <button
        onClick={onClick}
        aria-expanded={isActive}
        style={{
          height: 48,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "0 16px",
          border: "none",
          background: isActive ? "var(--color-brand-bg-subtle)" : "transparent",
          color: isActive ? "var(--color-brand)" : "var(--color-foreground)",
          cursor: "pointer",
          textAlign: "left",
          fontSize: 14,
          fontWeight: 600,
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center" }}>{icon}</span>
        <span>{title}</span>
        <span style={{ marginLeft: "auto", fontWeight: 400, color: "var(--color-foreground-secondary)" }}>{summary}</span>
        <span style={{ transform: isActive ? "rotate(180deg)" : "rotate(0)", transition: "transform 200ms ease" }}>▼</span>
      </button>
      <div
        ref={contentRef}
        style={{
          flex: 1,
          overflow: isActive ? "auto" : "hidden",
          height: isActive ? undefined : 0,
          minHeight: isActive ? 0 : 0,
          opacity: isActive ? 1 : 0,
          transition: "opacity 200ms ease, height 200ms ease",
        }}
      >
        {children}
      </div>
    </div>
  );
}
