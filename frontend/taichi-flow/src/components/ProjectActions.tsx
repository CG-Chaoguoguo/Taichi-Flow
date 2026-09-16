import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, ListMinus, Trash2 } from "lucide-react";
import { IconButton } from "./IconButton";
import { Button } from "./Button";
import { ConfirmDialog } from "./ConfirmDialog";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { ProjectDeleteMode, ProjectDeletePreview, ProjectInfo } from "../types";

export function ProjectActions({ project, onChanged }: { project: ProjectInfo; onChanged: () => Promise<void> }) {
  const [menu, setMenu] = useState(false);
  const [mode, setMode] = useState<ProjectDeleteMode | null>(null);
  const [preview, setPreview] = useState<ProjectDeletePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const previewDelete = useTaichiFlowStore((state) => state.previewProjectDelete);
  const deleteProject = useTaichiFlowStore((state) => state.deleteProject);
  const closeMenu = () => { setMenu(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!menu) return;
    root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const outside = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [menu]);
  const load = async (next: ProjectDeleteMode) => {
    setMode(next); setPreview(null); setError(""); setBusy(true); closeMenu();
    try { setPreview(await previewDelete(project.project_id, next)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法加载删除预览"); }
    finally { setBusy(false); }
  };
  return <div ref={root} className="tf-project-actions" onClick={(event) => event.stopPropagation()}>
    <IconButton icon={<MoreHorizontal size={16} />} label={`项目操作：${project.name}`} size="small"
      aria-haspopup="menu" aria-expanded={menu} onClick={(event) => { trigger.current = event.currentTarget; setMenu((open) => !open); }} />
    {menu && <div role="menu" aria-label={`${project.name}的操作`} className="tf-project-menu" onKeyDown={(event) => {
      const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      if (event.key === "Escape") { event.preventDefault(); closeMenu(); }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; items[next]?.focus();
      }
      if (event.key === "Tab") setMenu(false);
    }}>
      <button role="menuitem" onClick={() => void load("unregister")}><ListMinus size={16} />从列表移除</button>
      <button role="menuitem" onClick={() => void load("permanent")}><Trash2 size={16} />{project.deletion_status ? "重试彻底删除" : "彻底删除项目"}</button>
    </div>}
    {mode && <ConfirmDialog title={mode === "permanent" ? "彻底删除项目" : "从列表移除项目"} busy={busy} onClose={() => { setMode(null); trigger.current?.focus(); }}>
      <p className="tf-body">{mode === "permanent" ? `确定彻底删除“${project.name}”及其目录内所有文件？此操作不可撤销。` : `确定从列表移除“${project.name}”？本地文件将保留。`}</p>
      {busy && !preview && <p role="status">正在核验项目与任务状态…</p>}
      {preview?.retry && <p className="tf-caption tf-text-secondary">将继续上次未完成的删除。</p>}
      {preview?.blocked_reasons.map((reason) => <p role="alert" key={reason} className="tf-text-error">{reason}</p>)}
      {error && <p role="alert" className="tf-text-error">{error}</p>}
      <div className="tf-dialog-footer">
        <Button variant="secondary" disabled={busy} onClick={() => setMode(null)}>取消</Button>
        <Button variant={mode === "permanent" ? "danger" : "primary"} disabled={busy || (!preview && !error)} onClick={async () => {
          if (error || !preview?.allowed) { await load(mode); return; }
          if (!preview) return; setBusy(true); setError("");
          try { await deleteProject(preview, preview.name); setMode(null); await onChanged(); }
          catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败，请重新核验后重试"); await onChanged(); }
          finally { setBusy(false); }
        }}>{busy ? "处理中…" : error || (preview && !preview.allowed) ? "重试" : "确认"}</Button>
      </div>
    </ConfirmDialog>}
  </div>;
}
