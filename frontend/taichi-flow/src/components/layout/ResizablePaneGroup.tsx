import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import {
  Group,
  Panel,
  Separator,
  useGroupRef,
  usePanelRef,
  type GroupImperativeHandle,
  type Layout,
  type LayoutChangedMeta,
  type PanelSize,
} from "react-resizable-panels";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import { IconButton } from "../IconButton";

export type PaneOrientation = "horizontal" | "vertical";

type PaneGroupContextValue = {
  groupRef: React.RefObject<GroupImperativeHandle | null>;
  elementRef: React.RefObject<HTMLDivElement | null>;
  orientation: PaneOrientation;
  markUserInteraction: () => void;
};

const PaneGroupContext = createContext<PaneGroupContextValue | null>(null);

export type ResizablePaneGroupProps = {
  id: string;
  orientation: PaneOrientation;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  onLayoutChanged?: (layout: Layout, meta: LayoutChangedMeta, groupSizePx: number) => void;
};

export function ResizablePaneGroup({ id, orientation, children, className = "", style, onLayoutChanged }: ResizablePaneGroupProps) {
  const groupRef = useGroupRef();
  const elementRef = useRef<HTMLDivElement | null>(null);
  const explicitInteractionRef = useRef(false);
  const markUserInteraction = useCallback(() => {
    explicitInteractionRef.current = true;
  }, []);

  const handleLayoutChanged = useCallback((layout: Layout, meta: LayoutChangedMeta) => {
    const explicitlyTriggered = explicitInteractionRef.current;
    explicitInteractionRef.current = false;
    const resolvedMeta = explicitlyTriggered && !meta.isUserInteraction
      ? { ...meta, isUserInteraction: true }
      : meta;
    const groupSizePx = elementRef.current
      ? orientation === "horizontal" ? elementRef.current.clientWidth : elementRef.current.clientHeight
      : 0;
    onLayoutChanged?.(layout, resolvedMeta, groupSizePx);
  }, [onLayoutChanged, orientation]);

  const contextValue = useMemo<PaneGroupContextValue>(() => ({
    groupRef,
    elementRef,
    orientation,
    markUserInteraction,
  }), [groupRef, orientation, markUserInteraction]);

  return (
    <PaneGroupContext.Provider value={contextValue}>
      <Group
        id={id}
        className={`tf-resizable-group tf-resizable-group--${orientation} ${className}`.trim()}
        orientation={orientation}
        groupRef={groupRef}
        elementRef={elementRef}
        resizeTargetMinimumSize={{ coarse: 20, fine: 10 }}
        onLayoutChanged={handleLayoutChanged}
        style={style}
      >
        {children}
      </Group>
    </PaneGroupContext.Provider>
  );
}

type ResizablePaneProps = {
  id: string;
  children: ReactNode;
  defaultSize?: number | string;
  minSize: number | string;
  maxSize?: number | string;
  collapsed?: boolean;
  forceCollapsed?: boolean;
  collapsedSize?: number | string;
  groupResizeBehavior?: "preserve-relative-size" | "preserve-pixel-size";
  className?: string;
  onSizeChange?: (size: PanelSize) => void;
};

function numericSize(value: number | string, fallback: number) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return fallback;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * A Panel that never auto-collapses while the user is dragging. Its minimum
 * and maximum switch to the rail size only for an explicit or temporary
 * collapse request.
 */
export function ResizablePane({
  id,
  children,
  defaultSize,
  minSize,
  maxSize = "100%",
  collapsed = false,
  forceCollapsed = false,
  collapsedSize = 36,
  groupResizeBehavior = "preserve-relative-size",
  className = "",
  onSizeChange,
}: ResizablePaneProps) {
  const groupContext = useContext(PaneGroupContext);
  const panelRef = usePanelRef();
  const effectiveCollapsed = collapsed || forceCollapsed;
  const previousCollapsedRef = useRef(effectiveCollapsed);
  const previousDefaultSizeRef = useRef<number | string | undefined>(defaultSize);
  const expandedSizeRef = useRef(numericSize(defaultSize ?? minSize, numericSize(minSize, 1)));
  const collapsedPixels = numericSize(collapsedSize, 36);

  const handleResize = useCallback((size: PanelSize) => {
    if (!effectiveCollapsed && size.inPixels > collapsedPixels + 1) {
      expandedSizeRef.current = size.inPixels;
    }
    onSizeChange?.(size);
  }, [collapsedPixels, effectiveCollapsed, onSizeChange]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;

    if (effectiveCollapsed) {
      if (!previousCollapsedRef.current) {
        expandedSizeRef.current = Math.max(expandedSizeRef.current, panel.getSize().inPixels);
      }
      try {
        panel.resize(collapsedSize);
      } catch {
        // A persisted store update can race the Group registration during a
        // remount. The Panel prop still carries the collapsed size safely.
      }
    } else if (previousCollapsedRef.current) {
      try {
        panel.resize(Math.max(expandedSizeRef.current, numericSize(minSize, 1)));
      } catch {
        // See the registration race note above.
      }
    }
    previousCollapsedRef.current = effectiveCollapsed;
  }, [collapsedSize, effectiveCollapsed, minSize, panelRef]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel || previousDefaultSizeRef.current === defaultSize) return;

    const nextSize = defaultSize ?? minSize;
    if (effectiveCollapsed) {
      expandedSizeRef.current = numericSize(nextSize, numericSize(minSize, 1));
    } else {
      try {
        panel.resize(nextSize);
      } catch {
        // The Group will apply the new default while it finishes mounting.
      }
      expandedSizeRef.current = numericSize(nextSize, numericSize(minSize, 1));
    }
    previousDefaultSizeRef.current = defaultSize;
  }, [defaultSize, effectiveCollapsed, minSize, panelRef]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    const groupElement = groupContext?.elementRef.current;
    if (!panel || !groupElement || defaultSize === undefined || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(() => {
      if (effectiveCollapsed) return;
      try {
        panel.resize(defaultSize);
      } catch {
        // The observer can run during a Group remount; its next size change
        // will retry without surfacing an application error.
      }
    });
    observer.observe(groupElement);
    return () => observer.disconnect();
  }, [defaultSize, effectiveCollapsed, groupContext, panelRef]);

  return (
    <Panel
      id={id}
      panelRef={panelRef}
      defaultSize={effectiveCollapsed ? collapsedSize : defaultSize}
      minSize={effectiveCollapsed ? collapsedSize : minSize}
      maxSize={effectiveCollapsed ? collapsedSize : maxSize}
      collapsible={false}
      groupResizeBehavior={groupResizeBehavior}
      onResize={handleResize}
      className={`tf-resizable-pane__content ${className}`.trim()}
      data-pane-id={id}
    >
      {children}
    </Panel>
  );
}

type ResizeHandleProps = {
  id: string;
  leadingPanelId: string;
  label: string;
  leadingMinSize: number;
  leadingMaxSize?: number;
  onToggleCollapse?: () => void;
};

export function ResizeHandle({ id, leadingPanelId, label, leadingMinSize, leadingMaxSize = 10000, onToggleCollapse }: ResizeHandleProps) {
  const context = useContext(PaneGroupContext);
  if (!context) throw new Error("ResizeHandle must be rendered inside ResizablePaneGroup");

  const adjustLeadingPanel = useCallback((targetPixels: number) => {
    const group = context.groupRef.current;
    const element = context.elementRef.current;
    if (!group || !element) return;
    const groupSize = context.orientation === "horizontal" ? element.clientWidth : element.clientHeight;
    if (!groupSize) return;
    const layout = group.getLayout();
    const current = layout[leadingPanelId];
    if (current == null) return;
    const target = Math.min(100, Math.max(0, (targetPixels / groupSize) * 100));
    context.markUserInteraction();
    group.setLayout({ ...layout, [leadingPanelId]: target });
  }, [context, leadingPanelId]);

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const isArrow = event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "ArrowUp" || event.key === "ArrowDown";
    const isBoundary = event.key === "Home" || event.key === "End";
    const isToggle = event.key === "Enter";
    if (!isArrow && !isBoundary && !isToggle) return;

    event.preventDefault();
    event.stopPropagation();
    if (isToggle) {
      context.markUserInteraction();
      onToggleCollapse?.();
      return;
    }

    const group = context.groupRef.current;
    const element = context.elementRef.current;
    if (!group || !element) return;
    const groupSize = context.orientation === "horizontal" ? element.clientWidth : element.clientHeight;
    if (!groupSize) return;
    const layout = group.getLayout();
    const current = layout[leadingPanelId];
    if (current == null) return;

    if (event.key === "Home") {
      adjustLeadingPanel(leadingMinSize);
      return;
    }
    if (event.key === "End") {
      adjustLeadingPanel(leadingMaxSize);
      return;
    }

    const positive = context.orientation === "horizontal"
      ? event.key === "ArrowRight"
      : event.key === "ArrowDown";
    const step = event.shiftKey ? 32 : 8;
    const currentPixels = (current / 100) * groupSize;
    adjustLeadingPanel(currentPixels + (positive ? step : -step));
  }, [adjustLeadingPanel, context, leadingMaxSize, leadingMinSize, leadingPanelId, onToggleCollapse]);

  return (
    <Separator
      id={id}
      className="tf-resize-handle tf-focus-ring"
      aria-label={label}
      title={`${label}；拖动调整，双击重置`}
      onKeyDown={handleKeyDown}
      onDoubleClick={() => context.markUserInteraction()}
    />
  );
}

type PanelDirection = "left" | "right" | "top" | "bottom";

function directionIcon(direction: PanelDirection, collapsed: boolean) {
  if (direction === "left") return collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />;
  if (direction === "right") return collapsed ? <ChevronLeft size={14} /> : <ChevronRight size={14} />;
  if (direction === "top") return collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />;
  return collapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />;
}

export function PanelCollapseButton({
  label,
  collapsed,
  direction,
  onToggle,
}: {
  label: string;
  collapsed: boolean;
  direction: PanelDirection;
  onToggle: () => void;
}) {
  return (
    <IconButton
      size="small"
      className="tf-panel-collapse-button"
      icon={directionIcon(direction, collapsed)}
      label={`${collapsed ? "展开" : "折叠"}${label}`}
      aria-expanded={!collapsed}
      onClick={onToggle}
    />
  );
}

export function CollapsedPaneRail({
  label,
  direction,
  onExpand,
  temporary = false,
}: {
  label: string;
  direction: PanelDirection;
  onExpand?: () => void;
  temporary?: boolean;
}) {
  const collapsed = true;
  return (
    <div className="tf-collapsed-pane-rail">
      <button
        type="button"
        className="tf-collapsed-pane-rail-button tf-focus-ring"
        aria-label={temporary ? `${label}已暂时隐藏` : `展开${label}`}
        title={temporary ? `${label}将在退出焦点模式后恢复` : `展开${label}`}
        disabled={!onExpand}
        onClick={onExpand}
      >
        {directionIcon(direction, collapsed)}
        <span className="tf-sr-only">{temporary ? `${label}已暂时隐藏` : `展开${label}`}</span>
      </button>
    </div>
  );
}
