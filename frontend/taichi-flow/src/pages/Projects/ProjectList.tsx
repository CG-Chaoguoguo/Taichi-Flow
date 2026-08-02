import { useEffect, useState } from "react";
import { FolderOpen, Plus, Upload, Clock, Search, MoreHorizontal } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { DirectoryPickerDialog } from "../../components/DirectoryPickerDialog";
import type { ProjectInfo } from "../../types";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function ProjectList() {
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
      if (dialogMode === "import") {
        await openProject(newPath);
      } else {
        await createProject(newName, newPath);
      }
      setShowCreate(false);
      setNewName("");
      setNewPath("");
      const list = await fetchProjectList();
      setProjects(list);
    } catch (err) {
      addToast({ type: "error", message: err instanceof Error ? err.message : dialogMode === "import" ? "导入项目失败" : "创建项目失败" });
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpen = async (path: string) => {
    try {
      await openProject(path);
    } catch (err) {
      addToast({ type: "error", message: err instanceof Error ? err.message : "打开项目失败" });
    }
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
    <div style={{ height: "100%", overflow: "auto", padding: "32px" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 className="tf-display" style={{ marginBottom: 8 }}>
              项目
            </h1>
            <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
              一个项目包含一套共享输入和多个参数方案，方案共享项目输入，仅修改计算参数。
            </p>
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            <Button icon={<Plus size={16} />} onClick={() => openProjectDialog("create")}>
              新建项目
            </Button>
            <Button variant="secondary" icon={<FolderOpen size={16} />} onClick={() => openProjectDialog("import")}>
              打开本地项目
            </Button>
            <Button variant="secondary" icon={<Upload size={16} />} onClick={() => openProjectDialog("import")}>
              导入兼容算例
            </Button>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            borderRadius: "var(--radius-large)",
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            marginBottom: 20,
            maxWidth: 480,
          }}
        >
          <Search size={16} color="var(--color-foreground-tertiary)" />
          <input
            type="text"
            placeholder="搜索项目名称或路径..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1,
              border: "none",
              background: "transparent",
              outline: "none",
              color: "var(--color-foreground)",
              fontSize: 14,
            }}
          />
        </div>

        {combined.length === 0 ? (
          <div
            style={{
              padding: 64,
              textAlign: "center",
              borderRadius: "var(--radius-xlarge)",
              border: "1px dashed var(--color-border-strong)",
              background: "var(--color-surface)",
            }}
          >
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: "50%",
                background: "var(--color-surface-tertiary)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 16px",
              }}
            >
              <FolderOpen size={32} color="var(--color-foreground-tertiary)" />
            </div>
            <h2 className="tf-title" style={{ marginBottom: 8 }}>
              暂无项目
            </h2>
            <p className="tf-body" style={{ color: "var(--color-foreground-secondary)", marginBottom: 24 }}>
              新建项目或打开本地项目，开始组织输入文件与参数方案。
            </p>
            <Button icon={<Plus size={16} />} onClick={() => openProjectDialog("create")}>
              新建项目
            </Button>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 16 }}>
            {combined.map((project) => (
              <div
                key={project.project_id}
                style={{
                  padding: 20,
                  borderRadius: "var(--radius-xlarge)",
                  border: `1px solid ${activeProject?.project_id === project.project_id ? "var(--color-brand)" : "var(--color-border)"}`,
                  background: "var(--color-surface)",
                  boxShadow: "var(--shadow-rest)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                  cursor: "pointer",
                  transition: "box-shadow 120ms ease, border-color 120ms ease",
                }}
                onClick={() => handleOpen(project.root_path)}
                onMouseEnter={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-rest)")}
              >
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <h3 className="tf-subtitle tf-ellipsis" style={{ marginBottom: 4 }}>
                      {project.name}
                    </h3>
                    <p className="tf-caption tf-ellipsis" style={{ color: "var(--color-foreground-tertiary)" }}>
                      {project.root_path}
                    </p>
                  </div>
                  {activeProject?.project_id === project.project_id && <StatusBadge variant="success">当前打开</StatusBadge>}
                </div>

                <div style={{ display: "flex", gap: 16 }}>
                  <div>
                    <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                      方案
                    </div>
                    <div className="tf-body" style={{ fontWeight: 600 }}>
                      —
                    </div>
                  </div>
                  <div>
                    <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                      输入版本
                    </div>
                    <div className="tf-body" style={{ fontWeight: 600 }}>
                      —
                    </div>
                  </div>
                  <div>
                    <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                      队列
                    </div>
                    <div className="tf-body" style={{ fontWeight: 600 }}>
                      未运行
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto" }}>
                  <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Clock size={12} />
                    {formatDate(project.updated_at)}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFromHistory(project.project_id);
                    }}
                    style={{ color: "var(--color-foreground-tertiary)", display: "flex", alignItems: "center" }}
                    title="从历史记录移除"
                    aria-label="从历史记录移除"
                  >
                    <MoreHorizontal size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {showCreate && (
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
            onClick={() => setShowCreate(false)}
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
                {dialogMode === "import" ? "打开或导入项目" : "新建项目"}
              </h2>
              <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
                {dialogMode === "create" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <label htmlFor="project-name" className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>项目名称（必填）</label>
                    <input
                      id="project-name"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="例如：2026 年山区洪水模拟"
                      aria-invalid={!newName.trim()}
                      aria-describedby={!newName.trim() ? "project-name-error" : undefined}
                      style={{ padding: "8px 12px", borderRadius: "var(--radius-large)", border: `1px solid ${newName.trim() ? "var(--color-border)" : "var(--color-error)"}`, background: "var(--color-bg-canvas)", color: "var(--color-foreground)" }}
                    />
                    {!newName.trim() && <span id="project-name-error" className="tf-caption" style={{ color: "var(--color-error)" }}>项目名称为必填项</span>}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <label htmlFor="project-root-path" className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>本地根目录（必填）</label>
                  <div style={{ display: "flex", alignItems: "stretch", gap: 8 }}>
                    <input
                      id="project-root-path"
                      value={newPath}
                      onChange={(e) => setNewPath(e.target.value)}
                      placeholder={dialogMode === "import" ? "C:\\TaichiFlowProjects\\existing-case" : "C:\\TaichiFlowProjects\\my-project"}
                      aria-invalid={!newPath.trim()}
                      aria-describedby={!newPath.trim() ? "project-root-error project-root-help" : "project-root-help"}
                      style={{ flex: 1, minWidth: 0, padding: "8px 12px", borderRadius: "var(--radius-large)", border: `1px solid ${newPath.trim() ? "var(--color-border)" : "var(--color-error)"}`, background: "var(--color-bg-canvas)", color: "var(--color-foreground)", fontFamily: "var(--font-mono)" }}
                    />
                    <Button type="button" variant="secondary" icon={<FolderOpen size={16} />} onClick={() => void handleChooseDirectory()} disabled={isSelectingDirectory}>
                      {isSelectingDirectory ? "正在打开…" : "选择目录"}
                    </Button>
                  </div>
                  <span id="project-root-help" className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>可手工输入，或浏览本机已挂载盘符；选择后仍需点击{dialogMode === "import" ? "打开并导入" : "创建"}。</span>
                  {!newPath.trim() && <span id="project-root-error" className="tf-caption" style={{ color: "var(--color-error)" }}>请选择或输入本地根目录</span>}
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
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
      </div>
    </div>
  );
}
