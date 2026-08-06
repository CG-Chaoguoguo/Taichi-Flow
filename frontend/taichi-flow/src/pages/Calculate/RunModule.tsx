import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Cpu, List, ListPlus, Monitor, RefreshCw, Terminal, Timer } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import type { QueueItem, Scenario } from "../../types";
import { runApi } from "../../api/taichiFlowAdapter";

export function selectScenarioQueueItem(
  queue: QueueItem[],
  scenario: Pick<Scenario, "scenario_id" | "latest_simulation_id">,
): QueueItem | undefined {
  const scenarioItems = queue.filter((item) => item.scenario_id === scenario.scenario_id);
  const currentQueueItem = scenarioItems.find((item) =>
    ["waiting", "queued", "starting", "running", "stopping"].includes(item.status),
  );
  if (currentQueueItem) return currentQueueItem;
  const latestSimulationItem = scenarioItems.find(
    (item) => Boolean(scenario.latest_simulation_id) && item.simulation_id === scenario.latest_simulation_id,
  );
  return latestSimulationItem ?? scenarioItems[scenarioItems.length - 1];
}

export function RunModule({ scenario, readOnly = false }: { scenario: Scenario; readOnly?: boolean }) {
  const queue = useTaichiFlowStore((state) => state.queue);
  const metrics = useTaichiFlowStore((state) => state.metrics);
  const enqueueScenario = useTaichiFlowStore((state) => state.enqueueScenario);
  const retryQueueItem = useTaichiFlowStore((state) => state.retryQueueItem);
  const setDockTab = useTaichiFlowStore((state) => state.setDockTab);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarioConfiguration = useTaichiFlowStore((state) => state.scenarioConfigurations[scenario.scenario_id]);
  const fetchScenarioConfiguration = useTaichiFlowStore((state) => state.fetchScenarioConfiguration);

  const item = selectScenarioQueueItem(queue, scenario);
  const [logs, setLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState(false);

  useEffect(() => {
    if (readOnly) return;
    if (scenario.latest_simulation_id && activeProject && ["starting", "running", "stopping", "completed", "failed", "stopped", "interrupted"].includes(scenario.status)) {
      const interval = setInterval(() => {
        void runApi.terminal(activeProject.project_id, scenario.latest_simulation_id as string)
          .then((response) => setLogs(response.entries.slice(-200)))
          .catch(() => undefined);
      }, 1000);
      void runApi.terminal(activeProject.project_id, scenario.latest_simulation_id).then((response) => setLogs(response.entries.slice(-200))).catch(() => undefined);
      return () => clearInterval(interval);
    }
  }, [activeProject, readOnly, scenario.latest_simulation_id, scenario.status]);

  useEffect(() => {
    if (!readOnly) void fetchScenarioConfiguration(scenario.scenario_id);
  }, [fetchScenarioConfiguration, readOnly, scenario.scenario_id, scenario.version]);

  const handleEnqueue = async () => {
    if (readOnly) return;
    await enqueueScenario(scenario.scenario_id);
  };

  const elapsed = item?.started_at ? Math.floor((Date.now() - new Date(item.started_at).getTime()) / 1000) : 0;
  const elapsedText = `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;

  if (readOnly) {
    return (
      <div className="tf-module-body tf-stack tf-module-scroll">
        <div className="tf-card">
          <div className="tf-row tf-justify-between">
            <span className="tf-body tf-font-semibold">运行控制</span>
            <StatusBadge variant="neutral">只读</StatusBadge>
          </div>
          <div className="tf-caption tf-text-secondary">
            打开项目并选择方案后，可在此进行预检、入队并查看运行状态。
          </div>
        </div>
        <div className="tf-stack-md">
          <h4 className="tf-subtitle">运行预检</h4>
          <div className="tf-stack-sm">
            <CheckItem ok={false} text="DEM 输入已就绪" />
            <CheckItem ok={false} text="运行输入将在开始计算时冻结" />
            <CheckItem ok={metrics.gpu_percent !== null} text="GPU 指标可用" />
          </div>
          <Button icon={<ListPlus size={16} />} disabled>
            加入模拟队列
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="tf-module-body tf-stack tf-module-scroll">
      {/* 状态摘要 */}
      <div className="tf-card">
        <div className="tf-row tf-justify-between">
          <span className="tf-body tf-font-semibold">
            {scenario.name}
          </span>
          <StatusBadge variant={scenario.status} dot />
        </div>
        <div className="tf-caption tf-text-secondary">
          {scenario.binding_state === "runtime_snapshot"
            ? `运行输入快照 ${scenario.input_revision_id || "已冻结"}`
            : "草稿输入绑定（开始计算时冻结）"}
          · {Object.keys(scenario.parameter_patch || {}).length} 项参数变更
        </div>
      </div>

      {/* 预检 */}
      {scenario.status === "draft" || scenario.status === "ready" ? (
        <div className="tf-stack-md">
          <h4 className="tf-subtitle">运行预检</h4>
          <div className="tf-stack-sm">
            <CheckItem ok={Boolean(scenarioConfiguration?.validation?.valid)} text="草稿输入已通过预检" />
            <CheckItem ok={scenario.binding_state !== "runtime_snapshot" || Boolean(scenario.input_revision_id)} text="运行快照将在开始计算时冻结" />
            <CheckItem ok={metrics.gpu_percent !== null} text="GPU 指标可用" />
          </div>
          {!scenarioConfiguration?.validation?.valid ? (
            <div className="tf-caption tf-text-secondary">
              请补齐草稿输入绑定或参数校验项后再加入队列。
            </div>
          ) : null}
          <Button icon={<ListPlus size={16} />} onClick={handleEnqueue} disabled={!scenarioConfiguration?.validation?.valid}>
            加入模拟队列
          </Button>
        </div>
      ) : null}

      {/* 等待中 */}
      {(scenario.status === "waiting" || scenario.status === "queued") && item && (item.status === "waiting" || item.status === "queued") && (
        <div className="tf-stack-md">
          <h4 className="tf-subtitle">队列位置</h4>
          <div className="tf-display tf-text-brand">
            #{item.queue_order ?? item.position}
          </div>
          <p className="tf-body tf-text-secondary">
            {item.status === "waiting" ? "已加入待运行批次；请在底部队列点击“运行队列”。" : "当前批次已释放给调度器，排序已锁定。"}
          </p>
          <p className="tf-caption tf-text-warning">计算开始前输入仍可修改；开始后将冻结运行快照。</p>
          <Button variant="secondary" icon={<List size={16} />} onClick={() => setDockTab("queue")}>
            打开队列
          </Button>
        </div>
      )}

      {/* 运行中 */}
      {scenario.status === "running" && item && (
        <div className="tf-stack-md">
          <div className="tf-caption tf-text-info">运行输入快照已冻结，计算引用中的资产不可删除。</div>
          <div className="tf-row tf-gap-2">
            <Timer size={16} className="tf-text-secondary" />
            <span className="tf-body">已运行 {elapsedText}</span>
          </div>
          <div className="tf-row tf-gap-4">
            <div className="tf-row tf-gap-1">
              <Cpu size={14} className="tf-text-tertiary" />
              <span className="tf-caption">CPU {metrics.cpu_percent ?? 0}%</span>
            </div>
            <div className="tf-row tf-gap-1">
              <Monitor size={14} className="tf-text-tertiary" />
              <span className="tf-caption">GPU {metrics.gpu_percent ?? 0}%</span>
            </div>
          </div>
          <div className="tf-progress">
            <div className="tf-progress-fill" style={{ width: `${scenario.progress}%` }} />
          </div>
          <div className="tf-caption tf-text-tertiary tf-row tf-gap-1">
            <Terminal size={12} />
            轮询状态 · simulation_id: {item.simulation_id || "—"}
          </div>
        </div>
      )}

      {/* 已完成 */}
      {scenario.status === "completed" && (
        <div className="tf-stack-md">
          <div className="tf-status-row is-success">
            <CheckCircle2 size={20} />
            <span className="tf-body">模拟已完成</span>
          </div>
          <p className="tf-body tf-text-secondary">
            结果族：{scenario.result_family_count} 个 · 文件：{scenario.file_count} 个
          </p>
          <Button variant="secondary" icon={<List size={16} />} onClick={() => setShowLogs((value) => !value)}>
            查看运行日志
          </Button>
        </div>
      )}

      {/* 失败/停止 */}
      {(scenario.status === "failed" || scenario.status === "stopped") && (
        <div className="tf-stack-md">
          <div className="tf-status-row is-error">
            <AlertCircle size={20} />
            <span className="tf-body">{scenario.status === "failed" ? "模拟失败" : "已停止"}</span>
          </div>
          <p className="tf-body tf-text-secondary">
            请检查参数或输入文件后重试。
          </p>
          <Button icon={<RefreshCw size={16} />} onClick={() => (item ? retryQueueItem(item.queue_item_id) : handleEnqueue())}>
            重新加入队列
          </Button>
        </div>
      )}

      {/* 终端日志 */}
      {showLogs && (scenario.status === "running" || scenario.status === "completed" || scenario.status === "failed" || scenario.status === "stopped" || scenario.status === "interrupted") && (
        <div className="tf-terminal">
          {logs.map((line, idx) => (
            <div key={idx} className="tf-terminal-line">
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
    <div className={`tf-check-row${ok ? " is-ok" : " is-fail"}`}>
      {ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
      <span className="tf-body tf-text-secondary">
        {text}
      </span>
    </div>
  );
}
