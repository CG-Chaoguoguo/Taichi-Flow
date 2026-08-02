import { useEffect } from "react";
import { ArrowDown, ArrowUp, RotateCcw, Square, X } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
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
    return (
      <div style={{ padding: 48 }}>
        <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          请先选择项目。
        </p>
      </div>
    );
  }

  const running = queue.filter((q) => q.status === "running");
  const waiting = queue.filter((q) => q.status === "waiting").sort((a, b) => a.position - b.position);
  const completed = queue.filter((q) => q.status === "completed" || q.status === "failed" || q.status === "interrupted" || q.status === "canceled");

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "32px" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 className="tf-display" style={{ marginBottom: 4 }}>
              模拟队列
            </h1>
            <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
              并发数固定为 1，方案按顺序串行执行。等待中的任务可调整顺序。
            </p>
          </div>
          <div className="tf-caption" style={{ padding: "6px 12px", borderRadius: "var(--radius-large)", background: "var(--color-surface-tertiary)" }}>
            并发数：1
          </div>
        </div>

        {/* 当前运行 */}
        <section style={{ marginBottom: 24 }}>
          <h2 className="tf-subtitle" style={{ marginBottom: 12 }}>
            当前运行
          </h2>
          {running.length === 0 ? (
            <div
              style={{
                padding: 24,
                borderRadius: "var(--radius-xlarge)",
                border: "1px dashed var(--color-border-strong)",
                background: "var(--color-surface)",
                color: "var(--color-foreground-secondary)",
                textAlign: "center",
              }}
            >
              没有运行中的任务
            </div>
          ) : (
            running.map((item) => <QueueItemCard key={item.queue_item_id} item={item} onStop={() => stopRunningItem(item.queue_item_id)} />)
          )}
        </section>

        {/* 等待队列 */}
        <section style={{ marginBottom: 24 }}>
          <h2 className="tf-subtitle" style={{ marginBottom: 12 }}>
            等待队列
          </h2>
          {waiting.length === 0 ? (
            <div
              style={{
                padding: 24,
                borderRadius: "var(--radius-xlarge)",
                border: "1px dashed var(--color-border-strong)",
                background: "var(--color-surface)",
                color: "var(--color-foreground-secondary)",
                textAlign: "center",
              }}
            >
              队列中没有等待任务
            </div>
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

        {/* 最近完成 */}
        <section>
          <h2 className="tf-subtitle" style={{ marginBottom: 12 }}>
            最近完成/失败
          </h2>
          {completed.length === 0 ? (
            <div
              style={{
                padding: 24,
                borderRadius: "var(--radius-xlarge)",
                border: "1px dashed var(--color-border-strong)",
                background: "var(--color-surface)",
                color: "var(--color-foreground-secondary)",
                textAlign: "center",
              }}
            >
              暂无完成或失败记录
            </div>
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
    <div
      style={{
        padding: 16,
        borderRadius: "var(--radius-large)",
        border: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        boxShadow: "var(--shadow-rest)",
        marginBottom: 12,
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 40 }}>
        <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
          #{item.position}
        </span>
        <StatusBadge variant={item.status} dot />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="tf-body" style={{ fontWeight: 600, marginBottom: 4 }}>
          {item.scenario_name}
        </div>
        <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
          {item.simulation_id ? `simulation_id: ${item.simulation_id}` : "等待调度"} · 加入时间 {new Date(item.enqueued_at).toLocaleString("zh-CN")}
        </div>
        {item.status === "running" && (
          <div
            style={{
              height: 6,
              borderRadius: 3,
              background: "var(--color-surface-tertiary)",
              overflow: "hidden",
              marginTop: 8,
            }}
          >
            <div
              style={{
                width: `${item.progress}%`,
                height: "100%",
                background: "var(--color-brand)",
                transition: "width 500ms ease",
              }}
            />
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        {item.status === "waiting" && (
          <>
            <button style={{ color: "var(--color-foreground-secondary)" }} onClick={onMoveUp} title="上移" aria-label="上移">
              <ArrowUp size={16} />
            </button>
            <button style={{ color: "var(--color-foreground-secondary)" }} onClick={onMoveDown} title="下移" aria-label="下移">
              <ArrowDown size={16} />
            </button>
            <button style={{ color: "var(--color-error)" }} onClick={onCancel} title="取消" aria-label="取消">
              <X size={16} />
            </button>
          </>
        )}
        {item.status === "running" && (
          <button style={{ color: "var(--color-error)" }} onClick={onStop} title="停止" aria-label="停止">
            <Square size={16} />
          </button>
        )}
        {(item.status === "failed" || item.status === "interrupted" || item.status === "canceled") && (
          <button style={{ color: "var(--color-brand)" }} onClick={onRetry} title="重新排队" aria-label="重新排队">
            <RotateCcw size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
