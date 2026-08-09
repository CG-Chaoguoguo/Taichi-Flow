import { useMemo, useState } from "react";
import { ArchiveRestore, Copy, Layers, Plus, Trash2 } from "lucide-react";
import { useTaichiFlowStore, isActiveScenario, type EditorSelection } from "../../stores/taichiFlowStore";
import { StatusBadge } from "../../components/StatusBadge";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";
import { CreateScenarioNameDialog } from "../../components/CreateScenarioNameDialog";
import { ArchivedScenariosDialog, ScenarioDeleteDialog } from "../../components/ScenarioDialogs";
import { PanelCollapseButton } from "../../components/layout/ResizablePaneGroup";
import type { Scenario, ScenarioDeletePreview } from "../../types";

type ScenarioOutlinerProps = {
  selectedScenarioId?: string;
  onSelectScenario: (scenarioId: string) => void;
  onScenarioRemoved?: (scenarioId: string, nextScenarioId?: string) => void;
  onScenarioRestored?: (scenario: Scenario) => void;
  onToggleCollapse?: () => void;
};

function isSelected(selection: EditorSelection | null, id?: string): boolean {
  if (!selection) return false;
  if (selection.kind === "scenario" || selection.kind === "result") return selection.scenarioId === id;
  return false;
}

export function ScenarioOutliner({
  selectedScenarioId,
  onSelectScenario,
  onScenarioRemoved,
  onScenarioRestored,
  onToggleCollapse,
}: ScenarioOutlinerProps) {
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const setEditorSelection = useTaichiFlowStore((state) => state.setEditorSelection);
  const createScenario = useTaichiFlowStore((state) => state.createScenario);
  const duplicateScenario = useTaichiFlowStore((state) => state.duplicateScenario);
  const previewScenarioDeletion = useTaichiFlowStore((state) => state.previewScenarioDeletion);
  const archiveScenario = useTaichiFlowStore((state) => state.archiveScenario);
  const permanentlyDeleteScenario = useTaichiFlowStore((state) => state.permanentlyDeleteScenario);
  const restoreScenario = useTaichiFlowStore((state) => state.restoreScenario);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showArchiveDialog, setShowArchiveDialog] = useState(false);
  const [creating, setCreating] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Scenario | null>(null);
  const [deletePreview, setDeletePreview] = useState<ScenarioDeletePreview | null>(null);

  const activeScenarios = useMemo(() => scenarios.filter(isActiveScenario), [scenarios]);
  const archivedScenarios = useMemo(() => scenarios.filter((scenario) => !isActiveScenario(scenario)), [scenarios]);
  const suggestedName = `方案 ${activeScenarios.length + 1}`;

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

  const openDeleteDialog = async (scenario: Scenario) => {
    try {
      const preview = await previewScenarioDeletion(scenario.scenario_id);
      if (!preview) return;
      setDeleteTarget(scenario);
      setDeletePreview(preview);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "无法读取方案状态" });
    }
  };

  const closeDeleteDialog = () => {
    if (removing) return;
    setDeleteTarget(null);
    setDeletePreview(null);
  };

  const finishScenarioRemoval = (scenarioId: string) => {
    const removedIndex = activeScenarios.findIndex((scenario) => scenario.scenario_id === scenarioId);
    const next = activeScenarios[removedIndex + 1] || activeScenarios[removedIndex - 1];
    setEditorSelection(next ? { kind: "scenario", scenarioId: next.scenario_id } : { kind: "input", family: "all" });
    onScenarioRemoved?.(scenarioId, next?.scenario_id);
    if (next) onSelectScenario(next.scenario_id);
    setDeleteTarget(null);
    setDeletePreview(null);
  };

  const confirmArchive = async () => {
    if (!deleteTarget || !deletePreview || !deletePreview.can_archive) return;
    setRemoving(true);
    const scenarioId = deleteTarget.scenario_id;
    try {
      await archiveScenario(scenarioId);
      finishScenarioRemoval(scenarioId);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "归档方案失败" });
    } finally {
      setRemoving(false);
    }
  };

  const confirmPermanentDelete = async () => {
    if (!deleteTarget || !deletePreview || !deletePreview.can_permanently_delete) return;
    setRemoving(true);
    const scenarioId = deleteTarget.scenario_id;
    try {
      await permanentlyDeleteScenario(scenarioId);
      finishScenarioRemoval(scenarioId);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "方案操作失败" });
    } finally {
      setRemoving(false);
    }
  };

  const handleRestore = async (scenarioId: string) => {
    setRestoringId(scenarioId);
    try {
      const restored = await restoreScenario(scenarioId);
      if (!restored) return;
      setShowArchiveDialog(false);
      setEditorSelection({ kind: "scenario", scenarioId: restored.scenario_id });
      onSelectScenario(restored.scenario_id);
      onScenarioRestored?.(restored);
      addToast({ type: "success", message: "方案已恢复" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "恢复方案失败" });
    } finally {
      setRestoringId(null);
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
            <button
              type="button"
              className="tf-outliner-archive-button"
              aria-label={`查看归档方案（${archivedScenarios.length}）`}
              title="查看归档方案"
              onClick={() => setShowArchiveDialog(true)}
            >
              <ArchiveRestore size={14} />
              <span>{archivedScenarios.length}</span>
            </button>
          </div>
        </div>
        {activeScenarios.length === 0 ? (
          <div className="tf-outliner-empty">
            <p className="tf-caption tf-text-tertiary">暂无活动方案</p>
            <Button size="small" variant="secondary" icon={<Plus size={14} />} onClick={() => setShowCreateDialog(true)} disabled={creating}>
              创建方案
            </Button>
          </div>
        ) : activeScenarios.map((scenario) => {
          const active = selectedScenarioId === scenario.scenario_id || isSelected(editorSelection, scenario.scenario_id);
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
                <IconButton
                  size="small"
                  icon={<Trash2 size={12} />}
                  label="删除方案"
                  className="tf-text-error"
                  onClick={() => void openDeleteDialog(scenario)}
                />
                {scenario.status === "completed" ? (
                  <button type="button" className="tf-outliner-link" onClick={() => setEditorSelection({ kind: "result", scenarioId: scenario.scenario_id })}>
                    结果
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
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
      <ScenarioDeleteDialog
        open={Boolean(deleteTarget)}
        scenario={deleteTarget}
        preview={deletePreview}
        busy={removing}
        onClose={closeDeleteDialog}
        onArchive={confirmArchive}
        onPermanentDelete={confirmPermanentDelete}
      />
      <ArchivedScenariosDialog
        open={showArchiveDialog}
        scenarios={archivedScenarios}
        restoringId={restoringId}
        onClose={() => {
          if (!restoringId) setShowArchiveDialog(false);
        }}
        onRestore={handleRestore}
      />
    </aside>
  );
}
