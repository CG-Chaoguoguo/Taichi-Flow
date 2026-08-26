import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Cpu, List, Monitor, Play, RefreshCw, Square, Terminal, Timer } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { FailureSourcePolicySummary } from "../../components/FailureSourcePolicySummary";
import type { Scenario } from "../../types";
import { runApi } from "../../api/taichiFlowAdapter";

export function RunModule({ scenario, readOnly = false }: { scenario: Scenario; readOnly?: boolean }) {
  const queue = useTaichiFlowStore((state) => state.queue);
  const metrics = useTaichiFlowStore((state) => state.metrics);
  const enqueueScenario = useTaichiFlowStore((state) => state.enqueueScenario);
  const cancelQueueItem = useTaichiFlowStore((state) => state.cancelQueueItem);
  const stopRunningItem = useTaichiFlowStore((state) => state.stopRunningItem);
  const retryQueueItem = useTaichiFlowStore((state) => state.retryQueueItem);
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const catalog = useTaichiFlowStore((state) => state.parameterCatalog);
  const fetchParameterCatalog = useTaichiFlowStore((state) => state.fetchParameterCatalog);
  const scenarioConfiguration = useTaichiFlowStore((state) => state.scenarioConfigurations[scenario.scenario_id]);
  const fetchScenarioConfiguration = useTaichiFlowStore((state) => state.fetchScenarioConfiguration);
  const navigate = useNavigate();

  const item = queue.find((q) => q.scenario_id === scenario.scenario_id);
  const policyResolution = scenarioConfiguration?.compute_policy_resolution;
  const policyBlocked = policyResolution?.status === "blocked";
  const policyResolved = policyResolution?.status === "resolved";
  const [logs, setLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [runtimeProfile, setRuntimeProfile] = useState("cuda_production_default");
  const profileOptions = catalog?.runtime_profiles?.user_selectable?.length
    ? catalog.runtime_profiles.user_selectable
    : [
        { name: "cuda_production_default", label_zh: "CUDA 加速", description_zh: "使用 GPU 运行生产求解器（默认）。" },
        { name: "compat_default_off", label_zh: "CPU 兼容", description_zh: "使用 CPU 运行，适合无 GPU 环境。" },
      ];

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

  useEffect(() => {
    if (!catalog) void fetchParameterCatalog();
  }, [catalog, fetchParameterCatalog]);

  const handleEnqueue = async () => {
    if (readOnly) return;
    await enqueueScenario(scenario.scenario_id, runtimeProfile);
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
            打开项目并选择方案后，可在此进行预检、入队与运行控制。
          </div>
        </div>
        <div className="tf-stack-md">
          <h4 className="tf-subtitle">运行预检</h4>
          <div className="tf-stack-sm">
            <CheckItem ok={false} text="DEM 输入已就绪" />
            <CheckItem ok={false} text="运行输入将在开始计算时冻结" />
            <CheckItem ok={metrics.gpu_percent !== null} text="GPU 指标可用" />
          </div>
          <Button icon={<Play size={16} />} disabled>
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
            <CheckItem ok={Boolean(scenarioConfiguration?.validation?.valid)} text="方案输入已通过预检" />
            <CheckItem ok={policyResolved} text="失稳源策略已严格解析" />
            <CheckItem ok={scenario.binding_state !== "runtime_snapshot" || Boolean(scenario.input_revision_id)} text="入队时冻结输入与计算策略" />
            <CheckItem ok={metrics.gpu_percent !== null} text="GPU 指标可用" />
          </div>
          {!scenarioConfiguration ? (
            <div className="tf-caption tf-text-info">正在解析失稳源策略…</div>
          ) : null}
          {policyBlocked ? (
            <div className="tf-status-row is-error" role="alert">
              <AlertCircle size={16} />
              <span className="tf-body">{policyResolution.blocking_issue.message}</span>
            </div>
          ) : null}
          {!scenarioConfiguration?.validation?.valid && scenarioConfiguration ? (
            <div className="tf-caption tf-text-secondary">
              请补齐草稿输入绑定或参数校验项后再加入队列。
            </div>
          ) : null}
          <label className="tf-stack-sm" htmlFor="run-runtime-profile">
            <span className="tf-body tf-font-medium">计算后端（仅本次运行）</span>
            <select
              id="run-runtime-profile"
              className="tf-input"
              data-testid="run-runtime-profile"
              value={runtimeProfile}
              onChange={(event) => setRuntimeProfile(event.target.value)}
            >
              {profileOptions.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.label_zh || option.name}
                </option>
              ))}
            </select>
            <span className="tf-caption tf-text-tertiary">
              {profileOptions.find((option) => option.name === runtimeProfile)?.description_zh
                || "CUDA 与 CPU 仅影响本次入队任务，不写入方案参数。"}
            </span>
          </label>
          <FailureSourcePolicySummary resolution={policyResolution} />
          <button type="button" className="tf-link-button" onClick={() => navigate("/settings#compute-gates")}>
            {policyBlocked ? "前往设置调整策略 →" : "管理计算门禁 →"}
          </button>
          <Button icon={<Play size={16} />} onClick={handleEnqueue} disabled={!scenarioConfiguration?.validation?.valid || !policyResolved}>
            加入模拟队列
          </Button>
        </div>
      ) : null}

      {/* 等待中 */}
      {scenario.status === "queued" && item && (item.status === "waiting" || item.status === "queued") && (
        <div className="tf-stack-md">
          <h4 className="tf-subtitle">队列位置</h4>
          <div className="tf-display tf-text-brand">
            #{item.position}
          </div>
          <p className="tf-body tf-text-secondary">
            当前队列并发数限制为 1，前面还有 {item.position - 1} 个任务。
          </p>
           <p className="tf-caption tf-text-info">入队时已冻结输入修订与计算策略；如需使用新的 Settings，请重新加入队列。</p>
           <FailureSourcePolicySummary resolution={item.compute_policy_resolution} />
          <Button variant="secondary" icon={<Square size={16} />} onClick={() => cancelQueueItem(item.queue_item_id)}>
            取消排队
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
          <Button variant="danger" icon={<Square size={16} />} onClick={() => stopRunningItem(item.queue_item_id)}>
            停止模拟
          </Button>
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
