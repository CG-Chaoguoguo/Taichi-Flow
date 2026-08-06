import { useState } from "react";
import { Copy, Layers, Plus, Trash2 } from "lucide-react";
import { useTaichiFlowStore, type EditorSelection } from "../../stores/taichiFlowStore";
import { StatusBadge } from "../../components/StatusBadge";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";
import { CreateScenarioNameDialog } from "../../components/CreateScenarioNameDialog";
import { PanelCollapseButton } from "../../components/layout/ResizablePaneGroup";

type ScenarioOutlinerProps = {
  selectedScenarioId?: string;
  onSelectScenario: (scenarioId: string) => void;
  onToggleCollapse?: () => void;
};

function isSelected(selection: EditorSelection | null, kind: EditorSelection["kind"], id?: string): boolean {
  if (!selection || selection.kind !== kind) return false;
  if (selection.kind === "input") return selection.family === id;
  if (selection.kind === "scenario" || selection.kind === "result") return selection.scenarioId === id;
  if (selection.kind === "queue") return selection.queueItemId === id;
  return false;
}

export function ScenarioOutliner({ selectedScenarioId, onSelectScenario, onToggleCollapse }: ScenarioOutlinerProps) {
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const queue = useTaichiFlowStore((state) => state.queue);
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const setEditorSelection = useTaichiFlowStore((state) => state.setEditorSelection);
  const createScenario = useTaichiFlowStore((state) => state.createScenario);
  const duplicateScenario = useTaichiFlowStore((state) => state.duplicateScenario);
  const deleteScenario = useTaichiFlowStore((state) => state.deleteScenario);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [creating, setCreating] = useState(false);

  const runningCount = queue.filter((item) => item.status === "starting" || item.status === "running" || item.status === "stopping").length;
  const queuedCount = queue.filter((item) => item.status === "queued").length;
  const waitingCount = queue.filter((item) => item.status === "waiting").length;
  const suggestedName = `方案 ${scenarios.length + 1}`;

  const handleCreate = async (name: string) => {
    setCreating(true);
    try {
      const scenario = await createScenario(name);
      setEditorSelection({ kind: "scenario", scenarioId: scenario.scenario_id });
      onSelectScenario(scenario.scenario_id);
      setShowCreateDialog(false);
      addToast({ type: "success", message: "已创建方案" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "创建方案失败" });
    } finally {
      setCreating(false);
    }
  };

  return (
    <aside className="tf-outliner" aria-label="项目大纲">
      <div className="tf-outliner-section tf-outliner-section--grow">
        <div className="tf-outliner-section-title">
          <Layers size={12} />
          <span>方案</span>
          <div className="tf-outliner-title-actions">
            {onToggleCollapse ? <PanelCollapseButton label="方案栏" collapsed={false} direction="left" onToggle={onToggleCollapse} /> : null}
            <IconButton size="small" icon={<Plus size={14} />} label="新建方案" onClick={() => setShowCreateDialog(true)} disabled={creating} />
          </div>
        </div>
        {scenarios.length === 0 ? (
          <div className="tf-outliner-empty">
            <p className="tf-caption tf-text-tertiary">暂无方案</p>
            <Button size="small" variant="secondary" icon={<Plus size={14} />} onClick={() => setShowCreateDialog(true)} disabled={creating}>
              创建方案
            </Button>
          </div>
        ) : (
          scenarios.map((scenario) => {
            const active = selectedScenarioId === scenario.scenario_id || isSelected(editorSelection, "scenario", scenario.scenario_id);
            return (
              <div key={scenario.scenario_id} className={`tf-outliner-row${active ? " is-active" : ""}`}>
                <button
                  type="button"
                  className={`tf-outliner-item${active ? " active" : ""}`}
                  onClick={() => {
                    setEditorSelection({ kind: "scenario", scenarioId: scenario.scenario_id });
                    onSelectScenario(scenario.scenario_id);
                  }}
                >
                  <span className="tf-ellipsis">{scenario.name}</span>
                  <StatusBadge variant={scenario.status} />
                </button>
                <div className="tf-outliner-actions">
                  <IconButton
                    size="small"
                    icon={<Copy size={12} />}
                    label="复制方案"
                    onClick={() =>
                      void duplicateScenario(scenario.scenario_id)
                        .then((copy) => {
                          setEditorSelection({ kind: "scenario", scenarioId: copy.scenario_id });
                          onSelectScenario(copy.scenario_id);
                        })
                        .catch((error) => addToast({ type: "error", message: error instanceof Error ? error.message : "复制失败" }))
                    }
                  />
                  {scenario.status === "draft" || scenario.status === "ready" ? (
                    <IconButton
                      size="small"
                      icon={<Trash2 size={12} />}
                      label="删除方案"
                      className="tf-text-error"
                      onClick={() =>
                        void deleteScenario(scenario.scenario_id).catch((error) =>
                          addToast({ type: "error", message: error instanceof Error ? error.message : "删除失败" }),
                        )
                      }
                    />
                  ) : null}
                  {scenario.status === "completed" ? (
                    <button
                      type="button"
                      className="tf-outliner-link"
                      onClick={() => setEditorSelection({ kind: "result", scenarioId: scenario.scenario_id })}
                    >
                      结果
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="tf-outliner-section">
        <div className="tf-outliner-section-title">
          <span>队列</span>
          {runningCount > 0 ? <span className="tf-chip">{runningCount} 进行中</span> : queuedCount > 0 ? <span className="tf-chip">{queuedCount} 排队中</span> : waitingCount > 0 ? <span className="tf-chip">{waitingCount} 待运行</span> : <span className="tf-chip">空闲</span>}
        </div>
        {queue.slice(0, 4).map((item) => (
          <button
            key={item.queue_item_id}
            type="button"
            className={`tf-outliner-item${isSelected(editorSelection, "queue", item.queue_item_id) ? " active" : ""}`}
            onClick={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })}
          >
            <span className="tf-ellipsis">{item.scenario_name}</span>
            <StatusBadge variant={item.status} />
          </button>
        ))}
      </div>

      {showCreateDialog ? (
        <CreateScenarioNameDialog
          open
          initialName={suggestedName}
          busy={creating}
          onClose={() => {
            if (!creating) setShowCreateDialog(false);
          }}
          onCreate={handleCreate}
        />
      ) : null}
    </aside>
  );
}
