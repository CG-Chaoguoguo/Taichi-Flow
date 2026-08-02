import type { ReactNode } from "react";

type StatusVariant =
  | "draft"
  | "ready"
  | "queued"
  | "starting"
  | "running"
  | "stopping"
  | "completed"
  | "failed"
  | "stopped"
  | "archived"
  | "waiting"
  | "canceled"
  | "cancelled"
  | "interrupted"
  | "info"
  | "warning"
  | "success"
  | "error"
  | "neutral";

const statusMap: Record<StatusVariant, { label: string; color: string }> = {
  draft: { label: "草稿", color: "var(--color-foreground-tertiary)" },
  ready: { label: "待模拟", color: "var(--color-info)" },
  queued: { label: "排队中", color: "var(--color-info)" },
  running: { label: "运行中", color: "var(--color-brand)" },
  completed: { label: "已完成", color: "var(--color-success)" },
  failed: { label: "失败", color: "var(--color-error)" },
  stopped: { label: "已停止", color: "var(--color-warning)" },
  archived: { label: "已归档", color: "var(--color-foreground-tertiary)" },
  waiting: { label: "等待中", color: "var(--color-info)" },
  canceled: { label: "已取消", color: "var(--color-foreground-tertiary)" },
  interrupted: { label: "中断", color: "var(--color-error)" },
  starting: { label: "Starting", color: "var(--color-info)" },
  cancelled: { label: "Cancelled", color: "var(--color-foreground-tertiary)" },
  stopping: { label: "Stopping", color: "var(--color-warning)" },
  info: { label: "信息", color: "var(--color-info)" },
  warning: { label: "警告", color: "var(--color-warning)" },
  success: { label: "成功", color: "var(--color-success)" },
  error: { label: "错误", color: "var(--color-error)" },
  neutral: { label: "", color: "var(--color-foreground-tertiary)" },
};

interface StatusBadgeProps {
  variant: StatusVariant;
  children?: ReactNode;
  dot?: boolean;
  className?: string;
  ariaLabel?: string;
}

export function StatusBadge({ variant, children, dot = false, className = "", ariaLabel }: StatusBadgeProps) {
  const { label, color } = statusMap[variant] || statusMap.neutral;
  return (
    <span
      className={`tf-status-badge ${className}`}
      aria-label={ariaLabel || label}
      title={ariaLabel || label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        flexShrink: 0,
        whiteSpace: "nowrap",
        gap: "6px",
        padding: "2px 10px",
        borderRadius: "9999px",
        fontSize: "11px",
        fontWeight: 510,
        color: "var(--color-foreground-secondary)",
        backgroundColor: "rgba(255, 255, 255, 0.04)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
      }}
    >
      {dot && (
        <span
          className="tf-status-dot"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: color,
            flexShrink: 0,
          }}
        />
      )}
      {children || label}
    </span>
  );
}
