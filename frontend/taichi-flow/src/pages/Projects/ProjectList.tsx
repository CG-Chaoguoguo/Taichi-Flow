import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FolderOpen, Plus, Upload, Clock, Search, MoreHorizontal } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";
import { StatusBadge } from "../../components/StatusBadge";
import { DirectoryPickerDialog } from "../../components/DirectoryPickerDialog";
import { LegacyCaseImportDialog } from "../../components/LegacyCaseImportDialog";
import type { CaseImportCommitResult, ProjectInfo } from "../../types";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function ProjectList() {
  const navigate = useNavigate();
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const projectHistory = useTaichiFlowStore((state) => state.projectHistory);
  const fetchProjectList = useTaichiFlowStore((state) => state.fetchProjectList);
  const createProject = useTaichiFlowStore((state) => state.createProject);
  const openProject = useTaichiFlowStore((state) => state.openProject);
  const removeFromHistory = useTaichiFlowStore((state) => state.removeFromHistory);
  const addToast = useTaichiFlowStore((state) => state.addToast);

  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "import">("create");
  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSelectingDirectory, setIsSelectingDirectory] = useState(false);
  const [showDirectoryPicker, setShowDirectoryPicker] = useState(false);
  const [showCaseImport, setShowCaseImport] = useState(false);

  useEffect(() => {
    fetchProjectList().then(setProjects).catch(() => setProjects([]));
  }, [fetchProjectList]);

  const combined = [
    ...projects,
    ...projectHistory.filter((h) => !projects.find((p) => p.project_id === h.project_id)),
  ].filter((p) => p.name.toLowerCase().includes(search.toLowerCase()) || p.root_path.toLowerCase().includes(search.toLowerCase()));

  const handleCreate = async () => {
    if (!newPath.trim() || (dialogMode === "create" && !newName.trim())) return;
    setIsLoading(true);
    try {
      const project = dialogMode === "import" ? await openProject(newPath) : await createProject(newName, newPath);
      setShowCreate(false);
      setNewName("");
      setNewPath("");
      const list = await fetchProjectList();
      setProjects(list);
      navigate(`/launch/${project.project_id}`);
    } catch (err) {
      addToast({ type: "error", message: err instanceof Error ? err.message : dialogMode === "import" ? "导入项目失败" : "创建项目失败" });
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpen = (project: ProjectInfo) => {
    navigate(`/launch/${project.project_id}`);
  };

  const openProjectDialog = (mode: "create" | "import") => {
    setDialogMode(mode);
    setNewName("");
    setNewPath("");
    setShowCreate(true);
  };

  const handleChooseDirectory = async () => {
    const nativePicker = window.taichiFlowDesktop?.selectDirectory;
    if (!nativePicker) {
      setShowDirectoryPicker(true);
      return;
    }
    setIsSelectingDirectory(true);
    try {
      const result = await nativePicker({ defaultPath: newPath.trim() || undefined });
      if (!result.canceled && result.path) setNewPath(result.path);
    } catch (err) {
      addToast({ type: "error", message: err instanceof Error ? err.message : "无法打开系统目录窗口" });
    } finally {
      setIsSelectingDirectory(false);
    }
  };

  return (
    <div className="tf-page">
      <div className="tf-page-content tf-animate-in">
        <div className="tf-page-header">
          <div>
            <h1 className="tf-display tf-mb-2">项目</h1>
            <p className="tf-body tf-text-secondary">
              选择或创建项目后将进入一体化编辑器。方案、参数、队列与导出均在项目内完成。
            </p>
          </div>
          <div className="tf-actions-bar">
            <Button icon={<Plus size={16} />} onClick={() => openProjectDialog("create")}>
              新建项目
            </Button>
            <Button variant="secondary" icon={<FolderOpen size={16} />} onClick={() => openProjectDialog("import")}>
              打开本地项目
            </Button>
            <Button variant="secondary" icon={<Upload size={16} />} onClick={() => setShowCaseImport(true)}>
              导入兼容算例
            </Button>
          </div>
        </div>

        <div className="tf-search-box tf-search-box--medium">
          <Search size={16} className="tf-text-tertiary" />
          <input
            type="text"
            placeholder="搜索项目名称或路径..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {combined.length === 0 ? (
          <div className="tf-empty-state">
            <div className="tf-empty-icon">
              <FolderOpen size={32} className="tf-text-tertiary" />
            </div>
            <h2 className="tf-title tf-mb-2">暂无项目</h2>
            <p className="tf-body tf-text-secondary tf-mb-6">
              新建项目或打开本地项目，开始组织输入文件与参数方案。
            </p>
            <Button icon={<Plus size={16} />} onClick={() => openProjectDialog("create")}>
              新建项目
            </Button>
          </div>
        ) : (
          <div className="tf-project-grid">
            {combined.map((project) => (
              <div
                key={project.project_id}
                className={`tf-project-card${activeProject?.project_id === project.project_id ? " active" : ""}`}
                onClick={() => handleOpen(project)}
              >
                <div className="tf-row tf-justify-between tf-gap-2">
                  <div className="tf-min-w-0">
                    <h3 className="tf-subtitle tf-ellipsis tf-mb-2">{project.name}</h3>
                    <p className="tf-caption tf-ellipsis tf-text-tertiary">{project.root_path}</p>
                  </div>
                  {activeProject?.project_id === project.project_id && <StatusBadge variant="success">最近打开</StatusBadge>}
                </div>

                <div className="tf-metric-row">
                  <div>
                    <div className="tf-caption tf-text-tertiary">方案</div>
                    <div className="tf-body tf-font-semibold">—</div>
                  </div>
                  <div>
                    <div className="tf-caption tf-text-tertiary">输入版本</div>
                    <div className="tf-body tf-font-semibold">—</div>
                  </div>
                  <div>
                    <div className="tf-caption tf-text-tertiary">队列</div>
                    <div className="tf-body tf-font-semibold">未运行</div>
                  </div>
                </div>

                <div className="tf-project-card-footer">
                  <span className="tf-caption tf-text-tertiary tf-row tf-gap-1">
                    <Clock size={12} />
                    {formatDate(project.updated_at)}
                  </span>
                  <IconButton
                    size="small"
                    icon={<MoreHorizontal size={16} />}
                    label="从历史记录移除"
                    className="tf-text-tertiary"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFromHistory(project.project_id);
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {showCreate && (
          <div className="tf-dialog-overlay" onClick={() => setShowCreate(false)}>
            <div className="tf-dialog tf-dialog-narrow" onClick={(e) => e.stopPropagation()}>
              <h2 className="tf-title tf-mb-4">{dialogMode === "import" ? "打开或导入项目" : "新建项目"}</h2>
              <div className="tf-form-stack">
                {dialogMode === "create" && (
                  <div className="tf-form-field">
                    <label htmlFor="project-name" className="tf-caption tf-text-secondary">
                      项目名称（必填）
                    </label>
                    <input
                      id="project-name"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="例如：2026 年山区洪水模拟"
                      aria-invalid={!newName.trim()}
                      aria-describedby={!newName.trim() ? "project-name-error" : undefined}
                      className={`tf-input tf-full-width${!newName.trim() ? " is-invalid" : ""}`}
                    />
                    {!newName.trim() && (
                      <span id="project-name-error" className="tf-caption tf-text-error">
                        项目名称为必填项
                      </span>
                    )}
                  </div>
                )}
                <div className="tf-form-field">
                  <label htmlFor="project-root-path" className="tf-caption tf-text-secondary">
                    本地根目录（必填）
                  </label>
                  <div className="tf-input-row">
                    <input
                      id="project-root-path"
                      value={newPath}
                      onChange={(e) => setNewPath(e.target.value)}
                      placeholder={dialogMode === "import" ? "C:\\TaichiFlowProjects\\existing-case" : "C:\\TaichiFlowProjects\\my-project"}
                      aria-invalid={!newPath.trim()}
                      aria-describedby={!newPath.trim() ? "project-root-error project-root-help" : "project-root-help"}
                      className={`tf-input tf-mono tf-flex-1${!newPath.trim() ? " is-invalid" : ""}`}
                    />
                    <Button type="button" variant="secondary" icon={<FolderOpen size={16} />} onClick={() => void handleChooseDirectory()} disabled={isSelectingDirectory}>
                      {isSelectingDirectory ? "正在打开…" : "选择目录"}
                    </Button>
                  </div>
                  <span id="project-root-help" className="tf-caption tf-text-tertiary">
                    可手工输入，或浏览本机已挂载盘符；选择后仍需点击{dialogMode === "import" ? "打开并导入" : "创建"}。
                  </span>
                  {!newPath.trim() && (
                    <span id="project-root-error" className="tf-caption tf-text-error">
                      请选择或输入本地根目录
                    </span>
                  )}
                </div>
              </div>
              <div className="tf-row tf-justify-end tf-gap-2">
                <Button variant="secondary" onClick={() => setShowCreate(false)}>
                  取消
                </Button>
                <Button onClick={handleCreate} disabled={isLoading || !newPath.trim() || (dialogMode === "create" && !newName.trim())}>
                  {isLoading ? "处理中..." : dialogMode === "import" ? "打开并导入" : "创建"}
                </Button>
              </div>
            </div>
          </div>
        )}
        {showDirectoryPicker && (
          <DirectoryPickerDialog
            initialPath={newPath}
            onCancel={() => setShowDirectoryPicker(false)}
            onSelect={(path) => {
              setNewPath(path);
              setShowDirectoryPicker(false);
            }}
          />
        )}
        {showCaseImport ? (
          <LegacyCaseImportDialog
            onClose={() => setShowCaseImport(false)}
            onCommitted={async (result: CaseImportCommitResult) => {
              setShowCaseImport(false);
              await openProject(result.project.root_path);
              const list = await fetchProjectList();
              setProjects(list);
              navigate(`/launch/${result.project.project_id}`);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}
