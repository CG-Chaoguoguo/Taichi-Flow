import { ArchiveRestore, AlertTriangle, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect } from "react";
import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";
import type { Scenario, ScenarioDeletePreview } from "../types";

type ScenarioDeleteDialogProps = {
  open: boolean;
  scenario: Scenario | null;
  preview: ScenarioDeletePreview | null;
  busy?: boolean;
  onClose: () => void;
  onArchive: () => void | Promise<void>;
  onPermanentDelete: () => void | Promise<void>;
};

export function ScenarioDeleteDialog({
  open,
  scenario,
  preview,
  busy = false,
  onClose,
  onArchive,
  onPermanentDelete,
}: ScenarioDeleteDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  if (!open || !scenario || !preview) return null;
  const hasHistory = preview.preserves_history;
  const archiveBlocked = !preview.can_archive;
  const permanentBlocked = !preview.can_permanently_delete;
  const hasActiveWork = preview.active_simulation_ids.length > 0;
  const hasVisibleQueue = preview.blocking_queue_item_ids.length > 0;

  return (
    <div className="tf-dialog-overlay" onMouseDown={() => !busy && onClose()}>
      <section
        className="tf-dialog tf-dialog-narrow tf-scenario-delete-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scenario-delete-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="tf-dialog-header">
          <div className="tf-row tf-gap-2">
            <AlertTriangle size={18} className={permanentBlocked ? "tf-text-warning" : "tf-text-error"} />
            <h2 id="scenario-delete-title" className="tf-subtitle">删除方案</h2>
          </div>
          <p className="tf-caption tf-text-secondary tf-break-word">
            永久删除将移除“{scenario.name}”的方案、队列记录、运行历史、结果与输出文件，且无法恢复。
          </p>
        </div>
        <div className="tf-dialog-body tf-stack-sm">
          <div className="tf-delete-impact" aria-label="删除影响">
            <span>{preview.queue_item_count} 条队列记录</span>
            <span>{preview.run_count} 条运行记录</span>
            <span>{preview.result_family_count} 个结果族</span>
            <span>{preview.output_count} 个输出</span>
            <span>{preview.export_count} 个导出</span>
            {preview.derived_scenario_count > 0 ? <span>{preview.derived_scenario_count} 个派生方案将保留</span> : null}
          </div>
          {hasActiveWork || hasVisibleQueue ? (
            <div className="tf-warning-row" role="alert">
              {hasActiveWork
                ? `方案仍有 ${preview.active_simulation_ids.length} 个活动计算，永久删除前请先停止。`
                : `方案仍有 ${preview.blocking_queue_item_ids.length} 个可见队列项；归档需先移除，永久删除可直接清理非活动项。`}
            </div>
          ) : null}
          {hasHistory ? <div className="tf-caption tf-text-secondary">移入归档会保留历史与输出，并从活动列表隐藏。</div> : null}
        </div>
        <div className="tf-dialog-footer">
          <Button variant="secondary" onClick={onClose} disabled={busy}>取消</Button>
          {hasHistory ? (
            <Button
              variant="secondary"
              icon={<ArchiveRestore size={16} />}
              onClick={() => void onArchive()}
              disabled={busy || archiveBlocked}
            >
              移入归档
            </Button>
          ) : null}
          <Button
            variant="danger"
            icon={<Trash2 size={16} />}
            onClick={() => void onPermanentDelete()}
            disabled={busy || permanentBlocked}
          >
            {busy ? "处理中…" : "永久删除"}
          </Button>
        </div>
      </section>
    </div>
  );
}

type ArchivedScenariosDialogProps = {
  open: boolean;
  scenarios: Scenario[];
  restoringId?: string | null;
  onClose: () => void;
  onRestore: (scenarioId: string) => void | Promise<void>;
};

export function ArchivedScenariosDialog({
  open,
  scenarios,
  restoringId = null,
  onClose,
  onRestore,
}: ArchivedScenariosDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !restoringId) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open, restoringId]);

  if (!open) return null;
  return (
    <div className="tf-dialog-overlay" onMouseDown={() => !restoringId && onClose()}>
      <section
        className="tf-dialog tf-dialog-narrow tf-archive-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="archived-scenarios-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="tf-dialog-header">
          <div className="tf-row tf-justify-between tf-gap-2">
            <div className="tf-row tf-gap-2">
              <ArchiveRestore size={18} className="tf-text-brand" />
              <h2 id="archived-scenarios-title" className="tf-subtitle">归档方案</h2>
            </div>
            <Button variant="ghost" size="small" icon={<X size={16} />} aria-label="关闭归档方案" onClick={onClose} disabled={Boolean(restoringId)}>关闭</Button>
          </div>
          <p className="tf-caption tf-text-secondary">归档方案不会出现在活动列表中；恢复后可再次加入模拟队列。</p>
        </div>
        <div className="tf-dialog-body tf-stack-sm">
          {scenarios.length === 0 ? (
            <div className="tf-empty tf-body tf-text-tertiary">暂无归档方案</div>
          ) : scenarios.map((scenario) => (
            <div key={scenario.scenario_id} className="tf-list-item tf-row tf-gap-2">
              <div className="tf-flex-1 tf-min-w-0">
                <div className="tf-body tf-font-medium tf-ellipsis">{scenario.name}</div>
                <div className="tf-caption tf-text-tertiary">{scenario.latest_simulation_id ? "保留运行历史" : "无运行历史"}</div>
              </div>
              <StatusBadge variant="archived">已归档</StatusBadge>
              <Button
                size="small"
                variant="secondary"
                icon={<RotateCcw size={14} />}
                onClick={() => void onRestore(scenario.scenario_id)}
                disabled={Boolean(restoringId)}
              >
                {restoringId === scenario.scenario_id ? "恢复中…" : "恢复"}
              </Button>
            </div>
          ))}
        </div>
        <div className="tf-dialog-footer">
          <span className="tf-caption tf-text-tertiary">共 {scenarios.length} 个归档方案</span>
          <Button variant="secondary" onClick={onClose} disabled={Boolean(restoringId)}>关闭</Button>
        </div>
      </section>
    </div>
  );
}
