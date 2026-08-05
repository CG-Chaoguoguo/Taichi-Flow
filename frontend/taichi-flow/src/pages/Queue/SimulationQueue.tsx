import { useEffect } from "react";
import { ArrowDown, ArrowUp, RotateCcw, Square, X } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { IconButton } from "../../components/IconButton";
import { StatusBadge } from "../../components/StatusBadge";
import type { QueueItem } from "../../types";

export function SimulationQueue() {
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const queue = useTaichiFlowStore((state) => state.queue);
  const fetchQueue = useTaichiFlowStore((state) => state.fetchQueue);
  const cancelQueueItem = useTaichiFlowStore((state) => state.cancelQueueItem);
  const stopRunningItem = useTaichiFlowStore((state) => state.stopRunningItem);
  const reorderQueue = useTaichiFlowStore((state) => state.reorderQueue);
  const retryQueueItem = useTaichiFlowStore((state) => state.retryQueueItem);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  if (!activeProject) {
    return <div className="tf-empty-state tf-body">请先选择项目。</div>;
  }

  const running = queue.filter((q) => q.status === "running");
  const waiting = queue.filter((q) => q.status === "waiting").sort((a, b) => a.position - b.position);
  const completed = queue.filter((q) => q.status === "completed" || q.status === "failed" || q.status === "interrupted" || q.status === "canceled");

  return (
    <div className="tf-page">
      <div className="tf-page-content tf-animate-in">
        <div className="tf-page-header">
          <div>
            <h1 className="tf-display tf-mb-2">模拟队列</h1>
            <p className="tf-body tf-text-secondary">
              并发数固定为 1，方案按顺序串行执行。等待中的任务可调整顺序。
            </p>
          </div>
          <div className="tf-chip">并发数：1</div>
        </div>

        <section className="tf-section">
          <h2 className="tf-subtitle tf-mb-2">当前运行</h2>
          {running.length === 0 ? (
            <div className="tf-empty-state tf-body">没有运行中的任务</div>
          ) : (
            running.map((item) => <QueueItemCard key={item.queue_item_id} item={item} onStop={() => stopRunningItem(item.queue_item_id)} />)
          )}
        </section>

        <section className="tf-section">
          <h2 className="tf-subtitle tf-mb-2">等待队列</h2>
          {waiting.length === 0 ? (
            <div className="tf-empty-state tf-body">队列中没有等待任务</div>
          ) : (
            waiting.map((item) => (
              <QueueItemCard
                key={item.queue_item_id}
                item={item}
                onMoveUp={() => reorderQueue(item.queue_item_id, item.position - 1)}
                onMoveDown={() => reorderQueue(item.queue_item_id, item.position + 1)}
                onCancel={() => cancelQueueItem(item.queue_item_id)}
              />
            ))
          )}
        </section>

        <section>
          <h2 className="tf-subtitle tf-mb-2">最近完成/失败</h2>
          {completed.length === 0 ? (
            <div className="tf-empty-state tf-body">暂无完成或失败记录</div>
          ) : (
            completed.slice(-5).map((item) => <QueueItemCard key={item.queue_item_id} item={item} onRetry={() => retryQueueItem(item.queue_item_id)} />)
          )}
        </section>
      </div>
    </div>
  );
}

function QueueItemCard({
  item,
  onMoveUp,
  onMoveDown,
  onCancel,
  onStop,
  onRetry,
}: {
  item: QueueItem;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onCancel?: () => void;
  onStop?: () => void;
  onRetry?: () => void;
}) {
  return (
    <div className="tf-card tf-row tf-mb-2">
      <div className="tf-queue-position">
        <span className="tf-caption tf-text-tertiary">#{item.position}</span>
        <StatusBadge variant={item.status} dot />
      </div>
      <div className="tf-flex-1">
        <div className="tf-body tf-font-semibold tf-mb-2">{item.scenario_name}</div>
        <div className="tf-caption tf-text-tertiary">
          {item.simulation_id ? `simulation_id: ${item.simulation_id}` : "等待调度"} · 加入时间 {new Date(item.enqueued_at).toLocaleString("zh-CN")}
        </div>
        {item.status === "running" && (
          <div className="tf-progress tf-mt-2">
            <div className="tf-progress-fill" style={{ width: `${item.progress}%` }} />
          </div>
        )}
      </div>
      <div className="tf-icon-actions">
        {item.status === "waiting" && (
          <>
            <IconButton size="small" icon={<ArrowUp size={16} />} label="上移" onClick={onMoveUp} />
            <IconButton size="small" icon={<ArrowDown size={16} />} label="下移" onClick={onMoveDown} />
            <IconButton size="small" icon={<X size={16} />} label="取消" className="tf-text-error" onClick={onCancel} />
          </>
        )}
        {item.status === "running" && (
          <IconButton size="small" icon={<Square size={16} />} label="停止" className="tf-text-error" onClick={onStop} />
        )}
        {(item.status === "failed" || item.status === "interrupted" || item.status === "canceled") && (
          <IconButton size="small" icon={<RotateCcw size={16} />} label="重新排队" className="tf-text-brand" onClick={onRetry} />
        )}
      </div>
    </div>
  );
}
