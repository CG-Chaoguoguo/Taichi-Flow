import { CircleHelp } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type HelpTipPlacement = "bottom-start" | "bottom-end" | "top-start" | "top-end";

const GAP = 8;
const MAX_WIDTH = 280;
const VIEWPORT_PAD = 8;

function hasHelpContent(content: ReactNode): boolean {
  if (content == null || content === false) return false;
  if (typeof content === "string") return content.trim().length > 0;
  return true;
}

function measurePlacement(
  trigger: DOMRect,
  bubble: { width: number; height: number },
  preferred: HelpTipPlacement,
) {
  const spaceBelow = window.innerHeight - trigger.bottom - VIEWPORT_PAD;
  const spaceAbove = trigger.top - VIEWPORT_PAD;
  let vertical: "top" | "bottom" = preferred.startsWith("top") ? "top" : "bottom";
  if (vertical === "bottom" && spaceBelow < bubble.height && spaceAbove > spaceBelow) vertical = "top";
  if (vertical === "top" && spaceAbove < bubble.height && spaceBelow > spaceAbove) vertical = "bottom";

  const width = bubble.width || MAX_WIDTH;
  let left = preferred.endsWith("end") ? trigger.right - width : trigger.left;
  if (left < VIEWPORT_PAD) left = VIEWPORT_PAD;
  if (left + width > window.innerWidth - VIEWPORT_PAD) {
    left = Math.max(VIEWPORT_PAD, window.innerWidth - VIEWPORT_PAD - width);
  }
  const top = vertical === "bottom" ? trigger.bottom + GAP : trigger.top - GAP - (bubble.height || 0);
  return { top: Math.max(VIEWPORT_PAD, top), left };
}

export function HelpTip({
  content,
  label = "说明",
  size = 14,
  placement = "bottom-start",
}: {
  content: ReactNode;
  label?: string;
  size?: number;
  placement?: HelpTipPlacement;
}) {
  const tipId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    const bubble = bubbleRef.current;
    if (!trigger || !bubble) return;
    const rect = trigger.getBoundingClientRect();
    const size = bubble.getBoundingClientRect();
    setCoords(measurePlacement(rect, { width: size.width, height: size.height }, placement));
  }, [placement]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  }, [open, updatePosition, content]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.blur();
    };
    const onReposition = () => updatePosition();
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onReposition, true);
    window.addEventListener("resize", onReposition);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onReposition, true);
      window.removeEventListener("resize", onReposition);
    };
  }, [open, updatePosition]);

  if (!hasHelpContent(content)) return null;

  return (
    <span
      className={`tf-help-tip${open ? " is-open" : ""}`}
      data-testid="help-tip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={triggerRef}
        type="button"
        className="tf-help-tip-trigger tf-focus-ring"
        aria-label={label}
        aria-describedby={open ? tipId : undefined}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <CircleHelp size={size} aria-hidden="true" />
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <span
              ref={bubbleRef}
              id={tipId}
              role="tooltip"
              className="tf-help-tip-bubble"
              style={coords ? { top: coords.top, left: coords.left } : { visibility: "hidden", top: 0, left: 0 }}
            >
              {content}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}
