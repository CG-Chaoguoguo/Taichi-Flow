import type { MouseEvent } from "react";
import { Eye, EyeOff, FileText } from "lucide-react";
import { INPUT_FAMILY_LABELS } from "../constants/inputFamilies";
import { isVisualizableInput } from "../constants/visualizableInputs";
import type { InputFile } from "../types";
import { FAMILY_ICONS, fileStatusBadge } from "./AssetListView";
import { IconButton } from "./IconButton";
import { RuntimeLockBadge } from "./RuntimeLockBadge";

export type AssetGridViewProps = {
  files: InputFile[];
  emptyMessage: string;
  selectedFileId: string | null;
  layerVisibility: Record<string, boolean>;
  selectionMode?: boolean;
  selectedAssetIds?: Set<string>;
  onSelect: (file: InputFile) => void;
  onSelectionClick?: (file: InputFile, index: number, event: MouseEvent) => void;
  onToggleVisibility: (fileId: string) => void;
};

export function AssetGridView({
  files,
  emptyMessage,
  selectedFileId,
  layerVisibility,
  selectionMode = false,
  selectedAssetIds,
  onSelect,
  onSelectionClick,
  onToggleVisibility,
}: AssetGridViewProps) {
  if (files.length === 0) {
    return <div className="tf-empty tf-body tf-text-tertiary">{emptyMessage}</div>;
  }

  return (
    <div className="tf-asset-grid" role="list" aria-label="项目输入资产网格">
      {files.map((file, index) => {
        const visualizable = isVisualizableInput(file);
        const visible = layerVisibility[file.file_id] ?? true;
        const focusSelected = !selectionMode && selectedFileId === file.file_id;
        const deleteSelected = selectionMode && Boolean(selectedAssetIds?.has(file.file_id));
        const runtimeLocked = Boolean(file.runtime_lock?.locked);
        const selectable = file.deletable !== false && !runtimeLocked;
        return (
          <div
            key={file.file_id}
            role="listitem"
            className={`tf-asset-grid-card${focusSelected ? " is-selected" : ""}${deleteSelected ? " is-delete-selected" : ""}${runtimeLocked ? " is-runtime-locked" : ""}${selectionMode && !selectable ? " is-selection-disabled" : ""}`}
            aria-selected={selectionMode ? deleteSelected : focusSelected}
            aria-label={runtimeLocked ? `${file.name}，计算引用中` : file.name}
            title={runtimeLocked ? `计算引用中：${file.runtime_lock?.statuses.join(" / ") || "starting"}` : file.name}
          >
            <button
              type="button"
              className="tf-asset-grid-card-main"
              aria-pressed={selectionMode ? deleteSelected : focusSelected}
              disabled={selectionMode && !selectable}
              onClick={(event) => {
                if (selectionMode) {
                  if (!selectable) return;
                  onSelectionClick?.(file, index, event);
                  return;
                }
                onSelect(file);
              }}
            >
              <div className="tf-asset-grid-thumb" aria-hidden="true">
                {FAMILY_ICONS[file.family] || <FileText size={28} />}
              </div>
              <div className="tf-asset-grid-meta">
                <div className="tf-caption tf-font-medium tf-ellipsis">{file.name}</div>
                <div className="tf-caption tf-text-tertiary tf-ellipsis">
                  {INPUT_FAMILY_LABELS[file.family] || file.family}
                </div>
                <div className="tf-asset-grid-status">
                  <RuntimeLockBadge runtimeLock={file.runtime_lock} />
                  {fileStatusBadge(file.status)}
                </div>
              </div>
            </button>
            {visualizable ? (
              <div className="tf-asset-grid-actions">
                <IconButton
                  size="small"
                  icon={visible ? <Eye size={12} /> : <EyeOff size={12} />}
                  label={visible ? "在画布中隐藏" : "在画布中显示"}
                  active={visible}
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggleVisibility(file.file_id);
                  }}
                />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
