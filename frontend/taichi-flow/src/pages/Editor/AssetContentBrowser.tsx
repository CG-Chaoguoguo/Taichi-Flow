import { useMemo, useRef, useState, type MouseEvent } from "react";
import { FolderOpen, Grid2x2, LayoutList, Search, Upload } from "lucide-react";
import { AssetDeleteDialog } from "../../components/AssetDeleteDialog";
import { AssetGridView } from "../../components/AssetGridView";
import { AssetListView } from "../../components/AssetListView";
import { AssetSelectionToolbar } from "../../components/AssetSelectionToolbar";
import { Button } from "../../components/Button";
import { FilenameSortIconButton } from "../../components/FilenameSortIconButton";
import { IconButton } from "../../components/IconButton";
import {
  CollapsedPaneRail,
  PanelCollapseButton,
  ResizablePane,
  ResizablePaneGroup,
  ResizeHandle,
} from "../../components/layout/ResizablePaneGroup";
import {
  ALL_INPUT_FAMILY,
  INPUT_FAMILIES,
  INPUT_FAMILY_LABELS,
  type InputFamilyFilter,
} from "../../constants/inputFamilies";
import { useProjectAssets } from "../../hooks/useProjectAssets";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { InputFile } from "../../types";
import { sortAssetsByFilename } from "../../utils/filenameSort";

type AssetContentBrowserProps = {
  focusedAssetId?: string | null;
  onFocusAsset: (file: InputFile) => void;
  assetFamiliesCollapsed?: boolean;
  onToggleAssetFamilies?: () => void;
  assetFamilyPx?: number;
  onAssetLayoutChanged?: (familyPx: number, isUserInteraction: boolean) => void;
};

export function AssetContentBrowser({
  focusedAssetId = null,
  onFocusAsset,
  assetFamiliesCollapsed = false,
  onToggleAssetFamilies,
  assetFamilyPx = 160,
  onAssetLayoutChanged,
}: AssetContentBrowserProps) {
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const setInputFamily = useTaichiFlowStore((state) => state.setInputFamily);
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const selectedFamily: InputFamilyFilter = editorSelection?.kind === "input"
    ? editorSelection.family
    : ALL_INPUT_FAMILY;
  const [viewMode, setViewMode] = useState<"list" | "grid">("grid");
  const [search, setSearch] = useState("");
  const [sortByFilename, setSortByFilename] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const assets = useProjectAssets({ selectedFamily, focusedAssetId, readOnly: false });
  const {
    familyFiles,
    selectableFiles,
    readyCount,
    familyLabel,
    isAll,
    layerVisibility,
    selectedFileId,
    selectedAssetIds,
    setSelectedAssetIds,
    selectionMode,
    setSelectionMode,
    deletePreview,
    setDeletePreview,
    deleting,
    dragId,
    setDragId,
    dropId,
    setDropId,
    selectedCount,
    allSelected,
    partiallySelected,
    toggleSelected,
    handleSelectionClick,
    exitSelection,
    reviewDelete,
    confirmDelete,
    uploadFiles,
    toggleLayerVisibility,
    reorderLayer,
  } = assets;

  const filteredFiles = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return familyFiles;
    return familyFiles.filter((file) => {
      const familyLabelText = INPUT_FAMILY_LABELS[file.family] || file.family;
      return file.name.toLowerCase().includes(query) || familyLabelText.toLowerCase().includes(query);
    });
  }, [familyFiles, search]);

  const displayedFiles = useMemo(
    () => (sortByFilename ? sortAssetsByFilename(filteredFiles) : filteredFiles),
    [filteredFiles, sortByFilename],
  );

  const familyCounts = useMemo(() => {
    const counts: Record<string, number> = { [ALL_INPUT_FAMILY]: inputFiles.length };
    for (const family of INPUT_FAMILIES) {
      counts[family.id] = inputFiles.filter((file) => file.family === family.id).length;
    }
    return counts;
  }, [inputFiles]);

  const handleSelectFamily = (family: InputFamilyFilter) => {
    setInputFamily(family);
    setSearch("");
  };

  const handleSelectFile = (file: InputFile) => {
    onFocusAsset(file);
  };

  const handleAssetSelectionClick = (file: InputFile, index: number, event: MouseEvent) => {
    handleSelectionClick(
      file.file_id,
      index,
      { shiftKey: event.shiftKey, ctrlKey: event.ctrlKey, metaKey: event.metaKey },
      displayedFiles,
    );
  };

  return (
    <div className="tf-content-browser" aria-label="资产管理">
      <ResizablePaneGroup
        id="asset-browser"
        orientation="horizontal"
        className="tf-content-browser-layout"
        onLayoutChanged={(layout, meta, groupSizePx) => {
          if (!onAssetLayoutChanged || !groupSizePx) return;
          const familyPercent = layout["asset-families"] || 0;
          onAssetLayoutChanged(Math.round((familyPercent / 100) * groupSizePx), meta.isUserInteraction);
        }}
      >
        <ResizablePane
          id="asset-families"
          defaultSize={assetFamilyPx}
          minSize={128}
          maxSize={280}
          collapsed={assetFamiliesCollapsed}
          collapsedSize={40}
          groupResizeBehavior="preserve-pixel-size"
          className="tf-content-browser-sidebar-pane"
        >
          {assetFamiliesCollapsed ? (
            <CollapsedPaneRail label="资产分类" direction="left" onExpand={onToggleAssetFamilies} />
          ) : (
            <aside className="tf-content-browser-sidebar" aria-label="资产类型">
              <div className="tf-content-browser-sidebar-header">
                <span className="tf-caption tf-font-semibold tf-text-secondary">资产类型</span>
                {onToggleAssetFamilies ? (
                  <PanelCollapseButton label="资产分类" collapsed={false} direction="left" onToggle={onToggleAssetFamilies} />
                ) : null}
              </div>
              <button
                type="button"
                className={`tf-content-browser-family${selectedFamily === ALL_INPUT_FAMILY ? " is-active" : ""}`}
                onClick={() => handleSelectFamily(ALL_INPUT_FAMILY)}
              >
                <FolderOpen size={14} />
                <span className="tf-flex-1 tf-ellipsis">全部文件</span>
                <span className="tf-caption tf-text-tertiary">{familyCounts[ALL_INPUT_FAMILY] || 0}</span>
              </button>
              {INPUT_FAMILIES.map((family) => (
                <button
                  key={family.id}
                  type="button"
                  className={`tf-content-browser-family${selectedFamily === family.id ? " is-active" : ""}`}
                  onClick={() => handleSelectFamily(family.id)}
                >
                  <span className="tf-flex-1 tf-ellipsis">{family.label}</span>
                  <span className="tf-caption tf-text-tertiary">{familyCounts[family.id] || 0}</span>
                </button>
              ))}
            </aside>
          )}
        </ResizablePane>
        <ResizeHandle
          id="asset-families-splitter"
          leadingPanelId="asset-families"
          label="资产分类与内容之间的调整条"
          leadingMinSize={128}
          leadingMaxSize={280}
          onToggleCollapse={onToggleAssetFamilies}
        />
        <ResizablePane
          id="asset-content"
          minSize={360}
          className="tf-content-browser-main-pane"
          groupResizeBehavior="preserve-relative-size"
        >
          <div className="tf-content-browser-main">
            <div className="tf-content-browser-toolbar">
              <div className="tf-row tf-gap-2 tf-flex-1">
                <div className="tf-content-browser-search">
                  <Search size={14} />
                  <input
                    type="search"
                    value={search}
                    placeholder="搜索资产名称或类型…"
                    aria-label="搜索资产"
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </div>
                <FilenameSortIconButton
                  active={sortByFilename}
                  onToggle={() => setSortByFilename((current) => !current)}
                />
                <span className="tf-caption tf-text-secondary tf-content-browser-count">
                  {readyCount}/{familyFiles.length} 就绪 · {isAll ? "全部" : familyLabel}
                </span>
              </div>
              <div className="tf-row tf-gap-1">
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  disabled={isAll}
                  onChange={async (event) => {
                    await uploadFiles(Array.from(event.target.files || []));
                    event.target.value = "";
                  }}
                />
                <Button
                  size="small"
                  variant="secondary"
                  icon={<Upload size={14} />}
                  disabled={isAll}
                  title={isAll ? "请先选择具体输入类型" : `上传${familyLabel}`}
                  onClick={() => fileInput.current?.click()}
                >
                  上传
                </Button>
                {!selectionMode ? (
                  <Button
                    size="small"
                    variant="ghost"
                    disabled={familyFiles.length === 0}
                    onClick={() => setSelectionMode(true)}
                  >
                    删除
                  </Button>
                ) : null}
                <IconButton
                  size="small"
                  icon={<LayoutList size={14} />}
                  label="列表视图"
                  active={viewMode === "list"}
                  onClick={() => setViewMode("list")}
                />
                <IconButton
                  size="small"
                  icon={<Grid2x2 size={14} />}
                  label="网格视图"
                  active={viewMode === "grid"}
                  onClick={() => setViewMode("grid")}
                />
              </div>
            </div>

            {selectionMode ? (
              <AssetSelectionToolbar
                selectedCount={selectedCount}
                selectableCount={selectableFiles.length}
                allSelected={allSelected}
                partiallySelected={partiallySelected}
                onToggleAll={() => setSelectedAssetIds(new Set(allSelected ? [] : selectableFiles.map((file) => file.file_id)))}
                onDelete={() => void reviewDelete()}
                onCancel={exitSelection}
              />
            ) : null}

            <div className="tf-content-browser-body">
              {viewMode === "grid" ? (
                <AssetGridView
                  files={displayedFiles}
                  emptyMessage={isAll ? "项目资产库为空。" : "该类型暂无资产，请点击“上传”。"}
                  selectedFileId={selectedFileId}
                  layerVisibility={layerVisibility}
                  selectionMode={selectionMode}
                  selectedAssetIds={selectedAssetIds}
                  onSelect={handleSelectFile}
                  onSelectionClick={handleAssetSelectionClick}
                  onToggleVisibility={toggleLayerVisibility}
                />
              ) : (
                <AssetListView
                  files={displayedFiles}
                  emptyMessage={isAll ? "项目资产库为空。" : "该类型暂无资产，请点击“上传”。"}
                  selectedFileId={selectedFileId}
                  selectionMode={selectionMode}
                  selectedAssetIds={selectedAssetIds}
                  layerVisibility={layerVisibility}
                  reorderable={!sortByFilename}
                  dragId={dragId}
                  dropId={dropId}
                  compact
                  onSelect={handleSelectFile}
                  onToggleSelected={toggleSelected}
                  onSelectionClick={handleAssetSelectionClick}
                  onToggleVisibility={toggleLayerVisibility}
                  onReorder={reorderLayer}
                  onDragStart={setDragId}
                  onDragOver={setDropId}
                  onDragLeave={() => setDropId(null)}
                  onDragEnd={() => {
                    setDragId(null);
                    setDropId(null);
                  }}
                />
              )}
            </div>
          </div>
        </ResizablePane>
      </ResizablePaneGroup>

      <AssetDeleteDialog
        open={deletePreview !== null}
        preview={deletePreview}
        busy={deleting}
        onClose={() => !deleting && setDeletePreview(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
