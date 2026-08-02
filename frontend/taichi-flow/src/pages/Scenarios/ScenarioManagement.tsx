import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Copy,
  Download,
  Edit3,
  Filter,
  Play,
  Plus,
  Search,
  Trash2,
  Clock,
} from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import type { Scenario } from "../../types";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const statusFilters = [
  { key: "all", label: "全部" },
  { key: "ready", label: "待模拟" },
  { key: "queued", label: "排队中" },
  { key: "running", label: "运行中" },
  { key: "completed", label: "已完成" },
  { key: "failed", label: "失败/停止" },
  { key: "archived", label: "已归档" },
];

export function ScenarioManagement() {
  const navigate = useNavigate();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const fetchScenarios = useTaichiFlowStore((state) => state.fetchScenarios);
  const createScenario = useTaichiFlowStore((state) => state.createScenario);
  const duplicateScenario = useTaichiFlowStore((state) => state.duplicateScenario);
  const deleteScenario = useTaichiFlowStore((state) => state.deleteScenario);
  const enqueueScenario = useTaichiFlowStore((state) => state.enqueueScenario);
  const addToast = useTaichiFlowStore((state) => state.addToast);

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [baseId, setBaseId] = useState("");

  useEffect(() => {
    fetchScenarios();
  }, [fetchScenarios]);

  const filtered = useMemo(() => {
    return scenarios
      .filter((s) => (filter === "all" ? true : s.status === filter || (filter === "failed" && (s.status === "failed" || s.status === "stopped"))))
      .filter((s) => s.name.toLowerCase().includes(search.toLowerCase()));
  }, [scenarios, filter, search]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      await createScenario(newName, baseId || undefined);
      setShowCreate(false);
      setNewName("");
      setBaseId("");
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "创建方案失败" });
    }
  };

  const handleEnqueue = async (scenarioId: string) => {
    try {
      await enqueueScenario(scenarioId);
      navigate(`/projects/${activeProject?.project_id}/queue`);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "加入队列失败" });
    }
  };

  const handleDuplicate = async (scenarioId: string) => {
    try {
      await duplicateScenario(scenarioId);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "复制方案失败" });
    }
  };

  const handleDelete = async (scenarioId: string) => {
    try {
      await deleteScenario(scenarioId);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "删除方案失败" });
    }
  };

  if (!activeProject) {
    return (
      <div style={{ padding: 48 }}>
        <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          请先选择项目。
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "24px 32px 0" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div>
            <h1 className="tf-display" style={{ marginBottom: 4 }}>
              方案管理
            </h1>
            <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
              同一项目内的多套参数方案共享输入文件，每套方案拥有独立的模拟状态和结果。
            </p>
          </div>
          <Button icon={<Plus size={16} />} onClick={() => setShowCreate(true)}>
            新建方案
          </Button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              borderRadius: "var(--radius-large)",
              border: "1px solid var(--color-border)",
              background: "var(--color-surface)",
              flex: 1,
              maxWidth: 320,
            }}
          >
            <Search size={16} color="var(--color-foreground-tertiary)" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索方案名称..."
              style={{ flex: 1, border: "none", background: "transparent", outline: "none", color: "var(--color-foreground)" }}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Filter size={16} color="var(--color-foreground-tertiary)" />
            {statusFilters.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                style={{
                  padding: "4px 10px",
                  borderRadius: "var(--radius-medium)",
                  border: "none",
                  background: filter === f.key ? "var(--color-brand-bg-subtle)" : "transparent",
                  color: filter === f.key ? "var(--color-brand)" : "var(--color-foreground-secondary)",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "0 32px 32px" }}>
        <div style={{ borderRadius: "var(--radius-xlarge)", border: "1px solid var(--color-border)", overflow: "hidden", background: "var(--color-surface)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--color-surface-tertiary)" }}>
                {["方案名称", "输入版本", "参数摘要", "状态", "进度", "更新时间", "结果概况", "操作"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 16px",
                      textAlign: "left",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "var(--color-foreground-secondary)",
                      borderBottom: "1px solid var(--color-border)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: "center", padding: 48, color: "var(--color-foreground-secondary)" }}>
                    暂无符合条件的方案
                  </td>
                </tr>
              ) : (
                filtered.map((s) => <ScenarioRow key={s.scenario_id} scenario={s} onEnqueue={handleEnqueue} onDuplicate={handleDuplicate} onDelete={handleDelete} />)
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showCreate && (
        <CreateScenarioDialog
          newName={newName}
          setNewName={setNewName}
          baseId={baseId}
          setBaseId={setBaseId}
          scenarios={scenarios}
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}

function ScenarioRow({
  scenario,
  onEnqueue,
  onDuplicate,
  onDelete,
}: {
  scenario: Scenario;
  onEnqueue: (id: string) => void;
  onDuplicate: (id: string) => Promise<unknown>;
  onDelete: (id: string) => Promise<void>;
}) {
  const navigate = useNavigate();
  const projectId = useTaichiFlowStore((state) => state.activeProject)?.project_id;

  const paramCount = Object.keys(scenario.parameter_patch || {}).length;
  const paramSummary = paramCount === 0 ? "使用基准参数" : `${paramCount} 项参数已修改`;

  return (
    <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
      <td style={{ padding: "12px 16px" }}>
        <div className="tf-body" style={{ fontWeight: 600, marginBottom: 2 }}>
          {scenario.name}
        </div>
        <div className="tf-mono" style={{ color: "var(--color-foreground-tertiary)" }}>
          {scenario.scenario_id}
        </div>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
          {scenario.input_revision_id}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          {paramSummary}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <StatusBadge variant={scenario.status} dot />
      </td>
      <td style={{ padding: "12px 16px" }}>
        {scenario.status === "running" ? (
          <div>
            <div
              style={{
                height: 6,
                borderRadius: 3,
                background: "var(--color-surface-tertiary)",
                overflow: "hidden",
                marginBottom: 4,
              }}
            >
              <div
                style={{ width: `${scenario.progress}%`, height: "100%", background: "var(--color-brand)", transition: "width 500ms ease" }}
              />
            </div>
            <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
              {scenario.progress}%
            </span>
          </div>
        ) : (
          <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
            —
          </span>
        )}
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span className="tf-caption" style={{ color: "var(--color-foreground-secondary)", display: "flex", alignItems: "center", gap: 4 }}>
          <Clock size={12} />
          {formatDate(scenario.updated_at)}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          {scenario.status === "completed" ? `${scenario.result_family_count} 个结果族 · ${scenario.file_count} 个文件` : "—"}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={() => navigate(`/projects/${projectId}/scenarios/${scenario.scenario_id}/calculate`)}
            style={{ display: "flex", alignItems: "center", color: "var(--color-brand)" }}
            title="打开"
            aria-label="打开"
          >
            <Edit3 size={16} />
          </button>
          {(scenario.status === "ready" || scenario.status === "draft" || scenario.status === "failed" || scenario.status === "stopped") && (
            <button onClick={() => onEnqueue(scenario.scenario_id)} style={{ display: "flex", alignItems: "center", color: "var(--color-brand)" }} title="加入队列" aria-label="加入队列">
              <Play size={16} />
            </button>
          )}
          {scenario.status === "completed" && (
            <button style={{ display: "flex", alignItems: "center", color: "var(--color-foreground-secondary)" }} title="查看结果" aria-label="查看结果">
              <Download size={16} />
            </button>
          )}
          <button onClick={() => onDuplicate(scenario.scenario_id)} style={{ display: "flex", alignItems: "center", color: "var(--color-foreground-secondary)" }} title="复制" aria-label="复制">
            <Copy size={16} />
          </button>
          <button onClick={() => onDelete(scenario.scenario_id)} style={{ display: "flex", alignItems: "center", color: "var(--color-error)" }} title="删除" aria-label="删除">
            <Trash2 size={16} />
          </button>
        </div>
      </td>
    </tr>
  );
}

function CreateScenarioDialog({
  newName,
  setNewName,
  baseId,
  setBaseId,
  scenarios,
  onClose,
  onCreate,
}: {
  newName: string;
  setNewName: (v: string) => void;
  baseId: string;
  setBaseId: (v: string) => void;
  scenarios: Scenario[];
  onClose: () => void;
  onCreate: () => void | Promise<void>;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.35)",
        zIndex: 900,
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: 480,
          padding: 24,
          borderRadius: "var(--radius-xlarge)",
          background: "var(--color-surface)",
          boxShadow: "var(--shadow-dialog)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="tf-title" style={{ marginBottom: 16 }}>
          新建参数方案
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 20 }}>
          <label className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
            方案名称
          </label>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="例如：高摩阻方案"
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius-large)",
              border: "1px solid var(--color-border)",
              background: "var(--color-bg-canvas)",
              color: "var(--color-foreground)",
            }}
          />
          <label className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
            基于方案
          </label>
          <select
            value={baseId}
            onChange={(e) => setBaseId(e.target.value)}
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius-large)",
              border: "1px solid var(--color-border)",
              background: "var(--color-bg-canvas)",
              color: "var(--color-foreground)",
            }}
          >
            <option value="">基准参数</option>
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onCreate} disabled={!newName.trim()}>
            创建
          </Button>
        </div>
      </div>
    </div>
  );
}
