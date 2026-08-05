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
import { IconButton } from "../../components/IconButton";
import { StatusBadge } from "../../components/StatusBadge";
import type { Scenario } from "../../types";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const statusFilters = [
  { key: "all", label: "全部" },
  { key: "draft", label: "草稿" },
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
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const fetchScenarios = useTaichiFlowStore((state) => state.fetchScenarios);
  const fetchInputFiles = useTaichiFlowStore((state) => state.fetchInputFiles);
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
    fetchInputFiles();
  }, [fetchScenarios, fetchInputFiles]);

  const hasDem = inputFiles.some((file) => file.family === "dem" && (file.status === "ready" || file.status === "warning"));
  const needsBasicInputs = !hasDem;

  const filtered = useMemo(() => {
    return scenarios
      .filter((s) => (filter === "all" ? true : s.status === filter || (filter === "failed" && (s.status === "failed" || s.status === "stopped"))))
      .filter((s) => s.name.toLowerCase().includes(search.toLowerCase()));
  }, [scenarios, filter, search]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      const scenario = await createScenario(newName, baseId || undefined);
      setShowCreate(false);
      setNewName("");
      setBaseId("");
      if (scenario.status === "draft") {
        addToast({
          type: "warning",
          message: "方案已创建。请在输入绑定中选择 DEM 等资产并完成预检，再加入队列。",
        });
      } else {
        addToast({ type: "success", message: "方案已创建" });
      }
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
    return <div className="tf-empty-state tf-body">请先选择项目。</div>;
  }

  return (
    <div className="tf-fill-col">
      <div className="tf-page-toolbar tf-animate-in">
        <div className="tf-page-header">
          <div>
            <h1 className="tf-display tf-mb-2">方案管理</h1>
            <p className="tf-body tf-text-secondary">
              同一项目共享输入版本；各方案仅参数不同，并落在项目下独立子目录中。
            </p>
          </div>
          <Button icon={<Plus size={16} />} onClick={() => setShowCreate(true)}>
            新建方案
          </Button>
        </div>

        {needsBasicInputs ? (
          <div role="status" className="tf-alert-banner tf-mb-4">
            <div>
              <div className="tf-body tf-font-semibold tf-mb-2">尚未准备好基础输入数据</div>
              <div className="tf-caption tf-text-secondary">
                仍可先新建方案。入队前请在项目资产库导入 DEM（必填）等数据，并在方案“输入绑定”中完成预检。
              </div>
            </div>
            <Button
              variant="secondary"
              size="small"
              onClick={() => navigate(`/projects/${activeProject.project_id}`)}
            >
              去项目上传
            </Button>
          </div>
        ) : null}

        <div className="tf-row tf-mb-4">
          <div className="tf-search-box tf-search-box--narrow">
            <Search size={16} className="tf-text-tertiary" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索方案名称..."
            />
          </div>
          <div className="tf-row tf-gap-1">
            <Filter size={16} className="tf-text-tertiary" />
            {statusFilters.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`tf-filter-pill${filter === f.key ? " active" : ""}`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="tf-scroll-body">
        <div className="tf-table-wrap tf-glass">
          <table className="tf-table">
            <thead>
              <tr>
                {["方案名称", "输入版本", "工作目录", "参数摘要", "状态", "进度", "更新时间", "结果概况", "操作"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="tf-empty-state tf-body">暂无符合条件的方案</td>
                </tr>
              ) : (
                filtered.map((s) => (
                  <ScenarioRow
                    key={s.scenario_id}
                    scenario={s}
                    onEnqueue={handleEnqueue}
                    onDuplicate={handleDuplicate}
                    onDelete={handleDelete}
                  />
                ))
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
          needsBasicInputs={needsBasicInputs}
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
    <tr>
      <td>
        <div className="tf-body tf-font-semibold tf-mb-2">{scenario.name}</div>
        <div className="tf-mono tf-text-tertiary">{scenario.scenario_id}</div>
      </td>
      <td>
        <span className={`tf-caption ${scenario.input_revision_id ? "tf-text-secondary" : "tf-text-warning"}`}>
          {scenario.binding_state === "runtime_snapshot" ? "运行快照已冻结" : "草稿输入绑定"}
        </span>
      </td>
      <td>
        <span className="tf-mono tf-text-tertiary tf-ellipsis tf-block" title={scenario.work_dir}>
          {scenario.work_dir || `scenarios/${scenario.scenario_id}`}
        </span>
      </td>
      <td>
        <span className="tf-body tf-text-secondary">{paramSummary}</span>
      </td>
      <td>
        <StatusBadge variant={scenario.status} dot />
      </td>
      <td>
        {scenario.status === "running" ? (
          <div>
            <div className="tf-progress tf-mb-2">
              <div className="tf-progress-fill" style={{ width: `${scenario.progress}%` }} />
            </div>
            <span className="tf-caption tf-text-tertiary">{scenario.progress}%</span>
          </div>
        ) : (
          <span className="tf-caption tf-text-tertiary">—</span>
        )}
      </td>
      <td>
        <span className="tf-caption tf-text-secondary tf-row tf-gap-1">
          <Clock size={12} />
          {formatDate(scenario.updated_at)}
        </span>
      </td>
      <td>
        <span className="tf-body tf-text-secondary">
          {scenario.status === "completed" ? `${scenario.result_family_count} 个结果族 · ${scenario.file_count} 个文件` : "—"}
        </span>
      </td>
      <td>
        <div className="tf-icon-actions">
          <IconButton
            size="small"
            icon={<Edit3 size={16} />}
            label="打开"
            className="tf-text-brand"
            onClick={() => navigate(`/projects/${projectId}/scenarios/${scenario.scenario_id}/calculate`)}
          />
          {(scenario.status === "ready" || scenario.status === "draft" || scenario.status === "failed" || scenario.status === "stopped") && (
            <IconButton
              size="small"
              icon={<Play size={16} />}
              label="加入队列"
              className="tf-text-brand"
              onClick={() => onEnqueue(scenario.scenario_id)}
            />
          )}
          {scenario.status === "completed" && (
            <IconButton size="small" icon={<Download size={16} />} label="查看结果" />
          )}
          <IconButton
            size="small"
            icon={<Copy size={16} />}
            label="复制"
            onClick={() => onDuplicate(scenario.scenario_id)}
          />
          <IconButton
            size="small"
            icon={<Trash2 size={16} />}
            label="删除"
            className="tf-text-error"
            onClick={() => onDelete(scenario.scenario_id)}
          />
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
  needsBasicInputs,
  onClose,
  onCreate,
}: {
  newName: string;
  setNewName: (v: string) => void;
  baseId: string;
  setBaseId: (v: string) => void;
  scenarios: Scenario[];
  needsBasicInputs: boolean;
  onClose: () => void;
  onCreate: () => void | Promise<void>;
}) {
  return (
    <div className="tf-dialog-overlay" onClick={onClose}>
      <div className="tf-dialog tf-dialog-narrow" onClick={(e) => e.stopPropagation()}>
        <h2 className="tf-title tf-mb-4">新建参数方案</h2>
        <div className="tf-form-stack">
          <label className="tf-caption tf-text-secondary">方案名称</label>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="例如：高摩阻方案"
            className="tf-input tf-full-width"
          />
          <label className="tf-caption tf-text-secondary">基于方案</label>
          <select value={baseId} onChange={(e) => setBaseId(e.target.value)} className="tf-select tf-full-width">
            <option value="">基准参数</option>
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.name}
              </option>
            ))}
          </select>
          {needsBasicInputs ? (
            <div className="tf-info-callout tf-caption">
              当前还缺少 DEM 等基础输入。仍可创建为草稿方案；上传资产并完成输入绑定预检后，即可加入模拟队列。
            </div>
          ) : null}
        </div>
        <div className="tf-row tf-justify-end tf-gap-2">
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
