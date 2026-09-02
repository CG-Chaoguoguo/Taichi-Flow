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

const statusMap: Record<StatusVariant, { label: string }> = {
  draft: { label: "草稿" },
  ready: { label: "待模拟" },
  queued: { label: "排队中" },
  running: { label: "运行中" },
  completed: { label: "已完成" },
  failed: { label: "失败" },
  stopped: { label: "已停止" },
  archived: { label: "已归档" },
  waiting: { label: "等待中" },
  canceled: { label: "已取消" },
  interrupted: { label: "中断" },
  starting: { label: "Starting" },
  cancelled: { label: "Cancelled" },
  stopping: { label: "Stopping" },
  info: { label: "信息" },
  warning: { label: "警告" },
  success: { label: "成功" },
  error: { label: "错误" },
  neutral: { label: "" },
};

interface StatusBadgeProps {
  variant: StatusVariant;
  children?: ReactNode;
  dot?: boolean;
  className?: string;
  ariaLabel?: string;
}

export function StatusBadge({ variant, children, dot = false, className = "", ariaLabel }: StatusBadgeProps) {
  const { label } = statusMap[variant] || statusMap.neutral;
  const classes = ["tf-status-badge", variant === "running" ? "running" : "", className].filter(Boolean).join(" ");

  return (
    <span className={classes} aria-label={ariaLabel || label} title={ariaLabel || label}>
      {dot && <span className={`tf-status-dot tf-status-dot--${variant}`} />}
      {children || label}
    </span>
  );
}
