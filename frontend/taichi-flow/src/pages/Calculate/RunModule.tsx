import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Cpu, List, Monitor, Play, RefreshCw, Square, Terminal, Timer } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import type { Scenario } from "../../types";
import { runApi } from "../../api/taichiFlowAdapter";

export function RunModule({ scenario }: { scenario: Scenario }) {
  const queue = useTaichiFlowStore((state) => state.queue);
  const metrics = useTaichiFlowStore((state) => state.metrics);
  const enqueueScenario = useTaichiFlowStore((state) => state.enqueueScenario);
  const cancelQueueItem = useTaichiFlowStore((state) => state.cancelQueueItem);
  const stopRunningItem = useTaichiFlowStore((state) => state.stopRunningItem);
  const retryQueueItem = useTaichiFlowStore((state) => state.retryQueueItem);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);

  const item = queue.find((q) => q.scenario_id === scenario.scenario_id);
  const [logs, setLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState(false);

  useEffect(() => {
    if (scenario.latest_simulation_id && activeProject && ["starting", "running", "stopping", "completed", "failed", "stopped", "interrupted"].includes(scenario.status)) {
      const interval = setInterval(() => {
        void runApi.terminal(activeProject.project_id, scenario.latest_simulation_id as string)
          .then((response) => setLogs(response.entries.slice(-200)))
          .catch(() => undefined);
      }, 1000);
      void runApi.terminal(activeProject.project_id, scenario.latest_simulation_id).then((response) => setLogs(response.entries.slice(-200))).catch(() => undefined);
      return () => clearInterval(interval);
    }
  }, [activeProject, scenario.latest_simulation_id, scenario.status]);

  const handleEnqueue = async () => {
    await enqueueScenario(scenario.scenario_id);
  };

  const elapsed = item?.started_at ? Math.floor((Date.now() - new Date(item.started_at).getTime()) / 1000) : 0;
  const elapsedText = `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16, overflow: "auto" }}>
      {/* 状态摘要 */}
      <div
        style={{
          padding: 16,
          borderRadius: "var(--radius-large)",
          background: "var(--color-surface-tertiary)",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span className="tf-body" style={{ fontWeight: 600 }}>
            {scenario.name}
          </span>
          <StatusBadge variant={scenario.status} dot />
        </div>
        <div className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
          输入修订 {scenario.input_revision_id} · {Object.keys(scenario.parameter_patch || {}).length} 项参数变更
        </div>
      </div>

      {/* 预检 */}
      {scenario.status === "draft" || scenario.status === "ready" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <h4 className="tf-subtitle">运行预检</h4>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <CheckItem ok={inputFiles.some((file) => file.family === "dem" && file.status === "ready")} text="DEM 输入已就绪" />
            <CheckItem ok={scenario.input_revision_id.length > 0} text="输入修订已固定" />
            <CheckItem ok={metrics.gpu_percent !== null} text="GPU 指标可用" />
          </div>
          <Button icon={<Play size={16} />} onClick={handleEnqueue}>
            加入模拟队列
          </Button>
        </div>
      ) : null}

      {/* 等待中 */}
      {scenario.status === "queued" && item && (item.status === "waiting" || item.status === "queued") && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <h4 className="tf-subtitle">队列位置</h4>
          <div className="tf-display" style={{ color: "var(--color-brand)" }}>
            #{item.position}
          </div>
          <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
            当前队列并发数限制为 1，前面还有 {item.position - 1} 个任务。
          </p>
          <Button variant="secondary" icon={<Square size={16} />} onClick={() => cancelQueueItem(item.queue_item_id)}>
            取消排队
          </Button>
        </div>
      )}

      {/* 运行中 */}
      {scenario.status === "running" && item && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Timer size={16} color="var(--color-foreground-secondary)" />
            <span className="tf-body">已运行 {elapsedText}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <Cpu size={14} color="var(--color-foreground-tertiary)" />
              <span className="tf-caption">CPU {metrics.cpu_percent ?? 0}%</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <Monitor size={14} color="var(--color-foreground-tertiary)" />
              <span className="tf-caption">GPU {metrics.gpu_percent ?? 0}%</span>
            </div>
          </div>
          <div
            style={{
              height: 8,
              borderRadius: 4,
              background: "var(--color-surface-tertiary)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${scenario.progress}%`,
                height: "100%",
                background: "var(--color-brand)",
                transition: "width 500ms ease",
              }}
            />
          </div>
          <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", display: "flex", alignItems: "center", gap: 4 }}>
            <Terminal size={12} />
            轮询状态 · simulation_id: {item.simulation_id || "—"}
          </div>
          <Button variant="danger" icon={<Square size={16} />} onClick={() => stopRunningItem(item.queue_item_id)}>
            停止模拟
          </Button>
        </div>
      )}

      {/* 已完成 */}
      {scenario.status === "completed" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-success)" }}>
            <CheckCircle2 size={20} />
            <span className="tf-body">模拟已完成</span>
          </div>
          <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
            结果族：{scenario.result_family_count} 个 · 文件：{scenario.file_count} 个
          </p>
          <Button variant="secondary" icon={<List size={16} />} onClick={() => setShowLogs((value) => !value)}>
            查看运行日志
          </Button>
        </div>
      )}

      {/* 失败/停止 */}
      {(scenario.status === "failed" || scenario.status === "stopped") && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-error)" }}>
            <AlertCircle size={20} />
            <span className="tf-body">{scenario.status === "failed" ? "模拟失败" : "已停止"}</span>
          </div>
          <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
            请检查参数或输入文件后重试。
          </p>
          <Button icon={<RefreshCw size={16} />} onClick={() => (item ? retryQueueItem(item.queue_item_id) : handleEnqueue())}>
            重新加入队列
          </Button>
        </div>
      )}

      {/* 终端日志 */}
      {showLogs && (scenario.status === "running" || scenario.status === "completed" || scenario.status === "failed" || scenario.status === "stopped" || scenario.status === "interrupted") && (
        <div
          style={{
            flex: 1,
            minHeight: 120,
            borderRadius: "var(--radius-large)",
            background: "#0c0c0c",
            padding: 12,
            overflow: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "#d4d4d4",
          }}
        >
          {logs.map((line, idx) => (
            <div key={idx} style={{ marginBottom: 2 }}>
              {line}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CheckItem({ ok, text }: { ok: boolean; text: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, color: ok ? "var(--color-success)" : "var(--color-error)" }}>
      {ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
      <span className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
        {text}
      </span>
    </div>
  );
}
