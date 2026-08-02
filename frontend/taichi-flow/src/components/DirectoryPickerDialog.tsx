import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, Folder, HardDrive, RefreshCw, RotateCcw } from "lucide-react";
import { systemApi } from "../api/taichiFlowAdapter";
import type { DirectoryListing, DirectoryLocation } from "../types";
import { Button } from "./Button";

type DirectoryPickerDialogProps = {
  initialPath?: string;
  onCancel: () => void;
  onSelect: (path: string) => void;
};

type Breadcrumb = { label: string; path: string };

function buildBreadcrumbs(currentPath: string | null, roots: DirectoryLocation[]): Breadcrumb[] {
  if (!currentPath) return [];
  const normalizedCurrent = currentPath.toLowerCase();
  const root = roots.find((item) => normalizedCurrent === item.path.toLowerCase() || normalizedCurrent.startsWith(`${item.path.replace(/[\\/]$/, "").toLowerCase()}\\`) || normalizedCurrent.startsWith(`${item.path.replace(/[\\/]$/, "").toLowerCase()}/`));
  if (!root) return [{ label: currentPath, path: currentPath }];

  const separator = root.path.includes("\\") || currentPath.includes("\\") ? "\\" : "/";
  const rootWithoutTrailingSeparator = root.path.replace(/[\\/]+$/, "");
  const remainder = currentPath.slice(root.path.length).replace(/^[\\/]+/, "");
  const breadcrumbs: Breadcrumb[] = [{ label: root.name || root.path, path: root.path }];
  let accumulated = rootWithoutTrailingSeparator;
  for (const segment of remainder.split(/[\\/]/).filter(Boolean)) {
    accumulated = accumulated ? `${accumulated}${separator}${segment}` : `${separator}${segment}`;
    breadcrumbs.push({ label: segment, path: accumulated });
  }
  return breadcrumbs;
}

export function DirectoryPickerDialog({ initialPath, onCancel, onSelect }: DirectoryPickerDialogProps) {
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const browse = useCallback(async (path?: string) => {
    setLoading(true);
    setError(null);
    try {
      setListing(await systemApi.directories(path));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取此目录");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void browse(initialPath?.trim() || undefined);
  }, [browse, initialPath]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  const breadcrumbs = useMemo(() => buildBreadcrumbs(listing?.current_path ?? null, listing?.roots ?? []), [listing]);

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 980, display: "flex", alignItems: "center", justifyContent: "center", padding: 24, background: "rgba(0,0,0,0.5)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="directory-picker-title"
        style={{ width: "min(680px, 100%)", maxHeight: "min(720px, calc(100vh - 48px))", display: "flex", flexDirection: "column", borderRadius: "var(--radius-xlarge)", border: "1px solid var(--color-border)", background: "var(--color-surface)", boxShadow: "var(--shadow-dialog)", overflow: "hidden" }}
      >
        <div style={{ padding: "20px 22px 14px", borderBottom: "1px solid var(--color-border)" }}>
          <h2 id="directory-picker-title" className="tf-title" style={{ marginBottom: 6 }}>选择本机目录</h2>
          <p className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>仅显示本机已挂载盘符和可访问目录，不读取或展示文件内容。</p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderBottom: "1px solid var(--color-border)", minHeight: 52 }}>
          <Button size="small" variant="ghost" icon={<HardDrive size={15} />} onClick={() => void browse()} aria-label="查看盘符">盘符</Button>
          <Button size="small" variant="ghost" icon={<RotateCcw size={15} />} onClick={() => void browse(listing?.parent_path || undefined)} disabled={!listing?.parent_path} aria-label="返回上级">上级</Button>
          <div aria-label="当前目录面包屑" style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", overflowX: "auto", gap: 2 }}>
            {breadcrumbs.length === 0 ? (
              <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>选择盘符</span>
            ) : breadcrumbs.map((crumb, index) => (
              <span key={crumb.path} style={{ display: "inline-flex", alignItems: "center", flexShrink: 0 }}>
                {index > 0 && <ChevronRight size={13} color="var(--color-foreground-tertiary)" />}
                <button type="button" onClick={() => void browse(crumb.path)} className="tf-caption" style={{ padding: "4px 6px", borderRadius: "var(--radius-small)", color: index === breadcrumbs.length - 1 ? "var(--color-foreground)" : "var(--color-brand)" }}>
                  {crumb.label}
                </button>
              </span>
            ))}
          </div>
          <Button size="small" variant="ghost" icon={<RefreshCw size={15} />} onClick={() => void browse(listing?.current_path || undefined)} aria-label="刷新目录">刷新</Button>
        </div>

        {listing?.current_path && (
          <code style={{ padding: "8px 16px", borderBottom: "1px solid var(--color-border)", color: "var(--color-foreground-secondary)", background: "var(--color-bg-canvas)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {listing.current_path}
          </code>
        )}

        <div style={{ minHeight: 260, maxHeight: 420, overflow: "auto", padding: 10 }} aria-live="polite">
          {loading ? (
            <div className="tf-body" style={{ padding: 36, textAlign: "center", color: "var(--color-foreground-secondary)" }}>正在读取目录…</div>
          ) : error ? (
            <div role="alert" style={{ padding: 28, textAlign: "center", color: "var(--color-error)" }}>
              <p className="tf-body" style={{ marginBottom: 12 }}>{error}</p>
              <Button size="small" variant="secondary" onClick={() => void browse(listing?.current_path || initialPath?.trim() || undefined)}>重试</Button>
            </div>
          ) : !listing?.current_path ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
              {listing?.roots.map((root) => (
                <button key={root.path} type="button" onClick={() => void browse(root.path)} aria-label={root.name || root.path} style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 52, padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: "var(--radius-large)", background: "var(--color-surface-secondary)", color: "var(--color-foreground)", textAlign: "left" }}>
                  <HardDrive size={19} color="var(--color-brand)" />
                  <span style={{ minWidth: 0 }}>
                    <span className="tf-body" style={{ display: "block" }}>{root.name || root.path}</span>
                    <span className="tf-caption" style={{ color: root.writable ? "var(--color-success)" : "var(--color-foreground-tertiary)" }}>{root.writable ? "可写" : "只读"}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : listing.directories.length === 0 ? (
            <div className="tf-body" style={{ padding: 36, textAlign: "center", color: "var(--color-foreground-tertiary)" }}>此目录下没有可浏览的子目录</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {listing.directories.map((directory) => (
                <button key={directory.path} type="button" onClick={() => void browse(directory.path)} aria-label={`打开 ${directory.name}`} style={{ width: "100%", minHeight: 40, padding: "7px 10px", display: "flex", alignItems: "center", gap: 10, borderRadius: "var(--radius-medium)", color: "var(--color-foreground)", textAlign: "left" }}>
                  <Folder size={17} color="var(--color-brand)" fill="var(--color-brand-bg-subtle)" />
                  <span className="tf-body" style={{ flex: 1 }}>{directory.name}</span>
                  <span className="tf-caption" style={{ color: directory.writable ? "var(--color-success)" : "var(--color-foreground-tertiary)" }}>{directory.writable ? "可写" : "只读"}</span>
                  <ChevronRight size={15} color="var(--color-foreground-tertiary)" />
                </button>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "14px 18px", borderTop: "1px solid var(--color-border)" }}>
          <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>{listing?.current_path ? "选择当前显示的文件夹" : "请先进入一个本地目录"}</span>
          <div style={{ display: "flex", gap: 10 }}>
            <Button variant="secondary" onClick={onCancel}>取消</Button>
            <Button variant="primary" disabled={!listing?.can_select || !listing.current_path || loading} onClick={() => listing?.current_path && onSelect(listing.current_path)}>选择此文件夹</Button>
          </div>
        </div>
      </section>
    </div>
  );
}
