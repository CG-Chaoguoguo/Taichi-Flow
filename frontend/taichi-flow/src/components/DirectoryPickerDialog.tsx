import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, FileText, Folder, HardDrive, RefreshCw, RotateCcw } from "lucide-react";
import { systemApi } from "../api/taichiFlowAdapter";
import type { DirectoryListing, DirectoryLocation } from "../types";
import { Button } from "./Button";

type DirectoryPickerDialogProps = {
  initialPath?: string;
  mode?: "directory" | "file";
  title?: string;
  description?: string;
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

export function DirectoryPickerDialog({
  initialPath,
  mode = "directory",
  title,
  description,
  onCancel,
  onSelect,
}: DirectoryPickerDialogProps) {
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const isFileMode = mode === "file";

  const browse = useCallback(async (path?: string) => {
    setLoading(true);
    setError(null);
    setSelectedFile(null);
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
  const files = listing?.files || [];
  const canConfirm = isFileMode ? Boolean(selectedFile) : Boolean(listing?.can_select && listing.current_path);

  return (
    <div
      className="tf-dialog-overlay tf-smoke"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section role="dialog" aria-modal="true" aria-labelledby="directory-picker-title" className="tf-dialog tf-acrylic">
        <div className="tf-dialog-header">
          <h2 id="directory-picker-title" className="tf-title tf-mb-2">
            {title || (isFileMode ? "选择本机文件" : "选择本机目录")}
          </h2>
          <p className="tf-caption tf-text-secondary">
            {description || (isFileMode ? "浏览本机盘符并选择要导入的文件。" : "仅显示本机已挂载盘符和可访问目录。")}
          </p>
        </div>

        <div className="tf-dialog-toolbar">
          <Button size="small" variant="ghost" icon={<HardDrive size={15} />} onClick={() => void browse()} aria-label="查看盘符">盘符</Button>
          <Button size="small" variant="ghost" icon={<RotateCcw size={15} />} onClick={() => void browse(listing?.parent_path || undefined)} disabled={!listing?.parent_path} aria-label="返回上级">上级</Button>
          <div aria-label="当前目录面包屑" className="tf-dialog-breadcrumbs">
            {breadcrumbs.length === 0 ? (
              <span className="tf-caption tf-text-tertiary">选择盘符</span>
            ) : breadcrumbs.map((crumb, index) => (
              <span key={crumb.path} className="tf-row tf-gap-1">
                {index > 0 && <ChevronRight size={13} className="tf-text-tertiary" />}
                <button
                  type="button"
                  onClick={() => void browse(crumb.path)}
                  className={`tf-caption tf-link-button tf-breadcrumb-btn${index === breadcrumbs.length - 1 ? " is-current" : ""}`}
                >
                  {crumb.label}
                </button>
              </span>
            ))}
          </div>
          <Button size="small" variant="ghost" icon={<RefreshCw size={15} />} onClick={() => void browse(listing?.current_path || undefined)} aria-label="刷新目录">刷新</Button>
        </div>

        {listing?.current_path && (
          <code className="tf-mono tf-dialog-path">
            {selectedFile || listing.current_path}
          </code>
        )}

        <div className="tf-dialog-body" aria-live="polite">
          {loading ? (
            <div className="tf-empty tf-body">正在读取目录…</div>
          ) : error ? (
            <div role="alert" className="tf-empty tf-text-error">
              <p className="tf-body tf-mb-3">{error}</p>
              <Button size="small" variant="secondary" onClick={() => void browse(listing?.current_path || initialPath?.trim() || undefined)}>重试</Button>
            </div>
          ) : !listing?.current_path ? (
            <div className="tf-metric-grid">
              {listing?.roots.map((root) => (
                <button key={root.path} type="button" onClick={() => void browse(root.path)} aria-label={root.name || root.path} className="tf-metric-card tf-drive-card">
                  <HardDrive size={19} className="tf-text-brand" />
                  <span className="tf-flex-1">
                    <span className="tf-body tf-block">{root.name || root.path}</span>
                    <span className={`tf-caption ${root.writable ? "tf-text-success" : "tf-text-tertiary"}`}>{root.writable ? "可写" : "只读"}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : listing.directories.length === 0 && files.length === 0 ? (
            <div className="tf-empty tf-body tf-text-tertiary">此目录为空</div>
          ) : (
            <div className="tf-stack tf-gap-1">
              {listing.directories.map((directory) => (
                <button key={directory.path} type="button" onClick={() => void browse(directory.path)} aria-label={`打开 ${directory.name}`} className="tf-list-item">
                  <Folder size={17} className="tf-text-brand" />
                  <span className="tf-body tf-flex-1">{directory.name}</span>
                  <ChevronRight size={15} className="tf-text-tertiary" />
                </button>
              ))}
              {isFileMode
                ? files.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() => setSelectedFile(file.path)}
                      aria-label={`选择 ${file.name}`}
                      className={`tf-list-item${selectedFile === file.path ? " selected" : ""}`}
                    >
                      <FileText size={17} className="tf-text-secondary" />
                      <span className="tf-body tf-flex-1">{file.name}</span>
                      <span className="tf-caption tf-text-tertiary">
                        {typeof file.size === "number" ? `${(file.size / 1024).toFixed(1)} KB` : ""}
                      </span>
                    </button>
                  ))
                : null}
            </div>
          )}
        </div>

        <div className="tf-dialog-footer">
          <span className="tf-caption tf-text-tertiary">
            {isFileMode ? (selectedFile ? "已选择文件" : "请选择一个文件") : listing?.current_path ? "选择当前显示的文件夹" : "请先进入一个本地目录"}
          </span>
          <div className="tf-row">
            <Button variant="secondary" onClick={onCancel}>取消</Button>
            <Button
              variant="primary"
              disabled={!canConfirm || loading}
              onClick={() => {
                if (isFileMode && selectedFile) onSelect(selectedFile);
                else if (!isFileMode && listing?.current_path) onSelect(listing.current_path);
              }}
            >
              {isFileMode ? "选择此文件" : "选择此文件夹"}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
