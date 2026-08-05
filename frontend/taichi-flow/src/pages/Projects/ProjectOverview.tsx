import { useEffect, useRef, useState } from "react";
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
  FolderOpen,
} from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { DirectoryPickerDialog } from "../../components/DirectoryPickerDialog";
import { INPUT_FAMILIES, INPUT_FAMILY_LABELS } from "../../constants/inputFamilies";

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="tf-card">
      <div className="tf-row tf-justify-between tf-card-header">
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
  const fetchInputRevisions = useTaichiFlowStore((state) => state.fetchInputRevisions);
  const fetchQueue = useTaichiFlowStore((state) => state.fetchQueue);
  const uploadInputFromPath = useTaichiFlowStore((state) => state.uploadInputFromPath);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const inputPanelRef = useRef<HTMLDivElement>(null);
  const [uploadFamily, setUploadFamily] = useState("dem");
  const [showFilePicker, setShowFilePicker] = useState(false);

  useEffect(() => {
    fetchScenarios();
    fetchInputFiles();
    fetchInputRevisions();
    fetchQueue();
  }, [fetchScenarios, fetchInputFiles, fetchInputRevisions, fetchQueue]);

  if (!activeProject) {
    return (
      <div className="tf-empty-state tf-body">
        请先选择或创建一个项目。
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

  const scrollToInputs = () => {
    inputPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  let nextAction: { label: string; action: () => void; icon: React.ReactNode } | null = null;
  if (inputFiles.length === 0) {
    nextAction = { label: "配置项目输入", action: scrollToInputs, icon: <Database size={16} /> };
  } else if (scenarios.length === 0) {
    nextAction = {
      label: "新建参数方案",
      action: () => navigate(`/projects/${activeProject.project_id}/scenarios`),
      icon: <Plus size={16} />,
    };
  } else if (runningItem) {
    nextAction = {
      label: "查看当前模拟",
      action: () => navigate(`/projects/${activeProject.project_id}/queue`),
      icon: <Calculator size={16} />,
    };
  } else if (waitingCount > 0) {
    nextAction = {
      label: "查看模拟队列",
      action: () => navigate(`/projects/${activeProject.project_id}/queue`),
      icon: <List size={16} />,
    };
  } else if (statusCounts.ready > 0) {
    nextAction = {
      label: "将方案加入队列",
      action: () => navigate(`/projects/${activeProject.project_id}/scenarios`),
      icon: <List size={16} />,
    };
  } else if (completedScenarios.length > 0) {
    nextAction = {
      label: "导出数据",
      action: () => navigate(`/projects/${activeProject.project_id}/export`),
      icon: <Download size={16} />,
    };
  }

  return (
    <div className="tf-page">
      <div className="tf-page-content tf-animate-in">
        <div className="tf-page-header">
          <div>
            <h1 className="tf-display tf-mb-2">{activeProject.name}</h1>
            <p className="tf-body tf-text-secondary">
              {activeProject.description || "项目是多套计算方案的容器：输入数据项目共享，各方案仅参数不同。"}
            </p>
          </div>
          {nextAction && (
            <Button icon={nextAction.icon} onClick={nextAction.action}>
              {nextAction.label}
            </Button>
          )}
        </div>

        <div className="tf-metric-grid tf-mb-6">
          <SectionCard title="项目摘要">
            <div className="tf-stack tf-gap-1">
              <div className="tf-caption tf-text-tertiary">项目路径</div>
              <div className="tf-mono tf-break-all">{activeProject.root_path}</div>
              <div className="tf-caption tf-text-tertiary">更新时间</div>
              <div className="tf-body">{new Date(activeProject.updated_at).toLocaleString("zh-CN")}</div>
            </div>
          </SectionCard>

          <SectionCard
            title="共享输入"
            action={
              <Button variant="ghost" size="small" icon={<Database size={14} />} onClick={scrollToInputs}>
                管理
              </Button>
            }
          >
            <div className="tf-row tf-gap-2 tf-mb-2">
              {inputFiles.length > 0 && inputFiles.every((f) => f.status === "ready") ? (
                <CheckCircle2 size={20} className="tf-text-success" />
              ) : (
                <AlertCircle size={20} className="tf-text-warning" />
              )}
              <span className="tf-subtitle">
                {inputFiles.filter((f) => f.status === "ready").length}/{inputFiles.length} 就绪
              </span>
            </div>
            <p className="tf-caption tf-text-secondary">
              上传只收录到项目资产库；方案草稿可自由绑定或删除，计算开始后才冻结运行快照。
            </p>
          </SectionCard>

          <SectionCard title="方案状态">
            <div className="tf-stat-grid">
              {[
                { value: statusCounts.draft, label: "草稿" },
                { value: statusCounts.ready, label: "待模拟" },
                { value: statusCounts.running, label: "运行中" },
                { value: statusCounts.completed, label: "已完成" },
                { value: statusCounts.queued + waitingCount, label: "排队中" },
                { value: statusCounts.failed, label: "失败/停止" },
              ].map((stat) => (
                <div key={stat.label}>
                  <div className="tf-metric-value">{stat.value}</div>
                  <div className="tf-caption tf-text-tertiary">{stat.label}</div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>

        <div ref={inputPanelRef} className="tf-mb-6">
          <SectionCard title="项目输入管理">
            <p className="tf-caption tf-text-secondary tf-mb-4">
              从本机任意盘符选择文件导入。上传不会改变任何方案；请在方案的“输入绑定”中显式选择资产。
            </p>
            <div className="tf-actions-bar tf-mb-4">
              <select
                value={uploadFamily}
                onChange={(event) => setUploadFamily(event.target.value)}
                aria-label="输入文件族"
                className="tf-select"
              >
                {INPUT_FAMILIES.map(({ id: family, label }) => (
                  <option key={family} value={family}>
                    {label}
                  </option>
                ))}
              </select>
              <Button variant="secondary" icon={<FolderOpen size={16} />} onClick={() => setShowFilePicker(true)}>
                从本机路径导入
              </Button>
            </div>
            {inputFiles.length === 0 ? (
              <div className="tf-empty-state tf-body tf-text-tertiary">
                暂无输入文件。请先导入 DEM 等基础数据。
              </div>
            ) : (
              <div className="tf-stack tf-gap-1">
                {inputFiles.map((file) => (
                  <div key={file.file_id} className="tf-list-item tf-list-item--static">
                    <div className="tf-min-w-0">
                      <div className="tf-body tf-font-medium">{file.name}</div>
                      <div className="tf-caption tf-text-tertiary">
                        {INPUT_FAMILY_LABELS[file.family] || file.family} · {(file.size / 1024).toFixed(1)} KB
                      </div>
                    </div>
                    <StatusBadge variant={file.status === "ready" ? "success" : file.status === "invalid" ? "error" : "warning"}>
                      {file.status === "ready" ? "就绪" : file.status}
                    </StatusBadge>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </div>

        <div className="tf-two-col-grid tf-mb-6">
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
              <div className="tf-stack tf-gap-1">
                <div className="tf-row tf-gap-1">
                  <StatusBadge variant="running" dot />
                  <span className="tf-body">{runningItem.scenario_name}</span>
                </div>
                <div className="tf-progress">
                  <div className="tf-progress-fill" style={{ width: `${runningItem.progress}%` }} />
                </div>
                <div className="tf-caption tf-text-tertiary">
                  进度 {runningItem.progress}% · 项目内串行
                </div>
              </div>
            ) : (
              <div className="tf-body tf-text-secondary">
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
            <div className="tf-metric-row">
              <div>
                <div className="tf-metric-value">{completedScenarios.length}</div>
                <div className="tf-caption tf-text-tertiary">已完成方案</div>
              </div>
              <div>
                <div className="tf-metric-value">{completedScenarios.reduce((sum, s) => sum + s.result_family_count, 0)}</div>
                <div className="tf-caption tf-text-tertiary">结果族总数</div>
              </div>
              <div>
                <div className="tf-metric-value">
                  {completedScenarios.length > 0
                    ? new Date(Math.max(...completedScenarios.map((scenario) => new Date(scenario.updated_at).getTime()))).toLocaleDateString("zh-CN")
                    : "—"}
                </div>
                <div className="tf-caption tf-text-tertiary">最近完成</div>
              </div>
            </div>
          </SectionCard>
        </div>

        <div className="tf-row tf-gap-2">
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

      {showFilePicker ? (
        <DirectoryPickerDialog
          mode="file"
          title="导入项目输入文件"
          description="从本机任意盘符选择 DEM、降雨等输入文件。"
          onCancel={() => setShowFilePicker(false)}
          onSelect={async (path) => {
            setShowFilePicker(false);
            try {
              await uploadInputFromPath(uploadFamily, path);
              addToast({ type: "success", message: `${INPUT_FAMILY_LABELS[uploadFamily] || "输入文件"}已导入` });
            } catch (error) {
              addToast({ type: "error", message: error instanceof Error ? error.message : "导入失败" });
            }
          }}
        />
      ) : null}
    </div>
  );
}
