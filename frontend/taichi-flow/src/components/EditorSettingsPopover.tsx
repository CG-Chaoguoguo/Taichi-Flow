import { useEffect, useRef, useState } from "react";
import { Settings2 } from "lucide-react";
import { IconButton } from "./IconButton";
import { useTaichiFlowStore, type CanvasPreviewMode } from "../stores/taichiFlowStore";

const OPTIONS: { mode: CanvasPreviewMode; label: string; desc: string }[] = [
  { mode: "downsample", label: "栅格预览 · 快速", desc: "降采样（最长边 512px），适合大文件浏览" },
  { mode: "full", label: "栅格预览 · 原始", desc: "尽量全分辨率（超大自动上限保护）" },
];

export function EditorSettingsPopover() {
  const canvasPreviewMode = useTaichiFlowStore((state) => state.canvasPreviewMode);
  const setCanvasPreviewMode = useTaichiFlowStore((state) => state.setCanvasPreviewMode);
  const resetEditorLayout = useTaichiFlowStore((state) => state.resetEditorLayout);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  return (
    <div className="tf-menubar-settings" ref={rootRef}>
      <IconButton
        icon={<Settings2 size={16} />}
        label="画布设置"
        size="small"
        active={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open ? (
        <div className="tf-settings-popover tf-acrylic" role="dialog" aria-label="画布设置">
          <div className="tf-caption tf-font-semibold tf-settings-popover-title tf-text-secondary">画布设置</div>
          <div className="tf-stack-sm">
            {OPTIONS.map((option) => (
              <button
                key={option.mode}
                type="button"
                className={`tf-settings-option${canvasPreviewMode === option.mode ? " is-active" : ""}`}
                onClick={() => {
                  if (canvasPreviewMode === option.mode) {
                    setOpen(false);
                    return;
                  }
                  setCanvasPreviewMode(option.mode);
                  addToast({
                    type: "info",
                    message: option.mode === "downsample" ? "已切换为快速预览" : "已切换为原始预览",
                  });
                  setOpen(false);
                }}
              >
                <div className="tf-body tf-font-medium">{option.label}</div>
                <div className="tf-caption tf-text-tertiary">{option.desc}</div>
              </button>
            ))}
            <button
              type="button"
              className="tf-settings-option"
              onClick={() => {
                resetEditorLayout();
                addToast({ type: "success", message: "已恢复默认工作区布局" });
                setOpen(false);
              }}
            >
              <div className="tf-body tf-font-medium">重置工作区布局</div>
              <div className="tf-caption tf-text-tertiary">恢复方案栏、检视器、底部坞和嵌套分区的默认尺寸</div>
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
