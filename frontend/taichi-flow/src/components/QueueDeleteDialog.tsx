import { useEffect } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import { Button } from "./Button";
import type { QueueDeletePreview } from "../types";

type QueueDeleteDialogProps = {
  open: boolean;
  preview: QueueDeletePreview | null;
  busy?: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
};

export function QueueDeleteDialog({ open, preview, busy = false, onClose, onConfirm }: QueueDeleteDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  if (!open || !preview) return null;

  return (
    <div className="tf-dialog-overlay" onMouseDown={() => !busy && onClose()}>
      <section
        className="tf-dialog tf-dialog-narrow tf-queue-delete-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="queue-delete-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="tf-dialog-header">
          <div className="tf-row tf-gap-2">
            <AlertTriangle size={18} className="tf-text-warning" />
            <h2 id="queue-delete-title" className="tf-subtitle">确认移除队列项</h2>
          </div>
          <p className="tf-caption tf-text-secondary">
            只从队列视图移除记录；模拟 API、运行结果、输出文件和重试链都会保留。
          </p>
        </div>
        <div className="tf-dialog-body tf-stack-sm">
          <ul className="tf-asset-delete-list" aria-label="待移除队列项">
            {preview.items.map((item) => (
              <li key={item.queue_item_id}>
                <span className="tf-ellipsis">{item.scenario_name}</span>
              </li>
            ))}
          </ul>
          <div className="tf-delete-impact">
            <span>{preview.items.length} 项将从队列界面隐藏。</span>
            <span>{preview.items.filter((item) => Boolean(item.simulation_id)).length} 条已有运行结果会保留。</span>
          </div>
          <div className="tf-caption tf-text-secondary">此操作不可撤销，但不会删除计算结果。</div>
        </div>
        <div className="tf-dialog-footer">
          <Button variant="secondary" onClick={onClose} disabled={busy}>取消</Button>
          <Button
            variant="danger"
            icon={<Trash2 size={16} />}
            onClick={() => void onConfirm()}
            disabled={busy || !preview.can_delete}
          >
            移除 {preview.queue_item_ids.length} 项
          </Button>
        </div>
      </section>
    </div>
  );
}
