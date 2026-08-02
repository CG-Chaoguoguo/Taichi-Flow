import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Calculator,
  Database,
  Download,
  List,
  Plus,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div
      style={{
        padding: 20,
        borderRadius: "var(--radius-xlarge)",
        border: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        boxShadow: "var(--shadow-rest)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 className="tf-subtitle">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  );
}

export function ProjectOverview() {
  const navigate = useNavigate();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const queue = useTaichiFlowStore((state) => state.queue);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const fetchScenarios = useTaichiFlowStore((state) => state.fetchScenarios);
  const fetchInputFiles = useTaichiFlowStore((state) => state.fetchInputFiles);
  const fetchQueue = useTaichiFlowStore((state) => state.fetchQueue);

  useEffect(() => {
    fetchScenarios();
    fetchInputFiles();
    fetchQueue();
  }, [fetchScenarios, fetchInputFiles, fetchQueue]);

  if (!activeProject) {
    return (
      <div style={{ padding: 48, textAlign: "center" }}>
        <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          请先选择或创建一个项目。
        </p>
      </div>
    );
  }

  const statusCounts = {
    draft: scenarios.filter((s) => s.status === "draft").length,
    ready: scenarios.filter((s) => s.status === "ready").length,
    queued: scenarios.filter((s) => s.status === "queued").length,
    running: scenarios.filter((s) => s.status === "running").length,
    completed: scenarios.filter((s) => s.status === "completed").length,
    failed: scenarios.filter((s) => s.status === "failed" || s.status === "stopped").length,
  };

  const runningItem = queue.find((q) => q.status === "running");
  const waitingCount = queue.filter((q) => q.status === "waiting").length;
  const completedScenarios = scenarios.filter((s) => s.status === "completed");

  let nextAction: { label: string; path: string; icon: React.ReactNode } | null = null;
  if (inputFiles.length === 0) {
    nextAction = { label: "配置项目输入", path: "#", icon: <Database size={16} /> };
  } else if (scenarios.length === 0) {
    nextAction = { label: "新建参数方案", path: `/projects/${activeProject.project_id}/scenarios`, icon: <Plus size={16} /> };
  } else if (runningItem) {
    nextAction = { label: "查看当前模拟", path: `/projects/${activeProject.project_id}/queue`, icon: <Calculator size={16} /> };
  } else if (waitingCount > 0) {
    nextAction = { label: "查看模拟队列", path: `/projects/${activeProject.project_id}/queue`, icon: <List size={16} /> };
  } else if (statusCounts.ready > 0) {
    nextAction = { label: "将方案加入队列", path: `/projects/${activeProject.project_id}/scenarios`, icon: <List size={16} /> };
  } else if (completedScenarios.length > 0) {
    nextAction = { label: "导出数据", path: `/projects/${activeProject.project_id}/export`, icon: <Download size={16} /> };
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "32px" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 className="tf-display" style={{ marginBottom: 8 }}>
              {activeProject.name}
            </h1>
            <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
              {activeProject.description || "项目概览显示共享输入、方案状态、队列和结果摘要。"}
            </p>
          </div>
          {nextAction && (
            <Button icon={nextAction.icon} onClick={() => navigate(nextAction!.path)}>
              {nextAction.label}
            </Button>
          )}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 16,
            marginBottom: 24,
          }}
        >
          <SectionCard title="项目摘要">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                项目路径
              </div>
              <div className="tf-mono" style={{ wordBreak: "break-all" }}>
                {activeProject.root_path}
              </div>
              <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                更新时间
              </div>
              <div className="tf-body">{new Date(activeProject.updated_at).toLocaleString("zh-CN")}</div>
            </div>
          </SectionCard>

          <SectionCard
            title="共享输入"
            action={
              <Button variant="ghost" size="small" icon={<Database size={14} />}>
                管理
              </Button>
            }
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
              {inputFiles.every((f) => f.status === "ready") ? (
                <CheckCircle2 size={20} color="var(--color-success)" />
              ) : (
                <AlertCircle size={20} color="var(--color-warning)" />
              )}
              <span className="tf-subtitle">
                {inputFiles.filter((f) => f.status === "ready").length}/{inputFiles.length} 就绪
              </span>
            </div>
            <p className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
              输入修订由每个方案固定引用 · 所有方案共享不可变输入文件
            </p>
          </SectionCard>

          <SectionCard title="方案状态">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              <div style={{ textAlign: "center" }}>
                <div className="tf-subtitle">{statusCounts.draft}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  草稿
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div className="tf-subtitle">{statusCounts.ready}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  待模拟
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div className="tf-subtitle">{statusCounts.running}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  运行中
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div className="tf-subtitle">{statusCounts.completed}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  已完成
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div className="tf-subtitle">{statusCounts.queued + waitingCount}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  排队中
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div className="tf-subtitle">{statusCounts.failed}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  失败/停止
                </div>
              </div>
            </div>
          </SectionCard>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
          <SectionCard
            title="模拟队列"
            action={
              <Button
                variant="ghost"
                size="small"
                icon={<ArrowRight size={14} />}
                onClick={() => navigate(`/projects/${activeProject.project_id}/queue`)}
              >
                查看
              </Button>
            }
          >
            {runningItem ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <StatusBadge variant="running" dot />
                  <span className="tf-body">{runningItem.scenario_name}</span>
                </div>
                <div
                  style={{
                    height: 6,
                    borderRadius: 3,
                    background: "var(--color-surface-tertiary)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${runningItem.progress}%`,
                      height: "100%",
                      background: "var(--color-brand)",
                      transition: "width 500ms ease",
                    }}
                  />
                </div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                      进度 {runningItem.progress}% · 项目内串行
                </div>
              </div>
            ) : (
              <div style={{ color: "var(--color-foreground-secondary)" }} className="tf-body">
                当前没有运行中的任务。{waitingCount > 0 ? `队列中有 ${waitingCount} 个待执行任务。` : "请从方案管理加入队列。"}
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="结果摘要"
            action={
              <Button
                variant="ghost"
                size="small"
                icon={<ArrowRight size={14} />}
                onClick={() => navigate(`/projects/${activeProject.project_id}/export`)}
              >
                导出
              </Button>
            }
          >
            <div style={{ display: "flex", gap: 24 }}>
              <div>
                <div className="tf-subtitle">{completedScenarios.length}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  已完成方案
                </div>
              </div>
              <div>
                <div className="tf-subtitle">{completedScenarios.reduce((sum, s) => sum + s.result_family_count, 0)}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  结果族总数
                </div>
              </div>
              <div>
                <div className="tf-subtitle">{completedScenarios.length > 0 ? new Date(Math.max(...completedScenarios.map((scenario) => new Date(scenario.updated_at).getTime()))).toLocaleDateString("zh-CN") : "—"}</div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  最近完成
                </div>
              </div>
            </div>
          </SectionCard>
        </div>

        <div style={{ display: "flex", gap: 12 }}>
          <Button icon={<Plus size={16} />} onClick={() => navigate(`/projects/${activeProject.project_id}/scenarios`)}>
            新建参数方案
          </Button>
          <Button variant="secondary" icon={<Calculator size={16} />} onClick={() => navigate(`/projects/${activeProject.project_id}/scenarios`)}>
            打开方案管理
          </Button>
          <Button variant="secondary" icon={<List size={16} />} onClick={() => navigate(`/projects/${activeProject.project_id}/queue`)}>
            查看队列
          </Button>
        </div>
      </div>
    </div>
  );
}
