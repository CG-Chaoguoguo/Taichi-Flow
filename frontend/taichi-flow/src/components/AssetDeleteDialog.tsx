import { useEffect } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import { Button } from "./Button";
import type { AssetDeletePreview } from "../types";

type AssetDeleteDialogProps = {
  open: boolean;
  preview: AssetDeletePreview | null;
  busy?: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
};

export function AssetDeleteDialog({ open, preview, busy = false, onClose, onConfirm }: AssetDeleteDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  if (!open || !preview) return null;
  const locked = preview.runtime_locked.length > 0;

  return (
    <div className="tf-dialog-overlay" onMouseDown={() => !busy && onClose()}>
      <section
        className="tf-dialog tf-dialog-narrow tf-asset-delete-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="asset-delete-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="tf-dialog-header">
          <div className="tf-row tf-gap-2">
            <AlertTriangle size={18} className={locked ? "tf-text-warning" : "tf-text-error"} />
            <h2 id="asset-delete-title" className="tf-subtitle">确认删除文件</h2>
          </div>
          <p className="tf-caption tf-text-secondary">
            删除会从项目资产库移除文件；已结束计算的运行快照仍会保留其内容哈希。
          </p>
        </div>
        <div className="tf-dialog-body tf-stack-sm">
          <ul className="tf-asset-delete-list" aria-label="待删除文件">
            {preview.assets.map((asset) => (
              <li key={asset.file_id}>
                <span className="tf-ellipsis">{asset.name}</span>
                {asset.runtime_lock?.locked ? <span className="tf-text-warning">计算引用中</span> : null}
              </li>
            ))}
          </ul>
          <div className="tf-delete-impact">
            <span>将解除 {preview.affected_scenario_ids.length} 个草稿方案中的 {preview.detached_binding_count} 处绑定。</span>
            <span>将自动取消 {preview.cancelled_queue_item_ids.length} 个等待任务。</span>
          </div>
          {locked ? (
            <div className="tf-warning-row">
              当前选择包含计算引用中的文件。请等待计算结束或取消本次选择。
            </div>
          ) : (
            <div className="tf-caption tf-text-secondary">此操作不可撤销。</div>
          )}
        </div>
        <div className="tf-dialog-footer">
          <Button variant="secondary" onClick={onClose} disabled={busy}>取消</Button>
          <Button variant="danger" icon={<Trash2 size={16} />} onClick={() => void onConfirm()} disabled={busy || locked}>
            删除 {preview.asset_ids.length} 项
          </Button>
        </div>
      </section>
    </div>
  );
}
