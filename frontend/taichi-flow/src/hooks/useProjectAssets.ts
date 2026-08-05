import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ALL_INPUT_FAMILY, INPUT_FAMILY_LABELS, type InputFamilyFilter } from "../constants/inputFamilies";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { AssetDeletePreview, InputFile } from "../types";

export type UseProjectAssetsOptions = {
  selectedFamily: InputFamilyFilter;
  focusedAssetId?: string | null;
  readOnly?: boolean;
};

export type SelectionClickModifiers = {
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
};

function isSelectableFile(file: InputFile): boolean {
  return file.deletable !== false && !file.runtime_lock?.locked;
}

export function useProjectAssets({ selectedFamily, focusedAssetId = null, readOnly = false }: UseProjectAssetsOptions) {
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const layerVisibility = useTaichiFlowStore((state) => state.layerVisibility);
  const layerOrder = useTaichiFlowStore((state) => state.layerOrder);
  const fetchInputFiles = useTaichiFlowStore((state) => state.fetchInputFiles);
  const uploadInputs = useTaichiFlowStore((state) => state.uploadInputs);
  const previewInputDeletion = useTaichiFlowStore((state) => state.previewInputDeletion);
  const deleteInputFiles = useTaichiFlowStore((state) => state.deleteInputFiles);
  const toggleLayerVisibility = useTaichiFlowStore((state) => state.toggleLayerVisibility);
  const reorderLayer = useTaichiFlowStore((state) => state.reorderLayer);
  const addToast = useTaichiFlowStore((state) => state.addToast);

  const [selectedFileId, setSelectedFileId] = useState<string | null>(focusedAssetId);
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(() => new Set());
  const [selectionMode, setSelectionMode] = useState(false);
  const selectionAnchorIndexRef = useRef<number | null>(null);
  const [deletePreview, setDeletePreview] = useState<AssetDeletePreview | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropId, setDropId] = useState<string | null>(null);

  const isAll = selectedFamily === ALL_INPUT_FAMILY;
  const familyFiles = useMemo(() => {
    const filtered = isAll ? inputFiles : inputFiles.filter((file) => file.family === selectedFamily);
    const orderIndex = new Map(layerOrder.map((id, index) => [id, index]));
    return [...filtered].sort((a, b) => (orderIndex.get(a.file_id) ?? 0) - (orderIndex.get(b.file_id) ?? 0));
  }, [inputFiles, selectedFamily, isAll, layerOrder]);

  const selectableFiles = useMemo(
    () => familyFiles.filter((file) => isSelectableFile(file)),
    [familyFiles],
  );
  const readyCount = familyFiles.filter((file) => file.status === "ready").length;
  const familyLabel = INPUT_FAMILY_LABELS[selectedFamily] || selectedFamily;
  const selectedCount = [...selectedAssetIds].filter((id) => selectableFiles.some((file) => file.file_id === id)).length;
  const allSelected = selectableFiles.length > 0 && selectedCount === selectableFiles.length;
  const partiallySelected = selectedCount > 0 && !allSelected;

  useEffect(() => {
    if (!readOnly) void fetchInputFiles();
  }, [fetchInputFiles, readOnly]);

  useEffect(() => {
    setSelectedAssetIds(new Set());
    setSelectionMode(false);
    selectionAnchorIndexRef.current = null;
    setDeletePreview(null);
  }, [selectedFamily]);

  useEffect(() => {
    if (focusedAssetId) setSelectedFileId(focusedAssetId);
  }, [focusedAssetId]);

  useEffect(() => {
    const liveIds = new Set(familyFiles.map((file) => file.file_id));
    if (selectedFileId && !liveIds.has(selectedFileId) && focusedAssetId !== selectedFileId) {
      setSelectedFileId(null);
    }
    setSelectedAssetIds((current) => new Set([...current].filter((id) => liveIds.has(id))));
  }, [familyFiles, selectedFileId, focusedAssetId]);

  useEffect(() => {
    if (!selectionMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setSelectionMode(false);
        setSelectedAssetIds(new Set());
        selectionAnchorIndexRef.current = null;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectionMode]);

  const toggleSelected = useCallback((fileId: string) => {
    setSelectedAssetIds((current) => {
      const next = new Set(current);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  }, []);

  const handleSelectionClick = useCallback(
    (fileId: string, index: number, modifiers: SelectionClickModifiers, orderedFiles: InputFile[]) => {
      const target = orderedFiles[index];
      if (!target || target.file_id !== fileId || !isSelectableFile(target)) return;

      const additive = modifiers.ctrlKey || modifiers.metaKey;

      if (modifiers.shiftKey) {
        const anchor = selectionAnchorIndexRef.current ?? index;
        const from = Math.min(anchor, index);
        const to = Math.max(anchor, index);
        const rangeIds = orderedFiles
          .slice(from, to + 1)
          .filter((file) => isSelectableFile(file))
          .map((file) => file.file_id);
        setSelectedAssetIds((current) => {
          if (additive) {
            const next = new Set(current);
            for (const id of rangeIds) next.add(id);
            return next;
          }
          return new Set(rangeIds);
        });
        return;
      }

      setSelectedAssetIds((current) => {
        const next = new Set(current);
        if (next.has(fileId)) next.delete(fileId);
        else next.add(fileId);
        return next;
      });
      selectionAnchorIndexRef.current = index;
    },
    [],
  );

  const exitSelection = useCallback(() => {
    setSelectionMode(false);
    setSelectedAssetIds(new Set());
    selectionAnchorIndexRef.current = null;
  }, []);

  const reviewDelete = async () => {
    const ids = [...selectedAssetIds].filter((id) => selectableFiles.some((file) => file.file_id === id));
    if (!ids.length) return;
    try {
      setDeletePreview(await previewInputDeletion(ids));
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "无法获取删除影响" });
    }
  };

  const confirmDelete = async () => {
    if (!deletePreview) return;
    setDeleting(true);
    try {
      const result = await deleteInputFiles(deletePreview.asset_ids);
      setSelectedFileId((current) => (current && result.deleted_ids.includes(current) ? null : current));
      setDeletePreview(null);
      exitSelection();
      addToast({
        type: "success",
        message: `已删除 ${result.deleted_ids.length} 个文件，解除 ${result.detached_binding_count} 处草稿绑定，取消 ${result.cancelled_queue_item_ids.length} 个等待任务。`,
      });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "删除文件失败" });
      setDeletePreview(null);
      await fetchInputFiles();
    } finally {
      setDeleting(false);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length || readOnly || isAll) return [];
    try {
      const uploaded = await uploadInputs(selectedFamily, files);
      addToast({ type: "success", message: `${uploaded.length} 个${familyLabel}资产已收录` });
      return uploaded;
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "输入文件上传失败" });
      return [];
    }
  };

  const selectFile = (file: InputFile, onFocusLayer?: (id: string) => void) => {
    setSelectedFileId(file.file_id);
    onFocusLayer?.(file.file_id);
  };

  return {
    familyFiles,
    selectableFiles,
    readyCount,
    familyLabel,
    isAll,
    layerVisibility,
    selectedFileId,
    setSelectedFileId,
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
    addToast,
    readOnly,
  };
}
