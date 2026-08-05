import { ArrowDownAZ, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { InputFile } from "../types";
import { sortAssetsByFilename } from "../utils/filenameSort";
import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";

export function AssetPickerDialog({
  open,
  title,
  family,
  assets,
  selectedAssetId,
  sortable = false,
  onSelect,
  onClose,
}: {
  open: boolean;
  title: string;
  family?: string;
  assets: InputFile[];
  selectedAssetId?: string | null;
  sortable?: boolean;
  onSelect: (asset: InputFile) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [sortEnabled, setSortEnabled] = useState(false);

  useEffect(() => {
    if (!open) {
      setSearch("");
      setSortEnabled(false);
    }
  }, [open]);

  const candidates = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = assets.filter((asset) => {
      if (family && asset.family !== family) return false;
      return !needle || `${asset.name} ${asset.sha256 || ""}`.toLowerCase().includes(needle);
    });
    return sortEnabled ? sortAssetsByFilename(filtered) : filtered;
  }, [assets, family, search, sortEnabled]);

  if (!open) return null;
  return (
    <div className="tf-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="tf-dialog tf-asset-picker"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="tf-dialog-header">
          <div>
            <div className="tf-subtitle">{title}</div>
            <div className="tf-caption tf-text-tertiary">只显示项目资产库中的有类型文件；选择后才会修改方案草稿。</div>
          </div>
          <Button variant="ghost" size="small" icon={<X size={16} />} aria-label="关闭资产选择器" onClick={onClose}>
            关闭
          </Button>
        </header>
        <div className="tf-dialog-body tf-stack">
          <label className="tf-search-box">
            <Search size={16} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按文件名或 SHA-256 搜索" />
          </label>
          <div className="tf-asset-picker-list">
            {candidates.length === 0 ? (
              <div className="tf-empty tf-body tf-text-tertiary">资产库中暂无匹配文件。请先在项目“输入”节点上传。</div>
            ) : (
              candidates.map((asset) => (
                <button
                  key={asset.file_id}
                  type="button"
                  className={`tf-asset-picker-item${selectedAssetId === asset.file_id ? " is-selected" : ""}`}
                  aria-label={`选择资产 ${asset.name}`}
                  onClick={() => {
                    onSelect(asset);
                    onClose();
                  }}
                >
                  <span className="tf-flex-1 tf-text-left">
                    <span className="tf-body tf-font-medium tf-ellipsis">{asset.name}</span>
                    <span className="tf-caption tf-text-tertiary tf-block">
                      {asset.raster_metadata?.cols && asset.raster_metadata?.rows
                        ? `${asset.raster_metadata.cols} × ${asset.raster_metadata.rows} · `
                        : ""}
                      {asset.sha256 ? asset.sha256.slice(0, 12) : "无哈希"}
                    </span>
                  </span>
                  <StatusBadge variant={asset.status === "ready" ? "success" : "warning"}>
                    {asset.status === "ready" ? "可用" : asset.status}
                  </StatusBadge>
                </button>
              ))
            )}
          </div>
        </div>
        {sortable ? (
          <footer className="tf-asset-picker-footer">
            <span className="tf-caption tf-text-secondary">共 {candidates.length} 项</span>
            <Button
              variant={sortEnabled ? "secondary" : "ghost"}
              size="small"
              icon={<ArrowDownAZ size={14} />}
              aria-pressed={sortEnabled}
              aria-label={sortEnabled ? "取消按文件名排序" : "按文件名排序"}
              onClick={() => setSortEnabled((current) => !current)}
            >
              {sortEnabled ? "已按文件名排序" : "按文件名排序"}
            </Button>
          </footer>
        ) : null}
      </section>
    </div>
  );
}
