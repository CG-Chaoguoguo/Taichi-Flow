import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Check, Database, Play, Settings2, BarChart3, Save } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { isVisualizableInput } from "../../constants/visualizableInputs";
import { VisualizationCanvas } from "./VisualizationCanvas";
import { InputModule } from "./InputModule";
import { ParameterModule } from "./ParameterModule";
import { RunModule } from "./RunModule";
import { ResultModule } from "./ResultModule";
import { StatusBadge } from "../../components/StatusBadge";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";
import type { Scenario } from "../../types";

export type WorkspaceModule = "input" | "parameter" | "run" | "result";

const PREVIEW_SCENARIO: Scenario = {
  scenario_id: "",
  project_id: "",
  name: "未选择方案",
  input_revision_id: null,
  parameter_patch: {},
  effective_parameters: {},
  status: "draft",
  progress: 0,
  latest_simulation_id: null,
  result_family_count: 0,
  file_count: 0,
  created_at: "",
  updated_at: "",
};

export function CalculateWorkspace() {
  const { projectId, scenarioId } = useParams<{ projectId?: string; scenarioId?: string }>();
  const navigate = useNavigate();
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const layerVisibility = useTaichiFlowStore((state) => state.layerVisibility);
  const layerOrder = useTaichiFlowStore((state) => state.layerOrder);
  const updateScenario = useTaichiFlowStore((state) => state.updateScenario);
  const fetchScenarios = useTaichiFlowStore((state) => state.fetchScenarios);
  const setLayerVisibility = useTaichiFlowStore((state) => state.setLayerVisibility);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [activeModule, setActiveModule] = useState<WorkspaceModule>("input");
  const [canvasState, setCanvasState] = useState({ zoom: 1, offsetX: 0, offsetY: 0, selectedLayer: "" });
  const [draftPatch, setDraftPatch] = useState<Record<string, unknown>>({});
  const visibleLayers = useMemo(() => {
    const orderIndex = new Map(layerOrder.map((fileId, index) => [fileId, index]));
    return inputFiles
      .filter((file) => isVisualizableInput(file) && layerVisibility[file.file_id] === true)
      .sort((left, right) => (orderIndex.get(left.file_id) ?? 0) - (orderIndex.get(right.file_id) ?? 0))
      .map((file) => ({ fileId: file.file_id, name: file.name, family: file.family }));
  }, [inputFiles, layerVisibility, layerOrder]);

  const scenario = useMemo(
    () => (scenarioId ? scenarios.find((item) => item.scenario_id === scenarioId) : undefined),
    [scenarios, scenarioId],
  );
  const hasBoundScenario = Boolean(activeProject && scenario);
  const displayScenario = scenario ?? PREVIEW_SCENARIO;
  const readOnly = !hasBoundScenario;

  useEffect(() => {
    setDraftPatch({ ...(scenario?.parameter_patch || {}) });
  }, [scenario?.scenario_id, scenario?.updated_at]);

  const persistPatch = async () => {
    if (!scenario) return;
    await updateScenario(scenario.scenario_id, { parameter_patch: draftPatch });
    await fetchScenarios();
  };

  const handleSave = async () => {
    if (!scenario) return;
    try {
      await persistPatch();
      addToast({ type: "success", message: "方案已保存" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "保存方案失败" });
    }
  };

  const bannerText = !activeProject
    ? "尚未打开项目：可浏览计算工作台布局，输入与参数均为只读。"
    : !scenario
      ? "尚未选择方案：可管理项目资产；参数、运行与结果暂为只读。"
      : null;

  return (
    <div className="tf-fill-col tf-animate-in">
      <div className="tf-workspace-header tf-mica">
        <div className="tf-row tf-min-w-0">
          <IconButton
            icon={<ArrowLeft size={18} />}
            label={activeProject ? "返回方案管理" : "返回项目列表"}
            onClick={() => navigate(activeProject ? `/projects/${activeProject.project_id}/scenarios` : "/projects")}
            size="small"
          />
          <div className="tf-min-w-0">
            <div className="tf-subtitle tf-row tf-gap-2">
              {displayScenario.name}
              {hasBoundScenario ? <StatusBadge variant={displayScenario.status} dot /> : <StatusBadge variant="neutral">预览</StatusBadge>}
            </div>
            <div className="tf-caption tf-text-tertiary">
              {hasBoundScenario
                ? `${displayScenario.binding_state === "runtime_snapshot" ? "运行输入快照已冻结" : "草稿输入绑定，开始计算时冻结"} · ${displayScenario.scenario_id}`
                : activeProject
                  ? `${activeProject.name} · 等待选择或创建方案`
                  : "计算工作台预览"}
            </div>
          </div>
        </div>
        <div className="tf-row">
          {hasBoundScenario ? (
            <span className="tf-caption tf-saved-hint">
              <Check size={14} />
              已保存
            </span>
          ) : null}
          <Button
            variant="secondary"
            size="small"
            icon={<Save size={14} />}
            disabled={
              readOnly ||
              displayScenario.status === "completed" ||
              displayScenario.status === "archived" ||
              displayScenario.status === "running" ||
              displayScenario.status === "queued"
            }
            onClick={() => void handleSave()}
          >
            保存方案
          </Button>
        </div>
      </div>

      {bannerText ? (
        <div role="status" className="tf-workspace-banner tf-caption">
          {bannerText}
          {!activeProject ? (
            <button type="button" className="tf-link-button" onClick={() => navigate("/projects")}>
              去打开项目
            </button>
          ) : null}
          {activeProject && !scenario ? (
            <button type="button" className="tf-link-button" onClick={() => navigate(`/projects/${activeProject.project_id}/scenarios`)}>
              去方案管理
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="tf-fill-row">
        <div className="tf-canvas-pane">
          <VisualizationCanvas projectId={activeProject?.project_id || projectId} state={canvasState} setState={setCanvasState} activeModule={activeModule} visibleLayers={visibleLayers} />
        </div>

        <div className="tf-module-rail">
          <ModuleAccordion
            title="输入"
            icon={<Database size={16} />}
            summary={`${inputFiles.filter((file) => file.status === "ready").length}/${inputFiles.length} 就绪`}
            isActive={activeModule === "input"}
            onClick={() => setActiveModule("input")}
          >
            <InputModule
              selectedFamily="dem"
              readOnly={!activeProject}
               onFocusLayer={(id) => {
                 setLayerVisibility(id, true);
                 setCanvasState((current) => ({ ...current, selectedLayer: id }));
               }}
            />
          </ModuleAccordion>
          <ModuleAccordion
            title="参数"
            icon={<Settings2 size={16} />}
            summary={`${Object.keys(draftPatch).length} 项变更`}
            isActive={activeModule === "parameter"}
            onClick={() => setActiveModule("parameter")}
          >
            <ParameterModule
              scenario={displayScenario}
              readOnly={readOnly}
              draftPatch={draftPatch}
              onDraftChange={setDraftPatch}
              onSave={persistPatch}
            />
          </ModuleAccordion>
          <ModuleAccordion
            title="运行"
            icon={<Play size={16} />}
            summary={displayScenario.status === "running" ? "运行中" : readOnly ? "只读" : "待模拟"}
            isActive={activeModule === "run"}
            onClick={() => setActiveModule("run")}
          >
            <RunModule scenario={displayScenario} readOnly={readOnly} />
          </ModuleAccordion>
          <ModuleAccordion
            title="结果"
            icon={<BarChart3 size={16} />}
            summary={`${displayScenario.result_family_count} 个结果族`}
            isActive={activeModule === "result"}
            onClick={() => setActiveModule("result")}
          >
            <ResultModule scenario={displayScenario} readOnly={readOnly} />
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
    <div className={`tf-module-accordion${isActive ? " is-active" : ""}`}>
      <button
        onClick={onClick}
        aria-expanded={isActive}
        className={`tf-module-header${isActive ? " active" : ""}`}
      >
        <span className="tf-button-icon">{icon}</span>
        <span>{title}</span>
        <span className="tf-module-summary">{summary}</span>
        <span className="tf-module-chevron">▼</span>
      </button>
      <div
        ref={contentRef}
        className={`tf-module-accordion-body${isActive ? " is-open" : ""}`}
      >
        {children}
      </div>
    </div>
  );
}
