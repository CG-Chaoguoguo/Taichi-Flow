import type { MouseEvent } from "react";
import { AlertCircle, Eye, EyeOff, FileText, GripVertical, Layers, Map as MapIcon, Monitor, Waves } from "lucide-react";
import { INPUT_FAMILY_LABELS } from "../constants/inputFamilies";
import { isVisualizableInput } from "../constants/visualizableInputs";
import type { InputFile } from "../types";
import { IconButton } from "./IconButton";
import { RuntimeLockBadge } from "./RuntimeLockBadge";
import { StatusBadge } from "./StatusBadge";

export const FAMILY_ICONS: Record<string, React.ReactNode> = {
  dem: <MapIcon size={16} />,
  slope: <MapIcon size={16} />,
  zones: <Layers size={16} />,
  boundary: <MapIcon size={16} />,
  rainfall: <Waves size={16} />,
  inflow: <Waves size={16} />,
  outflow: <Waves size={16} />,
  monitoring: <Monitor size={16} />,
  config: <FileText size={16} />,
};

export function fileStatusBadge(status: InputFile["status"]) {
  switch (status) {
    case "ready":
      return <StatusBadge variant="success">就绪</StatusBadge>;
    case "warning":
      return <StatusBadge variant="warning">警告</StatusBadge>;
    case "invalid":
      return <StatusBadge variant="error">错误</StatusBadge>;
    case "unsupported":
      return <StatusBadge variant="neutral">不支持</StatusBadge>;
    case "parsing":
    case "visualizing":
      return <StatusBadge variant="info">处理中</StatusBadge>;
    case "metadata_only":
      return <StatusBadge variant="neutral">仅元数据</StatusBadge>;
    default:
      return <StatusBadge variant="neutral">未知</StatusBadge>;
  }
}

export type AssetListViewProps = {
  files: InputFile[];
  emptyMessage: string;
  selectedFileId: string | null;
  selectionMode: boolean;
  selectedAssetIds: Set<string>;
  layerVisibility: Record<string, boolean>;
  readOnly?: boolean;
  reorderable?: boolean;
  dragId: string | null;
  dropId: string | null;
  compact?: boolean;
  onSelect: (file: InputFile) => void;
  onToggleSelected: (fileId: string) => void;
  onSelectionClick?: (file: InputFile, index: number, event: MouseEvent) => void;
  onToggleVisibility: (fileId: string) => void;
  onReorder: (fromId: string, toId: string) => void;
  onDragStart: (fileId: string) => void;
  onDragOver: (fileId: string) => void;
  onDragLeave: (fileId: string) => void;
  onDragEnd: () => void;
};

export function AssetListView({
  files,
  emptyMessage,
  selectedFileId,
  selectionMode,
  selectedAssetIds,
  layerVisibility,
  readOnly = false,
  reorderable = true,
  dragId,
  dropId,
  compact = false,
  onSelect,
  onToggleSelected,
  onSelectionClick,
  onToggleVisibility,
  onReorder,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDragEnd,
}: AssetListViewProps) {
  const canReorder = reorderable && !readOnly && !selectionMode;
  if (files.length === 0) {
    return <div className="tf-empty tf-body tf-text-tertiary">{emptyMessage}</div>;
  }

  return (
    <div className="tf-stack-sm" role="list" aria-label="项目输入资产">
      {files.map((file, index) => {
        const visualizable = isVisualizableInput(file);
        const visible = layerVisibility[file.file_id] ?? true;
        const focusSelected = !selectionMode && selectedFileId === file.file_id;
        const runtimeLocked = Boolean(file.runtime_lock?.locked);
        const selectable = file.deletable !== false && !runtimeLocked;
        const checked = selectedAssetIds.has(file.file_id);
        return (
          <div
            key={file.file_id}
            role="listitem"
            tabIndex={0}
            draggable={canReorder}
            aria-selected={selectionMode ? checked : focusSelected}
            aria-label={runtimeLocked ? `${file.name}，计算引用中` : file.name}
            title={runtimeLocked ? `计算引用中：${file.runtime_lock?.statuses.join(" / ") || "starting"}` : undefined}
            onDragStart={(event) => {
              if (!canReorder) return;
              onDragStart(file.file_id);
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData("text/plain", file.file_id);
            }}
            onDragOver={(event) => {
              if (!canReorder) return;
              event.preventDefault();
              if (dragId && dragId !== file.file_id) onDragOver(file.file_id);
            }}
            onDragLeave={() => {
              if (dropId === file.file_id) onDragLeave(file.file_id);
            }}
            onDrop={(event) => {
              if (!canReorder) return;
              event.preventDefault();
              const fromId = event.dataTransfer.getData("text/plain") || dragId;
              if (fromId) onReorder(fromId, file.file_id);
              onDragEnd();
            }}
            onDragEnd={onDragEnd}
            onClick={(event) => {
              if (selectionMode) {
                if (!selectable) return;
                onSelectionClick?.(file, index, event);
                return;
              }
              onSelect(file);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (selectionMode) {
                  if (!selectable) return;
                  onSelectionClick?.(file, index, {
                    shiftKey: event.shiftKey,
                    ctrlKey: event.ctrlKey,
                    metaKey: event.metaKey,
                    preventDefault: () => undefined,
                    stopPropagation: () => undefined,
                  } as MouseEvent);
                  return;
                }
                onSelect(file);
              }
              if (selectionMode && event.key === " " && selectable) {
                event.preventDefault();
                if (onSelectionClick) {
                  onSelectionClick(file, index, {
                    shiftKey: event.shiftKey,
                    ctrlKey: event.ctrlKey,
                    metaKey: event.metaKey,
                    preventDefault: () => undefined,
                    stopPropagation: () => undefined,
                  } as MouseEvent);
                  return;
                }
                onToggleSelected(file.file_id);
              }
            }}
            className={`tf-list-item${focusSelected ? " selected" : ""}${checked && selectionMode ? " is-delete-selected" : ""}${dragId === file.file_id ? " is-dragging" : ""}${dropId === file.file_id ? " is-drop-target" : ""}${runtimeLocked ? " is-runtime-locked" : ""}${selectionMode && !selectable ? " is-selection-disabled" : ""}`}
          >
            {selectionMode ? (
              <input
                type="checkbox"
                className="tf-asset-selection-checkbox"
                aria-label={`选择 ${file.name}`}
                checked={checked}
                disabled={!selectable}
                onClick={(event) => {
                  // Prevent the row handler from also toggling this item.
                  event.stopPropagation();
                }}
                onChange={(event) => {
                  if (!selectable) return;
                  if (onSelectionClick) {
                    onSelectionClick(file, index, {
                      shiftKey: false,
                      ctrlKey: false,
                      metaKey: false,
                      preventDefault: () => undefined,
                      stopPropagation: () => undefined,
                    } as MouseEvent);
                    return;
                  }
                  onToggleSelected(file.file_id);
                  void event;
                }}
              />
            ) : canReorder ? (
              <span className="tf-drag-handle" aria-hidden="true" title="拖拽排序">
                <GripVertical size={14} />
              </span>
            ) : null}
            <span className="tf-icon-inline">{FAMILY_ICONS[file.family] || <FileText size={16} />}</span>
            <div className="tf-flex-1">
              <div className="tf-body tf-ellipsis tf-font-medium">{file.name}</div>
              <div className="tf-caption tf-text-tertiary">
                {INPUT_FAMILY_LABELS[file.family] || file.family} · {(file.size / 1024).toFixed(1)} KB
              </div>
              {!compact ? (
                <div className="tf-caption tf-text-tertiary tf-mono">
                  {file.roles?.join(" · ") || "未声明角色"} · {file.sha256?.slice(0, 10) || "无哈希"}
                </div>
              ) : null}
              {file.warnings && file.warnings.length > 0 ? (
                <div className="tf-caption tf-warning-row">
                  <AlertCircle size={12} />
                  {file.warnings[0]}
                </div>
              ) : null}
            </div>
            <div className="tf-list-item-actions">
              <RuntimeLockBadge runtimeLock={file.runtime_lock} />
              {visualizable ? (
                <>
                  {file.status !== "ready" ? fileStatusBadge(file.status) : null}
                  <IconButton
                    size="small"
                    icon={visible ? <Eye size={14} /> : <EyeOff size={14} />}
                    label={visible ? "在画布中隐藏" : "在画布中显示"}
                    active={visible}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleVisibility(file.file_id);
                    }}
                  />
                </>
              ) : (
                fileStatusBadge(file.status)
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
