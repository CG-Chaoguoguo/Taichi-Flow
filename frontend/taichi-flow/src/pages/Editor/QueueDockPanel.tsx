import { ArrowDown, ArrowUp, RotateCcw, Square, X } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { IconButton } from "../../components/IconButton";
import { StatusBadge } from "../../components/StatusBadge";
import type { QueueItem } from "../../types";

export function QueueDockPanel() {
  const queue = useTaichiFlowStore((state) => state.queue);
  const cancelQueueItem = useTaichiFlowStore((state) => state.cancelQueueItem);
  const stopRunningItem = useTaichiFlowStore((state) => state.stopRunningItem);
  const reorderQueue = useTaichiFlowStore((state) => state.reorderQueue);
  const retryQueueItem = useTaichiFlowStore((state) => state.retryQueueItem);
  const setEditorSelection = useTaichiFlowStore((state) => state.setEditorSelection);

  const running = queue.filter((item) => item.status === "running");
  const waiting = queue.filter((item) => item.status === "waiting" || item.status === "queued").sort((a, b) => a.position - b.position);
  const completed = queue.filter((item) =>
    ["completed", "failed", "interrupted", "canceled", "cancelled", "stopped"].includes(item.status),
  );

  if (queue.length === 0) {
    return <div className="tf-dock-empty tf-caption tf-text-tertiary">队列为空。在属性面板入队方案后，任务会出现在这里。</div>;
  }

  return (
    <div className="tf-dock-panel">
      {running.map((item) => (
        <QueueRow key={item.queue_item_id} item={item} onStop={() => void stopRunningItem(item.queue_item_id)} onSelect={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })} />
      ))}
      {waiting.map((item) => (
        <QueueRow
          key={item.queue_item_id}
          item={item}
          onMoveUp={() => void reorderQueue(item.queue_item_id, item.position - 1)}
          onMoveDown={() => void reorderQueue(item.queue_item_id, item.position + 1)}
          onCancel={() => void cancelQueueItem(item.queue_item_id)}
          onSelect={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })}
        />
      ))}
      {completed.slice(-5).map((item) => (
        <QueueRow
          key={item.queue_item_id}
          item={item}
          onRetry={() => void retryQueueItem(item.queue_item_id)}
          onSelect={() => setEditorSelection({ kind: "queue", queueItemId: item.queue_item_id })}
        />
      ))}
    </div>
  );
}

function QueueRow({
  item,
  onMoveUp,
  onMoveDown,
  onCancel,
  onStop,
  onRetry,
  onSelect,
}: {
  item: QueueItem;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onCancel?: () => void;
  onStop?: () => void;
  onRetry?: () => void;
  onSelect?: () => void;
}) {
  return (
    <div className="tf-dock-queue-row">
      <button type="button" className="tf-dock-queue-main" onClick={onSelect}>
        <span className="tf-caption tf-text-tertiary">#{item.position}</span>
        <StatusBadge variant={item.status} dot />
        <span className="tf-body tf-ellipsis">{item.scenario_name}</span>
        {item.status === "running" ? (
          <div className="tf-progress tf-dock-queue-progress">
            <div className="tf-progress-fill" style={{ width: `${item.progress}%` }} />
          </div>
        ) : null}
      </button>
      <div className="tf-icon-actions">
        {(item.status === "waiting" || item.status === "queued") && (
          <>
            <IconButton size="small" icon={<ArrowUp size={14} />} label="上移" onClick={onMoveUp} />
            <IconButton size="small" icon={<ArrowDown size={14} />} label="下移" onClick={onMoveDown} />
            <IconButton size="small" icon={<X size={14} />} label="取消" className="tf-text-error" onClick={onCancel} />
          </>
        )}
        {item.status === "running" && (
          <IconButton size="small" icon={<Square size={14} />} label="停止" className="tf-text-error" onClick={onStop} />
        )}
        {(item.status === "failed" || item.status === "interrupted" || item.status === "canceled" || item.status === "cancelled") && (
          <IconButton size="small" icon={<RotateCcw size={14} />} label="重新排队" className="tf-text-brand" onClick={onRetry} />
        )}
      </div>
    </div>
  );
}
