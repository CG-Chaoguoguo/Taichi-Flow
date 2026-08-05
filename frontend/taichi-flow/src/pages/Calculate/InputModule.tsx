import { useRef } from "react";
import { Info } from "lucide-react";
import { AssetDeleteDialog } from "../../components/AssetDeleteDialog";
import { AssetListView } from "../../components/AssetListView";
import { AssetSelectionToolbar } from "../../components/AssetSelectionToolbar";
import type { InputFamilyFilter } from "../../constants/inputFamilies";
import { useProjectAssets } from "../../hooks/useProjectAssets";

export type InputModuleProps = {
  selectedFamily: InputFamilyFilter;
  onFocusLayer: (id: string) => void;
  readOnly?: boolean;
  compact?: boolean;
  focusedAssetId?: string | null;
};

export function InputModule({
  selectedFamily,
  onFocusLayer,
  readOnly = false,
  compact = false,
  focusedAssetId = null,
}: InputModuleProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const assets = useProjectAssets({ selectedFamily, focusedAssetId, readOnly });
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
    selectFile,
    toggleLayerVisibility,
    reorderLayer,
  } = assets;

  return (
    <div className={`tf-module-body tf-stack${compact ? " is-compact" : ""}`}>
      {!compact ? (
        <div className="tf-info-banner">
          <Info size={16} color="var(--color-info)" />
          <span className="tf-caption tf-text-secondary">
            {readOnly
              ? "未打开项目时仅可预览资产库；打开项目后可独立上传文件。"
              : isAll
                ? "这里是项目资产库，不会隐式改变任何方案。请按类型上传；方案在“输入绑定”页显式引用资产。"
                : `当前类型：${familyLabel}。上传只会收录为项目资产，不会自动绑定到当前方案。`}
          </span>
        </div>
      ) : null}

      <div className="tf-row tf-justify-between">
        <span className="tf-caption tf-text-secondary">{readyCount}/{familyFiles.length} 个文件就绪</span>
        {!selectionMode ? (
          <div className="tf-row tf-gap-2">
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              disabled={readOnly || isAll}
              onChange={async (event) => {
                const files = Array.from(event.target.files || []);
                await uploadFiles(files);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              className="tf-caption tf-link-button"
              disabled={readOnly || isAll}
              title={isAll ? "请先选择具体输入类型" : undefined}
              onClick={() => fileInput.current?.click()}
            >
              上传资产
            </button>
            <button
              type="button"
              className="tf-caption tf-link-button"
              disabled={readOnly || familyFiles.length === 0}
              onClick={() => setSelectionMode(true)}
            >
              删除文件
            </button>
          </div>
        ) : null}
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

      {familyFiles.length > 1 && !selectionMode && !compact ? (
        <div className="tf-caption tf-text-tertiary">拖拽左侧手柄调整图层顺序</div>
      ) : null}

      <AssetListView
        files={familyFiles}
        emptyMessage={isAll ? "项目资产库为空。" : "该类型暂无资产，请点击“上传资产”。"}
        selectedFileId={selectedFileId}
        selectionMode={selectionMode}
        selectedAssetIds={selectedAssetIds}
        layerVisibility={layerVisibility}
        readOnly={readOnly}
        dragId={dragId}
        dropId={dropId}
        compact={compact}
        onSelect={(file) => selectFile(file, onFocusLayer)}
        onToggleSelected={toggleSelected}
        onSelectionClick={(file, index, event) =>
          handleSelectionClick(
            file.file_id,
            index,
            { shiftKey: event.shiftKey, ctrlKey: event.ctrlKey, metaKey: event.metaKey },
            familyFiles,
          )
        }
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
