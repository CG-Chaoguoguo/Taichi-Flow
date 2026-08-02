import { useEffect, useRef, useState } from "react";
import { ZoomIn, ZoomOut, Move, Layers, MousePointer2 } from "lucide-react";
import { IconButton } from "../../components/IconButton";
import type { WorkspaceModule } from "./CalculateWorkspace";

interface VisualizationCanvasProps {
  state: { zoom: number; offsetX: number; offsetY: number; selectedLayer: string };
  setState: React.Dispatch<React.SetStateAction<{ zoom: number; offsetX: number; offsetY: number; selectedLayer: string }>>;
  activeModule: WorkspaceModule;
}

export function VisualizationCanvas({ state, setState, activeModule }: VisualizationCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [dragging, setDragging] = useState(false);
  const [probe, setProbe] = useState<{ x: number; y: number; value: string | null } | null>(null);
  const lastPos = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = container.clientWidth * dpr;
    canvas.height = container.clientHeight * dpr;
    canvas.style.width = `${container.clientWidth}px`;
    canvas.style.height = `${container.clientHeight}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 背景
    ctx.fillStyle = getComputedStyle(container).getPropertyValue("--color-surface-secondary") || "#fafafa";
    ctx.fillRect(0, 0, container.clientWidth, container.clientHeight);

    // 网格
    ctx.strokeStyle = getComputedStyle(container).getPropertyValue("--color-border") || "#e0e0e0";
    ctx.lineWidth = 1 / dpr;
    const gridSize = 40;
    for (let x = 0; x < container.clientWidth; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, container.clientHeight);
      ctx.stroke();
    }
    for (let y = 0; y < container.clientHeight; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(container.clientWidth, y);
      ctx.stroke();
    }

    ctx.fillStyle = getComputedStyle(container).getPropertyValue("--color-foreground-tertiary") || "#64748b";
    ctx.font = "13px sans-serif";
    ctx.fillText("选择真实输入或结果文件后显示栅格预览", 24, 28);
  }, [state.zoom, state.offsetX, state.offsetY, activeModule]);

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setState((s) => ({ ...s, zoom: Math.max(0.5, Math.min(5, s.zoom * delta)) }));
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    setDragging(true);
    lastPos.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (dragging) {
      const dx = e.clientX - lastPos.current.x;
      const dy = e.clientY - lastPos.current.y;
      setState((s) => ({ ...s, offsetX: s.offsetX + dx, offsetY: s.offsetY + dy }));
      lastPos.current = { x: e.clientX, y: e.clientY };
    }
  };

  const handleMouseUp = () => setDragging(false);

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left - state.offsetX) / state.zoom;
    const y = (e.clientY - rect.top - state.offsetY) / state.zoom;
    setProbe({ x: Math.round(x), y: Math.round(y), value: null });
  };

  return (
    <div ref={containerRef} style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden" }}>
      <canvas
        ref={canvasRef}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleCanvasClick}
        style={{ display: "block", width: "100%", height: "100%", cursor: dragging ? "grabbing" : "grab" }}
      />

      {/* 画布工具栏 */}
      <div
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          display: "flex",
          gap: 4,
          padding: 4,
          borderRadius: "var(--radius-large)",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          boxShadow: "var(--shadow-floating)",
        }}
      >
        <IconButton icon={<Move size={16} />} label="平移" active={dragging} onClick={() => setDragging((value) => !value)} size="small" />
        <IconButton
          icon={<ZoomIn size={16} />}
          label="放大"
          onClick={() => setState((s) => ({ ...s, zoom: Math.min(5, s.zoom * 1.2) }))}
          size="small"
        />
        <IconButton
          icon={<ZoomOut size={16} />}
          label="缩小"
          onClick={() => setState((s) => ({ ...s, zoom: Math.max(0.5, s.zoom / 1.2) }))}
          size="small"
        />
        <IconButton
          icon={<Layers size={16} />}
          label="重置视图"
          onClick={() => setState({ zoom: 1, offsetX: 0, offsetY: 0, selectedLayer: "" })}
          size="small"
        />
      </div>

      {/* 图例 */}
      <div
        style={{
          position: "absolute",
          bottom: 12,
          left: 12,
          padding: 12,
          borderRadius: "var(--radius-large)",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          boxShadow: "var(--shadow-floating)",
          minWidth: 160,
        }}
      >
        <div className="tf-caption" style={{ fontWeight: 600, marginBottom: 8, color: "var(--color-foreground-secondary)" }}>
          图例
        </div>
        {[
          { color: "#60a5fa", label: "DEM 高程" },
          { color: "#dc2626", label: "边界" },
          { color: "#16a34a", label: "监测点" },
        ].map((item) => (
          <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ width: 12, height: 12, background: item.color, borderRadius: 2 }} />
            <span className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
              {item.label}
            </span>
          </div>
        ))}
      </div>

      {/* 探针 */}
      {probe && (
        <div
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            padding: 12,
            borderRadius: "var(--radius-large)",
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            boxShadow: "var(--shadow-floating)",
            minWidth: 180,
          }}
        >
          <div className="tf-caption" style={{ fontWeight: 600, marginBottom: 8, color: "var(--color-foreground-secondary)" }}>
            数值探针
          </div>
          <div className="tf-mono" style={{ color: "var(--color-foreground-secondary)" }}>
            X: {probe.x}, Y: {probe.y}
          </div>
          <div className="tf-body" style={{ color: "var(--color-foreground)" }}>
            {probe.value}
          </div>
        </div>
      )}

      {/* 模块提示 */}
      <div
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          padding: "6px 12px",
          borderRadius: "var(--radius-large)",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          boxShadow: "var(--shadow-floating)",
        }}
      >
        <span className="tf-caption" style={{ color: "var(--color-foreground-secondary)", display: "flex", alignItems: "center", gap: 6 }}>
          <MousePointer2 size={14} />
          {activeModule === "input" && "输入可视化"}
          {activeModule === "parameter" && "参数编辑"}
          {activeModule === "run" && "运行状态"}
          {activeModule === "result" && "结果浏览"}
        </span>
      </div>
    </div>
  );
}
