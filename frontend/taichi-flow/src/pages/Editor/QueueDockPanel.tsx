import { useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent } from "react";
import { ListPlus, RotateCcw, Square, Trash2 } from "lucide-react";
import { AssetSelectionToolbar } from "../../components/AssetSelectionToolbar";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";
import { QueueDeleteDialog } from "../../components/QueueDeleteDialog";
import { StatusBadge } from "../../components/StatusBadge";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { QueueDeletePreview, QueueItem } from "../../types";

const TERMINAL_STATUSES = ["completed", "failed", "interrupted", "canceled", "cancelled", "stopped"] as const;
const ACTIVE_STATUSES = ["starting", "running", "stopping"] as const;

const isActive = (item: QueueItem) => (ACTIVE_STATUSES as readonly string[]).includes(item.status);
const isSelectable = (item: QueueItem) => !isActive(item) && item.deletable !== false;
const orderValue = (item: QueueItem) => item.queue_order ?? item.position;

export function QueueDockPanel() {
  const queue = useTaichiFlowStore((state) => state.queue);
  const startQueueBatch = useTaichiFlowStore((state) => state.startQueueBatch);
  const previewQueueDeletion = useTaichiFlowStore((state) => state.previewQueueDeletion);
  const deleteQueueItems = useTaichiFlowStore((state) => state.deleteQueueItems);
  const stopRunningItem = useTaichiFlowStore((state) => state.stopRunningItem);
  const reorderQueue = useTaichiFlowStore((state) => state.reorderQueue);
  const retryQueueItem = useTaichiFlowStore((state) => state.retryQueueItem);
  const setEditorSelection = useTaichiFlowStore((state) => state.setEditorSelection);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [deletePreview, setDeletePreview] = useState<QueueDeletePreview | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropId, setDropId] = useState<string | null>(null);
  const selectionAnchorRef = useRef<number | null>(null);

  const running = queue.filter((item) => isActive(item));
  const waiting = queue
    .filter((item) => item.status === "waiting" || item.status === "queued")
    .sort((a, b) => orderValue(a) - orderValue(b) || a.enqueued_at.localeCompare(b.enqueued_at));
  const terminal = queue.filter((item) => (TERMINAL_STATUSES as readonly string[]).includes(item.status)).slice(-5);
  const renderedItems = useMemo(() => [...running, ...waiting, ...terminal], [running, waiting, terminal]);
  const selectableItems = renderedItems.filter(isSelectable);
  const selectedCount = [...selectedIds].filter((id) => selectableItems.some((item) => item.queue_item_id === id)).length;
  const allSelected = selectableItems.length > 0 && selectedCount === selectableItems.length;
  const partiallySelected = selectedCount > 0 && !allSelected;
  const waitingCount = waiting.filter((item) => item.status === "waiting").length;
  const queueOrderLocked = queue.some((item) => ["queued", "starting", "running", "stopping"].includes(item.status));
  const hasQueue = renderedItems.length > 0;

  useEffect(() => {
    const visible = new Set(selectableItems.map((item) => item.queue_item_id));
    setSelectedIds((current) => new Set([...current].filter((id) => visible.has(id))));
  }, [queue]);

  useEffect(() => {
    if (!selectionMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setSelectionMode(false);
        setSelectedIds(new Set());
        selectionAnchorRef.current = null;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectionMode]);

  const exitSelection = () => {
    setSelectionMode(false);
    setSelectedIds(new Set());
    selectionAnchorRef.current = null;
  };

  const toggleSelected = (item: QueueItem, index: number, event?: MouseEvent) => {
    if (!isSelectable(item)) return;
    const additive = Boolean(event?.ctrlKey || event?.metaKey);
    if (event?.shiftKey) {
      const anchor = selectionAnchorRef.current ?? index;
      const from = Math.min(anchor, index);
      const to = Math.max(anchor, index);
      const range = renderedItems.slice(from, to + 1).filter(isSelectable).map((candidate) => candidate.queue_item_id);
      setSelectedIds((current) => {
        if (additive) return new Set([...current, ...range]);
        return new Set(range);
      });
      return;
    }
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(item.queue_item_id)) next.delete(item.queue_item_id);
      else next.add(item.queue_item_id);
      return next;
    });
    selectionAnchorRef.current = index;
  };

  const reviewDelete = async () => {
    const ids = [...selectedIds].filter((id) => selectableItems.some((item) => item.queue_item_id === id));
    if (!ids.length) return;
    const preview = await previewQueueDeletion(ids);
    if (preview) setDeletePreview(preview);
  };

  const confirmDelete = async () => {
    if (!deletePreview) return;
    setDeleting(true);
    try {
      const result = await deleteQueueItems(deletePreview.queue_item_ids);
      if (result) {
        setDeletePreview(null);
        exitSelection();
      }
    } finally {
      setDeleting(false);
    }
  };

  const handleDrop = (target: QueueItem) => {
    if (!dragId || target.status !== "waiting" || dragId === target.queue_item_id) return;
    const newPosition = waiting.findIndex((item) => item.queue_item_id === target.queue_item_id) + 1;
    if (newPosition > 0) void reorderQueue(dragId, newPosition);
    setDragId(null);
    setDropId(null);
  };

  if (!hasQueue) {
    return <div className="tf-dock-empty tf-caption tf-text-tertiary">队列为空。在右侧运行页加入方案后，点击“运行队列”启动当前批次。</div>;
  }

  return (
    <div className="tf-dock-panel">
      {!selectionMode ? (
        <div className="tf-queue-toolbar" role="toolbar" aria-label="队列控制">
          <Button
            size="small"
            variant="primary"
            icon={<ListPlus size={14} />}
            onClick={() => void startQueueBatch()}
            disabled={waitingCount === 0}
          >
            运行队列（{waitingCount}）
          </Button>
          <Button
            size="small"
            variant="ghost"
            icon={<Trash2 size={14} />}
            onClick={() => setSelectionMode(true)}
            disabled={selectableItems.length === 0}
          >
            删除
          </Button>
          <span className="tf-flex-spacer" />
          {waiting.some((item) => item.status === "queued") ? <span className="tf-caption tf-text-secondary">当前批次已锁定排序</span> : null}
        </div>
      ) : (
        <AssetSelectionToolbar
          selectedCount={selectedCount}
          selectableCount={selectableItems.length}
          allSelected={allSelected}
          partiallySelected={partiallySelected}
          onToggleAll={() => setSelectedIds(allSelected ? new Set() : new Set(selectableItems.map((item) => item.queue_item_id)))}
          onDelete={() => void reviewDelete()}
          onCancel={exitSelection}
          ariaLabel="队列批量选择"
          selectAllLabel="全选可移除的队列项"
        />
      )}

      {running.map((item, index) => (
        <QueueRow
          key={item.queue_item_id}
          item={item}
          displayIndex={index + 1}
          selectionMode={selectionMode}
          selected={selectedIds.has(item.queue_item_id)}
          onSelectionClick={(event) => toggleSelected(item, index, event)}
          onStop={() => void stopRunningItem(item.queue_item_id)}
          onSelect={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })}
        />
      ))}
      {waiting.map((item, index) => (
        <QueueRow
          key={item.queue_item_id}
          item={item}
          displayIndex={running.length + index + 1}
          selectionMode={selectionMode}
          selected={selectedIds.has(item.queue_item_id)}
          canDrag={!selectionMode && !queueOrderLocked && item.status === "waiting"}
          isDragging={dragId === item.queue_item_id}
          isDropTarget={dropId === item.queue_item_id}
          onDragStart={(event) => {
            setDragId(item.queue_item_id);
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", item.queue_item_id);
          }}
          onDragOver={(event) => {
            if (item.status !== "waiting" || !dragId) return;
            event.preventDefault();
            setDropId(item.queue_item_id);
          }}
          onDrop={() => handleDrop(item)}
          onDragEnd={() => {
            setDragId(null);
            setDropId(null);
          }}
          onSelectionClick={(event) => toggleSelected(item, running.length + index, event)}
          onSelect={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })}
        />
      ))}
      {terminal.map((item, index) => (
        <QueueRow
          key={item.queue_item_id}
          item={item}
          displayIndex={running.length + waiting.length + index + 1}
          selectionMode={selectionMode}
          selected={selectedIds.has(item.queue_item_id)}
          onSelectionClick={(event) => toggleSelected(item, running.length + waiting.length + index, event)}
          onRetry={() => void retryQueueItem(item.queue_item_id)}
          onSelect={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })}
        />
      ))}

      <QueueDeleteDialog
        open={deletePreview !== null}
        preview={deletePreview}
        busy={deleting}
        onClose={() => !deleting && setDeletePreview(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function QueueRow({
  item,
  displayIndex,
  selectionMode,
  selected,
  canDrag = false,
  isDragging = false,
  isDropTarget = false,
  onSelectionClick,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onStop,
  onRetry,
  onSelect,
}: {
  item: QueueItem;
  displayIndex: number;
  selectionMode: boolean;
  selected: boolean;
  canDrag?: boolean;
  isDragging?: boolean;
  isDropTarget?: boolean;
  onSelectionClick?: (event: MouseEvent) => void;
  onDragStart?: (event: DragEvent<HTMLDivElement>) => void;
  onDragOver?: (event: DragEvent<HTMLDivElement>) => void;
  onDrop?: () => void;
  onDragEnd?: () => void;
  onStop?: () => void;
  onRetry?: () => void;
  onSelect?: () => void;
}) {
  const selectable = isSelectable(item);
  return (
    <div
      className={`tf-dock-queue-row${canDrag ? " is-draggable" : ""}${isDragging ? " is-dragging" : ""}${isDropTarget ? " is-drop-target" : ""}${!selectable ? " is-locked" : ""}`}
      draggable={canDrag}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={(event) => {
        event.preventDefault();
        onDrop?.();
      }}
      onDragEnd={onDragEnd}
      onClick={selectionMode && selectable ? onSelectionClick : undefined}
    >
      {selectionMode && selectable ? (
        <input
          type="checkbox"
          className="tf-dock-queue-checkbox"
          checked={selected}
          onChange={(event) => onSelectionClick?.(event.nativeEvent as unknown as MouseEvent)}
          onClick={(event) => event.stopPropagation()}
          aria-label={`选择 ${item.scenario_name}`}
        />
      ) : null}
      <button
        type="button"
        className="tf-dock-queue-main"
        onClick={(event) => {
          event.stopPropagation();
          if (selectionMode && selectable) onSelectionClick?.(event);
          else onSelect?.();
        }}
      >
        <span className="tf-caption tf-text-tertiary" aria-label={`队列序号 ${displayIndex}`}>{displayIndex}</span>
        <StatusBadge variant={item.status} dot />
        <span className="tf-body tf-ellipsis">{item.scenario_name}</span>
        {item.status === "running" ? (
          <div className="tf-progress tf-dock-queue-progress">
            <div className="tf-progress-fill" style={{ width: `${item.progress}%` }} />
          </div>
        ) : null}
      </button>
      {!selectionMode ? (
        <div className="tf-icon-actions">
          {item.status === "starting" || item.status === "running" ? (
            <IconButton size="small" icon={<Square size={14} />} label="停止" className="tf-text-error" onClick={onStop} />
          ) : null}
          {["failed", "interrupted", "canceled", "cancelled", "stopped"].includes(item.status) ? (
            <IconButton size="small" icon={<RotateCcw size={14} />} label="重新加入队列" className="tf-text-brand" onClick={onRetry} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
