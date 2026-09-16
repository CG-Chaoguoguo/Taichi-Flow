import { useEffect, useRef } from "react";
import { Trash2, X } from "lucide-react";
import { Button } from "./Button";

type AssetSelectionToolbarProps = {
  selectedCount: number;
  selectableCount: number;
  allSelected: boolean;
  partiallySelected: boolean;
  onToggleAll: () => void;
  onDelete: () => void;
  onCancel: () => void;
};

export function AssetSelectionToolbar({
  selectedCount,
  selectableCount,
  allSelected,
  partiallySelected,
  onToggleAll,
  onDelete,
  onCancel,
}: AssetSelectionToolbarProps) {
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = partiallySelected;
  }, [partiallySelected]);

  return (
    <div className="tf-asset-selection-toolbar" role="toolbar" aria-label="文件批量选择">
      <label className="tf-selection-toggle">
        <input
          ref={selectAllRef}
          type="checkbox"
          checked={allSelected}
          disabled={selectableCount === 0}
          onChange={onToggleAll}
          aria-label="全选当前筛选结果中可删除的文件"
        />
        <span>全选</span>
      </label>
      <span className="tf-caption tf-text-secondary">已选 {selectedCount} 项</span>
      <div className="tf-flex-spacer" />
      <Button size="small" variant="danger" icon={<Trash2 size={14} />} disabled={selectedCount === 0} onClick={onDelete}>
        删除 {selectedCount} 项
      </Button>
      <Button size="small" variant="ghost" icon={<X size={14} />} onClick={onCancel}>
        取消
      </Button>
    </div>
  );
}
